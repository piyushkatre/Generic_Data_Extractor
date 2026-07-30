"""
Home Dashboard - counts, recent jobs, quick actions.

Pure presentation: everything here is read via ConfigService/SchemaService/
JobService.list() and aggregated in this page. No business logic - the
"how many are running/completed/failed" counts are simple filters over data
the services already return.
"""

import streamlit as st

from app.ui._services import get_config_service, get_schema_service, get_job_service

st.set_page_config(page_title="AI Extractor", page_icon="🧭", layout="wide")

st.title("🧭 AI Extractor — Dashboard")
st.caption("A generic, schema-driven web extraction framework.")

config_service = get_config_service()
schema_service = get_schema_service()
job_service = get_job_service()

configs = config_service.list()
schemas = schema_service.list()
jobs = job_service.list()

running_statuses = {"validating", "queued", "running"}
running_jobs = [j for j in jobs if j["status"] in running_statuses]
completed_jobs = [j for j in jobs if j["status"] == "completed"]
failed_jobs = [j for j in jobs if j["status"] in ("failed", "partial")]

st.markdown("### Overview")
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Website Configurations", len(configs))
col2.metric("Extraction Schemas", len(schemas))
col3.metric("Total Jobs", len(jobs))
col4.metric("Running Jobs", len(running_jobs))
col5.metric("Completed Jobs", len(completed_jobs))
col6.metric("Failed / Partial Jobs", len(failed_jobs))

st.divider()

st.markdown("### Quick Actions")
qa1, qa2, qa3 = st.columns(3)
with qa1:
    if st.button("➕ New Configuration", use_container_width=True):
        st.session_state["cm_request_new"] = True
        st.switch_page("ui/config_manager.py")
with qa2:
    if st.button("➕ New Schema", use_container_width=True):
        st.session_state["sm_request_new"] = True
        st.switch_page("ui/schema_manager.py")
with qa3:
    if st.button("➕ New Job", use_container_width=True):
        st.switch_page("ui/job_runner.py")

st.divider()

st.markdown("### Recent Jobs")
if not jobs:
    st.info("No jobs yet. Create a Website Configuration and Extraction Schema, then start a job.")
else:
    recent = sorted(jobs, key=lambda j: j.get("created_at") or "", reverse=True)[:10]
    st.dataframe(
        [
            {
                "Job Name": j["name"],
                "Status": j["status"].upper(),
                "URLs": j["url_count"],
                "Created": j.get("created_at", ""),
            }
            for j in recent
        ],
        use_container_width=True,
        hide_index=True,
    )
    st.page_link("ui/job_history.py", label="View full Job History →")
