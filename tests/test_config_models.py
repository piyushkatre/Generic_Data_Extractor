import json
import os

import pytest

from config.errors import ValidationError
from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionField, ExtractionSchema
from config.extraction_job import ExtractionJob


# ---------------------------------------------------------------------------
# WebsiteConfig
# ---------------------------------------------------------------------------

def test_website_config_defaults():
    wc = WebsiteConfig()
    assert wc.domain == "*"
    assert wc.keep_tables is True
    assert wc.browser_config == {}


def test_website_config_round_trips_legacy_adapter_dict():
    with open(os.path.join("templates", "franchise_bazar", "config.json"), encoding="utf-8") as f:
        raw = json.load(f)

    wc = WebsiteConfig.from_dict(raw)
    assert wc.name == "FranchiseBazar"
    assert wc.domain == "franchisebazar.com"
    assert wc.priority == 10
    assert "franchisebazar.in" in wc.aliases

    back = wc.to_dict()
    assert back["domain"] == "franchisebazar.com"
    assert back["browser_config"] == raw["browser_config"]
    assert back["removable_elements"] == raw["removable_elements"]


def test_website_config_to_pruning_profile():
    wc = WebsiteConfig(
        name="Test Site",
        domain="test.com",
        removable_elements={"remove_tag_names": ["nav"], "remove_class_keywords": ["ads"]},
        keep_elements={"keep_heading_keywords": ["about"]},
    )
    profile = wc.to_pruning_profile()
    assert profile.domain == "test.com"
    assert profile.remove_tag_names == ["nav"]
    assert profile.keep_heading_keywords == ["about"]
    assert profile.keep_tables is True


# ---------------------------------------------------------------------------
# ExtractionField / ExtractionSchema
# ---------------------------------------------------------------------------

def test_extraction_field_defaults_and_validation():
    f = ExtractionField(name="price", type="string", description="Product price")
    assert f.column == "Price"  # auto-derived
    assert f.required is False
    assert f.extraction_owner is None

    with pytest.raises(ValueError):
        ExtractionField(name="bad", type="not_a_type")

    with pytest.raises(ValueError):
        ExtractionField(name="bad", extraction_owner="not_valid")


def test_extraction_schema_simplified_format():
    es = ExtractionSchema.from_dict({
        "name": "Generic Product",
        "fields": [
            {"name": "product_name", "type": "string", "description": "Name", "required": True},
            {"name": "price", "type": "string", "description": "Price"},
        ],
    })
    assert es.field_names() == ["product_name", "price"]
    assert es.required_field_names == ["product_name"]

    d = es.to_dict()
    assert "product_name" in d["extraction_fields"]
    assert "Product Name" in d["columns"]
    assert "Additional Information" in d["columns"]
    assert d["required_fields"] == ["Product Name"]


def test_extraction_schema_legacy_round_trip_preserves_all_columns():
    with open(os.path.join("templates", "franchise_bazar", "schema.json"), encoding="utf-8") as f:
        raw = json.load(f)

    es = ExtractionSchema.from_legacy_dict(raw)
    d = es.to_dict()

    # Every original column must survive the round-trip, including ones
    # (Source URL, Extraction Date, Last Updated) that don't correspond to
    # any declared extraction_fields entry.
    for col in raw["columns"]:
        assert col in d["columns"], f"Column '{col}' was dropped by the round-trip"

    assert d["primary_key"] == raw["primary_key"]
    assert set(d["required_fields"]) == set(raw["required_fields"])


def test_franchisebazar_expanded_schema_loads_and_has_no_duplicate_aliases():
    """The real, in-storage FranchiseBazar schema was expanded with new
    business-concept fields (Business Model, Segment, Expected Hours,
    Expansion Locations, Documentation Details, Business Suitability,
    Ideal Entrepreneur Profile) plus alias enrichments on Training/
    Description. This must still load/validate cleanly, and - since
    alias-aware resolution now means ANY field can be found via ANY of its
    aliases - no two DIFFERENT fields may declare an overlapping alias
    (that would make resolution ambiguous)."""
    from config.schema_store import SchemaStore

    schema = SchemaStore().load("franchisebazar_schema-6667f9a3")
    field_names = schema.field_names()

    for new_field in (
        "Business Model", "Segment", "Expected Hours", "Expansion Locations",
        "Documentation Details", "Business Suitability", "Ideal Entrepreneur Profile",
    ):
        assert new_field in field_names, f"expected new field '{new_field}' to be present"

    # Original fields untouched.
    for original_field in ("Franchise Name", "Investment Required", "Space Required", "Industry", "Products", "support"):
        assert original_field in field_names

    # No two different fields share a normalized alias/name - otherwise
    # resolve_by_alias() couldn't unambiguously pick one.
    from core.field_matching import normalize_field_name
    owner_of = {}
    for f in schema.fields:
        for candidate in [f.name] + list(f.aliases):
            key = normalize_field_name(candidate)
            if key in owner_of and owner_of[key] != f.name:
                raise AssertionError(
                    f"alias '{candidate}' (normalized '{key}') is declared by both "
                    f"'{owner_of[key]}' and '{f.name}' - ambiguous alias resolution"
                )
            owner_of[key] = f.name


def test_extraction_schema_build_model_has_no_franchise_base_fields():
    """A schema with no extraction_fields at all should produce a model
    with only the small universal core - no inherited franchise vocabulary."""
    from modules.dataset_builder.schema_loader import SchemaLoader

    es = ExtractionSchema.from_dict({"name": "Bare Schema", "fields": []})
    model = SchemaLoader.build_model(es)
    field_names = set(model.model_fields.keys())

    assert "royalty" not in field_names
    assert "franchise_fee" not in field_names
    assert "investment_min" not in field_names
    assert {"source_url", "page_title", "page_summary", "entities", "metadata"}.issubset(field_names)


