import json
import pytest
from modules.gemini import CanonicalFranchiseRecord, KeyValueItem
from modules.dataset_builder.schema_mapper import SchemaMapper
from modules.dataset_builder.record_validator import RecordValidator

def test_parse_investment_range():
    # Min/Max lakh range
    min_val, max_val = SchemaMapper.parse_investment_range("Rs. 50 Lakhs - 75 Lakhs")
    assert min_val == 5000000
    assert max_val == 7500000

    # Max only lakh
    min_val, max_val = SchemaMapper.parse_investment_range("upto 20 Lakhs")
    assert min_val is None
    assert max_val == 2000000

    # Crore range
    min_val, max_val = SchemaMapper.parse_investment_range("1.5 Cr - 2 Cr")
    assert min_val == 15000000
    assert max_val == 20000000

    # Min only
    min_val, max_val = SchemaMapper.parse_investment_range("Above ₹10 Lakhs")
    assert min_val == 1000000
    assert max_val is None

    # Empty fallback
    assert SchemaMapper.parse_investment_range(None) == (None, None)
    assert SchemaMapper.parse_investment_range("") == (None, None)


def test_parse_area_range():
    # Simple range
    min_val, max_val = SchemaMapper.parse_area_range("1000 - 2000 sq ft")
    assert min_val == 1000
    assert max_val == 2000

    # Single value min
    min_val, max_val = SchemaMapper.parse_area_range("500 sq ft")
    assert min_val == 500
    assert max_val is None


def test_schema_mapper_mapping_and_normalization():
    excel_cols = [
        "Franchise Name", "Brand", "Minimum Investment", "Maximum Investment",
        "Phone", "Email", "Website", "Additional Information"
    ]
    
    mapper = SchemaMapper(excel_columns=excel_cols)
    
    record = CanonicalFranchiseRecord(
        franchise_name="Pizza Hub",
        brand="Pizza Hub Inc.",
        investment_required="Rs. 10 Lakhs - 20 Lakhs",
        phone="+91-98765-43210",
        email="Contact@PizzaHub.Com ",
        website="pizzahub.com",
        preferred_locations="North India", # Core canonical field -> excluded from fallback
        additional_information=[KeyValueItem(key="info", value="Some extra text info")]
    )

    # Clean, validate and derive fields via the validation package first
    validated = RecordValidator.validate_record(record)
    validated = RecordValidator.derive_numeric_ranges(validated)

    result_dict = mapper.map_to_excel(validated, "https://pizzahub.com")

    # Mapped values
    assert result_dict["Franchise Name"] == "Pizza Hub"
    assert result_dict["Brand"] == "Pizza Hub Inc."
    
    # Normalized investment range
    assert result_dict["Minimum Investment"] == "1000000"
    assert result_dict["Maximum Investment"] == "2000000"

    # Normalized phone
    assert result_dict["Phone"] == "+91-98765-43210"

    # Normalized email
    assert result_dict["Email"] == "contact@pizzahub.com"

    # Normalized website
    assert result_dict["Website"] == "https://pizzahub.com"

    # Unmapped canonical fields and additional info in JSON fallback
    fallback_str = result_dict["Additional Information"]
    assert fallback_str != ""
    fallback_data = json.loads(fallback_str)
    
    # Preferred locations should be excluded from fallback because a dedicated schema field exists
    assert "preferred_locations" not in fallback_data
    assert fallback_data["info"] == "Some extra text info"
