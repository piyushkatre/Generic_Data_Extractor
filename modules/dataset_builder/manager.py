import os
from datetime import datetime
import openpyxl
from typing import Dict, Any, List, Optional
from modules.dataset_builder.detector import DuplicateDetector

class ExcelFileLockedError(PermissionError):
    """Exception raised when an Excel workbook file is locked or open in another application."""
    pass

class ExcelWriter:
    """
    Directly interacts with openpyxl to perform workbook file I/O operations.
    """
    
    @staticmethod
    def get_or_create_workbook(file_path: str) -> openpyxl.Workbook:
        if os.path.exists(file_path):
            try:
                # Exclusive lock check to early-detect locked file
                with open(file_path, "r+"):
                    pass
            except PermissionError as e:
                raise ExcelFileLockedError(
                    f"The Excel file '{os.path.basename(file_path)}' is currently locked/open. Please close it and retry."
                ) from e
            except Exception:
                pass
                
            try:
                return openpyxl.load_workbook(file_path)
            except Exception:
                # If file is corrupted or empty, create a new one
                pass
        return openpyxl.Workbook()

    @staticmethod
    def save_workbook(wb: openpyxl.Workbook, file_path: str):
        # Ensure parent directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            wb.save(file_path)
        except PermissionError as e:
            raise ExcelFileLockedError(
                f"The Excel file '{os.path.basename(file_path)}' is currently locked/open. Please close it and retry."
            ) from e

