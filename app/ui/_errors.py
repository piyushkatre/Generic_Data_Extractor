"""
Uniform error display for the UI layer. Every service call a page makes
should go through safe_call() so a ValidationError/NotFoundError/
DuplicateNameError/JobLifecycleError is always rendered the same way -
a clear, titled message, never a raw stack trace.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import streamlit as st

from config.errors import ValidationError
from services.errors import NotFoundError, DuplicateNameError, JobLifecycleError

_TITLES = {
    ValidationError: "Configuration Error",
    NotFoundError: "Not Found",
    DuplicateNameError: "Duplicate Name",
    JobLifecycleError: "Job Error",
}


def safe_call(fn: Callable, *args, **kwargs) -> Tuple[bool, Optional[Any]]:
    """
    Calls fn(*args, **kwargs). Returns (True, result) on success. On any of
    the known backend error types, renders a clean st.error(...) - title
    plus the error's own message, no traceback - and returns (False, None).
    Any other exception is also caught and shown (never left to crash the
    page with a raw traceback), tagged "Unexpected Error".
    """
    try:
        return True, fn(*args, **kwargs)
    except (ValidationError, NotFoundError, DuplicateNameError, JobLifecycleError) as e:
        title = _TITLES.get(type(e), "Error")
        st.error(f"**{title}**\n\n{e}")
    except Exception as e:
        st.error(f"**Unexpected Error**\n\n{e}")
    return False, None
