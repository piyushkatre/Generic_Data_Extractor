"""
ConfigStore
===========
Save/load/list/delete WebsiteConfig records - what makes a WebsiteConfig
reusable (create it once through the UI or a script, run many jobs against
it later) instead of a one-off object built inline for a single run.

No versioning yet: saving under an existing id overwrites that record.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from config._file_store import JsonFileStore
from config._util import slugify
from config.website_config import WebsiteConfig


class ConfigStore:
    def __init__(self, storage_dir: str = "storage/configs"):
        self._store = JsonFileStore(
            storage_dir,
            to_dict=lambda wc: wc.to_dict(),
            from_dict=lambda d: WebsiteConfig.from_dict(d),
        )

    def save(self, website_config: WebsiteConfig, config_id: Optional[str] = None) -> str:
        config_id = config_id or f"{slugify(website_config.name, fallback='config')}-{uuid.uuid4().hex[:8]}"
        return self._store.save(config_id, website_config)

    def load(self, config_id: str) -> WebsiteConfig:
        return self._store.load(config_id)

    def delete(self, config_id: str) -> None:
        self._store.delete(config_id)

    def exists(self, config_id: str) -> bool:
        return self._store.exists(config_id)

    def list(self) -> List[Dict[str, str]]:
        """Cheap listing: id + name + domain for every saved config,
        without fully rehydrating each one into a WebsiteConfig object."""
        summaries = []
        for config_id in self._store.list_ids():
            raw = self._store.load_raw(config_id)
            summaries.append({
                "id": config_id,
                "name": raw.get("name", "Untitled Website Configuration"),
                "domain": raw.get("domain", "*"),
            })
        return summaries
