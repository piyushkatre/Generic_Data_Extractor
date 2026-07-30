import os
import pytest
from unittest.mock import patch, MagicMock
import httpx
import json
from pydantic import BaseModel

from modules.llm.factory import get_llm_provider
from modules.llm.ollama_provider import OllamaProvider, OllamaModelUnavailableError, classify_transport_error
from modules.llm.gemini_provider import GeminiProvider
from modules.adapter_loader import ExtractionResult, ExtractedEntity, ExtractedRecord, KeyValue
from modules.config import ExtractorConfig

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


# ------------------------------------------------------------------
# Configurable timeout (Task 3 / Task 7): OLLAMA_TIMEOUT and
# OLLAMA_CONNECT_TIMEOUT flow from env -> ExtractorConfig -> the
# httpx.Timeout object passed to httpx.post().
# ------------------------------------------------------------------

def test_config_reads_ollama_timeout_env_vars():
    with patch.dict(os.environ, {"OLLAMA_TIMEOUT": "900", "OLLAMA_CONNECT_TIMEOUT": "5"}):
        config = ExtractorConfig.load()
    assert config.OLLAMA_TIMEOUT == 900.0
    assert config.OLLAMA_CONNECT_TIMEOUT == 5.0


def test_config_ollama_timeout_defaults_when_unset():
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OLLAMA_TIMEOUT", None)
        os.environ.pop("OLLAMA_CONNECT_TIMEOUT", None)
        config = ExtractorConfig.load()
    assert config.OLLAMA_TIMEOUT == 600.0
    assert config.OLLAMA_CONNECT_TIMEOUT == 10.0


@patch("httpx.post")
def test_ollama_post_uses_configured_timeout(mock_post, mock_extraction_result):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": mock_extraction_result.model_dump_json()}
    }
    mock_post.return_value = mock_response

    with patch.dict(os.environ, {"OLLAMA_TIMEOUT": "123", "OLLAMA_CONNECT_TIMEOUT": "7"}):
        provider = OllamaProvider()
        provider.extract(
            html_content="<html><body>Test</body></html>",
            response_model=ExtractionResult
        )

    used_timeout = mock_post.call_args.kwargs["timeout"]
    assert isinstance(used_timeout, httpx.Timeout)
    assert used_timeout.read == 123.0
    assert used_timeout.connect == 7.0


# ------------------------------------------------------------------
# classify_transport_error (Task 2 / Task 4): purely type-based
# classification, no model-specific or website-specific branching.
# ------------------------------------------------------------------

def test_classify_transport_error_connection_failure():
    assert classify_transport_error(httpx.ConnectError("refused")) == "connection failure"
    assert classify_transport_error(httpx.ConnectTimeout("refused")) == "connection failure"


def test_classify_transport_error_timeout():
    assert classify_transport_error(httpx.ReadTimeout("slow")) == "timeout"
    assert classify_transport_error(httpx.PoolTimeout("pool full")) == "timeout"


def test_classify_transport_error_other_transport_failure():
    request = httpx.Request("POST", "http://localhost:11434/api/chat")
    response = httpx.Response(status_code=500, request=request)
    err = httpx.HTTPStatusError("server error", request=request, response=response)
    assert classify_transport_error(err) == "transport failure"


# ------------------------------------------------------------------
# Model-unavailable (Task 3 / Task 4): a 404 or an {"error": ...} body
# is a real HTTP response, not a transport failure - it must raise
# immediately and NOT be retried, since retrying can't make a missing
# model appear.
# ------------------------------------------------------------------

@patch("httpx.post")
def test_ollama_model_unavailable_404_fails_fast_no_retry(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.json.return_value = {"error": "model 'qwen2.5:7b' not found, try pulling it first"}
    mock_post.return_value = mock_response

    provider = OllamaProvider()
    metrics = {"requests": 0, "retries": 0}

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(OllamaModelUnavailableError):
            provider.extract(
                html_content="<html><body>Test</body></html>",
                response_model=ExtractionResult,
                context_metrics=metrics
            )

    assert mock_post.call_count == 1
    assert metrics["requests"] == 1
    assert metrics["retries"] == 0
    mock_sleep.assert_not_called()


@patch("httpx.post")
def test_ollama_model_unavailable_error_field_in_200_response_fails_fast(mock_post):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"error": "model not found"}
    mock_post.return_value = mock_response

    provider = OllamaProvider()
    with pytest.raises(OllamaModelUnavailableError):
        provider.extract(
            html_content="<html><body>Test</body></html>",
            response_model=ExtractionResult
        )

    assert mock_post.call_count == 1


# ------------------------------------------------------------------
# Read timeouts are still retried (only genuinely unrecoverable
# failures like a missing model skip retry) - a ReadTimeout behaves
# exactly like the pre-existing ConnectError retry test.
# ------------------------------------------------------------------

@patch("httpx.post")
def test_ollama_extraction_retry_on_read_timeout(mock_post, mock_extraction_result):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": mock_extraction_result.model_dump_json()}
    }

    mock_post.side_effect = [
        httpx.ReadTimeout("timed out"),
        mock_response
    ]

    metrics = {"requests": 0, "retries": 0}
    provider = OllamaProvider()

    with patch("time.sleep") as mock_sleep:
        result = provider.extract(
            html_content="<html><body>Test</body></html>",
            response_model=ExtractionResult,
            context_metrics=metrics
        )

    assert isinstance(result, ExtractionResult)
    assert mock_post.call_count == 2
    assert metrics["requests"] == 2
    assert metrics["retries"] == 1
    mock_sleep.assert_called_once()

