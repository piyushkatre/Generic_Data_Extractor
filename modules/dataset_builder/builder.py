import os
import time
import asyncio
from typing import Dict, Any, List, Union, Optional
from utils.logger import get_logger

from modules.browser import fetch_webpage
from modules.gemini import extract_web_data, ExtractionResult
from modules.preprocessor import clean_html, detect_page_type
from modules.dataset_builder.schema_loader import SchemaLoader
from modules.dataset_builder.manager import WorkbookManager, ExcelFileLockedError
from modules.dataset_builder.record_mapper import RecordMapper, ValidationError as MapperValidationError
from writers.dataset_writer import DatasetWriter, create_writer
from core.field_matching import normalize_field_name, SUPPORTED_METADATA_COLUMNS

logger = get_logger(__name__)

class DatasetBuilder:
    """
    Main orchestrator for the schema-driven dataset construction pipeline.
    Processes URLs, handles transient errors, normalizes records, and saves
    them via a format-agnostic DatasetWriter (Excel or CSV - see writers/).

    DatasetBuilder itself never imports openpyxl/Workbook/Worksheet and
    never branches on output format: it resolves the schema and the one
    normalized record per URL, then hands both to self.writer, which is the
    only thing that knows what a "row" means for the configured format.
    """

    def __init__(
        self,
        schemas_dir: str = "schemas",
        datasets_dir: str = "datasets",
        output_format: Optional[str] = None,
        writer: Optional[DatasetWriter] = None,
    ):
        self.schemas_dir = os.path.abspath(schemas_dir)
        self.schema_loader = SchemaLoader(schemas_dir=schemas_dir)
        # Kept for backward compatibility - some callers/tests read/replace
        # this directly (e.g. to redirect datasets_dir), and it's otherwise
        # unrelated to which DatasetWriter is actually used to save records.
        self.manager = WorkbookManager(datasets_dir=datasets_dir)

        self.output_format = (output_format or os.getenv("OUTPUT_FORMAT", "excel")).strip().lower()
        # Dependency injection: pass writer= directly (tests, or a caller
        # with its own DatasetWriter) to bypass the output_format lookup
        # entirely.
        self.writer: DatasetWriter = writer if writer is not None else create_writer(
            self.output_format, datasets_dir=datasets_dir
        )

    def _parse_urls(self, urls: Union[str, List[str]]) -> List[str]:
        """
        Parses inputs (list of URLs, single URL, or text file containing URLs) into a list of URLs.
        """
        if isinstance(urls, str):
            urls = urls.strip()
            # Check if it is a file path
            if os.path.exists(urls) and not urls.startswith(("http://", "https://")):
                try:
                    with open(urls, "r", encoding="utf-8") as f:
                        return [line.strip() for line in f if line.strip()]
                except Exception as e:
                    logger.error(f"Failed to read URLs from file {urls}: {e}")
                    return []
            else:
                return [urls]
        elif isinstance(urls, (list, tuple, set)):
            return [str(u).strip() for u in urls if str(u).strip()]
        return []

    async def process_urls(self, urls: Union[str, List[str]], user_instructions: str = "") -> Dict[str, Any]:
        """
        Processes each URL sequentially, extracts structured information,
        normalizes it, and saves it via self.writer.
        """
        from core.pipeline import ExtractionPipeline
        parsed_urls = self._parse_urls(urls)
        logger.info(f"DatasetBuilder: processing {len(parsed_urls)} URLs.")

        results = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "details": []
        }

        for url in parsed_urls:
            logger.info(f"Processing URL: {url}")
            try:
                pipeline = ExtractionPipeline()
                pipeline_res = await pipeline.run(
                    url=url,
                    user_instructions=user_instructions,
                    schemas_dir=self.schemas_dir,
                    datasets_dir=self.manager.datasets_dir
                )

                results["success"] += 1
                results["details"].append({
                    "url": url,
                    "status": "Success",
                    "page_type": pipeline_res["result"].page_type,
                    "dataset": pipeline_res["save_info"].get("workbook_name")
                })
            except ExcelFileLockedError as e:
                logger.warning(f"[Dataset Warning] {url} skipped because file is locked: {e}")
                results["failed"] += 1
                results["details"].append({
                    "url": url,
                    "status": "Failed (File Locked)",
                    "reason": str(e)
                })
            except Exception as e:
                logger.error(f"Failed to process URL {url}: {e}")
                results["failed"] += 1
                results["details"].append({
                    "url": url,
                    "status": "Failed",
                    "reason": str(e)
                })
            results["processed"] += 1

        return results

    def save_extraction_result(
        self,
        result: Any,
        source_url: str,
        detected_page_type: str,
        timestamp: str,
        html_content: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        page_type: Optional[str] = None,
        pipeline_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Saves a single pre-extracted ExtractionResult via self.writer.
        Returns info about save status, dataset file, operation type
        (Inserted/Updated), and row number.

        `schema`/`page_type`, when given, are used as-is - this is the
        schema (and its name) the caller actually extracted/mapped `result`
        with (e.g. RuntimeAdapter.schema from core/pipeline.py). Without
        them, the schema is re-derived independently from `source_url` -
        which silently disagrees with the schema an ExtractionSchema-driven
        job actually used whenever the URL's domain doesn't match a
        registered templates/ entry (a bug this parameter exists to avoid;
        see tests/test_end_to_end_workflow.py).

        `pipeline_metadata` (e.g. {"source_url": ..., "page_title": ...})
        supplies the pipeline's own authoritative values for the schema's
        opt-in metadata_columns (config/extraction_schema.py). These are
        written directly into the final record below, entirely bypassing
        RecordMapper/SchemaMapper/AliasRegistry - they are never treated as
        extraction fields and can never be overwritten by an LLM/DOM value.
        `source_url` always falls back to the `source_url` parameter above
        when not given explicitly.
        """
        logger.info("DatasetBuilder initialized")

        if schema is not None:
            page_type = page_type or getattr(result, "page_type", None) or detected_page_type or "Unknown"
            dataset_name = schema.get("dataset_name") or f"{page_type.lower().replace(' ', '_')}.xlsx"
        # 1. Determine page type and load schema dynamically using AdapterLoader or SchemaLoader in tests
        elif os.path.basename(self.schemas_dir) != "schemas":
            page_type = "Franchise Page" if "testfranchise" in source_url.lower() else (getattr(result, "page_type", None) or detected_page_type or "Unknown")
            schema = self.schema_loader.load_schema(page_type)
            dataset_name = schema.get("dataset_name", "test_franchise.xlsx")
        else:
            from modules.adapter_loader import AdapterLoader
            adapter = AdapterLoader.load(source_url)
            schema = adapter.schema
            page_type = adapter.name
            dataset_name = schema.get("dataset_name", "misc_dataset.xlsx")

        logger.info(f"Schema loaded for page type: {page_type}")

        sheet_name   = schema.get("sheet_name", "General Web Data")
        columns      = schema.get("columns", [])
        primary_keys = schema.get("primary_key", ["Source URL"])

        # Pipeline metadata columns (Source Url / Page Title) - opt-in via
        # the schema's own metadata_columns list, never extraction fields.
        # Added to the writer's column list here so they get a real
        # header/cell; their VALUES are appended directly from
        # pipeline_metadata below, after mapping - never resolved through
        # RecordMapper/SchemaMapper/AliasRegistry, so they can never
        # collide with (or be overwritten by) an extracted field.
        #
        # Skipped for an identity the schema's own `columns` already cover
        # (e.g. a legacy templates/*/schema.json that already lists "Source
        # URL" as a plain column, populated - unchanged - by SchemaMapper's
        # existing alias matching): this avoids ever writing two columns
        # for the same identity under different display text.
        existing_normalized_columns = {normalize_field_name(c) for c in columns}
        metadata_column_ids = schema.get("metadata_columns", list(SUPPORTED_METADATA_COLUMNS.keys()))
        metadata_columns = {
            normalize_field_name(m): SUPPORTED_METADATA_COLUMNS[normalize_field_name(m)]
            for m in metadata_column_ids
            if normalize_field_name(m) in SUPPORTED_METADATA_COLUMNS
            and normalize_field_name(m) not in existing_normalized_columns
        }
        columns = list(columns) + list(metadata_columns.values())

        # 2. Map to exactly ONE normalized record (one URL -> one row)
        from modules.dataset_builder.schema_mapper import MappingResult

        try:
            if isinstance(result, MappingResult):
                logger.info("Bypassing duplicate schema mapping; MappingResult received directly.")
                normalized_record = result.mapped_record
            elif isinstance(result, dict) and "entities" not in result:
                logger.info("Bypassing duplicate schema mapping; mapped dict received directly.")
                normalized_record = result
            else:
                logger.info("Raw extraction result received; performing schema mapping.")
                record_mapper = RecordMapper(schema)
                try:
                    mapping_res = record_mapper.map(result, source_url, html_content=html_content)
                    normalized_record = mapping_res.mapped_record
                except MapperValidationError as ve:
                    logger.warning(f"Validation failed for {source_url}: {ve}")
                    return {
                        "status": "Skipped",
                        "reason": str(ve),
                        "workbook_name": os.path.join("datasets", dataset_name).replace("\\", "/"),
                        "operation": "Skipped",
                        "row_number": None,
                    }

            # 2b. Append enabled metadata columns directly from pipeline
            # metadata - after mapping, bypassing AliasRegistry/SchemaMapper
            # entirely (see the docstring above).
            meta_values = dict(pipeline_metadata or {})
            meta_values.setdefault("source_url", source_url)
            for norm_id, col_name in metadata_columns.items():
                normalized_record[col_name] = meta_values.get(norm_id) or ""

            # 3. Write via the format-agnostic writer - Excel or CSV,
            # DatasetBuilder doesn't know or care which.
            self.writer.begin_dataset(dataset_name, sheet_name, columns)
            self.writer.write_headers()
            op_info = self.writer.append_record(normalized_record, primary_keys, timestamp)
            logger.info(f"Record {op_info['operation'].lower()} at row {op_info['row_number']}")

            summary_info = {
                "status": "Success",
                "page_type": page_type,
                "strategy": "DIRECT",
                "execution_time": 0,
                "chunk_count": 1,
                "batch_count": 1,
                "error": ""
            }
            self.writer.log_summary(source_url, summary_info)

            finish_info = self.writer.finish()
            logger.info("Dataset saved")
            logger.info("Dataset update completed")

            return {
                "status": "Success",
                # Key name kept as "workbook_name" for backward compatibility
                # with existing callers (core/pipeline.py logs) even when
                # the format is CSV.
                "workbook_name": os.path.join("datasets", os.path.basename(finish_info["file_path"])).replace("\\", "/"),
                "operation": op_info["operation"],
                "row_number": op_info["row_number"],
                # Real, directly-openable path + format + total row count,
                # straight from the writer that actually wrote the file - so
                # the UI (app/ui/_dataset_preview.py) never has to guess a
                # path or search datasets_dir.
                "output_path": finish_info["file_path"],
                "output_format": finish_info.get("format", self.output_format),
                "records_written": finish_info.get("record_count"),
                "sheet_name": finish_info.get("sheet_name"),
            }
        except ExcelFileLockedError as e:
            logger.warning(f"[Dataset Warning] {e}")
            return {
                "status": "Failed",
                "reason": str(e),
                "error": str(e),
                "workbook_name": os.path.join("datasets", dataset_name).replace("\\", "/"),
                "operation": "Skipped (File Locked)",
                "row_number": None,
            }
