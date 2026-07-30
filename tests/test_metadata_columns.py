"""
Tests for opt-in pipeline metadata columns (Source URL / Page Title) -
config/extraction_schema.py's ExtractionSchema.metadata_columns and
modules/dataset_builder/builder.py's DatasetBuilder.save_extraction_result().

These values are pipeline metadata, never extraction fields: the LLM and
deterministic extractor never see or produce them, and DatasetBuilder
writes them directly from pipeline_metadata after SchemaMapper finishes -
never through RecordMapper/SchemaMapper/AliasRegistry. See
core/field_matching.SUPPORTED_METADATA_COLUMNS, the single source of truth
for which identities are supported and what column name each gets.
"""

import csv
import os

import pytest

from config.errors import ValidationError
from config.extraction_schema import ExtractionSchema
from modules.dataset_builder.builder import DatasetBuilder
from writers.csv_writer import CSVDatasetWriter


# ---------------------------------------------------------------------------
# ExtractionSchema.metadata_columns - model / validation / persistence
# ---------------------------------------------------------------------------

def test_extraction_schema_defaults_to_both_metadata_columns_enabled():
    """A schema built with no explicit choice (e.g. ExtractionSchema()) gets
    both enabled - the same default requirement 5 promises for schemas
    saved before this field existed."""
    es = ExtractionSchema()
    assert es.metadata_columns == ["source_url", "page_title"]


def test_extraction_schema_metadata_columns_source_url_only():
    es = ExtractionSchema.from_dict({"name": "S", "fields": [], "metadata_columns": ["source_url"]})
    assert es.metadata_columns == ["source_url"]


def test_extraction_schema_metadata_columns_page_title_only():
    es = ExtractionSchema.from_dict({"name": "S", "fields": [], "metadata_columns": ["page_title"]})
    assert es.metadata_columns == ["page_title"]


def test_extraction_schema_metadata_columns_both_enabled():
    es = ExtractionSchema.from_dict({"name": "S", "fields": [], "metadata_columns": ["source_url", "page_title"]})
    assert es.metadata_columns == ["source_url", "page_title"]


def test_extraction_schema_metadata_columns_both_disabled():
    """An explicit empty list (user unchecked both boxes) must be preserved
    exactly - never silently re-defaulted back to both enabled."""
    es = ExtractionSchema.from_dict({"name": "S", "fields": [], "metadata_columns": []})
    assert es.metadata_columns == []


def test_extraction_schema_rejects_unsupported_metadata_column():
    with pytest.raises(ValidationError, match="not supported"):
        ExtractionSchema.from_dict({"name": "S", "fields": [], "metadata_columns": ["confidence"]})


def test_extraction_schema_rejects_unsupported_metadata_column_direct_construction():
    with pytest.raises(ValidationError, match="not supported"):
        ExtractionSchema(name="S", metadata_columns=["some_made_up_field"])


def test_extraction_schema_from_legacy_dict_defaults_metadata_columns_when_absent():
    """Backward compatibility: a real templates/*/schema.json (no
    metadata_columns key at all) loads correctly and defaults to both
    enabled - no manual migration required."""
    with open(os.path.join("templates", "franchise_bazar", "schema.json"), encoding="utf-8") as f:
        import json
        raw = json.load(f)
    assert "metadata_columns" not in raw

    es = ExtractionSchema.from_legacy_dict(raw)
    assert es.metadata_columns == ["source_url", "page_title"]


def test_extraction_schema_round_trip_preserves_metadata_columns_choice():
    """ExtractionSchema.to_dict() never includes a "fields" key, so a
    schema saved via SchemaStore always reloads through
    ExtractionSchema.from_legacy_dict() (the same shape SchemaStore.load()
    feeds it) - the user's actual metadata_columns choice, including an
    explicit empty list, must survive that exact round trip."""
    es = ExtractionSchema.from_dict({"name": "S", "fields": [], "metadata_columns": ["page_title"]})
    persisted = es.to_dict()
    assert "fields" not in persisted  # confirms the round trip goes through from_legacy_dict()

    reloaded = ExtractionSchema.from_dict(persisted)
    assert reloaded.metadata_columns == ["page_title"]

    es_empty = ExtractionSchema.from_dict({"name": "S", "fields": [], "metadata_columns": []})
    reloaded_empty = ExtractionSchema.from_dict(es_empty.to_dict())
    assert reloaded_empty.metadata_columns == []


def test_extraction_schema_to_dict_keeps_metadata_columns_out_of_columns_and_aliases():
    """metadata_columns must never be merged into columns/aliases - those
    feed SchemaMapper's AliasRegistry, and metadata columns are never
    routed through it."""
    es = ExtractionSchema.from_dict({
        "name": "S",
        "fields": [{"name": "Franchise Name", "type": "string"}],
        "metadata_columns": ["source_url", "page_title"],
    })
    d = es.to_dict()
    assert "Source Url" not in d["columns"]
    assert "Page Title" not in d["columns"]
    assert "source_url" not in d["aliases"]
    assert "page_title" not in d["aliases"]
    assert d["metadata_columns"] == ["source_url", "page_title"]


