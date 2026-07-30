import os
from unittest.mock import patch

import pytest

from config.config_store import ConfigStore
from config.schema_store import SchemaStore
from config.job_store import JobStore
from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from config.errors import ValidationError
from services.config_service import ConfigService
from services.schema_service import SchemaService
from services.job_service import JobService
from services.errors import NotFoundError, DuplicateNameError, JobLifecycleError


HTML = "<html><body><h1>Widget X</h1><span>Price: $19.99</span></body></html>"


async def _fake_fetch_webpage(url, timeout_ms=30000):
    return {"url": url, "final_url": url, "title": "Widget", "html": HTML, "render_time_ms": 1}


def _llm_side_effect(**kwargs):
    model_cls = kwargs["response_model"]
    return model_cls(page_title="Widget X", page_summary="A great widget", price="$19.99")


# ---------------------------------------------------------------------------
# ConfigService
# ---------------------------------------------------------------------------

def test_config_service_create_get_update_delete(tmp_path):
    service = ConfigService(ConfigStore(storage_dir=str(tmp_path / "configs")))

    config_id = service.create({"name": "IndiaMART Products", "domain": "indiamart.com"})
    loaded = service.get(config_id)
    assert loaded.domain == "indiamart.com"

    updated = service.update(config_id, {"name": "IndiaMART Products", "domain": "indiamart.com", "priority": 9})
    assert updated.priority == 9
    assert service.get(config_id).priority == 9

    service.delete(config_id)
    with pytest.raises(NotFoundError):
        service.get(config_id)


def test_config_service_rejects_duplicate_name(tmp_path):
    service = ConfigService(ConfigStore(storage_dir=str(tmp_path / "configs")))
    service.create({"name": "IndiaMART Products", "domain": "indiamart.com"})

    with pytest.raises(DuplicateNameError):
        service.create({"name": "IndiaMART Products", "domain": "otherdomain.com"})

    with pytest.raises(DuplicateNameError):
        service.create({"name": "indiamart products", "domain": "case-insensitive.com"})  # case-insensitive match


def test_config_service_propagates_clear_validation_errors(tmp_path):
    service = ConfigService(ConfigStore(storage_dir=str(tmp_path / "configs")))
    with pytest.raises(ValidationError, match="name must be a non-empty string"):
        service.create({"name": ""})


def test_config_service_update_missing_id_raises_not_found(tmp_path):
    service = ConfigService(ConfigStore(storage_dir=str(tmp_path / "configs")))
    with pytest.raises(NotFoundError):
        service.update("does-not-exist", {"name": "X"})


# ---------------------------------------------------------------------------
# SchemaService
# ---------------------------------------------------------------------------

def test_schema_service_create_get_list(tmp_path):
    service = SchemaService(SchemaStore(storage_dir=str(tmp_path / "schemas")))

    schema_id = service.create({
        "name": "Generic Product",
        "fields": [{"name": "price", "type": "string", "description": "Price"}],
    })
    loaded = service.get(schema_id)
    assert loaded.field_names() == ["price"]
    assert len(service.list()) == 1


def test_schema_service_rejects_duplicate_name(tmp_path):
    service = SchemaService(SchemaStore(storage_dir=str(tmp_path / "schemas")))
    service.create({"name": "Generic Product", "fields": []})
    with pytest.raises(DuplicateNameError):
        service.create({"name": "Generic Product", "fields": []})


def test_schema_service_accepts_already_built_object(tmp_path):
    service = SchemaService(SchemaStore(storage_dir=str(tmp_path / "schemas")))
    es = ExtractionSchema.from_dict({"name": "Direct Object Schema", "fields": []})
    schema_id = service.create(es)
    assert service.get(schema_id).name == "Direct Object Schema"


# ---------------------------------------------------------------------------
# JobService
# ---------------------------------------------------------------------------

def _make_job_service(tmp_path):
    return JobService(
        config_store=ConfigStore(storage_dir=str(tmp_path / "configs")),
        schema_store=SchemaStore(storage_dir=str(tmp_path / "schemas")),
        job_store=JobStore(storage_dir=str(tmp_path / "jobs")),
    )


def test_job_service_create_job_requires_config_or_config_id(tmp_path):
    service = _make_job_service(tmp_path)
    with pytest.raises(ValueError):
        service.create_job(name="Job", urls=["https://example.com"], extraction_schema=ExtractionSchema.from_dict({"name": "X", "fields": []}))


def test_job_service_create_job_with_missing_config_id_raises_not_found(tmp_path):
    service = _make_job_service(tmp_path)
    with pytest.raises(NotFoundError):
        service.create_job(
            name="Job", urls=["https://example.com"],
            config_id="does-not-exist",
            extraction_schema=ExtractionSchema.from_dict({"name": "X", "fields": []}),
        )


@pytest.mark.asyncio
async def test_job_service_full_lifecycle_create_run_completed(tmp_path):
    service = _make_job_service(tmp_path)
    config_id = service.config_store.save(WebsiteConfig(name="Generic Product Site"))
    schema_id = service.schema_store.save(ExtractionSchema.from_dict({
        "name": "Generic Product",
        "fields": [{"name": "price", "type": "string", "description": "Price"}],
    }))

    job = service.create_job(name="Widget Job", urls=["https://example.com/p/1"], config_id=config_id, schema_id=schema_id)
    assert job.status == "created"

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect

        completed = await service.run(job.id)

    assert completed.status == "completed"
    assert service.get(job.id).status == "completed"


@pytest.mark.asyncio
async def test_job_service_run_rejects_already_running_or_terminal(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": [{"name": "price", "type": "string", "description": "Price"}]})
    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es)

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect
        await service.run(job.id)

    with pytest.raises(JobLifecycleError, match="already completed"):
        await service.run(job.id)


