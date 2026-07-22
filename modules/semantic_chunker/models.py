"""
Adaptive Semantic Chunker — output and planning models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SplitPlan(BaseModel):
    """
    Plan generated before splitting to recommend the best extraction strategy.
    """
    section: str = Field(description="Name/identifier of the HTML section being analyzed.")
    split_candidates: List[str] = Field(description="List of possible split strategy candidates.")
    estimated_tokens: int = Field(description="Estimated token count of this section.")
    recommended_split: str = Field(description="The recommended split strategy.")


class SemanticChunk(BaseModel):
    """
    One semantically coherent slice of a webpage.
    """
    chunk_id: int = Field(description="1-based sequential identifier within this chunking result.")
    page_title: str = Field(
        default="",
        description="Title of the original page, extracted from <title> or the first <h1>.",
    )
    page_type_guess: str = Field(
        default="",
        description="Inferred page type forwarded from PageProfiler. Empty when not available.",
    )
    parent_section: str = Field(
        default="",
        description="Outermost semantic container of this chunk (e.g. 'section#products', 'main').",
    )
    heading_path: List[str] = Field(
        default_factory=list,
        description="Ordered breadcrumb of heading texts (h1 → h2 → ...).",
    )
    estimated_tokens: int = Field(
        description="Estimated LLM token count for this chunk.",
    )
    char_count: int = Field(
        description="Exact character count of the chunk's HTML string.",
    )
    html: str = Field(
        description="Valid HTML fragment ready to be sent to an LLM.",
    )
    has_overlap: bool = Field(
        default=False,
        description="True when the start of HTML is repeated from the end of the previous chunk.",
    )
    overlap_chars: int = Field(
        default=0,
        description="Number of characters at the start of HTML that constitute the overlap region.",
    )
    parent_chunk: Optional[int] = Field(
        default=None,
        description="The ID of the parent chunk from which this chunk was recursively split.",
    )
    depth: int = Field(
        default=0,
        description="The recursion depth at which this chunk was generated.",
    )
    split_reason: str = Field(
        default="",
        description="The reason why this chunk was split.",
    )
    split_level: str = Field(
        default="",
        description="The semantic level description used for splitting.",
    )
    source_xpath: str = Field(
        default="",
        description="The best-effort XPath of the element's parent container.",
    )


class ChunkingResult(BaseModel):
    """
    Complete output of a single AdaptiveSemanticChunker.chunk() call.
    """
    chunks: List[SemanticChunk] = Field(
        description="Ordered list of semantic chunks ready for LLM consumption.",
    )
    total_chunks: int = Field(
        description="Total number of chunks produced.",
    )
    strategy_used: str = Field(
        description="Name of the ExtractionStrategy applied during chunking.",
    )
    total_chars: int = Field(
        description="Total character count across all chunks (excluding overlap).",
    )
    average_chunk_chars: int = Field(
        description="Average character count per chunk.",
    )
    largest_chunk_chars: int = Field(
        description="Character count of the largest chunk.",
    )
    smallest_chunk_chars: int = Field(
        description="Character count of the smallest chunk.",
    )
    recursive_split_count: int = Field(
        description="Number of times a semantic block was recursively split.",
    )
    chunking_time_ms: int = Field(
        description="Wall-clock time in milliseconds taken to produce all chunks.",
    )
    oversized_chunks: int = Field(
        default=0,
        description="Number of chunks that still exceed max_chunk_size after all attempts.",
    )