# ---------------------------------------------------------------------------
# Metadata never reaches the dynamic schema / LLM prompt
# ---------------------------------------------------------------------------

def test_metadata_columns_never_appear_in_extraction_fields():
    es = ExtractionSchema.from_dict({
        "name": "S",
        "fields": [{"name": "Franchise Name", "type": "string"}],
        "metadata_columns": ["source_url", "page_title"],
    })
    d = es.to_dict()
    assert "source_url" not in d["extraction_fields"]
    assert "page_title" not in d["extraction_fields"]
    assert "Source URL" not in d["extraction_fields"]
    assert "Page Title" not in d["extraction_fields"]


def test_metadata_columns_do_not_change_the_dynamic_pydantic_model():
    """SchemaLoader.build_model() must produce the identical field set
    whether metadata_columns is empty or both enabled - source_url/
    page_title are already always present via GenericExtractionRecord;
    metadata_columns must add nothing new to the model."""
    from modules.dataset_builder.schema_loader import SchemaLoader

    es_enabled = ExtractionSchema.from_dict({
        "name": "S", "fields": [{"name": "Franchise Name", "type": "string"}],
        "metadata_columns": ["source_url", "page_title"],
    })
    es_disabled = ExtractionSchema.from_dict({
        "name": "S", "fields": [{"name": "Franchise Name", "type": "string"}],
        "metadata_columns": [],
    })

    fields_enabled = set(SchemaLoader.build_model(es_enabled).model_fields.keys())
    fields_disabled = set(SchemaLoader.build_model(es_disabled).model_fields.keys())
    assert fields_enabled == fields_disabled


def test_metadata_columns_never_appear_in_extraction_prompt():
    """PromptBuilder only ever reads schema["extraction_fields"] - a schema
    dict's metadata_columns key must have zero effect on the prompt."""
    from core.prompt_builder import ExtractionPromptBuilder

    es_enabled = ExtractionSchema.from_dict({
        "name": "S", "fields": [{"name": "Franchise Name", "type": "string"}],
        "metadata_columns": ["source_url", "page_title"],
    })
    es_disabled = ExtractionSchema.from_dict({
        "name": "S", "fields": [{"name": "Franchise Name", "type": "string"}],
        "metadata_columns": [],
    })

    prompt_enabled = ExtractionPromptBuilder.build_prompt(
        website_name="Test", schema=es_enabled.to_dict(), structured_dom=[],
    )
    prompt_disabled = ExtractionPromptBuilder.build_prompt(
        website_name="Test", schema=es_disabled.to_dict(), structured_dom=[],
    )
    assert prompt_enabled == prompt_disabled
    assert "source_url" not in prompt_enabled.lower().replace(" ", "_")
    assert "page_title" not in prompt_enabled.lower().replace(" ", "_")


# ---------------------------------------------------------------------------
# DatasetBuilder.save_extraction_result() - direct-from-pipeline-metadata
# writing, bypassing RecordMapper/SchemaMapper/AliasRegistry entirely.
# ---------------------------------------------------------------------------

_BASE_SCHEMA_COLUMNS = ["Franchise Name", "Investment Required"]


def _schema_dict(metadata_columns):
    return {
        "dataset_name": "metadata_columns_test.xlsx",
        "sheet_name": "Data",
        "primary_key": ["Franchise Name"],
        "columns": list(_BASE_SCHEMA_COLUMNS),
        "aliases": {"franchise_name": "Franchise Name", "investment_required": "Investment Required"},
        "metadata_columns": metadata_columns,
    }


def _read_csv_row(csv_path):
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return dict(zip(rows[0], rows[1])), rows[0]


def test_dataset_builder_source_url_only(tmp_path):
    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    save_info = builder.save_extraction_result(
        result={"Franchise Name": "Gym A", "Investment Required": "Rs. 10 Lakhs"},
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=_schema_dict(["source_url"]),
        pipeline_metadata={"source_url": "https://example.com/gym-a", "page_title": "Gym A | Franchise"},
    )
    row, headers = _read_csv_row(save_info["output_path"])
    assert "Source Url" in headers
    assert "Page Title" not in headers
    assert row["Source Url"] == "https://example.com/gym-a"


def test_dataset_builder_page_title_only(tmp_path):
    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    save_info = builder.save_extraction_result(
        result={"Franchise Name": "Gym A", "Investment Required": "Rs. 10 Lakhs"},
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=_schema_dict(["page_title"]),
        pipeline_metadata={"source_url": "https://example.com/gym-a", "page_title": "Gym A | Franchise"},
    )
    row, headers = _read_csv_row(save_info["output_path"])
    assert "Page Title" in headers
    assert "Source Url" not in headers
    assert row["Page Title"] == "Gym A | Franchise"


