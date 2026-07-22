"""
FastAPI Backend Server.
Provides a simple API endpoint for the AI-powered web data extractor.
"""

import os
import sys
import time
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from google import genai

# Add the parent directory to python path for modular package resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.browser import fetch_webpage
from modules.preprocessor import clean_html
from modules.gemini import extract_web_data, ExtractionResult
from utils.logger import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="Web Data Extractor API",
    description="Intelligently extracts structured data from any webpage using Gemini.",
    version="1.0.0"
)

# Initialize GenAI Client once at startup
client: Optional[genai.Client] = None
try:
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        client = genai.Client(api_key=api_key)
    else:
        logger.warning("GEMINI_API_KEY environment variable is missing in FastAPI startup context.")
except Exception as e:
    logger.error(f"Failed to initialize GenAI client on FastAPI startup: {e}")

class ExtractionRequest(BaseModel):
    url: str = Field(description="Target webpage URL.")
    user_instructions: Optional[str] = Field(
        default="",
        description="Optional custom guidelines or instructions to focus the extraction."
    )

class ExtractionResponse(BaseModel):
    url: str
    final_url: str
    page_title: str
    page_type: str
    page_summary: str
    entities: Dict[str, List[Dict[str, Any]]]
    render_time_ms: int
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
        # 1. Fetch webpage via Playwright
        render_result = await fetch_webpage(url)
        render_time_ms = render_result["render_time_ms"]
        
        # 2. Clean HTML
        cleaned_html = clean_html(render_result["html"])
        
        # 3. Extract data via Gemini
        extraction = extract_web_data(
            html_content=cleaned_html,
            user_instructions=user_instructions,
            client=client
        )
        
        total_time_ms = int((time.time() - start_time) * 1000)
        
        # Get clean dictionary format
        clean_data = extraction.to_clean_dict()
        
        return ExtractionResponse(
            url=url,
            final_url=render_result["final_url"],
            page_title=extraction.page_title,
            page_type=extraction.page_type,
            page_summary=extraction.page_summary,
            entities=clean_data["entities"],
            render_time_ms=render_time_ms,
            total_time_ms=total_time_ms
        )
        
    except Exception as e:
        logger.critical(f"API extraction failure for {url}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Extraction encountered a critical error: {e}"
        )
