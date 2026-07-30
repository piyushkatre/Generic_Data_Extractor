"""
End-to-end ExtractionPipeline test with rendering and the LLM call mocked.

There was previously zero test coverage of core/pipeline.py itself (all
existing tests exercised its collaborators - modules.gemini, the schema
mapper, the validator - individually). This covers the full 8-stage run,
including the deterministic/LLM field-ownership merge and the
templates/-resolved RuntimeAdapter path.
"""

import os
import tempfile
from unittest.mock import patch

import pytest


HTML = """
<html><head><title>Cult Fit Franchise Opportunity</title></head>
<body>
  <h1>Cult Fit Franchise Opportunity</h1>
  <table>
    <tr><td>Investment:</td><td>Rs. 30 Lakhs - 50 Lakhs</td></tr>
    <tr><td>Franchise Fee:</td><td>Rs. 5 Lakhs</td></tr>
  </table>
  <a href="mailto:contact@cultfit.com">Email</a>
</body></html>
"""


async def _fake_fetch_webpage(url, timeout_ms=30000):
    return {"url": url, "final_url": url, "title": "Cult Fit", "html": HTML, "render_time_ms": 5}


@pytest.mark.asyncio
async def test_pipeline_runs_all_stages_and_merges_dom_and_llm_fields():
    from core.pipeline import ExtractionPipeline

    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(
            page_title="Cult Fit",
            page_summary="A fitness franchise",
            business_model="Gym franchise model",  # LLM-only field per FIELD_STRATEGY
        )

    with tempfile.TemporaryDirectory() as tmp_datasets:
        with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
             patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            mock_extract.side_effect = side_effect

            pipeline = ExtractionPipeline()
            result = await pipeline.run(
                "https://franchisebazar.com/franchise/cult-fit",
                datasets_dir=tmp_datasets,
            )

    assert result["status"] == "success"
    assert all(s["status"] == "Completed" for s in pipeline.stages.values())

    record = result["result"]
    # Deterministic-owned fields resolved from the mocked HTML, not the LLM.
    assert record.franchise_name == "Cult Fit Franchise Opportunity"
    assert "30 Lakhs" in record.investment_required
    assert record.email == "contact@cultfit.com"
    # LLM-owned field came through from the mocked response.
    assert record.business_model == "Gym franchise model"

    # Page-type detection is informational only - present, never used to pick a schema.
    assert "detected_page_type" in result
    assert "detected_page_type_confidence" in result

    # Run metrics surface previously-internal-only measurements.
    metrics = result["run_metrics"]
    for key in ("html_size_raw", "html_size_cleaned", "dom_block_count", "total_time_seconds"):
        assert key in metrics

    mapped = result["mapped_record"].mapped_record
    assert mapped["Franchise Name"] == "Cult Fit Franchise Opportunity"


@pytest.mark.asyncio
async def test_deterministic_field_survives_pipeline_with_correct_provenance():
    """
    Regression test for two bugs found while investigating a report of
    deterministically-extracted fields (e.g. Franchise Fee) going missing
    from output despite being logged as extracted:

    1. modules/dataset_builder/schema_mapper.py read a metadata key named
       "fields_from_gemini", but core/pipeline.py's Hybrid Merge stage
       writes "fields_from_llm" - so the Schema Coverage Report's
       "LLM Fields" count was always 0 regardless of actual LLM
       contribution (confirmed both by code reading and by real historical
       production logs).
    2. modules/dataset_builder/record_mapper.py's RecordMapper.map() always
       re-ran RecordValidator a second time even when the caller (this
       pipeline) had already validated the record.

    Neither bug actually dropped field values (proven via a real execution
    trace during the investigation), but this test locks in both the value
    survival AND the provenance counts so a future regression in either
    direction - values disappearing, or counts becoming wrong again - fails
    a test instead of only being visible in a Schema Coverage Report log
    line nobody's watching.
    """
    from core.pipeline import ExtractionPipeline

    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(
            page_title="Cult Fit",
            page_summary="A fitness franchise",
            business_model="Gym franchise model",  # LLM-only field per FIELD_STRATEGY
            # Deliberately does NOT set franchise_fee/investment_required -
            # those must come from deterministic extraction alone.
        )

    with tempfile.TemporaryDirectory() as tmp_datasets:
        with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
             patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            mock_extract.side_effect = side_effect

            pipeline = ExtractionPipeline()
            result = await pipeline.run(
                "https://franchisebazar.com/franchise/cult-fit",
                datasets_dir=tmp_datasets,
            )

    assert result["status"] == "success"

    # Stage 1 -> merge: deterministic-only field survives the hybrid merge.
    record = result["result"]
    assert record.franchise_fee is not None
    assert "5 Lakhs" in record.franchise_fee

    # Stage: appears in mapped_record (final Excel row).
    mapping_result = result["mapped_record"]
    assert mapping_result.mapped_record.get("Franchise Fee")
    assert "5 Lakhs" in mapping_result.mapped_record["Franchise Fee"]

    # Stage: provenance counters are correct. This is the exact regression
    # check for the fields_from_llm/fields_from_gemini key mismatch - before
    # the fix, llm_count was unconditionally 0 here even though
    # business_model (LLM-only) is visibly present in mapped_record.
    coverage = mapping_result.coverage_statistics
    assert coverage["deterministic_count"] >= 1, (
        "franchise_fee (and other DOM-sourced fields) should be counted as deterministic"
    )
    assert coverage["llm_count"] >= 1, (
        "business_model (LLM-only) should be counted as LLM-sourced - this "
        "fails if the fields_from_llm/fields_from_gemini key names mismatch again"
    )


