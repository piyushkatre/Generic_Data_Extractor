"""
UI-only glue between JobService's async run()/rerun() and Streamlit's
synchronous, single-threaded-per-script-run execution model.

Streamlit cannot process a new interaction (like a Cancel button click)
while a script run is blocked inside `await job_service.run(...)`, so a job
is instead executed in a background thread; the main (Streamlit) thread
stays free to handle button clicks - including calling
`job_service.cancel(job_id)`, which works because job_service is the same
cached instance both threads share (see _services.py), and because
core.job_executor only ever calls `cancel_event.is_set()` (a plain
attribute read), never `await cancel_event.wait()` - so setting it from
another thread never touches asyncio's cross-thread-unsafe wakeup path.

Progress is kept in a plain, lock-guarded, process-level dict (not
st.session_state, which isn't meant for cross-thread access) that pages
poll when redrawing. This module makes no extraction/validation/lifecycle
decisions - it only decides *when* to call JobService.run()/rerun(), never
what running means.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, Optional

_lock = threading.Lock()
_progress: Dict[str, Dict[str, Any]] = {}
_threads: Dict[str, threading.Thread] = {}


def _make_progress_callback(job_id: str):
    def _callback(url: str, data: Dict[str, Any]) -> None:
        with _lock:
            _progress[job_id] = {"url": url, **data}
    return _callback


def is_running(job_id: str) -> bool:
    with _lock:
        thread = _threads.get(job_id)
    return thread is not None and thread.is_alive()


def get_latest_progress(job_id: str) -> Optional[Dict[str, Any]]:
    with _lock:
        return _progress.get(job_id)


def clear_progress(job_id: str) -> None:
    with _lock:
        _progress.pop(job_id, None)
        _threads.pop(job_id, None)


def _start(job_service, job_id: str, coro_factory, max_concurrency: int) -> None:
    if is_running(job_id):
        return
    clear_progress(job_id)

    def _worker():
        try:
            asyncio.run(coro_factory(_make_progress_callback(job_id)))
        except Exception as e:
            with _lock:
                _progress[job_id] = {**_progress.get(job_id, {}), "thread_error": str(e)}

    thread = threading.Thread(target=_worker, daemon=True)
    with _lock:
        _threads[job_id] = thread
    thread.start()


def start_job(job_service, job_id: str, max_concurrency: int = 2) -> None:
    """Runs job_service.run(job_id, ...) in a background thread."""
    _start(
        job_service, job_id,
        lambda cb: job_service.run(job_id, progress_callback=cb, max_concurrency=max_concurrency),
        max_concurrency,
    )


def start_rerun(job_service, job_id: str, max_concurrency: int = 2) -> None:
    """Runs job_service.rerun(job_id, ...) in a background thread."""
    _start(
        job_service, job_id,
        lambda cb: job_service.rerun(job_id, progress_callback=cb, max_concurrency=max_concurrency),
        max_concurrency,
    )
