"""
Multipage Streamlit entry point (Milestone 3).

Wires together the six pages under app/ui/ via st.navigation/st.Page. This
file itself contains no UI logic and does not call st.set_page_config -
each page under app/ui/ configures its own page (title/icon/layout) since
each is its own Streamlit script run.

sys.path is extended here (once, before any page runs) so that every page
can `from app.ui... import ...` / `from services... import ...` /
`from config... import ...` regardless of the working directory Streamlit
was launched from - matching what the previous single-page app.py did.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st

pages = {
    "Overview": [
        st.Page("ui/home.py", title="Dashboard", icon="🧭", default=True),
    ],
    "Manage": [
        st.Page("ui/config_manager.py", title="Website Configurations", icon="⚙️"),
        st.Page("ui/schema_manager.py", title="Extraction Schemas", icon="🧩"),
    ],
    "Jobs": [
        st.Page("ui/job_runner.py", title="New Job", icon="🚀"),
        st.Page("ui/job_monitor.py", title="Job Monitor", icon="📡"),
        st.Page("ui/job_history.py", title="Job History", icon="🗂️"),
    ],
}

nav = st.navigation(pages)
nav.run()
