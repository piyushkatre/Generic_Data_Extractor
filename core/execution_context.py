"""
ExecutionContext
================
The single, immutable source of truth for one job's execution: which Job,
which RuntimeAdapter (and therefore which WebsiteConfig and
ExtractionSchema - exposed as read-only properties, never stored as
separate fields, so they can never drift out of sync with the adapter),
and - once a specific URL is being run - that URL's PipelineContext.

Created exactly once per job, by JobService.run(); every lower layer
(execute_job, ExtractionPipeline, and everything ExtractionPipeline calls)
receives this same object rather than being handed the RuntimeAdapter/
WebsiteConfig/ExtractionSchema separately - so there is no code path where a
stage can reload or substitute a different schema/config than the one the
job was actually created with.

This is the fix behind the DatasetBuilder.save_extraction_result() bug the
end-to-end integration test caught (see tests/test_end_to_end_workflow.py):
that bug was possible only because the Excel-writing stage had its own way
to re-derive a schema instead of being handed the one already in use.
ExecutionContext doesn't remove that particular re-derivation path by
itself (core/pipeline.py still passes `schema=` explicitly for that one
call) - it exists so *future* stages have no need to invent one, because
the correct schema/config/job is always one attribute away on whatever
context object they were already given.

Deliberately extensible: a tracing id, auth/user identity, or a quota
budget can be added as a new field here later without touching every
method signature between JobService and ExtractionPipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Optional

from config.extraction_job import ExtractionJob
from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from core.runtime_adapter import RuntimeAdapter
from core.pipeline_context import PipelineContext


@dataclass(frozen=True)
class ExecutionContext:
    job: ExtractionJob
    runtime_adapter: RuntimeAdapter
    pipeline_context: Optional[PipelineContext] = None

    @property
    def website_config(self) -> WebsiteConfig:
        return self.runtime_adapter.website_config

    @property
    def extraction_schema(self) -> ExtractionSchema:
        return self.runtime_adapter.extraction_schema

    def for_url(
        self,
        url: str,
        progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> "ExecutionContext":
        """
        Returns a new ExecutionContext scoped to one URL's run: a fresh
        PipelineContext, but the exact same `job`/`runtime_adapter` object
        references as `self` - never a re-resolved copy. Safe to call
        repeatedly (e.g. once per URL in a multi-URL job) from the same
        base ExecutionContext.
        """
        pipeline_context = PipelineContext(
            url=url,
            runtime_adapter=self.runtime_adapter,
            job_id=self.job.id,
            progress_callback=progress_callback,
        )
        return replace(self, pipeline_context=pipeline_context)
