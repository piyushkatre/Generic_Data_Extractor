"""
Job Monitor - live progress for a running job, falling back to the
persisted job record once it's finished.

While a job is running (per app.ui._job_runtime.is_running), progress is
read from the in-memory, lock-guarded dict _job_runtime keeps (fed by the
progress_callback JobService.run() was given) inside an auto-refreshing
st.fragment. Once the job is no longer running, everything shown comes
from JobService.get(job_id) - the persisted ExtractionJob - since that is
the only source of truth after the background thread exits.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import streamlit as st

from app.ui._services import get_job_service
from app.ui._errors import safe_call
from app.ui import _job_runtime
from app.ui._dataset_preview import get_latest_save_info, render_extraction_result

st.set_page_config(page_title="Job Monitor", page_icon="📡", layout="wide")
st.title("📡 Job Monitor")

job_service = get_job_service()

jobs = job_service.list()
if not jobs:
    st.info("No jobs yet. Start one from the Job Runner page.")
    st.page_link("ui/job_runner.py", label="🚀 Go to Job Runner")
    st.stop()

default_job_id = st.session_state.get("job_monitor_job_id")
job_ids = [j["id"] for j in jobs]
if default_job_id not in job_ids:
    default_job_id = job_ids[0]

options = {f"{j['name']} — {j['status'].upper()} ({j['id']})": j["id"] for j in jobs}
default_label = next(k for k, v in options.items() if v == default_job_id)
selected_label = st.selectbox("Job", list(options.keys()), index=list(options.keys()).index(default_label))
job_id = options[selected_label]
st.session_state["job_monitor_job_id"] = job_id

STAGE_ICONS = {"Pending": "⚪", "Running": "🔵", "Completed": "✅", "Failed": "❌"}


def _render_stage_table(stages: Dict[str, Dict[str, Any]]):
    for name, info in stages.items():
        status = info.get("status", "Pending")
        duration = info.get("duration", 0.0)
        icon = STAGE_ICONS.get(status, "⚪")
        c1, c2, c3 = st.columns([3, 1, 1])
        c1.write(f"{icon} {name}")
        c2.write(status)
        c3.write(f"{duration:.2f}s" if duration else "—")


def _render_run_metrics(metrics: Dict[str, Any]):
    if not metrics:
        st.caption("No runtime metrics yet.")
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("HTML Size (raw)", metrics.get("html_size_raw", "—"))
    m2.metric("HTML Size (cleaned)", metrics.get("html_size_cleaned", "—"))
    m3.metric("DOM Reduction %", metrics.get("dom_reduction_pct", "—"))
    m4.metric("DOM Blocks", metrics.get("dom_block_count", "—"))
    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Estimated Prompt Tokens", metrics.get("raw_tokens", "—"))
    m6.metric("Filtered Tokens", metrics.get("filtered_tokens", "—"))
    m7.metric("Completion Tokens", "Not tracked")
    m8.metric("Total Runtime", f"{metrics.get('total_time_seconds', '—')}s" if metrics.get("total_time_seconds") is not None else "—")


def _url_counts(stage_log):
    completed = sum(1 for e in stage_log if e.get("status") == "success")
    failed = sum(1 for e in stage_log if e.get("status") == "failed")
    cancelled = sum(1 for e in stage_log if e.get("status") == "cancelled")
    return completed, failed, cancelled


ok, job = safe_call(job_service.get, job_id)
if not ok:
    st.stop()

top1, top2, top3 = st.columns([2, 1, 1])
top1.subheader(f"{job.name}")
top2.metric("Status", job.status.value.upper() if hasattr(job.status, "value") else str(job.status).upper())
top3.metric("URLs", len(job.urls))

is_live = _job_runtime.is_running(job_id)

btn1, btn2 = st.columns(2)
if btn1.button("🔄 Refresh", use_container_width=True):
    st.rerun()
if btn2.button("🛑 Cancel Job", use_container_width=True, disabled=job.status.is_terminal):
    ok, _ = safe_call(job_service.cancel, job_id)
    if ok:
        st.success("✅ Cancellation requested.")
        st.rerun()

st.divider()


@st.fragment(run_every=2 if is_live else None)
def _live_panel():
    still_running = _job_runtime.is_running(job_id)
    progress = _job_runtime.get_latest_progress(job_id) if still_running else None

    ok_inner, current_job = safe_call(job_service.get, job_id)
    if not ok_inner:
        return

    status_val = current_job.status.value if hasattr(current_job.status, "value") else str(current_job.status)
    st.markdown(f"**Status:** `{status_val.upper()}`" + ("  🔴 live" if still_running else ""))

    completed, failed, cancelled = _url_counts(current_job.stage_log)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Completed URLs", completed)
    c2.metric("Failed URLs", failed)
    c3.metric("Cancelled URLs", cancelled)
    c4.metric("Remaining", max(len(current_job.urls) - completed - failed - cancelled, 0))

    if progress:
        st.caption(f"Current URL: {progress.get('url', '—')}")
        total_stages = len(progress.get("stages", {})) or 1
        done_stages = sum(1 for s in progress.get("stages", {}).values() if s.get("status") == "Completed")
        st.progress(min(done_stages / total_stages, 1.0))
        st.caption(f"Elapsed: {progress.get('total_time', 0.0):.1f}s")

        st.markdown("##### Pipeline Stages (current URL)")
        _render_stage_table(progress.get("stages", {}))

        if progress.get("thread_error"):
            st.error(f"**Job Error**\n\n{progress['thread_error']}")

        with st.expander("Logs"):
            for line in progress.get("logs", [])[-200:]:
                st.text(line)
    elif current_job.stage_log:
        last = current_job.stage_log[-1]
        st.caption(f"Last URL processed: {last.get('url', '—')} — {last.get('status', '—')}")
        run_metrics = last.get("run_metrics", {})
        if run_metrics:
            st.markdown("##### Runtime Metrics (last URL)")
            _render_run_metrics(run_metrics)
        detected = last.get("detected_page_type")
        if detected:
            conf = last.get("detected_page_type_confidence")
            st.caption(f"Detected Page Type: **{detected}**" + (f" (confidence {conf:.0%})" if conf is not None else ""))
    else:
        st.info("Waiting for the job to start producing progress...")

    if current_job.error:
        st.error(f"**Job Error**\n\n{current_job.error}")


_live_panel()

if job.status.is_terminal:
    st.divider()
    st.markdown("### Extracted Dataset")
    latest_save_info = get_latest_save_info(job)
    if latest_save_info:
        render_extraction_result(latest_save_info, key_prefix=f"job_monitor_{job_id}")
    elif job.stage_log:
        st.info("No records were extracted.")

st.divider()
st.markdown("### URL Results")
if not job.stage_log:
    st.caption("No URLs processed yet.")
else:
    st.dataframe(
        [
            {
                "URL": e.get("url", ""),
                "Status": e.get("status", "").upper(),
                "Duration": f"{e.get('duration', 0):.2f}s" if e.get("duration") is not None else "—",
                "Page Type": e.get("detected_page_type") or "—",
                "Output": (e.get("save_info") or {}).get("workbook_name", "—") if e.get("save_info") else ("Error: " + str(e.get("error")) if e.get("error") else "—"),
            }
            for e in job.stage_log
        ],
        use_container_width=True,
        hide_index=True,
    )
