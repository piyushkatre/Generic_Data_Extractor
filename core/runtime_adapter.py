"""
RuntimeAdapter
==============
Per review feedback: the adapter *concept* is kept, not deleted. What
changes is where it comes from - a RuntimeAdapter is assembled in-memory
from a WebsiteConfig + ExtractionSchema (provided by a caller, a UI, or a
template loader) instead of being read from an `adapters/<site>/` folder
matched by URL domain at pipeline time.

RuntimeAdapter exposes the exact same surface ExtractionPipeline already
expects from today's `Adapter` (`.config`, `.schema`, `.name`, `.domain`,
`.priority`, `.get_profile()`, `.get_model()`), which is why the rest of the
pipeline - and modules/browser.py, modules/preprocessor.py,
modules/relevant_dom/builder.py, which all read `.config`/`.schema` - need
no interface change at all.

`from_adapter()` bridges today's file-based Adapter (still loaded via
AdapterLoader from templates/) into a RuntimeAdapter, so the transition
doesn't require every caller to construct a WebsiteConfig/ExtractionSchema
by hand right away.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from pydantic import BaseModel

from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from modules.domain_profiles.base import DomainProfile
from modules.dataset_builder.schema_loader import SchemaLoader


class RuntimeAdapter:
    """
    Same duck-typed interface as modules.adapter_loader.Adapter, built
    in-memory from a WebsiteConfig + ExtractionSchema pair.
    """

    def __init__(
        self,
        website_config: WebsiteConfig,
        extraction_schema: ExtractionSchema,
        name: Optional[str] = None,
    ):
        self.website_config = website_config
        self.extraction_schema = extraction_schema

        self.name = name or website_config.name
        self.domain = website_config.domain
        self.domains = website_config.domains
        self.aliases = website_config.aliases
        self.priority = website_config.priority
        self.version = website_config.version
        self.metadata = website_config.metadata

        # Legacy dict-shaped surface existing generic modules already read.
        self.config: Dict[str, Any] = website_config.to_dict()
        self.schema: Dict[str, Any] = extraction_schema.to_dict()

        self._model_cache: Optional[Type[BaseModel]] = None

    def get_profile(self) -> DomainProfile:
        return self.website_config.to_pruning_profile()

    def get_model(self) -> Type[BaseModel]:
        if self._model_cache is None:
            self._model_cache = SchemaLoader.build_model(self.extraction_schema)
        return self._model_cache

    @classmethod
    def from_config_and_schema(
        cls,
        website_config: WebsiteConfig,
        extraction_schema: ExtractionSchema,
        name: Optional[str] = None,
    ) -> "RuntimeAdapter":
        return cls(website_config, extraction_schema, name=name)

    @classmethod
    def from_adapter(cls, adapter: Any) -> "RuntimeAdapter":
        """
        Bridges a legacy, file-loaded modules.adapter_loader.Adapter (as
        returned by AdapterLoader.load(url), reading from templates/) into a
        RuntimeAdapter - so nothing calling AdapterLoader today has to change
        before WebsiteConfig/ExtractionSchema are authored directly.
        """
        website_config = WebsiteConfig.from_dict(adapter.config)
        extraction_schema = ExtractionSchema.from_legacy_dict(adapter.schema)
        return cls(website_config, extraction_schema, name=getattr(adapter, "name", None))
