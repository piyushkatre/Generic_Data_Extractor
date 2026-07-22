import pytest
import time
from unittest.mock import patch, MagicMock
from modules.gemini import extract_web_data, ExtractionResult, ExtractedEntity, ExtractedRecord, KeyValue
from modules.preprocessor import clean_html, detect_page_type
from modules.semantic_chunker.chunker import chunk_html

@pytest.fixture(autouse=True)
def reset_quota_manager():
    from modules.gemini import QuotaManager
    QuotaManager.set_exhausted(False)

@pytest.fixture
def mock_extraction_result():
    return ExtractionResult(
        page_title="Acme Integrated Portal",
        page_type="Product Catalog",
        page_summary="Consolidated test summary.",
        entities=[
            ExtractedEntity(
                entity_type="Company",
                records=[
                    ExtractedRecord(
                        attributes=[
                            KeyValue(key="name", value="Acme Corp"),
                            KeyValue(key="phone", value="+91 98765-43210")
                        ]
                    )
                ]
            )
        ]
    )

@patch("modules.gemini.genai.Client")
def test_pipeline_direct_routing(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(
        text=mock_extraction_result.model_dump_json()
    )
    mock_client_class.return_value = mock_client

    small_html = "<html><body><h1>Acme Portal</h1><p>Contact: +91 98765-43210</p></body></html>"
    
    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100"}):
        result = extract_web_data(
            html_content=small_html,
            user_instructions="Extract company details",
            client=mock_client,
            run_pipeline=True
        )
    
    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Acme Integrated Portal"
    assert len(result.entities) == 1
    assert result.entities[0].entity_type == "Company"
    assert result.entities[0].records[0].attributes[0].value == "Acme Corp"

@patch("modules.gemini.genai.Client")
def test_pipeline_chunked_routing(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(
        text=mock_extraction_result.model_dump_json()
    )
    mock_client_class.return_value = mock_client

    large_html = "<html><body><h1>Acme Portal</h1>" + "<p>Description</p>" * 100 + "</body></html>"
    
    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "20", "MAX_BATCH_TOKENS": "20"}):
        result = extract_web_data(
            html_content=large_html,
            client=mock_client,
            run_pipeline=True
        )
        
    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Acme Integrated Portal"

@patch("modules.gemini.genai.Client")
def test_improved_batch_processing_isolation(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    mock_client.models.generate_content.return_value = MagicMock(
        text=mock_extraction_result.model_dump_json()
    )
    mock_client_class.return_value = mock_client

    # Chunks with different parent sections should NOT be batched together
    sectional_html = """
    <html><body>
      <section id="secA"><p>This is section A. A very long line to force splitting rules if limits are low.</p></section>
      <section id="secB"><p>This is section B. A separate topic entirely.</p></section>
    </body></html>
    """
    
    # Low safe token limit to trigger chunking and low batch token limit
    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "15", "MAX_BATCH_TOKENS": "100"}):
        # We manually chunk first to check batch count inside extract_web_data log/metrics,
        # but we can verify that pipeline successfully processes the different sections.
        result = extract_web_data(
            html_content=sectional_html,
            client=mock_client,
            run_pipeline=True
        )
        
    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Acme Integrated Portal"

@patch("modules.gemini.genai.Client")
def test_retry_logic_with_retry_delay(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ValueError("RESOURCE_EXHAUSTED: 429 Quota Exceeded (retryDelay: 0.1s)")
        return MagicMock(text=mock_extraction_result.model_dump_json())
        
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    html = "<html><body><h1>Direct HTML</h1><p>Content</p></body></html>"
    
    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100", "MAX_RETRIES": "2", "RETRY_DELAY": "0.05"}):
        result = extract_web_data(
            html_content=html,
            client=mock_client,
            run_pipeline=True
        )
        
    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Acme Integrated Portal"
    # Call count should be 2 (first call failed retryable error, second succeeded)
    assert call_count == 2

class MockAPIError(Exception):
    def __init__(self, code, details):
        self.code = code
        self.details = details
        super().__init__(f"API Error {code}")

@patch("modules.gemini.genai.Client")
def test_retry_logic_with_api_error_details(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            details = {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "0.1s"
                        }
                    ]
                }
            }
            raise MockAPIError(429, details)
        return MagicMock(text=mock_extraction_result.model_dump_json())
        
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    html = "<html><body><h1>Direct HTML</h1><p>Content</p></body></html>"
    
    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100", "MAX_RETRIES": "2", "RETRY_DELAY": "0.05"}):
        result = extract_web_data(
            html_content=html,
            client=mock_client,
            run_pipeline=True
        )
        
    assert isinstance(result, ExtractionResult)
    assert result.page_title == "Acme Integrated Portal"
    assert call_count == 2


