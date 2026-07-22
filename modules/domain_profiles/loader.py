"""
loader.py
=========
DomainProfileLoader — maps any URL to the most appropriate DomainProfile dynamically using adapters.
"""

from __future__ import annotations

from modules.domain_profiles.base import DomainProfile
from utils.logger import get_logger

logger = get_logger(__name__)


class DomainProfileLoader:
    """
    Registry-based loader that maps registrable domain names to profiles dynamically using adapters.
    """
    _CUSTOM_REGISTRY = {}
    _REGISTRY = _CUSTOM_REGISTRY

    @classmethod
    def load(cls, url: str) -> DomainProfile:
        """
        Returns the DomainProfile for *url*, falling back to DefaultProfile.

        Parameters
        ----------
        url : str — any valid URL (with or without scheme)
        """
        from urllib.parse import urlparse
        domain = url.lower()
        try:
            url_str = url
            if "://" not in url:
                url_str = "https://" + url
            parsed = urlparse(url_str)
            hostname = (parsed.netloc or "").split(":")[0].strip().lower()
            if hostname.startswith("www."):
                hostname = hostname[4:]
            domain = hostname or url.lower()
        except Exception:
            pass

        # Check manual registry first
        for registered_domain, profile in cls._CUSTOM_REGISTRY.items():
            if domain == registered_domain or domain.endswith("." + registered_domain):
                return profile

        from modules.adapter_loader import AdapterLoader
        adapter = AdapterLoader.load(url)
        profile = adapter.get_profile()
        logger.info(
            f"DomainProfileLoader: matched '{url}' to '{adapter.name}' profile"
        )
        return profile

    @classmethod
    def register(cls, domain: str, profile: DomainProfile) -> None:
        """
        Legacy registration method. Retained for backwards compatibility.
        """
        cls._CUSTOM_REGISTRY[domain] = profile
        logger.info(f"DomainProfileLoader: registered '{profile.name}' for '{domain}' manually.")
