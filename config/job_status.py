r"""
JobStatus
=========
Explicit job lifecycle, defined now so that future execution changes
(background workers, a real queue, retries) don't require touching the
ExtractionJob model - only how a status transition gets triggered:

    CREATED -> VALIDATING -> QUEUED -> RUNNING -> COMPLETED
                                              \-> FAILED
                                              \-> PARTIAL   (some URLs failed, some succeeded)
                                              \-> CANCELLED

CREATED/VALIDATING/QUEUED/CANCELLED are not meaningfully different from each
other today (there is no real queue or worker yet - JobService.run() moves
through them essentially immediately), but the states exist so a caller can
already depend on them.
"""

from __future__ import annotations

from enum import Enum


class JobStatus(str, Enum):
    CREATED = "created"
    VALIDATING = "validating"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PARTIAL = "partial"

    @property
    def is_terminal(self) -> bool:
        return self in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.PARTIAL)

    @classmethod
    def values(cls):
        return [s.value for s in cls]
