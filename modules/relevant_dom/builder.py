"""
builder.py
==========
RelevantDOMBuilder — Domain-Aware HTML filter.

Responsibility
--------------
Decide which sections of a cleaned HTML page are worth keeping before
sending the page to Gemini.  This module never extracts business values,
never uses fixed CSS selectors, and never parses currency or dates.

Algorithm (five phases)
------------------------
A  Hard removal   – decompose structural noise tags (nav, footer, …)
B  Section scoring – assign a relevance score to each block element
C  Decision        – decompose blocks whose score < keep_threshold
D  Contact check   – warn if phone/email was filtered out
E  Cleanup         – remove empty elements, compact whitespace

Scoring uses only the profile's keyword lists. A section passes Phase C
if ANY of these contributes a net non-negative score:
  • A heading inside the section matches a keep_heading_keyword
  • A class / id / aria-label matches a keep_class/id_keyword
  • The section contains a <table> with a header row (<th>)
  • The section contains a phone number, email, or address keyword
"""

from __future__ import annotations

import re
import time
from typing import List

from bs4 import BeautifulSoup, Tag, NavigableString

from modules.domain_profiles.base import DomainProfile
from modules.preprocessor import estimate_tokens
from utils.logger import get_logger

logger = get_logger(__name__)


class RelevantDOMBuilder:
    """
    Filters *cleaned_html* using the rules in *profile*.

    Typical usage
    -------------
        profile = DomainProfileLoader.load(url)
        filtered_html = RelevantDOMBuilder(profile).build(cleaned_html, url)

    The returned string is a compact HTML fragment ready to be passed directly
    to ``extract_web_data()`` — no other changes to the pipeline are needed.
    """

    # Tags eligible for Phase B/C scoring (block-level containers).
    # Excludes inline and leaf elements (p, li, span, …) to keep scoring
    # at the section level rather than paragraph level.
    _SCORING_TAGS: frozenset = frozenset({
        "div", "section", "article", "main", "aside",
        "form", "header", "footer", "nav",
    })

    # Tags to check for emptiness in Phase E cleanup.
    _CLEANUP_TAGS: frozenset = frozenset({
        "div", "section", "article", "main", "aside",
        "p", "ul", "ol", "dl", "span",
    })

    # Regex patterns for contact detection.
    _PHONE_RE = re.compile(r"\+?\d[\d\s\-\(\)]{6,}\d")
    _EMAIL_RE = re.compile(r"[\w.\-_+]+@[\w.\-_]+\.[a-zA-Z]{2,}")

    # Address / location keywords.
    _ADDRESS_KW: frozenset = frozenset({
        "address", "location", "street", "city", "state",
        "pincode", "zip code", "postal", "office",
    })

    # Maximum recursion depth (guard against pathologically nested pages).
    _MAX_DEPTH: int = 12

    def __init__(self, profile: DomainProfile, schema: Optional[dict] = None, config: Optional[dict] = None):
        self.profile = profile
        self.schema = schema or {}
        self.config = config or {}
        
        # Build dynamic CRITICAL keyword checks
        self.critical_keywords = set()
        
        # 1. Add schema fields, columns, and aliases to dynamic preservation list
        if self.schema:
            for col in self.schema.get("columns", []):
                self.critical_keywords.add(str(col).strip().lower())
            aliases = self.schema.get("aliases", {})
            for k, v in aliases.items():
                self.critical_keywords.add(str(k).strip().lower())
                self.critical_keywords.add(str(v).strip().lower())
            ext_fields = self.schema.get("extraction_fields", {})
            for k in ext_fields.keys():
                self.critical_keywords.add(str(k).strip().lower())

        # 2. Add config semantic_keywords (contact, financial, training) if available
        # Default fallback semantic keywords if config is empty
        default_semantic_kws = {
            "financial": ["investment", "capital", "roi", "payback", "royalty", "fee", "cost"],
            "contact": ["phone", "email", "address", "location", "maps.google", "wa.me", "tel", "mailto"],
            "training": ["training", "support", "assistance"]
        }
        semantic_kws = self.config.get("semantic_keywords", {}) if isinstance(self.config, dict) else {}
        
        # If config is empty/missing, check fallback to default
        financial_list = semantic_kws.get("financial") if isinstance(semantic_kws, dict) else None
        if not financial_list:
            financial_list = default_semantic_kws["financial"]
            
        contact_list = semantic_kws.get("contact") if isinstance(semantic_kws, dict) else None
        if not contact_list:
            contact_list = default_semantic_kws["contact"]
            
        training_list = semantic_kws.get("training") if isinstance(semantic_kws, dict) else None
        if not training_list:
            training_list = default_semantic_kws["training"]
            
        self.critical_keywords.update(financial_list)
        self.critical_keywords.update(contact_list)
        self.critical_keywords.update(training_list)
        
        # Make sure they are cleaned
        self.critical_keywords = {k.lower().strip() for k in self.critical_keywords if k}

    def _is_critical_node(self, element: Tag) -> bool:
        """
        Determines if element or any of its descendants contain critical keywords,
        phones, emails, or location signals.
        """
        text = element.get_text(" ", strip=True).lower()
        if any(kw in text for kw in self.critical_keywords):
            return True
            
        # Regex check for phone / email
        if self._PHONE_RE.search(text) or self._EMAIL_RE.search(text):
            return True
            
        # Address keywords
        if any(kw in text for kw in self._ADDRESS_KW):
            return True
            
        return False

    # ── Public API ─────────────────────────────────────────────────────────────

    def build(self, cleaned_html: str, url: str = "") -> str:
        """
        Filters *cleaned_html* and returns a compact, reduced HTML string.

        Parameters
        ----------
        cleaned_html : str  — output of ``preprocessor.clean_html()``
        url          : str  — original URL used only for log messages

        Returns
        -------
        str — filtered HTML, always smaller than (or equal to) the input
        """
        if not cleaned_html:
            return ""

        start_time = time.perf_counter()

        original_size   = len(cleaned_html)
        original_tokens = estimate_tokens(cleaned_html)

        soup = BeautifulSoup(cleaned_html, "html.parser")

        # Counters passed by reference as single-element lists.
        removed = [0]
        kept    = [0]

        # ── Phase A: Hard removal ─────────────────────────────────────────────
        self._phase_a(soup, removed)

        # ── Phase B+C: Score and filter ───────────────────────────────────────
        root = soup.find("body") or soup
        self._process_subtree(root, removed, kept, depth=0)

        # ── Phase D: Contact safety net ───────────────────────────────────────
        self._phase_d(soup, url)

        # ── Phase E: Cleanup ──────────────────────────────────────────────────
        filtered_html = self._phase_e(soup)

        # ── Logging ───────────────────────────────────────────────────────────
        filtered_size   = len(filtered_html)
        filtered_tokens = estimate_tokens(filtered_html)
        elapsed_ms      = int((time.perf_counter() - start_time) * 1000)
        reduction_pct   = (
            100.0 * (original_tokens - filtered_tokens) / original_tokens
            if original_tokens > 0 else 0.0
        )

        # Cache metrics on the builder instance for pipeline logs
        self.original_tokens = original_tokens
        self.filtered_tokens = filtered_tokens
        self.reduction_pct = reduction_pct
        self.sections_kept = kept[0]
        self.sections_removed = removed[0]

        logger.info(
            "\n=== Relevant DOM Builder ===\n"
            f"URL:              {url}\n"
            f"Domain:           {self.profile.domain}\n"
            f"Profile:          {self.profile.name}\n"
            f"Original size:    {original_size / 1024:.1f} KB  "
            f"(≈{original_tokens:,} tokens)\n"
            f"Filtered size:    {filtered_size / 1024:.1f} KB  "
            f"(≈{filtered_tokens:,} tokens)\n"
            f"Token reduction:  {reduction_pct:.1f}%\n"
            f"Sections kept:    {kept[0]}\n"
            f"Sections removed: {removed[0]}\n"
            f"Execution time:   {elapsed_ms}ms\n"
            "==========================="
        )

        return filtered_html

    # ── Phase A: Hard removal ──────────────────────────────────────────────────

    def _phase_a(self, soup: BeautifulSoup, removed: List[int]) -> None:
        """Decompose structural tags and elements with noise class/id/aria names listed in profile."""
        # 1. Tag name hard removal
        for tag_name in self.profile.remove_tag_names:
            for element in soup.find_all(tag_name):
                element.decompose()
                removed[0] += 1

        # 2. Decompose elements matching class, id, and aria removal keywords
        for element in soup.find_all(True):
            if element.parent is None or element.name in ("html", "body"):
                continue

            # Remove hidden elements
            style = (element.get("style") or "").lower().replace(" ", "")
            if "display:none" in style or "visibility:hidden" in style:
                element.decompose()
                removed[0] += 1
                continue

            # Extract identifier attributes
            raw_classes = element.get("class", [])
            elem_classes = " ".join(raw_classes if isinstance(raw_classes, list) else [raw_classes]).lower()
            elem_id = (element.get("id") or "").lower()
            elem_aria = (element.get("aria-label") or "").lower()
            elem_role = (element.get("role") or "").lower()

            # Unconditional removal checks
            matched_remove = False
            for kw in self.profile.remove_class_keywords:
                if kw.lower() in elem_classes:
                    element.decompose()
                    matched_remove = True
                    removed[0] += 1
                    break

            if matched_remove or element.parent is None:
                continue

            for kw in self.profile.remove_id_keywords:
                if kw.lower() in elem_id:
                    element.decompose()
                    matched_remove = True
                    removed[0] += 1
                    break

            if matched_remove or element.parent is None:
                continue

            for kw in self.profile.remove_aria_keywords:
                if kw.lower() in elem_aria or kw.lower() in elem_role:
                    element.decompose()
                    removed[0] += 1
                    break

    # ── Phase B+C: Recursive scoring and filtering ─────────────────────────────

    def _process_subtree(
        self,
        root: Tag,
        removed: List[int],
        kept: List[int],
        depth: int,
    ) -> None:
        """
        Recursively walks block-level children of *root*, scoring each.

        Children that score below ``profile.keep_threshold`` are decomposed.
        For children that pass, recursion continues so that bad sub-sections
        nested inside good containers are also removed.
        """
        if depth > self._MAX_DEPTH:
            return

        # Snapshot children before mutating the tree.
        block_children = [
            child
            for child in root.children
            if isinstance(child, Tag) and child.name in self._SCORING_TAGS
        ]

        for child in block_children:
            # Skip elements already decomposed by an earlier iteration.
            if child.parent is None:
                continue

            score = self._score_element(child)

            if score < self.profile.keep_threshold:
                # If the node is CRITICAL level, preserve it!
                if self._is_critical_node(child):
                    kept[0] += 1
                    # Recurse into positive blocks to remove bad nested sub-sections.
                    has_nested = any(
                        isinstance(c, Tag) and c.name in self._SCORING_TAGS
                        for c in child.children
                    )
                    if has_nested:
                        self._process_subtree(child, removed, kept, depth + 1)
                else:
                    child.decompose()
                    removed[0] += 1
            else:
                kept[0] += 1
                # Recurse into positive blocks to remove bad nested sub-sections.
                has_nested = any(
                    isinstance(c, Tag) and c.name in self._SCORING_TAGS
                    for c in child.children
                )
                if has_nested:
                    self._process_subtree(child, removed, kept, depth + 1)

    def _score_element(self, element: Tag) -> float:
        """
        Computes a relevance score for *element* using the profile's rules.

        Score >= 0 → keep.   Score < 0 → remove.
        """
        profile = self.profile
        score   = 0.0

        # ── Tag-level hard-remove signal (should be caught in Phase A already) ─
        if element.name in profile.remove_tag_names:
            return profile.tag_remove_score  # strongly negative

        # ── Collect identifier strings ────────────────────────────────────────
        raw_classes = element.get("class", [])
        elem_classes = " ".join(
            raw_classes if isinstance(raw_classes, list) else [raw_classes]
        ).lower()
        elem_id    = (element.get("id")         or "").lower()
        elem_aria  = (element.get("aria-label") or "").lower()
        elem_role  = (element.get("role")       or "").lower()
        identifiers = f"{elem_classes} {elem_id} {elem_aria} {elem_role}"

        # ── Class / ID / ARIA removal signals ─────────────────────────────────
        for kw in profile.remove_class_keywords:
            if kw.lower() in identifiers:
                score += profile.class_remove_score

        for kw in profile.remove_id_keywords:
            if kw.lower() in elem_id:
                score += profile.class_remove_score

        for kw in profile.remove_aria_keywords:
            if kw.lower() in elem_aria or kw.lower() in elem_role:
                score += profile.class_remove_score

        # ── Class / ID keep signals ────────────────────────────────────────────
        for kw in profile.keep_class_keywords:
            if kw.lower() in identifiers:
                score += profile.class_keep_score

        for kw in profile.keep_id_keywords:
            if kw.lower() in elem_id:
                score += profile.class_keep_score

        # ── Heading text signals ───────────────────────────────────────────────
        # Find all headings inside this element (recursive, so nested headings count).
        for heading in element.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            heading_text = heading.get_text(" ", strip=True).lower()

            # Keep signals are checked first; a single match is sufficient per heading.
            matched_keep = False
            for kw in profile.keep_heading_keywords:
                if kw.lower() in heading_text:
                    score += profile.heading_keep_score
                    matched_keep = True
                    break

            # Only check remove signals if no keep keyword matched this heading.
            if not matched_keep:
                for kw in profile.remove_heading_keywords:
                    if kw.lower() in heading_text:
                        score += profile.heading_remove_score
                        break

        # ── Table bonus ───────────────────────────────────────────────────────
        if profile.keep_tables:
            for table in element.find_all("table"):
                # Only business tables (have header row or caption), not layout tables.
                if table.find("th") or table.find("caption"):
                    score += profile.table_score
                    break  # one qualifying table is enough

        # ── Contact bonus ─────────────────────────────────────────────────────
        if profile.keep_contact_blocks:
            text = element.get_text(" ", strip=True).lower()
            if self._PHONE_RE.search(text):
                score += profile.contact_score
            elif self._EMAIL_RE.search(text):
                score += profile.contact_score
            elif any(kw in text for kw in self._ADDRESS_KW):
                score += profile.contact_score * 0.5  # partial credit

        if self._is_critical_node(element):
            score = max(score, self.profile.keep_threshold)

        return score

    # ── Phase D: Contact safety net ───────────────────────────────────────────

    def _phase_d(self, soup: BeautifulSoup, url: str) -> None:
        """
        Logs a warning if filtering appears to have removed all contact info.

        Note: contact blocks usually score ≥ +10 (contact_score) so they
        survive Phase C. This check catches edge cases where contact info was
        only inside a footer/nav that was hard-removed in Phase A.
        """
        page_text = soup.get_text(" ", strip=True)
        has_phone = bool(self._PHONE_RE.search(page_text))
        has_email = bool(self._EMAIL_RE.search(page_text))

        if not has_phone and not has_email:
            logger.warning(
                f"RelevantDOMBuilder: no phone/email found after filtering for {url}. "
                "If contact info was inside the footer/nav, consider adding it to "
                "the profile's keep_contact_blocks or adjusting remove_tag_names."
            )

    # ── Phase E: Cleanup ──────────────────────────────────────────────────────

    def _phase_e(self, soup: BeautifulSoup) -> str:
        """
        Iteratively removes empty block elements and returns compact HTML.

        Runs up to 5 passes because removing a block can leave its parent empty,
        which can then also be removed.
        """
        for _ in range(5):
            changed = False
            for element in soup.find_all(list(self._CLEANUP_TAGS)):
                if element.parent is None:
                    continue
                # Remove if: no visible text AND no preserved leaf tags.
                has_text = bool(element.get_text(strip=True))
                has_leaf = bool(element.find(["img", "input", "button", "a", "table"]))
                if not has_text and not has_leaf:
                    element.decompose()
                    changed = True
            if not changed:
                break

        # Compact whitespace (same format as preprocessor.clean_html output).
        return " ".join(str(soup).split())
