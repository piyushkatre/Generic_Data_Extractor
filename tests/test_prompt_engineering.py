"""
Tests for the restructured extraction prompt (core/prompt_builder.py) -
prompt-engineering-only improvements: clearer system instructions, a
readable (non-JSON) schema definition with descriptions/aliases, a fixed
7-section structure, generic (non-website-specific) extraction guidance,
anti-hallucination instructions, and output-reliability rules.

None of these tests touch or mock DeterministicExtractor, RelevantDOMBuilder,
OwnershipResolver, or SchemaMapper - this file is scoped exactly like the
change itself: prompt text only. See tests/test_field_matching.py for the
alias-specific prompt assertions (Task 2 of the previous turn) - this file
covers the broader instruction/structure work from this turn.
"""

import re

from core.prompt_builder import ExtractionPromptBuilder


def _schema(fields):
    """fields: dict of {name: {"description": str, "aliases": [str, ...]}} -
    any key may be omitted per field."""
    return {
        "extraction_fields": {
            name: {k: v for k, v in info.items() if v}
            for name, info in fields.items()
        }
    }


SAMPLE_SCHEMA = _schema({
    "Franchise Name": {"description": "Name of the franchise brand.", "aliases": ["name", "brand"]},
    "Space Required": {
        "description": "Minimum area required for operating the business.",
        "aliases": ["Space", "Area", "Area Required"],
    },
    "Royalty": {"aliases": ["royalty fee", "royalty percentage"]},
    "Description": {"description": "General overview of the business."},
    "Segment": {},
})


# ---------------------------------------------------------------------------
# Task 3: fixed 7-section structure, in the documented order.
# ---------------------------------------------------------------------------

_SECTION_HEADERS = [
    "## 1. TASK",
    "## 2. GENERAL RULES",
    "## 3. SCHEMA FIELDS",
    "## 4. ALREADY EXTRACTED FIELDS",
    "## 5. REMAINING FIELDS TO EXTRACT",
    "## 6. DOM CONTENT",
    "## 7. EXPECTED JSON OUTPUT",
]


def test_prompt_sections_all_present_in_documented_order():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
        deterministic_fields=["franchise_name"],
    )
    positions = [prompt.find(h) for h in _SECTION_HEADERS]
    assert all(p != -1 for p in positions), f"missing section(s): {[h for h, p in zip(_SECTION_HEADERS, positions) if p == -1]}"
    assert positions == sorted(positions), "sections must appear in the documented 1-7 order"


def test_prompt_structure_stable_regardless_of_schema_content():
    """The 7-section skeleton must appear even for a schema with zero
    fields and zero DOM content - no section silently disappears."""
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Empty Site", schema={"extraction_fields": {}}, structured_dom=[],
    )
    for header in _SECTION_HEADERS:
        assert header in prompt


# ---------------------------------------------------------------------------
# Task 1: system instructions cover every requested behavior.
# ---------------------------------------------------------------------------

def test_general_rules_cover_every_requested_instruction():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    rules_section = prompt[prompt.find("## 2. GENERAL RULES"):prompt.find("## 3. SCHEMA FIELDS")].lower()

    # Search the entire DOM before returning null.
    assert "entire dom" in rules_section
    # Aliases identify the same concept under different wording.
    assert "alias" in rules_section
    # Prefer explicit values; never hallucinate/invent/guess.
    assert "invent" in rules_section or "guess" in rules_section
    # Null only when genuinely absent.
    assert "genuinely absent" in rules_section
    # Ignore navigation/ads/unrelated content.
    assert "navigation" in rules_section
    assert "advertisement" in rules_section
    # Preserve exact wording for descriptive fields.
    assert "exact original wording" in rules_section or "preserve" in rules_section
    # Don't normalize structured values unless required.
    assert "original format" in rules_section
    # Deterministic values are authoritative / never overwritten.
    assert "authoritative" in rules_section
    # Multiple candidate values -> pick the most relevant.
    assert "most directly" in rules_section or "most relevant" in rules_section


def test_general_rules_contain_no_website_specific_wording():
    """The instructions must be entirely generic - nothing here should
    mention a specific site, brand, or hardcoded field name."""
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="FranchiseBazar", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    rules_section = prompt[prompt.find("## 2. GENERAL RULES"):prompt.find("## 3. SCHEMA FIELDS")]
    assert "FranchiseBazar" not in rules_section
    assert "Space Required" not in rules_section  # a real field name must not leak into the generic rules


