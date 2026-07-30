"""
Tests for the Playwright navigation-failure detection added to
modules/browser.py: a page.goto() failure (raised exception, or a settled
final URL on Chromium's internal chrome-error:// interstitial) must be
retried a bounded number of times and, if navigation never reaches a real
page, must raise BrowserNavigationError instead of silently continuing
with an empty/garbage document. Benign goto() timeouts that still land on
a real page must keep the pre-existing lenient behavior (proceed with
whatever rendered).

These tests mock Playwright entirely (no real browser/network) and patch
out the post-navigation stages (_auto_scroll/_expand_elements/
_navigate_and_merge_tabs) so only the navigation logic itself is exercised.
"""

import os
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from modules.browser import fetch_webpage, BrowserNavigationError, _is_browser_error_page

TEST_URL = "https://example.com/some-page"


# ---------------------------------------------------------------------------
# Pure function: _is_browser_error_page
# ---------------------------------------------------------------------------

def test_is_browser_error_page_true_for_chrome_error_scheme():
    assert _is_browser_error_page("chrome-error://chromewebdata/") is True


def test_is_browser_error_page_false_for_real_urls():
    assert _is_browser_error_page("https://example.com/some-page") is False
    assert _is_browser_error_page("about:blank") is False
    assert _is_browser_error_page("") is False


# ---------------------------------------------------------------------------
# Mock scaffolding for fetch_webpage()
# ---------------------------------------------------------------------------

class FakePage:
    """Minimal stand-in for a Playwright Page, covering only what
    fetch_webpage's navigation block touches directly."""

    def __init__(self, goto_outcomes):
        # goto_outcomes: list of dicts, one per expected goto() call:
        #   {"raise": Exception or None, "url_after": str, "status": int or None}
        self.url = "about:blank"
        self._goto_outcomes = list(goto_outcomes)
        self.goto_call_args = []
        self.wait_for_timeout_calls = []

    def set_default_timeout(self, ms):
        pass

    async def add_init_script(self, script):
        pass

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_call_args.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        outcome = self._goto_outcomes.pop(0)
        self.url = outcome["url_after"]
        if outcome.get("raise") is not None:
            raise outcome["raise"]
        response = MagicMock()
        response.status = outcome.get("status")
        return response

    async def wait_for_timeout(self, ms):
        self.wait_for_timeout_calls.append(ms)

    async def title(self):
        return "Test Page"

    async def query_selector(self, selector):
        return None


def _install_playwright_mock(monkeypatch, fake_page):
    fake_browser = MagicMock()
    fake_browser.close = AsyncMock()

    fake_context = MagicMock()
    fake_context.new_page = AsyncMock(return_value=fake_page)
    fake_context.close = AsyncMock()
    fake_browser.new_context = AsyncMock(return_value=fake_context)

    fake_p = MagicMock()
    fake_p.chromium.launch = AsyncMock(return_value=fake_browser)

    fake_pw_cm = MagicMock()
    fake_pw_cm.__aenter__ = AsyncMock(return_value=fake_p)
    fake_pw_cm.__aexit__ = AsyncMock(return_value=False)

    monkeypatch.setattr("modules.browser.async_playwright", lambda: fake_pw_cm)
    return fake_page


@pytest.fixture(autouse=True)
def _stub_post_navigation_stages(monkeypatch):
    """Every test in this file only cares about navigation - stub out
    scrolling/expansion/tab-merging so a successful navigation doesn't need
    a fully-featured fake DOM."""
    monkeypatch.setattr("modules.browser._auto_scroll", AsyncMock())
    monkeypatch.setattr("modules.browser._expand_elements", AsyncMock(return_value=False))
    monkeypatch.setattr("modules.browser._navigate_and_merge_tabs", AsyncMock(return_value="<html><body>ok</body></html>"))


# ---------------------------------------------------------------------------
# Navigation succeeds immediately - no retry needed.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_immediate_success_no_retry(monkeypatch):
    fake_page = FakePage([
        {"raise": None, "url_after": TEST_URL, "status": 200},
    ])
    _install_playwright_mock(monkeypatch, fake_page)

    result = await fetch_webpage(TEST_URL)

    assert result["html"] == "<html><body>ok</body></html>"
    assert len(fake_page.goto_call_args) == 1