@pytest.mark.asyncio
async def test_hybrid_merge_matches_display_name_schema_field_to_deterministic_value():
    """
    Regression test for the field-name-normalization fix (core/field_matching.py):
    DeterministicExtractor always returns canonical snake_case keys
    ("franchise_fee"), but a schema is free to name its fields with display
    text ("Franchise Fee") - the schema is the source of truth, so users
    should never need to know or use snake_case.

    Case 1: a schema field named "Franchise Fee" still receives the value
            DeterministicExtractor found under "franchise_fee".
    Case 3: DeterministicExtractor also finds "expected_hours" (a concept
            this schema never declared a field for) - it must NOT be
            auto-injected into the merged record.
    Case 4: the schema's own display name/output column ("Franchise Fee")
            is unaffected by normalization - never "franchise_fee".
    """
    from core.runtime_adapter import RuntimeAdapter
    from config.website_config import WebsiteConfig
    from config.extraction_schema import ExtractionSchema
    from core.pipeline import ExtractionPipeline

    html = """
    <html><head><title>Cult Fit Franchise Opportunity</title></head>
    <body>
      <h1>Cult Fit Franchise Opportunity</h1>
      <table>
        <tr><td>Franchise Fee:</td><td>Rs. 5 Lakhs</td></tr>
      </table>
      <ul>
        <li><strong>Expected Working Hours:</strong> 8 Hours</li>
      </ul>
    </body></html>
    """

    async def fake_fetch(url, timeout_ms=30000):
        return {"url": url, "final_url": url, "title": "Cult Fit", "html": html, "render_time_ms": 1}

    # Schema declares ONLY "Franchise Fee", using display-text naming - not
    # DeterministicExtractor's canonical "franchise_fee".
    website_config = WebsiteConfig(name="Display Name Schema Test Site")
    extraction_schema = ExtractionSchema.from_dict({
        "name": "Display Name Schema",
        "fields": [{"name": "Franchise Fee", "type": "string", "description": "Franchise entry fee"}],
    })
    runtime_adapter = RuntimeAdapter.from_config_and_schema(website_config, extraction_schema)

    # Structural guarantee (mirrors tests/test_schema_field_omission.py):
    # the dynamic model has no field for the deterministic-only concept,
    # under either naming convention.
    active_model = runtime_adapter.get_model()
    assert "Franchise Fee" in active_model.model_fields
    assert "expected_hours" not in active_model.model_fields
    assert "Expected Hours" not in active_model.model_fields

    def llm_side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        # The LLM never finds the fee either - the merged value must come
        # from the deterministic extractor alone.
        return model_cls(page_title="Cult Fit", page_summary="A fitness franchise")

    with tempfile.TemporaryDirectory() as tmp_datasets:
        with patch("modules.dataset_builder.builder.fetch_webpage", new=fake_fetch), \
             patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            mock_extract.side_effect = llm_side_effect

            pipeline = ExtractionPipeline()
            result = await pipeline.run(
                "https://example.com/franchise/cult-fit",
                datasets_dir=tmp_datasets,
                runtime_adapter=runtime_adapter,
            )

    assert result["status"] == "success"
    record = result["result"]

    # Case 1: deterministic value survived the Hybrid Merge despite the
    # display-name schema field.
    assert getattr(record, "Franchise Fee") == "Rs. 5 Lakhs"

    # Case 3: expected_hours was found deterministically too, but the
    # schema never asked for it, so it must not appear anywhere on the
    # merged record under either naming convention.
    assert not hasattr(record, "expected_hours")
    assert not hasattr(record, "Expected Hours")

    # Case 4: the mapped output column is still the schema's own display
    # text, never the normalized/snake_case form.
    mapped_columns = result["mapped_record"].mapped_record.keys()
    assert "Franchise Fee" in mapped_columns
    assert "franchise_fee" not in mapped_columns
    assert result["mapped_record"].mapped_record["Franchise Fee"] == "Rs. 5 Lakhs"


