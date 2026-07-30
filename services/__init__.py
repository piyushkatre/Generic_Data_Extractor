"""
services package
=================
The stable boundary between a future UI (or any other frontend/API) and the
stores (config/config_store.py, config/schema_store.py, config/job_store.py).
A caller (UI, CLI, another service) is only ever expected to call methods on
ConfigService/SchemaService/JobService - never to open a store directly, and
never to know that "storage" currently means one JSON file per record under
storage/.

Each service owns:
  - validation (delegating to the model's own validate(), but also applying
    service-level rules the model can't check by itself - e.g. duplicate
    names, which requires seeing every other saved record)
  - duplicate detection
  - translating store-level KeyErrors into a clear NotFoundError
  - (JobService only) the job lifecycle and cooperative cancellation
"""

from services.errors import NotFoundError, DuplicateNameError, JobLifecycleError
from services.config_service import ConfigService
from services.schema_service import SchemaService
from services.job_service import JobService

__all__ = [
    "NotFoundError", "DuplicateNameError", "JobLifecycleError",
    "ConfigService", "SchemaService", "JobService",
]