# ---------------------------------------------------------------------------
# Persistent failure (every attempt raises AND lands on chrome-error://):
# must exhaust retries then raise BrowserNavigationError - this is the
# AmbitionBox scenario.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_persistent_error_page_raises_after_exhausting_retries(monkeypatch):
    import httpx  # only for a realistic exception message; not httpx-specific logic under test
    nav_error = Exception("Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at " + TEST_URL)

    fake_page = FakePage([
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
    ])
    _install_playwright_mock(monkeypatch, fake_page)

    with patch.dict(os.environ, {"PLAYWRIGHT_NAV_RETRIES": "1", "PLAYWRIGHT_NAV_RETRY_DELAY_MS": "0"}):
        with pytest.raises(BrowserNavigationError) as exc_info:
            await fetch_webpage(TEST_URL)

    assert "ERR_HTTP2_PROTOCOL_ERROR" in str(exc_info.value)
    assert len(fake_page.goto_call_args) == 2  # nav_retries=1 -> 2 total attempts


@pytest.mark.asyncio
async def test_retry_count_is_configurable_via_env(monkeypatch):
    nav_error = Exception("net::ERR_CONNECTION_RESET")
    fake_page = FakePage([
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
    ])
    _install_playwright_mock(monkeypatch, fake_page)

    with patch.dict(os.environ, {"PLAYWRIGHT_NAV_RETRIES": "3", "PLAYWRIGHT_NAV_RETRY_DELAY_MS": "0"}):
        with pytest.raises(BrowserNavigationError):
            await fetch_webpage(TEST_URL)

    assert len(fake_page.goto_call_args) == 4  # nav_retries=3 -> 4 total attempts


# ---------------------------------------------------------------------------
# Transient failure that recovers on retry: first attempt lands on
# chrome-error://, second attempt succeeds -> must proceed normally, no
# exception.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recovers_when_a_later_retry_succeeds(monkeypatch):
    nav_error = Exception("net::ERR_HTTP2_PROTOCOL_ERROR")
    fake_page = FakePage([
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
        {"raise": None, "url_after": TEST_URL, "status": 200},
    ])
    _install_playwright_mock(monkeypatch, fake_page)

    with patch.dict(os.environ, {"PLAYWRIGHT_NAV_RETRIES": "1", "PLAYWRIGHT_NAV_RETRY_DELAY_MS": "0"}):
        result = await fetch_webpage(TEST_URL)

    assert result["html"] == "<html><body>ok</body></html>"
    assert len(fake_page.goto_call_args) == 2


# ---------------------------------------------------------------------------
# Benign goto() timeout that does NOT land on chrome-error:// (e.g. DOM
# loaded but a slow subresource kept wait_until from firing in time) - must
# preserve the pre-existing lenient behavior: proceed with whatever
# rendered, no retry, no exception.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_benign_timeout_on_real_page_proceeds_without_retry(monkeypatch):
    timeout_error = Exception("Page.goto: Timeout 20000ms exceeded.")
    fake_page = FakePage([
        {"raise": timeout_error, "url_after": TEST_URL, "status": None},
    ])
    _install_playwright_mock(monkeypatch, fake_page)

    result = await fetch_webpage(TEST_URL)

    assert result["html"] == "<html><body>ok</body></html>"
    # Must NOT have retried - the browser landed on a real page, so this is
    # treated as success-with-a-warning, not a navigation failure.
    assert len(fake_page.goto_call_args) == 1


# ---------------------------------------------------------------------------
# The raised exception carries the diagnostic info promised by the
# improved logging requirements (requested URL / final URL / reason).
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_exception_message_contains_diagnostic_context(monkeypatch):
    nav_error = Exception("net::ERR_HTTP2_PROTOCOL_ERROR")
    fake_page = FakePage([
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
        {"raise": nav_error, "url_after": "chrome-error://chromewebdata/", "status": None},
    ])
    _install_playwright_mock(monkeypatch, fake_page)

    with patch.dict(os.environ, {"PLAYWRIGHT_NAV_RETRIES": "1", "PLAYWRIGHT_NAV_RETRY_DELAY_MS": "0"}):
        with pytest.raises(BrowserNavigationError) as exc_info:
            await fetch_webpage(TEST_URL)

    message = str(exc_info.value)
    assert TEST_URL in message
    assert "2 attempt" in message
