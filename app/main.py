"""
FastAPI Backend Server.
Provides a simple API endpoint for the AI-powered web data extractor.

This used to call modules.browser/modules.preprocessor/modules.gemini
directly - an independent, simplified re-implementation of what
core.pipeline.ExtractionPipeline already does. That meant the same URL could
produce different results depending on whether it was extracted through
this API or the Streamlit UI. It now calls the same ExtractionPipeline the
UI uses, so there is exactly one execution path regardless of entry point.
"""

import os
import sys
import time
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# Add the parent directory to python path for modular package resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.pipeline import ExtractionPipeline
from utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="Web Data Extractor API",
    description="Intelligently extracts structured data from any webpage using the configured LLM provider.",
    version="1.0.0"
)


class ExtractionRequest(BaseModel):
    url: str = Field(description="Target webpage URL.")
    user_instructions: Optional[str] = Field(
        default="",
        description="Optional custom guidelines or instructions to focus the extraction."
    )


class ExtractionResponse(BaseModel):
    url: str
    page_title: str
    page_type: str
    page_summary: str
    entities: Dict[str, List[Dict[str, Any]]]
    detected_page_type: Optional[str] = None
    detected_page_type_confidence: Optional[float] = None
    run_metrics: Dict[str, Any] = Field(default_factory=dict)
    total_time_ms: int


@app.post(
    "/extract",
    response_model=ExtractionResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract structured data from a target URL."
)
async def extract_web_data_endpoint(req: ExtractionRequest):
    url = req.url
    user_instructions = req.user_instructions or ""

    logger.info(f"Received API extraction request for URL: {url}")

    start_time = time.time()
    try:
        pipeline = ExtractionPipeline()
        pipeline_res = await pipeline.run(url, user_instructions=user_instructions)

        extraction = pipeline_res["result"]
        clean_data = extraction.to_clean_dict()
        total_time_ms = int((time.time() - start_time) * 1000)

        return ExtractionResponse(
            url=url,
            page_title=clean_data["page_title"],
            page_type=clean_data["page_type"],
            page_summary=clean_data["page_summary"],
            entities=clean_data["entities"],
            detected_page_type=pipeline_res.get("detected_page_type"),
            detected_page_type_confidence=pipeline_res.get("detected_page_type_confidence"),
            run_metrics=pipeline_res.get("run_metrics", {}),
            total_time_ms=total_time_ms
        )

    except Exception as e:
        logger.critical(f"API extraction failure for {url}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction encountered a critical error: {e}"
        )