def test_dataset_builder_both_enabled(tmp_path):
    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    save_info = builder.save_extraction_result(
        result={"Franchise Name": "Gym A", "Investment Required": "Rs. 10 Lakhs"},
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=_schema_dict(["source_url", "page_title"]),
        pipeline_metadata={"source_url": "https://example.com/gym-a", "page_title": "Gym A | Franchise"},
    )
    row, headers = _read_csv_row(save_info["output_path"])
    assert "Source Url" in headers and "Page Title" in headers
    assert row["Source Url"] == "https://example.com/gym-a"
    assert row["Page Title"] == "Gym A | Franchise"


def test_dataset_builder_both_disabled(tmp_path):
    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    save_info = builder.save_extraction_result(
        result={"Franchise Name": "Gym A", "Investment Required": "Rs. 10 Lakhs"},
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=_schema_dict([]),
        pipeline_metadata={"source_url": "https://example.com/gym-a", "page_title": "Gym A | Franchise"},
    )
    _, headers = _read_csv_row(save_info["output_path"])
    assert "Source Url" not in headers
    assert "Page Title" not in headers
    assert headers == _BASE_SCHEMA_COLUMNS


def test_dataset_builder_metadata_values_come_from_pipeline_metadata_not_the_extracted_record(tmp_path):
    """Proves the values are copied directly from pipeline_metadata, not
    derived from `result` in any way: `result` here has no source_url/
    page_title-shaped keys at all, and it's a plain dict (the
    "isinstance(result, dict)" bypass branch), which never even
    instantiates RecordMapper/SchemaMapper. If the metadata columns still
    come out correct, they can only have come from pipeline_metadata."""
    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    plain_dict_result = {"Franchise Name": "Gym A", "Investment Required": "Rs. 10 Lakhs"}
    assert "entities" not in plain_dict_result  # confirms the dict-bypass branch is what runs

    save_info = builder.save_extraction_result(
        result=plain_dict_result,
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=_schema_dict(["source_url", "page_title"]),
        pipeline_metadata={
            "source_url": "https://distinguishable-value.example/exact-page",
            "page_title": "A Distinguishable Page Title",
        },
    )
    row, _ = _read_csv_row(save_info["output_path"])
    assert row["Source Url"] == "https://distinguishable-value.example/exact-page"
    assert row["Page Title"] == "A Distinguishable Page Title"


def test_dataset_builder_source_url_falls_back_to_source_url_parameter_when_pipeline_metadata_omits_it(tmp_path):
    """If a caller doesn't pass pipeline_metadata at all (or omits
    "source_url" from it), Source Url still gets the correct value from the
    save_extraction_result() `source_url` parameter, which is always
    correct (see core/pipeline.py) - not left blank."""
    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    save_info = builder.save_extraction_result(
        result={"Franchise Name": "Gym A", "Investment Required": "Rs. 10 Lakhs"},
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=_schema_dict(["source_url"]),
        # No pipeline_metadata given at all.
    )
    row, _ = _read_csv_row(save_info["output_path"])
    assert row["Source Url"] == "https://example.com/gym-a"


def test_dataset_builder_skips_metadata_column_already_covered_by_schemas_own_columns(tmp_path):
    """A legacy-style schema that already lists "Source URL" as a plain
    column (e.g. templates/*/schema.json's extra_columns) must not also
    gain a second, differently-cased "Source Url" column - the existing
    column is left to whatever already populates it (unchanged)."""
    schema = _schema_dict(["source_url"])
    schema["columns"] = ["Franchise Name", "Source URL"]  # pre-existing column, different casing

    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    save_info = builder.save_extraction_result(
        result={"Franchise Name": "Gym A", "Source URL": "https://example.com/gym-a"},
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=schema,
        pipeline_metadata={"source_url": "https://example.com/gym-a"},
    )
    _, headers = _read_csv_row(save_info["output_path"])
    assert headers.count("Source URL") == 1
    assert "Source Url" not in headers


def test_dataset_builder_defaults_metadata_columns_when_schema_omits_the_key(tmp_path):
    """A schema dict with no "metadata_columns" key at all (e.g. an
    existing raw schema.json, or a schema saved before this feature
    existed) defaults to both enabled - matching ExtractionSchema's own
    default, so no existing schema needs manual migration."""
    schema = _schema_dict(["source_url", "page_title"])
    del schema["metadata_columns"]
    assert "metadata_columns" not in schema

    builder = DatasetBuilder(datasets_dir=str(tmp_path), output_format="csv")
    save_info = builder.save_extraction_result(
        result={"Franchise Name": "Gym A", "Investment Required": "Rs. 10 Lakhs"},
        source_url="https://example.com/gym-a",
        detected_page_type="Franchise",
        timestamp="2026-01-01 00:00:00",
        schema=schema,
        pipeline_metadata={"source_url": "https://example.com/gym-a", "page_title": "Gym A | Franchise"},
    )
    row, headers = _read_csv_row(save_info["output_path"])
    assert "Source Url" in headers and "Page Title" in headers
    assert row["Source Url"] == "https://example.com/gym-a"
    assert row["Page Title"] == "Gym A | Franchise"
