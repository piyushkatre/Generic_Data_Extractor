import pytest
from modules.gemini import CanonicalFranchiseRecord, KeyValueItem
from modules.dataset_builder.deterministic_extractor import DeterministicExtractor
from modules.gemini import extract_web_data

def test_deterministic_extractor_basic():
    html = """
    <html>
      <body>
        <h1>Cult Fit Franchise Opportunity</h1>
        <table>
          <tr>
            <td>Investment:</td>
            <td>Rs. 30 Lakhs - 50 Lakhs</td>
          </tr>
          <tr>
            <td>Franchise Fee:</td>
            <td>Rs. 5 Lakhs</td>
          </tr>
          <tr>
            <td>Franchising Commenced:</td>
            <td>2018</td>
          </tr>
        </table>
        <ul>
          <li><strong>Expected Working Hours:</strong> 8 Hours</li>
          <li><strong>Preferred Expansion Locations:</strong> South India</li>
        </ul>
        <a href="https://facebook.com/cultfit">Facebook Link</a>
        <a href="mailto:contact@cultfit.com">Email Link</a>
        <img src="https://cultfit.com/logo.png" class="brand-logo" />
      </body>
    </html>
    """
    extractor = DeterministicExtractor()
    res = extractor.extract(html)

    # Brand/title cleanup regex (stripping "- Franchise Opportunity" suffixes)
    # was removed as franchise-specific text cleanup that doesn't belong in a
    # generic engine; brand now falls back to the raw franchise_name value.
    assert res["franchise_name"] == "Cult Fit Franchise Opportunity"
    assert res["brand"] == "Cult Fit Franchise Opportunity"
    assert res["investment_required"] == "Rs. 30 Lakhs - 50 Lakhs"
    assert res["franchise_fee"] == "Rs. 5 Lakhs"
    assert res["franchise_since"] == "2018"
    assert res["franchise_start_year"] == "2018"
    assert res["expected_hours"] == "8 Hours"
    assert res["preferred_locations"] == "South India"
    assert res["facebook"] == "https://facebook.com/cultfit"
    assert res["email"] == "contact@cultfit.com"
    assert "logo.png" in res["logo"]


def test_merge_priority_order():
    # DOM extracted values
    dom_extracted = {
        "franchise_name": "Pizza Point (DOM)",
        "phone": "+91-99999-99999"
    }

    # Gemini extracted values (mock result)
    gemini_res = CanonicalFranchiseRecord(
        franchise_name="Pizza Point (Gemini)",
        phone="+91-11111-11111",
        email="info@pizzapoint.com"
    )

    # Replicate pipeline merge step
    merged_data = {}
    fields_from_dom = []
    fields_from_gemini = []

    gemini_dict = gemini_res.model_dump()
    for field in CanonicalFranchiseRecord.model_fields.keys():
        dom_val = dom_extracted.get(field)
        gem_val = gemini_dict.get(field)

        is_dom_populated = dom_val not in (None, "", [], {})
        is_gem_populated = gem_val not in (None, "", [], {})

        if is_dom_populated:
            merged_data[field] = dom_val
            if field not in ("entities", "page_title", "page_summary", "metadata"):
                fields_from_dom.append(field)
        elif is_gem_populated:
            merged_data[field] = gem_val
            if field not in ("entities", "page_title", "page_summary", "metadata"):
                fields_from_gemini.append(field)
        else:
            if field in ("products", "services", "images", "brochures", "documents", "faq", "additional_information", "metadata"):
                merged_data[field] = []
            else:
                merged_data[field] = None

    merged_data["metadata"] = [
        KeyValueItem(key="fields_from_dom", value=", ".join(fields_from_dom)),
        KeyValueItem(key="fields_from_gemini", value=", ".join(fields_from_gemini))
    ]
    
    final_record = CanonicalFranchiseRecord(**merged_data)

    # DOM should override Gemini
    assert final_record.franchise_name == "Pizza Point (DOM)"
    assert final_record.phone == "+91-99999-99999"
    
    # Gemini should supply fields absent in DOM
    assert final_record.email == "info@pizzapoint.com"
    
    # Metadata should track origins correctly
    fields_dom_str = next(item.value for item in final_record.metadata if item.key == "fields_from_dom")
    fields_gemini_str = next(item.value for item in final_record.metadata if item.key == "fields_from_gemini")
    assert "franchise_name" in fields_dom_str
    assert "email" in fields_gemini_str

