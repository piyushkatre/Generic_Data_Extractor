"""
JobStore
========
Save/load/list ExtractionJob records - job history. A stored job embeds its
own WebsiteConfig/ExtractionSchema inline (via ExtractionJob.to_dict()/
from_dict()) rather than referencing ConfigStore/SchemaStore ids: a job
record reflects exactly what it ran with, even if the underlying saved
config/schema is edited afterwards. No deletion by design - job history is
meant to persist; no versioning either (a job doesn't get re-versioned, a
new run is a new job).
"""

from __future__ import annotations

from typing import Any, Dict, List

from config._file_store import JsonFileStore
from config.extraction_job import ExtractionJob


class JobStore:
    def __init__(self, storage_dir: str = "storage/jobs"):
        self._store = JsonFileStore(
            storage_dir,
            to_dict=lambda job: job.to_dict(),
            from_dict=lambda d: ExtractionJob.from_dict(d),
        )

    def save(self, job: ExtractionJob) -> str:
        """Saves (or overwrites) the job under its own id - call again after
        execute_job() completes to persist the final status/stage_log."""
        return self._store.save(job.id, job)

    def load(self, job_id: str) -> ExtractionJob:
        return self._store.load(job_id)

    def exists(self, job_id: str) -> bool:
        return self._store.exists(job_id)

    def list(self) -> List[Dict[str, Any]]:
        """Cheap listing: id + name + status + url count for every job."""
        summaries = []
        for job_id in self._store.list_ids():
            raw = self._store.load_raw(job_id)
            summaries.append({
                "id": job_id,
                "name": raw.get("name", "Untitled Job"),
                "status": raw.get("status", "pending"),
                "created_at": raw.get("created_at"),
                "url_count": len(raw.get("urls", [])),
            })
        return summaries