class WorkbookManager:
    """
    Orchestrates sheet structure, records insertion/update, extraction summaries,
    and failed extraction logs inside openpyxl Workbooks.
    """

    def __init__(self, datasets_dir: str = "datasets"):
        self.datasets_dir = os.path.abspath(datasets_dir)

    def write_extracted_records(
        self,
        schema: Dict[str, Any],
        normalized_records: List[Dict[str, str]],
        source_url: str,
        summary_info: Dict[str, Any]
    ):
        """
        Appends or updates extracted data records in the target dataset workbook,
        and logs the operation in the Extraction Summary sheet.
        """
        dataset_name = schema.get("dataset_name", "misc_dataset.xlsx")
        sheet_name = schema.get("sheet_name", "General Web Data")
        primary_keys = schema.get("primary_key", [])
        columns = schema.get("columns", [])
        
        file_path = os.path.join(self.datasets_dir, dataset_name)
        wb = ExcelWriter.get_or_create_workbook(file_path)
        
        # Ensure sheets exist
        self._ensure_sheet_headers(wb, sheet_name, columns)
        self._ensure_summary_sheet_headers(wb)
        
        ws = wb[sheet_name]
        headers = [str(cell.value).strip() if cell.value is not None else "" for cell in ws[1]]
        
        timestamp_now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        for record in normalized_records:
            # Check for existing record matching primary keys
            row_idx = DuplicateDetector.find_duplicate_row_index(ws, primary_keys, record)
            
            # Map column names to index values (1-indexed for openpyxl)
            if row_idx:
                # Update existing row
                # Set Last Updated, preserve Extraction Date if present
                for col in columns:
                    if col == "Last Updated":
                        record[col] = timestamp_now
                    elif col == "Extraction Date":
                        # Fetch original Extraction Date value
                        try:
                            col_idx = headers.index(col) + 1
                            orig_val = ws.cell(row=row_idx, column=col_idx).value
                            record[col] = str(orig_val if orig_val is not None else timestamp_now)
                        except ValueError:
                            record[col] = timestamp_now
                    
                    if col in record:
                        try:
                            idx = headers.index(col) + 1
                            ws.cell(row=row_idx, column=idx, value=record[col])
                        except ValueError:
                            pass
            else:
                # Insert new row
                # Set both Extraction Date and Last Updated
                row_idx = ws.max_row + 1
                for col in columns:
                    if col == "Extraction Date" or col == "Last Updated":
                        record[col] = timestamp_now
                        
                    if col in record:
                        try:
                            idx = headers.index(col) + 1
                            ws.cell(row=row_idx, column=idx, value=record[col])
                        except ValueError:
                            pass
                            
        # Log summary info
        self._log_summary(wb, source_url, summary_info)
        ExcelWriter.save_workbook(wb, file_path)
        
        return {
            "operation": "Updated" if row_idx else "Inserted",
            "row_number": row_idx if row_idx else ws.max_row
        }

    def log_failed_url(
        self,
        schema: Dict[str, Any],
        url: str,
        reason: str,
        retry_recommended: bool = True
    ):
        """
        Logs a failed URL extraction into the Failed URLs sheet of the workbook.
        """
        dataset_name = schema.get("dataset_name", "misc_dataset.xlsx")
        file_path = os.path.join(self.datasets_dir, dataset_name)
        wb = ExcelWriter.get_or_create_workbook(file_path)
        
        self._ensure_failed_sheet_headers(wb)
        ws = wb["Failed URLs"]
        
        row_idx = ws.max_row + 1
        ws.cell(row=row_idx, column=1, value=url)
        ws.cell(row=row_idx, column=2, value=reason)
        ws.cell(row=row_idx, column=3, value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ws.cell(row=row_idx, column=4, value="Yes" if retry_recommended else "No")
        
        ExcelWriter.save_workbook(wb, file_path)

    def _ensure_sheet_headers(self, wb: openpyxl.Workbook, sheet_name: str, columns: List[str]):
        """
        Checks if the target data sheet exists and has correct headers. If not, initializes it.
        """
        if sheet_name not in wb.sheetnames:
            # If sheet is new and there's a default Sheet created, rename it
            if len(wb.sheetnames) == 1 and wb.sheetnames[0] == "Sheet":
                ws = wb["Sheet"]
                ws.title = sheet_name
            else:
                ws = wb.create_sheet(title=sheet_name)
                
            # Write headers
            for idx, col in enumerate(columns, start=1):
                ws.cell(row=1, column=idx, value=col)
        else:
            # Sheet exists, verify headers match
            ws = wb[sheet_name]
            headers = [cell.value for cell in ws[1]]
            if not headers or all(h is None for h in headers):
                for idx, col in enumerate(columns, start=1):
                    ws.cell(row=1, column=idx, value=col)

    def _ensure_summary_sheet_headers(self, wb: openpyxl.Workbook):
        """
        Initializes the 'Extraction Summary' sheet.
        """
        summary_cols = [
            "URL", "Status", "Page Type", "Strategy", "Execution Time (ms)",
            "Chunk Count", "Batch Count", "Extraction Timestamp", "Error"
        ]
        sheet_name = "Extraction Summary"
        if sheet_name not in wb.sheetnames:
            ws = wb.create_sheet(title=sheet_name)
            for idx, col in enumerate(summary_cols, start=1):
                ws.cell(row=1, column=idx, value=col)
        else:
            ws = wb[sheet_name]
            headers = [cell.value for cell in ws[1]]
            if not headers or all(h is None for h in headers):
                for idx, col in enumerate(summary_cols, start=1):
                    ws.cell(row=1, column=idx, value=col)

    def _ensure_failed_sheet_headers(self, wb: openpyxl.Workbook):
        """
        Initializes the 'Failed URLs' sheet.
        """
        failed_cols = ["URL", "Reason", "Timestamp", "Retry Recommended"]
        sheet_name = "Failed URLs"
        if sheet_name not in wb.sheetnames:
            ws = wb.create_sheet(title=sheet_name)
            for idx, col in enumerate(failed_cols, start=1):
                ws.cell(row=1, column=idx, value=col)
        else:
            ws = wb[sheet_name]
            headers = [cell.value for cell in ws[1]]
            if not headers or all(h is None for h in headers):
                for idx, col in enumerate(failed_cols, start=1):
                    ws.cell(row=1, column=idx, value=col)

    def _log_summary(self, wb: openpyxl.Workbook, url: str, info: Dict[str, Any]):
        """
        Appends an extraction summary record.
        """
        ws = wb["Extraction Summary"]
        row_idx = ws.max_row + 1
        
        ws.cell(row=row_idx, column=1, value=url)
        ws.cell(row=row_idx, column=2, value=info.get("status", "Success"))
        ws.cell(row=row_idx, column=3, value=info.get("page_type", "Unknown"))
        ws.cell(row=row_idx, column=4, value=info.get("strategy", "DIRECT"))
        ws.cell(row=row_idx, column=5, value=info.get("execution_time", 0))
        ws.cell(row=row_idx, column=6, value=info.get("chunk_count", 1))
        ws.cell(row=row_idx, column=7, value=info.get("batch_count", 1))
        ws.cell(row=row_idx, column=8, value=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        ws.cell(row=row_idx, column=9, value=info.get("error", ""))