@pytest.mark.asyncio
async def test_job_service_rerun_allows_running_a_terminal_job_again(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": [{"name": "price", "type": "string", "description": "Price"}]})
    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es)

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect
        await service.run(job.id)
        rerun_result = await service.rerun(job.id)

    assert rerun_result.status == "completed"
    assert len(rerun_result.stage_log) == 1  # reset, not appended


@pytest.mark.asyncio
async def test_job_service_cancel_before_running_marks_cancelled_immediately(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": []})
    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es)

    cancelled = service.cancel(job.id)
    assert cancelled.status == "cancelled"


@pytest.mark.asyncio
async def test_job_service_cancel_is_noop_for_already_terminal_job(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": [{"name": "price", "type": "string", "description": "Price"}]})
    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es)

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect
        await service.run(job.id)

    result = service.cancel(job.id)
    assert result.status == "completed"  # unchanged, not overwritten to "cancelled"


@pytest.mark.asyncio
async def test_job_service_cancel_while_running_stops_remaining_urls(tmp_path):
    """Cancelling mid-run lets in-flight URLs finish but skips the rest."""
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": [{"name": "price", "type": "string", "description": "Price"}]})
    job = service.create_job(
        name="Job",
        urls=["https://example.com/p/1", "https://example.com/p/2", "https://example.com/p/3"],
        website_config=wc, extraction_schema=es,
    )

    async def slow_fetch_then_cancel(url, timeout_ms=30000):
        if url.endswith("/p/1"):
            # Cancel while the first URL is still "in flight".
            service.cancel(job.id)
        return {"url": url, "final_url": url, "title": "Widget", "html": HTML, "render_time_ms": 1}

    with patch("modules.dataset_builder.builder.fetch_webpage", new=slow_fetch_then_cancel), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect
        result = await service.run(job.id, max_concurrency=1)

    assert result.status == "cancelled"
    statuses = {entry["url"]: entry["status"] for entry in result.stage_log}
    assert statuses["https://example.com/p/1"] == "success"  # already in flight, completed
    assert statuses["https://example.com/p/2"] == "cancelled"
    assert statuses["https://example.com/p/3"] == "cancelled"


def test_job_service_get_missing_job_raises_not_found(tmp_path):
    service = _make_job_service(tmp_path)
    with pytest.raises(NotFoundError):
        service.get("does-not-exist")


# ---------------------------------------------------------------------------
# JobService - Output Format (UI -> ExtractionJob -> Pipeline -> DatasetBuilder
# -> WriterFactory), replacing the OUTPUT_FORMAT env var.
# ---------------------------------------------------------------------------

def test_job_service_create_job_stores_selected_output_format(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": []})

    csv_job = service.create_job(name="CSV Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es, output_format="csv")
    assert csv_job.output_format == "csv"
    assert service.get(csv_job.id).output_format == "csv"

    # Case/whitespace-tolerant, since it comes straight from a UI radio label.
    excel_job = service.create_job(name="Excel Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es, output_format=" Excel ")
    assert excel_job.output_format == "excel"


def test_job_service_create_job_defaults_to_excel_when_output_format_not_passed(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": []})

    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es)
    assert job.output_format == "excel"


@pytest.mark.asyncio
async def test_job_service_run_writes_csv_when_job_output_format_is_csv(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": [{"name": "price", "type": "string", "description": "Price"}]})
    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es, output_format="csv")

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect
        completed = await service.run(job.id, datasets_dir=str(tmp_path / "datasets"))

    save_info = completed.stage_log[0]["save_info"]
    assert save_info["output_format"] == "csv"
    assert save_info["output_path"].endswith(".csv")
    assert os.path.exists(save_info["output_path"])


@pytest.mark.asyncio
async def test_job_service_run_writes_excel_when_job_output_format_is_excel(tmp_path):
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": [{"name": "price", "type": "string", "description": "Price"}]})
    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es, output_format="excel")

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect
        completed = await service.run(job.id, datasets_dir=str(tmp_path / "datasets"))

    save_info = completed.stage_log[0]["save_info"]
    assert save_info["output_format"] == "excel"
    assert save_info["output_path"].endswith(".xlsx")
    assert os.path.exists(save_info["output_path"])


@pytest.mark.asyncio
async def test_job_service_run_records_clear_error_for_invalid_output_format(tmp_path):
    """execute_job() catches each URL's exception individually (so one bad
    URL doesn't crash a whole batch job) - an invalid output_format
    therefore surfaces as a failed job with the WriterFactory's ValueError
    message on the stage_log entry, not as a raised exception out of
    service.run() itself (see test_pipeline_run_raises_value_error_for_unknown_job_output_format
    in tests/test_job_executor.py for the layer where it genuinely raises)."""
    service = _make_job_service(tmp_path)
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": [{"name": "price", "type": "string", "description": "Price"}]})
    job = service.create_job(name="Job", urls=["https://example.com/p/1"], website_config=wc, extraction_schema=es, output_format="pdf")

    with patch("modules.dataset_builder.builder.fetch_webpage", new=_fake_fetch_webpage), \
         patch("modules.dataset_builder.builder.extract_web_data") as mock_extract, \
         patch.dict(os.environ, {"GEMINI_API_KEY": "test"}):
        mock_extract.side_effect = _llm_side_effect
        completed = await service.run(job.id, datasets_dir=str(tmp_path / "datasets"))

    assert completed.status == "failed"
    assert "Unknown output_format" in completed.stage_log[0]["error"]
