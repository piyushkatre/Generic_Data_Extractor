"""
Tests for core/field_matching.normalize_field_name() and its use in
PromptBuilder's already-solved detection (core/prompt_builder.py) - the
part of the schema-field-vs-deterministic-key naming fix that doesn't
require a full pipeline run. See tests/test_pipeline_integration.py for the
end-to-end Hybrid Merge coverage (Cases 1/3/4 from the fix spec).

Case 2 (from the fix spec) lives here: PromptBuilder must recognize a
schema field as already solved when the deterministic extractor found it
under its own canonical snake_case name, even though the schema field's
display name uses spaces/Title Case.
"""

from core.field_matching import (
    normalize_field_name, is_reserved_pipeline_field, RESERVED_PIPELINE_FIELDS,
    alias_lookup_keys, resolve_by_alias,
)
from core.prompt_builder import ExtractionPromptBuilder


def test_normalize_field_name_examples_from_spec():
    assert normalize_field_name("Franchise Fee") == "franchise_fee"
    assert normalize_field_name("Investment Required") == "investment_required"
    assert normalize_field_name("Source URL") == "source_url"
    assert normalize_field_name("Expected No of Hours") == "expected_no_of_hours"


def test_normalize_field_name_already_snake_case_is_unchanged():
    assert normalize_field_name("franchise_fee") == "franchise_fee"


def test_normalize_field_name_hyphens_and_extra_whitespace():
    assert normalize_field_name("Hyphen-Separated-Field") == "hyphen_separated_field"
    assert normalize_field_name("  Extra   Spaces  ") == "extra_spaces"


def test_normalize_field_name_empty_string():
    assert normalize_field_name("") == ""
    assert normalize_field_name(None) == ""


def test_normalize_field_name_never_called_on_display_text_mutates_nothing():
    """Normalization is a pure function returning a new string - the
    original display name a caller holds is untouched."""
    original = "Franchise Fee"
    normalize_field_name(original)
    assert original == "Franchise Fee"


# ---------------------------------------------------------------------------
# Case 2: PromptBuilder marks a Title-Case schema field as already solved
# when the deterministic extractor found it under its canonical snake_case
# name.
# ---------------------------------------------------------------------------

def _schema_dict(field_names):
    return {
        "extraction_fields": {
            name: {"type": "string", "description": ""} for name in field_names
        }
    }


def test_prompt_builder_recognizes_already_solved_field_across_naming_conventions():
    schema = _schema_dict(["Investment Required", "Franchise Fee"])

    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site",
        schema=schema,
        structured_dom=[],
        deterministic_fields=["investment_required"],  # DeterministicExtractor's own canonical form
    )

    solved_section = prompt[prompt.find("ALREADY EXTRACTED FIELDS"):prompt.find("REMAINING FIELDS")]
    # Bounded to section 5 itself (not open-ended to end-of-prompt): section
    # 7's output-key manifest legitimately lists EVERY field, solved or not
    # - that's the actual list of expected JSON keys, a separate concern
    # from "which fields should the LLM search the DOM for".
    remaining_section = prompt[prompt.find("REMAINING FIELDS TO EXTRACT"):prompt.find("## 6. DOM CONTENT")]

    assert "Investment Required" in solved_section
    assert "Investment Required" not in remaining_section
    # Franchise Fee was NOT deterministically solved, so it must still be
    # asked for.
    assert "Franchise Fee" in remaining_section


def test_prompt_builder_field_names_in_prompt_stay_as_schema_display_text():
    """Normalization must never leak into the prompt text itself - the LLM
    is still asked about "Investment Required", never "investment_required"."""
    schema = _schema_dict(["Investment Required"])

    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site",
        schema=schema,
        structured_dom=[],
        deterministic_fields=["investment_required"],
    )

    assert "investment_required" not in prompt
    assert "Investment Required" in prompt


