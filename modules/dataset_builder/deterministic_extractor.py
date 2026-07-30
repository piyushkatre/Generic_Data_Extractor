import re
import os
import json
from typing import Dict, Any, List, Optional, Tuple
from bs4 import BeautifulSoup, Tag
from utils.logger import get_logger
from core.field_strategy import get_strategy
import inspect

logger = get_logger(__name__)

# Legacy fallback vocabulary for franchise-shaped schemas. Schema-declared
# aliases (schema["aliases"]) always take priority when present — see
# resolve_key_to_field() below. This registry only ever resolves to field
# names already registered in core/field_strategy.py, so it is inert (never
# mis-captures a field) for any schema whose field names aren't part of that
# franchise-shaped set. It exists so DeterministicExtractor still produces
# useful output when constructed without a schema, or with a schema that
# doesn't declare its own aliases. Kept intentionally (not schema-driven yet)
# until field ownership itself becomes schema-driven in a later milestone.
CONCEPT_REGISTRY = {
    "investment_required": ["investment", "capital", "investment required", "initial investment", "total investment", "capital required"],
    "area_required": ["area", "space", "floor area", "space required", "store size", "area required"],
    "franchise_fee": ["fee", "franchise fee", "joining fee", "signup fee", "entry fee"],
    "agreement_duration": ["agreement", "contract", "term", "tenure", "agreement duration"],
    "expected_hours": ["hours", "working hours", "expected hours"],
    "training": ["training", "training support"],
    "support": ["support", "assistance", "business support"],
    "preferred_locations": ["location", "preferred location", "expansion location", "preferred locations"],
    "number_of_employees": ["employees", "staff", "no of employees", "number of employees"],
    "number_of_outlets": ["outlets", "stores", "units", "number of outlets", "franchise outlets"],
    "established_year": ["established", "founded", "established year", "year founded", "founded year",
                         "operations commenced on", "operational since", "operations since"],
    "franchise_start_year": ["franchise since", "franchising commenced", "franchise start", "franchise since year",
                              "franchising / distribution commenced on", "franchising commenced on",
                              "distribution commenced on"],
    "operations_commenced": ["operations commenced", "business commenced"],
    "phone": ["phone", "mobile", "contact", "tele", "telephone"],
    "email": ["email", "mail", "email address"],
    "website": ["website", "site", "web site", "official website"],
    "address": ["address", "registered office", "head office"],
    "brand": ["brand", "brand name", "name of brand"],
    "franchise_name": ["franchise name", "name of the franchise"]
}

# ---------------------------------------------------------------------------
# Generic "Label: Value Label: Value ..." text-blob parsing.
#
# Some pages pack multiple key/value pairs as one continuous run of text
# inside a single element with no per-pair child element to split on (e.g.
# a <div> whose only content is the literal text
# "Operations Commenced On: 2023 Franchising / Distribution Commenced On:
# 2025 Number of Employees: 15" - no <li>/<span>/<dt> boundaries at all).
# detect_and_classify_layouts() has no element-count signal to work with
# for this shape (0 or 1 direct children), so it falls back to detecting
# the pattern in the raw TEXT itself. A "label" is a short run of words
# starting with a capital letter (allowing "/", "&", and lowercase
# connector words like "of"/"on" within it) immediately followed by ":".
# This is purely structural - it never references any specific label text,
# class name, id, or site.
_LABEL_FIRST_WORD = r"[A-Z][A-Za-z\-]*"
_LABEL_OTHER_WORD = r"[A-Za-z][A-Za-z\-]*"
_LABEL_WORD_SEP = r"[\s/&]+"
_LABEL_VALUE_PATTERN = re.compile(
    rf"(?P<label>{_LABEL_FIRST_WORD}(?:{_LABEL_WORD_SEP}{_LABEL_OTHER_WORD}){{0,5}})\s*:\s*"
)


def _extract_label_value_pairs_from_text(text: str) -> List[Tuple[str, str]]:
    """
    Splits text containing zero or more "Label: Value" pairs with no
    element-level separation between them, in two tiers:

    1. If the text splits into 2+ real lines (BeautifulSoup preserves
       literal newlines present in the source text node) and EVERY line
       independently looks like exactly one "Label: Value" pair, use that
       directly - each line is already unambiguous on its own, including
       when a value happens to look like a label-shaped word (e.g. a name).
    2. Otherwise (everything collapsed onto one line, as in the motivating
       real-world case), fall back to finding every "Label:" boundary in
       the whole blob and taking each value as the text up to the next
       boundary (or end of string). This is unambiguous whenever values
       are non-word text (numbers, currency, etc.), which is the common
       case for this shape - see the docstring above for why a value that
       itself looks like another label is a known, accepted limitation of
       text-only inference without line breaks to lean on.
    """
    if not text:
        return []

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    if len(lines) >= 2:
        line_pairs: List[Tuple[str, str]] = []
        for ln in lines:
            m = _LABEL_VALUE_PATTERN.match(ln)
            if not m:
                line_pairs = []
                break
            label = m.group("label").strip()
            value = ln[m.end():].strip()
            if not label or not value:
                line_pairs = []
                break
            line_pairs.append((label, value))
        if len(line_pairs) >= 2:
            return line_pairs

    matches = list(_LABEL_VALUE_PATTERN.finditer(text))
    pairs: List[Tuple[str, str]] = []
    for i, m in enumerate(matches):
        label = m.group("label").strip()
        value_start = m.end()
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        value = text[value_start:value_end].strip()
        if label and value:
            pairs.append((label, value))
    return pairs


