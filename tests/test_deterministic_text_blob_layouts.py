"""
Tests for the generic "Label: Value" text-blob Summary Layout support in
modules/dataset_builder/deterministic_extractor.py.

Covers the case detect_and_classify_layouts() previously missed entirely: a
container with 0 or 1 direct child elements whose own text contains
multiple colon-delimited "Label: Value" pairs with no per-pair element
boundary between them (e.g. <div class="body-item"><div
class="body-content">Operations Commenced On: 2023 Franchising /
Distribution Commenced On: 2025 Number of Employees: 15</div></div> - three
pairs concatenated as one text node, no <li>/<span>/<dt> per pair).

Detection is purely structural (repeated "Label:" boundaries in the text,
or one pair per real line) - no class names, ids, or site-specific
selectors are referenced anywhere in this feature or these tests.
"""

from bs4 import BeautifulSoup

from modules.dataset_builder.deterministic_extractor import (
    DeterministicExtractor,
    _extract_label_value_pairs_from_text,
)


def _layouts_and_relationships(html):
    soup = BeautifulSoup(html, "html.parser")
    extractor = DeterministicExtractor(schema={}, config={})
    layouts = extractor.detect_and_classify_layouts(soup)
    relationships = []
    for layout in layouts:
        relationships.extend(extractor.extract_relationships_from_layout(layout))
    return layouts, relationships


# ---------------------------------------------------------------------------
# _extract_label_value_pairs_from_text() unit coverage
# ---------------------------------------------------------------------------

def test_helper_no_colon_returns_no_pairs():
    assert _extract_label_value_pairs_from_text("This company has operated since 2023.") == []


def test_helper_single_colon_returns_one_pair():
    pairs = _extract_label_value_pairs_from_text("Our mission: to build better gyms.")
    assert len(pairs) == 1


def test_helper_line_separated_pairs_handles_word_shaped_values():
    """A value that itself looks like a label-shaped word (e.g. a name)
    must not be misread as the start of the next label - this only works
    unambiguously when pairs are line-separated."""
    text = "Name: ABC\nInvestment: Rs. 20 Lakhs\nArea: 3000 sqft"
    pairs = _extract_label_value_pairs_from_text(text)
    assert pairs == [("Name", "ABC"), ("Investment", "Rs. 20 Lakhs"), ("Area", "3000 sqft")]


def test_helper_collapsed_single_line_with_numeric_values():
    text = "Operations Commenced On: 2023 Franchising / Distribution Commenced On: 2025 Number of Employees: 15"
    pairs = _extract_label_value_pairs_from_text(text)
    assert pairs == [
        ("Operations Commenced On", "2023"),
        ("Franchising / Distribution Commenced On", "2025"),
        ("Number of Employees", "15"),
    ]


# ---------------------------------------------------------------------------
# Case 1: one-child container, two "Label: Value" pairs (line-separated)
# ---------------------------------------------------------------------------

def test_case1_one_child_container_two_pairs_extracts_two_relationships():
    html = """
    <div class="wrapper">
      <div class="content">Operations Commenced On: 2023
Employees: 15</div>
    </div>
    """
    layouts, relationships = _layouts_and_relationships(html)

    assert any(l["type"] == "Summary Layout" for l in layouts)
    assert len(relationships) == 2
    keys = {k.strip() for k, v in relationships}
    assert keys == {"Operations Commenced On", "Employees"}


# ---------------------------------------------------------------------------
# Case 2: normal paragraph - must NOT be classified as Summary Layout
# ---------------------------------------------------------------------------

def test_case2_normal_paragraph_not_classified_as_summary_layout():
    html = '<div class="content">This company has operated since 2023.</div>'
    layouts, _ = _layouts_and_relationships(html)
    assert not [l for l in layouts if l["type"] == "Summary Layout"]


# ---------------------------------------------------------------------------
# Case 3: random text containing exactly one colon - must NOT be classified
# ---------------------------------------------------------------------------

def test_case3_single_colon_marketing_text_not_classified():
    html = '<div class="content">Our mission: to build better gyms for everyone.</div>'
    layouts, _ = _layouts_and_relationships(html)
    assert not [l for l in layouts if l["type"] == "Summary Layout"]


# ---------------------------------------------------------------------------
# Case 4: three "Label: Value" pairs inside ONE text node, no line breaks -
# the exact shape from the original investigation (real FranchiseBazar
# HTML, reproduced generically with no site-specific selector).
# ---------------------------------------------------------------------------

def test_case4_three_pairs_in_one_text_node_classified_as_summary_layout():
    html = (
        '<div class="body-item">'
        '<div class="body-content">'
        "Operations Commenced On: 2023 "
        "Franchising / Distribution Commenced On: 2025 "
        "Number of Employees: 15"
        "</div>"
        "</div>"
    )
    layouts, relationships = _layouts_and_relationships(html)

    summary_layouts = [l for l in layouts if l["type"] == "Summary Layout"]
    # Exactly one classification - the innermost element holding the text,
    # not also its 1-child wrapper (no duplicate extraction).
    assert len(summary_layouts) == 1
    assert len(relationships) == 3

    values = {k.strip(): v.strip() for k, v in relationships}
    assert values == {
        "Operations Commenced On": "2023",
        "Franchising / Distribution Commenced On": "2025",
        "Number of Employees": "15",
    }


# ---------------------------------------------------------------------------
# Genericity: unrelated domains (not franchise-shaped) work identically -
# proves nothing here is FranchiseBazar-specific.
# ---------------------------------------------------------------------------

def test_generic_non_franchise_labels_also_detected():
    html = (
        '<div class="card">'
        "<div>Name: ABC\nInvestment: Rs. 20 Lakhs\nArea: 3000 sqft</div>"
        "</div>"
    )
    layouts, relationships = _layouts_and_relationships(html)
    assert any(l["type"] == "Summary Layout" for l in layouts)
    values = {k.strip(): v.strip() for k, v in relationships}
    assert values == {"Name": "ABC", "Investment": "Rs. 20 Lakhs", "Area": "3000 sqft"}


def test_generic_ceo_founded_revenue_labels_also_detected():
    html = (
        "<section>"
        "<div>CEO: John Doe\nFounded: 2015\nRevenue: ₹50 Cr</div>"
        "</section>"
    )
    layouts, relationships = _layouts_and_relationships(html)
    assert any(l["type"] == "Summary Layout" for l in layouts)
    values = {k.strip(): v.strip() for k, v in relationships}
    assert values == {"CEO": "John Doe", "Founded": "2015", "Revenue": "₹50 Cr"}


# ---------------------------------------------------------------------------
# No regression to the pre-existing multi-child Summary Layout path
# ---------------------------------------------------------------------------

def test_existing_multi_child_summary_layout_still_works():
    html = (
        "<div>"
        "<div>Franchise Name: ABC Gym</div>"
        "<div>Established: 2020</div>"
        "<div>Location: Delhi</div>"
        "</div>"
    )
    layouts, relationships = _layouts_and_relationships(html)
    assert any(l["type"] == "Summary Layout" for l in layouts)
    values = {k.strip(): v.strip() for k, v in relationships}
    assert values == {"Franchise Name": "ABC Gym", "Established": "2020", "Location": "Delhi"}
