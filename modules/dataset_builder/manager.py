"""
Backward-compatibility re-export shim.

The real Excel/openpyxl implementation (ExcelFileLockedError, ExcelWriter,
WorkbookManager) moved to writers/excel_writer.py as part of the Excel/CSV
output-layer refactor, so all Excel-specific code lives in one place
alongside the new CSV writer. This module keeps the old import path
(`from modules.dataset_builder.manager import WorkbookManager, ExcelWriter`)
working for existing callers/tests without changes.

`import openpyxl` is kept here (unused directly) because tests patch
"modules.dataset_builder.manager.openpyxl.Workbook.save" - removing this
import would break that patch target.
"""

import openpyxl  # noqa: F401 - kept for `patch("modules.dataset_builder.manager.openpyxl...")` targets

from writers.excel_writer import (  # noqa: F401
    ExcelFileLockedError,
    ExcelWriter,
    WorkbookManager,
)
