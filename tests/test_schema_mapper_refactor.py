import pytest
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from modules.dataset_builder.schema_mapper import AliasRegistry, SchemaMapper
from modules.adapter_loader import CanonicalFranchiseRecord, KeyValueItem

def test_automatic_alias_generation():
    excel_cols = ["Investment Required", "Franchise Name"]
    manual_aliases = {"investment_required": ["capital required"]}
    schema_aliases = {"investment": "Investment Required"}
    
    registry = AliasRegistry(
        excel_columns=excel_cols,
        manual_aliases=manual_aliases,
        schema_aliases=schema_aliases
    )
    
    # Check generated variations for investment_required
    aliases = registry.canonical_aliases.get("investment_required", set())
    assert "investment required" in aliases
    assert "Investment Required" in aliases
    assert "investment_required" in aliases
    assert "capital required" in aliases
    assert "capital_required" in aliases
    assert "investment" in aliases
    assert "investmentrequired" in aliases

def test_bidirectional_alias_resolution():
    excel_cols = ["Franchise Name", "Investment Required"]
    manual_aliases = {"investment_required": ["capital required"], "franchise_name": ["brand"]}
    schema_aliases = {}
    
    registry = AliasRegistry(
        excel_columns=excel_cols,
        manual_aliases=manual_aliases,
        schema_aliases=schema_aliases
    )
    
    # Resolve from manual alias
    col, score, m_type = registry.resolve_field_to_column("capital required")
    assert col == "Investment Required"
    assert score == 0.95
    assert m_type == "Alias Match"
    
    # Resolve from canonical field directly
    col, score, m_type = registry.resolve_field_to_column("investment_required")
    assert col == "Investment Required"
    assert score == 0.95  # Alias match because "Investment Required" is in variations
    
    # Resolve from auto-generated casing variation
    col, score, m_type = registry.resolve_field_to_column("BRAND")
    assert col == "Franchise Name"
    assert score >= 0.90

def test_confidence_based_matching():
    excel_cols = ["Products / Services", "Phone Number", "Total Capital"]
    manual_aliases = {"investment_required": ["capital"]}
    schema_aliases = {}
    
    registry = AliasRegistry(excel_cols, manual_aliases, schema_aliases)
    
    # Exact match vs. lower confidence matches
    col, score, m_type = registry.resolve_field_to_column("Phone Number")
    assert col == "Phone Number"
    assert score == 1.0
    assert m_type == "Exact Match"
    
    # Normalized/Fuzzy match for "Total Capital"
    col, score, m_type = registry.resolve_field_to_column("capital")
    assert col == "Total Capital"
    assert score >= 0.60

def test_multi_field_column_merging():
    excel_cols = ["Products / Services", "Franchise Name"]
    schema = {
        "name": "Test Adapter",
        "config": {
            "mergeable_columns": ["Products / Services"],
            "array_delimiter": " | "
        },
        "aliases": {
            "products": "Products / Services",
            "services": "Products / Services"
        }
    }
    
    mapper = SchemaMapper(excel_columns=excel_cols, schema=schema)
    
    # Mock CanonicalFranchiseRecord or a custom model
    class MockRecord(BaseModel):
        franchise_name: str
        products: List[str]
        services: List[str]
        metadata: List[Any] = Field(default_factory=list)
        
    record = MockRecord(
        franchise_name="Merge Gym",
        products=["Gym Equipment", "Dumbbells"],
        services=["Personal Training", "Yoga Class"]
    )
    
    mapped_res = mapper.map_to_excel(record, source_url="https://testmerge.com")
    
    assert mapped_res["Franchise Name"] == "Merge Gym"
    # Merged array elements without duplicates, joined by " | "
    products_services_val = mapped_res["Products / Services"]
    assert "Gym Equipment" in products_services_val
    assert "Dumbbells" in products_services_val
    assert "Personal Training" in products_services_val
    assert "Yoga Class" in products_services_val
    assert " | " in products_services_val

def test_array_formatting_delimiters():
    excel_cols = ["Images", "Franchise Name"]
    schema = {
        "name": "Test Adapter",
        "config": {
            "array_delimiter": "; "
        }
    }
    mapper = SchemaMapper(excel_columns=excel_cols, schema=schema)
    
    class MockRecord(BaseModel):
        franchise_name: str
        images: List[str]
        metadata: List[Any] = Field(default_factory=list)
        
    record = MockRecord(
        franchise_name="Array Brand",
        images=["img1.png", "img2.jpg"]
    )
    
    mapped_res = mapper.map_to_excel(record, source_url="https://testarray.com")
    assert mapped_res["Images"] == "img1.png; img2.jpg"

def test_unmapped_field_reporting_in_metadata():
    excel_cols = ["Franchise Name"]
    mapper = SchemaMapper(excel_columns=excel_cols)
    
    class MockRecord(BaseModel):
        franchise_name: str
        unmapped_test_field: str
        metadata: List[Any] = Field(default_factory=list)
        
    record = MockRecord(
        franchise_name="Test Brand",
        unmapped_test_field="Some raw extraction value"
    )
    
    # This should warn and map to excel, adding coverage metrics and unmapped fields lists to metadata
    mapper.map_to_excel(record, source_url="https://testwarn.com")
    
    metadata_keys = [item.key for item in record.metadata]
    assert "unmapped_count" in metadata_keys
    assert "unmapped_fields_list" in metadata_keys
    
    # Retrieve value for unmapped_fields_list
    unmapped_fields_val = next(item.value for item in record.metadata if item.key == "unmapped_fields_list")
    assert "unmapped_test_field" in unmapped_fields_val
