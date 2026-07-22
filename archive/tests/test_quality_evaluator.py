import os
import pytest
from modules.gemini import ExtractionResult
from modules.evaluation.validators import OfflineValidator
from modules.evaluation.dom_checker import DOMChecker
from modules.evaluation.quality_evaluator import ExtractionQualityEvaluator

def test_offline_validators():
    # Email
    assert not OfflineValidator.validate_email("valid@example.com")
    assert len(OfflineValidator.validate_email("invalid-email")) == 1

    # Phone
    assert not OfflineValidator.validate_phone("+91 98765 43210")
    assert len(OfflineValidator.validate_phone("12")) == 1

    # URL
    assert not OfflineValidator.validate_url("https://example.com/franchise", "website")
    assert len(OfflineValidator.validate_url("not_a_url", "website")) == 1

    # Currency
    assert not OfflineValidator.validate_investment("₹20 Lakhs")
    assert len(OfflineValidator.validate_investment("NoMoneyHere")) == 1

    # ROI
    assert not OfflineValidator.validate_roi("25% return p.a.")
    assert len(OfflineValidator.validate_roi("good profit")) == 1

    # Area
    assert not OfflineValidator.validate_area("500 sq ft")
    assert len(OfflineValidator.validate_area("large room")) == 1

    # Date
    assert not OfflineValidator.validate_date("2024-05-15", "established_year")
    assert not OfflineValidator.validate_date("2024", "franchise_since")
    assert len(OfflineValidator.validate_date("not-a-date", "established_year")) == 1

    # List fields
    assert not OfflineValidator.validate_list_field(["Item A", "Item B"], "products")
    assert len(OfflineValidator.validate_list_field("not-a-list", "products")) == 1


def test_dom_checker_semantic_and_value_checks():
    # Semantic Match (Task 1)
    html = "<html><body><p>We require an investment of Rs. 20 Lakhs and phone is +91-98444-43200.</p></body></html>"
    checker = DOMChecker(html)

    # Rs. 20 Lakhs vs 20 Lakhs
    assert checker.is_value_in_dom("20 Lakhs")
    # Phone number normalization formatting match
    assert checker.is_value_in_dom("9844443200")
    # Royalty check - absent
    assert not checker.is_value_in_dom("5%")

    # Value-aware Likely Missed (Task 3)
    # Phone pattern in DOM
    assert checker.has_actual_value_in_dom("phone")
    # Email pattern - not in DOM
    assert not checker.has_actual_value_in_dom("email")
    # Investment pattern - present
    assert checker.has_actual_value_in_dom("investment_required")


def test_quality_evaluator_scoring_and_benchmarks():
    html = """
    <html>
      <body>
        <h1>BeatBox Gym Franchise</h1>
        <p>Investment required: Rs. 20 Lakhs. Contact email: info@beatbox.com</p>
      </body>
    </html>
    """
    
    result = ExtractionResult(
        franchise_name="BeatBox Gym",
        email="info@beatbox.com",
        investment_required=None, # Missing in JSON but present in DOM -> Likely Missed
        royalty="5%", # Extracted but NOT in DOM -> Possible Hallucination
        phone=None # Missing in JSON, not in DOM -> Missing on Page
    )

    evaluator = ExtractionQualityEvaluator()
    benchmark_file = "benchmarks/test_benchmark_log.csv"
    
    # Remove existing test log if present
    if os.path.exists(benchmark_file):
        os.remove(benchmark_file)

    report = evaluator.evaluate(
        result=result,
        html_content=html,
        execution_time=2.45,
        token_count=1500,
        schema_required=["Franchise Name", "Email"],
        source_url="https://test.com"
    )

    assert isinstance(report, dict)
    assert "coverage_ratio" in report
    assert report["coverage_percentage"] > 0
    assert report["confidence_score"] >= 0 and report["confidence_score"] <= 100

    statuses = report["field_statuses"]
    assert statuses["franchise_name"] == "Extracted Successfully"
    assert statuses["investment_required"] == "Likely Missed"
    assert statuses["phone"] == "Missing on Page"
    assert statuses["royalty"] == "Possible Hallucination"
    assert len(report["hallucinations"]) == 1
    assert report["hallucinations"][0]["field"] == "royalty"

    # Verify benchmark logger created the file and wrote metrics (Task 7)
    evaluator._log_benchmark(
        metrics={
            "timestamp": "2026-07-03 12:00:00",
            "url": "https://test.com",
            "coverage": "2 / 37",
            "dom_match": "75.0%",
            "confidence": "50.0%",
            "hallucinations": 1,
            "critical_fields_missing": "investment_required",
            "execution_time_sec": "2.45",
            "token_count": 1500
        },
        filepath=benchmark_file
    )

    assert os.path.exists(benchmark_file)
    with open(benchmark_file, "r", encoding="utf-8") as f:
        content = f.read()
        assert "https://test.com" in content
        assert "2 / 37" in content
        assert "75.0%" in content
        assert "1500" in content

    # Clean up test benchmark file
    if os.path.exists(benchmark_file):
        os.remove(benchmark_file)

def test_developer_mode_config():
    from modules.config import ExtractorConfig
    from unittest.mock import patch
    
    with patch.dict(os.environ, {"DEVELOPER_MODE": "true"}):
        cfg = ExtractorConfig.load()
        assert cfg.DEVELOPER_MODE is True
        
    with patch.dict(os.environ, {"DEVELOPER_MODE": "false"}):
        cfg = ExtractorConfig.load()
        assert cfg.DEVELOPER_MODE is False
