"""
ExtractionJob
=============
Every extraction becomes an ExtractionJob: a batch of URLs run against one
WebsiteConfig + one ExtractionSchema. This is a pure, in-memory data object;
JobStore persists it and JobService owns its lifecycle (see
services/job_service.py) - core/job_executor.py knows how to actually run
one.

The output filename is derived from the job's own name (falling back to the
website config's name), never from a page-type/domain classification -
per the "CSV filename should be based on the extraction job or website, not
the domain type" requirement.

Lifecycle: see config/job_status.py for the full state diagram.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from config.job_status import JobStatus
from config.errors import ValidationError
from config._util import slugify


@dataclass
class ExtractionJob:
    name: str
    urls: List[str]
    website_config: WebsiteConfig
    extraction_schema: ExtractionSchema
    # Selected in the UI (Job Runner's "Output Format" control), never via
    # the OUTPUT_FORMAT env var - see core/pipeline.py's Dataset Generation
    # stage, which reads this field and hands it to DatasetBuilder. Defaults
    # to "excel" so jobs created before this field existed (or by any
    # caller that doesn't set it) keep their prior behavior.
    output_format: str = "excel"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: JobStatus = JobStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    stage_log: List[Dict[str, Any]] = field(default_factory=list)
    run_metrics: Dict[str, Any] = field(default_factory=dict)
    output_path: Optional[str] = None
    error: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.output_format, str):
            self.output_format = self.output_format.strip().lower()
        if isinstance(self.status, str):
            try:
                self.status = JobStatus(self.status)
            except ValueError:
                raise ValidationError(
                    f"ExtractionJob status must be one of {JobStatus.values()}, got '{self.status}'."
                )
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("ExtractionJob.name must be a non-empty string.")
        if not isinstance(self.urls, list) or not self.urls:
            raise ValidationError(f"ExtractionJob '{self.name}': urls must be a non-empty list of URL strings.")

        bad_urls = [u for u in self.urls if not isinstance(u, str) or not u.strip()]
        if bad_urls:
            raise ValidationError(
                f"ExtractionJob '{self.name}': urls contains {len(bad_urls)} empty or non-string entr"
                f"{'y' if len(bad_urls) == 1 else 'ies'}."
            )

        if not isinstance(self.website_config, WebsiteConfig):
            raise ValidationError(
                f"ExtractionJob '{self.name}': website_config must be a WebsiteConfig instance, "
                f"got {type(self.website_config).__name__}."
            )
        if not isinstance(self.extraction_schema, ExtractionSchema):
            raise ValidationError(
                f"ExtractionJob '{self.name}': extraction_schema must be an ExtractionSchema instance, "
                f"got {type(self.extraction_schema).__name__}."
            )

    # ------------------------------------------------------------------
    # State transitions - see config/job_status.py for the full diagram.
    # ------------------------------------------------------------------
    def mark_validating(self) -> None:
        self.status = JobStatus.VALIDATING

    def mark_queued(self) -> None:
        self.status = JobStatus.QUEUED

    def mark_running(self) -> None:
        self.status = JobStatus.RUNNING

    def mark_completed(self, output_path: Optional[str] = None) -> None:
        self.status = JobStatus.COMPLETED
        if output_path:
            self.output_path = output_path

    def mark_failed(self, error: str) -> None:
        self.status = JobStatus.FAILED
        self.error = error

    def mark_partial(self, error: Optional[str] = None) -> None:
        self.status = JobStatus.PARTIAL
        if error:
            self.error = error

    def mark_cancelled(self) -> None:
        self.status = JobStatus.CANCELLED

    def add_url_result(self, url: str, result: Dict[str, Any]) -> None:
        """Appends one URL's per-run stage log / outcome to the job record."""
        self.stage_log.append({"url": url, **result})

    # ------------------------------------------------------------------
    # Output naming - job/site based, not page-type based
    # ------------------------------------------------------------------
    def generate_output_filename(self, extension: str = "csv") -> str:
        base_name = self.name or self.website_config.name
        return f"{slugify(base_name, fallback='extraction_job')}.{extension.lstrip('.')}"

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "urls": list(self.urls),
            "website_config": self.website_config.to_dict(),
            "extraction_schema": self.extraction_schema.to_dict(),
            "output_format": self.output_format,
            "status": self.status.value,
            "created_at": self.created_at,
            "stage_log": self.stage_log,
            "run_metrics": self.run_metrics,
            "output_path": self.output_path,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionJob":
        """
        Rebuilds an ExtractionJob from its to_dict() output (e.g. loaded
        back from a JobStore). The job's WebsiteConfig/ExtractionSchema are
        embedded inline rather than referenced by id - this is a minimal,
        self-contained job record; a config/schema edited after a job ran
        does not retroactively change that job's own record.
        """
        return cls(
            name=data["name"],
            urls=list(data["urls"]),
            website_config=WebsiteConfig.from_dict(data["website_config"]),
            extraction_schema=ExtractionSchema.from_dict(data["extraction_schema"]),
            output_format=data.get("output_format") or "excel",
            id=data.get("id") or uuid.uuid4().hex,
            status=data.get("status", JobStatus.CREATED.value),
            created_at=data.get("created_at") or datetime.now().isoformat(),
            stage_log=list(data.get("stage_log", [])),
            run_metrics=dict(data.get("run_metrics", {})),
            output_path=data.get("output_path"),
            error=data.get("error"),
        )
