"""
WebsiteConfig
=============
One of the three runtime inputs of the extraction engine (URLs, Website
Configuration, Extraction Schema). Describes how to render and clean a
website's pages and which DOM sections are worth keeping before an LLM call
- everything today's `adapters/<site>/config.json` holds, minus any implicit
per-site scanning/discovery. A WebsiteConfig is created and owned by the
caller (UI, script, or a template loader) and handed explicitly to a
RuntimeAdapter for a run - it is never discovered by matching a URL's domain
against a scanned folder from inside the pipeline itself.

No persistence (save/load/versioning) lives here yet - that is a later
milestone. `from_dict`/`to_dict`/`from_json_file` are enough to bridge to
and from today's JSON file shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from modules.domain_profiles.base import DomainProfile
from config.errors import ValidationError

_DICT_FIELDS = ("browser_config", "dom_clean_config", "clickable_tabs", "removable_elements", "keep_elements", "metadata")
_LIST_FIELDS = ("extraction_rules", "domains", "aliases")
_BOOL_FIELDS = ("keep_tables", "keep_contact_blocks")
_SCORE_FIELDS = (
    "heading_keep_score", "heading_remove_score", "class_keep_score", "class_remove_score",
    "tag_remove_score", "table_score", "contact_score", "keep_threshold",
)


@dataclass
class WebsiteConfig:
    name: str = "Untitled Website Configuration"
    domain: str = "*"
    domains: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    priority: int = 0
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    extraction_rules: List[str] = field(default_factory=list)
    browser_config: Dict[str, Any] = field(default_factory=dict)
    dom_clean_config: Dict[str, Any] = field(default_factory=dict)
    clickable_tabs: Dict[str, Any] = field(default_factory=dict)
    removable_elements: Dict[str, Any] = field(default_factory=dict)
    keep_elements: Dict[str, Any] = field(default_factory=dict)

    keep_tables: bool = True
    keep_contact_blocks: bool = True
    heading_keep_score: float = 10.0
    heading_remove_score: float = -8.0
    class_keep_score: float = 5.0
    class_remove_score: float = -6.0
    tag_remove_score: float = -20.0
    table_score: float = 8.0
    contact_score: float = 10.0
    keep_threshold: float = 0.0

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        """Raises ValidationError with a message naming exactly which field
        is wrong, instead of letting a malformed config surface as a raw
        KeyError/TypeError somewhere deep inside browser.py/preprocessor.py
        the first time that field is actually used."""
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("WebsiteConfig.name must be a non-empty string.")
        if not isinstance(self.domain, str) or not self.domain.strip():
            raise ValidationError(f"WebsiteConfig '{self.name}': domain must be a non-empty string (use '*' for a generic fallback).")
        if not isinstance(self.priority, int) or isinstance(self.priority, bool):
            raise ValidationError(f"WebsiteConfig '{self.name}': priority must be an int, got {type(self.priority).__name__}.")

        for attr in _DICT_FIELDS:
            value = getattr(self, attr)
            if not isinstance(value, dict):
                raise ValidationError(f"WebsiteConfig '{self.name}': {attr} must be an object/dict, got {type(value).__name__}.")

        for attr in _LIST_FIELDS:
            value = getattr(self, attr)
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise ValidationError(f"WebsiteConfig '{self.name}': {attr} must be a list of strings.")

        for attr in _BOOL_FIELDS:
            value = getattr(self, attr)
            if not isinstance(value, bool):
                raise ValidationError(f"WebsiteConfig '{self.name}': {attr} must be true or false, got {type(value).__name__}.")

        for attr in _SCORE_FIELDS:
            value = getattr(self, attr)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValidationError(f"WebsiteConfig '{self.name}': {attr} must be a number, got {type(value).__name__}.")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebsiteConfig":
        """
        Builds a WebsiteConfig from a plain dict - either a hand-authored
        one, or one loaded straight from a legacy `adapters/*/config.json` /
        `templates/*/config.json` file (same shape).
        """
        data = data or {}
        domain = data.get("domain", "*")
        domains = domain if isinstance(domain, list) else ([domain] if domain else ["*"])

        raw_aliases = data.get("aliases", [])
        aliases = raw_aliases if isinstance(raw_aliases, list) else ([raw_aliases] if raw_aliases else [])

        return cls(
            name=data.get("name", "Untitled Website Configuration"),
            domain=domain if isinstance(domain, str) else (domain[0] if domain else "*"),
            domains=domains,
            aliases=aliases,
            priority=int(data.get("priority", 0)),
            version=str(data.get("version", "1.0.0")),
            metadata=data.get("metadata", {}) or {},
            extraction_rules=data.get("extraction_rules", []) or [],
            browser_config=data.get("browser_config", {}) or {},
            dom_clean_config=data.get("dom_clean_config", {}) or {},
            clickable_tabs=data.get("clickable_tabs", {}) or {},
            removable_elements=data.get("removable_elements", {}) or {},
            keep_elements=data.get("keep_elements", {}) or {},
            keep_tables=data.get("keep_tables", True),
            keep_contact_blocks=data.get("keep_contact_blocks", True),
            heading_keep_score=data.get("heading_keep_score", 10.0),
            heading_remove_score=data.get("heading_remove_score", -8.0),
            class_keep_score=data.get("class_keep_score", 5.0),
            class_remove_score=data.get("class_remove_score", -6.0),
            tag_remove_score=data.get("tag_remove_score", -20.0),
            table_score=data.get("table_score", 8.0),
            contact_score=data.get("contact_score", 10.0),
            keep_threshold=data.get("keep_threshold", 0.0),
        )

    @classmethod
    def from_json_file(cls, path: str) -> "WebsiteConfig":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> Dict[str, Any]:
        """
        Produces the same dict shape today's Adapter.config exposes, so
        existing generic modules (browser.py, preprocessor.py,
        relevant_dom/builder.py) keep working against it unchanged.
        """
        return {
            "name": self.name,
            "domain": self.domain,
            "aliases": list(self.aliases),
            "priority": self.priority,
            "version": self.version,
            "metadata": dict(self.metadata),
            "extraction_rules": list(self.extraction_rules),
            "browser_config": dict(self.browser_config),
            "dom_clean_config": dict(self.dom_clean_config),
            "clickable_tabs": dict(self.clickable_tabs),
            "removable_elements": dict(self.removable_elements),
            "keep_elements": dict(self.keep_elements),
            "keep_tables": self.keep_tables,
            "keep_contact_blocks": self.keep_contact_blocks,
            "heading_keep_score": self.heading_keep_score,
            "heading_remove_score": self.heading_remove_score,
            "class_keep_score": self.class_keep_score,
            "class_remove_score": self.class_remove_score,
            "tag_remove_score": self.tag_remove_score,
            "table_score": self.table_score,
            "contact_score": self.contact_score,
            "keep_threshold": self.keep_threshold,
        }

    def to_pruning_profile(self) -> DomainProfile:
        """
        Builds the DomainProfile consumed by RelevantDOMBuilder - the same
        computation Adapter.get_profile() performs today, just sourced from
        this object instead of a freshly-parsed config.json.
        """
        removable = self.removable_elements or {}
        keep = self.keep_elements or {}

        return DomainProfile(
            domain=self.domain,
            name=self.name,
            remove_tag_names=removable.get("remove_tag_names", []),
            remove_heading_keywords=removable.get("remove_heading_keywords", []),
            remove_class_keywords=removable.get("remove_class_keywords", []),
            remove_id_keywords=removable.get("remove_id_keywords", []),
            remove_aria_keywords=removable.get("remove_aria_keywords", []),
            keep_heading_keywords=keep.get("keep_heading_keywords", []),
            keep_class_keywords=keep.get("keep_class_keywords", []),
            keep_id_keywords=keep.get("keep_id_keywords", []),
            keep_tables=self.keep_tables,
            keep_contact_blocks=self.keep_contact_blocks,
            heading_keep_score=self.heading_keep_score,
            heading_remove_score=self.heading_remove_score,
            class_keep_score=self.class_keep_score,
            class_remove_score=self.class_remove_score,
            tag_remove_score=self.tag_remove_score,
            table_score=self.table_score,
            contact_score=self.contact_score,
            keep_threshold=self.keep_threshold,
        )
