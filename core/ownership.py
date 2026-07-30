"""
OwnershipResolver
=================
Replaces the hand-rolled per-field merge branching that used to live inline
in core/pipeline.py (and, duplicated, in modules/gemini.py's now-removed
second orchestration path). Single implementation of "who owns this field,
deterministic extraction or the LLM, and how do we merge the two values."

Milestone 1 note: this still falls back to the existing, franchise-keyed
`core/field_strategy.FIELD_STRATEGY` table for its generic default - that
table is not schema-driven yet (a later milestone). What *is* schema-driven
already: an ExtractionField's own optional `extraction_owner`/`merge_policy`
attributes, when the user set them, always take priority over the table.
This means a schema field named anything the table doesn't recognize (once
normalized - see below) simply falls back to the table's own generic
unknown-field default ("llm", "llm_only") - it never silently behaves like
a franchise field it isn't.

The table's keys are canonical snake_case, but a schema's own field names
are free-form display text ("Franchise Fee", "Investment Required") - the
schema is the source of truth for field identity, so field_name is
normalized (core/field_matching.normalize_field_name) before the table
lookup, rather than requiring schema authors to know or use snake_case.

Like the Hybrid Merge dom-value lookup in core/pipeline.py, this table
lookup is also alias-aware (core/field_matching.resolve_by_alias): a field
named "Space Required" with alias "area required" gets the SAME strategy
as the table's "area_required" entry (owner=deterministic,
merge_policy=deterministic_first), not the generic unknown-field default -
otherwise a value resolve_by_alias() finds in core/pipeline.py's dom-value
lookup would still be discarded here, because "llm_only" (the unknown-field
default) ignores dom_val whenever the LLM didn't also find it.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from core.field_matching import normalize_field_name, resolve_by_alias
from core.field_strategy import FIELD_STRATEGY, get_strategy

_EMPTY = (None, "", [], {})


class OwnershipResolver:
    """Resolves field ownership/merge policy and applies the merge itself."""

    @staticmethod
    def get_strategy(field_name: str, extraction_field: Optional[Any] = None) -> Dict[str, Any]:
        """
        Returns the effective strategy dict for a field: `{owner, merge_policy, ...}`.
        An ExtractionField's own `extraction_owner`/`merge_policy`, if set,
        override the generic default from core/field_strategy.py.
        """
        aliases = getattr(extraction_field, "aliases", None) if extraction_field else None
        matched = resolve_by_alias(field_name, aliases, FIELD_STRATEGY)
        base = dict(matched) if matched is not None else dict(get_strategy(normalize_field_name(field_name)))

        owner_override = getattr(extraction_field, "extraction_owner", None) if extraction_field else None
        merge_override = getattr(extraction_field, "merge_policy", None) if extraction_field else None

        if owner_override:
            base["owner"] = owner_override
        if merge_override:
            base["merge_policy"] = merge_override
        return base

    @staticmethod
    def merge(
        field_name: str,
        dom_val: Any,
        gem_val: Any,
        extraction_field: Optional[Any] = None,
    ) -> Tuple[Any, str]:
        """
        Applies the field's merge policy to a deterministic value and an LLM
        value, returning (final_value, final_source), where final_source is
        one of "Deterministic", "LLM", or "None".
        """
        strategy = OwnershipResolver.get_strategy(field_name, extraction_field)
        merge_policy = strategy.get("merge_policy", "llm_only")

        dom_present = dom_val not in _EMPTY
        gem_present = gem_val not in _EMPTY

        if merge_policy == "deterministic_only":
            return (dom_val, "Deterministic") if dom_present else (None, "None")

        if merge_policy == "deterministic_first":
            if dom_present:
                return dom_val, "Deterministic"
            return (gem_val, "LLM") if gem_present else (None, "None")

        if merge_policy == "llm_first":
            if gem_present:
                return gem_val, "LLM"
            return (dom_val, "Deterministic") if dom_present else (None, "None")

        # "llm_only" and any unrecognized policy fall back to LLM-only.
        return (gem_val, "LLM") if gem_present else (None, "None")
