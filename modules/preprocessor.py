"""
HTML preprocessor module.
Removes non-content tags, compresses structural layouts, and extracts core metadata.
"""

from bs4 import BeautifulSoup, Comment
from typing import Optional, Any, Set
import re
from utils.logger import get_logger

logger = get_logger(__name__)

def clean_html(raw_html: str, adapter: Optional[Any] = None) -> str:
    """
    Cleans raw HTML by removing scripts, style blocks, inline formats, SVGs, etc.,
    reducing token count and focusing purely on structure and content.
    """
    if not raw_html:
        return ""

    logger.info("=" * 80)
    logger.info("RAW HTML BEFORE CLEANING")
    logger.info(len(raw_html))
    logger.info(raw_html[:1000])
    logger.info("=" * 80)   
        
    soup = BeautifulSoup(raw_html, "lxml")
    
    # Load configuration from adapter if available
    dom_clean_config = {}
    if adapter and hasattr(adapter, "config"):
        dom_clean_config = adapter.config.get("dom_clean_config", {})

    # 1. Build dynamic preservation labels
    schema_labels = _preserve_business_layouts(soup, adapter)

    # 2. Decompose technical tags and strip comments
    removed_nodes_count, preserved_important_nodes_count = _remove_noise(soup, dom_clean_config, schema_labels)

    # 3. Handle images, links, allowed tags, and attributes
    _normalize_html(soup, dom_clean_config)

    # Create cleaned HTML first
    cleaned_html = " ".join(str(soup).split())

    # DOM snapshot logs
    original_size = len(raw_html)
    original_tags = len(BeautifulSoup(raw_html, "lxml").find_all(True))
    cleaned_size = len(cleaned_html)
    cleaned_tags = len(soup.find_all(True))

    logger.debug(
        f"\n=== Preprocessor DOM Clean Stats ===\n"
        f"Original DOM: {original_size} chars, {original_tags} tags\n"
        f"Cleaned DOM:  {cleaned_size} chars, {cleaned_tags} tags\n"
        f"Removed Nodes Count: {removed_nodes_count}\n"
        f"Preserved Nodes Count: {preserved_important_nodes_count}\n"
        f"====================================="
    )

    logger.info("=" * 80)
    logger.info("HTML AFTER CLEANING")
    logger.info(f"Length : {len(cleaned_html)}")
    logger.info(cleaned_html[:1000])
    logger.info("=" * 80)

    return cleaned_html

def _preserve_business_layouts(soup: BeautifulSoup, adapter: Optional[Any]) -> Set[str]:
    """
    Builds the set of preservation labels dynamically based on columns, aliases,
    and extraction fields from the adapter's schema, instead of using hardcoded keywords.
    """
    schema_labels = set()
    if adapter and hasattr(adapter, "schema") and adapter.schema:
        schema = adapter.schema
        for col in schema.get("columns", []):
            schema_labels.add(str(col).strip().lower())
        aliases = schema.get("aliases", {})
        for k, v in aliases.items():
            schema_labels.add(str(k).strip().lower())
            schema_labels.add(str(v).strip().lower())
        ext_fields = schema.get("extraction_fields", {})
        for k in ext_fields.keys():
            schema_labels.add(str(k).strip().lower())
            
    # Fallback to defaults if schema_labels is empty
    if not schema_labels:
        schema_labels = {
            "investment", "investment required", "franchise fee", "phone", 
            "email", "address", "support", "training", "brand", "category",
            "about", "business model", "royalty", "roi", "payback", "location"
        }
    return schema_labels

def _should_preserve_tag(tag: Any, schema_labels: Set[str]) -> bool:
    """
    Helper to check if tag should be preserved.
    """
    if tag.name in ("html", "body") or tag.parent is None:
        return True
        
    # Preserve tables and definition lists
    if tag.name in ("table", "dl") or tag.find(["table", "dl"]):
        return True
        
    # Check text in heading/label tags or paragraph/span/div tags for schema labels
    for el in [tag] + list(tag.find_all(True)):
        el_name = el.name
        el_text = el.get_text(separator=" ", strip=True).lower()
        
        if el_name in ("table", "dl"):
            return True
            
        if el_name in ("h1", "h2", "h3", "h4", "h5", "h6", "label", "dt", "th", "td", "span", "p", "div"):
            if any(lbl in el_text for lbl in schema_labels):
                return True
    return False

