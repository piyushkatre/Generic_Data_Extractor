"""
Backward-compatibility re-export shim - DuplicateDetector moved to
writers/excel_writer.py as part of the Excel/CSV output-layer refactor.
"""

from writers.excel_writer import DuplicateDetector  # noqa: F401
