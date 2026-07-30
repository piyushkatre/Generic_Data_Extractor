"""
Job History - table of every job, with View/Rerun actions, via
JobService.list()/.get()/.rerun() only.

There is no JobService.delete() (JobStore intentionally has no deletion -
job history is meant to persist as a durable record), so a "Delete" action
is deliberately not offered here rather than adding a new service method
for it.
"""

from __future__ import annotations

import streamlit as st

from app.ui._services import get_job_service
from app.ui._errors import safe_call
from app.ui import _job_runtime
from app.ui._dataset_preview import get_latest_save_info, render_extraction_result

st.set_page_config(page_title="Job History", page_icon="🗂️", layout="wide")
st.title("🗂️ Job History")
st.caption("Job records persist permanently - there is no delete action, by design.")

job_service = get_job_service()

jobs = job_service.list()
if not jobs:
    st.info("No jobs yet.")
    st.page_link("ui/job_runner.py", label="🚀 Go to Job Runner")
    st.stop()


def _duration_for(job_id: str) -> str:
    ok, job = safe_call(job_service.get, job_id)
    if not ok:
        return "—"
    total = job.run_metrics.get("total_time_seconds") if job.run_metrics else None
    if total is None and job.stage_log:
        durations = [e.get("duration") for e in job.stage_log if e.get("duration") is not None]
        total = sum(durations) if durations else None
    return f"{total:.2f}s" if total is not None else "—"


def _output_for(job_id: str) -> str:
    ok, job = safe_call(job_service.get, job_id)
    if not ok or not job.stage_log:
        return "—"
    names = {
        (e.get("save_info") or {}).get("workbook_name")
        for e in job.stage_log
        if e.get("status") == "success" and e.get("save_info")
    }
    names.discard(None)
    return ", ".join(sorted(names)) if names else "—"


rows_sorted = sorted(jobs, key=lambda j: j.get("created_at") or "", reverse=True)

st.dataframe(
    [
        {
            "Job Name": j["name"],
            "Created": j.get("created_at", ""),
            "Status": j["status"].upper(),
            "Duration": _duration_for(j["id"]),
            "URLs": j["url_count"],
            "Output": _output_for(j["id"]),
        }
        for j in rows_sorted
    ],
    use_container_width=True,
    hide_index=True,
)

st.markdown("#### Manage a job")
options = {f"{j['name']} — {j['status'].upper()} ({j['id']})": j["id"] for j in rows_sorted}
selected_label = st.selectbox("Select a job", list(options.keys()))
selected_id = options[selected_label]

ok, selected_job = safe_call(job_service.get, selected_id)

a1, a2 = st.columns(2)
if a1.button("👁️ View / Monitor", use_container_width=True):
    st.session_state["job_monitor_job_id"] = selected_id
    st.switch_page("ui/job_monitor.py")

rerun_disabled = ok and _job_runtime.is_running(selected_id)
if a2.button("🔁 Rerun", use_container_width=True, disabled=rerun_disabled):
    _job_runtime.start_rerun(job_service, selected_id)
    st.session_state["job_monitor_job_id"] = selected_id
    st.success("✅ Rerun started.")
    st.switch_page("ui/job_monitor.py")

if ok and selected_job:
    with st.expander("Details"):
        st.write(f"**Status:** {selected_job.status.value.upper()}")
        st.write(f"**Created:** {selected_job.created_at}")
        st.write(f"**URLs ({len(selected_job.urls)}):**")
        st.write(selected_job.urls)
        if selected_job.error:
            st.error(f"**Job Error**\n\n{selected_job.error}")

    if selected_job.status.is_terminal:
        latest_save_info = get_latest_save_info(selected_job)
        if latest_save_info:
            output_format = (latest_save_info.get("output_format") or "excel").upper()
            st.write(f"**Output Format:** {output_format}")
            st.markdown("#### Extracted Dataset")
            render_extraction_result(latest_save_info, key_prefix=f"job_history_{selected_id}")
        elif selected_job.stage_log:
            st.info("No records were extracted.")
