"""
record_mapper.py
================
Transforms one ExtractionResult into exactly ONE normalized MappingResult aligned to
schema columns. Thin wrapper around SchemaMapper to preserve backward compatibility.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple
from utils.logger import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    """Raised when a required schema field is still missing after all defaults."""


class FieldNormalizer:
    """
    Cleans individual field values according to the semantic meaning of their key.
    Entirely stateless — all methods are static.
    """

    @staticmethod
    def normalize(key: str, value: Any) -> str:
        if value is None:
            return ""

        if isinstance(value, (list, tuple)):
            seen: set = set()
            parts: List[str] = []
            for item in value:
                s = str(item).strip()
                if s and s not in seen:
                    seen.add(s)
                    parts.append(s)
            value = " | ".join(parts)
        elif isinstance(value, dict):
            value = json.dumps(value, ensure_ascii=False)
        else:
            value = str(value)

        value = re.sub(r"\s+", " ", value).strip()
        key_lower = key.lower()

        if any(k in key_lower for k in ("phone", "mobile", "contact number", "landline")):
            value = re.sub(r"[^\d\+\-\(\)\sa-zA-Z]", "", value)
            value = re.sub(r"\s+", " ", value).strip()
            return value

        if "email" in key_lower:
            value = value.lower()
            m = re.search(r"[\w.\-_+]+@[\w.\-_]+\.[a-zA-Z]{2,}", value)
            return m.group(0) if m else value

        _url_keys = ("website", "url", "link", "site",
                     "facebook", "instagram", "linkedin", "twitter", "youtube")
        if any(k in key_lower for k in _url_keys):
            value = value.strip().replace(" ", "")
            if value and not value.startswith(("http://", "https://", "ftp://")):
                value = "https://" + value
            if value.endswith("/") and value.count("/") > 2:
                value = value.rstrip("/")
            return value

        _financial_keys = ("investment", "fee", "royalty", "roi",
                           "capital", "payback", "cost", "price", "revenue")
        if any(k in key_lower for k in _financial_keys):
            value = value.replace("\u2013", "-").replace("\u2014", "-")
            value = value.replace("\u00a0", " ").replace("\u20b9", "\u20b9")
            value = re.sub(r"\s+", " ", value).strip()
            return value

        _date_keys = ("date", "year", "since", "established", "founded", "payback period")
        if any(k in key_lower for k in _date_keys):
            year_match = re.search(r"\b(19|20)\d{2}\b", value)
            if year_match:
                full_date = re.search(
                    r"(\d{1,2})[\-/](\d{1,2})[\-/]((19|20)\d{2})", value
                )
                if full_date:
                    d, m_num, y = full_date.group(1), full_date.group(2), full_date.group(3)
                    value = f"{y}-{int(m_num):02d}-{int(d):02d}"
                else:
                    value = year_match.group(0)
            return value

        return value

    @staticmethod
    def clean_additional_info(data: dict) -> str:
        cleaned = {
            k: v for k, v in data.items()
            if v not in (None, "", [], {})
        }
        return json.dumps(cleaned, ensure_ascii=False) if cleaned else ""


class FieldMapper:
    """
    Maps raw extracted keys to schema column names using the schema's
    *aliases* dict and exact column name matching.
    """

    def __init__(self, schema: Dict[str, Any]):
        self.columns: List[str] = schema.get("columns", [])
        self._lookup: Dict[str, str] = {}

        for col in self.columns:
            norm = self._normalise_key(col)
            self._lookup[norm] = col

        for alias, col in schema.get("aliases", {}).items():
            norm = self._normalise_key(alias)
            self._lookup[norm] = col

    def get_column(self, raw_key: str) -> Optional[str]:
        return self._lookup.get(self._normalise_key(raw_key))

    def map(self, raw: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        mapped: Dict[str, Any] = {}
        unmapped: Dict[str, Any] = {}

        for key, value in raw.items():
            col = self.get_column(key)
            if col:
                if col not in mapped or not mapped[col]:
                    mapped[col] = value
            else:
                unmapped[key] = value

        return mapped, unmapped

    @staticmethod
    def _normalise_key(key: str) -> str:
        return str(key).strip().lower().replace("_", " ").replace("-", " ")


class PrimaryEntityDetector:
    """
    Scores each entity in *ExtractionResult.entities* and selects the one
    most likely to represent the primary subject of the page.
    """

    _NOISE_WORDS = {
        "data", "dataset", "xlsx", "sheet", "general", "web", "page",
        "info", "information",
    }

    def __init__(self, schema: Dict[str, Any]):
        combined = (
            f"{schema.get('dataset_name', '')} "
            f"{schema.get('sheet_name', '')}"
        ).lower()
        self._schema_keywords: set = {
            w
            for w in re.findall(r"\w+", combined)
            if w not in self._NOISE_WORDS and len(w) > 3
        }

    def detect(self, entities: list) -> Tuple[Optional[Any], List[Any]]:
        if not entities:
            return None, []
        if len(entities) == 1:
            return entities[0], []

        scored = sorted(
            enumerate(entities),
            key=lambda x: (-self._score(x[1], x[0]), x[0]),
        )
        _, primary_entity = scored[0]
        related = [e for _, e in scored[1:]]
        return primary_entity, related

    def _score(self, entity: Any, index: int) -> float:
        score = 0.0
        entity_type_lower = entity.entity_type.lower()

        if any(kw in entity_type_lower for kw in self._schema_keywords):
            score += 10.0

        if len(entity.records) == 1:
            score += 5.0
            attr_count = len(entity.records[0].attributes)
            score += min(attr_count, 10) * 0.2

        if index == 0:
            score += 1.0

        return score


class RecordMapper:
    """
    Transforms one *ExtractionResult* into **exactly one** MappingResult
    aligned to schema columns. Thin wrapper delegating to SchemaMapper.
    """

    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema
        self.columns: List[str] = schema.get("columns", [])
        self.required_fields: List[str] = schema.get("required_fields", [])

    def map(self, result: Any, source_url: str, html_content: Optional[str] = None) -> Any:
        from modules.dataset_builder.schema_mapper import SchemaMapper
        from modules.dataset_builder.record_validator import RecordValidator
        
        # Ensure validation and numeric range derivation are executed (robust fallback for direct mapper calls in tests)
        result = RecordValidator.validate_record(result)
        result = RecordValidator.derive_numeric_ranges(result)
        
        mapper = SchemaMapper(excel_columns=self.columns, schema_aliases=self.schema.get("aliases"), schema=self.schema)
        mapping_result = mapper.map_to_excel(result, source_url, html_content=html_content)

        normalized = mapping_result.mapped_record

        # Validate required fields
        missing = [r for r in self.required_fields if not normalized.get(r)]
        if missing:
            for req in missing:
                req_lower = req.lower()
                if "url" in req_lower:
                    normalized[req] = source_url
                elif "title" in req_lower or "name" in req_lower:
                    normalized[req] = getattr(result, "page_title", None) or source_url

            missing = [r for r in self.required_fields if not normalized.get(r)]
            if missing:
                msg = (
                    f"Validation failed — missing required fields {missing} "
                    f"for URL: {source_url}"
                )
                logger.warning(msg)
                raise ValidationError(msg)

        return mapping_result