def test_prompt_builder_no_deterministic_fields_all_remaining():
    schema = _schema_dict(["Franchise Fee"])
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=schema, structured_dom=[], deterministic_fields=[],
    )
    remaining_section = prompt[prompt.find("REMAINING FIELDS TO EXTRACT"):]
    assert "Franchise Fee" in remaining_section


# ---------------------------------------------------------------------------
# alias_lookup_keys() / resolve_by_alias() - the generic alias-aware lookup
# used by both core/pipeline.py's Hybrid Merge dom-value lookup and
# core/ownership.py's FIELD_STRATEGY lookup. See tests/test_pipeline_integration.py
# (test_hybrid_merge_finds_deterministic_value_via_schema_alias_synonym) and
# tests/test_ownership_resolver.py for the end-to-end coverage; this file
# covers the pure function in isolation.
# ---------------------------------------------------------------------------

def test_alias_lookup_keys_matches_spec_example():
    """Schema field "Space Required" with aliases ["Area Required", "Space",
    "Space Required"] should produce lookup entries space_required,
    area_required, space (the duplicate "Space Required" alias, already
    covered by the field's own name, is dropped)."""
    keys = alias_lookup_keys("Space Required", ["Area Required", "Space", "Space Required"])
    assert keys == ["space_required", "area_required", "space"]


def test_alias_lookup_keys_own_name_first_even_if_declared_as_an_alias_too():
    keys = alias_lookup_keys("Franchise Fee", ["franchise fee", "fee"])
    assert keys[0] == "franchise_fee"
    assert keys == ["franchise_fee", "fee"]  # "franchise fee" alias deduped against the own name


def test_alias_lookup_keys_no_aliases_returns_just_own_name():
    assert alias_lookup_keys("Franchise Fee", None) == ["franchise_fee"]
    assert alias_lookup_keys("Franchise Fee", []) == ["franchise_fee"]


def test_resolve_by_alias_finds_value_under_declared_alias():
    """The exact motivating scenario: DeterministicExtractor stores a value
    under its own canonical key "area_required"; the schema names the
    field "Space Required" but declares "area required" as an alias."""
    lookup = {"franchise_name": "Cult Fit", "area_required": "500 - 1000 sq ft"}
    value = resolve_by_alias("Space Required", ["Area Required", "Space", "Space Required"], lookup)
    assert value == "500 - 1000 sq ft"


def test_resolve_by_alias_prefers_own_name_over_alias_when_both_present():
    lookup = {"franchise_fee": "own-name-value", "fee": "alias-value"}
    value = resolve_by_alias("Franchise Fee", ["fee"], lookup)
    assert value == "own-name-value"


def test_resolve_by_alias_returns_none_when_nothing_matches():
    lookup = {"franchise_name": "Cult Fit"}
    assert resolve_by_alias("Space Required", ["Area Required"], lookup) is None


def test_resolve_by_alias_no_aliases_behaves_like_plain_normalized_lookup():
    """Backward compatibility: a field with no aliases at all resolves
    exactly like the pre-fix normalize_field_name()-only lookup."""
    lookup = {"franchise_fee": "Rs. 5 Lakhs"}
    assert resolve_by_alias("Franchise Fee", None, lookup) == "Rs. 5 Lakhs"
    assert resolve_by_alias("Franchise Fee", [], lookup) == "Rs. 5 Lakhs"


# ---------------------------------------------------------------------------
# Task 2: PromptBuilder includes each field's declared aliases.
# ---------------------------------------------------------------------------

def _schema_dict_with_aliases(fields):
    """fields: dict of {field_name: [alias, ...]} (empty/absent list = no aliases)."""
    return {
        "extraction_fields": {
            name: ({"type": "string", "description": ""} | ({"aliases": aliases} if aliases else {}))
            for name, aliases in fields.items()
        }
    }


def _schema_fields_section(prompt: str) -> str:
    """Extracts the "## 3. SCHEMA FIELDS" section's body from a built prompt."""
    return prompt[prompt.find("## 3. SCHEMA FIELDS"):prompt.find("## 4. ALREADY EXTRACTED FIELDS")]