def _remove_noise(soup: BeautifulSoup, dom_clean_config: dict, schema_labels: Set[str]) -> tuple[int, int]:
    """
    Decomposes technical tags, comments, and config-specified noise elements.
    """
    removed_nodes_count = 0
    preserved_important_nodes_count = 0

    # 1. Decompose technical tags
    technical_tags = ["script", "style", "noscript", "template", "svg", "canvas", "iframe", "embed", "object"]
    for tag in soup(technical_tags):
        tag.decompose()
        
    # 2. Strip comments
    comments = soup.find_all(string=lambda text: isinstance(text, Comment))
    for comment in comments:
        comment.extract()
        
    # 3. Content container extraction
    content_container = dom_clean_config.get("content_container")
    if content_container:
        container_el = soup.select_one(content_container)
        if container_el:
            # Modify tag content in place
            soup.contents = container_el.contents
            
    # 4. Removable selectors
    removable_selectors = dom_clean_config.get("removable_selectors", [])
    for sel in removable_selectors:
        try:
            for el in list(soup.select(sel)):
                if el.parent is None or el.name in ("html", "body"):
                    continue
                if _should_preserve_tag(el, schema_labels):
                    preserved_important_nodes_count += 1
                else:
                    el.decompose()
                    removed_nodes_count += 1
        except Exception:
            pass
                
    # 5. Ignored classes / ids
    ignored_classes = dom_clean_config.get("ignored_classes", [])
    ignored_ids = dom_clean_config.get("ignored_ids", [])
    if ignored_classes or ignored_ids:
        for tag in list(soup.find_all(True)):
            if tag.name in ("html", "body") or tag.parent is None:
                continue
            classes = [c.lower() for c in tag.get("class", [])] if tag.get("class") else []
            tag_id = str(tag.get("id", "")).lower()
            if any(cls.lower() in classes for cls in ignored_classes) or any(id_kw.lower() in tag_id for id_kw in ignored_ids):
                if _should_preserve_tag(tag, schema_labels):
                    preserved_important_nodes_count += 1
                else:
                    tag.decompose()
                    removed_nodes_count += 1

    return removed_nodes_count, preserved_important_nodes_count

def _normalize_html(soup: BeautifulSoup, dom_clean_config: dict):
    """
    Normalizes images, links, tags, and attributes in the DOM.
    """
    # 1. Image handling
    image_handling = dom_clean_config.get("image_handling", "keep")
    if image_handling == "remove":
        for img in soup.find_all("img"):
            img.decompose()
    elif image_handling == "convert_to_text":
        for img in soup.find_all("img"):
            alt = img.get("alt", "") or img.get("title", "")
            if alt:
                img.replace_with(f" [Image: {alt}] ")
            else:
                img.decompose()
                
    # 2. Link handling
    link_handling = dom_clean_config.get("link_handling", "keep")
    if link_handling == "remove":
        for a in soup.find_all("a"):
            a.decompose()
    elif link_handling == "convert_to_text":
        for a in soup.find_all("a"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if text:
                a.replace_with(f" {text} ({href}) " if href else f" {text} ")
            else:
                a.decompose()

    # 3. Allowed tags filtering (strip other tags but keep inner contents)
    allowed_tags = dom_clean_config.get("allowed_tags")
    if allowed_tags:
        allowed_tags_set = set(allowed_tags)
        allowed_tags_set.update(["html", "body"])
        for tag in list(soup.find_all(True)):
            if tag.name not in allowed_tags_set and tag.parent is not None:
                tag.unwrap()

    # 4. Strip unnecessary attributes to compress DOM size
    allowed_attrs = {
        "href", "src", "value", "title", "alt", "placeholder",
        "class", "id", "role", "aria-label", "aria-controls",
        "data-bs-toggle", "data-toggle"
    }
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in allowed_attrs}

def extract_metadata(raw_html: str) -> dict:
    """
    Extracts page headers, meta description, and page title.
    """
    if not raw_html:
        return {"title": "", "description": "", "og_properties": {}}
        
    soup = BeautifulSoup(raw_html, "lxml")
    
    title = ""
    if soup.title:
        title = soup.title.string or ""
    else:
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text()
            
    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc:
        description = meta_desc.get("content", "")
    else:
        og_desc = soup.find("meta", attrs={"property": "og:description"})
        if og_desc:
            description = og_desc.get("content", "")
            
    og_properties = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        content = meta.get("content")
        if prop and content and (prop.startswith("og:") or prop.startswith("twitter:")):
            og_properties[prop] = content
            
    return {
        "title": title.strip(),
        "description": description.strip(),
        "og_properties": og_properties
    }

def estimate_tokens(cleaned_html: str) -> int:
    """
    Estimates token count of cleaned HTML by taking the max of
    estimated HTML tokens and estimated visible text tokens.
    """
    if not cleaned_html:
        return 0
    html_tokens = len(cleaned_html) // 4
    
    soup = BeautifulSoup(cleaned_html, "html.parser")
    visible_text = soup.get_text(" ", strip=True)
    text_tokens = len(visible_text) // 3
    
    return max(html_tokens, text_tokens)

