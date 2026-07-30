"""
Tests for ExtractionJob.output_format - the UI's Output Format selection
(app/ui/job_runner.py), stored on the job itself rather than read from the
OUTPUT_FORMAT env var (see core/pipeline.py's Dataset Generation stage).
"""

from config.website_config import WebsiteConfig
from config.extraction_schema import ExtractionSchema
from config.extraction_job import ExtractionJob


def _wc():
    return WebsiteConfig(name="Generic Site")


def _es():
    return ExtractionSchema.from_dict({"name": "Generic", "fields": []})


def test_default_output_format_is_excel_for_backward_compatibility():
    job = ExtractionJob(name="Job", urls=["https://a.com"], website_config=_wc(), extraction_schema=_es())
    assert job.output_format == "excel"


def test_output_format_is_normalized_case_and_whitespace():
    job = ExtractionJob(
        name="Job", urls=["https://a.com"], website_config=_wc(), extraction_schema=_es(),
        output_format=" CSV ",
    )
    assert job.output_format == "csv"


def test_to_dict_from_dict_roundtrip_preserves_output_format():
    job = ExtractionJob(
        name="Job", urls=["https://a.com"], website_config=_wc(), extraction_schema=_es(),
        output_format="csv",
    )
    restored = ExtractionJob.from_dict(job.to_dict())
    assert restored.output_format == "csv"


def test_from_dict_defaults_to_excel_when_output_format_key_missing():
    """A job record saved before this field existed (or any older caller's
    dict) must still load, defaulting to Excel."""
    job = ExtractionJob(name="Job", urls=["https://a.com"], website_config=_wc(), extraction_schema=_es())
    data = job.to_dict()
    del data["output_format"]

    restored = ExtractionJob.from_dict(data)
    assert restored.output_format == "excel"
