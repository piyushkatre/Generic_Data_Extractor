import os
import tempfile
from unittest.mock import patch

import pytest

from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from config.extraction_job import ExtractionJob
from core.runtime_adapter import RuntimeAdapter
from core.execution_context import ExecutionContext
from core.pipeline import ExtractionPipeline
from core.job_executor import execute_job


HTML = "<html><body><h1>Widget X</h1><span>Price: $19.99</span></body></html>"


async def _fake_fetch_webpage(url, timeout_ms=30000):
    return {"url": url, "final_url": url, "title": "Widget", "html": HTML, "render_time_ms": 1}


def _make_job(urls, output_format="excel"):
    wc = WebsiteConfig(name="Generic Product Site")
    es = ExtractionSchema.from_dict({
        "name": "Generic Product",
        "fields": [
            {"name": "product_name", "type": "string", "description": "Name of the product"},
            {"name": "price", "type": "string", "description": "Product price"},
        ],
    })
    return ExtractionJob(
        name="Test Product Job", urls=urls, website_config=wc, extraction_schema=es,
        output_format=output_format,
    )


def _make_execution_context(job):
    runtime_adapter = RuntimeAdapter.from_config_and_schema(job.website_config, job.extraction_schema, name=job.name)
    return ExecutionContext(job=job, runtime_adapter=runtime_adapter)


@pytest.mark.asyncio
async def test_execute_job_success_marks_job_completed_and_logs_each_url():
    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Widget X", page_summary="A great widget", price="$19.99")

    job = _make_job(["https://example.com/p/1", "https://example.com/p/2"])

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect

        result_job = await execute_job(_make_execution_context(job))

    assert result_job.status == "completed"
    assert len(result_job.stage_log) == 2
    urls_seen = {entry["url"] for entry in result_job.stage_log}
    assert urls_seen == {"https://example.com/p/1", "https://example.com/p/2"}
    assert all(entry["status"] == "success" for entry in result_job.stage_log)


@pytest.mark.asyncio
async def test_execute_job_partial_failure_marks_job_partial():
    call_count = {"n": 0}

    async def flaky_fetch(url, timeout_ms=30000):
        call_count["n"] += 1
        if "fail" in url:
            raise RuntimeError("simulated render failure")
        return {"url": url, "final_url": url, "title": "Widget", "html": HTML, "render_time_ms": 1}

    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Widget X", page_summary="A great widget", price="$19.99")

    job = _make_job(["https://example.com/p/ok", "https://example.com/p/fail"])

    with patch("modules.dataset_builder.builder.fetch_webpage", new=flaky_fetch), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect

        result_job = await execute_job(_make_execution_context(job))

    assert result_job.status == "partial"
    statuses = {entry["url"]: entry["status"] for entry in result_job.stage_log}
    assert statuses["https://example.com/p/ok"] == "success"
    assert statuses["https://example.com/p/fail"] == "failed"


@pytest.mark.asyncio
async def test_execute_job_progress_callback_receives_url_tagged_updates():
    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Widget X", page_summary="Summary", price="$1.00")

    job = _make_job(["https://example.com/p/1"])
    events = []

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect

        await execute_job(_make_execution_context(job), progress_callback=lambda url, data: events.append((url, data)))

    assert events
    assert all(url == "https://example.com/p/1" for url, _ in events)


# ---------------------------------------------------------------------
# Output Format propagation (UI -> ExtractionJob -> Pipeline -> DatasetBuilder
# -> WriterFactory), replacing the OUTPUT_FORMAT env var.
# ---------------------------------------------------------------------

@pytest.mark.asyncio
async def test_execute_job_writes_csv_when_job_output_format_is_csv(tmp_path):
    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Widget X", page_summary="A great widget", price="$19.99")

    job = _make_job(["https://example.com/p/1"], output_format="csv")

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect

        result_job = await execute_job(_make_execution_context(job), datasets_dir=str(tmp_path))

    save_info = result_job.stage_log[0]["save_info"]
    assert save_info["output_format"] == "csv"
    assert save_info["output_path"].endswith(".csv")
    assert os.path.exists(save_info["output_path"])


@pytest.mark.asyncio
async def test_execute_job_writes_excel_when_job_output_format_is_excel(tmp_path):
    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Widget X", page_summary="A great widget", price="$19.99")

    job = _make_job(["https://example.com/p/1"], output_format="excel")

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect

        result_job = await execute_job(_make_execution_context(job), datasets_dir=str(tmp_path))

    save_info = result_job.stage_log[0]["save_info"]
    assert save_info["output_format"] == "excel"
    assert save_info["output_path"].endswith(".xlsx")
    assert os.path.exists(save_info["output_path"])


@pytest.mark.asyncio
async def test_execute_job_defaults_to_excel_when_job_has_no_explicit_output_format(tmp_path):
    """A job built without ever setting output_format (e.g. an older
    caller/test that only passes name/urls/config/schema) must still
    produce Excel output, matching ExtractionJob's own default."""
    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Widget X", page_summary="A great widget", price="$19.99")

    wc = WebsiteConfig(name="Generic Product Site")
    es = ExtractionSchema.from_dict({
        "name": "Generic Product",
        "fields": [{"name": "price", "type": "string", "description": "Product price"}],
    })
    job = ExtractionJob(name="Test Product Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es)
    assert job.output_format == "excel"  # never set explicitly - dataclass default

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect

        result_job = await execute_job(_make_execution_context(job), datasets_dir=str(tmp_path))

    save_info = result_job.stage_log[0]["save_info"]
    assert save_info["output_format"] == "excel"
    assert save_info["output_path"].endswith(".xlsx")


@pytest.mark.asyncio
async def test_pipeline_run_raises_value_error_for_unknown_job_output_format(tmp_path):
    """ExtractionPipeline.run() (called directly, bypassing execute_job's
    per-URL try/except) surfaces the WriterFactory's ValueError as-is for an
    output_format the UI never actually offers (radio only offers
    CSV/Excel) but a programmatic caller could still set."""
    def side_effect(**kwargs):
        model_cls = kwargs["response_model"]
        return model_cls(page_title="Widget X", page_summary="A great widget", price="$19.99")

    job = _make_job(["https://example.com/p/1"], output_format="pdf")
    execution_context = _make_execution_context(job)

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = side_effect

        pipeline = ExtractionPipeline()
        with pytest.raises(ValueError, match="Unknown output_format"):
            await pipeline.run(
                "https://example.com/p/1", execution_context=execution_context,
                datasets_dir=str(tmp_path),
            )
