"""
Shared "extraction result" UI block: completion summary, dataframe
preview, and download button - all sourced from the exact file
DatasetWriter wrote. The path/format/row-count come from
save_info["output_path"/"output_format"/"records_written"/"sheet_name"],
set by DatasetBuilder.save_extraction_result() (modules/dataset_builder/builder.py)
via writers.DatasetWriter.finish() (writers/dataset_writer.py) and
propagated, unchanged, through core/pipeline.py's return value into
ExtractionJob.stage_log[i]["save_info"]. This module never searches
datasets_dir and never re-derives a path - it only reads the file the
pipeline already reported.

The preview dataframe and the download button read the SAME file: the
dataframe via pandas (for display), the download via raw file bytes (so
what's downloaded is byte-identical to what's on disk, not a pandas
round-trip reconstruction that could reformat/re-quote values).

Used by app/ui/job_monitor.py (right after a job finishes) and
app/ui/job_history.py (viewing a past job).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st


def get_latest_save_info(job: Any) -> Optional[Dict[str, Any]]:
    """
    Finds the most recent successful save_info in a job's stage_log. All
    URLs in one job share the same config/schema, so they write to the
    same output file - the last successful entry's save_info therefore
    reflects the complete, fully-accumulated dataset for a batch job, not
    just the last URL's own row.
    """
    for entry in reversed(job.stage_log or []):
        if entry.get("status") == "success" and (entry.get("save_info") or {}).get("output_path"):
            return entry["save_info"]
    return None


def _load_dataframe(output_path: str, output_format: str, sheet_name: Optional[str]) -> pd.DataFrame:
    fmt = (output_format or "").strip().lower()
    if not fmt:
        fmt = "csv" if output_path.lower().endswith(".csv") else "excel"
    if fmt == "csv":
        return pd.read_csv(output_path)
    return pd.read_excel(output_path, sheet_name=sheet_name or 0)


def _mime_type(output_format: str) -> str:
    if (output_format or "").strip().lower() == "csv":
        return "text/csv"
    return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render_extraction_result(save_info: Optional[Dict[str, Any]], key_prefix: str = "extraction_result") -> None:
    """
    Renders the post-extraction block. `save_info` is whatever
    DatasetBuilder.save_extraction_result() returned for the most recent
    successful URL in a job (see get_latest_save_info()). Renders nothing
    if there's no output_path to show (e.g. every URL in the job failed
    before reaching the write stage) - callers decide whether to show a
    fallback message for that case.
    """
    if not save_info or not save_info.get("output_path"):
        return

    output_path = save_info["output_path"]
    output_format = save_info.get("output_format") or ("csv" if output_path.lower().endswith(".csv") else "excel")
    sheet_name = save_info.get("sheet_name")

    if not os.path.exists(output_path):
        st.warning(f"Output file not found: `{output_path}` (it may have been moved or deleted since this job ran).")
        return

    try:
        df = _load_dataframe(output_path, output_format, sheet_name)
    except Exception as e:
        st.error(f"**Could not read output file**\n\n{e}")
        return

    st.success("✅ Extraction Completed")
    c1, c2 = st.columns(2)
    c1.metric("Records written", len(df))
    c2.metric("Output format", output_format.upper())

    if len(df) == 0:
        st.info("No records were extracted.")
        return

    st.dataframe(df, use_container_width=True)

    with open(output_path, "rb") as f:
        file_bytes = f.read()

    st.download_button(
        "⬇️ Download dataset",
        data=file_bytes,
        file_name=os.path.basename(output_path),
        mime=_mime_type(output_format),
        key=f"{key_prefix}_download",
        use_container_width=True,
    )
