"""
PipelineContext
===============
Lightweight carrier of runtime state through one URL's pass through
ExtractionPipeline. Replaces scattered instance attributes (`self.logs`,
`self.stages`, `self.start_time`) with a single explicit object that is
passed through the pipeline stages, making the pipeline easier to test and
giving ExtractionJob/JobService a clean per-URL state
object to collect once the run is done.

This intentionally does not introduce any persistence - it is a plain,
in-memory object for the duration of a single pipeline run.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional


@dataclass
class PipelineContext:
    url: str
    runtime_adapter: Any
    job_id: Optional[str] = None
    debug_dir: Optional[str] = None
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None

    logs: List[str] = field(default_factory=list)
    stages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    run_metrics: Dict[str, Any] = field(default_factory=dict)
    detected_page_type: Optional[str] = None
    detected_page_type_confidence: Optional[float] = None

    start_time: Optional[float] = None
    end_time: Optional[float] = None

    STAGE_NAMES = (
        "Job Configuration Loaded",
        "Browser Rendering",
        "DOM Cleaning",
        "Structured DOM Creation",
        "Deterministic Extraction",
        "LLM Extraction",
        "Validation",
        "Schema Mapping",
    )

    def __post_init__(self):
        if not self.stages:
            self.stages = {name: {"status": "Pending", "duration": 0.0} for name in self.STAGE_NAMES}

    def start(self) -> None:
        self.start_time = time.time()

    def elapsed(self) -> float:
        if self.start_time is None:
            return 0.0
        return (self.end_time or time.time()) - self.start_time

    def log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.logs.append(f"[{timestamp}] {message}")

    def update_stage(self, stage: str, status: str, duration: float = 0.0) -> None:
        if stage in self.stages:
            self.stages[stage]["status"] = status
            self.stages[stage]["duration"] = duration
        if self.progress_callback:
            self.progress_callback({
                "stages": self.stages,
                "logs": self.logs,
                "total_time": self.elapsed(),
            })

    def set_page_type(self, page_type: str, confidence: float) -> None:
        """Records the (informational-only) page-type detection result.
        Never used to select a schema - just surfaced for display."""
        self.detected_page_type = page_type
        self.detected_page_type_confidence = confidence
