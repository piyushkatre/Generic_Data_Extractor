import os
import json
from typing import Any, Dict, List, Optional, Type, Union

from pydantic import BaseModel, Field, create_model

_VALID_FIELD_TYPES = {"string", "array", "integer", "number", "boolean"}


class SchemaLoader:
    """
    Load Schema -> Validate Schema -> Build Dynamic Model.

    `load_schema()` (below, unchanged) resolves a page-type string to one of
    the legacy `schemas/*.json` files - kept as an optional "suggest a
    starting template" helper, not a mandatory runtime dependency.

    `build_model()` (new) is the schema-driven replacement for
    Adapter.get_model(): it builds a dynamic Pydantic model with NO
    inheritance from a franchise-shaped base class - just a small universal
    core (see modules/dataset_builder/generic_record.py) plus whatever
    fields the schema declares.
    """

    def __init__(self, schemas_dir: str = "schemas"):
        # Resolve path relative to project root or use absolute path
        self.schemas_dir = os.path.abspath(schemas_dir)
        
        # Map extracted page_type categories to correct schema filenames
        self.page_type_map = {
            "franchise listing": "franchise_schema.json",
            "franchise page": "franchise_schema.json",
            "franchise": "franchise_schema.json",
            
            "company website": "company_schema.json",
            "organization": "company_schema.json",
            
            "product page": "product_schema.json",
            "product listing": "product_schema.json",
            "product": "product_schema.json",
            
            "blog": "blog_schema.json",
            "news article": "blog_schema.json",
            "article": "blog_schema.json",
            
            "government website": "government_schema.json",
            "government": "government_schema.json",
            
            "documentation": "documentation_schema.json",
            "faq": "documentation_schema.json",
            "faq page": "documentation_schema.json"
        }

    def load_schema(self, page_type: str) -> Dict[str, Any]:
        """
        Loads the appropriate schema dict for the given page_type.
        Falls back to misc_schema.json if no matching schema is found.
        """
        cleaned_type = str(page_type).strip().lower()
        filename = self.page_type_map.get(cleaned_type, "misc_schema.json")
        schema_path = os.path.join(self.schemas_dir, filename)
        
        if not os.path.exists(schema_path):
            # Fall back to misc_schema.json
            schema_path = os.path.join(self.schemas_dir, "misc_schema.json")
            if not os.path.exists(schema_path):
                # Critical fallback: default empty dictionary schema template
                return {
                    "dataset_name": "misc_dataset.xlsx",
                    "sheet_name": "General Web Data",
                    "primary_key": ["Source URL", "Title"],
                    "required_fields": ["Title", "Source URL"],
                    "aliases": {"title": "Title", "source url": "Source URL"},
                    "columns": ["Source URL", "Title", "Additional Information", "Extraction Date", "Last Updated"]
                }
                
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def build_model(schema: Union[Any, Dict[str, Any]]) -> Type[BaseModel]:
        """
        Builds a dynamic Pydantic model purely from the given schema's
        declared fields, with no franchise-base-class inheritance.

        Accepts either a config.extraction_schema.ExtractionSchema object
        (preferred) or a legacy schema dict (adapters/*/schema.json shape) -
        anything exposing extraction_fields/columns/aliases in that shape.
        """
        from modules.dataset_builder.generic_record import GenericExtractionRecord

        schema_dict = schema.to_dict() if hasattr(schema, "to_dict") else (schema or {})
        extraction_fields = schema_dict.get("extraction_fields", {}) or {}
        SchemaLoader._validate_extraction_fields(extraction_fields)

        entity_type_label = schema_dict.get("name") or "Extracted Record"

        fields: Dict[str, Any] = {
            "page_type": (Optional[str], Field(default=entity_type_label, description="Type of the page/record")),
        }
        for field_name, field_info in extraction_fields.items():
            field_type = str(field_info.get("type", "string")).lower()
            field_desc = field_info.get("description", "")

            if field_type == "array":
                fields[field_name] = (Optional[List[str]], Field(default_factory=list, description=field_desc))
            elif field_type == "integer":
                fields[field_name] = (Optional[int], Field(default=None, description=field_desc))
            elif field_type == "number":
                fields[field_name] = (Optional[float], Field(default=None, description=field_desc))
            elif field_type == "boolean":
                fields[field_name] = (Optional[bool], Field(default=None, description=field_desc))
            else:
                fields[field_name] = (Optional[str], Field(default=None, description=field_desc))

        def to_clean_dict(self) -> Dict[str, Any]:
            d = self.model_dump()
            label = self.page_type or entity_type_label
            return {
                "page_title": self.page_title or self.source_url or "Untitled Page",
                "page_type": label,
                "page_summary": self.page_summary or "",
                "entities": {label: [d]},
            }

        DynamicModel = create_model(
            "SchemaExtractionRecord",
            **fields,
            __base__=GenericExtractionRecord,
        )
        DynamicModel.to_clean_dict = to_clean_dict
        return DynamicModel

    @staticmethod
    def _validate_extraction_fields(extraction_fields: Dict[str, Any]) -> None:
        for field_name, info in extraction_fields.items():
            if not isinstance(info, dict):
                raise ValueError(f"Schema field '{field_name}' must be an object, got {type(info).__name__}")
            field_type = str(info.get("type", "string")).lower()
            if field_type not in _VALID_FIELD_TYPES:
                raise ValueError(
                    f"Schema field '{field_name}' has invalid type '{field_type}' "
                    f"(expected one of {sorted(_VALID_FIELD_TYPES)})"
                )
