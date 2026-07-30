"""
Job Runner - the primary page. Workflow: Select Configuration -> Select
Schema -> Enter URLs -> Run.

Only collects input, does light UI-level presence/shape checks (non-empty
name, at least one URL, a config and schema chosen), and delegates
everything else to JobService.create_job() / the background runner in
_job_runtime.py (which itself only calls JobService.run()). No retry/
concurrency/validation policy lives here.
"""

from __future__ import annotations

from datetime import datetime
from typing import List

import streamlit as st

from app.ui._services import get_config_service, get_schema_service, get_job_service
from app.ui._errors import safe_call
from app.ui import _job_runtime

st.set_page_config(page_title="Job Runner", page_icon="🚀", layout="wide")
st.title("🚀 New Extraction Job")

config_service = get_config_service()
schema_service = get_schema_service()
job_service = get_job_service()

configs = config_service.list()
schemas = schema_service.list()

if not configs or not schemas:
    st.warning(
        "You need at least one Website Configuration and one Extraction Schema before running a job."
    )
    c1, c2 = st.columns(2)
    if not configs:
        c1.page_link("ui/config_manager.py", label="➕ Create a Website Configuration")
    if not schemas:
        c2.page_link("ui/schema_manager.py", label="➕ Create an Extraction Schema")
    st.stop()

st.markdown("### 1. Select Configuration")
config_options = {f"{c['name']} ({c['domain']})": c["id"] for c in configs}
config_label = st.selectbox("Website Configuration*", list(config_options.keys()))
config_id = config_options[config_label]

st.markdown("### 2. Select Schema")
schema_options = {f"{s['name']} ({s['field_count']} fields)": s["id"] for s in schemas}
schema_label = st.selectbox("Extraction Schema*", list(schema_options.keys()))
schema_id = schema_options[schema_label]

st.markdown("### 3. Enter URLs")
url_mode = st.radio("Input method", ["Single URL", "Multiple URLs", "Upload TXT file"], horizontal=True)

urls: List[str] = []
if url_mode == "Single URL":
    single = st.text_input("URL", placeholder="https://example.com/page")
    if single.strip():
        urls = [single.strip()]
elif url_mode == "Multiple URLs":
    multi = st.text_area("URLs (one per line)", height=180, placeholder="https://example.com/a\nhttps://example.com/b")
    urls = [u.strip() for u in multi.splitlines() if u.strip()]
else:
    uploaded = st.file_uploader("Upload a .txt file with one URL per line", type=["txt"])
    if uploaded is not None:
        content = uploaded.read().decode("utf-8", errors="ignore")
        urls = [u.strip() for u in content.splitlines() if u.strip()]

if urls:
    st.caption(f"{len(urls)} URL(s) ready.")
    with st.expander("Preview URLs"):
        st.write(urls)

st.markdown("### 4. Job Details")
default_name = f"Job - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
job_name = st.text_input("Job Name*", value=default_name)
max_concurrency = st.slider("Max Concurrency", min_value=1, max_value=10, value=2,
                             help="How many URLs to process in parallel.")

st.markdown("### 5. Output Format")
output_format_label = st.radio(
    "Output Format", ["CSV", "Excel"], horizontal=True,
    help="Format for the generated dataset file.",
)
output_format = output_format_label.strip().lower()

st.divider()
v1, v2 = st.columns(2)
validate_clicked = v1.button("✅ Validate", use_container_width=True)
start_clicked = v2.button("▶️ Start Job", use_container_width=True, type="primary")

if validate_clicked:
    problems = []
    if not job_name.strip():
        problems.append("Job name is required.")
    if not urls:
        problems.append("At least one URL is required.")
    if problems:
        st.error("**Validation Error**\n\n" + "\n".join(f"- {p}" for p in problems))
    else:
        st.success(f"✅ Looks good — {len(urls)} URL(s), configuration '{config_label}', schema '{schema_label}'.")

if start_clicked:
    problems = []
    if not job_name.strip():
        problems.append("Job name is required.")
    if not urls:
        problems.append("At least one URL is required.")
    if problems:
        st.error("**Validation Error**\n\n" + "\n".join(f"- {p}" for p in problems))
    else:
        ok, job = safe_call(
            job_service.create_job,
            name=job_name.strip(), urls=urls, config_id=config_id, schema_id=schema_id,
            output_format=output_format,
        )
        if ok:
            _job_runtime.start_job(job_service, job.id, max_concurrency=max_concurrency)
            st.session_state["job_monitor_job_id"] = job.id
            st.success(f"✅ Job '{job.name}' started.")
            st.switch_page("ui/job_monitor.py")
