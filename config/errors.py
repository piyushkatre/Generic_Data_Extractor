"""
Validation errors for the three runtime input models. A subclass of
ValueError (so existing `except ValueError` call sites still catch it), but
named distinctly so callers that want to handle "this input was invalid" as
its own case (e.g. a UI form, or a service layer) can do so precisely, and
so the message is always actionable - naming exactly which object and which
field is wrong - rather than a raw KeyError/TypeError surfacing from deep
inside a consumer of the (invalid) object.
"""

from __future__ import annotations


class ValidationError(ValueError):
    pass
