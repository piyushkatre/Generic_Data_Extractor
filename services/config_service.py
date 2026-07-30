"""
ConfigService
=============
The only thing a UI (or any caller) should ever touch to create, read,
update, delete, or list WebsiteConfig records - it never opens ConfigStore
directly.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

from config.config_store import ConfigStore
from config.website_config import WebsiteConfig
from services.errors import NotFoundError, DuplicateNameError

_ConfigInput = Union[Dict[str, Any], WebsiteConfig]


class ConfigService:
    def __init__(self, store: Optional[ConfigStore] = None):
        self.store = store or ConfigStore()

    def create(self, data: _ConfigInput) -> str:
        """Validates, checks for a duplicate name, and saves a new WebsiteConfig.
        Raises config.errors.ValidationError or DuplicateNameError."""
        website_config = self._coerce(data)
        self._check_duplicate_name(website_config.name)
        return self.store.save(website_config)

    def get(self, config_id: str) -> WebsiteConfig:
        try:
            return self.store.load(config_id)
        except KeyError as e:
            raise NotFoundError(f"No WebsiteConfig found with id '{config_id}'.") from e

    def update(self, config_id: str, data: _ConfigInput) -> WebsiteConfig:
        if not self.store.exists(config_id):
            raise NotFoundError(f"No WebsiteConfig found with id '{config_id}'.")
        website_config = self._coerce(data)
        self.store.save(website_config, config_id=config_id)
        return website_config

    def delete(self, config_id: str) -> None:
        if not self.store.exists(config_id):
            raise NotFoundError(f"No WebsiteConfig found with id '{config_id}'.")
        self.store.delete(config_id)

    def list(self) -> List[Dict[str, str]]:
        return self.store.list()

    @staticmethod
    def _coerce(data: _ConfigInput) -> WebsiteConfig:
        website_config = data if isinstance(data, WebsiteConfig) else WebsiteConfig.from_dict(data)
        website_config.validate()
        return website_config

    def _check_duplicate_name(self, name: str) -> None:
        existing = {row["name"].strip().lower() for row in self.store.list()}
        if name.strip().lower() in existing:
            raise DuplicateNameError(
                f"A WebsiteConfig named '{name}' already exists. Choose a different name, "
                "or call update() on the existing one instead of create()."
            )
