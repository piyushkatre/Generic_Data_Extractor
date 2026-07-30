"""
SchemaStore
===========
Save/load/list/delete ExtractionSchema records - the schema equivalent of
ConfigStore. No versioning yet: saving under an existing id overwrites that
record.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from config._file_store import JsonFileStore
from config._util import slugify
from config.extraction_schema import ExtractionSchema


class SchemaStore:
    def __init__(self, storage_dir: str = "storage/schemas"):
        self._store = JsonFileStore(
            storage_dir,
            to_dict=lambda es: es.to_dict(),
            from_dict=lambda d: ExtractionSchema.from_dict(d),
        )

    def save(self, extraction_schema: ExtractionSchema, schema_id: Optional[str] = None) -> str:
        schema_id = schema_id or f"{slugify(extraction_schema.name, fallback='schema')}-{uuid.uuid4().hex[:8]}"
        return self._store.save(schema_id, extraction_schema)

    def load(self, schema_id: str) -> ExtractionSchema:
        return self._store.load(schema_id)

    def delete(self, schema_id: str) -> None:
        self._store.delete(schema_id)

    def exists(self, schema_id: str) -> bool:
        return self._store.exists(schema_id)

    def list(self) -> List[Dict[str, str]]:
        """Cheap listing: id + name + field count for every saved schema."""
        summaries = []
        for schema_id in self._store.list_ids():
            raw = self._store.load_raw(schema_id)
            summaries.append({
                "id": schema_id,
                "name": raw.get("name", "Untitled Extraction Schema"),
                "field_count": len(raw.get("extraction_fields", {})),
            })
        return summaries
