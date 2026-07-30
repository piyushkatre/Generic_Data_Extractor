"""
Tests for the pure logic in app/ui/_dataset_preview.py - the parts that
don't require a live Streamlit script-run context (get_latest_save_info(),
_load_dataframe(), _mime_type()). render_extraction_result() itself (the
st.* rendering) is covered by the project's headless-browser smoke tests,
matching how other app/ui/*.py logic is tested in this project.
"""

import csv
import os
from types import SimpleNamespace

import pandas as pd
import pytest

from app.ui._dataset_preview import get_latest_save_info, _load_dataframe, _mime_type


def _job(stage_log):
    return SimpleNamespace(stage_log=stage_log)


# ---------------------------------------------------------------------
# get_latest_save_info()
# ---------------------------------------------------------------------

def test_get_latest_save_info_no_stage_log():
    assert get_latest_save_info(_job([])) is None
    assert get_latest_save_info(_job(None)) is None


def test_get_latest_save_info_no_successful_entries():
    job = _job([
        {"status": "failed", "url": "https://a.com", "error": "boom"},
    ])
    assert get_latest_save_info(job) is None


def test_get_latest_save_info_ignores_success_entries_without_output_path():
    """A success entry whose save_info has no output_path (e.g. a
    MappingResult bypass path, or an older job run before this field
    existed) must not be returned as if it were usable."""
    job = _job([
        {"status": "success", "save_info": {"status": "Success", "operation": "Inserted"}},
    ])
    assert get_latest_save_info(job) is None


def test_get_latest_save_info_returns_the_last_successful_one():
    """Batch job: multiple URLs share the same output file, so the LAST
    successful entry's save_info reflects the complete, fully-accumulated
    dataset - this is what makes a batch job's preview show everything
    without any special-case aggregation."""
    job = _job([
        {"status": "success", "save_info": {"output_path": "/tmp/a.csv", "records_written": 1}},
        {"status": "failed", "save_info": None},
        {"status": "success", "save_info": {"output_path": "/tmp/a.csv", "records_written": 3}},
    ])
    result = get_latest_save_info(job)
    assert result == {"output_path": "/tmp/a.csv", "records_written": 3}


# ---------------------------------------------------------------------
# _load_dataframe() / _mime_type()
# ---------------------------------------------------------------------

def test_load_dataframe_csv(tmp_path):
    path = tmp_path / "out.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Franchise Name", "Investment Required"])
        writer.writerow(["Cult Fit", "Rs. 30 Lakhs"])

    df = _load_dataframe(str(path), "csv", None)
    assert list(df.columns) == ["Franchise Name", "Investment Required"]
    assert len(df) == 1
    assert df.iloc[0]["Franchise Name"] == "Cult Fit"


def test_load_dataframe_infers_csv_from_extension_when_format_missing(tmp_path):
    path = tmp_path / "out.csv"
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["A"])
        writer.writerow(["1"])

    df = _load_dataframe(str(path), "", None)
    assert list(df.columns) == ["A"]


def test_load_dataframe_excel(tmp_path):
    pytest.importorskip("openpyxl")
    path = tmp_path / "out.xlsx"
    df_in = pd.DataFrame([{"Franchise Name": "Cult Fit"}])
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df_in.to_excel(writer, sheet_name="Franchise Data", index=False)

    df = _load_dataframe(str(path), "excel", "Franchise Data")
    assert list(df.columns) == ["Franchise Name"]
    assert df.iloc[0]["Franchise Name"] == "Cult Fit"


def test_mime_type():
    assert _mime_type("csv") == "text/csv"
    assert _mime_type("CSV") == "text/csv"
    assert _mime_type("excel") != "text/csv"
    assert _mime_type("") != "text/csv"
