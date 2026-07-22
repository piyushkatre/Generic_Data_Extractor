"""
Gemini API connector module.
Orchestrates direct DOM-to-LLM data extraction using the Google GenAI SDK.
Supports pipeline routing to modular intelligence, chunking, and merging components.
"""

from __future__ import annotations

import os
import json
import time
import random
from typing import List, Dict, Any, Optional, Union, Type
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field, model_validator
from utils.logger import get_logger

load_dotenv()
logger = get_logger(__name__)

from modules.llm.gemini_provider import (
    QuotaManager,
    get_cached_gemini_schema,
    repair_json_string,
    parse_quota_error,
    generate_gemini_schema
)

from modules.adapter_loader import KeyValueItem, FAQItem, ExtractionResult, CanonicalFranchiseRecord, ExtractedEntity, ExtractedRecord, KeyValue

from bs4 import BeautifulSoup
import re


def extract_web_data(
    html_content: str,
    user_instructions: str = "",
    client: Optional[genai.Client] = None,
    run_pipeline: bool = True,
    max_output_tokens: Optional[int] = None,
    context_metrics: Optional[Dict[str, int]] = None,
    source_url: Optional[str] = None,
    response_model: Optional[Type[BaseModel]] = None,
    adapter: Optional[Any] = None,
) -> Any:
    """
    Analyzes the HTML content of a webpage and extracts structured data.
    When run_pipeline=True, invokes the five-stage intelligence pipeline.
    When run_pipeline=False, communicates directly with Gemini.
    """
    if QuotaManager.is_exhausted():
        logger.warning("Bypassing extract_web_data call: Gemini daily quota exhausted.")
        raise ValueError("Gemini daily quota exhausted. Stop immediately.")
    if client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY environment variable is missing. Live API calls will fail.")
        client = genai.Client(api_key=api_key)

    # ------------------------------------------------------------------
    # Stage Routing: Unified Extraction Pipeline Integration
    # ------------------------------------------------------------------
    if run_pipeline:
        from modules.config import ExtractorConfig
        from modules.preprocessor import clean_html, estimate_tokens, detect_page_type
        from modules.adapter_loader import AdapterLoader
        from modules.dataset_builder.deterministic_extractor import DeterministicExtractor
        from modules.relevant_dom.builder import RelevantDOMBuilder
        from modules.dataset_builder.record_validator import RecordValidator

        start_pipeline_time = time.perf_counter()

        # Load active adapter
        adapter = AdapterLoader.load(source_url or "")
        DynamicModel = adapter.get_model()

        # 1. Clean HTML
        full_cleaned_html = clean_html(html_content)

        # 1.2. Run deterministic DOM extractor on full cleaned HTML using active schema
        dom_extractor = DeterministicExtractor(adapter.schema)
        dom_extracted = dom_extractor.extract(full_cleaned_html, url=source_url)

        # Print every deterministically extracted field before Gemini
        logger.info("\n=== Deterministic DOM Extraction Results ===")
        for key, val in dom_extracted.items():
            if val not in (None, "", [], {}):
                logger.info(f"  Field '{key}': {val}")
        logger.info("============================================\n")

        # 1.1. Domain-Aware Relevant DOM Builder using adapter config
        profile = adapter.get_profile()
        dom_builder = RelevantDOMBuilder(profile)
        cleaned_html = dom_builder.build(full_cleaned_html, source_url or "")

        fields_from_dom = []
        fields_from_gemini = []

        # Helper to merge DOM and Gemini results
        def merge_results(gemini_res: Any) -> Any:
            nonlocal fields_from_dom, fields_from_gemini
            merged_data = {}

            gemini_dict = gemini_res.model_dump()
            for field in DynamicModel.model_fields.keys():
                dom_val = dom_extracted.get(field)
                gem_val = gemini_dict.get(field)

                is_dom_populated = dom_val not in (None, "", [], {})
                is_gem_populated = gem_val not in (None, "", [], {})

                is_list_field = field in ("products", "services", "images", "brochures", "documents", "faq", "additional_information", "metadata")

                if is_dom_populated:
                    merged_data[field] = dom_val
                    if field not in ("entities", "page_title", "page_summary", "metadata"):
                        fields_from_dom.append(field)
                elif is_gem_populated:
                    merged_data[field] = gem_val
                    if field not in ("entities", "page_title", "page_summary", "metadata"):
                        fields_from_gemini.append(field)
                else:
                    if is_list_field:
                        merged_data[field] = []
                    else:
                        merged_data[field] = None

            merged_data["metadata"] = [
                KeyValueItem(key="fields_from_dom", value=", ".join(fields_from_dom)),
                KeyValueItem(key="fields_from_gemini", value=", ".join(fields_from_gemini)),
                KeyValueItem(key="deterministic_fields_count", value=str(len([k for k, v in dom_extracted.items() if v not in (None, "", [], {})]))),
                KeyValueItem(key="original_tokens", value=str(estimated_tokens)),
                KeyValueItem(key="filtered_tokens", value=str(dom_builder.filtered_tokens)),
                KeyValueItem(key="reduction_pct", value=f"{dom_builder.reduction_pct:.1f}%"),
                KeyValueItem(key="filtered_html", value=cleaned_html)
            ]
            
            # Populate entities dictionary format expected by components
            merged_data["entities"] = gemini_res.entities if hasattr(gemini_res, "entities") else []
            merged_data["page_title"] = gemini_res.page_title or merged_data.get("franchise_name")
            merged_data["page_summary"] = gemini_res.page_summary or merged_data.get("description")

            return DynamicModel(**merged_data)

        # DOM Checker hallucination checks are archived/disabled in production refactoring
        metrics_ref = context_metrics if context_metrics is not None else {}
        metrics_ref["hallucinations_removed"] = 0
        metrics_ref["present_fields"] = []
        metrics_ref["extracted_fields"] = []
        metrics_ref["validated_fields"] = []
        metrics_ref["hallucinated_fields"] = []

        # 2. Token Heuristics & Page Type Heuristics
        estimated_tokens = estimate_tokens(cleaned_html)
        page_type_info = detect_page_type(cleaned_html)
        page_type = page_type_info["page_type"]
        confidence = page_type_info["confidence"]
        
        config = ExtractorConfig.load()
        
        # Metrics to track
        metrics = context_metrics if context_metrics is not None else {"requests": 0, "retries": 0}
        metrics["original_tokens"] = estimated_tokens
        metrics["filtered_tokens"] = dom_builder.filtered_tokens
        metrics["reduction_pct"] = dom_builder.reduction_pct
        metrics["sections_kept"] = dom_builder.sections_kept
        metrics["sections_removed"] = dom_builder.sections_removed
        metrics["deterministic_fields"] = fields_from_dom
        metrics["deterministic_fields_count"] = len(fields_from_dom)
        metrics["fields_from_gemini"] = fields_from_gemini

        # Force DIRECT strategy (exactly one request per URL)
        direct_out_tokens = min(8192, max(2048, estimated_tokens * 2))
        
        result = extract_web_data(
            html_content=cleaned_html,
            user_instructions=user_instructions,
            client=client,
            run_pipeline=False,
            max_output_tokens=direct_out_tokens,
            context_metrics=metrics,
            source_url=source_url,
            response_model=DynamicModel,
            adapter=adapter
        )
        
        # Apply priority merge
        result = merge_results(result)
        # Run Record Validator (clean/normalize/validate fields)
        result = RecordValidator.validate_record(result)
        # Hallucination check via DOMChecker is disabled/archived in production refactoring
        
        elapsed_ms = int((time.perf_counter() - start_pipeline_time) * 1000)
        
        return result

    # ------------------------------------------------------------------
    # Base Layer: Low-level single-shot LLM caller (delegated to provider)
    # ------------------------------------------------------------------
    from modules.llm.factory import get_llm_provider
    provider = get_llm_provider(client)
    return provider.extract(
        html_content=html_content,
        user_instructions=user_instructions,
        client=client,
        max_output_tokens=max_output_tokens,
        context_metrics=context_metrics,
        source_url=source_url,
        response_model=response_model,
        adapter=adapter
    )



