import re
from typing import Dict, Any, Optional, Tuple
from utils.logger import get_logger
from modules.validation import formatters

logger = get_logger(__name__)

_NESTED_LIST_FIELDS = ("entities", "faq", "additional_information", "metadata")


class DynamicWrapper:
    """
    Duck-typed fallback used when a record can't be reconstructed as its
    original Pydantic class (e.g. the model doesn't declare a field this
    method wants to add, such as investment_min on a schema that never
    declared it). Preserves nested list-of-model fields (entities, faq,
    additional_information, metadata) as their original objects rather than
    the plain dicts a flattened model_dump() would produce - callers
    downstream (SchemaMapper, PrimaryEntityDetector) do attribute access on
    those nested items and would otherwise break.
    """
    def __init__(self, **entries):
        self.__dict__.update(entries)

    def model_dump(self):
        return self.__dict__


def _reconstruct_record(class_type: type, data: Dict[str, Any], original_record: Any) -> Any:
    """
    Rebuilds a record as `class_type(**data)`, falling back to a
    DynamicWrapper (with nested list fields restored from the original
    record) if the class doesn't accept `data` as-is.
    """
    try:
        return class_type(**data)
    except Exception:
        for nested_field in _NESTED_LIST_FIELDS:
            if hasattr(original_record, nested_field):
                data[nested_field] = getattr(original_record, nested_field)
        return DynamicWrapper(**data)

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

        return _reconstruct_record(class_type, data, record)

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

        # If the model doesn't declare investment_min/area_min etc. (a schema
        # simply didn't ask for them), fall back to a DynamicWrapper that
        # still carries the derived values as loose attributes, but with
        # nested list fields (entities/faq/...) restored from the original
        # record so downstream attribute access on them keeps working.
        has_fields = hasattr(class_type, "model_fields") or hasattr(class_type, "__fields__")
        if has_fields:
            fields = class_type.model_fields if hasattr(class_type, "model_fields") else class_type.__fields__
            if "investment_min" not in fields and "investment_required" in fields:
                return DynamicWrapper(**{**data, **{f: getattr(record, f) for f in _NESTED_LIST_FIELDS if hasattr(record, f)}})

        return _reconstruct_record(class_type, data, record)

    # ------------------------------------------------------------------
    # The methods below delegate to modules/validation/formatters.py.
    # They are kept here, with identical names/signatures, purely for
    # backward compatibility with existing callers (including tests) that
    # invoke them as RecordValidator classmethods. The implementation lives
    # in one place now instead of being duplicated across this class and
    # SchemaMapper.
    # ------------------------------------------------------------------

    @classmethod
    def format_single_investment(cls, amount: int, symbol: str = "₹") -> str:
        return formatters.format_single_investment(amount, symbol=symbol)

    @classmethod
    def normalize_investment_text(cls, text: str) -> str:
        return formatters.normalize_investment_text(text)

    @classmethod
    def normalize_area_text(cls, text: str) -> str:
        return formatters.normalize_area_text(text)

    @classmethod
    def normalize_hours_text(cls, text: str) -> str:
        return formatters.normalize_hours_text(text)

    @classmethod
    def normalize_phone(cls, phone: str) -> str:
        return formatters.normalize_phone(phone)

    @classmethod
    def parse_investment_range(cls, text: Any) -> Tuple[Optional[int], Optional[int]]:
        return formatters.parse_investment_range(text)

    @classmethod
    def parse_area_range(cls, text: Any) -> Tuple[Optional[int], Optional[int]]:
        return formatters.parse_area_range(text)

    @classmethod
    def normalize_currency(cls, val: str) -> Optional[str]:
        return formatters.normalize_currency(val)

    @classmethod
    def normalize_measurement(cls, val: str) -> Optional[str]:
        return formatters.normalize_measurement(val)

    @classmethod
    def normalize_percentage(cls, val: str) -> Optional[str]:
        return formatters.normalize_percentage(val)

    @classmethod
    def normalize_duration(cls, val: str) -> Optional[str]:
        return formatters.normalize_duration(val)