def detect_page_type(cleaned_html: str) -> dict:
    """
    Detects webpage type using fast DOM-structure heuristics.
    Returns a dict with "page_type" and "confidence".
    """
    if not cleaned_html:
        return {"page_type": "Unknown", "confidence": 0.0}
        
    soup = BeautifulSoup(cleaned_html, "html.parser")
    text_lower = soup.get_text(" ").lower()
    
    h1s = soup.find_all("h1")
    h2s = soup.find_all("h2")
    h3s = soup.find_all("h3")
    headings_count = len(h1s) + len(h2s) + len(h3s)
    paragraphs = soup.find_all("p")
    lists = soup.find_all(["ul", "ol"])
    tables = soup.find_all("table")
    details = soup.find_all("details")
    links = soup.find_all("a")
    code_snippets = soup.find_all(["code", "pre"])
    
    def has_class_or_id_match(keywords: list[str]) -> int:
        match_count = 0
        for tag in soup.find_all(True):
            tag_id = str(tag.get("id", "")).lower()
            tag_classes = [c.lower() for c in tag.get("class", [])] if tag.get("class") else []
            for kw in keywords:
                if kw in tag_id or any(kw in c for c in tag_classes):
                    match_count += 1
        return match_count

    scores = {
        "FAQ": 0.0,
        "Product Listing": 0.0,
        "Franchise Listing": 0.0,
        "Documentation": 0.0,
        "News Article": 0.0,
        "Blog": 0.0,
        "Product Page": 0.0,
        "Company Website": 0.0
    }

    # FAQ
    faq_keywords = ["faq", "frequently-asked", "question", "answer"]
    faq_matches = has_class_or_id_match(faq_keywords)
    if faq_matches >= 3 or len(details) >= 3:
        scores["FAQ"] += 0.6
    q_headings = sum(1 for h in (h2s + h3s) if h.get_text().strip().endswith("?"))
    if q_headings >= 3:
        scores["FAQ"] += 0.5
    if "frequently asked questions" in text_lower or "faq" in text_lower:
        scores["FAQ"] += 0.3

    # Franchise / Product Listing
    price_count = text_lower.count("$") + text_lower.count("€") + text_lower.count("£") + text_lower.count("price")
    action_count = text_lower.count("add to cart") + text_lower.count("buy now") + text_lower.count("checkout")
    
    franchise_keywords = ["franchise", "territory", "own a unit", "investment range", "franchising"]
    franchise_matches = sum(1 for kw in franchise_keywords if kw in text_lower)
    
    if franchise_matches >= 2:
        scores["Franchise Listing"] += 0.8
        
    product_keywords = ["product", "item", "card", "grid", "listing", "shop"]
    product_matches = has_class_or_id_match(product_keywords)
    if price_count >= 5 and (product_matches >= 5 or action_count >= 3):
        scores["Product Listing"] += 0.7
        
    # Product Page
    if price_count > 0 and action_count >= 1 and price_count < 5:
        scores["Product Page"] += 0.7
        
    # Documentation
    doc_keywords = ["docs", "documentation", "guide", "api", "reference"]
    doc_matches = sum(1 for kw in doc_keywords if kw in text_lower)
    if len(code_snippets) >= 3:
        scores["Documentation"] += 0.4
    if headings_count >= 8:
        scores["Documentation"] += 0.3
    if doc_matches >= 2:
        scores["Documentation"] += 0.3

    # News / Blog
    article_keywords = ["author", "published", "byline", "written-by", "date"]
    article_matches = has_class_or_id_match(article_keywords)
    if article_matches >= 2:
        scores["News Article"] += 0.4
        scores["Blog"] += 0.4
    if len(paragraphs) >= 6:
        if len(links) < len(paragraphs) * 2.5:
            scores["Blog"] += 0.3
            scores["News Article"] += 0.3
            
    news_keywords = ["news", "report", "press release", "journal", "associated press", "editor"]
    news_matches = sum(1 for kw in news_keywords if kw in text_lower)
    if news_matches >= 2:
        scores["News Article"] += 0.3
    else:
        scores["Blog"] += 0.1

    # Company Website
    company_keywords = ["about us", "contact us", "our services", "careers", "privacy policy", "solutions", "partners"]
    comp_matches = sum(1 for kw in company_keywords if kw in text_lower)
    if comp_matches >= 3:
        scores["Company Website"] += 0.7

    best_type = "Unknown"
    best_score = 0.0
    for ptype, score in scores.items():
        if score > best_score:
            best_score = score
            best_type = ptype
            
    if best_score < 0.45:
        best_type = "Unknown"
        best_score = 0.0
        
    return {
        "page_type": best_type,
        "confidence": round(min(best_score, 1.0), 2)
    }
