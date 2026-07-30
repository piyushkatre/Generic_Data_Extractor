"""
JobService
==========
The only thing a UI (or any caller) should ever touch to create, run,
cancel, list, or get ExtractionJob records. Absorbs what a separate
JobRunner class used to do (resolve config/schema, execute, persist) plus:
  - the explicit job lifecycle (config/job_status.py)
  - cooperative cancellation of a running job
  - translating store-level KeyErrors into a clear NotFoundError

Stable public interface: create_job(), run(), cancel(), rerun(), list(), get().
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional

from config.config_store import ConfigStore
from config.schema_store import SchemaStore
from config.job_store import JobStore
from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from config.extraction_job import ExtractionJob
from config.job_status import JobStatus
from core.runtime_adapter import RuntimeAdapter
from core.execution_context import ExecutionContext
from core.job_executor import execute_job
from services.errors import NotFoundError, JobLifecycleError

ProgressCallback = Callable[[str, Dict[str, Any]], None]


class JobService:
    def __init__(
        self,
        config_store: Optional[ConfigStore] = None,
        schema_store: Optional[SchemaStore] = None,
        job_store: Optional[JobStore] = None,
    ):
        self.config_store = config_store or ConfigStore()
        self.schema_store = schema_store or SchemaStore()
        self.job_store = job_store or JobStore()
        # In-memory only: which currently-running jobs (by id) have an
        # active cancellation signal. Lost on process restart, same as any
        # other in-flight execution state - a crashed/restarted process has
        # nothing running to cancel anyway.
        self._cancel_events: Dict[str, asyncio.Event] = {}

    # ------------------------------------------------------------------
    # create_job
    # ------------------------------------------------------------------
    def create_job(
        self,
        name: str,
        urls: List[str],
        config_id: Optional[str] = None,
        schema_id: Optional[str] = None,
        website_config: Optional[WebsiteConfig] = None,
        extraction_schema: Optional[ExtractionSchema] = None,
        output_format: str = "excel",
    ) -> ExtractionJob:
        """
        Creates a job in CREATED status and persists it. Pass either a
        saved config_id/schema_id (resolved via ConfigStore/SchemaStore) or
        a WebsiteConfig/ExtractionSchema object directly for a one-off run.
        `output_format` ("csv"/"excel", case-insensitive) is the UI's Output
        Format selection - stored on the job itself and read back by
        core/pipeline.py's Dataset Generation stage, never via the
        OUTPUT_FORMAT env var. Defaults to "excel" for callers that don't
        pass one (older tests/scripts).
        Raises config.errors.ValidationError if the job's own inputs (name,
        urls, ...) are structurally invalid, or NotFoundError if a given
        config_id/schema_id doesn't exist.
        """
        wc = self._resolve_config(config_id, website_config)
        es = self._resolve_schema(schema_id, extraction_schema)
        job = ExtractionJob(
            name=name, urls=urls, website_config=wc, extraction_schema=es,
            output_format=output_format,
        )
        self.job_store.save(job)
        return job

    def _resolve_config(self, config_id: Optional[str], website_config: Optional[WebsiteConfig]) -> WebsiteConfig:
        if website_config is not None:
            return website_config
        if config_id is not None:
            try:
                return self.config_store.load(config_id)
            except KeyError as e:
                raise NotFoundError(f"No WebsiteConfig found with id '{config_id}'.") from e
        raise ValueError("create_job() requires either config_id or website_config.")

    def _resolve_schema(self, schema_id: Optional[str], extraction_schema: Optional[ExtractionSchema]) -> ExtractionSchema:
        if extraction_schema is not None:
            return extraction_schema
        if schema_id is not None:
            try:
                return self.schema_store.load(schema_id)
            except KeyError as e:
                raise NotFoundError(f"No ExtractionSchema found with id '{schema_id}'.") from e
        raise ValueError("create_job() requires either schema_id or extraction_schema.")

    # ------------------------------------------------------------------
    # run / rerun / cancel
    # ------------------------------------------------------------------
    async def run(
        self,
        job_id: str,
        max_concurrency: int = 2,
        progress_callback: Optional[ProgressCallback] = None,
        schemas_dir: str = "schemas",
        datasets_dir: str = "datasets",
    ) -> ExtractionJob:
        """
        Runs a CREATED (or previously VALIDATING/QUEUED - e.g. left over
        from an interrupted process) job through CREATED -> VALIDATING ->
        QUEUED -> RUNNING -> a terminal status, persisting the job after
        each transition so a crash mid-run leaves a recoverable record.

        `schemas_dir`/`datasets_dir` are forwarded to the pipeline's Excel
        output stage (see docs/ARCHITECTURE_REDESIGN.md - CSV output, with a
        job/site-derived filename, is a later milestone; today's output
        location is still these two directories).

        Raises JobLifecycleError if the job is already RUNNING or already
        terminal (COMPLETED/FAILED/CANCELLED/PARTIAL) - call rerun() if you
        intentionally want to run a finished job again.
        """
        job = self.get(job_id)
        if job.status == JobStatus.RUNNING:
            raise JobLifecycleError(f"Job '{job_id}' is already running.")
        if job.status.is_terminal:
            raise JobLifecycleError(
                f"Job '{job_id}' is already {job.status.value} and cannot be run again via run(). "
                "Call rerun() if you intentionally want to run it again."
            )

        job.mark_validating()
        self.job_store.save(job)
        job.website_config.validate()
        job.extraction_schema.validate()

        job.mark_queued()
        self.job_store.save(job)

        # Built exactly once, here - every stage of every URL in this job
        # receives this same ExecutionContext (or a `.for_url()` derivative
        # sharing the same job/runtime_adapter references), never a
        # separately re-resolved RuntimeAdapter/WebsiteConfig/ExtractionSchema.
        runtime_adapter = RuntimeAdapter.from_config_and_schema(
            job.website_config, job.extraction_schema, name=job.name
        )
        execution_context = ExecutionContext(job=job, runtime_adapter=runtime_adapter)

        cancel_event = asyncio.Event()
        self._cancel_events[job_id] = cancel_event
        try:
            job = await execute_job(
                execution_context, max_concurrency=max_concurrency,
                progress_callback=progress_callback, cancel_event=cancel_event,
                schemas_dir=schemas_dir, datasets_dir=datasets_dir,
            )
        finally:
            self._cancel_events.pop(job_id, None)

        self.job_store.save(job)
        return job

    async def rerun(
        self,
        job_id: str,
        max_concurrency: int = 2,
        progress_callback: Optional[ProgressCallback] = None,
        schemas_dir: str = "schemas",
        datasets_dir: str = "datasets",
    ) -> ExtractionJob:
        """Reruns a job (of any status, including terminal ones) against the
        exact WebsiteConfig/ExtractionSchema it was created with, clearing
        its previous stage_log/run_metrics/error first."""
        job = self.get(job_id)
        if job.status == JobStatus.RUNNING:
            raise JobLifecycleError(f"Job '{job_id}' is already running.")

        job.stage_log = []
        job.run_metrics = {}
        job.error = None
        job.status = JobStatus.CREATED
        self.job_store.save(job)

        return await self.run(
            job_id, max_concurrency=max_concurrency, progress_callback=progress_callback,
            schemas_dir=schemas_dir, datasets_dir=datasets_dir,
        )

    def cancel(self, job_id: str) -> ExtractionJob:
        """
        Requests cancellation of a job. For a currently-running job this
        sets a cooperative signal that execute_job() checks between URLs
        (already-in-flight URLs still complete); for a job that hasn't
        started running yet, it's cancelled immediately. A no-op (returns
        the job unchanged) if the job is already in a terminal status.
        """
        job = self.get(job_id)
        if job.status.is_terminal:
            return job

        cancel_event = self._cancel_events.get(job_id)
        if cancel_event is not None:
            cancel_event.set()
        else:
            job.mark_cancelled()
            self.job_store.save(job)
        return job

    # ------------------------------------------------------------------
    # get / list
    # ------------------------------------------------------------------
    def get(self, job_id: str) -> ExtractionJob:
        try:
            return self.job_store.load(job_id)
        except KeyError as e:
            raise NotFoundError(f"No ExtractionJob found with id '{job_id}'.") from e

    def list(self) -> List[Dict[str, Any]]:
        return self.job_store.list()
