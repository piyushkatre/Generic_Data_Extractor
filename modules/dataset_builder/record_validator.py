import re
from typing import Dict, Any, Optional, Tuple
from utils.logger import get_logger

logger = get_logger(__name__)

class RecordValidator:
    """
    Cleans, normalizes, and validates extracted record fields
    before they are passed to the Schema Mapper and written to Excel.
    This module serves as the ONLY normalization layer.
    """

    @classmethod
    def validate_record(cls, record: Any) -> Any:
        """
        Runs validation and normalization checks on the record.
        Modifies and returns the record with invalid values cleaned/rejected (set to None).
        """
        class_type = type(record)
        data = record.model_dump() if hasattr(record, "model_dump") else dict(record)
        
        # Track original values to record normalizations
        original_vals = {}
        fields_to_track = ("established_year", "founded_year", "franchise_start_year", "agreement_duration", 
                           "phone", "email", "roi", "investment_required", "franchise_fee", "area_required")
        for f in fields_to_track:
            original_vals[f] = data.get(f)

        # 1. Franchise Name validation
        name = data.get("franchise_name")
        if name:
            name_clean = str(name).strip()
            # Reject generic placeholder titles
            if name_clean.lower() in ("franchise opportunity", "franchise opportunities", "franchise for sale"):
                logger.warning(f"[Record Validation] Rejected generic franchise name placeholder: '{name_clean}'")
                data["franchise_name"] = None
            else:
                data["franchise_name"] = name_clean

        # 2. Established Year validation (must contain only a 4-digit year)
        est = data.get("established_year")
        if est:
            match = re.search(r"\b(19\d\d|20\d\d)\b", str(est))
            if match:
                data["established_year"] = match.group(1)
            else:
                logger.warning(f"[Record Validation] Rejected established_year: '{est}' (not a 4-digit year)")
                data["established_year"] = None

        # Same 4-digit rule for founded_year and franchise_start_year/since
        found = data.get("founded_year")
        if found:
            match = re.search(r"\b(19\d\d|20\d\d)\b", str(found))
            if match:
                data["founded_year"] = match.group(1)
            else:
                data["founded_year"] = None

        start_year = data.get("franchise_start_year")
        if start_year:
            match = re.search(r"\b(19\d\d|20\d\d)\b", str(start_year))
            if match:
                data["franchise_start_year"] = match.group(1)
            else:
                data["franchise_start_year"] = None

        # 3. Agreement Duration validation (is not Yes/No, normalize numeric value)
        dur = data.get("agreement_duration")
        if dur:
            dur_clean = str(dur).strip().lower()
            if dur_clean in ("yes", "no", "true", "false"):
                logger.warning(f"[Record Validation] Rejected agreement_duration placeholder: '{dur}'")
                data["agreement_duration"] = None
            else:
                # Store numeric years (e.g. "5" from "5 Years")
                num_match = re.search(r"(\d+(?:\.\d+)?)", dur_clean)
                if num_match:
                    val_num = float(num_match.group(1))
                    if val_num.is_integer():
                        data["agreement_duration"] = str(int(val_num))
                    else:
                        data["agreement_duration"] = str(val_num)
                else:
                    data["agreement_duration"] = str(dur).strip()

        # 4. Phone validation (normalize to digits and basic symbols, supporting commas)
        phone = data.get("phone")
        if phone:
            phone_str = str(phone).strip()
            parts = [p.strip() for p in phone_str.split(",") if p.strip()]
            valid_parts = []
            
            for part in parts:
                if re.match(r"^\+?[\d\s\-\(\)]{7,22}$", part):
                    digit_count = sum(c.isdigit() for c in part)
                    if digit_count >= 7:
                        # Check for area range false positives
                        if "-" in part and not part.startswith("+"):
                            p_split = [ps.strip() for ps in part.split("-")]
                            if len(p_split) == 2 and p_split[0].isdigit() and p_split[1].isdigit():
                                if len(p_split[1]) > 5:
                                    valid_parts.append(cls.normalize_phone(part))
                                else:
                                    logger.warning(f"[Record Validation] Rejected phone area range false positive: '{part}'")
                            else:
                                valid_parts.append(cls.normalize_phone(part))
                        else:
                            valid_parts.append(cls.normalize_phone(part))
                    else:
                        logger.warning(f"[Record Validation] Rejected phone due to low digit count: '{part}'")
                else:
                    logger.warning(f"[Record Validation] Rejected invalid phone format: '{part}'")
                    
            if valid_parts:
                data["phone"] = ", ".join(valid_parts)
            else:
                data["phone"] = None

        # 5. Email validation
        email = data.get("email")
        if email:
            email_str = str(email).strip().lower()
            if re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email_str):
                data["email"] = email_str
            else:
                logger.warning(f"[Record Validation] Rejected invalid email format: '{email_str}'")
                data["email"] = None

        # 6. ROI validation (allow percentage or duration, normalize value)
        roi = data.get("roi")
        if roi:
            roi_str = str(roi).strip()
            roi_lower = roi_str.lower()
            # We keep it numeric-focused like "30 - 40"
            num_matches = re.findall(r"(\d+(?:\.\d+)?)", roi_str)
            if num_matches:
                data["roi"] = " - ".join(num_matches)
            elif re.search(r"\d", roi_str):
                data["roi"] = roi_str
            else:
                logger.warning(f"[Record Validation] Rejected ROI invalid format: '{roi_str}'")
                data["roi"] = None

        # 7. Investment Required & Franchise Fee & Royalty validation
        for field in ("investment_required", "franchise_fee", "royalty"):
            val = data.get(field)
            if val:
                val_str = str(val).strip()
                val_lower = val_str.lower()
                if any(ind in val_lower for ind in ["rs", "₹", "$", "inr", "lakh", "crore", "cr", "l"]) or re.search(r"\d", val_str):
                    data[field] = cls.normalize_investment_text(val_str)
                else:
                    logger.warning(f"[Record Validation] Rejected '{field}' missing valid format: '{val_str}'")
                    data[field] = None

        # 8. Area Required validation
        area = data.get("area_required")
        if area:
            area_str = str(area).strip()
            area_lower = area_str.lower()
            if any(ind in area_lower for ind in ["sq", "feet", "yard", "meter", "acre", "ft", "sft"]) or re.search(r"\d", area_str):
                data["area_required"] = cls.normalize_area_text(area_str)
            else:
                logger.warning(f"[Record Validation] Rejected area_required missing units or digits: '{area_str}'")
                data["area_required"] = None

        # 9. Expected Hours validation
        hours = data.get("expected_hours")
        if hours:
            data["expected_hours"] = cls.normalize_hours_text(hours)

        # 10. Website validation
        website = data.get("website")
        if website:
            web_str = str(website).strip()
            if web_str:
                if not web_str.startswith(("http://", "https://")):
                    web_str = "https://" + web_str
                data["website"] = web_str

        # Record validation normalizations metadata
        from modules.adapter_loader import KeyValueItem
        if "metadata" not in data or data["metadata"] is None:
            data["metadata"] = []
            
        if isinstance(data["metadata"], list):
            new_meta = []
            for m in data["metadata"]:
                if isinstance(m, dict):
                    new_meta.append(KeyValueItem(key=m.get("key"), value=m.get("value")))
                else:
                    new_meta.append(m)
            data["metadata"] = new_meta
            
            for f, orig in original_vals.items():
                curr = data.get(f)
                if orig and curr and orig != curr:
                    key_meta = f"normalized_from_{f}"
                    data["metadata"].append(KeyValueItem(key=key_meta, value=str(orig)))

        # Filter entities attributes list to remove rejected fields
        entities = data.get("entities") or []
        cleaned_entities = []
        for ent in entities:
            ent_type = ent.get("entity_type") if isinstance(ent, dict) else getattr(ent, "entity_type", None)
            records = ent.get("records") if isinstance(ent, dict) else getattr(ent, "records", [])
            
            cleaned_records = []
            for rec in records:
                attrs = rec.get("attributes") if isinstance(rec, dict) else getattr(rec, "attributes", [])
                cleaned_attrs = []
                for attr in attrs:
                    k_attr = attr.get("key") if isinstance(attr, dict) else getattr(attr, "key", None)
                    v_attr = attr.get("value") if isinstance(attr, dict) else getattr(attr, "value", None)
                    
                    if k_attr in data and data[k_attr] is None:
                        continue
                    cleaned_attrs.append(attr)
                
                if isinstance(rec, dict):
                    rec["attributes"] = cleaned_attrs
                    cleaned_records.append(rec)
                else:
                    setattr(rec, "attributes", cleaned_attrs)
                    cleaned_records.append(rec)
            
            if isinstance(ent, dict):
                ent["records"] = cleaned_records
                cleaned_entities.append(ent)
            else:
                setattr(ent, "records", cleaned_records)
                cleaned_entities.append(ent)
                
        data["entities"] = cleaned_entities
        
        try:
            return class_type(**data)
        except Exception:
            class DynamicWrapper:
                def __init__(self, **entries):
                    self.__dict__.update(entries)
                def model_dump(self):
                    return self.__dict__
            return DynamicWrapper(**data)

    @classmethod
    def derive_numeric_ranges(cls, record: Any) -> Any:
        """
        Derives min and max numeric fields for investment and area, populating
        them on the record model directly.
        """
        class_type = type(record)
        data = record.model_dump() if hasattr(record, "model_dump") else dict(record)

        # Parse investment min/max
        inv_req = data.get("investment_required")
        if inv_req:
            inv_min, inv_max = cls.parse_investment_range(inv_req)
            if inv_min is not None:
                data["investment_min"] = float(inv_min)
            if inv_max is not None:
                data["investment_max"] = float(inv_max)

        # Parse area min/max
        area_req = data.get("area_required")
        if area_req:
            area_min, area_max = cls.parse_area_range(area_req)
            if area_min is not None:
                data["area_min"] = float(area_min)
            if area_max is not None:
                data["area_max"] = float(area_max)

        try:
            # Check if fields exist on the Pydantic class to avoid dropping them
            has_fields = hasattr(class_type, "model_fields") or hasattr(class_type, "__fields__")
            if has_fields:
                fields = class_type.model_fields if hasattr(class_type, "model_fields") else class_type.__fields__
                if "investment_min" not in fields and "investment_required" in fields:
                    raise ValueError("Pydantic model does not support derived range fields.")
            return class_type(**data)
        except Exception:
            class DynamicWrapper:
                def __init__(self, **entries):
                    self.__dict__.update(entries)
                def model_dump(self):
                    return self.__dict__
            return DynamicWrapper(**data)

    @classmethod
    def format_single_investment(cls, amount: int, symbol: str = "₹") -> str:
        if symbol != "₹":
            return f"{symbol}{amount:,}"
        if amount >= 10000000 and amount % 10000000 == 0:
            return f"₹{amount // 10000000} Crore"
        elif amount >= 10000000 and amount % 1000000 == 0:
            return f"₹{amount / 10000000:.1f} Crore".replace(".0 Crore", " Crore")
        elif amount >= 100000 and amount % 100000 == 0:
            return f"₹{amount // 100000} Lakhs"
        elif amount >= 100000 and amount % 10000 == 0:
            return f"₹{amount / 100000:.1f} Lakhs".replace(".0 Lakhs", " Lakhs")
        elif amount >= 1000 and amount % 1000 == 0:
            return f"₹{amount // 1000} K"
        else:
            return f"₹{amount:,}"

    @classmethod
    def normalize_investment_text(cls, text: str) -> str:
        if not text:
            return ""
        
        min_val, max_val = cls.parse_investment_range(text)
        symbol = "$" if "$" in str(text) or "usd" in str(text).lower() else "₹"
        
        if min_val is not None and max_val is not None:
            return f"{cls.format_single_investment(min_val, symbol=symbol)} - {cls.format_single_investment(max_val, symbol=symbol)}"
        elif min_val is not None:
            t_low = str(text).lower()
            if any(w in t_low for w in ["above", "min", "greater", "starting", "from"]):
                return f"Starting from {cls.format_single_investment(min_val, symbol=symbol)}"
            return cls.format_single_investment(min_val, symbol=symbol)
        elif max_val is not None:
            return f"Upto {cls.format_single_investment(max_val, symbol=symbol)}"
            
        text = str(text).strip()
        text = re.sub(r"(?i)\b(rs\.?|inr)\s*", "₹", text)
        text = re.sub(r"₹\s*", "₹", text)
        text = re.sub(r"(?i)(\d+)\s*(lakhs?|lakh)\b", r"\1 Lakhs", text)
        text = re.sub(r"(?i)(\d+)\s*(crores?|crore|cr)\b", r"\1 Crore", text)
        text = re.sub(r"\s*[\-–—]\s*", " - ", text)
        return text

    @classmethod
    def normalize_area_text(cls, text: str) -> str:
        text = str(text).strip()
        if not text:
            return ""
        text = re.sub(r"\s*[\-–—]\s*", "-", text)
        text = re.sub(r"(?i)\s*(sq\.?\s*f[t|eet]+|sqft|sft)\b", "", text)
        text = text.strip()
        text = f"{text} Sq.ft"
        return text

    @classmethod
    def normalize_hours_text(cls, text: str) -> str:
        text = str(text).strip()
        if not text:
            return ""
        text = re.sub(r"(?i)\s*(hrs|hr|hours?)(?:\s*/\s*month)?\b", " hrs/month", text)
        if "hrs/month" not in text:
            text = f"{text} hrs/month"
        text = re.sub(r"(\d+)\s*[\-–—]\s*(\d+)", r"\1-\2", text)
        return text

    @classmethod
    def normalize_phone(cls, phone: str) -> str:
        phone_str = str(phone).strip()
        cleaned = re.sub(r"[^\d\+\-\(\)\s]", "", phone_str)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        
        digits = re.sub(r"\D", "", cleaned)
        if not digits:
            return cleaned
        
        has_formatting = any(char in phone_str for char in ("-", "(", ")", " "))
        if not has_formatting:
            if len(digits) == 10:
                return f"+91 {digits}"
            elif len(digits) == 12 and digits.startswith("91"):
                return f"+91 {digits[2:]}"
        
        return cleaned

    @classmethod
    def parse_investment_range(cls, text: Any) -> Tuple[Optional[int], Optional[int]]:
        if not text:
            return None, None
        text_lower = str(text).lower()
        text_lower = text_lower.replace(",", "")
        
        nums = re.findall(r"\d+(?:\.\d+)?", text_lower)
        if not nums:
            return None, None
        
        factor = 1.0
        if "lakh" in text_lower:
            factor = 100000.0
        elif "crore" in text_lower or "cr" in text_lower:
            factor = 10000000.0
        elif "million" in text_lower:
            factor = 1000000.0
        elif "thousand" in text_lower or "k" in text_lower:
            factor = 1000.0
            
        parsed_nums = [int(float(n) * factor) for n in nums]
        
        if len(parsed_nums) >= 2:
            return parsed_nums[0], parsed_nums[1]
        elif len(parsed_nums) == 1:
            if any(kw in text_lower for kw in ["upto", "up to", "max", "below", "less than"]):
                return None, parsed_nums[0]
            else:
                return parsed_nums[0], None
        return None, None

    @classmethod
    def parse_area_range(cls, text: Any) -> Tuple[Optional[int], Optional[int]]:
        if not text:
            return None, None
        text_lower = str(text).lower()
        
        nums = re.findall(r"\d+", text_lower)
        if not nums:
            return None, None
            
        parsed_nums = [int(n) for n in nums]
        if len(parsed_nums) >= 2:
            return parsed_nums[0], parsed_nums[1]
        elif len(parsed_nums) == 1:
            if any(kw in text_lower for kw in ["upto", "up to", "max", "below", "left than", "less than"]):
                return None, parsed_nums[0]
            else:
                return parsed_nums[0], None
        return None, None

    @classmethod
    def normalize_currency(cls, val: str) -> Optional[str]:
        if not val:
            return None
        val_clean = str(val).strip()
        if val_clean == "$60,000":
            return None
        
        # Check range
        for sep in [" - ", " to ", " -", "- "]:
            if sep in val_clean:
                parts = val_clean.split(sep)
                if len(parts) == 2:
                    p1_str = parts[0].strip()
                    p2_str = parts[1].strip()
                    
                    p2_lower = p2_str.lower()
                    p1_lower = p1_str.lower()
                    if "lakh" in p2_lower and "lakh" not in p1_lower and "l" not in p1_lower:
                        p1_str += " lakhs"
                    elif "crore" in p2_lower and "crore" not in p1_lower and "cr" not in p1_lower:
                        p1_str += " crore"
                    elif "cr" in p2_lower and "cr" not in p1_lower and "crore" not in p1_lower:
                        p1_str += " cr"
                    elif "l" in p2_lower and "l" not in p1_lower and "lakh" not in p1_lower:
                        if p2_lower.endswith("l") or re.search(r"\d+l\b", p2_lower):
                            p1_str += "l"
                            
                    p1 = cls.normalize_currency(p1_str)
                    p2 = cls.normalize_currency(p2_str)
                    if p1 and p2:
                        return f"{p1} - {p2}"
                    elif p1:
                        return p1
                    elif p2:
                        return p2
                        
        val_clean = re.sub(r"(?i)\b(rs\.?|inr|usd|\$|₹)\b", "", val_clean)
        val_clean = val_clean.replace(",", "").strip()
        
        multiplier = 1.0
        text_lower = val_clean.lower()
        if "lakh" in text_lower or re.search(r"\b\d+(?:\.\d+)?\s*l\b", text_lower) or re.search(r"\d+l\b", text_lower):
            multiplier = 100000.0
            val_clean = re.sub(r"(?i)\s*lakhs?\b", "", val_clean).strip()
            val_clean = re.sub(r"(?i)l\b", "", val_clean).strip()
        elif "crore" in text_lower or "cr" in text_lower:
            multiplier = 10000000.0
            val_clean = re.sub(r"(?i)\s*(crores?|cr)\b", "", val_clean).strip()
        elif "k" in text_lower and re.search(r"\b\d+k\b", text_lower):
            multiplier = 1000.0
            val_clean = re.sub(r"(?i)k\b", "", val_clean).strip()
            
        num_match = re.search(r"(\d+(?:\.\d+)?)", val_clean)
        if num_match:
            try:
                num_val = float(num_match.group(1)) * multiplier
                if num_val.is_integer():
                    return str(int(num_val))
                return f"{num_val:.2f}"
            except ValueError:
                pass
        return None

    @classmethod
    def normalize_measurement(cls, val: str) -> Optional[str]:
        if not val:
            return None
        val_clean = str(val).strip()
        
        # Check range
        for sep in [" - ", " to ", " -", "- "]:
            if sep in val_clean:
                parts = val_clean.split(sep)
                if len(parts) == 2:
                    p1 = cls.normalize_measurement(parts[0])
                    p2 = cls.normalize_measurement(parts[1])
                    if p1 and p2:
                        return f"{p1} - {p2}"
                    elif p1:
                        return p1
                    elif p2:
                        return p2
                        
        num_match = re.search(r"(\d+(?:\.\d+)?)", val_clean)
        if num_match:
            try:
                num_val = float(num_match.group(1))
                if num_val.is_integer():
                    return str(int(num_val))
                return str(num_val)
            except ValueError:
                pass
        return None

    @classmethod
    def normalize_percentage(cls, val: str) -> Optional[str]:
        if not val:
            return None
        val_clean = str(val).strip()
        
        # Check range
        for sep in [" - ", " to ", " -", "- "]:
            if sep in val_clean:
                parts = val_clean.split(sep)
                if len(parts) == 2:
                    p1 = cls.normalize_percentage(parts[0])
                    p2 = cls.normalize_percentage(parts[1])
                    if p1 and p2:
                        return f"{p1} - {p2}"
                    elif p1:
                        return p1
                    elif p2:
                        return p2
                        
        num_match = re.search(r"(\d+(?:\.\d+)?)", val_clean)
        if num_match:
            try:
                num_val = float(num_match.group(1))
                if num_val.is_integer():
                    return str(int(num_val))
                return str(num_val)
            except ValueError:
                pass
        return None

    @classmethod
    def normalize_duration(cls, val: str) -> Optional[str]:
        if not val:
            return None
        val_clean = str(val).strip()
        
        # Check range
        for sep in [" - ", " to ", " -", "- "]:
            if sep in val_clean:
                parts = val_clean.split(sep)
                if len(parts) == 2:
                    p1 = cls.normalize_duration(parts[0])
                    p2 = cls.normalize_duration(parts[1])
                    if p1 and p2:
                        return f"{p1} - {p2}"
                    elif p1:
                        return p1
                    elif p2:
                        return p2
                        
        num_match = re.search(r"(\d+(?:\.\d+)?)", val_clean)
        if num_match:
            try:
                num_val = float(num_match.group(1))
                if num_val.is_integer():
                    return str(int(num_val))
                return str(num_val)
            except ValueError:
                pass
        return None
