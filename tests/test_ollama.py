import os
import pytest
from unittest.mock import patch, MagicMock
import httpx
import json
from pydantic import BaseModel

from modules.llm.factory import get_llm_provider
from modules.llm.ollama_provider import OllamaProvider
from modules.llm.gemini_provider import GeminiProvider
from modules.adapter_loader import ExtractionResult, ExtractedEntity, ExtractedRecord, KeyValue

@pytest.fixture
def mock_extraction_result():
    return ExtractionResult(
        page_title="Ollama Test Portal",
        page_type="Product Catalog",
        page_summary="Test summary.",
        entities=[
            ExtractedEntity(
                entity_type="Company",
                records=[
                    ExtractedRecord(
                        attributes=[
                            KeyValue(key="name", value="Ollama Corp"),
                            KeyValue(key="phone", value="+1 123 456 7890")
                        ]
                    )
                ]
            )
        ]
    )

def test_provider_factory_resolution():
    with patch.dict(os.environ, {"LLM_PROVIDER": "gemini"}):
        provider = get_llm_provider()
        assert isinstance(provider, GeminiProvider)

    with patch.dict(os.environ, {"LLM_PROVIDER": "ollama"}):
        provider = get_llm_provider()
        assert isinstance(provider, OllamaProvider)

@patch("httpx.post")
def test_ollama_extraction_success(mock_post, mock_extraction_result):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": mock_extraction_result.model_dump_json()
        }
    }
    mock_post.return_value = mock_response

    provider = OllamaProvider()
    result = provider.extract(
        html_content="<html><body>Test</body></html>",
        user_instructions="Extract info",
        response_model=ExtractionResult
    )

    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Ollama Test Portal"
    assert result.entities[0].records[0].attributes[0].value == "Ollama Corp"
    mock_post.assert_called_once()

@patch("httpx.post")
def test_ollama_extraction_retry_on_connection_error(mock_post, mock_extraction_result):
    # First call raises ConnectError, second call succeeds
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": mock_extraction_result.model_dump_json()
        }
    }
    
    mock_post.side_effect = [
        httpx.ConnectError("Connection refused"),
        mock_response
    ]

    metrics = {"requests": 0, "retries": 0}
    provider = OllamaProvider()
    
    with patch("time.sleep") as mock_sleep:  # bypass delay in tests
        result = provider.extract(
            html_content="<html><body>Test</body></html>",
            response_model=ExtractionResult,
            context_metrics=metrics
        )

    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Ollama Test Portal"
    assert mock_post.call_count == 2
    assert metrics["requests"] == 2
    assert metrics["retries"] == 1
    mock_sleep.assert_called_once()

@patch("httpx.post")
def test_ollama_json_repair_fallback(mock_post, mock_extraction_result):
    # Ollama returns malformed JSON with trailing comma inside closing brace
    malformed_json = '{"page_title": "Ollama Test Portal", "page_type": "Product Catalog", "page_summary": "Test summary.", "entities": [],}'
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": malformed_json
        }
    }
    mock_post.return_value = mock_response

    provider = OllamaProvider()
    result = provider.extract(
        html_content="<html><body>Test</body></html>",
        response_model=ExtractionResult
    )

    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Ollama Test Portal"
    mock_post.assert_called_once()


# ------------------------------------------------------------------
# Test Schema and Models for Normalization Tests
# ------------------------------------------------------------------
class TestChild(BaseModel):
    name: str

class TestParent(BaseModel):
    tags: list[str]
    children: list[TestChild]
    scalar_field: str


def test_normalization_logic():
    from modules.llm.ollama_provider import normalize_data

    # 1. Test Object -> List wrapping
    raw_data = {
        "tags": ["a", "b"],
        "children": {"name": "Child1"},
        "scalar_field": "hello"
    }
    logs = []
    normalized = normalize_data(raw_data, TestParent, logs)
    assert normalized["children"] == [{"name": "Child1"}]
    assert "• children : dict → list" in logs

    # 2. Test String -> List splitting (comma)
    raw_data_comma = {
        "tags": "tag1, tag2, tag3",
        "children": [{"name": "Child1"}],
        "scalar_field": "hello"
    }
    logs = []
    normalized = normalize_data(raw_data_comma, TestParent, logs)
    assert normalized["tags"] == ["tag1", "tag2", "tag3"]
    assert "• tags : str → list (3 items)" in logs

    # 3. Test String -> List splitting (newline)
    raw_data_newline = {
        "tags": "tagA\ntagB",
        "children": [{"name": "Child1"}],
        "scalar_field": "hello"
    }
    logs = []
    normalized = normalize_data(raw_data_newline, TestParent, logs)
    assert normalized["tags"] == ["tagA", "tagB"]
    assert "• tags : str → list (2 items)" in logs

    # 4. Test already-valid array and scalar untouched
    raw_data_valid = {
        "tags": ["tag1"],
        "children": [{"name": "Child1"}],
        "scalar_field": "hello"
    }
    logs = []
    normalized = normalize_data(raw_data_valid, TestParent, logs)
    assert normalized == raw_data_valid
    assert not logs


