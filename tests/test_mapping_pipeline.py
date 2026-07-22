import pytest
import os
import tempfile
import openpyxl
from unittest.mock import MagicMock, patch
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from modules.dataset_builder.schema_mapper import MappingResult, SchemaMapper
from modules.dataset_builder.record_mapper import RecordMapper, ValidationError
from modules.dataset_builder.builder import DatasetBuilder
from modules.adapter_loader import CanonicalFranchiseRecord, KeyValueItem

def test_mapping_result_value_object_behavior():
    mapped_data = {
        "Franchise Name": "Gym Pro",
        "Phone": "+91-99999-99999",
        "Email": "info@gympro.com"
    }
    
    mr = MappingResult(
        mapped_record=mapped_data,
        mapped_fields=["Franchise Name", "Phone", "Email"],
        unmapped_fields=["extra_key"],
        merged_fields=[],
        confidence_scores={"Franchise Name": 1.0, "Phone": 0.95},
        coverage_statistics={"coverage_percentage": "100.0%"},
        normalization_statistics={"normalized_count": 2, "merged_count": 0}
    )
    
    # 1. Assert it is NOT a subclass or direct instance of dict
    assert not isinstance(mr, dict)
    
    # 2. Assert it behaves like a dict via helper magic methods
    assert mr["Franchise Name"] == "Gym Pro"
    assert mr.get("Email") == "info@gympro.com"
    assert mr.get("Nonexistent", "default") == "default"
    assert "Phone" in mr
    
    # Check iteration/views
    assert sorted(list(mr.keys())) == ["Email", "Franchise Name", "Phone"]
    assert sorted(list(mr.values())) == ["+91-99999-99999", "Gym Pro", "info@gympro.com"]

def test_schema_mapper_returns_mapping_result():
    excel_cols = ["Franchise Name", "Minimum Investment", "Additional Information"]
    mapper = SchemaMapper(excel_columns=excel_cols)
    
    class MockRecord(BaseModel):
        franchise_name: str
        investment_required: str
        extra_info: str
        metadata: List[Any] = Field(default_factory=list)
        
    record = MockRecord(
        franchise_name="Pizza Hut",
        investment_required="Rs. 50 Lakhs",
        extra_info="High profit model"
    )
    
    from modules.dataset_builder.record_validator import RecordValidator
    validated_record = RecordValidator.validate_record(record)
    validated_record = RecordValidator.derive_numeric_ranges(validated_record)
    
    mapping_res = mapper.map_to_excel(validated_record, source_url="https://pizza.com")
    
    assert isinstance(mapping_res, MappingResult)
    assert mapping_res.mapped_record["Franchise Name"] == "Pizza Hut"
    assert mapping_res.mapped_record["Minimum Investment"] == "5000000"
    
    # Verify metadata arrays inside MappingResult
    assert "franchise_name" in mapping_res.mapped_fields or "Franchise Name" in mapping_res.mapped_fields
    assert "extra_info" in mapping_res.unmapped_fields
    assert "coverage_percentage" in mapping_res.coverage_statistics

def test_record_mapper_validation_wrapper():
    schema = {
        "columns": ["Franchise Name", "Phone", "Revenue"],
        "required_fields": ["Revenue"]
    }
    
    record_mapper = RecordMapper(schema)
    
    class MockRecord(BaseModel):
        franchise_name: str
        phone: str
        revenue: str
        metadata: List[Any] = Field(default_factory=list)
        
    # Test successful validation
    rec_valid = MockRecord(franchise_name="Valid Gym", phone="12345", revenue="100")
    res = record_mapper.map(rec_valid, source_url="https://test.com")
    assert isinstance(res, MappingResult)
    assert res.mapped_record["Franchise Name"] == "Valid Gym"
    
    # Test failed validation (missing required field)
    rec_invalid = MockRecord(franchise_name="Gym", phone="12345", revenue="")
    with pytest.raises(ValidationError):
        record_mapper.map(rec_invalid, source_url="https://test.com")

def test_dataset_builder_bypasses_duplicate_mapping():
    schema = {
        "columns": ["Franchise Name", "Phone"],
        "primary_key": ["Franchise Name"],
        "sheet_name": "General Data",
        "dataset_name": "unified_test.xlsx"
    }
    
    mapped_data = {
        "Franchise Name": "Direct Gym",
        "Phone": "987654"
    }
    
    mr = MappingResult(
        mapped_record=mapped_data,
        mapped_fields=["Franchise Name", "Phone"],
        unmapped_fields=[],
        merged_fields=[],
        confidence_scores={},
        coverage_statistics={},
        normalization_statistics={}
    )
    
    with tempfile.TemporaryDirectory() as temp_dir:
        from modules.dataset_builder.manager import WorkbookManager
        
        builder = DatasetBuilder(schemas_dir=temp_dir, datasets_dir=temp_dir)
        builder.manager = WorkbookManager(datasets_dir=temp_dir)
        
        # Mock schema loader so it loads our custom test schema
        builder.schema_loader.load_schema = MagicMock(return_value=schema)
        
        # Patch RecordMapper to ensure it is NEVER called when MappingResult is passed
        with patch("modules.dataset_builder.builder.RecordMapper") as mock_mapper_cls:
            res_save = builder.save_extraction_result(
                result=mr,
                source_url="https://direct.com",
                detected_page_type="General Data",
                timestamp="2026-07-06 12:00:00"
            )
            
            # Assert mock RecordMapper was not instantiated
            mock_mapper_cls.assert_not_called()
            
            assert res_save["status"] == "Success"
            assert res_save["operation"] == "Inserted"
