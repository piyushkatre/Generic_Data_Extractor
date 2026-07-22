"""
test_relevant_dom.py
====================
Unit tests for the Domain-Aware Relevant DOM Builder.

All tests are self-contained and require no network access.
HTML fixtures are minimal and purpose-built to trigger specific code paths.
"""

import pytest
from bs4 import BeautifulSoup

from modules.domain_profiles.base import DomainProfile
from modules.domain_profiles.loader import DomainProfileLoader
from modules.adapter_loader import AdapterLoader

def DefaultProfile():
    return AdapterLoader.load("https://unknown.com").get_profile()

def FranchiseBazarProfile():
    return AdapterLoader.load("https://franchisebazar.com").get_profile()

from modules.relevant_dom.builder import RelevantDOMBuilder
from modules.preprocessor import estimate_tokens


# ── Test helpers ───────────────────────────────────────────────────────────────

def _wrap(body_html: str) -> str:
    """Wraps a body HTML fragment in a full document."""
    return f"<html><body>{body_html}</body></html>"


def _text(html: str) -> str:
    """Extracts visible lowercase text from an HTML string."""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True).lower()


def _build(html: str, profile=None) -> str:
    """Runs RelevantDOMBuilder with the given (or default FranchiseBazar) profile."""
    if profile is None:
        profile = FranchiseBazarProfile()
    return RelevantDOMBuilder(profile).build(html)


# ── DomainProfileLoader ────────────────────────────────────────────────────────

class TestDomainProfileLoader:

    def test_franchisebazar_exact_match(self):
        """Direct franchisebazar.com URL (no www.) loads FranchiseBazarProfile."""
        profile = DomainProfileLoader.load("https://franchisebazar.com/franchise/cult-fit")
        assert profile.name == "FranchiseBazar"
        assert profile.domain == "franchisebazar.com"

    def test_franchisebazar_www_subdomain(self):
        """www.franchisebazar.com should also match FranchiseBazarProfile."""
        profile = DomainProfileLoader.load(
            "https://www.franchisebazar.com/franchise-opportunity/cult"
        )
        assert profile.name == "FranchiseBazar"

    def test_franchisebazar_blog_subdomain(self):
        """Any subdomain of franchisebazar.com should match."""
        profile = DomainProfileLoader.load("https://blog.franchisebazar.com/article/123")
        assert profile.name == "FranchiseBazar"

    def test_unknown_domain_falls_back_to_default(self):
        """An unregistered domain returns the Default profile."""
        profile = DomainProfileLoader.load("https://someunknown.example.com/page")
        assert profile.name == "Default"

    def test_register_custom_profile(self):
        """DomainProfileLoader.register() makes a new domain resolvable."""
        custom = DomainProfile(domain="custom.io", name="Custom")
        DomainProfileLoader.register("custom.io", custom)
        loaded = DomainProfileLoader.load("https://www.custom.io/page")
        assert loaded.name == "Custom"
        # Cleanup — remove the custom entry to avoid polluting other tests
        DomainProfileLoader._REGISTRY.pop("custom.io", None)

    def test_domain_extraction_strips_port(self):
        """Port numbers are stripped from the hostname."""
        profile = DomainProfileLoader.load("http://franchisebazar.com:8080/page")
        assert profile.name == "FranchiseBazar"

    def test_url_without_scheme(self):
        """URLs without a scheme are handled gracefully."""
        profile = DomainProfileLoader.load("franchisebazar.com/franchise/test")
        assert profile.name == "FranchiseBazar"


# ── Phase A: Hard removal ──────────────────────────────────────────────────────

class TestPhaseAHardRemoval:

    def test_nav_is_removed(self):
        """<nav> elements are removed unconditionally."""
        html = _wrap(
            '<nav id="main-nav"><a href="/">Home</a><a href="/about">About</a></nav>'
            '<div><h2>Investment Details</h2><p>₹20 Lakhs total investment.</p></div>'
        )
        result = _build(html)
        assert "home" not in _text(result)
        assert "investment details" in _text(result)

    def test_footer_is_removed(self):
        """<footer> elements are removed unconditionally."""
        html = _wrap(
            '<div><h2>Franchise Fee</h2><p>₹5 Lakhs one-time fee.</p></div>'
            '<footer><p>© 2024 FranchiseBazar. All rights reserved.</p></footer>'
        )
        result = _build(html)
        assert "all rights reserved" not in _text(result)
        assert "franchise fee" in _text(result)

    def test_aside_is_removed(self):
        """<aside> elements are removed unconditionally."""
        html = _wrap(
            '<main><h2>About the Brand</h2><p>Great franchise opportunity.</p></main>'
            '<aside><h3>Popular Searches</h3><ul><li>Food franchise</li></ul></aside>'
        )
        result = _build(html)
        assert "popular searches" not in _text(result)
        assert "about the brand" in _text(result)

    def test_hidden_elements_removed(self):
        """Elements with display:none inline style are removed."""
        html = _wrap(
            '<div style="display:none"><p>Hidden tracking pixel content</p></div>'
            '<div><h2>Contact Us</h2><p>Phone: +91 98765 43210</p></div>'
        )
        result = _build(html)
        assert "hidden tracking" not in _text(result)
        assert "contact us" in _text(result)


