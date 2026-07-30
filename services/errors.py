"""
Service-level errors. These wrap store-level failures (a raw KeyError from
a missing file) and add business-rule failures (duplicate names, invalid
lifecycle transitions) that only a service - not a store, and not a model's
own validate() - can know about.
"""

from __future__ import annotations


class NotFoundError(KeyError):
    """Raised when a service is asked for a record id that doesn't exist."""


class DuplicateNameError(ValueError):
    """Raised when creating a new record whose name collides with an existing one."""


class JobLifecycleError(ValueError):
    """Raised when an operation isn't valid for a job's current lifecycle state
    (e.g. running a job that's already running, or already finished)."""
