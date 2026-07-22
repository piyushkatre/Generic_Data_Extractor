"""
domain_profiles package
=======================
Each module in this package defines one DomainProfile — a plain data object
that tells RelevantDOMBuilder which sections of a page are worth keeping.

Profiles never parse business values; they only describe what HTML is useful.

Adding a new website
--------------------
1. Create  modules/domain_profiles/mysite.py   (return a DomainProfile)
2. Register in DomainProfileLoader._REGISTRY:
       "mysite.com": MySiteProfile()
No other code needs to change.
"""

from modules.domain_profiles.base import DomainProfile
from modules.domain_profiles.loader import DomainProfileLoader

__all__ = [
    "DomainProfile",
    "DomainProfileLoader",
]