# ---------------------------------------------------------------------------
# Task 2: readable (non-JSON) schema definitions with description/aliases.
# ---------------------------------------------------------------------------

def _schema_fields_section(prompt: str) -> str:
    return prompt[prompt.find("## 3. SCHEMA FIELDS"):prompt.find("## 4. ALREADY EXTRACTED FIELDS")]


def test_schema_fields_section_is_plain_text_not_json():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    section = _schema_fields_section(prompt)
    assert '{"type"' not in section
    assert '"description":' not in section
    assert "- Space Required" in section  # plain, dash-bulleted line


def test_schema_fields_section_includes_description_and_aliases():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    section = _schema_fields_section(prompt)
    assert "- Space Required: Minimum area required for operating the business. (aliases: Space, Area, Area Required)" in section


def test_schema_fields_section_drops_self_referential_alias():
    """Some real schemas list a field's own name as one of its own aliases
    (harmless authoring pattern - identity matching elsewhere already
    handles it). It carries no information in the prompt, so it must not
    be repeated in the (aliases: ...) clause."""
    schema = _schema({"Royalty": {"aliases": ["Royalty", "royalty fee", "royalty percentage"]}})
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=schema, structured_dom=[],
    )
    section = _schema_fields_section(prompt)
    assert section.strip() == "## 3. SCHEMA FIELDS\n- Royalty (aliases: royalty fee, royalty percentage)"


def test_schema_fields_section_field_with_only_aliases_no_description():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    section = _schema_fields_section(prompt)
    assert "- Royalty (aliases: royalty fee, royalty percentage)" in section


def test_schema_fields_section_field_with_neither_description_nor_aliases():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    section = _schema_fields_section(prompt)
    lines = [l for l in section.splitlines() if l.strip().startswith("- Segment")]
    assert lines == ["- Segment"]


def test_schema_fields_section_excludes_already_solved_fields():
    """Token-efficiency: a field the LLM doesn't need to search for gets no
    description/aliases block at all - only its bare name appears (in the
    separate, compact ALREADY EXTRACTED FIELDS list)."""
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
        deterministic_fields=["franchise_name"],
    )
    section = _schema_fields_section(prompt)
    assert "Franchise Name" not in section
    assert "- Space Required" in section  # still-remaining fields keep their full definition


# ---------------------------------------------------------------------------
# Task 6: output reliability - every field name listed once as the exact
# expected output keys.
# ---------------------------------------------------------------------------

def test_output_format_section_lists_every_field_exactly_once():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
        deterministic_fields=["franchise_name"],
    )
    output_section = prompt[prompt.find("## 7. EXPECTED JSON OUTPUT"):]
    for field_name in ("Franchise Name", "Space Required", "Royalty", "Description", "Segment"):
        assert output_section.count(field_name) == 1, f"{field_name!r} should appear exactly once in the output-key list"


def test_output_format_forbids_markdown_and_commentary():
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    output_section = prompt[prompt.find("## 7. EXPECTED JSON OUTPUT"):].lower()
    assert "markdown" in output_section
    assert "duplicate" in output_section
    assert "null" in output_section


# ---------------------------------------------------------------------------
# Backward compatibility.
# ---------------------------------------------------------------------------

def test_site_extraction_rules_still_appear_in_prompt():
    """WebsiteConfig.extraction_rules (per-site, config-driven, not
    hardcoded) must still reach the prompt - relocated into General Rules,
    not dropped."""
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
        extraction_rules=["Always prefer the price shown in INR over USD."],
    )
    assert "Always prefer the price shown in INR over USD." in prompt
    # Still located within General Rules, not a stray trailing block.
    rules_section = prompt[prompt.find("## 2. GENERAL RULES"):prompt.find("## 3. SCHEMA FIELDS")]
    assert "Always prefer the price shown in INR over USD." in rules_section


def test_field_names_stay_as_schema_display_text_not_normalized():
    """Unchanged guarantee from the field-name-normalization fix - still
    true after the prompt restructure."""
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="Test Site", schema=SAMPLE_SCHEMA, structured_dom=[],
    )
    assert "space_required" not in prompt
    assert "Space Required" in prompt


def test_prompt_returns_a_non_empty_string_for_minimal_inputs():
    """Smoke test: no exceptions, no empty output, for the most minimal
    possible call (matches the old function's basic contract)."""
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="X", schema={}, structured_dom=[],
    )
    assert isinstance(prompt, str) and prompt.strip()