def test_prompt_builder_includes_aliases_when_present():
    schema = _schema_dict_with_aliases({
        "Space Required": ["Space", "Area Required", "Space Required"],
    })
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=schema, structured_dom=[],
    )
    schema_section = _schema_fields_section(prompt)
    assert "(aliases:" in schema_section
    assert "Area Required" in schema_section
    assert "Space Required" in schema_section


def test_prompt_builder_omits_aliases_clause_when_field_has_none():
    """Backward compatibility: a field with no declared aliases produces a
    line with no "(aliases: ...)" clause at all."""
    schema = _schema_dict_with_aliases({"Franchise Fee": []})
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=schema, structured_dom=[],
    )
    schema_section = _schema_fields_section(prompt)
    assert "(aliases:" not in schema_section
    assert "- Franchise Fee" in schema_section


def test_prompt_builder_mixed_fields_with_and_without_aliases():
    schema = _schema_dict_with_aliases({
        "Space Required": ["Space", "Area Required"],
        "Franchise Fee": [],
    })
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=schema, structured_dom=[],
    )
    schema_section = _schema_fields_section(prompt)
    assert "- Space Required (aliases: Space, Area Required)" in schema_section
    assert "- Franchise Fee" in schema_section
    assert "Franchise Fee (aliases:" not in schema_section


def test_prompt_builder_still_works_with_real_extraction_schema_to_dict_output():
    """Integration with config/extraction_schema.py: ExtractionField.to_dict()
    already nests aliases per-field (only when non-empty) - PromptBuilder
    should pick them up with zero extra plumbing."""
    from config.extraction_schema import ExtractionSchema

    es = ExtractionSchema.from_dict({
        "name": "Test Schema",
        "fields": [
            {"name": "Space Required", "type": "string", "aliases": ["Area Required", "Space"]},
            {"name": "Franchise Fee", "type": "string"},
        ],
    })
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=es.to_dict(), structured_dom=[],
    )
    schema_section = _schema_fields_section(prompt)
    assert "Area Required" in schema_section
    assert "- Franchise Fee" in schema_section


# ---------------------------------------------------------------------------
# RESERVED_PIPELINE_FIELDS / is_reserved_pipeline_field() - the single
# source of truth for which field identities belong to the pipeline itself
# (see modules/dataset_builder/generic_record.py's GenericExtractionRecord)
# and must never be redeclared by a user-authored schema. See
# config/extraction_schema.py's ExtractionField.validate() for where this
# is enforced.
# ---------------------------------------------------------------------------

def test_is_reserved_pipeline_field_recognizes_every_casing_variant():
    # "Source URL", "source_url", and "Source Url" must all resolve to the
    # same reserved identity, regardless of how a schema author typed it.
    for variant in ("Source URL", "source_url", "Source Url", "source url", "SOURCE_URL", " Source   URL "):
        assert is_reserved_pipeline_field(variant), f"{variant!r} should be recognized as reserved"


def test_is_reserved_pipeline_field_covers_every_pipeline_metadata_field():
    for name in (
        "source_url", "extracted_at", "confidence", "page_type", "page_title",
        "page_summary", "entities", "faq", "additional_information", "metadata",
    ):
        assert is_reserved_pipeline_field(name), f"{name!r} should be reserved"


def test_is_reserved_pipeline_field_false_for_ordinary_schema_fields():
    for name in ("Franchise Fee", "investment_required", "Phone", "Website", "Category"):
        assert not is_reserved_pipeline_field(name)


def test_reserved_pipeline_fields_are_already_normalized():
    """RESERVED_PIPELINE_FIELDS stores identities, not display text - every
    entry must already be in normalize_field_name()'s own output form."""
    for entry in RESERVED_PIPELINE_FIELDS:
        assert normalize_field_name(entry) == entry
