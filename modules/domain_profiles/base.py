"""
base.py
=======
DomainProfile dataclass — the single interface every domain profile implements.

A profile is **pure data**. It contains no DOM-parsing logic, no CSS selectors,
no extraction code. All filtering logic lives in RelevantDOMBuilder.

Design principles
-----------------
• Keyword matching is case-insensitive substring matching (no regex in profiles).
• Profiles describe *intent* ("keep investment sections"), not implementation.
• All fields have safe defaults so a minimal profile still works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class DomainProfile:
    """
    Declarative rules for one website (or the generic default).

    The RelevantDOMBuilder reads these rules and applies them — profiles
    never call BeautifulSoup or any HTML parser directly.
    """

    # ── Identity ───────────────────────────────────────────────────────────────
    domain: str   # "franchisebazar.com"  |  "*" for the default profile
    name:   str   # Human-readable label used in logs

    # ── Phase A: Hard structural removal (by tag name, unconditional) ──────────
    # These HTML tags are decomposed before any scoring takes place.
    remove_tag_names: List[str] = field(default_factory=list)

    # ── Phase B/C: Section REMOVAL signals ────────────────────────────────────
    # Each keyword is matched as a substring (case-insensitive) against:
    #   remove_heading_keywords → heading text (h1-h6 inside the element)
    #   remove_class_keywords   → element's class attribute(s)
    #   remove_id_keywords      → element's id attribute
    #   remove_aria_keywords    → aria-label or role attribute
    remove_heading_keywords: List[str] = field(default_factory=list)
    remove_class_keywords:   List[str] = field(default_factory=list)
    remove_id_keywords:      List[str] = field(default_factory=list)
    remove_aria_keywords:    List[str] = field(default_factory=list)

    # ── Phase B/C: Section KEEP signals (override removal if matched) ──────────
    keep_heading_keywords: List[str] = field(default_factory=list)
    keep_class_keywords:   List[str] = field(default_factory=list)
    keep_id_keywords:      List[str] = field(default_factory=list)

    # ── Universal preservation flags ───────────────────────────────────────────
    keep_tables:         bool = True   # <table> with <th> always kept
    keep_contact_blocks: bool = True   # blocks with phone/email/address always kept

    # ── Scoring weights (tunable per profile) ─────────────────────────────────
    heading_keep_score:   float = 10.0
    heading_remove_score: float = -8.0
    class_keep_score:     float =  5.0
    class_remove_score:   float = -6.0
    tag_remove_score:     float = -20.0  # used only if a remove_tag slips past Phase A
    table_score:          float =  8.0
    contact_score:        float = 10.0

    # ── Decision threshold ─────────────────────────────────────────────────────
    # Sections with  score >= keep_threshold  are preserved.
    # Sections with  score <  keep_threshold  are removed.
    keep_threshold: float = 0.0
