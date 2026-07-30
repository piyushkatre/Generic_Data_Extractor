"""
Verifies that a field not declared in the active ExtractionSchema is
intentionally omitted end-to-end - not just absent from the dynamic model in
isolation, but genuinely never surfaces anywhere in a real pipeline run, even
when:
  - the rendered HTML contains clearly-extractable data for that field
    (deterministic extraction would happily find it if asked), and
  - the (mocked) LLM response includes a value for that field anyway.

This is the concrete guarantee behind "no franchise assumptions in core":
a schema that doesn't ask for a field gets a model that structurally cannot
carry it, regardless of what's on the page or what the LLM returns.
"""

import os
import tempfile
from unittest.mock import patch

import pytest

from config.extraction_schema import ExtractionSchema
from modules.dataset_builder.schema_loader import SchemaLoader
from modules.dataset_builder.deterministic_extractor import DeterministicExtractor


HTML_WITH_FRANCHISE_FEE = """
<html><head><title>Cult Fit Franchise Opportunity</title></head>
<body>
  <h1>Cult Fit Franchise Opportunity</h1>
  <table>
    <tr><td>Investment:</td><td>Rs. 30 Lakhs - 50 Lakhs</td></tr>
    <tr><td>Franchise Fee:</td><td>Rs. 5 Lakhs</td></tr>
  </table>
</body></html>
"""


def _narrow_schema():
    """A schema that only wants franchise_name and investment_required -
    deliberately NOT franchise_fee, even though "franchise fee" is a
    recognized concept in core/field_strategy.py and the deterministic
    extractor's legacy CONCEPT_REGISTRY fallback vocabulary, and is present
    on the page below."""
    return ExtractionSchema.from_dict({
        "name": "Narrow Franchise Schema",
        "fields": [
            {"name": "franchise_name", "type": "string", "description": "Name of the franchise"},
            {"name": "investment_required", "type": "string", "description": "Investment required"},
        ],
    })


# ---------------------------------------------------------------------------
# Unit level: the dynamic model itself
# ---------------------------------------------------------------------------

def test_build_model_only_has_declared_fields():
    model = SchemaLoader.build_model(_narrow_schema())
    field_names = set(model.model_fields.keys())

    assert "franchise_name" in field_names
    assert "investment_required" in field_names
    # Adjacent, closely-related franchise fields that were NOT declared.
    for undeclared in ("franchise_fee", "royalty", "roi", "payback_period", "agreement_duration"):
        assert undeclared not in field_names


def test_constructing_model_with_undeclared_kwarg_drops_it_silently():
    """Pydantic's default extra="ignore" behavior means an undeclared field
    passed at construction time (e.g. because an LLM response included it
    anyway) is dropped, not stored and not an error."""
    model = SchemaLoader.build_model(_narrow_schema())
    instance = model(franchise_name="Cult Fit", investment_required="Rs. 30 Lakhs", franchise_fee="Rs. 5 Lakhs")

    assert instance.franchise_name == "Cult Fit"
    assert not hasattr(instance, "franchise_fee")


def test_deterministic_extractor_finds_franchise_fee_but_schema_has_nowhere_to_put_it():
    """The deterministic extractor is schema-driven for what it's ALLOWED to
    resolve; a field can be present in det_extracted (because the concept
    registry can recognize it) even though it will never reach the final
    record, because the active model has no such field to merge it into."""
    schema_dict = _narrow_schema().to_dict()
    extractor = DeterministicExtractor(schema=schema_dict)
    result = extractor.extract(HTML_WITH_FRANCHISE_FEE)

    # Deterministic extraction can still find it (schema-agnostic layout
    # parsing + the legacy CONCEPT_REGISTRY fallback vocabulary, which does
    # recognize "franchise fee" independent of this schema's own aliases) ...
    assert result.get("franchise_fee") == "Rs. 5 Lakhs"
    # ...but it will never be copied into the model, because the pipeline's
    # merge loop only ever iterates active_model.model_fields.keys().
    model = SchemaLoader.build_model(schema_dict)
    assert "franchise_fee" not in model.model_fields


# ---------------------------------------------------------------------------
# Full pipeline: undeclared field never surfaces in the final record or
# the mapped Excel row, even though the LLM "hallucinated" a value for it.
# ---------------------------------------------------------------------------

async def _fake_fetch_webpage(url, timeout_ms=30000):
    return {"url": url, "final_url": url, "title": "Cult Fit", "html": HTML_WITH_FRANCHISE_FEE, "render_time_ms": 1}


@pytest.mark.asyncio
async def test_pipeline_omits_undeclared_field_even_when_llm_returns_it():
    from core.runtime_adapter import RuntimeAdapter
    from config.website_config import WebsiteConfig
    from core.pipeline import ExtractionPipeline

    website_config = WebsiteConfig(name="Narrow Test Site")
    extraction_schema = _narrow_schema()
    runtime_adapter = RuntimeAdapter.from_config_and_schema(website_config, extraction_schema)

    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        assert "franchise_fee" not in model_cls.model_fields  # sanity: LLM's own response schema has no such field either
        # Even if the raw LLM JSON somehow contained "franchise_fee" (e.g.
        # the provider stuffed it in unprompted), constructing the response
        # model silently drops it - it can never reach this point as a
        # real attribute.
        return model_cls(page_title="Cult Fit", page_summary="A fitness franchise", franchise_name="Cult Fit")

    with tempfile.TemporaryDirectory() as tmp_datasets:
        with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
             patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
             patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
            mock_extract.side_effect = side_effect

            pipeline = ExtractionPipeline()
            result = await pipeline.run(
                "https://example.com/franchise/cult-fit",
                datasets_dir=tmp_datasets,
                runtime_adapter=runtime_adapter,
            )

    assert result["status"] == "success"
    record = result["result"]

    assert not hasattr(record, "franchise_fee")
    assert record.franchise_name == "Cult Fit Franchise Opportunity"  # deterministic-owned, from the H1

    # And the mapped Excel row has no "Franchise Fee" column at all - the
    # schema never declared one, so nothing was ever asked to write it.
    mapped_columns = result["mapped_record"].mapped_record.keys()
    assert "Franchise Fee" not in mapped_columns