# ---------------------------------------------------------------------------
# Reserved pipeline metadata fields (core/field_matching.RESERVED_PIPELINE_FIELDS)
# ===========================================================================
# A schema must never declare an ExtractionField whose identity collides
# with a field the pipeline itself owns (source_url, extracted_at,
# confidence, page_type, page_title, page_summary, entities, faq,
# additional_information, metadata) - see modules/dataset_builder/
# generic_record.py's GenericExtractionRecord. Such a collision let a
# schema-declared field (e.g. "Source URL") win SchemaMapper's
# alias-confidence scoring over the pipeline's own reserved field, silently
# overwriting the authoritative value with whatever the LLM guessed.
# Rejecting it at schema validation time removes the need for any such
# scoring workaround entirely.
# ---------------------------------------------------------------------------

def test_extraction_schema_valid_schema_with_ordinary_fields_is_unaffected():
    """A schema that declares none of the reserved names must still
    construct and validate exactly as before."""
    es = ExtractionSchema.from_dict({
        "name": "Valid Schema",
        "fields": [
            {"name": "Franchise Name", "type": "string", "required": True},
            {"name": "Investment Required", "type": "string"},
            {"name": "Phone", "type": "string", "aliases": ["contact number", "mobile"]},
        ],
    })
    assert es.field_names() == ["Franchise Name", "Investment Required", "Phone"]


@pytest.mark.parametrize("reserved_name", ["Source URL", "source_url", "Source Url", "Confidence", "confidence"])
def test_extraction_field_rejects_reserved_pipeline_field_names(reserved_name):
    with pytest.raises(ValidationError, match="reserved for pipeline metadata"):
        ExtractionField(name=reserved_name, type="string")


def test_extraction_schema_from_dict_rejects_reserved_field_at_creation_time():
    """Mirrors app/ui/schema_manager.py's Save flow: SchemaService.create()
    calls ExtractionSchema.from_dict(payload) on whatever the user typed in
    the field editor - a reserved name must be rejected right there, before
    anything is persisted."""
    with pytest.raises(ValidationError, match="reserved for pipeline metadata"):
        ExtractionSchema.from_dict({
            "name": "Bad Schema",
            "fields": [
                {"name": "Franchise Name", "type": "string"},
                {"name": "Source URL", "type": "string", "aliases": ["url", "link", "page url"], "required": True},
            ],
        })


def test_extraction_schema_loading_existing_invalid_schema_fails_fast_with_descriptive_error():
    """Backward compatibility: a schema saved before this validation existed
    (e.g. the exact real-world "FranchiseBazar Schema" record that caused
    the Source URL collision bug) must fail to load with a clear,
    descriptive exception - never silently proceed into extraction."""
    stored_schema_dict = {
        "name": "FranchiseBazar Schema",
        "fields": [
            {"name": "Franchise Name", "type": "string", "required": True},
            {"name": "Source URL", "type": "string", "aliases": ["url", "link", "page url"], "required": True},
            {"name": "Investment Required", "type": "string", "required": True},
        ],
    }
    with pytest.raises(ValidationError) as exc_info:
        ExtractionSchema.from_dict(stored_schema_dict)

    message = str(exc_info.value)
    assert "Source URL" in message
    assert "reserved for pipeline metadata" in message


def test_extraction_schema_legacy_dict_rejects_reserved_extraction_field_too():
    """The templates/*/schema.json (adapters/*/schema.json legacy) loading
    path goes through the same ExtractionField construction, so it's
    covered by the same fail-fast validation."""
    with pytest.raises(ValidationError, match="reserved for pipeline metadata"):
        ExtractionSchema.from_legacy_dict({
            "extraction_fields": {
                "franchise_name": {"type": "string"},
                "source_url": {"type": "string"},
            },
            "columns": ["Franchise Name", "Source URL"],
            "aliases": {"franchise_name": "Franchise Name", "source_url": "Source URL"},
        })


# ---------------------------------------------------------------------------
# ExtractionJob
# ---------------------------------------------------------------------------

def _make_job(**overrides):
    defaults = dict(
        name="IndiaMART Product Extraction",
        urls=["https://example.com/p/1"],
        website_config=WebsiteConfig(name="Generic"),
        extraction_schema=ExtractionSchema.from_dict({"name": "Generic", "fields": []}),
    )
    defaults.update(overrides)
    return ExtractionJob(**defaults)


def test_extraction_job_requires_at_least_one_url():
    with pytest.raises(ValueError):
        _make_job(urls=[])


def test_extraction_job_output_filename_from_job_name_not_domain_type():
    job = _make_job(name="IndiaMART Product Extraction")
    assert job.generate_output_filename() == "indiamart_product_extraction.csv"
    assert job.generate_output_filename("xlsx") == "indiamart_product_extraction.xlsx"


def test_extraction_job_state_transitions():
    job = _make_job()
    assert job.status == "created"

    job.mark_running()
    assert job.status == "running"

    job.add_url_result("https://example.com/p/1", {"status": "success"})
    assert job.stage_log == [{"url": "https://example.com/p/1", "status": "success"}]

    job.mark_completed("storage/outputs/x.csv")
    assert job.status == "completed"
    assert job.output_path == "storage/outputs/x.csv"


def test_extraction_job_invalid_status_rejected():
    with pytest.raises(ValueError):
        _make_job(status="not_a_status")
