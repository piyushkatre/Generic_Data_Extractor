import pytest
from modules.gemini import ExtractionResult, ExtractedEntity, ExtractedRecord, KeyValue
from modules.merger.merger import AIResultMerger

def test_result_merger_basic():
    # Setup test results
    res1 = ExtractionResult(
        page_title="Acme Corp",
        page_type="Company",
        page_summary="Found contact details.",
        entities=[
            ExtractedEntity(
                entity_type="Contact",
                records=[
                    ExtractedRecord(
                        attributes=[
                            KeyValue(key="email", value="sales@acme.com"),
                            KeyValue(key="phone", value="12345")
                        ]
                    )
                ]
            )
        ]
    )

    res2 = ExtractionResult(
        page_title="Acme Corp",
        page_type="Company",
        page_summary="Found executive details.",
        entities=[
            ExtractedEntity(
                entity_type="Contact",
                records=[
                    # Duplicate of res1
                    ExtractedRecord(
                        attributes=[
                            KeyValue(key="email", value="sales@acme.com"),
                            KeyValue(key="phone", value="12345")
                        ]
                    ),
                    # New record
                    ExtractedRecord(
                        attributes=[
                            KeyValue(key="email", value="support@acme.com"),
                            KeyValue(key="phone", value="67890")
                        ]
                    )
                ]
            ),
            ExtractedEntity(
                entity_type="Executive",
                records=[
                    ExtractedRecord(
                        attributes=[
                            KeyValue(key="name", value="John Doe"),
                            KeyValue(key="role", value="CEO")
                        ]
                    )
                ]
            )
        ]
    )

    merger = AIResultMerger()
    merged = merger.merge([res1, res2])

    assert merged.page_title == "Acme Corp"
    assert merged.page_type == "Company"
    assert "Found contact details." in merged.page_summary
    assert "Found executive details." in merged.page_summary

    # Contacts should have merged and deduplicated (1 duplicate removed, 1 new added -> total 2 records)
    contact_entity = next((e for e in merged.entities if e.entity_type == "Contact"), None)
    assert contact_entity is not None
    assert len(contact_entity.records) == 2

    # Executive entity should be preserved
    exec_entity = next((e for e in merged.entities if e.entity_type == "Executive"), None)
    assert exec_entity is not None
    assert len(exec_entity.records) == 1
    assert exec_entity.records[0].attributes[0].value == "John Doe"

def test_json_repair_basic():
    from modules.gemini import repair_json_string
    # Case 1: Trailing commas
    assert repair_json_string('{"a": 1,}') == '{"a": 1}'
    assert repair_json_string('{"a": [1, 2,],}') == '{"a": [1, 2]}'
    
    # Case 2: Markdown block
    assert repair_json_string('```json\n{"a": 1}\n```') == '{"a": 1}'
    
    # Case 3: Missing closing quotes (unterminated string)
    assert repair_json_string('{"a": "hello') == '{"a": "hello"}'
    
    # Case 4: Missing closing braces/brackets (truncation)
    assert repair_json_string('{"a": {"b": 1') == '{"a": {"b": 1}}'
    assert repair_json_string('{"a": [{"b": 1') == '{"a": [{"b": 1}]}'

