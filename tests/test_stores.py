import pytest

from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from config.extraction_job import ExtractionJob
from config.config_store import ConfigStore
from config.schema_store import SchemaStore
from config.job_store import JobStore


# ---------------------------------------------------------------------------
# ConfigStore
# ---------------------------------------------------------------------------

def test_config_store_save_load_round_trip(tmp_path):
    store = ConfigStore(storage_dir=str(tmp_path / "configs"))
    wc = WebsiteConfig(name="IndiaMART Products", domain="indiamart.com", priority=5)

    config_id = store.save(wc)
    loaded = store.load(config_id)

    assert loaded.name == "IndiaMART Products"
    assert loaded.domain == "indiamart.com"
    assert loaded.priority == 5


def test_config_store_list_and_delete(tmp_path):
    store = ConfigStore(storage_dir=str(tmp_path / "configs"))
    id1 = store.save(WebsiteConfig(name="Site A"), config_id="site-a")
    id2 = store.save(WebsiteConfig(name="Site B"), config_id="site-b")

    listing = {row["id"]: row["name"] for row in store.list()}
    assert listing == {"site-a": "Site A", "site-b": "Site B"}

    store.delete(id1)
    assert not store.exists(id1)
    assert store.exists(id2)
    assert [row["id"] for row in store.list()] == ["site-b"]


def test_config_store_missing_id_raises(tmp_path):
    store = ConfigStore(storage_dir=str(tmp_path / "configs"))
    with pytest.raises(KeyError):
        store.load("does-not-exist")


# ---------------------------------------------------------------------------
# SchemaStore
# ---------------------------------------------------------------------------

def test_schema_store_save_load_round_trip(tmp_path):
    store = SchemaStore(storage_dir=str(tmp_path / "schemas"))
    es = ExtractionSchema.from_dict({
        "name": "Generic Product",
        "fields": [
            {"name": "product_name", "type": "string", "description": "Name"},
            {"name": "price", "type": "string", "description": "Price", "required": True},
        ],
    })

    schema_id = store.save(es)
    loaded = store.load(schema_id)

    assert loaded.name == "Generic Product"
    assert loaded.field_names() == ["product_name", "price"]
    assert loaded.required_field_names == ["price"]


def test_schema_store_preserves_optional_field_metadata(tmp_path):
    """extraction_owner/merge_policy/format must survive a save/load round-trip."""
    store = SchemaStore(storage_dir=str(tmp_path / "schemas"))
    es = ExtractionSchema.from_dict({
        "name": "Custom Ownership Schema",
        "fields": [
            {
                "name": "price", "type": "string", "description": "Price",
                "extraction_owner": "deterministic", "merge_policy": "deterministic_only",
            },
        ],
    })
    schema_id = store.save(es)
    loaded = store.load(schema_id)

    field = loaded.get_field("price")
    assert field.extraction_owner == "deterministic"
    assert field.merge_policy == "deterministic_only"


def test_schema_store_list(tmp_path):
    store = SchemaStore(storage_dir=str(tmp_path / "schemas"))
    store.save(ExtractionSchema.from_dict({"name": "A", "fields": []}), schema_id="a")
    store.save(ExtractionSchema.from_dict({
        "name": "B", "fields": [{"name": "x", "type": "string", "description": ""}]
    }), schema_id="b")

    listing = {row["id"]: row["field_count"] for row in store.list()}
    assert listing == {"a": 0, "b": 1}


# ---------------------------------------------------------------------------
# JobStore
# ---------------------------------------------------------------------------

def _make_job(name="Test Job"):
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": []})
    return ExtractionJob(name=name, urls=["https://example.com/1"], website_config=wc, extraction_schema=es)


def test_job_store_save_load_round_trip(tmp_path):
    store = JobStore(storage_dir=str(tmp_path / "jobs"))
    job = _make_job()
    job.mark_running()
    job.add_url_result("https://example.com/1", {"status": "success"})
    job.mark_completed("storage/outputs/x.csv")

    store.save(job)
    loaded = store.load(job.id)

    assert loaded.id == job.id
    assert loaded.status == "completed"
    assert loaded.output_path == "storage/outputs/x.csv"
    assert loaded.stage_log == [{"url": "https://example.com/1", "status": "success"}]
    assert loaded.website_config.name == "Generic Site"
    assert loaded.extraction_schema.name == "Generic"


def test_job_store_list(tmp_path):
    store = JobStore(storage_dir=str(tmp_path / "jobs"))
    job1 = _make_job("Job One")
    job2 = _make_job("Job Two")
    job2.mark_completed()

    store.save(job1)
    store.save(job2)

    listing = {row["id"]: row["status"] for row in store.list()}
    assert listing == {job1.id: "created", job2.id: "completed"}
