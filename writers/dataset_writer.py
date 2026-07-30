"""
DatasetWriter
=============
Format-agnostic sink for one schema-driven dataset. DatasetBuilder talks to
exactly this interface - it never imports openpyxl, never knows about
workbooks/worksheets/rows-vs-lines, and never knows whether a given run
writes .xlsx or .csv. Adding a third output format later means adding a
third DatasetWriter implementation, not touching DatasetBuilder.

A writer's four calls always happen in this order, once per
DatasetBuilder.save_extraction_result() call (matching the pre-refactor
behavior of opening, mutating, and immediately re-saving the destination
file on every single URL's save - not a long-lived open-file session):

    begin_dataset(dataset_name, sheet_name, columns)
    write_headers()
    append_record(record, primary_keys, timestamp)   # zero or more times
    finish()

`log_summary`/`log_failed_url` are optional, best-effort hooks - formats
that have no natural place for them (CSV) inherit the no-op default here
rather than forcing DatasetBuilder to special-case "does this format
support a summary log".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class DatasetWriter(ABC):
    @abstractmethod
    def begin_dataset(self, dataset_name: str, sheet_name: str, columns: List[str]) -> None:
        """Resolves the destination file for this schema's dataset_name and
        prepares it for writing (opens/creates a workbook, or opens/creates
        a CSV file). `columns` is the schema's column order, authoritative
        for both write_headers() and append_record()."""

    @abstractmethod
    def write_headers(self) -> None:
        """Ensures the header row exists in the destination, writing it if
        this is a new (or header-less) dataset. Idempotent - a no-op if
        headers are already present."""

    @abstractmethod
    def append_record(self, record: Dict[str, Any], primary_keys: List[str], timestamp: str) -> Dict[str, Any]:
        """Writes one normalized record (one URL -> one row), in the column
        order begin_dataset() was given. Returns
        {"operation": "Inserted" | "Updated", "row_number": Optional[int]}.
        Formats without efficient random-access update (CSV) always insert
        and return row_number as the 1-indexed data row just appended."""

    def log_summary(self, source_url: str, summary_info: Dict[str, Any]) -> None:
        """Optional: records an extraction summary entry alongside the
        dataset. No-op by default."""

    def log_failed_url(self, url: str, reason: str, retry_recommended: bool = True) -> None:
        """Optional: records a failed-URL entry alongside the dataset.
        No-op by default."""

    @abstractmethod
    def finish(self) -> Dict[str, Any]:
        """Flushes/saves the dataset to disk. Returns
        {"file_path": str, "format": "csv" | "excel", "record_count": int}
        - record_count is the total number of data rows now in the file
        (not just the ones written this call), so a caller reading it after
        the last URL in a batch job reflects the whole dataset. This is
        what lets the UI show "Records written" / locate the output file
        without re-deriving either from the pipeline result or by scanning
        directories - see app/ui/_dataset_preview.py."""


def create_writer(output_format: str, datasets_dir: str = "datasets") -> DatasetWriter:
    """
    Dependency-injection factory: the single place that maps a config value
    ("csv" / "excel") to a concrete DatasetWriter. Callers that want a
    specific writer instance (e.g. tests) should construct one directly and
    pass it to DatasetBuilder(writer=...) instead of going through this.
    """
    normalized = (output_format or "excel").strip().lower()
    if normalized == "csv":
        from writers.csv_writer import CSVDatasetWriter
        return CSVDatasetWriter(datasets_dir=datasets_dir)
    if normalized == "excel":
        from writers.excel_writer import ExcelDatasetWriter
        return ExcelDatasetWriter(datasets_dir=datasets_dir)
    raise ValueError(f"Unknown output_format '{output_format}' - expected 'csv' or 'excel'.")
