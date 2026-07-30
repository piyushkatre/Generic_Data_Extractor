"""
GenericExtractionRecord
========================
The minimal, schema-agnostic base class SchemaLoader.build_model() attaches
schema fields to. Unlike CanonicalFranchiseRecord (kept, unchanged, for
backward compatibility with existing callers), this carries NO franchise
vocabulary at all - only fields every extraction genuinely needs regardless
of vertical: where it came from, when, a title/summary pair, a confidence
score, an entities/FAQ scaffold, and the metadata/additional-information
overflow bags every downstream stage (validator, mapper) already expects.

Reuses the same nested models (FAQItem, KeyValueItem, ExtractedEntity,
ExtractedRecord, KeyValue) already defined in modules/adapter_loader.py -
those are generic structural scaffolding, not franchise-specific, so they
are not duplicated here.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from modules.adapter_loader import FAQItem, KeyValueItem, ExtractedEntity


class GenericExtractionRecord(BaseModel):
    # Pipeline meta
    source_url: Optional[str] = Field(default=None, description="The URL of the source page")
    extracted_at: Optional[str] = Field(default=None, description="ISO extraction timestamp")
    confidence: Optional[float] = Field(default=None, description="Extraction confidence score (0.0 to 1.0)")

    # Universal display fields
    page_type: Optional[str] = Field(default=None, description="Type of the page/record, as named by the active schema")
    page_title: Optional[str] = Field(default=None, description="Title of the page")
    page_summary: Optional[str] = Field(default=None, description="Brief summary of the page")

    # Generic overflow / scaffolding - populated by RecordValidator/SchemaMapper,
    # not assumed to contain any particular field names.
    entities: Optional[List[ExtractedEntity]] = Field(default_factory=list, description="Entity/record groupings, if any were produced")
    faq: Optional[List[FAQItem]] = Field(default_factory=list, description="Frequently asked questions list, if the page had one")
    additional_information: Optional[List[KeyValueItem]] = Field(default_factory=list, description="Unmapped/overflow key-value pairs")
    metadata: Optional[List[KeyValueItem]] = Field(default_factory=list, description="Internal pipeline execution metadata")

    @model_validator(mode="after")
    def populate_fallbacks(self) -> "GenericExtractionRecord":
        if not self.page_title:
            self.page_title = self.source_url or "Untitled Page"
        if not self.page_summary:
            self.page_summary = ""
        return self

    def to_clean_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        label = self.page_type or "Extracted Record"
        return {
            "page_title": self.page_title or self.source_url or "Untitled Page",
            "page_type": label,
            "page_summary": self.page_summary or "",
            "entities": {label: [d]},
        }
