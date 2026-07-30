"""
Shared service instances for the Streamlit UI.

The three services (ConfigService/SchemaService/JobService) are the ONLY
backend interfaces any page in app/ui/ is allowed to call - never
ConfigStore/SchemaStore/JobStore directly. Cached via st.cache_resource so
every page (and every script rerun) shares the exact same instances: this
matters most for JobService, whose in-memory `_cancel_events` need to be
visible to a Cancel button click regardless of which page/rerun issues it.
"""

from __future__ import annotations

import streamlit as st

from services.config_service import ConfigService
from services.schema_service import SchemaService
from services.job_service import JobService


@st.cache_resource
def get_config_service() -> ConfigService:
    return ConfigService()


@st.cache_resource
def get_schema_service() -> SchemaService:
    return SchemaService()


@st.cache_resource
def get_job_service() -> JobService:
    return JobService()