# ── Phase B+C: Section scoring ─────────────────────────────────────────────────

class TestPhaseSectionScoring:

    def test_keep_investment_section(self):
        """Sections with franchise investment headings must be preserved."""
        html = _wrap(
            '<div class="content">'
            '  <div><h2>Investment Details</h2>'
            '    <p>Total investment: ₹20 Lakhs. Franchise fee: ₹5 Lakhs. Royalty: 5%.</p>'
            '  </div>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "investment details" in t
        assert "20 lakhs" in t

    def test_remove_related_franchise_section(self):
        """Sections with 'Related Franchise' headings must be removed."""
        html = _wrap(
            '<div>'
            '  <div class="franchise-detail">'
            '    <h2>About the Brand</h2>'
            '    <p>BeatBox Gym is a premium fitness franchise.</p>'
            '  </div>'
            '  <div class="related-list">'
            '    <h2>Related Franchise</h2>'
            '    <ul><li>Cult Fit</li><li>Anytime Fitness</li></ul>'
            '  </div>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "about the brand" in t
        assert "beatbox gym" in t
        assert "related franchise" not in t

    def test_remove_sidebar_by_class(self):
        """Sections with class 'sidebar' are removed regardless of content."""
        html = _wrap(
            '<div class="main-content">'
            '  <div><h2>Franchise Fee</h2><p>₹5 Lakhs one-time franchise fee.</p></div>'
            '</div>'
            '<div class="sidebar">'
            '  <h3>Other Franchises</h3>'
            '  <p>Check out these other opportunities.</p>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "franchise fee" in t
        assert "other franchises" not in t

    def test_remove_newsletter_section(self):
        """Newsletter / subscribe sections must be removed."""
        html = _wrap(
            '<div><h2>Investment</h2><p>₹15 Lakhs required.</p></div>'
            '<div class="newsletter">'
            '  <h3>Subscribe to Newsletter</h3>'
            '  <p>Get updates on new franchise opportunities.</p>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "investment" in t
        assert "subscribe to newsletter" not in t

    def test_nested_bad_section_removed_from_good_parent(self):
        """
        A bad sub-section nested inside a good parent container is removed
        while the good parent is preserved.
        """
        html = _wrap(
            '<div class="page-wrapper">'           # generic wrapper → score ≈ 0, recurse
            '  <div class="franchise-detail">'     # class keep → score +5
            '    <h2>Area Required</h2>'            # heading keep → score +10
            '    <p>500-700 sq ft required.</p>'
            '  </div>'
            '  <div class="related">'              # class remove → score -6.5
            '    <h2>Recommended Franchise</h2>'   # heading remove → score -9
            '    <ul><li>Gym X</li></ul>'
            '  </div>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "area required" in t
        assert "recommended franchise" not in t

    def test_contact_section_preserved(self):
        """
        Contact blocks with phone/email survive even if they have no
        explicit keep-heading signal (contact_score compensates).
        """
        html = _wrap(
            '<div class="main">'
            '  <div><h2>About the Franchise</h2><p>We offer great support.</p></div>'
            '  <div class="contact-block">'
            '    <p>Phone: +91 98765 43210</p>'
            '    <p>Email: info@beatboxgym.com</p>'
            '  </div>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "+91" in t or "98765" in t
        assert "info@beatboxgym.com" in t


# ── Table handling ─────────────────────────────────────────────────────────────

class TestTableHandling:

    def test_business_table_preserved(self):
        """Tables with <th> header rows are always preserved."""
        html = _wrap(
            '<div>'
            '  <table>'
            '    <tr><th>Parameter</th><th>Value</th></tr>'
            '    <tr><td>Investment</td><td>₹20 Lakhs</td></tr>'
            '    <tr><td>Royalty</td><td>5%</td></tr>'
            '    <tr><td>Payback</td><td>18 months</td></tr>'
            '  </table>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "investment" in t
        assert "royalty" in t
        assert "payback" in t
        assert "<table" in result.lower()


# ── Token reduction ────────────────────────────────────────────────────────────

class TestTokenReduction:

    def test_significant_token_reduction(self):
        """Filtered HTML must have fewer tokens than the original noisy page."""
        junk_sidebar = (
            '<div class="sidebar">'
            '  <h3>Related Franchise</h3>'
            '  <p>' + ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 30) + '</p>'
            '</div>'
        ) * 8  # 8 copies of junk sidebar

        useful = (
            '<div class="franchise-detail">'
            '  <h2>Investment Details</h2>'
            '  <p>Total investment: ₹20 Lakhs. Franchise fee: ₹5 Lakhs. Royalty: 5%.</p>'
            '</div>'
            '<div class="contact-info">'
            '  <h2>Contact</h2>'
            '  <p>Phone: +91 98765 43210</p>'
            '  <p>Email: info@brand.com</p>'
            '</div>'
        )

        html = _wrap(
            '<nav>Main Navigation</nav>'
            + junk_sidebar
            + useful
            + '<footer>Footer Content</footer>'
        )

        original_tokens = estimate_tokens(html)
        result = _build(html)
        filtered_tokens = estimate_tokens(result)

        # Expect at least 30% token reduction on this noisy page
        assert filtered_tokens < original_tokens * 0.7, (
            f"Expected >30% reduction, got filtered={filtered_tokens} "
            f"vs original={original_tokens}"
        )
        # Useful content must survive
        assert "investment details" in _text(result)
        assert "98765" in _text(result)

    def test_already_clean_page_unchanged(self):
        """A page with no noise should not lose any visible content."""
        html = _wrap(
            '<div class="franchise-detail">'
            '  <h2>Franchise Overview</h2>'
            '  <p>Gym franchise with 500 outlets across India.</p>'
            '  <h2>Investment Required</h2>'
            '  <p>₹20 Lakhs total investment.</p>'
            '</div>'
        )
        result = _build(html)
        t = _text(result)
        assert "franchise overview" in t
        assert "investment required" in t
        assert "500 outlets" in t


# ── HTML validity ──────────────────────────────────────────────────────────────

class TestHtmlValidity:

    def test_output_is_parseable(self):
        """Filtered HTML must be parseable by BeautifulSoup without errors."""
        html = _wrap(
            '<nav>Nav</nav>'
            '<div class="content"><h2>About</h2><p>Franchise info.</p></div>'
            '<div class="sidebar"><h3>Related</h3><p>Other stuff.</p></div>'
            '<footer>Footer</footer>'
        )
        result = _build(html)
        soup = BeautifulSoup(result, "html.parser")
        assert soup is not None
        assert len(soup.find_all(True)) > 0

    def test_empty_string_input(self):
        """Empty input must return an empty string without raising."""
        result = _build("", profile=DefaultProfile())
        assert result == ""


# ── Phase E: Empty element cleanup ────────────────────────────────────────────

class TestEmptyElementCleanup:

    def test_empty_divs_removed_after_filtering(self):
        """Empty <div> tags left after filtering are removed in Phase E."""
        html = _wrap(
            '<div class="wrapper">'
            '  <div class="sidebar"></div>'   # empty from the start
            '  <div>'
            '    <h2>Contact</h2>'
            '    <p>Email: info@brand.com</p>'
            '  </div>'
            '</div>'
        )
        result = _build(html)
        soup = BeautifulSoup(result, "html.parser")
        empty_divs = [d for d in soup.find_all("div") if not d.get_text(strip=True)]
        assert len(empty_divs) == 0


# ── DefaultProfile ─────────────────────────────────────────────────────────────

class TestDefaultProfile:

    def test_default_profile_keeps_main_content(self):
        """DefaultProfile preserves <main> and <article> content."""
        html = _wrap(
            '<nav><a>Home</a><a>About</a></nav>'
            '<main>'
            '  <article>'
            '    <h1>Company Overview</h1>'
            '    <p>We provide consulting services across India.</p>'
            '  </article>'
            '</main>'
            '<footer><p>© 2024 Corp. All rights reserved.</p></footer>'
        )
        result = _build(html, profile=DefaultProfile())
        t = _text(result)
        assert "company overview" in t
        assert "consulting services" in t
        assert "all rights reserved" not in t

    def test_default_profile_removes_ads(self):
        """DefaultProfile removes sections with class 'advertisement'."""
        html = _wrap(
            '<div class="content"><h2>Services</h2><p>We offer IT solutions.</p></div>'
            '<div class="advertisement"><p>Sponsored ad content here.</p></div>'
        )
        result = _build(html, profile=DefaultProfile())
        t = _text(result)
        assert "services" in t
        assert "sponsored ad content" not in t