@pytest.mark.asyncio
async def test_hybrid_merge_finds_deterministic_value_via_schema_alias_synonym():
    """
    Regression test for the alias-aware Hybrid Merge fix
    (core/field_matching.resolve_by_alias(), wired into
    core/pipeline.py's ownership-merge loop).

    Unlike test_hybrid_merge_matches_display_name_schema_field_to_deterministic_value
    above (a pure casing/spacing difference: "Franchise Fee" vs
    "franchise_fee", already bridged by normalize_field_name() alone),
    this covers a genuine *synonym*: DeterministicExtractor's canonical
    concept is "area_required" (see CONCEPT_REGISTRY's label list "area",
    "space", "area required", ...), but the schema names the field "Space
    Required" - a different word entirely, which normalize_field_name()
    can never bridge on its own. Only consulting the field's own declared
    `aliases` (here: "area required") can find the deterministic value.
    """
    from core.runtime_adapter import RuntimeAdapter
    from config.website_config import WebsiteConfig
    from config.extraction_schema import ExtractionSchema
    from core.pipeline import ExtractionPipeline

    html = """
    <html><head><title>Cult Fit Franchise Opportunity</title></head>
    <body>
      <h1>Cult Fit Franchise Opportunity</h1>
      <table>
        <tr><td>Area:</td><td>500 - 1000 sq ft</td></tr>
      </table>
    </body></html>
    """

    async def fake_fetch(url, timeout_ms=30000):
        return {"url": url, "final_url": url, "title": "Cult Fit", "html": html, "render_time_ms": 1}

    # Schema names the field "Space Required" (a synonym, not a casing
    # variant, of DeterministicExtractor's "area_required") but correctly
    # declares "area required" as one of its aliases - exactly the
    # real-world pattern a schema author uses to say "this concept may
    # appear on the page under a different label".
    website_config = WebsiteConfig(name="Alias Synonym Test Site")
    extraction_schema = ExtractionSchema.from_dict({
        "name": "Alias Synonym Schema",
        "fields": [{
            "name": "Space Required", "type": "string", "description": "",
            "aliases": ["area required", "space", "floor area"],
        }],
    })
    runtime_adapter = RuntimeAdapter.from_config_and_schema(website_config, extraction_schema)

    def llm_side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        # LLM never finds it either - the merged value must come from the
        # deterministic extractor alone, via the alias bridge.
        return model_cls(page_title="Cult Fit", page_summary="A fitness franchise")

    with tempfile.TemporaryDirectory() as tmp_datasets:
        with patch("modules.dataset_builder.builder.fetch_webpage", new=fake_fetch), \
             patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            mock_extract.side_effect = llm_side_effect

            pipeline = ExtractionPipeline()
            result = await pipeline.run(
                "https://example.com/franchise/cult-fit",
                datasets_dir=tmp_datasets,
                runtime_adapter=runtime_adapter,
            )

    assert result["status"] == "success"

    # Before the fix: this would be None (normalize_field_name("Space
    # Required") == "space_required", which never matches the
    # deterministic extractor's "area_required" key).
    mapped_columns = result["mapped_record"].mapped_record
    assert mapped_columns.get("Space Required"), (
        "deterministic value should have been found via the schema's own "
        "'area required' alias, not just the field's own name"
    )
    assert "500" in mapped_columns["Space Required"]


@pytest.mark.asyncio
async def test_pipeline_isolated_schema_dir_override_still_works():
    """Callers (like DatasetBuilder) can still inject a custom schema via a
    non-default schemas_dir, for isolated/test schema directories."""
    import json
    from core.pipeline import ExtractionPipeline

    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Test", page_summary="Test summary")

    with tempfile.TemporaryDirectory() as tmp_schemas, tempfile.TemporaryDirectory() as tmp_datasets:
        franchise_schema = {
            "dataset_name": "test_franchise.xlsx",
            "sheet_name": "Franchise Data",
            "primary_key": ["Source URL"],
            "required_fields": ["Franchise Name", "Source URL"],
            "aliases": {"franchise name": "Franchise Name", "source url": "Source URL"},
            "columns": ["Source URL", "Franchise Name", "Additional Information"],
            "extraction_fields": {
                "franchise_name": {"type": "string", "description": "Name"},
            },
        }
        with open(os.path.join(tmp_schemas, "franchise_schema.json"), "w", encoding="utf-8") as f:
            json.dump(franchise_schema, f)

        with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
             patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            mock_extract.side_effect = side_effect

            pipeline = ExtractionPipeline()
            result = await pipeline.run(
                "https://testfranchise.com",
                schemas_dir=tmp_schemas,
                datasets_dir=tmp_datasets,
            )

    assert result["status"] == "success"
    assert result["mapped_record"].mapped_record["Franchise Name"] == "Cult Fit Franchise Opportunity"
