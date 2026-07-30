"""
Gemini API connector module.

This used to independently re-implement the full clean -> prune ->
deterministic -> LLM -> merge -> validate sequence (the `run_pipeline=True`
branch below), duplicating what core/pipeline.py does. That meant the same
URL could produce different results depending on whether it was served by
the Streamlit UI (core/pipeline.py) or the FastAPI endpoint (which called
this module directly) - a correctness risk. Orchestration now happens
exactly once, in core.pipeline.ExtractionPipeline; this module is a thin
"call the configured LLM provider" wrapper only.
"""

from __future__ import annotations

import os
from typing import Dict, Any, Optional, Type
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel
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
    Calls the configured LLM provider (Gemini or Ollama) to extract
    structured data from the given HTML content.

    `run_pipeline` is accepted only for backward-compatible call signatures
    and no longer branches behavior: full-pipeline orchestration (cleaning,
    DOM pruning, deterministic extraction, field-ownership merging,
    validation) lives solely in core.pipeline.ExtractionPipeline now.
    Callers that need the full pipeline should use that class directly
    instead of this flag.
    """
    if QuotaManager.is_exhausted():
        logger.warning("Bypassing extract_web_data call: Gemini daily quota exhausted.")
        raise ValueError("Gemini daily quota exhausted. Stop immediately.")
    if client is None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            logger.warning("GEMINI_API_KEY environment variable is missing. Live API calls will fail.")
        client = genai.Client(api_key=api_key)

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


