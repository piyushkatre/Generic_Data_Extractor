from config.extraction_schema import ExtractionField
from core.ownership import OwnershipResolver


def test_get_strategy_falls_back_to_field_strategy_table():
    strategy = OwnershipResolver.get_strategy("investment_required")
    assert strategy["owner"] == "deterministic"
    assert strategy["merge_policy"] == "deterministic_first"


def test_get_strategy_unknown_field_defaults_to_llm_only():
    strategy = OwnershipResolver.get_strategy("some_totally_custom_product_field")
    assert strategy["owner"] == "llm"
    assert strategy["merge_policy"] == "llm_only"


def test_get_strategy_normalizes_schema_display_name_to_match_table():
    """A schema field named with the display convention ("Franchise Fee")
    must resolve to the same strategy as its canonical snake_case form -
    the FIELD_STRATEGY table is keyed by canonical identity, not by
    whatever casing/spacing a schema author happened to type."""
    strategy = OwnershipResolver.get_strategy("Franchise Fee")
    assert strategy["owner"] == "deterministic"
    assert strategy["merge_policy"] == "deterministic_first"

    strategy_hyphens = OwnershipResolver.get_strategy("investment-required")
    assert strategy_hyphens["owner"] == "deterministic"
    assert strategy_hyphens["merge_policy"] == "deterministic_first"


def test_merge_normalizes_field_name_for_display_name_schema_field():
    """End-to-end through merge(): a Title-Case schema field name still
    gets the correct (deterministic_first) policy, so a present dom_val
    wins over a present llm_val exactly as it would under the canonical
    snake_case name."""
    val, source = OwnershipResolver.merge("Franchise Fee", "Rs. 5 Lakhs", "Rs. 5 Lakhs (LLM)")
    assert val == "Rs. 5 Lakhs"
    assert source == "Deterministic"


def test_extraction_field_override_wins_over_table_default():
    field_meta = ExtractionField(
        name="price", type="string", description="Price",
        extraction_owner="deterministic", merge_policy="deterministic_only",
    )
    strategy = OwnershipResolver.get_strategy("price", field_meta)
    assert strategy["owner"] == "deterministic"
    assert strategy["merge_policy"] == "deterministic_only"


def test_merge_deterministic_first_prefers_dom_value():
    val, source = OwnershipResolver.merge("investment_required", "Rs. 20 Lakhs", "20 Lakhs (LLM)")
    assert val == "Rs. 20 Lakhs"
    assert source == "Deterministic"


def test_merge_deterministic_first_falls_back_to_llm_when_dom_empty():
    val, source = OwnershipResolver.merge("investment_required", None, "20 Lakhs (LLM)")
    assert val == "20 Lakhs (LLM)"
    assert source == "LLM"


def test_merge_llm_only_ignores_dom_value():
    val, source = OwnershipResolver.merge("description", "dom text", "llm text")
    assert val == "llm text"
    assert source == "LLM"


def test_merge_deterministic_only_never_uses_llm():
    field_meta = ExtractionField(
        name="sku", type="string", description="SKU",
        merge_policy="deterministic_only",
    )
    val, source = OwnershipResolver.merge("sku", None, "llm-guessed-sku", field_meta)
    assert val is None
    assert source == "None"


def test_merge_both_empty_returns_none():
    val, source = OwnershipResolver.merge("phone", None, "")
    assert val is None
    assert source == "None"


# ---------------------------------------------------------------------
# Alias-aware strategy lookup (core/field_matching.resolve_by_alias).
# A schema field's own name is a SYNONYM, not just a casing/spacing
# variant, of a FIELD_STRATEGY table key - normalize_field_name() alone
# (already covered above) can't bridge that; only the field's own declared
# aliases can.
# ---------------------------------------------------------------------

def test_get_strategy_resolves_via_declared_alias_when_own_name_is_unknown():
    """"Space Required" isn't itself a FIELD_STRATEGY key, but it declares
    "area required" as an alias, which normalizes to the known
    "area_required" entry (deterministic, deterministic_first)."""
    field_meta = ExtractionField(
        name="Space Required", type="string", description="",
        aliases=["Area Required", "Space", "Space Required"],
    )
    strategy = OwnershipResolver.get_strategy("Space Required", field_meta)
    assert strategy["owner"] == "deterministic"
    assert strategy["merge_policy"] == "deterministic_first"


def test_merge_resolves_deterministic_first_policy_via_alias():
    """End-to-end through merge(): the alias-derived deterministic_first
    policy means a present dom_val wins over a present llm_val, exactly as
    it would if the field had been named "Area Required" directly."""
    field_meta = ExtractionField(
        name="Space Required", type="string", description="",
        aliases=["Area Required", "Space", "Space Required"],
    )
    val, source = OwnershipResolver.merge(
        "Space Required", "500 - 1000 sq ft", "1000 sq ft (LLM)", field_meta,
    )
    assert val == "500 - 1000 sq ft"
    assert source == "Deterministic"


def test_get_strategy_own_name_takes_priority_over_aliases():
    """If the field's own name IS a recognized table key, that entry wins -
    aliases are only consulted when the field's own name doesn't match."""
    field_meta = ExtractionField(
        name="Franchise Fee", type="string", description="",
        aliases=["some_totally_custom_product_field"],  # would resolve to the unknown-field default
    )
    strategy = OwnershipResolver.get_strategy("Franchise Fee", field_meta)
    assert strategy["owner"] == "deterministic"
    assert strategy["merge_policy"] == "deterministic_first"


def test_get_strategy_no_matching_alias_falls_back_to_unknown_default():
    field_meta = ExtractionField(
        name="Totally Custom Field", type="string", description="",
        aliases=["also custom", "still not a real concept"],
    )
    strategy = OwnershipResolver.get_strategy("Totally Custom Field", field_meta)
    assert strategy["owner"] == "llm"
    assert strategy["merge_policy"] == "llm_only"


def test_get_strategy_extraction_owner_override_still_wins_over_alias_match():
    """An explicit extraction_owner/merge_policy on the field always takes
    priority - even over a strategy resolved via alias, not just the
    field's own name (already covered by
    test_extraction_field_override_wins_over_table_default above)."""
    field_meta = ExtractionField(
        name="Space Required", type="string", description="",
        aliases=["Area Required"],
        extraction_owner="llm", merge_policy="llm_only",
    )
    strategy = OwnershipResolver.get_strategy("Space Required", field_meta)
    assert strategy["owner"] == "llm"
    assert strategy["merge_policy"] == "llm_only"
