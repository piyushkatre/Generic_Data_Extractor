"""
Job execution
=============
Runs an ExtractionJob: a batch of URLs against one WebsiteConfig + one
ExtractionSchema, through the single ExtractionPipeline execution path.

Takes an ExecutionContext (built once by the caller - JobService.run() -
around the job and its RuntimeAdapter) rather than a bare ExtractionJob, so
there is exactly one RuntimeAdapter construction site for a job's entire
run: this function never builds its own, and neither does anything it
calls. See core/execution_context.py for why that matters.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, Optional

from config.extraction_job import ExtractionJob
from core.execution_context import ExecutionContext
from core.pipeline import ExtractionPipeline


async def execute_job(
    execution_context: ExecutionContext,
    max_concurrency: int = 2,
    progress_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    cancel_event: Optional[asyncio.Event] = None,
    schemas_dir: str = "schemas",
    datasets_dir: str = "datasets",
) -> ExtractionJob:
    """
    Runs every URL in `execution_context.job.urls` through
    ExtractionPipeline, using `execution_context.runtime_adapter` (built
    once by the caller), and records each URL's outcome on the job.

    `progress_callback`, if given, is called as `progress_callback(url, stage_data)`
    for every stage update of every URL - the same shape
    ExtractionPipeline's own progress_callback receives, just tagged with
    which URL it came from so a caller running multiple URLs concurrently
    can tell them apart.

    `cancel_event`, if given, is checked before starting each URL (and again
    right after acquiring the concurrency slot): once set, any URL not yet
    started is skipped and recorded as "cancelled" rather than run, and the
    job's final status is CANCELLED instead of COMPLETED/FAILED/PARTIAL.
    This is cooperative, not preemptive - a URL already mid-render/mid-LLM-call
    when cancellation is requested still runs to completion.
    """
    job = execution_context.job
    job.mark_running()

    semaphore = asyncio.Semaphore(max_concurrency)
    any_failed = False
    any_succeeded = False

    def _cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    async def run_one(url: str) -> None:
        nonlocal any_failed, any_succeeded
        if _cancelled():
            job.add_url_result(url, {"status": "cancelled"})
            return
        async with semaphore:
            if _cancelled():
                job.add_url_result(url, {"status": "cancelled"})
                return
            url_progress_callback = (lambda data, _url=url: progress_callback(_url, data)) if progress_callback else None
            pipeline = ExtractionPipeline(progress_callback=url_progress_callback)
            try:
                pipeline_res = await pipeline.run(
                    url, execution_context=execution_context,
                    schemas_dir=schemas_dir, datasets_dir=datasets_dir,
                )
                any_succeeded = True
                job.add_url_result(url, {
                    "status": "success",
                    "duration": pipeline_res["duration"],
                    "detected_page_type": pipeline_res.get("detected_page_type"),
                    "detected_page_type_confidence": pipeline_res.get("detected_page_type_confidence"),
                    "run_metrics": pipeline_res.get("run_metrics", {}),
                    "save_info": pipeline_res.get("save_info"),
                })
            except Exception as e:
                any_failed = True
                job.add_url_result(url, {"status": "failed", "error": str(e)})

    await asyncio.gather(*(run_one(url) for url in job.urls))

    if _cancelled():
        job.mark_cancelled()
    elif any_failed and any_succeeded:
        job.mark_partial()
    elif any_failed:
        job.mark_failed("One or more URLs failed - see stage_log for details.")
    else:
        job.mark_completed()

    return job
