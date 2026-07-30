"""
ExtractionField / ExtractionSchema
===================================
The second of the three runtime inputs of the extraction engine. An
ExtractionSchema is an ordered list of fields the user wants extracted from a
page - it replaces `adapters/<site>/schema.json` plus the page-type-keyed
`schemas/*.json` files as the source of "what fields exist and what type are
they."

Per review feedback, field metadata is kept deliberately small: only
`name` / `type` / `description` / `aliases` / `required` are asked of a user
up front. `extraction_owner` / `merge_policy` / `format` are optional,
advanced attributes - most schemas will never set them, and
core/ownership.py supplies a generic, type-based default whenever they're
absent.

`to_dict()` produces the same dict shape today's `adapter.schema` exposes
(`extraction_fields` / `columns` / `aliases` / `primary_key` / etc.), so the
existing generic modules (DeterministicExtractor, SchemaMapper, PromptBuilder,
RecordMapper) keep working against it unchanged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from config.errors import ValidationError
from core.field_matching import is_reserved_pipeline_field, normalize_field_name, SUPPORTED_METADATA_COLUMNS


def _default_metadata_columns() -> List[str]:
    """Both supported metadata columns, enabled by default - see
    core/field_matching.SUPPORTED_METADATA_COLUMNS. Used as the
    ExtractionSchema.metadata_columns default, and as the fallback for any
    schema (new or legacy) that predates this field entirely, so no
    existing schema needs manual migration."""
    return list(SUPPORTED_METADATA_COLUMNS.keys())


_VALID_TYPES = {"string", "array", "integer", "number", "boolean"}
_VALID_OWNERS = {"deterministic", "hybrid", "llm"}
_VALID_MERGE_POLICIES = {"deterministic_only", "deterministic_first", "llm_only", "llm_first"}


def _default_column_name(field_name: str) -> str:
    """'investment_required' -> 'Investment Required' (used when a field
    doesn't specify its own output column name)."""
    return field_name.replace("_", " ").strip().title()


@dataclass
class ExtractionField:
    name: str
    type: str = "string"
    description: str = ""
    aliases: List[str] = field(default_factory=list)
    required: bool = False
    column: Optional[str] = None

    # Optional / advanced - most schemas never set these; a generic
    # type-based default is supplied by core/ownership.py when absent.
    extraction_owner: Optional[str] = None
    merge_policy: Optional[str] = None
    format: Optional[str] = None

    def __post_init__(self):
        self.validate()
        if not self.column:
            self.column = _default_column_name(self.name)

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("ExtractionField.name must be a non-empty string.")
        if is_reserved_pipeline_field(self.name):
            raise ValidationError(
                f"ExtractionField '{self.name}': this name is reserved for pipeline metadata "
                "(source_url, extracted_at, confidence, page_type, page_title, page_summary, "
                "entities, faq, additional_information, metadata - see "
                "core/field_matching.RESERVED_PIPELINE_FIELDS) and is populated automatically by "
                "the pipeline itself. Choose a different field name; if you need this value as an "
                "output column, it is already included automatically."
            )
        if self.type not in _VALID_TYPES:
            raise ValidationError(
                f"ExtractionField '{self.name}': invalid type '{self.type}' (expected one of {sorted(_VALID_TYPES)})."
            )
        if not isinstance(self.description, str):
            raise ValidationError(f"ExtractionField '{self.name}': description must be a string.")
        if not isinstance(self.aliases, list) or not all(isinstance(a, str) for a in self.aliases):
            raise ValidationError(f"ExtractionField '{self.name}': aliases must be a list of strings.")
        if not isinstance(self.required, bool):
            raise ValidationError(f"ExtractionField '{self.name}': required must be true or false.")
        if self.extraction_owner is not None and self.extraction_owner not in _VALID_OWNERS:
            raise ValidationError(
                f"ExtractionField '{self.name}': invalid extraction_owner '{self.extraction_owner}' "
                f"(expected one of {sorted(_VALID_OWNERS)})."
            )
        if self.merge_policy is not None and self.merge_policy not in _VALID_MERGE_POLICIES:
            raise ValidationError(
                f"ExtractionField '{self.name}': invalid merge_policy '{self.merge_policy}' "
                f"(expected one of {sorted(_VALID_MERGE_POLICIES)})."
            )

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "ExtractionField":
        return cls(
            name=name,
            type=data.get("type", "string"),
            description=data.get("description", ""),
            aliases=list(data.get("aliases", []) or []),
            required=bool(data.get("required", False)),
            column=data.get("column"),
            extraction_owner=data.get("extraction_owner"),
            merge_policy=data.get("merge_policy"),
            format=data.get("format"),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = {"type": self.type, "description": self.description}
        if self.aliases:
            d["aliases"] = list(self.aliases)
        if self.required:
            d["required"] = True
        if self.extraction_owner:
            d["extraction_owner"] = self.extraction_owner
        if self.merge_policy:
            d["merge_policy"] = self.merge_policy
        if self.format:
            d["format"] = self.format
        return d


@dataclass
class ExtractionSchema:
    name: str = "Untitled Extraction Schema"
    fields: List[ExtractionField] = field(default_factory=list)
    primary_key_fields: List[str] = field(default_factory=list)
    additional_information_column: str = "Additional Information"
    # Columns that exist in the output (e.g. "Source URL", "Extraction Date",
    # "Last Updated", or a reserved-but-unmapped column like "Brand") but
    # don't correspond to any declared ExtractionField - preserved verbatim
    # so a legacy schema's column list round-trips through to_dict()
    # without silently losing columns nothing extracts into directly.
    extra_columns: List[str] = field(default_factory=list)
    extra_required_columns: List[str] = field(default_factory=list)
    # Excel output naming (legacy - a later milestone derives the output
    # filename from the ExtractionJob/WebsiteConfig name instead; see
    # docs/ARCHITECTURE_REDESIGN.md). Preserved through the round-trip so a
    # legacy schema's own workbook/sheet naming isn't silently dropped.
    dataset_name: Optional[str] = None
    sheet_name: str = "General Web Data"
    # Pipeline metadata (source_url, page_title) a user wants included as
    # plain OUTPUT COLUMNS - never as ExtractionFields (those identities are
    # rejected outright by ExtractionField.validate() above). Populated
    # directly from pipeline metadata by DatasetBuilder after SchemaMapper
    # finishes mapping extracted fields - see
    # modules/dataset_builder/builder.py's save_extraction_result() and
    # core/field_matching.SUPPORTED_METADATA_COLUMNS (the only currently
    # supported identities). Defaults to both enabled, so a schema saved
    # before this field existed needs no manual migration.
    metadata_columns: List[str] = field(default_factory=_default_metadata_columns)

    def __post_init__(self):
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("ExtractionSchema.name must be a non-empty string.")
        if not isinstance(self.fields, list) or not all(isinstance(f, ExtractionField) for f in self.fields):
            raise ValidationError(
                f"ExtractionSchema '{self.name}': fields must be a list of ExtractionField objects "
                "(use ExtractionField.from_dict() or ExtractionSchema.from_dict() rather than passing raw dicts)."
            )

        seen_names = set()
        for f in self.fields:
            if f.name in seen_names:
                raise ValidationError(
                    f"ExtractionSchema '{self.name}': field name '{f.name}' is declared more than once."
                )
            seen_names.add(f.name)

        if not isinstance(self.primary_key_fields, list) or not all(isinstance(p, str) for p in self.primary_key_fields):
            raise ValidationError(f"ExtractionSchema '{self.name}': primary_key_fields must be a list of strings.")

        if not isinstance(self.metadata_columns, list) or not all(isinstance(m, str) for m in self.metadata_columns):
            raise ValidationError(f"ExtractionSchema '{self.name}': metadata_columns must be a list of strings.")
        for m in self.metadata_columns:
            if normalize_field_name(m) not in SUPPORTED_METADATA_COLUMNS:
                raise ValidationError(
                    f"ExtractionSchema '{self.name}': metadata_columns entry '{m}' is not supported. "
                    f"Only {sorted(SUPPORTED_METADATA_COLUMNS.keys())} are currently supported "
                    "(see core/field_matching.SUPPORTED_METADATA_COLUMNS)."
                )

    def field_names(self) -> List[str]:
        return [f.name for f in self.fields]

    def get_field(self, name: str) -> Optional[ExtractionField]:
        for f in self.fields:
            if f.name == name:
                return f
        return None

    @property
    def required_field_names(self) -> List[str]:
        return [f.name for f in self.fields if f.required]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtractionSchema":
        """
        Accepts either:
        - the new, simplified shape: {"name": ..., "fields": [{"name": ..., "type": ..., ...}, ...]}
        - today's legacy schema.json shape: {"extraction_fields": {name: {...}}, "aliases": {...}, "columns": [...], "primary_key": [...]}
        """
        data = data or {}
        if "fields" in data:
            fields = [
                ExtractionField.from_dict(f["name"], f) if "name" in f else None
                for f in data.get("fields", [])
            ]
            fields = [f for f in fields if f is not None]
            return cls(
                name=data.get("name", "Untitled Extraction Schema"),
                fields=fields,
                primary_key_fields=list(data.get("primary_key_fields", []) or []),
                additional_information_column=data.get("additional_information_column", "Additional Information"),
                # "key present" vs "key absent" matters here: an existing
                # schema with no metadata_columns key at all defaults to
                # both enabled (backward compatibility), but a schema that
                # explicitly saved an empty list (both disabled by the
                # user) must stay empty, not silently re-enable.
                metadata_columns=list(data["metadata_columns"]) if "metadata_columns" in data else _default_metadata_columns(),
            )

        return cls.from_legacy_dict(data)

    @classmethod
    def from_legacy_dict(cls, data: Dict[str, Any]) -> "ExtractionSchema":
        """
        Builds an ExtractionSchema from today's `adapters/*/schema.json` /
        `templates/*/schema.json` shape (extraction_fields dict + columns +
        aliases + primary_key), so existing template content can be loaded
        without being hand-rewritten into the new field-list format.
        """
        data = data or {}
        extraction_fields = data.get("extraction_fields", {}) or {}
        aliases_map = data.get("aliases", {}) or {}
        columns = data.get("columns", []) or []
        primary_keys = data.get("primary_key", []) or []
        required_columns = set(data.get("required_fields", []) or [])

        # Column name -> field name (reverse of the alias-driven lookup
        # DeterministicExtractor builds), so we can recover which column a
        # field is meant to write to.
        col_for_field: Dict[str, str] = {}
        for field_name in extraction_fields.keys():
            col_name = aliases_map.get(field_name) or aliases_map.get(field_name.replace("_", " "))
            if not col_name:
                norm_field = field_name.lower().replace("_", "")
                for col in columns:
                    if col.lower().replace(" ", "").replace("_", "") == norm_field:
                        col_name = col
                        break
            col_for_field[field_name] = col_name or _default_column_name(field_name)

        # field name -> [alias keys] (reverse of alias_key -> column_name)
        aliases_for_field: Dict[str, List[str]] = {}
        for alias_key, col_name in aliases_map.items():
            for field_name, col in col_for_field.items():
                if col.lower().strip() == str(col_name).lower().strip():
                    aliases_for_field.setdefault(field_name, []).append(alias_key)

        fields = []
        for field_name, info in extraction_fields.items():
            col_name = col_for_field.get(field_name, _default_column_name(field_name))
            fields.append(ExtractionField(
                name=field_name,
                type=info.get("type", "string"),
                description=info.get("description", ""),
                aliases=aliases_for_field.get(field_name, []),
                required=col_name in required_columns or field_name in required_columns,
                column=col_name,
                # Preserve optional/advanced metadata (set by a user, or
                # round-tripping through ExtractionSchema.to_dict()) if present.
                extraction_owner=info.get("extraction_owner"),
                merge_policy=info.get("merge_policy"),
                format=info.get("format"),
            ))

        primary_key_fields = []
        for pk_col in primary_keys:
            match = next((f.name for f in fields if f.column == pk_col), None)
            primary_key_fields.append(match or pk_col)

        known_columns = {f.column for f in fields}
        extra_columns = [c for c in columns if c not in known_columns and c != "Additional Information"]
        extra_required_columns = [c for c in required_columns if c not in known_columns]

        return cls(
            name=data.get("name", data.get("sheet_name", "Untitled Extraction Schema")),
            fields=fields,
            primary_key_fields=primary_key_fields,
            extra_columns=extra_columns,
            extra_required_columns=extra_required_columns,
            dataset_name=data.get("dataset_name"),
            sheet_name=data.get("sheet_name", "General Web Data"),
            # Same "key present (even if empty)" vs "key absent" handling as
            # from_dict()'s new-shape branch - see the comment there. A raw
            # templates/*/schema.json genuinely has no metadata_columns key
            # (defaults to both enabled); a schema round-tripped through
            # to_dict() -> SchemaStore -> back through this same legacy-shape
            # branch (see to_dict()'s docstring - persisted schemas are
            # always saved in this shape) must preserve whatever the user
            # actually chose, including an explicit empty list.
            metadata_columns=list(data["metadata_columns"]) if "metadata_columns" in data else _default_metadata_columns(),
        )

    @classmethod
    def from_json_file(cls, path: str) -> "ExtractionSchema":
        with open(path, "r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    def to_dict(self) -> Dict[str, Any]:
        """
        Produces the legacy dict shape existing generic modules already
        consume: `extraction_fields` (for DeterministicExtractor and
        PromptBuilder), `columns` + `aliases` + `primary_key` (for
        SchemaMapper and RecordMapper).
        """
        extraction_fields = {f.name: f.to_dict() for f in self.fields}

        columns = [f.column for f in self.fields]
        for extra_col in self.extra_columns:
            if extra_col not in columns:
                columns.append(extra_col)
        if self.additional_information_column not in columns:
            columns.append(self.additional_information_column)

        aliases: Dict[str, str] = {}
        for f in self.fields:
            aliases[f.name] = f.column
            aliases[f.name.replace("_", " ")] = f.column
            for alias in f.aliases:
                aliases[alias] = f.column
        # Identity aliases for extra columns (e.g. "source url" -> "Source
        # URL") so a field with no declared ExtractionField (Source URL is
        # populated by the pipeline itself, not extracted from the page)
        # still resolves during schema mapping.
        for extra_col in self.extra_columns:
            aliases.setdefault(extra_col.lower(), extra_col)
            aliases.setdefault(extra_col.lower().replace(" ", "_"), extra_col)

        primary_key_columns = []
        for pk_field_name in self.primary_key_fields:
            matched = self.get_field(pk_field_name)
            primary_key_columns.append(matched.column if matched else pk_field_name)

        required_fields = [f.column for f in self.fields if f.required] + list(self.extra_required_columns)

        result = {
            "name": self.name,
            "extraction_fields": extraction_fields,
            "columns": columns,
            "aliases": aliases,
            "primary_key": primary_key_columns,
            "required_fields": required_fields,
            "sheet_name": self.sheet_name,
            # Deliberately NOT merged into `columns`/`aliases` above - these
            # are resolved directly from pipeline metadata by DatasetBuilder,
            # never through AliasRegistry/SchemaMapper (which never reads
            # this key at all). See core/field_matching.SUPPORTED_METADATA_COLUMNS.
            "metadata_columns": list(self.metadata_columns),
        }
        if self.dataset_name:
            result["dataset_name"] = self.dataset_name
        return result
