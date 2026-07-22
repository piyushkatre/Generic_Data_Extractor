import re
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup

class DOMChecker:
    """
    Scans the filtered DOM text using advanced regex patterns and semantic normalizations
    to detect actual values, matching numbers, and identify potential hallucinations or misses.
    """

    FIELD_KEYWORDS: Dict[str, List[str]] = {
        "franchise_name": ["franchise", "brand", "company", "opportunity"],
        "brand": ["brand", "trademark", "name"],
        "industry": ["industry", "sector", "business type"],
        "category": ["category", "segment", "type"],
        "description": ["description", "overview", "summary"],
        "about": ["about", "established", "founded", "history"],
        "business_model": ["model", "business model", "franchise model", "foce", "foco"],
        "investment_required": ["investment", "capital", "cost", "lakhs", "crore", "inr", "investment required", "fees"],
        "franchise_fee": ["fee", "franchise fee", "joining fee", "signup fee"],
        "royalty": ["royalty", "commission", "sharing", "percent", "%", "royalty/commission"],
        "roi": ["roi", "return", "return on investment", "profitability"],
        "payback_period": ["payback", "payback period", "break-even", "breakeven", "months", "years"],
        "area_required": ["area", "space", "sq ft", "square feet", "size", "floor", "area required"],
        "store_size": ["store size", "outlet size", "dimensions"],
        "products": ["products", "items", "goods", "menu"],
        "services": ["services", "offerings", "activities"],
        "training": ["training", "induction", "program", "manual"],
        "marketing_support": ["marketing", "advertising", "promo", "branding", "support"],
        "business_support": ["support", "setup", "assistance", "operations"],
        "contact_person": ["contact person", "spokesperson", "representative", "manager", "contact"],
        "phone": ["phone", "mobile", "contact number", "call", "tel", "whatsapp"],
        "email": ["email", "mail", "contact us"],
        "website": ["website", "www.", "url", "domain", "visit"],
        "address": ["address", "location", "office", "headquarters", "street"],
        "city": ["city", "town"],
        "state": ["state", "province"],
        "country": ["country", "nation"],
        "facebook": ["facebook.com", "facebook"],
        "instagram": ["instagram.com", "instagram"],
        "linkedin": ["linkedin.com", "linkedin"],
        "twitter": ["twitter.com", "twitter", "x.com"],
        "youtube": ["youtube.com", "youtube"],
        "faq": ["faq", "frequently asked", "questions"],
        "images": ["image", "gallery", "photo", "banner"],
        "documents": ["brochure", "pdf", "manual", "document", "download"],
        "segment": ["segment", "niche", "specialization"],
        "number_of_outlets": ["outlets", "stores", "number of outlets", "units", "network"],
        "number_of_employees": ["employees", "staff", "team", "people"],
        "franchise_since": ["since", "franchising commenced", "franchise start"],
        "logo_url": ["logo", "brand image", "logo url"]
    }

    def __init__(self, html_content: str):
        self.html_content = html_content or ""
        self.soup = BeautifulSoup(self.html_content, "html.parser")
        
        # Get raw visible text
        raw_text = self.soup.get_text(separator=" ")
        self.dom_text = re.sub(r"\s+", " ", raw_text).lower()

        # Helper to normalize strings for spaces, hyphens, casing, line breaks, and currency
        def normalize_string(s: str) -> str:
            s = s.lower().replace("\n", " ").replace("\r", " ")
            s = re.sub(r"(?:₹|\$|rs\.?|inr|usd|lakhs?|crores?|cr|thousand|million|k)", "", s)
            s = re.sub(r"\s+", " ", s).strip()
            s = s.replace("-", "").replace(" ", "")
            return s

        self.dom_text_norm = normalize_string(self.dom_text)

        # Build list of DOM digits and anchor URLs
        self.dom_digits = "".join(re.findall(r"\d", self.dom_text))
        
        # Extract link hrefs
        self.dom_urls = []
        for tag in self.soup.find_all("a", href=True):
            href = tag["href"].strip().lower()
            if href and not href.startswith(("#", "javascript:", "tel:", "mailto:")):
                self.dom_urls.append(href)

        # Extract doc hrefs
        self.dom_docs = []
        for tag in self.soup.find_all("a", href=True):
            href = tag["href"].strip().lower()
            if href.endswith((".pdf", ".doc", ".docx", ".zip")):
                self.dom_docs.append(href)

        # Extract images
        self.dom_images = []
        for tag in self.soup.find_all("img", src=True):
            src = tag["src"].strip().lower()
            if src:
                self.dom_images.append(src)

    # ── Value Existence Checks (Likely Missed - Task 3) ───────────────────────

    def has_actual_value_in_dom(self, field_name: str) -> bool:
        """
        Determines if an actual value (pattern-wise) exists in the DOM text
        rather than relying purely on keywords matching.
        """
        # First, ensure base keywords exist
        has_keywords = self.has_keyword_match(field_name)

        if field_name == "email":
            # Search for actual email pattern in text
            pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
            emails = re.findall(pattern, self.dom_text)
            return len(emails) > 0

        elif field_name == "phone":
            # Search for sequences of numbers of length >= 8
            # E.g. +91-98444-43200
            pattern = r"\b\+?\d[\d\s\-\(\)]{6,14}\d\b"
            phones = re.findall(pattern, self.dom_text)
            # Filter out sequences with less than 6 digits
            valid_phones = [p for p in phones if len(re.sub(r"\D", "", p)) >= 10]
            return len(valid_phones) > 0

        elif field_name in ("website", "facebook", "instagram", "linkedin", "youtube", "twitter"):
            # Check anchors or text domains
            if self.dom_urls:
                # If checking specific social networks, verify domain shapes
                if field_name == "facebook":
                    return any("facebook.com" in url for url in self.dom_urls)
                elif field_name == "instagram":
                    return any("instagram.com" in url for url in self.dom_urls)
                elif field_name == "linkedin":
                    return any("linkedin.com" in url for url in self.dom_urls)
                elif field_name == "twitter":
                    return any("twitter.com" in url or "x.com" in url for url in self.dom_urls)
                elif field_name == "youtube":
                    return any("youtube.com" in url or "youtu.be" in url for url in self.dom_urls)
                else:
                    # website
                    # Check if there are anchors other than social sites
                    non_social = [url for url in self.dom_urls if not any(social in url for social in ["facebook", "instagram", "linkedin", "youtube", "twitter", "pinterest", "x.com"])]
                    if non_social:
                        return True
            
            # Substring match keywords shape in text
            pattern = r"(?:https?://)?(?:www\.)?[a-zA-Z0-9-]+\.[a-zA-Z]{2,4}"
            urls = re.findall(pattern, self.dom_text)
            return len(urls) > 0

        elif field_name in ("investment_required", "franchise_fee"):
            # Needs keyword + numeric currency pattern
            if not has_keywords:
                return False
            # Find numbers associated with Lakhs, Cr, Rupees, $, Rs.
            pattern = r"(?:₹|\$|rs\.?|inr|usd|lakhs?|crores?|cr|thousand|million|k)?\s*\d+(?:\.\d+)?\s*(?:lakhs?|crores?|cr|thousand|million|k)?"
            matches = re.findall(pattern, self.dom_text)
            return len(matches) > 0

        elif field_name == "royalty":
            if not has_keywords:
                return False
            # Needs % royalty sign or keywords near numbers
            pattern = r"\d+(?:\.\d+)?\s*%"
            percent_matches = re.findall(pattern, self.dom_text)
            return len(percent_matches) > 0 or "percent" in self.dom_text

        elif field_name == "roi":
            if not has_keywords:
                return False
            # Needs numeric ROI or percentage
            pattern = r"\d+(?:\.\d+)?\s*%"
            return len(re.findall(pattern, self.dom_text)) > 0 or any(kw in self.dom_text for kw in ["return on investment", "payback"])

        elif field_name == "area_required":
            if not has_keywords:
                return False
            # Needs spatial unit pattern and dimensions
            pattern = r"\d+(?:\s*-\s*\d+)?\s*(?:sq\.?\s*ft\.?|square\s*feet|sq\.?\s*yards|acres?|carpet|meters?)"
            matches = re.findall(pattern, self.dom_text)
            return len(matches) > 0

        # Fallback to general keyword match
        return has_keywords

    def has_keyword_match(self, field_name: str) -> bool:
        keywords = self.FIELD_KEYWORDS.get(field_name, [])
        if not keywords:
            return False
        return any(kw in self.dom_text for kw in keywords)

    # ── Semantic DOM Matching (Task 1 & Task 4) ──────────────────────────────

    def is_value_in_dom(self, value: Any, field_name: Optional[str] = None) -> bool:
        """
        Performs semantic match checking on the DOM.
        Converts both elements to normalized shapes, resolving formatting issues.
        """
        if value is None:
            return True

        if isinstance(value, list):
            if not value:
                return True
            return any(self.is_value_in_dom(item, field_name) for item in value)

        if isinstance(value, dict):
            return any(self.is_value_in_dom(v, field_name) for v in value.values())

        val_str = str(value).strip()
        if not val_str:
            return True

        val_lower = val_str.lower()
        
        # Duration parser helper
        def parse_duration_to_months(s: str) -> Optional[float]:
            s_low = s.lower().strip()
            num_match = re.search(r"(\d+(?:\.\d+)?)", s_low)
            if not num_match:
                return None
            val = float(num_match.group(1))
            if "year" in s_low or "yr" in s_low:
                return val * 12.0
            elif "month" in s_low or "mo" in s_low:
                return val
            elif "day" in s_low:
                return val / 30.0
            return None

        # 1. Phone number check
        if field_name == "phone":
            digits_only = re.sub(r"\D", "", val_lower)
            if len(digits_only) < 7:
                return False
            if digits_only in self.dom_digits:
                return True
            if digits_only.startswith("91") and len(digits_only) > 10:
                if digits_only[2:] in self.dom_digits:
                    return True
            return False

        # 2. Email check
        if field_name == "email" or "@" in val_lower:
            email_pattern = re.escape(val_lower)
            return bool(re.search(email_pattern, self.dom_text))

        # 3. Website & Social links check
        if field_name in ("website", "facebook", "instagram", "linkedin", "youtube", "twitter", "whatsapp_link") or "url" in str(field_name):
            clean_url = val_lower.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            if not clean_url:
                return True
            clean_dom_urls = [u.replace("https://", "").replace("http://", "").replace("www.", "").strip("/") for u in self.dom_urls]
            if clean_url in clean_dom_urls or any(clean_url in u for u in clean_dom_urls) or clean_url in self.dom_text:
                return True
            return False

        # 4. Images & Logos check
        if field_name in ("images", "logo", "logo_url"):
            clean_img = val_lower.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            if not clean_img:
                return True
            if any(clean_img in img for img in self.dom_images) or clean_img in self.dom_text:
                return True
            return False

        # 5. Documents & Brochures check
        if field_name in ("brochures", "documents"):
            clean_doc = val_lower.replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
            if not clean_doc:
                return True
            if any(clean_doc in doc for doc in self.dom_docs) or clean_doc in self.dom_text:
                return True
            return False

        # 6. Years check
        if field_name in ("founded_year", "franchise_start_year", "operations_commenced", "established_year", "franchise_since"):
            years = re.findall(r"\b\d{4}\b", val_lower)
            if years:
                return any(y in self.dom_text for y in years)
            digits = re.findall(r"\d+", val_lower)
            if digits:
                return any(d in self.dom_text for d in digits)

        # 7. ROI & Payback check (with duration equivalence support)
        if field_name in ("roi", "payback_period") or "duration" in str(field_name):
            val_months = parse_duration_to_months(val_lower)
            if val_months is not None:
                dom_durations = re.findall(r"(\d+(?:\.\d+)?\s*(?:month|year|day|yr|mo|s)\b)", self.dom_text)
                for dom_dur in dom_durations:
                    dom_m = parse_duration_to_months(dom_dur)
                    if dom_m is not None and abs(dom_m - val_months) < 0.1:
                        return True
            digits = re.findall(r"\d+", val_lower)
            if digits:
                if any(d in self.dom_text for d in digits):
                    return True
            return any(w in self.dom_text for w in val_lower.split() if len(w) > 3)

        # 7b. Area / Measurement check
        if field_name in ("area_required", "area_min", "area_max", "store_size"):
            digits = re.findall(r"\d+", val_lower)
            if digits:
                val_digits = "".join(digits)
                if val_digits in self.dom_digits:
                    return True

        # 7c. Address normalization check
        if field_name == "address":
            clean_addr = re.sub(r"\W+", "", val_lower)
            clean_dom_text = re.sub(r"\W+", "", self.dom_text)
            if clean_addr in clean_dom_text:
                return True

        # 8. Skip generic/empty terms
        if val_lower in ("yes", "no", "true", "false", "n/a", "none", "null") or (len(val_lower) < 3 and val_lower.isalpha()):
            return True

        # 9. String Normalization check
        def normalize_string(s: str) -> str:
            s = s.lower().replace("\n", " ").replace("\r", " ")
            s = re.sub(r"(?:₹|\$|rs\.?|inr|usd|lakhs?|crores?|cr|thousand|million|k)", "", s)
            s = re.sub(r"\s+", " ", s).strip()
            s = s.replace("-", "").replace(" ", "")
            return s

        val_norm = normalize_string(val_lower)
        if val_norm and val_norm in self.dom_text_norm:
            return True

        # 10. Digit extraction comparison
        digits = re.findall(r"\d+", val_lower)
        if digits:
            val_digits = "".join(digits)
            if val_digits in self.dom_digits:
                return True
            if not any(d in self.dom_text for d in digits):
                return False

        # 11. Word overlap fallback
        words = re.findall(r"[a-z0-9]{3,}", val_lower)
        words = [w for w in words if w not in ["lakh", "lakhs", "crore", "crores", "cr", "percent", "rs", "inr", "usd", "franchise"]]
        if not words:
            return True

        matches = [word for word in words if word in self.dom_text]
        return len(matches) > 0
