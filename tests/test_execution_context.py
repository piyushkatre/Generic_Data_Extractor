"""
Verifies ExecutionContext's core guarantee: every URL in a job's run shares
the exact same `job`/`runtime_adapter` object references (and therefore the
exact same WebsiteConfig/ExtractionSchema) - `.for_url()` only ever varies
the per-URL PipelineContext, never re-resolves the config/schema/adapter.
"""

import os
from unittest.mock import patch

import pytest

from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from config.extraction_job import ExtractionJob
from core.runtime_adapter import RuntimeAdapter
from core.execution_context import ExecutionContext
from core.pipeline_context import PipelineContext


def _make_execution_context():
    wc = WebsiteConfig(name="Generic Product Site")
    es = ExtractionSchema.from_dict({
        "name": "Generic Product",
        "fields": [{"name": "price", "type": "string", "description": "Price"}],
    })
    job = ExtractionJob(name="Test Job", urls=["https://example.com/1", "https://example.com/2"], website_config=wc, extraction_schema=es)
    runtime_adapter = RuntimeAdapter.from_config_and_schema(wc, es, name=job.name)
    return ExecutionContext(job=job, runtime_adapter=runtime_adapter)


def test_execution_context_is_immutable():
    ctx = _make_execution_context()
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError (a subclass of AttributeError)
        ctx.job = None


def test_website_config_and_extraction_schema_are_derived_not_stored():
    ctx = _make_execution_context()
    assert ctx.website_config is ctx.runtime_adapter.website_config
    assert ctx.extraction_schema is ctx.runtime_adapter.extraction_schema


def test_for_url_preserves_job_and_runtime_adapter_identity():
    base_ctx = _make_execution_context()

    ctx_1 = base_ctx.for_url("https://example.com/1")
    ctx_2 = base_ctx.for_url("https://example.com/2")

    # Same job, same runtime_adapter object across every URL derived from
    # the same base context - never a re-resolved copy.
    assert ctx_1.job is base_ctx.job
    assert ctx_2.job is base_ctx.job
    assert ctx_1.runtime_adapter is base_ctx.runtime_adapter
    assert ctx_2.runtime_adapter is base_ctx.runtime_adapter
    assert ctx_1.website_config is ctx_2.website_config
    assert ctx_1.extraction_schema is ctx_2.extraction_schema

    # But each has its own, url-scoped PipelineContext.
    assert ctx_1.pipeline_context is not ctx_2.pipeline_context
    assert ctx_1.pipeline_context.url == "https://example.com/1"
    assert ctx_2.pipeline_context.url == "https://example.com/2"


def test_for_url_returns_new_instance_not_mutating_base():
    base_ctx = _make_execution_context()
    assert base_ctx.pipeline_context is None

    derived = base_ctx.for_url("https://example.com/1")
    assert derived is not base_ctx
    assert base_ctx.pipeline_context is None  # base untouched
    assert derived.pipeline_context is not None


def test_for_url_wires_progress_callback_and_job_id_into_pipeline_context():
    base_ctx = _make_execution_context()
    events = []
    derived = base_ctx.for_url("https://example.com/1", progress_callback=lambda data: events.append(data))

    assert isinstance(derived.pipeline_context, PipelineContext)
    assert derived.pipeline_context.job_id == base_ctx.job.id
    derived.pipeline_context.update_stage("Browser Rendering", "Running")
    assert events  # progress_callback fired


# ---------------------------------------------------------------------------
# End-to-end: execute_job builds ONE ExecutionContext-worth of state and
# every URL's pipeline run actually receives the same runtime_adapter.
# ---------------------------------------------------------------------------

HTML = "<html><body><h1>Widget X</h1><span>Price: $19.99</span></body></html>"


async def _fake_fetch_webpage(url, timeout_ms=30000):
    return {"url": url, "final_url": url, "title": "Widget", "html": HTML, "render_time_ms": 1}


@pytest.mark.asyncio
async def test_execute_job_uses_same_runtime_adapter_for_every_url():
    from core.job_executor import execute_job

    ctx = _make_execution_context()
    seen_adapters = []

    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        seen_adapters.append(kwargs["adapter"])
        return model_cls(page_title="Widget X", page_summary="Summary", price="$1.00")

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect
        await execute_job(ctx)

    assert len(seen_adapters) == 2
    # Both URLs' LLM calls were handed the exact same RuntimeAdapter object -
    # not two independently-resolved ones.
    assert seen_adapters[0] is seen_adapters[1]
    assert seen_adapters[0] is ctx.runtime_adapter
