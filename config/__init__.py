"""
config package
===============
Pure data models for the three runtime inputs of the extraction engine:
WebsiteConfig, ExtractionSchema (+ ExtractionField), and ExtractionJob.

This package intentionally contains NO persistence layer yet (no
ConfigStore/SchemaStore/JobStore) and is not wired into any UI. Storage and
UI are a later milestone. For now these are plain, testable data objects
that bridge into the legacy dict-shaped contracts the existing generic
modules (DeterministicExtractor, SchemaMapper, PromptBuilder, browser,
preprocessor, relevant_dom) already expect, via their `to_dict()` methods.
"""

from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionField, ExtractionSchema
from config.extraction_job import ExtractionJob

__all__ = ["WebsiteConfig", "ExtractionField", "ExtractionSchema", "ExtractionJob"]
