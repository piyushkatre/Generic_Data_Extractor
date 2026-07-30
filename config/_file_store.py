"""
Minimal file-backed CRUD store shared by ConfigStore, SchemaStore, and
JobStore: one JSON file per record, named by id, under a storage directory.

Deliberately minimal, per the "introduce gradually" / "don't overcomplicate"
guidance: no versioning (saving an existing id overwrites it - versioning is
a later milestone), no locking, no database. This is meant to be replaced or
extended, not to be the final storage design.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, TypeVar

T = TypeVar("T")


class JsonFileStore:
    def __init__(
        self,
        storage_dir: str,
        to_dict: Callable[[Any], Dict[str, Any]],
        from_dict: Callable[[Dict[str, Any]], Any],
    ):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
        self._to_dict = to_dict
        self._from_dict = from_dict

    def _path(self, record_id: str) -> str:
        return os.path.join(self.storage_dir, f"{record_id}.json")

    def exists(self, record_id: str) -> bool:
        return os.path.exists(self._path(record_id))

    def save(self, record_id: str, record: Any) -> str:
        with open(self._path(record_id), "w", encoding="utf-8") as f:
            json.dump(self._to_dict(record), f, indent=2, ensure_ascii=False)
        return record_id

    def load(self, record_id: str) -> Any:
        path = self._path(record_id)
        if not os.path.exists(path):
            raise KeyError(f"No record found with id '{record_id}' in {self.storage_dir}")
        with open(path, "r", encoding="utf-8") as f:
            return self._from_dict(json.load(f))

    def load_raw(self, record_id: str) -> Dict[str, Any]:
        """Loads the raw JSON dict without reconstructing the object - used
        for cheap listing (e.g. reading just a "name" field) without paying
        the cost of fully rehydrating every record."""
        path = self._path(record_id)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def delete(self, record_id: str) -> None:
        path = self._path(record_id)
        if os.path.exists(path):
            os.remove(path)

    def list_ids(self) -> List[str]:
        if not os.path.isdir(self.storage_dir):
            return []
        return sorted(
            fname[:-5] for fname in os.listdir(self.storage_dir)
            if fname.endswith(".json")
        )
