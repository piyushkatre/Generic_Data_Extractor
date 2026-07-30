"""
CSV dataset output - the new format this migration adds. Uses only
Python's standard `csv` module (no pandas).

CSV has no concept of "sheet" (sheet_name is accepted for interface
symmetry with ExcelDatasetWriter but unused) and no efficient random-access
update, so unlike Excel this writer is append-only: every append_record()
call inserts a new row rather than searching for and updating a matching
primary-key row. This is a deliberate, documented behavior difference
between formats, not a bug - Excel's insert-or-update semantics are
preserved exactly for Excel output; CSV output simply appends, matching
this migration's explicit CSV requirements (append rows in order, no
mention of dedup/merge).
"""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, List, Optional

from writers.dataset_writer import DatasetWriter


class CSVDatasetWriter(DatasetWriter):
    def __init__(self, datasets_dir: str = "datasets"):
        self.datasets_dir = os.path.abspath(datasets_dir)
        self._file_path: Optional[str] = None
        self._columns: List[str] = []

    def begin_dataset(self, dataset_name: str, sheet_name: str, columns: List[str]) -> None:
        dataset_name = dataset_name or "misc_dataset.csv"
        base, _ext = os.path.splitext(dataset_name)
        self._file_path = os.path.join(self.datasets_dir, f"{base}.csv")
        self._columns = list(columns or [])
        os.makedirs(self.datasets_dir, exist_ok=True)

    def write_headers(self) -> None:
        """Writes the header row once - only if the file doesn't exist yet
        or is empty. A pre-existing non-empty CSV is assumed to already have
        its header row (matching ExcelDatasetWriter's "verify headers exist,
        write only if missing" idempotency)."""
        needs_header = not os.path.exists(self._file_path) or os.path.getsize(self._file_path) == 0
        if needs_header:
            with open(self._file_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(self._columns)

    def append_record(self, record: Dict[str, Any], primary_keys: List[str], timestamp: str) -> Dict[str, Any]:
        record = dict(record)
        for col in ("Extraction Date", "Last Updated"):
            if col in self._columns:
                record[col] = timestamp

        row_values = []
        for col in self._columns:
            val = record.get(col)
            row_values.append("" if val is None else str(val))

        with open(self._file_path, "a", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(row_values)

        with open(self._file_path, "r", encoding="utf-8", newline="") as f:
            row_number = sum(1 for _ in f) - 1  # exclude header row

        return {"operation": "Inserted", "row_number": row_number}

    def finish(self) -> Dict[str, Any]:
        record_count = 0
        if self._file_path and os.path.exists(self._file_path):
            with open(self._file_path, "r", encoding="utf-8", newline="") as f:
                record_count = max(sum(1 for _ in f) - 1, 0)  # exclude header row
        return {"file_path": self._file_path, "format": "csv", "record_count": record_count}