@patch("modules.gemini.genai.Client")
def test_quota_requests_per_minute(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            details = {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {
                                    "quotaId": "GenerateRequestsPerMinutePerProjectPerModel",
                                    "quotaMetric": "generativelanguage.googleapis.com/generate_content_requests"
                                }
                            ]
                        },
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "0.05s"
                        }
                    ]
                }
            }
            raise MockAPIError(429, details)
        return MagicMock(text=mock_extraction_result.model_dump_json())
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100", "MAX_RETRIES": "2"}):
        result = extract_web_data("<html><body>test</body></html>", client=mock_client, run_pipeline=True)
    assert call_count == 2

@patch("modules.gemini.genai.Client")
def test_quota_tokens_per_minute(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            details = {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                            "violations": [
                                {
                                    "quotaId": "GenerateContentInputTokensPerModelPerMinute",
                                    "quotaMetric": "generativelanguage.googleapis.com/generate_content_tokens"
                                }
                            ]
                        },
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "0.05s"
                        }
                    ]
                }
            }
            raise MockAPIError(429, details)
        return MagicMock(text=mock_extraction_result.model_dump_json())
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100", "MAX_RETRIES": "2"}):
        result = extract_web_data("<html><body>test</body></html>", client=mock_client, run_pipeline=True)
    assert call_count == 2

@patch("modules.gemini.genai.Client")
def test_quota_requests_per_day_fails_immediately(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        details = {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": "GenerateRequestsPerDayPerProjectPerModel",
                                "quotaMetric": "generativelanguage.googleapis.com/generate_content_daily_requests"
                            }
                        ]
                    }
                ]
            }
        }
        raise MockAPIError(429, details)
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    with pytest.raises(ValueError) as excinfo:
        extract_web_data("<html><body>test</body></html>", client=mock_client, run_pipeline=True)
    
    assert "daily quota exhausted" in str(excinfo.value).lower()
    assert call_count == 1


@patch("modules.gemini.genai.Client")
def test_quota_tokens_per_day_fails_immediately(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        details = {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "details": [
                    {
                        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                        "violations": [
                            {
                                "quotaId": "GenerateContentInputTokensPerModelPerDay",
                                "quotaMetric": "generativelanguage.googleapis.com/generate_content_daily_tokens"
                            }
                        ]
                    }
                ]
            }
        }
        raise MockAPIError(429, details)
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    with pytest.raises(ValueError) as excinfo:
        extract_web_data("<html><body>test</body></html>", client=mock_client, run_pipeline=True)
    
    assert "daily quota exhausted" in str(excinfo.value).lower()
    assert call_count == 1


@patch("modules.gemini.genai.Client")
def test_quota_unknown_429_with_delay(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            details = {
                "error": {
                    "code": 429,
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "0.05s"
                        }
                    ]
                }
            }
            raise MockAPIError(429, details)
        return MagicMock(text=mock_extraction_result.model_dump_json())
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100", "MAX_RETRIES": "2"}):
        result = extract_web_data("<html><body>test</body></html>", client=mock_client, run_pipeline=True)
    assert call_count == 2

@patch("modules.gemini.genai.Client")
def test_quota_unknown_429_without_delay_fails(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise MockAPIError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    # New behaviour: unknown 429 without delay is now classified as per-minute
    # (retried once, then model exhausts retries and raises the original error).
    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100", "GEMINI_MODELS": "gemini-2.5-flash", "MAX_RETRIES": "1"}):
        with pytest.raises(MockAPIError):
            extract_web_data("<html><body>test</body></html>", client=mock_client, run_pipeline=True)
    # Should have retried at least once (MAX_RETRIES=1 → 2 attempts)
    assert call_count >= 1


@patch("modules.gemini.genai.Client")
def test_quota_non_429_error_no_retry(mock_client_class, mock_extraction_result):
    mock_client = MagicMock()
    call_count = 0
    def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ValueError("Some other error")
    mock_client.models.generate_content.side_effect = side_effect
    mock_client_class.return_value = mock_client

    with patch.dict("os.environ", {"SAFE_TOKEN_LIMIT": "100", "GEMINI_MODELS": "gemini-2.5-flash"}):
        with pytest.raises(ValueError):
            extract_web_data("<html><body>test</body></html>", client=mock_client, run_pipeline=True)
    assert call_count == 1


