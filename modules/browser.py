"""
Playwright-based browser rendering module.
Handles loading client-side hydrated dynamic pages, auto-scrolling to trigger lazy loads,
expanding content widgets (read more, show more, accordions), and recovering fully rendered HTML.
"""

import time
import os
import asyncio
from typing import Dict, Any
from playwright.async_api import async_playwright, Page
from utils.logger import get_logger

logger = get_logger(__name__)

async def fetch_webpage(url: str, timeout_ms: int = 30000) -> Dict[str, Any]:
    """
    Launches a headless Chromium browser, navigates to the url, renders JavaScript,
    scrolls to the bottom, expands common accordions/buttons, and captures the fully rendered HTML.

    Args:
        url (str): Target webpage URL.
        timeout_ms (int): Navigation and load timeout in milliseconds.

    Returns:
        Dict[str, Any]: Render results including:
            - url: Original request URL
            - final_url: Page URL after redirects
            - title: Page title
            - html: Rendered HTML content
            - render_time_ms: Total time taken for rendering in milliseconds
    """
    start_time = time.time()
    
    # 1. Resolve domain and load matching adapter configuration
    from modules.adapter_loader import AdapterLoader
    adapter = AdapterLoader.load(url)
    browser_config = adapter.config.get("browser_config", {})
    
    wait_config = browser_config.get("wait_strategy", {})
    wait_until = wait_config.get("wait_until", "domcontentloaded")
    timeout_ms = wait_config.get("timeout_ms", timeout_ms)
    wait_after_load_ms = wait_config.get("wait_after_load_ms", 1000)
    
    scroll_config = browser_config.get("scroll_strategy", {})
    max_scrolls = scroll_config.get("max_scrolls", 15)
    scroll_delay_ms = scroll_config.get("scroll_delay_ms", 1000)
    
    lazy_config = browser_config.get("lazy_loading", {})
    trigger_expanders = lazy_config.get("trigger_expanders", True)
    
    content_container = browser_config.get("content_container")
    selectors_to_ignore = browser_config.get("selectors_to_ignore", [])
    
    # Load configuration from environment variables or fall back to defaults
    headless = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"
    env_timeout = os.getenv("PLAYWRIGHT_TIMEOUT")
    if env_timeout:
        try:
            timeout_ms = int(env_timeout)
        except ValueError:
            logger.warning(f"Invalid PLAYWRIGHT_TIMEOUT value '{env_timeout}'. Falling back to {timeout_ms}ms.")

    logger.info(f"Initiating page render for: {url} (headless={headless}, timeout={timeout_ms}ms)")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream"
            ],
            ignore_default_args=["--enable-automation"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        
        await page.add_init_script("delete navigator.__proto__.webdriver;")
        
        try:
            page.set_default_timeout(timeout_ms)
            content_sources = ["Main Page"]
            
            logger.debug(f"Navigating to {url}...")
            try:
                await page.goto(url, wait_until=wait_until, timeout=timeout_ms)
            except Exception as goto_error:
                logger.warning(f"Navigation timeout/error occurred for {url}. Proceeding: {goto_error}")
            
            # Post-load delay
            if wait_after_load_ms > 0:
                await page.wait_for_timeout(wait_after_load_ms)
            
            # Perform page scrolling
            if max_scrolls > 0:
                logger.info(f"Executing progressive auto-scroll (max scrolls: {max_scrolls}, delay: {scroll_delay_ms}ms)...")
                await _auto_scroll(page, max_scrolls, scroll_delay_ms)
                content_sources.append("Progressive Auto-Scroll")
            
            # Decompose ignored elements from the active browser tab
            for selector in selectors_to_ignore:
                try:
                    await page.evaluate(f"() => {{ document.querySelectorAll('{selector}').forEach(e => e.remove()); }}")
                except Exception:
                    pass
            
            # Expand dynamic content containers
            if trigger_expanders:
                logger.info("Locating and expanding toggle/read-more elements...")
                expanded_any = await _expand_elements(page)
                if expanded_any:
                    content_sources.append("Accordion / Read More Expansion")
            
            # Click and merge tabs
            clickable_tabs_config = adapter.config.get("clickable_tabs", {})
            logger.info("Locating tabs and collecting tab contents...")
            html = await _navigate_and_merge_tabs(page, clickable_tabs_config, content_sources)

            # Log content source trace summary
            logger.info(f"Content Source Trace: {' -> '.join(content_sources)}")

            logger.info("=" * 80)
            logger.info("BROWSER OUTPUT")
            logger.info(f"HTML Length : {len(html)}")
            logger.info(html[:5000])
            logger.info("=" * 80)
            
            # Content container targeting
            if content_container:
                try:
                    container_handle = await page.query_selector(content_container)
                    if container_handle:
                        html = await container_handle.evaluate("node => node.outerHTML")
                except Exception as container_err:
                    logger.debug(f"Content container selection failed: {container_err}")
            
            final_url = page.url
            title = await page.title()
            
            render_time = int((time.time() - start_time) * 1000)
            logger.info(f"Successfully rendered webpage {final_url} in {render_time}ms")
            
            return {
                "url": url,
                "final_url": final_url,
                "title": title,
                "html": html,
                "render_time_ms": render_time,
                "content_sources": content_sources
            }
            
        except Exception as e:
            logger.error(f"Error rendering webpage {url}: {e}", exc_info=True)
            raise e
        finally:
            await context.close()
            await browser.close()

async def _auto_scroll(page: Page, max_scrolls: int = 15, scroll_delay_ms: int = 1000) -> None:
    """
    Scrolls down the page progressively to trigger infinite scroll/lazy loading.
    """
    last_height = await page.evaluate("document.body.scrollHeight")
    scroll_count = 0
    
    while scroll_count < max_scrolls:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        await page.wait_for_timeout(scroll_delay_ms)
        
        new_height = await page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            logger.debug(f"Auto-scroll complete at height {new_height} after {scroll_count} iterations.")
            break
            
        last_height = new_height
        scroll_count += 1
        logger.debug(f"Scroll iteration {scroll_count}: height updated to {new_height}")

async def _expand_elements(page: Page) -> bool:
    """
    Finds and clicks common elements that expand text blocks or accordion structures.

    Args:
        page (Page): The Playwright Page instance.
    """
    expand_keywords = ["show more", "read more", "load more", "view more", "expand"]
    clicked_any = False
    
    try:
        # Scan for tags that are commonly clickable
        candidates = await page.query_selector_all("button, a, span, div[role='button']")
        logger.debug(f"Found {len(candidates)} potential interactive tags for expansion scans.")
        
        for candidate in candidates:
            try:
                # Check inner text safely
                text = (await candidate.inner_text() or "").strip().lower()
                
                if any(keyword in text for keyword in expand_keywords):
                    # Exclude typical link headers or navigation links that load new pages
                    is_link_navigation = await candidate.evaluate(
                        "node => node.tagName === 'A' && node.getAttribute('href') && "
                        "!node.getAttribute('href').startsWith('#') && "
                        "!node.getAttribute('href').startsWith('javascript:')"
                    )
                    if is_link_navigation:
                        continue
                    
                    if await candidate.is_visible():
                        logger.debug(f"Clicking expand target containing: '{text}'")
                        # Click with a minimal timeout so a single slow button won't hang the loop
                        await candidate.click(timeout=1000)
                        clicked_any = True
                        # Small pause to allow dynamic scripts to expand target layout
                        await page.wait_for_timeout(400)
            except Exception as inner_error:
                # Swallowing errors for individual clicks to keep scanning other elements
                logger.debug(f"Interactive element click skipped: {inner_error}")
    except Exception as e:
        logger.warning(f"Error occurred during element expansion check: {e}")
    return clicked_any


async def _navigate_and_merge_tabs(page: Page, config: dict = None, content_sources: list = None) -> str:
    """
    Clicks all interactive tab elements on the page, captures content of each tab,
    and merges the contents into one comprehensive HTML document.
    """
    if config is None:
        config = {}
    if content_sources is None:
        content_sources = []
        
    # Counters for tabs classification
    static_tabs_count = 0
    dynamic_tabs_count = 0
    duplicate_tabs_count = 0
    ignored_tabs_count = 0
        
    # 1. Capture base page content
    base_html = await page.content()
    
    # 2. Identify tab triggers
    tab_selectors = config.get("selectors", [
        'a[data-toggle="tab"]',
        'a[data-toggle="pill"]',
        'a[role="tab"]',
        'button[role="tab"]',
        '.nav-tabs a',
        '.nav-tabs button',
        '.nav-pills a',
        '.tabs a',
        '.tab-link',
        '.tab-btn',
        'li.nav-item a',
        '.brand-profile-tabs a',
        '.franchise-navigation a'
    ])
    
    tab_elements = []
    for selector in tab_selectors:
        try:
            elms = await page.query_selector_all(selector)
            for el in elms:
                if el not in tab_elements:
                    tab_elements.append(el)
        except Exception:
            pass

    allowed_keywords = config.get("allowed_keywords", ["profile", "business summary", "faq", "gallery", "reviews"])
    ignored_keywords = config.get("ignored_keywords", ["email login", "social login", "login", "register", "signin", "signup"])

    # Locate by xpath text search for the specific allowed keywords
    for text in allowed_keywords:
        try:
            locs = page.locator(
                f"xpath=//a[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')] | "
                f"//button[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')] | "
                f"//span[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{text}')]"
            )
            count = await locs.count()
            for i in range(count):
                el = await locs.nth(i).element_handle()
                if el and el not in tab_elements:
                    tab_elements.append(el)
        except Exception:
            pass

    # Filter tab elements to ONLY franchise content tabs, ignoring auth/modals/popups
    filtered_tabs = []
    for el in tab_elements:
        try:
            if not (await el.is_visible() and await el.is_enabled()):
                ignored_tabs_count += 1
                continue

            # Check text
            tab_text_lower = (await el.inner_text() or "").lower().strip()
            if not any(kw in tab_text_lower for kw in allowed_keywords):
                ignored_tabs_count += 1
                continue
            if any(kw in tab_text_lower for kw in ignored_keywords):
                ignored_tabs_count += 1
                continue

            # Check if element resides inside a modal, popup, auth, login, register, or social container
            is_modal_or_auth = await el.evaluate("""(node) => {
                let parent = node.parentElement;
                while (parent && parent.tagName !== "BODY" && parent.tagName !== "HTML") {
                    let id = (parent.id || "").toLowerCase();
                    let cls = (parent.className || "").toLowerCase();
                    if (id.includes("modal") || id.includes("popup") || id.includes("login") || id.includes("auth") || id.includes("social") || id.includes("register")) return true;
                    if (cls.includes("modal") || cls.includes("popup") || cls.includes("login") || cls.includes("auth") || cls.includes("social") || cls.includes("register")) return true;
                    parent = parent.parentElement;
                }
                return false;
            }""")
            
            if is_modal_or_auth:
                ignored_tabs_count += 1
                continue

            filtered_tabs.append(el)
        except Exception:
            pass

    tab_elements = filtered_tabs
            
    tab_htmls = []
    clicked_hrefs = set()
    
    for el in tab_elements:
        tab_name = ""
        click_success = False
        content_loaded = False
        size_before = 0
        size_after = 0
        
        try:
            tab_name = (await el.inner_text() or "").strip()
            if not (await el.is_visible() and await el.is_enabled()):
                ignored_tabs_count += 1
                continue
                
            href = await el.get_attribute("href")
            if href:
                href_clean = href.strip()
                if href_clean.startswith("http") or (href_clean and not href_clean.startswith("#") and "." in href_clean):
                    ignored_tabs_count += 1
                    continue
                if href_clean in clicked_hrefs:
                    duplicate_tabs_count += 1
                    continue
                clicked_hrefs.add(href_clean)
                
            size_before = len(await page.content())
            
            logger.info(f"Clicking tab trigger: '{tab_name}' (href: '{href}')")
            await el.click(timeout=3000)
            click_success = True
            
            await page.wait_for_timeout(800)
            
            tab_html = await page.content()
            size_after = len(tab_html)
            content_loaded = size_after > 0
            
            if size_after > size_before:
                dynamic_tabs_count += 1
                content_sources.append(f"Dynamic Tab [{tab_name}]")
            else:
                static_tabs_count += 1
                logger.warning(f"Warning: clicking tab '{tab_name}' did not increase DOM content size ({size_before} -> {size_after}).")
                
            tab_htmls.append((tab_name, click_success, content_loaded, size_before, size_after, tab_html))
        except Exception as tab_err:
            logger.debug(f"Tab click failed for '{tab_name}': {tab_err}")
            
    # Log consolidated tab exploration metrics
    logger.info(
        f"\n=== Browser Tab Exploration Summary ===\n"
        f"Total Tabs Discovered: {len(tab_elements) + ignored_tabs_count + duplicate_tabs_count}\n"
        f"Static Tabs Explored:  {static_tabs_count}\n"
        f"Dynamic Tabs Explored: {dynamic_tabs_count}\n"
        f"Duplicate Tabs:        {duplicate_tabs_count}\n"
        f"Ignored Tabs:          {ignored_tabs_count}\n"
        f"========================================="
    )

    if not tab_htmls:
        return base_html
        
    from bs4 import BeautifulSoup
    base_soup = BeautifulSoup(base_html, "html.parser")
    
    def is_tab_pane(tag):
        if tag.name != "div":
            return False
        role = tag.get("role")
        classes = tag.get("class", [])
        if role == "tabpanel":
            return True
        if any("tab-pane" in c or "tabpane" in c for c in classes):
            return True
        return False
        
    base_panes = base_soup.find_all(is_tab_pane)
    base_panes_map = {pane.get("id"): pane for pane in base_panes if pane.get("id")}
    
    for t_name, click_success, content_loaded, size_before, size_after, other_html in tab_htmls:
        try:
            other_soup = BeautifulSoup(other_html, "html.parser")
            other_panes = other_soup.find_all(is_tab_pane)
            
            merged_any = False
            for o_pane in other_panes:
                o_id = o_pane.get("id")
                if o_id:
                    if o_id in base_panes_map:
                        b_pane = base_panes_map[o_id]
                        b_text_len = len(b_pane.get_text(strip=True))
                        o_text_len = len(o_pane.get_text(strip=True))
                        if o_text_len > b_text_len:
                            b_pane.clear()
                            for child in list(o_pane.children):
                                b_pane.append(child)
                            merged_any = True
                    else:
                        if base_soup.body:
                            base_soup.body.append(o_pane)
                            base_panes_map[o_id] = o_pane
                            merged_any = True
            
            merge_reason = "Merge successful (new/larger tabpanel elements integrated into base DOM)"
            if not merged_any:
                if size_after <= size_before:
                    merge_reason = "Tab content was already fully present in the static base HTML (pre-loaded statically) or did not load new nodes."
                else:
                    merge_reason = "DOM size increased, but no new/larger specific tabpanels (Bootstrap tab-pane or role=tabpanel) were found to merge."

            logger.info(
                f"\n--- Tab Logging Details ---\n"
                f"Tab Name:            {t_name}\n"
                f"Clicked Successfully: {click_success}\n"
                f"Content Loaded:      {content_loaded}\n"
                f"Content Size Before: {size_before} bytes\n"
                f"Content Size After:  {size_after} bytes\n"
                f"DOM Merged:          {merged_any}\n"
                f"DOM Merge Reason:    {merge_reason}\n"
                f"==========================="
            )
        except Exception as merge_err:
            logger.error(f"Failed to merge tab {t_name}: {merge_err}")
            
    # Force all panes to be visible in final output html
    for pane in base_soup.find_all(is_tab_pane):
        classes = pane.get("class", [])
        if "active" not in classes:
            classes.append("active")
            classes.append("show")
            pane["class"] = classes
        style = pane.get("style", "")
        if "display: none" in style or "display:none" in style:
            pane["style"] = style.replace("display: none", "display: block").replace("display:none", "display:block")
            
    return str(base_soup)

