"""
Verifies that WebsiteConfig/ExtractionSchema/ExtractionJob validation
produces clear, actionable error messages naming exactly which field is
wrong - instead of a raw KeyError/TypeError surfacing later, deep inside
whatever first tries to use the malformed object.
"""

import pytest

from config.errors import ValidationError
from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionField, ExtractionSchema
from config.extraction_job import ExtractionJob


# ---------------------------------------------------------------------------
# WebsiteConfig
# ---------------------------------------------------------------------------

def test_website_config_rejects_empty_name():
    with pytest.raises(ValidationError, match="name must be a non-empty string"):
        WebsiteConfig(name="")


def test_website_config_rejects_wrong_type_for_dict_field():
    with pytest.raises(ValidationError, match="browser_config must be an object/dict"):
        WebsiteConfig(name="Test Site", browser_config="not a dict")


def test_website_config_rejects_wrong_type_for_score_field():
    with pytest.raises(ValidationError, match="heading_keep_score must be a number"):
        WebsiteConfig(name="Test Site", heading_keep_score="ten")


def test_website_config_rejects_non_bool_for_bool_field():
    with pytest.raises(ValidationError, match="keep_tables must be true or false"):
        WebsiteConfig(name="Test Site", keep_tables="yes")


def test_website_config_from_dict_with_missing_sections_still_validates():
    """from_dict() fills in empty-dict defaults for missing config sections
    (e.g. no browser_config key at all) rather than raising - a genuinely
    minimal config is valid, it just does very little."""
    wc = WebsiteConfig.from_dict({"name": "Bare Config", "domain": "example.com"})
    assert wc.browser_config == {}
    assert wc.name == "Bare Config"


# ---------------------------------------------------------------------------
# ExtractionField / ExtractionSchema
# ---------------------------------------------------------------------------

def test_extraction_field_rejects_empty_name():
    with pytest.raises(ValidationError, match="name must be a non-empty string"):
        ExtractionField(name="")


def test_extraction_field_rejects_invalid_type():
    with pytest.raises(ValidationError, match="invalid type 'currency'"):
        ExtractionField(name="price", type="currency")


def test_extraction_field_rejects_invalid_extraction_owner():
    with pytest.raises(ValidationError, match="invalid extraction_owner 'maybe'"):
        ExtractionField(name="price", extraction_owner="maybe")


def test_extraction_schema_rejects_duplicate_field_names():
    with pytest.raises(ValidationError, match="'price' is declared more than once"):
        ExtractionSchema(
            name="Bad Schema",
            fields=[
                ExtractionField(name="price", type="string", description="Price A"),
                ExtractionField(name="price", type="string", description="Price B"),
            ],
        )


def test_extraction_schema_rejects_raw_dicts_in_fields_list():
    with pytest.raises(ValidationError, match="fields must be a list of ExtractionField objects"):
        ExtractionSchema(name="Bad Schema", fields=[{"name": "price", "type": "string"}])


def test_extraction_schema_rejects_empty_name():
    with pytest.raises(ValidationError, match="name must be a non-empty string"):
        ExtractionSchema(name="")


# ---------------------------------------------------------------------------
# ExtractionJob
# ---------------------------------------------------------------------------

def _valid_config_and_schema():
    return WebsiteConfig(name="Generic Site"), ExtractionSchema.from_dict({"name": "Generic", "fields": []})


def test_extraction_job_rejects_empty_urls_list():
    wc, es = _valid_config_and_schema()
    with pytest.raises(ValidationError, match="urls must be a non-empty list"):
        ExtractionJob(name="Job", urls=[], website_config=wc, extraction_schema=es)


def test_extraction_job_rejects_blank_url_entries():
    wc, es = _valid_config_and_schema()
    with pytest.raises(ValidationError, match="empty or non-string entr"):
        ExtractionJob(name="Job", urls=["https://example.com", "   "], website_config=wc, extraction_schema=es)


def test_extraction_job_rejects_wrong_type_for_website_config():
    _, es = _valid_config_and_schema()
    with pytest.raises(ValidationError, match="website_config must be a WebsiteConfig instance"):
        ExtractionJob(name="Job", urls=["https://example.com"], website_config={"name": "not an object"}, extraction_schema=es)


def test_extraction_job_rejects_wrong_type_for_extraction_schema():
    wc, _ = _valid_config_and_schema()
    with pytest.raises(ValidationError, match="extraction_schema must be an ExtractionSchema instance"):
        ExtractionJob(name="Job", urls=["https://example.com"], website_config=wc, extraction_schema={"name": "not an object"})


def test_extraction_job_rejects_invalid_status_with_clear_message():
    wc, es = _valid_config_and_schema()
    with pytest.raises(ValidationError, match="status must be one of"):
        ExtractionJob(name="Job", urls=["https://example.com"], website_config=wc, extraction_schema=es, status="not_a_status")