class DeterministicExtractor:
    """
    Deterministic field parser extracting business attributes from web pages
    by matching generic HTML structures and metadata patterns.
    """

    def __init__(self, schema: Dict[str, Any] = None, config: Dict[str, Any] = None):
        self.schema = schema or {}
        self.config = config or {}
        self.raw_to_field = {}
        
        ext_fields = self.schema.get("extraction_fields", {})
        aliases = self.schema.get("aliases", {})
        
        # Build target column to field key lookup
        col_to_field = {}
        for field_name in ext_fields.keys():
            col_name = aliases.get(field_name) or aliases.get(field_name.replace("_", " "))
            if not col_name:
                norm_field = field_name.lower().replace("_", "")
                for col in self.schema.get("columns", []):
                    if col.lower().replace(" ", "").replace("_", "") == norm_field:
                        col_name = col
                        break
            if col_name:
                col_to_field[col_name.lower().strip()] = field_name
        
        # Map every alias key in schema to the matching field_name
        for alias_key, col_name in aliases.items():
            field_key = col_to_field.get(col_name.lower().strip())
            if field_key:
                self.raw_to_field[alias_key.lower().strip()] = field_key

    def is_portal_link(self, href: str, current_url: str = "") -> bool:
        """
        Detects self-referential links (the current page linking back to its own
        site/portal) generically, from the current page's own domain — no
        hardcoded list of known portal names.
        """
        href_lower = href.lower().strip()

        # Skip social sharing URLs
        share_patterns = [
            "share", "sharer", "intent/tweet", "sharearticle", "dialog/share",
            "pin/create", "sharing", "twitter.com/home?status", "facebook.com/sharer.php"
        ]
        if any(p in href_lower for p in share_patterns):
            return True

        # Skip links pointing back to the current page's own domain
        own_domain_parts = set()
        if current_url:
            from urllib.parse import urlparse
            try:
                parsed = urlparse(current_url)
                netloc = parsed.netloc.lower()
                domain_parts = netloc.split(".")
                for part in domain_parts:
                    if len(part) > 3 and part not in ("www", "com", "net", "org", "co", "in"):
                        own_domain_parts.add(part)
            except Exception:
                pass

        for part in own_domain_parts:
            if part in href_lower:
                return True
        return False

    def resolve_key_to_field(self, key: str) -> Optional[str]:
        k_clean = key.lower().strip().rstrip(":")
        
        is_yes_no_question = k_clean.startswith(("do you", "do we", "is there", "are there", "has ", "does ", "is it", "is this", "are you", "can ", "should ", "will ", "would ", "have you", "suitable for"))
        excluded_fields = {"agreement_duration", "training", "support", "investment_required", "franchise_fee"} if is_yes_no_question else set()

        # 1. Check schema aliases mapping first (highest priority)
        if self.raw_to_field and k_clean in self.raw_to_field:
            field_name = self.raw_to_field[k_clean]
            if field_name not in excluded_fields and self._is_field_allowed(field_name):
                return field_name
                
        # 2. Try exact match on concept registry values
        for field_name, aliases in CONCEPT_REGISTRY.items():
            if field_name in excluded_fields:
                continue
            if k_clean in aliases:
                if self._is_field_allowed(field_name):
                    return field_name
                    
        # 3. Try fuzzy/substring match on schema aliases
        if self.raw_to_field:
            for alias_k, field_name in self.raw_to_field.items():
                if field_name in excluded_fields:
                    continue
                if alias_k in k_clean or k_clean in alias_k:
                    if self._is_field_allowed(field_name):
                        return field_name
                        
        # 4. Try substring match on concept registry values
        for field_name, aliases in CONCEPT_REGISTRY.items():
            if field_name in excluded_fields:
                continue
            for alias in aliases:
                if len(alias) > 3 and (alias in k_clean or k_clean in alias):
                    if self._is_field_allowed(field_name):
                        return field_name
                        
        return None

    def _is_field_allowed(self, field: str) -> bool:
        strategy = get_strategy(field)
        return strategy.get("owner") in ("deterministic", "hybrid")

    def detect_and_classify_layouts(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        Scans DOM tree to detect and classify recurring business layouts.
        """
        classified_layouts = []
        
        # 1. Find Tables (Specification Layout or QA Layout)
        for table in soup.find_all("table"):
            cells = table.find_all(["td", "th"])
            has_q = any("?" in cell.get_text() for cell in cells)
            if has_q:
                classified_layouts.append({
                    "type": "QA Layout",
                    "element": table,
                    "snippet": str(table)[:200]
                })
            else:
                classified_layouts.append({
                    "type": "Specification Layout",
                    "element": table,
                    "snippet": str(table)[:200]
                })
            
        # 2. Find Definition Lists (Specification Layout or QA Layout)
        for dl in soup.find_all("dl"):
            dts = dl.find_all("dt")
            has_q = any("?" in dt.get_text() for dt in dts)
            if has_q:
                classified_layouts.append({
                    "type": "QA Layout",
                    "element": dl,
                    "snippet": str(dl)[:200]
                })
            else:
                classified_layouts.append({
                    "type": "Specification Layout",
                    "element": dl,
                    "snippet": str(dl)[:200]
                })
            
        # 3. Find list elements (Checklist Layout, Specification Layout, QA Layout, or Content Section)
        for list_tag in soup.find_all(["ul", "ol"]):
            items = list_tag.find_all("li")
            if not items:
                continue
            first_text = items[0].get_text().strip()
            if any(first_text.startswith(c) for c in ["✓", "✔", "☑", "•", "-", "*"]):
                classified_layouts.append({
                    "type": "Checklist Layout",
                    "element": list_tag,
                    "snippet": str(list_tag)[:200]
                })
            else:
                # Check for structural Q&A bullet lists
                has_q = any("?" in li.get_text() and ":" in li.get_text() for li in items)
                if has_q:
                    classified_layouts.append({
                        "type": "QA Layout",
                        "element": list_tag,
                        "snippet": str(list_tag)[:200]
                    })
                else:
                    has_colon = all(":" in li.get_text() for li in items[:2])
                    if has_colon:
                        classified_layouts.append({
                            "type": "Specification Layout",
                            "element": list_tag,
                            "snippet": str(list_tag)[:200]
                        })
                    else:
                        classified_layouts.append({
                            "type": "Content Section",
                            "element": list_tag,
                            "snippet": str(list_tag)[:200]
                        })

        # 4. Heading + Sibling Paragraph (Structural QA Layout)
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"]):
            heading_text = heading.get_text(strip=True)
            if "?" in heading_text:
                sibling = heading.next_sibling
                while sibling and not isinstance(sibling, Tag):
                    sibling = sibling.next_sibling
                if sibling and sibling.name in ("p", "div", "span") and sibling.get_text(strip=True):
                    qa_container = soup.new_tag("div")
                    # Append copies to avoid mutating original DOM structure
                    qa_container.append(BeautifulSoup(str(heading), "html.parser"))
                    qa_container.append(BeautifulSoup(str(sibling), "html.parser"))
                    classified_layouts.append({
                        "type": "QA Layout",
                        "element": qa_container,
                        "snippet": f"Q: {heading_text} | A: {sibling.get_text(strip=True)[:100]}"
                    })

        # 5. Find potential stacked or summary containers
        for div in soup.find_all(["div", "section"]):
            if len(div.get_text()) > 500:
                continue
                
            children = [c for c in div.find_all(recursive=False) if c.get_text(strip=True)]
            if len(children) == 2:
                t1 = children[0].get_text(strip=True)
                t2 = children[1].get_text(strip=True)
                
                is_val1 = any(ind in t1.lower() for ind in ["rs", "₹", "$", "lakh", "crore", "sq", "feet", "outlets", "year"]) or re.search(r"^\d", t1)
                is_val2 = any(ind in t2.lower() for ind in ["rs", "₹", "$", "lakh", "crore", "sq", "feet", "outlets", "year"]) or re.search(r"^\d", t2)
                
                if (is_val1 and len(t2) < 40) or (is_val2 and len(t1) < 40):
                    classified_layouts.append({
                        "type": "Statistic Layout",
                        "element": div,
                        "snippet": str(div)[:200]
                    })
                    
            elif len(children) >= 3 and len(children) <= 8:
                child_texts = [c.get_text(strip=True) for c in children]
                has_colons = all(":" in txt for txt in child_texts)
                if has_colons:
                    classified_layouts.append({
                        "type": "Summary Layout",
                        "element": div,
                        "snippet": str(div)[:200]
                    })

            elif len(children) <= 1:
                # Generic text-blob variant of a Summary Layout: no distinct
                # per-pair child element at all (0 children), or a single
                # wrapper child (1 child) - e.g. <div class="body-item">
                # wrapping one <div class="body-content"> that itself holds
                # several "Label: Value" pairs as one run of text with no
                # <li>/<span>/<dt> boundaries between them. Detected purely
                # from the TEXT structure (see _extract_label_value_pairs_from_text),
                # never from class names/ids/selectors.
                if len(children) == 1 and children[0].name in ("div", "section"):
                    # Defer to the child - it's visited separately by this
                    # same loop and is the more specific match, avoiding a
                    # duplicate classification of the same text twice.
                    continue
                text = div.get_text(separator=" ", strip=True)
                if len(_extract_label_value_pairs_from_text(text)) >= 2:
                    classified_layouts.append({
                        "type": "Summary Layout",
                        "element": div,
                        "snippet": str(div)[:200]
                    })

        # 6. Heading Sections (Content Section)
        for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
            # Prevent re-adding Q&A headings as normal content sections
            if "?" not in heading.get_text():
                classified_layouts.append({
                    "type": "Content Section",
                    "element": heading,
                    "snippet": str(heading)[:200]
                })
            
        return classified_layouts

    def extract_relationships_from_layout(self, layout: Dict[str, Any]) -> List[Tuple[str, Any]]:
        """
        Extracts Key -> Value, List/Array, or Paragraph relationships from the layout.
        """
        relationships = []
        l_type = layout["type"]
        el = layout["element"]
        
        if l_type == "Specification Layout":
            if el.name == "table":
                rows = el.find_all("tr")
                if rows:
                    headers = []
                    header_cells = rows[0].find_all(["th", "td"])
                    is_header = False
                    if rows[0].find("th") or all(c.find(["strong", "b"]) for c in header_cells):
                        is_header = True
                    
                    if is_header and len(header_cells) > 1:
                        headers = [cell.get_text(separator=" ", strip=True).lower().rstrip(":") for cell in header_cells]
                        start_idx = 1
                    else:
                        headers = []
                        start_idx = 0
                        
                    for row in rows[start_idx:]:
                        cells = row.find_all(["td", "th"])
                        if len(cells) == 2 and not headers:
                            k = cells[0].get_text(separator=" ", strip=True)
                            v = cells[1].get_text(separator=" ", strip=True)
                            relationships.append((k, v))
                        elif headers and len(cells) == len(headers):
                            for h, cell in zip(headers, cells):
                                v = cell.get_text(separator=" ", strip=True)
                                relationships.append((h, v))
            elif el.name == "dl":
                dts = el.find_all("dt")
                for dt in dts:
                    dd = dt.find_next_sibling("dd")
                    if dd:
                        relationships.append((dt.get_text(strip=True), dd.get_text(strip=True)))
            else:
                for tag in el.find_all(["li", "p", "div", "span"], recursive=True):
                    text = tag.get_text(separator=" ", strip=True)
                    if ":" in text and not any(proto in text.lower() for proto in ["http:", "https:", "mailto:", "tel:"]):
                        parts = text.split(":", 1)
                        relationships.append((parts[0], parts[1]))
                        
        elif l_type == "QA Layout":
            if el.name == "dl":
                dts = el.find_all("dt")
                for dt in dts:
                    dd = dt.find_next_sibling("dd")
                    if dd:
                        relationships.append((dt.get_text(strip=True), dd.get_text(strip=True)))
            elif el.name == "table":
                rows = el.find_all("tr")
                for row in rows:
                    cells = row.find_all(["td", "th"])
                    if len(cells) == 2:
                        relationships.append((cells[0].get_text(strip=True), cells[1].get_text(strip=True)))
            elif el.name in ("ul", "ol"):
                for li in el.find_all("li"):
                    text = li.get_text(separator=" ", strip=True)
                    if ":" in text:
                        parts = text.split(":", 1)
                        relationships.append((parts[0], parts[1]))
            else:
                # Sibling question + paragraph wrapped div
                children = [c for c in el.find_all(recursive=False)]
                if len(children) == 2:
                    relationships.append((children[0].get_text(strip=True), children[1].get_text(strip=True)))

        elif l_type == "Statistic Layout":
            children = [c for c in el.find_all(recursive=False) if c.get_text(strip=True)]
            if len(children) == 2:
                t1 = children[0].get_text(strip=True)
                t2 = children[1].get_text(strip=True)
                # Determine which child is the numeric value and which is the label.
                # Only genuine numeric/currency units are used as value indicators.
                # Generic nouns like "outlets" and "year" are intentionally excluded
                # because they appear in labels (e.g. "Franchise Outlets", "Established Year")
                # and would cause the label to be misidentified as the value.
                _numeric_units = ["rs", "\u20b9", "$", "lakh", "crore", "sq", "sqft", "%"]

                def _is_numeric_value(text: str) -> bool:
                    if re.search(r"^\d", text):
                        return True
                    return any(unit in text.lower() for unit in _numeric_units) and len(text) < 40

                t1_is_val = _is_numeric_value(t1)
                t2_is_val = _is_numeric_value(t2)

                if t2_is_val and not t1_is_val:
                    # t1 = label, t2 = value  (normal card: title on top, value below)
                    relationships.append((t1, t2))
                elif t1_is_val and not t2_is_val:
                    # t1 = value, t2 = label  (inverted card) — swap to (label, value)
                    relationships.append((t2, t1))
                else:
                    # Ambiguous (both or neither look numeric) — treat first child as label
                    relationships.append((t1, t2))
                    
        elif l_type == "Summary Layout":
            for tag in el.find_all(recursive=True):
                text = tag.get_text(separator=" ", strip=True)
                if ":" in text:
                    parts = text.split(":", 1)
                    relationships.append((parts[0], parts[1]))

            if not relationships:
                # Text-blob variant (detect_and_classify_layouts() rule 5,
                # the <=1-child branch): no descendant element carried an
                # individual "Label: Value" pair, because there are no
                # per-pair child elements at all. Reuse the same generic
                # pattern matcher used to detect this layout in the first
                # place, applied to the element's own text - not a separate
                # extraction pipeline.
                text = el.get_text(separator=" ", strip=True)
                relationships.extend(_extract_label_value_pairs_from_text(text))

        elif l_type == "Checklist Layout":
            list_items = [li.get_text(separator=" ", strip=True) for li in el.find_all("li") if li.get_text(strip=True)]
            prev_header = el.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
            if prev_header:
                k = prev_header.get_text(strip=True)
                relationships.append((k, list_items))
            else:
                for item in list_items:
                    for kw in ["training", "marketing", "support"]:
                        if kw in item.lower():
                            relationships.append((kw, item))
                            
        elif l_type == "Content Section":
            k = el.get_text(strip=True)
            sibling = el.find_next_sibling()
            if sibling:
                if sibling.name in ("p", "span", "div") and not sibling.find(["div", "p", "table", "ul", "ol"]):
                    v = sibling.get_text(separator=" ", strip=True)
                    relationships.append((k, v))
                elif sibling.name in ("ul", "ol"):
                    list_items = [li.get_text(separator=" ", strip=True) for li in sibling.find_all("li") if li.get_text(strip=True)]
                    if list_items:
                        relationships.append((k, list_items))
                        
        return relationships

    def extract(self, html_content: str, url: str = "") -> Dict[str, Any]:
        logger.info(f"Running extractor from: {inspect.getfile(self.__class__)}")

        extracted = {}
        if not html_content:
            return extracted

        soup = BeautifulSoup(html_content, "html.parser")

        # Extract top-level heading as the main franchise name (page title context relationship)
        if self._is_field_allowed("franchise_name"):
            franchise_name = None
            if franchise_name:
                extracted.setdefault("franchise_name", franchise_name)

        # 1. Structured Data (Relationship 4)
        self.extract_from_jsonld(soup, extracted, url=url)
        self.extract_from_meta(soup, extracted, url=url)
        self.extract_from_breadcrumbs(soup, extracted)
        self.extract_primary_identity(soup, extracted)

        # 2. Anchor -> Destination (Relationship 3)
        self.extract_from_anchor_attributes(soup, extracted, url=url)

        # 3. Media (Relationship 5)
        self.extract_from_images(soup, extracted)

        # 4. Layout-based extraction (Relationship 1, 2, 6)
        layouts = self.detect_and_classify_layouts(soup)
        layouts_audit_data = []

        for layout in layouts:
            layout_entry = {
                "type": layout["type"],
                "snippet": layout.get("snippet", "")[:200],
                "extracted_fields": []
            }
            relationships = self.extract_relationships_from_layout(layout)
            for k, v in relationships:
                field_name = self.resolve_key_to_field(k)

                if field_name:
                    is_added = False

                    if isinstance(v, list):
                        v_clean = [x.strip() for x in v if x and x.strip()]
                        if v_clean:
                            extracted.setdefault(field_name, v_clean)
                            is_added = True

                    else:
                        v_str = str(v).strip()

                        negatives = [
                            "not revealed",
                            "not disclosed",
                            "n/a",
                            "nil",
                            "none",
                            "not specified",
                            "not available",
                        ]

                        if v_str and not any(
                            neg == v_str.lower() or v_str.lower().startswith(neg)
                            for neg in negatives
                        ):

                            v_str = re.sub(r"\s+", " ", v_str).strip()

                            # -------------------------------------------------------
                            # Brand Validation (Only affects Brand field)
                            # -------------------------------------------------------
                            if field_name == "brand":
                                # Ignore long descriptive paragraphs
                                if (
                                    len(v_str) > 60
                                    or len(v_str.split()) > 8
                                    or "." in v_str
                                ):
                                    logger.info(
                                        f"[Deterministic] Ignoring invalid Brand: {v_str[:80]}"
                                    )
                                    continue

                            if (
                                field_name not in extracted
                                or extracted[field_name] in (None, "", [], {})
                            ):
                                extracted[field_name] = v_str
                                is_added = True

                    if is_added:
                        layout_entry["extracted_fields"].append(field_name)
                        logger.info(
                            f"[Deterministic] Extracted Field: {field_name} from Layout: {layout['type']}"
                        )

            layouts_audit_data.append(layout_entry)

        # Save layouts trace to 05_layouts.json
        from modules.llm.ollama_provider import get_latest_debug_dir
        debug_dir = get_latest_debug_dir()
        if debug_dir:
            try:
                os.makedirs(debug_dir, exist_ok=True)
                with open(os.path.join(debug_dir, "05_layouts.json"), "w", encoding="utf-8") as f:
                    json.dump(layouts_audit_data, f, indent=2)
            except Exception as e:
                logger.warning(f"Failed to write 05_layouts.json: {e}")

        # WhatsApp link phone number extraction fallback
        if not extracted.get("phone") and extracted.get("whatsapp_link"):
            wa_link = extracted["whatsapp_link"]
            from urllib.parse import urlparse, parse_qs
            try:
                parsed_url = urlparse(wa_link)
                params = parse_qs(parsed_url.query)
                phone_list = params.get("phone")
                if phone_list:
                    extracted["phone"] = phone_list[0].strip()
                    logger.info(f"[Deterministic] Extracted fallback phone '{extracted['phone']}' from whatsapp_link.")
            except Exception as e:
                logger.warning(f"Failed to extract phone from whatsapp_link: {e}")


        # Fall back to franchise_name for brand when brand wasn't resolved
        # elsewhere (or looks like an oversized, mis-captured blob of text).
        if extracted.get("franchise_name"):
            current_brand = extracted.get("brand")
            if (
                not current_brand
                or len(current_brand.split()) > 8
                or len(current_brand) > 60
            ):
                extracted["brand"] = extracted["franchise_name"]


        if "franchise_since" in extracted and "franchise_start_year" not in extracted:
            extracted["franchise_start_year"] = extracted["franchise_since"]
        if "franchise_start_year" in extracted and "franchise_since" not in extracted:
            extracted["franchise_since"] = extracted["franchise_start_year"]

        # Parse FAQ sections
        self.extract_from_faq(soup, extracted)

        return extracted

    import re

    def extract_primary_identity(self, soup, extracted):
        """
        Extract Brand and Franchise Name from high-confidence page elements.

        This function ONLY populates:
            - franchise_name
            - brand

        It never overwrites existing values.
        """

        # Already extracted
        if extracted.get("franchise_name") and extracted.get("brand"):
            return

        candidates = []

        # ------------------------------------------------------------------
        # 1. JSON-LD Organization / Brand
        # ------------------------------------------------------------------
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                import json
                data = json.loads(script.string)

                if isinstance(data, dict):
                    name = data.get("name")
                    if name:
                        candidates.append(name)

            except Exception:
                pass

        # ------------------------------------------------------------------
        # 2. H1
        # ------------------------------------------------------------------
        h1 = soup.find("h1")
        if h1:
            candidates.append(h1.get_text(" ", strip=True))

        # ------------------------------------------------------------------
        # 3. Common identity containers
        # ------------------------------------------------------------------
        selectors = [
            ".company-name",
            ".brand-name",
            ".business-name",
            ".franchise-name",
            ".company-title",
        ]

        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                candidates.append(node.get_text(" ", strip=True))

        # ------------------------------------------------------------------
        # 4. HTML Title
        # ------------------------------------------------------------------
        if soup.title:
            candidates.append(soup.title.get_text(" ", strip=True))

        # ------------------------------------------------------------------
        # 5. Logo Alt
        # ------------------------------------------------------------------
        logo = soup.find("img", alt=True)
        if logo:
            candidates.append(logo["alt"])

        # ------------------------------------------------------------------
        # Normalize
        # ------------------------------------------------------------------
        for value in candidates:

            if not value:
                continue

            value = value.strip()

            if not value:
                continue

            if len(value) > 60:
                continue

            extracted.setdefault("franchise_name", value)
            extracted.setdefault("brand", value)

            logger.info(
                f"[Deterministic] Primary Identity: {value}"
            )

            break

    def extract_from_jsonld(self, soup: BeautifulSoup, extracted: Dict[str, Any], url: str = ""):
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                self._parse_json_ld(data, extracted, snippet=str(script), url=url)
            except Exception as e:
                logger.debug(f"[Deterministic] JSON-LD parse warning: {e}")
                continue

    def _parse_json_ld(self, data: Any, extracted: Dict[str, Any], snippet: str = "", url: str = ""):
        if isinstance(data, list):
            for item in data:
                self._parse_json_ld(item, extracted, snippet=snippet, url=url)
            return
        if not isinstance(data, dict):
            return
            
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                self._parse_json_ld(v, extracted, snippet=snippet, url=url)
                
        snippet_clean = snippet[:100].replace('\n', ' ').strip()

        # Parse Organization details
        name = data.get("name") or data.get("legalName")
        if name and isinstance(name, str):
            name_lower = name.lower()
            is_portal = any(p in name_lower for p in ["franchisebazar", "franchise bazar", "franchisemart", "franchise mart", "franchiseindia", "franchise india"])
            if not is_portal:
                if self._is_field_allowed("franchise_name"):
                    extracted.setdefault("franchise_name", name)
                
        email = data.get("email")
        if email and isinstance(email, str) and "@" in email:
            if not self.is_portal_link(email, current_url=url):
                if self._is_field_allowed("email"):
                    extracted.setdefault("email", email)
            
        tel = data.get("telephone") or data.get("phone")
        if tel and isinstance(tel, str):
            if self._is_field_allowed("phone"):
                extracted.setdefault("phone", tel)
            
        url_ld = data.get("url")
        if url_ld and isinstance(url_ld, str) and url_ld.startswith(("http", "www")):
            if not self.is_portal_link(url_ld, current_url=url):
                if self._is_field_allowed("website"):
                    extracted.setdefault("website", url_ld)
            
        logo = data.get("logo")
        if logo:
            l_url = None
            if isinstance(logo, str) and logo.startswith(("http", "www")):
                l_url = logo
            elif isinstance(logo, dict) and logo.get("url"):
                l_url = logo.get("url")
            if l_url and self._is_field_allowed("logo_url"):
                extracted.setdefault("logo", l_url)
                extracted.setdefault("logo_url", l_url)
                    
        addr = data.get("address")
        if addr:
            if isinstance(addr, str):
                if self._is_field_allowed("address"):
                    extracted.setdefault("address", addr)
            elif isinstance(addr, dict):
                parts = []
                for key in ["streetAddress", "addressLocality", "addressRegion", "postalCode", "addressCountry"]:
                    val = addr.get(key)
                    if val and isinstance(val, str):
                        parts.append(val)
                if parts and self._is_field_allowed("address"):
                    full_addr = ", ".join(parts)
                    extracted.setdefault("address", full_addr)

        if isinstance(data, dict) and data.get("@type") == "FAQPage":
            main_entity = data.get("mainEntity", [])
            if not isinstance(main_entity, list):
                main_entity = [main_entity]
            faq_list = extracted.setdefault("faq", [])
            for item in main_entity:
                if isinstance(item, dict) and item.get("@type") == "Question":
                    q = item.get("name")
                    ans_obj = item.get("acceptedAnswer")
                    a_val = ans_obj.get("text") if isinstance(ans_obj, dict) else None
                    if q and a_val:
                        faq_list.append({"question": str(q), "answer": str(a_val)})

        if isinstance(data, dict) and data.get("@type") == "BreadcrumbList":
            items = data.get("itemListElement", [])
            if isinstance(items, list):
                crumbs = []
                for item in items:
                    if isinstance(item, dict):
                        crumb_name = item.get("name") or (item.get("item", {}) if isinstance(item.get("item"), dict) else {}).get("name")
                        if crumb_name:
                            crumbs.append(str(crumb_name).strip())
                if crumbs:
                    hierarchy = " > ".join(crumbs)
                    if self._is_field_allowed("category"):
                        extracted.setdefault("category", crumbs[-1])
                    if self._is_field_allowed("segment"):
                        extracted.setdefault("segment", hierarchy)

    def extract_from_meta(self, soup: BeautifulSoup, extracted: Dict[str, Any], url: str = ""):
        for meta in soup.find_all("meta"):
            prop = meta.get("property", "").lower()
            name_attr = meta.get("name", "").lower()
            content = meta.get("content", "").strip()
            if not content:
                continue
                
            if prop in ("og:title", "twitter:title") or name_attr == "title":
                content_lower = content.lower()
                is_portal = any(p in content_lower for p in ["franchisebazar", "franchise bazar", "franchisemart", "franchise mart", "franchiseindia", "franchise india"])
                if not is_portal:
                    if self._is_field_allowed("franchise_name"):
                        extracted.setdefault("franchise_name", content)
            elif prop in ("og:description", "twitter:description") or name_attr == "description":
                if self._is_field_allowed("description"):
                    extracted.setdefault("description", content)
            elif prop == "og:url":
                if not self.is_portal_link(content, current_url=url):
                    if self._is_field_allowed("website"):
                        extracted.setdefault("website", content)

    def extract_from_anchor_attributes(self, soup: BeautifulSoup, extracted: Dict[str, Any], url: str = ""):
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            href_lower = href.lower()
            text_lower = a.get_text().lower()
            
            if self.is_portal_link(href, current_url=url):
                continue
                
            if href_lower.startswith("mailto:"):
                email = href[7:].split("?")[0].strip()
                if email and not self.is_portal_link(email, current_url=url):
                    if self._is_field_allowed("email"):
                        extracted.setdefault("email", email)
            elif href_lower.startswith("tel:"):
                phone = href[4:].split("?")[0].strip()
                if phone and self._is_field_allowed("phone"):
                    extracted.setdefault("phone", phone)
            elif "wa.me" in href_lower or "api.whatsapp.com" in href_lower or "whatsapp:" in href_lower:
                if self._is_field_allowed("whatsapp_link"):
                    extracted.setdefault("whatsapp_link", href)
            elif any(m in href_lower for m in ["maps.google", "google.com/maps", "openstreetmap.org", "openstreetmap", "directions", "location"]):
                if self._is_field_allowed("google_maps_link"):
                    extracted.setdefault("google_maps_link", href)
            elif "facebook" in href_lower or "facebook" in text_lower:
                if href.startswith(("http", "www")):
                    if self._is_field_allowed("facebook"):
                        extracted.setdefault("facebook", href)
            elif "instagram" in href_lower or "instagram" in text_lower:
                if href.startswith(("http", "www")):
                    if self._is_field_allowed("instagram"):
                        extracted.setdefault("instagram", href)
            elif "linkedin" in href_lower or "linkedin" in text_lower:
                if href.startswith(("http", "www")):
                    if self._is_field_allowed("linkedin"):
                        extracted.setdefault("linkedin", href)
            elif "twitter" in href_lower or "twitter" in text_lower or "x.com" in href_lower:
                if href.startswith(("http", "www")):
                    if self._is_field_allowed("twitter"):
                        extracted.setdefault("twitter", href)
            elif "youtube" in href_lower or "youtube" in text_lower or "youtu.be" in href_lower:
                if href.startswith(("http", "www")):
                    if self._is_field_allowed("youtube"):
                        extracted.setdefault("youtube", href)
            elif "website" in a.get_text().lower() or "visit website" in a.get_text().lower() or "visit site" in a.get_text().lower():
                if self._is_field_allowed("website"):
                    extracted.setdefault("website", href)

        # Regex fallback on raw body text for email/phone
        text_body = soup.get_text(separator=" ")
        if self._is_field_allowed("email") and "email" not in extracted:
            email_match = re.search(r"\b[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+\b", text_body)
            if email_match:
                val_m = email_match.group(0)
                if not self.is_portal_link(val_m, current_url=url):
                    extracted["email"] = val_m
        if self._is_field_allowed("phone") and "phone" not in extracted:
            phone_match = re.search(r"\b\+?\d[\d\s\-\(\)]{8,15}\d\b", text_body)
            if phone_match:
                val_m = phone_match.group(0)
                if sum(1 for c in val_m if c.isdigit()) >= 9:
                    extracted["phone"] = val_m

    def extract_from_images(self, soup: BeautifulSoup, extracted: Dict[str, Any]):
        images = []
        for img in soup.find_all("img", src=True):
            src = img["src"].strip()
            if src and not src.startswith("data:"):
                images.append(src)
                
        logo_url = None
        for img in soup.find_all("img", src=True):
            src = img["src"].strip()
            if not src or src.startswith("data:"):
                continue
            parent = img.parent
            is_header_or_logo = False
            while parent and parent.name != "body":
                p_class = " ".join(parent.get("class", [])) if parent.get("class") else ""
                p_id = parent.get("id", "") or ""
                if parent.name == "header" or "logo" in p_class.lower() or "logo" in p_id.lower() or "header" in p_class.lower():
                    is_header_or_logo = True
                    break
                parent = parent.parent
                
            img_class = " ".join(img.get("class", [])) if img.get("class") else ""
            img_id = img.get("id", "") or ""
            if is_header_or_logo or "logo" in img_class.lower() or "logo" in img_id.lower() or "logo" in src.lower():
                logo_url = src
                break
                
        if logo_url and self._is_field_allowed("logo_url"):
            extracted.setdefault("logo", logo_url)
            extracted.setdefault("logo_url", logo_url)
        elif images and self._is_field_allowed("logo_url"):
            extracted.setdefault("logo", images[0])
            extracted.setdefault("logo_url", images[0])
            
        if images and self._is_field_allowed("images"):
            extracted.setdefault("images", images[:15])

    def extract_from_faq(self, soup: BeautifulSoup, extracted: Dict[str, Any]):
        faq_items = []
        faq_blocks = soup.find_all(lambda tag: tag.get("itemtype") == "https://schema.org/FAQPage" or "faq" in " ".join(tag.get("class", [])).lower())
        for block in faq_blocks:
            questions = block.find_all(lambda t: t.get("itemprop") == "name" or "question" in " ".join(t.get("class", [])).lower() or t.name in ("h3", "h4"))
            for q_tag in questions:
                ans_tag = q_tag.find_next_sibling(lambda t: t.get("itemprop") == "text" or "answer" in " ".join(t.get("class", [])).lower() or t.name in ("p", "div"))
                if ans_tag:
                    q = q_tag.get_text(separator=" ", strip=True)
                    a = ans_tag.get_text(separator=" ", strip=True)
                    if q and a and len(q) < 200 and len(a) < 1000:
                        faq_items.append({"question": q, "answer": a})
                        
        if not faq_items:
            for q_tag in soup.find_all(["dt", "strong", "h4", "h5"]):
                text = q_tag.get_text(separator=" ", strip=True)
                if text.endswith("?") or any(w in text.lower() for w in ["what ", "why ", "how ", "where ", "who ", "when "]):
                    ans_tag = q_tag.find_next_sibling(["dd", "p", "div"])
                    if ans_tag:
                        ans_text = ans_tag.get_text(separator=" ", strip=True)
                        if ans_text and len(text) < 150 and 20 < len(ans_text) < 800:
                            faq_items.append({"question": text, "answer": ans_text})
                            
        if faq_items:
            existing_faq = extracted.setdefault("faq", [])
            for faq in faq_items:
                if faq not in existing_faq:
                    existing_faq.append(faq)

    def extract_from_breadcrumbs(self, soup: BeautifulSoup, extracted: Dict[str, Any]):
        breadcrumb_el = soup.find(lambda tag: any(kw in " ".join(tag.get("class", [])).lower() or kw in (tag.get("id", "") or "").lower() or kw in tag.get("role", "").lower() for kw in ["breadcrumb", "nav-breadcrumb"]))
        if not breadcrumb_el:
            breadcrumb_el = soup.find(lambda tag: tag.get("itemprop") == "breadcrumb")
            
        if breadcrumb_el:
            crumbs = [li.get_text(separator=" ", strip=True) for li in breadcrumb_el.find_all(["li", "span", "a"]) if li.get_text(separator=" ", strip=True)]
            crumbs = [c for c in crumbs if c not in (">", "/", "|", "home", "home page")]
            if crumbs:
                hierarchy = " > ".join(crumbs)
                if self._is_field_allowed("category"):
                    extracted.setdefault("category", crumbs[-1])
                if self._is_field_allowed("segment"):
                    extracted.setdefault("segment", hierarchy)
