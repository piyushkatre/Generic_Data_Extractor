"""
Field-name normalization for matching a schema's own field names against
canonical/deterministic-extractor field names, regardless of the casing or
word-separator convention (spaces, hyphens, underscores) a schema author
used to name a field.

The schema is the source of truth for field identity and display text.
This is used ONLY for identity *comparison* during matching (PromptBuilder's
already-solved check, the Hybrid Merge lookup, OwnershipResolver's strategy
lookup) - never to alter anything user-visible. Schema display names,
output columns, Excel/CSV headers, and UI labels always keep the schema's
exact original text; only the comparison uses the normalized form.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

_WHITESPACE_OR_HYPHEN = re.compile(r"[\s\-]+")
_MULTI_UNDERSCORE = re.compile(r"_+")


def normalize_field_name(name: str) -> str:
    """
    'Franchise Fee'          -> 'franchise_fee'
    'Investment Required'    -> 'investment_required'
    'Source URL'             -> 'source_url'
    'Expected No of Hours'   -> 'expected_no_of_hours'
    """
    if not name:
        return ""
    normalized = name.strip().lower()
    normalized = _WHITESPACE_OR_HYPHEN.sub("_", normalized)
    normalized = _MULTI_UNDERSCORE.sub("_", normalized)
    return normalized


# ---------------------------------------------------------------------------
# Reserved pipeline metadata fields
# ---------------------------------------------------------------------------
# The single source of truth for which field identities belong to the
# pipeline itself, never to a user-authored schema. These are exactly the
# fields modules/dataset_builder/generic_record.py's GenericExtractionRecord
# declares - populated by core/pipeline.py (source_url, extracted_at),
# GenericExtractionRecord's own fallbacks (page_title, page_summary), or
# left as pipeline-owned scaffolding (confidence, page_type, entities, faq,
# additional_information, metadata) - never by a schema-declared,
# LLM/DOM-extracted field.
#
# A schema field whose *normalized* name collides with one of these (e.g. a
# field literally named "Source URL") is indistinguishable, after identity
# normalization, from the pipeline's own reserved field. Once such a field
# reaches SchemaMapper, both compete for the same output column, and the
# schema-declared one wins the alias-confidence scoring (an exact-case-fold
# match against the column beats the pipeline field's own alias match) -
# silently overwriting the pipeline's authoritative value with whatever the
# LLM guessed. Rejecting the collision at schema validation time (see
# config/extraction_schema.py's ExtractionField.validate()) removes the
# need for any such scoring workaround: SchemaMapper never has to be taught
# to break this tie, because the collision can no longer exist.
RESERVED_PIPELINE_FIELDS = frozenset(
    normalize_field_name(name)
    for name in (
        "source_url",
        "extracted_at",
        "confidence",
        "page_type",
        "page_title",
        "page_summary",
        "entities",
        "faq",
        "additional_information",
        "metadata",
    )
)


def is_reserved_pipeline_field(name: str) -> bool:
    """True if `name` identifies one of RESERVED_PIPELINE_FIELDS once
    normalized - e.g. "Source URL", "source_url", and "Source Url" all
    resolve to the same reserved identity, regardless of which one a schema
    author happened to type."""
    return normalize_field_name(name) in RESERVED_PIPELINE_FIELDS


# ---------------------------------------------------------------------------
# Supported metadata columns
# ---------------------------------------------------------------------------
# The subset of RESERVED_PIPELINE_FIELDS a schema may opt into as a plain
# OUTPUT COLUMN via ExtractionSchema.metadata_columns - never as an
# ExtractionField (that's still rejected by is_reserved_pipeline_field()
# above). Maps each supported identity to its canonical display/column
# name, so this dict is the single source of truth for both:
#   - validation (config/extraction_schema.py's ExtractionSchema.validate())
#   - column naming (modules/dataset_builder/builder.py's
#     DatasetBuilder.save_extraction_result(), which appends these columns
#     directly from pipeline metadata after SchemaMapper finishes mapping -
#     never through AliasRegistry/SchemaMapper).
#
# Only "source_url" and "page_title" are supported today; extending this
# dict is how a future metadata column would be added, without touching
# the dynamic schema, PromptBuilder, deterministic extraction, field
# ownership, or Hybrid Merge - those never see metadata_columns at all.
SUPPORTED_METADATA_COLUMNS = {
    "source_url": "Source Url",
    "page_title": "Page Title",
}


# ---------------------------------------------------------------------------
# Alias-aware lookup
# ---------------------------------------------------------------------------
# A schema field's own name and the DeterministicExtractor's canonical key
# for the same concept aren't always the same *word* - normalize_field_name()
# only bridges casing/spacing/hyphenation differences (e.g. "Franchise Fee"
# -> "franchise_fee" -> matches deterministic key "franchise_fee"), never
# synonyms (e.g. schema field "Space Required" vs deterministic key
# "area_required" - different words, so normalize_field_name() alone can
# never make them equal). A schema's own declared `aliases` are exactly
# where this synonym relationship is recorded ("Space Required" lists
# "area required" as one of its aliases); resolve_by_alias() is the single,
# generic place that consults them, so any lookup keyed by
# normalize_field_name() - deterministic extraction results today, and any
# future such lookup - can find a value stored under a field's alias, not
# just under its own exact name.

def alias_lookup_keys(field_name: str, aliases: Optional[Iterable[str]] = None) -> List[str]:
    """
    Returns the ordered, de-duplicated list of normalized identities that
    should all resolve to `field_name`: its own normalized name first
    (so a field's own name always takes priority over any alias when both
    happen to be present in a lookup), then each of its declared aliases,
    normalized, in declaration order.

    Example: field_name="Space Required", aliases=["Area Required", "Space",
    "Space Required"] -> ["space_required", "area_required", "space"]
    (the duplicate normalized "Space Required" alias is dropped).
    """
    keys: List[str] = []
    seen = set()
    for candidate in (field_name, *(aliases or [])):
        key = normalize_field_name(candidate)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def resolve_by_alias(field_name: str, aliases: Optional[Iterable[str]], lookup: Dict[str, Any]) -> Any:
    """
    Looks up a value for `field_name` in `lookup` - a dict already keyed by
    normalize_field_name() (e.g. deterministic extraction results). Tries
    the field's own normalized name first, then each of its normalized
    aliases (see alias_lookup_keys()), returning the value for the first
    identity found in `lookup`. Returns None if none of them are present.

    Generic by construction: works for any field/alias list from any
    schema - no field names or website-specific rules are hardcoded here.
    """
    for key in alias_lookup_keys(field_name, aliases):
        if key in lookup:
            return lookup[key]
    return None