def test_deterministic_extractor_qa_layout_and_exclusion():
    html = """
    <html>
      <body>
        <dl>
          <dt>Do you have a Franchise Agreement?</dt>
          <dd>Yes</dd>
          <dt>Term of Agreement?</dt>
          <dd>5 Years</dd>
          <dt>Where is Initial Training conducted?</dt>
          <dd>At Head Office</dd>
        </dl>
      </body>
    </html>
    """
    extractor = DeterministicExtractor(schema={
        "extraction_fields": {
            "agreement_duration": {"type": "string", "description": "Term of Agreement"},
            "training": {"type": "string", "description": "Training details"}
        }
    })
    res = extractor.extract(html)

    # Do you have a Franchise Agreement? is a yes/no question, should NOT match agreement_duration
    # Term of Agreement? should match agreement_duration
    assert res.get("agreement_duration") == "5 Years"


# ── Fix 1: Statistic Layout key/value ordering ────────────────────────────────

def test_statistic_layout_hero_card_key_value_order():
    """
    Statistic Layout must produce (label, value) — NOT (value, label).

    Before the fix, the label 'Franchise Outlets' triggered the 'outlets'
    indicator and the relationship was stored as ("80 - 160", "Franchise Outlets"),
    preventing concept matching.  After the fix, only genuine numeric/currency
    units are used as value indicators, so labels are never swapped with values.
    """
    html = """
    <html><body>
      <div>
        <div>Space Req.</div>
        <div>3000 - 5000 Sq.ft</div>
      </div>
      <div>
        <div>Investment Range</div>
        <div>Rs. 15 Lakhs - 20 Lakhs</div>
      </div>
      <div>
        <div>Franchise Outlets</div>
        <div>80 - 160</div>
      </div>
    </body></html>
    """
    extractor = DeterministicExtractor()
    res = extractor.extract(html)

    # area_required picks up the space card
    assert res.get("area_required") == "3000 - 5000 Sq.ft"
    # investment_required picks up the investment card
    assert res.get("investment_required") == "Rs. 15 Lakhs - 20 Lakhs"
    # number_of_outlets picks up the outlet card — key/value must NOT be swapped
    assert res.get("number_of_outlets") == "80 - 160"


# ── Fix 3: established_year alias expansion ───────────────────────────────────

def test_established_year_from_operations_commenced_on_label():
    """
    'Operations Commenced On' (FranchiseBazar body-box pattern) must resolve
    to established_year after alias expansion.

    The container needs 3+ colon-containing children to trigger Summary Layout,
    which mirrors the real div.body-content structure on FranchiseBazar pages.
    """
    html = """
    <html><body>
      <div>
        <span>Operations Commenced On: 2016</span>
        <span>Franchising / Distribution Commenced On: 2022</span>
        <span>Number of Employees: 15</span>
      </div>
    </body></html>
    """
    extractor = DeterministicExtractor()
    res = extractor.extract(html)
    assert res.get("established_year") == "2016"


# ── Modified Fix 2: franchise_start_year alias → bridge → franchise_since ─────

def test_franchise_since_from_distribution_commenced_label():
    """
    'Franchising / Distribution Commenced On' (FranchiseBazar body-box pattern)
    must resolve to franchise_start_year via alias expansion, then be bridged
    to franchise_since by the existing compatibility sync.  Both fields must
    be populated with the same value.

    The container needs 3+ colon-containing children to trigger Summary Layout,
    which mirrors the real div.body-content structure on FranchiseBazar pages.
    """
    html = """
    <html><body>
      <div>
        <span>Operations Commenced On: 2016</span>
        <span>Franchising / Distribution Commenced On: 2022</span>
        <span>Number of Employees: 15</span>
      </div>
    </body></html>
    """
    extractor = DeterministicExtractor()
    res = extractor.extract(html)
    # franchise_start_year populated directly from registry alias
    assert res.get("franchise_start_year") == "2022"
    # franchise_since populated via the backward-compat bridge
    assert res.get("franchise_since") == "2022"

