import os

from modules.adapter_loader import Adapter, AdapterLoader
from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from core.runtime_adapter import RuntimeAdapter


def test_runtime_adapter_from_config_and_schema_exposes_adapter_interface():
    wc = WebsiteConfig(name="Generic Site", domain="example.com")
    es = ExtractionSchema.from_dict({
        "name": "Generic Product",
        "fields": [{"name": "price", "type": "string", "description": "Price"}],
    })

    ra = RuntimeAdapter.from_config_and_schema(wc, es)

    assert ra.name == "Generic Site"
    assert ra.domain == "example.com"
    assert isinstance(ra.config, dict)
    assert isinstance(ra.schema, dict)
    assert "price" in ra.schema["extraction_fields"]

    profile = ra.get_profile()
    assert profile.domain == "example.com"

    model = ra.get_model()
    assert "price" in model.model_fields
    assert "royalty" not in model.model_fields  # no franchise base class


def test_runtime_adapter_from_adapter_bridges_legacy_file_based_adapter():
    adapter = Adapter(os.path.join("templates", "franchise_bazar"))
    ra = RuntimeAdapter.from_adapter(adapter)

    assert ra.name == "FranchiseBazar"
    assert ra.domain == "franchisebazar.com"
    assert ra.priority == 10
    # WebsiteConfig.to_dict() fills in default scoring weights that the raw
    # config.json didn't explicitly override, and doesn't model the
    # "dom_selectors" key (confirmed dead/unused - no module reads it) -
    # compare the fields that are actually consumed elsewhere in the codebase.
    for key in adapter.config.keys():
        if key == "dom_selectors":
            continue
        assert ra.config[key] == adapter.config[key]

    # Field content should match the adapter's own declared schema fields.
    assert set(ra.schema["extraction_fields"].keys()) == set(adapter.schema["extraction_fields"].keys())

    model = ra.get_model()
    assert "franchise_name" in model.model_fields


def test_runtime_adapter_get_model_is_cached():
    wc = WebsiteConfig(name="Generic Site")
    es = ExtractionSchema.from_dict({"name": "Generic", "fields": []})
    ra = RuntimeAdapter.from_config_and_schema(wc, es)

    model_a = ra.get_model()
    model_b = ra.get_model()
    assert model_a is model_b


def test_runtime_adapter_resolves_via_adapter_loader_from_templates_dir():
    adapter = AdapterLoader.load("https://franchisebazar.com/franchise/x")
    ra = RuntimeAdapter.from_adapter(adapter)
    assert ra.name == "FranchiseBazar"