@patch("httpx.post")
def test_ollama_immediate_fail_on_schema_validation_error(mock_post):
    # Ollama returns valid JSON but with invalid keys that normalization cannot fix
    invalid_response = {
        "tags": ["a"],
        "children": [{"name_invalid_key": "Child1"}],  # missing required 'name' field
        "scalar_field": "hello"
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": json.dumps(invalid_response)
        }
    }
    mock_post.return_value = mock_response

    provider = OllamaProvider()
    metrics = {"requests": 0, "retries": 0}
    
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        provider.extract(
            html_content="<html><body>Test</body></html>",
            response_model=TestParent,
            context_metrics=metrics
        )
    
    # Verify that it was only called once and did not enter retry loop for validation error
    assert mock_post.call_count == 1
    assert metrics["requests"] == 1


@patch("httpx.post")
@patch("modules.llm.ollama_provider.get_latest_debug_dir")
@patch("os.makedirs")
@patch("builtins.open")
def test_ollama_raw_response_saved_in_debug_mode(mock_open, mock_makedirs, mock_get_latest_debug_dir, mock_post, mock_extraction_result):
    mock_get_latest_debug_dir.return_value = "debug/run_test_run"
    
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {
            "role": "assistant",
            "content": mock_extraction_result.model_dump_json()
        }
    }
    mock_post.return_value = mock_response

    provider = OllamaProvider()
    
    with patch.dict(os.environ, {"DEBUG": "true"}):
        provider.extract(
            html_content="<html><body>Test</body></html>",
            response_model=ExtractionResult
        )

    # Verify raw response file creation
    mock_makedirs.assert_called_once_with("debug/run_test_run", exist_ok=True)
    expected_raw_path = os.path.join("debug/run_test_run", "06_ollama_raw_response.json")
    expected_norm_path = os.path.join("debug/run_test_run", "06_ollama_normalized.json")
    
    mock_open.assert_any_call(expected_raw_path, "w", encoding="utf-8")
    mock_open.assert_any_call(expected_norm_path, "w", encoding="utf-8")


def test_key_value_item_normalization_mapping():
    from modules.llm.ollama_provider import normalize_data
    from modules.adapter_loader import KeyValueItem

    class TestKeyValueModel(BaseModel):
        additional_info: list[KeyValueItem]

    # Input dictionary that needs normalization
    raw_data = {
        "additional_info": {
            "description": "This is a gym.",
            "faq": [],
            "area": "1500 sqft"
        }
    }
    logs = []
    normalized = normalize_data(raw_data, TestKeyValueModel, logs)
    
    assert isinstance(normalized["additional_info"], list)
    assert len(normalized["additional_info"]) == 3
    
    # Check that entries are properly mapped into KeyValueItem compatible structures
    description_item = next(item for item in normalized["additional_info"] if item["key"] == "description")
    assert description_item["value"] == "This is a gym."
    
    faq_item = next(item for item in normalized["additional_info"] if item["key"] == "faq")
    assert faq_item["value"] == []
    
    area_item = next(item for item in normalized["additional_info"] if item["key"] == "area")
    assert area_item["value"] == "1500 sqft"
    
    # Assert logs recorded the conversion
    assert "List[KeyValueItem]" in "".join(logs)

    # Already correct format shouldn't change
    correct_data = {
        "additional_info": [
            {"key": "description", "value": "gym"},
            {"key": "area", "value": "1500"}
        ]
    }
    logs = []
    normalized_correct = normalize_data(correct_data, TestKeyValueModel, logs)
    assert normalized_correct == correct_data
    assert not logs

