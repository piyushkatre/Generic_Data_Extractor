import pytest
from core.dom_builder import DOMBlockBuilder
from core.prompt_builder import ExtractionPromptBuilder
from core.pipeline import FranchiseExtractionPipeline
from modules.adapter_loader import AdapterLoader, Adapter
from modules.dataset_builder.record_validator import RecordValidator

def test_dom_block_builder():
    html = """
    <html>
      <body>
        <h1>Title here</h1>
        <p>Some description text here.</p>
        <ul>
          <li>Bullet 1</li>
          <li>Bullet 2</li>
        </ul>
        <table>
          <tr><th>Key</th><th>Value</th></tr>
          <tr><td>Investment</td><td>10 Lakhs</td></tr>
        </table>
      </body>
    </html>
    """
    builder = DOMBlockBuilder(html)
    blocks = builder.build_blocks()
    
    assert len(blocks) == 4
    assert blocks[0]["type"] == "heading"
    assert blocks[0]["text"] == "Title here"
    assert blocks[1]["type"] == "paragraph"
    assert blocks[1]["text"] == "Some description text here."
    assert blocks[2]["type"] == "list"
    assert blocks[2]["items"] == ["Bullet 1", "Bullet 2"]
    assert blocks[3]["type"] == "table"
    assert blocks[3]["rows"] == [["Key", "Value"], ["Investment", "10 Lakhs"]]

def test_prompt_builder():
    schema = {
        "extraction_fields": {
            "franchise_name": {"type": "string", "description": "The name of the franchise"},
            "investment_required": {"type": "string", "description": "Minimum investment needed"}
        }
    }
    blocks = [
        {"type": "heading", "level": 1, "text": "Domino's Pizza"},
        {"type": "paragraph", "text": "Requires 50 Lakhs initial capital."}
    ]
    rules = ["Ensure capitalization of brand name."]
    
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="TestSite",
        schema=schema,
        structured_dom=blocks,
        extraction_rules=rules,
        deterministic_fields=["investment_required"]
    )
    
    assert "TestSite" in prompt
    assert "Domino's Pizza" in prompt
    assert "Ensure capitalization" in prompt
    assert "investment_required" in prompt

def test_record_validator_normalization():
    # Test currency normalizations
    assert RecordValidator.normalize_currency("₹25 Lakhs") == "2500000"
    assert RecordValidator.normalize_currency("Rs. 5.5 Lakhs") == "550000"
    assert RecordValidator.normalize_currency("INR 50,000") == "50000"
    assert RecordValidator.normalize_currency("$10,000") == "10000"
    assert RecordValidator.normalize_currency("1.2 Crore") == "12000000"
    
    # Test measurement normalizations
    assert RecordValidator.normalize_measurement("500 Sq Ft") == "500"
    assert RecordValidator.normalize_measurement("1000-2000 sft") == "1000"
    
    # Test percentage normalizations
    assert RecordValidator.normalize_percentage("30%") == "30"
    assert RecordValidator.normalize_percentage("10-20 percent") == "10"
    
    # Test duration normalizations
    assert RecordValidator.normalize_duration("5 Years") == "5"
    assert RecordValidator.normalize_duration("10 yr") == "10"

def test_adapter_registry_priority_and_aliases():
    AdapterLoader.initialize()
    # Let's request domain match for franchisebazar.in (which is an alias of franchisebazar.com)
    adapter = AdapterLoader.load("https://franchisebazar.in/some-franchise")
    assert adapter.name == "FranchiseBazar"
    assert adapter.priority == 10
    
    # Check fallback default adapter
    fallback = AdapterLoader.load("https://unknownsite.com")
    assert fallback.name == "Default"
    assert fallback.priority == 0


def test_prompt_builder_fallback_deterministic():
    schema = {
        "extraction_fields": {
            "established_year": {"type": "string", "description": "Year established"},
            "franchise_since": {"type": "string", "description": "Franchised since year"},
            "number_of_outlets": {"type": "string", "description": "Number of outlets"}
        }
    }
    blocks = [{"type": "heading", "level": 1, "text": "Domino's Pizza"}]
    
    # Simulate deterministic extraction failing completely (deterministic_fields is empty)
    prompt = ExtractionPromptBuilder.build_prompt(
        website_name="TestSite",
        schema=schema,
        structured_dom=blocks,
        deterministic_fields=[]
    )
    
    import re
    solved_match = re.search(r"## 4\. ALREADY EXTRACTED FIELDS.*?\n(?:.*\n)*?\n##", prompt)
    remaining_match = re.search(r"## 5\. REMAINING FIELDS TO EXTRACT.*?\n(?:.*\n)*?\n##", prompt)
    
    solved_section = solved_match.group(0) if solved_match else ""
    remaining_section = remaining_match.group(0) if remaining_match else ""
    
    for field in ["established_year", "franchise_since", "number_of_outlets"]:
        assert field not in solved_section
        assert field in remaining_section

