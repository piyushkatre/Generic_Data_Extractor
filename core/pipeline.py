import time
import asyncio
import os
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from modules.adapter_loader import AdapterLoader
# Dynamic imports moved to run() to support mocking
from modules.preprocessor import clean_html, estimate_tokens, detect_page_type
from core.dom_builder import DOMBlockBuilder
from core.prompt_builder import ExtractionPromptBuilder
from core.pipeline_context import PipelineContext
from core.runtime_adapter import RuntimeAdapter
from core.execution_context import ExecutionContext
from core.ownership import OwnershipResolver
from core.field_matching import normalize_field_name, resolve_by_alias
from modules.dataset_builder.deterministic_extractor import DeterministicExtractor
from modules.gemini import QuotaManager
from modules.dataset_builder.record_validator import RecordValidator
from modules.dataset_builder.record_mapper import RecordMapper
from modules.dataset_builder.builder import DatasetBuilder
from modules.dataset_builder.schema_loader import SchemaLoader
from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from core.field_strategy import print_registry_summary

from utils.logger import get_logger

logger = get_logger(__name__)


class ExtractionPipeline:
    """
    Central orchestrator coordinating the generic pipeline stages:
    Config Resolution -> Playwright rendering -> Tab merge -> DOM clean
    -> Structured blocks -> Deterministic regex -> Programmatic Prompt -> LLM -> Validator -> Mapper -> Excel

    Consumes a RuntimeAdapter (the same duck-typed interface today's
    file-based Adapter exposes: `.config`, `.schema`, `.name`, `.get_profile()`,
    `.get_model()`), built from a WebsiteConfig + ExtractionSchema. A caller
    that already has a WebsiteConfig/ExtractionSchema for this run (e.g. a
    ExtractionJob via core.job_executor) can pass a RuntimeAdapter directly;
    otherwise `run()` resolves one via AdapterLoader (reading from
    templates/) by the URL's domain, for backward compatibility.

    This is the SINGLE execution path for the pipeline: cleaning, DOM
    pruning, deterministic extraction, field-ownership merging, and
    validation used to be re-implemented a second time inside
    modules/gemini.py; that duplicate orchestration has been removed so a
    given URL always produces the same result regardless of which caller
    (Streamlit UI, FastAPI endpoint, ExtractionJob) triggered the run.
    """
    def __init__(self, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.progress_callback = progress_callback
        # These mirror the equivalent PipelineContext attributes for the
        # duration of a run, so existing callers reading pipeline.stages /
        # pipeline.logs (e.g. the Streamlit UI) keep working unchanged, and
        # so pipeline.stages is already populated (all "Pending") before
        # run() is ever called, matching prior behavior.
        self.stages: Dict[str, Dict[str, Any]] = {
            name: {"status": "Pending", "duration": 0.0} for name in PipelineContext.STAGE_NAMES
        }
        self.logs: List[str] = []
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

    def log(self, message: str):
        logger.info(message)

    async def run(
        self,
        url: str,
        user_instructions: str = "",
        schemas_dir: str = "schemas",
        datasets_dir: str = "datasets",
        runtime_adapter: Optional[RuntimeAdapter] = None,
        execution_context: Optional[ExecutionContext] = None,
    ) -> Dict[str, Any]:
        """
        Runs the full extraction pipeline for one URL.

        `execution_context`, when given (this is how core.job_executor and
        therefore JobService drive a run), is the authoritative source of
        the RuntimeAdapter for this call - `runtime_adapter` is ignored in
        that case. A fresh, url-scoped ExecutionContext is derived from it
        via `.for_url()`, reusing the exact same `job`/`runtime_adapter`
        object references (see core/execution_context.py).

        Otherwise, `runtime_adapter` is used as-is if given (built ahead of
        time from a caller-supplied WebsiteConfig + ExtractionSchema), or -
        for callers with neither - a RuntimeAdapter is resolved from
        AdapterLoader (matching the URL's domain against templates/).
        """
        if execution_context is not None:
            execution_context = execution_context.for_url(url, progress_callback=self.progress_callback)
            ctx = execution_context.pipeline_context
            # Reuse this pipeline instance's pre-seeded "Pending" stages dict
            # for backward-compatible external reads (pipeline.stages).
            ctx.stages = self.stages
        else:
            ctx = PipelineContext(
                url=url,
                runtime_adapter=runtime_adapter,
                progress_callback=self.progress_callback,
                stages=self.stages,
            )
        ctx.start()
        # Mirror context state onto self.* for backward-compatible external reads.
        self.logs = ctx.logs
        self.start_time = ctx.start_time

        ctx.log(f"Pipeline started for URL: {url}")
        print_registry_summary()

        # Dynamically import to allow test suite mock patching at execution time
        try:
            from modules.dataset_builder.builder import fetch_webpage, extract_web_data
        except ImportError:
            from modules.browser import fetch_webpage
            from modules.gemini import extract_web_data

        raw_html = ""
        filtered_html = ""
        raw_tokens = 0
        clean_tokens = 0
        token_reduction_pct = 0.0

        # 1. Job Configuration Loaded (config + schema resolution)
        t0 = time.time()
        ctx.update_stage("Job Configuration Loaded", "Running")
        ctx.log("Resolving website configuration and extraction schema...")
        try:
            if ctx.runtime_adapter is None:
                if os.path.basename(schemas_dir) != "schemas":
                    # Test/isolated-schema-directory support: lets a caller
                    # (e.g. the test suite) inject a custom ExtractionSchema
                    # via `schemas_dir` without needing a matching templates/
                    # entry, while still using the domain-matched
                    # WebsiteConfig. This is the one remaining caller of
                    # SchemaLoader.load_schema() as a schema *source* -
                    # everywhere else, the schema is whatever the caller
                    # (or the resolved adapter/template) explicitly provided.
                    schema_loader = SchemaLoader(schemas_dir=schemas_dir)
                    page_type = "Franchise Page" if "testfranchise" in url.lower() else "General Web Data"
                    test_schema_dict = schema_loader.load_schema(page_type)

                    base_adapter = AdapterLoader.load(url)
                    website_config = WebsiteConfig.from_dict(base_adapter.config)
                    extraction_schema = ExtractionSchema.from_legacy_dict(test_schema_dict)
                    ctx.runtime_adapter = RuntimeAdapter.from_config_and_schema(
                        website_config, extraction_schema, name=page_type
                    )
                else:
                    adapter = AdapterLoader.load(url)
                    ctx.runtime_adapter = RuntimeAdapter.from_adapter(adapter)
            runtime_adapter = ctx.runtime_adapter

            ctx.log(
                f"Loaded configuration: {runtime_adapter.name} "
                f"(Domain: {runtime_adapter.domain}, Priority: {getattr(runtime_adapter, 'priority', 0)})"
            )
            ctx.update_stage("Job Configuration Loaded", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"Error resolving configuration: {e}")
            ctx.update_stage("Job Configuration Loaded", "Failed", time.time() - t0)
            raise e

        # 2. Browser Rendering
        t0 = time.time()
        ctx.update_stage("Browser Rendering", "Running")
        ctx.log("Launching browser and rendering page content (including tab exploration)...")
        try:
            render_res = await fetch_webpage(url)
            raw_html = render_res.get("html", "")

            is_debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes") or os.getenv("DEVELOPER_MODE", "false").lower() in ("true", "1", "yes")
            if is_debug:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                ctx.debug_dir = f"debug/run_{timestamp}"
                os.makedirs(ctx.debug_dir, exist_ok=True)
                with open(os.path.join(ctx.debug_dir, "01_rendered.html"), "w", encoding="utf-8") as f:
                    f.write(raw_html)

            ctx.log("Browser rendering and tab exploration successfully completed.")
            ctx.update_stage("Browser Rendering", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"Browser rendering failed: {e}")
            ctx.update_stage("Browser Rendering", "Failed", time.time() - t0)
            raise e

        # 3. DOM Cleaning
        t0 = time.time()
        ctx.update_stage("DOM Cleaning", "Running")
        ctx.log("Cleaning and pruning DOM based on the resolved website configuration...")
        try:
            cleaned_html = clean_html(raw_html, adapter=runtime_adapter)
            if ctx.debug_dir:
                with open(os.path.join(ctx.debug_dir, "02_cleaned.html"), "w", encoding="utf-8") as f:
                    f.write(cleaned_html)

            from modules.relevant_dom.builder import RelevantDOMBuilder
            profile = runtime_adapter.get_profile()
            dom_builder = RelevantDOMBuilder(profile, schema=runtime_adapter.schema, config=runtime_adapter.config)
            filtered_html = dom_builder.build(cleaned_html, url)
            if ctx.debug_dir:
                with open(os.path.join(ctx.debug_dir, "03_relevant.html"), "w", encoding="utf-8") as f:
                    f.write(filtered_html)

            raw_tokens = estimate_tokens(raw_html)
            clean_tokens = estimate_tokens(filtered_html)
            token_reduction_pct = ((raw_tokens - clean_tokens) / raw_tokens * 100.0) if raw_tokens > 0 else 0.0

            # Page-type detection: informational only, attached to the run
            # for display - it never selects a schema. The schema for this
            # run is always the one the caller resolved above.
            page_type_info = detect_page_type(filtered_html)
            ctx.set_page_type(page_type_info["page_type"], page_type_info["confidence"])

            ctx.run_metrics.update({
                "html_size_raw": len(raw_html),
                "html_size_cleaned": len(filtered_html),
                "raw_tokens": raw_tokens,
                "filtered_tokens": clean_tokens,
                "dom_reduction_pct": round(token_reduction_pct, 1),
                "relevant_dom_reduction_pct": round(getattr(dom_builder, "reduction_pct", 0.0), 1),
                "relevant_dom_sections_kept": getattr(dom_builder, "sections_kept", 0),
                "relevant_dom_sections_removed": getattr(dom_builder, "sections_removed", 0),
            })

            ctx.log(
                f"DOM cleaned. Token count reduced from {raw_tokens} to {clean_tokens} "
                f"({token_reduction_pct:.1f}% reduction). Detected page type: "
                f"{page_type_info['page_type']} ({page_type_info['confidence'] * 100:.0f}% confidence, informational only)."
            )
            ctx.update_stage("DOM Cleaning", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"DOM cleaning failed: {e}")
            ctx.update_stage("DOM Cleaning", "Failed", time.time() - t0)
            raise e

        # 4. Structured DOM Creation
        t0 = time.time()
        ctx.update_stage("Structured DOM Creation", "Running")
        ctx.log("Converting cleaned DOM into structured semantic blocks...")
        dom_blocks: List[Dict[str, Any]] = []
        try:
            block_builder = DOMBlockBuilder(filtered_html)
            dom_blocks = block_builder.build_blocks()
            if ctx.debug_dir:
                with open(os.path.join(ctx.debug_dir, "04_blocks.json"), "w", encoding="utf-8") as f:
                    f.write(json.dumps(dom_blocks, indent=2))

            ctx.run_metrics["dom_block_count"] = len(dom_blocks)
            ctx.log(f"Created {len(dom_blocks)} semantic block elements.")
            ctx.update_stage("Structured DOM Creation", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"Structured DOM builder failed: {e}")
            ctx.update_stage("Structured DOM Creation", "Failed", time.time() - t0)
            raise e

        # 5. Deterministic Extraction
        t0 = time.time()
        ctx.update_stage("Deterministic Extraction", "Running")
        ctx.log("Running regex and selector-based deterministic parser...")
        det_extracted: Dict[str, Any] = {}
        solved_fields: List[str] = []
        try:
            det_extractor = DeterministicExtractor(schema=runtime_adapter.schema, config=runtime_adapter.config)
            det_extracted = det_extractor.extract(filtered_html, url=url)

            solved_fields = [k for k, v in det_extracted.items() if v not in (None, "", [], {})]
            ctx.log(f"Deterministic extraction solved {len(solved_fields)} fields: {solved_fields}")
            ctx.update_stage("Deterministic Extraction", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"Deterministic extraction failed: {e}")
            ctx.update_stage("Deterministic Extraction", "Failed", time.time() - t0)
            raise e

        # 6. LLM Extraction
        t0 = time.time()
        ctx.update_stage("LLM Extraction", "Running")
        ctx.log("Sending structured DOM and dynamic instructions to the configured LLM provider...")
        try:
            if QuotaManager.is_exhausted():
                raise ValueError("Gemini daily quota exhausted.")

            prompt_rules = runtime_adapter.config.get("extraction_rules", [])
            prompt = ExtractionPromptBuilder.build_prompt(
                website_name=runtime_adapter.name,
                schema=runtime_adapter.schema,
                structured_dom=dom_blocks,
                extraction_rules=prompt_rules,
                deterministic_fields=solved_fields
            )
            if ctx.debug_dir:
                with open(os.path.join(ctx.debug_dir, "05_prompt.txt"), "w", encoding="utf-8") as f:
                    f.write(prompt)

            active_model = runtime_adapter.get_model()

            loop = asyncio.get_event_loop()
            llm_res = await loop.run_in_executor(
                None,
                lambda: extract_web_data(
                    html_content=filtered_html,
                    user_instructions=prompt,
                    client=None,
                    run_pipeline=False,
                    response_model=active_model,
                    adapter=runtime_adapter,
                    source_url=url
                )
            )

            if ctx.debug_dir:
                with open(os.path.join(ctx.debug_dir, "06_llm_response.json"), "w", encoding="utf-8") as f:
                    f.write(llm_res.model_dump_json(indent=2))

            # Merge deterministic & LLM results using the (single) field
            # ownership resolver - replaces the inline branching that used
            # to live here, and the separate copy that used to live in
            # modules/gemini.py's now-removed second orchestration path.
            merged_data: Dict[str, Any] = {}
            llm_dict = llm_res.model_dump()
            fields_from_dom: List[str] = []
            fields_from_llm: List[str] = []

            # Normalized lookup of deterministic results, keyed by normalized
            # identity - used ONLY to match a schema field to its
            # deterministic value; the schema field's own name/casing (used
            # everywhere below) is never altered. A deterministic key with no
            # matching schema field (e.g. "expected_hours" on a schema that
            # never declared it) is never looked up here and never enters
            # merged_data - the loop below only ever iterates schema fields,
            # so the pipeline never injects a field the user didn't request.
            normalized_det_extracted = {normalize_field_name(k): v for k, v in det_extracted.items()}

            for field_name in active_model.model_fields.keys():
                if field_name in ("entities", "faq", "additional_information", "metadata", "source_url", "extracted_at"):
                    continue

                extraction_field = runtime_adapter.extraction_schema.get_field(field_name)
                schema_aliases = extraction_field.aliases if extraction_field else None
                # Alias-aware: tries field_name itself first, then each of
                # the schema's own declared aliases (e.g. schema field
                # "Space Required" with alias "area required" still finds
                # the deterministic extractor's "area_required" key - see
                # core/field_matching.py for why normalize_field_name()
                # alone can't bridge a synonym like this).
                dom_val = resolve_by_alias(field_name, schema_aliases, normalized_det_extracted)
                llm_val = llm_dict.get(field_name)

                final_val, final_source = OwnershipResolver.merge(field_name, dom_val, llm_val, extraction_field)
                merged_data[field_name] = final_val

                if final_source == "Deterministic":
                    fields_from_dom.append(field_name)
                elif final_source == "LLM":
                    fields_from_llm.append(field_name)

                ctx.log(
                    f"\n[Field Ownership] Field Name: {field_name}\n"
                    f"  Deterministic:  {'YES' if dom_val not in (None, '', [], {}) else 'NO'}\n"
                    f"  LLM Used:       {'YES' if llm_val not in (None, '', [], {}) else 'NO'}\n"
                    f"  Final Source:   {final_source}"
                )

            merged_data["entities"] = llm_res.entities
            merged_data["faq"] = llm_res.faq
            merged_data["additional_information"] = llm_res.additional_information

            from modules.adapter_loader import KeyValueItem
            merged_metadata = [
                KeyValueItem(key="fields_from_dom", value=", ".join(fields_from_dom)),
                KeyValueItem(key="fields_from_llm", value=", ".join(fields_from_llm)),
            ]
            if llm_res.metadata:
                for item in llm_res.metadata:
                    key = item.key if hasattr(item, "key") else (item.get("key") if isinstance(item, dict) else None)
                    value = item.value if hasattr(item, "value") else (item.get("value") if isinstance(item, dict) else None)
                    if key not in ("fields_from_dom", "fields_from_llm", "fields_from_gemini"):
                        merged_metadata.append(KeyValueItem(key=key, value=value))
            merged_data["metadata"] = merged_metadata

            merged_data["source_url"] = url
            merged_data["extracted_at"] = datetime.now().isoformat()

            result = active_model(**merged_data)

            ctx.log("LLM data extraction completed successfully.")
            ctx.update_stage("LLM Extraction", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"LLM extraction failed: {e}")
            ctx.update_stage("LLM Extraction", "Failed", time.time() - t0)
            raise e

        # 7. Validation
        t0 = time.time()
        ctx.update_stage("Validation", "Running")
        ctx.log("Running validator for currency/percentage/measurement/phone normalizations...")
        try:
            validated_res = RecordValidator.validate_record(result)
            validated_res = RecordValidator.derive_numeric_ranges(validated_res)
            if ctx.debug_dir:
                dump = validated_res.model_dump_json(indent=2) if hasattr(validated_res, "model_dump_json") else json.dumps(validated_res.model_dump(), indent=2)
                with open(os.path.join(ctx.debug_dir, "07_validated.json"), "w", encoding="utf-8") as f:
                    f.write(dump)
            ctx.log("Field values successfully validated and normalized.")
            ctx.update_stage("Validation", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"Record validation failed: {e}")
            ctx.update_stage("Validation", "Failed", time.time() - t0)
            raise e

        # 8. Schema Mapping
        t0 = time.time()
        ctx.update_stage("Schema Mapping", "Running")
        ctx.log("Mapping record attributes to workbook columns...")
        try:
            schema = runtime_adapter.schema
            page_type = runtime_adapter.name

            mapper = RecordMapper(schema)
            # validated_res already went through RecordValidator in the
            # Validation stage above - skip RecordMapper's own internal
            # validation pass so it isn't run twice on the same record.
            mapped_record = mapper.map(validated_res, url, html_content=raw_html, already_validated=True)

            if ctx.debug_dir:
                with open(os.path.join(ctx.debug_dir, "08_mapping.json"), "w", encoding="utf-8") as f:
                    f.write(json.dumps(getattr(mapped_record, "mapping_paths", {}), indent=2))
                with open(os.path.join(ctx.debug_dir, "09_final_row.json"), "w", encoding="utf-8") as f:
                    f.write(json.dumps(mapped_record.mapped_record, indent=2))

            ctx.log("Schema attributes mapped to target sheet structure.")
            ctx.update_stage("Schema Mapping", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"Schema mapping failed: {e}")
            ctx.update_stage("Schema Mapping", "Failed", time.time() - t0)
            raise e

        # 9. Dataset Generation
        # DatasetBuilder is format-agnostic (writers/excel_writer.py or
        # writers/csv_writer.py, chosen by output_format) - this stage never
        # knows how to write either one, it just forwards the job's own
        # Output Format selection (set in the UI, see app/ui/job_runner.py)
        # from execution_context.job.output_format down to DatasetBuilder.
        # No execution_context (e.g. a caller that only passed a bare
        # runtime_adapter) means no job-level selection is available, so
        # output_format is left None and DatasetBuilder falls back to its
        # own default.
        t0 = time.time()
        ctx.update_stage("Dataset Generation", "Running")
        ctx.log("Writing record to destination dataset...")
        try:
            output_format = execution_context.job.output_format if execution_context is not None else None
            db = DatasetBuilder(schemas_dir=schemas_dir, datasets_dir=datasets_dir, output_format=output_format)
            save_info = await loop.run_in_executor(
                None,
                lambda: db.save_extraction_result(
                    mapped_record,
                    url,
                    page_type,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    raw_html,
                    schema=schema,
                    page_type=page_type,
                    pipeline_metadata={
                        "source_url": url,
                        "page_title": getattr(validated_res, "page_title", None),
                    },
                )
            )
            ctx.log(f"Saved dataset. File: {save_info.get('workbook_name')}, Row: {save_info.get('row_number')}.")
            ctx.update_stage("Dataset Generation", "Completed", time.time() - t0)
        except Exception as e:
            ctx.log(f"Dataset writing failed: {e}")
            ctx.update_stage("Dataset Generation", "Failed", time.time() - t0)
            raise e

        ctx.end_time = time.time()
        self.end_time = ctx.end_time
        ctx.run_metrics["total_time_seconds"] = round(ctx.elapsed(), 2)

        # Diagnostic Log Summary
        cov_pct = mapped_record.coverage_statistics.get("coverage_percentage", "0%")
        mapped_count = mapped_record.coverage_statistics.get("mapped_count", 0)
        total_count = mapped_record.coverage_statistics.get("total_schema_fields", 0)

        ctx.log("\n=================== PIPELINE DIAGNOSTIC SUMMARY ===================")
        ctx.log(f"Extraction Time:  {ctx.end_time - ctx.start_time:.2f} seconds")
        ctx.log(f"DOM Size (Raw):   {len(raw_html)} characters")
        ctx.log(f"DOM Size (Clean): {len(filtered_html)} characters")
        ctx.log(f"Token Reduction:  {raw_tokens - clean_tokens} tokens ({token_reduction_pct:.1f}% reduction)")
        ctx.log(f"Detected Page Type (informational): {ctx.detected_page_type} ({(ctx.detected_page_type_confidence or 0) * 100:.0f}%)")
        ctx.log(f"Schema Coverage:  {cov_pct} ({mapped_count}/{total_count} fields mapped)")
        ctx.log(f"Mapped Columns:   {list(mapped_record.mapped_record.keys())}")
        ctx.log(f"Unmapped Fields:  {mapped_record.unmapped_fields}")
        ctx.log(f"Excel File:       {save_info.get('workbook_name')}")
        ctx.log(f"Excel Row:        {save_info.get('row_number')} ({save_info.get('operation')})")
        ctx.log("===================================================================\n")

        ctx.log(f"Extraction pipeline successfully finished in {ctx.end_time - ctx.start_time:.2f}s!")

        # Run diagnostic extraction journey inspector
        if ctx.debug_dir:
            try:
                from modules.diagnostics.extraction_inspector import ExtractionInspector
                inspector = ExtractionInspector(ctx.debug_dir, runtime_adapter.schema)
                inspector.generate_journey_report()
                ctx.log("Extraction journey diagnostic report generated at: debug/extraction_journey.md")
            except Exception as diag_err:
                ctx.log(f"Failed to generate extraction journey report: {diag_err}")

        return {
            "status": "success",
            "result": validated_res,
            "mapped_record": mapped_record,
            "save_info": save_info,
            "duration": ctx.end_time - ctx.start_time,
            "detected_page_type": ctx.detected_page_type,
            "detected_page_type_confidence": ctx.detected_page_type_confidence,
            "run_metrics": ctx.run_metrics,
        }


# Backward-compatible alias - the class was previously named
# FranchiseExtractionPipeline. Prefer ExtractionPipeline in new code.
FranchiseExtractionPipeline = ExtractionPipeline
