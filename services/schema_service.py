"""
SchemaService
=============
The only thing a UI (or any caller) should ever touch to create, read,
update, delete, or list ExtractionSchema records - it never opens
SchemaStore directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from config.schema_store import SchemaStore
from config.extraction_schema import ExtractionSchema
from services.errors import NotFoundError, DuplicateNameError

_SchemaInput = Union[Dict[str, Any], ExtractionSchema]


class SchemaService:
    def __init__(self, store: Optional[SchemaStore] = None):
        self.store = store or SchemaStore()

    def create(self, data: _SchemaInput) -> str:
        """Validates, checks for a duplicate name, and saves a new ExtractionSchema.
        Raises config.errors.ValidationError or DuplicateNameError."""
        extraction_schema = self._coerce(data)
        self._check_duplicate_name(extraction_schema.name)
        return self.store.save(extraction_schema)

    def get(self, schema_id: str) -> ExtractionSchema:
        try:
            return self.store.load(schema_id)
        except KeyError as e:
            raise NotFoundError(f"No ExtractionSchema found with id '{schema_id}'.") from e

    def update(self, schema_id: str, data: _SchemaInput) -> ExtractionSchema:
        if not self.store.exists(schema_id):
            raise NotFoundError(f"No ExtractionSchema found with id '{schema_id}'.")
        extraction_schema = self._coerce(data)
        self.store.save(extraction_schema, schema_id=schema_id)
        return extraction_schema

    def delete(self, schema_id: str) -> None:
        if not self.store.exists(schema_id):
            raise NotFoundError(f"No ExtractionSchema found with id '{schema_id}'.")
        self.store.delete(schema_id)

    def list(self) -> List[Dict[str, Any]]:
        return self.store.list()

    @staticmethod
    def _coerce(data: _SchemaInput) -> ExtractionSchema:
        extraction_schema = data if isinstance(data, ExtractionSchema) else ExtractionSchema.from_dict(data)
        extraction_schema.validate()
        return extraction_schema

    def _check_duplicate_name(self, name: str) -> None:
        existing = {row["name"].strip().lower() for row in self.store.list()}
        if name.strip().lower() in existing:
            raise DuplicateNameError(
                f"An ExtractionSchema named '{name}' already exists. Choose a different name, "
                "or call update() on the existing one instead of create()."
            )
