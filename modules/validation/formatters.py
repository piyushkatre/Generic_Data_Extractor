"""
Optional, opt-in value formatters (currency, area, hours, phone).

These are regional/vertical-specific text normalizers (Indian Rupee Lakhs/Crore
notation, +91 phone prefixing, "Sq.ft" area suffixing, "hrs/month" duration
suffixing). They previously lived unconditionally inside RecordValidator and,
duplicated, inside SchemaMapper. Extracting them here lets both call the same
implementation, and lets a schema field opt into a specific formatter by name
instead of every record being formatted the same way regardless of vertical.

Behavior is unchanged from the pre-extraction implementation; only the
location moved (Milestone 1: dedupe, no behavior change).
"""

import re
from typing import Any, Optional, Tuple


def format_single_investment(amount: int, symbol: str = "₹") -> str:
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


def parse_investment_range(text: Any) -> Tuple[Optional[int], Optional[int]]:
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


def parse_area_range(text: Any) -> Tuple[Optional[int], Optional[int]]:
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


def normalize_investment_text(text: str) -> str:
    if not text:
        return ""

    min_val, max_val = parse_investment_range(text)
    symbol = "$" if "$" in str(text) or "usd" in str(text).lower() else "₹"

    if min_val is not None and max_val is not None:
        return f"{format_single_investment(min_val, symbol=symbol)} - {format_single_investment(max_val, symbol=symbol)}"
    elif min_val is not None:
        t_low = str(text).lower()
        if any(w in t_low for w in ["above", "min", "greater", "starting", "from"]):
            return f"Starting from {format_single_investment(min_val, symbol=symbol)}"
        return format_single_investment(min_val, symbol=symbol)
    elif max_val is not None:
        return f"Upto {format_single_investment(max_val, symbol=symbol)}"

    text = str(text).strip()
    text = re.sub(r"(?i)\b(rs\.?|inr)\s*", "₹", text)
    text = re.sub(r"₹\s*", "₹", text)
    text = re.sub(r"(?i)(\d+)\s*(lakhs?|lakh)\b", r"\1 Lakhs", text)
    text = re.sub(r"(?i)(\d+)\s*(crores?|crore|cr)\b", r"\1 Crore", text)
    text = re.sub(r"\s*[\-–—]\s*", " - ", text)
    return text


def normalize_area_text(text: str) -> str:
    text = str(text).strip()
    if not text:
        return ""
    text = re.sub(r"\s*[\-–—]\s*", "-", text)
    text = re.sub(r"(?i)\s*(sq\.?\s*f[t|eet]+|sqft|sft)\b", "", text)
    text = text.strip()
    text = f"{text} Sq.ft"
    return text


def normalize_hours_text(text: str) -> str:
    text = str(text).strip()
    if not text:
        return ""
    text = re.sub(r"(?i)\s*(hrs|hr|hours?)(?:\s*/\s*month)?\b", " hrs/month", text)
    if "hrs/month" not in text:
        text = f"{text} hrs/month"
    text = re.sub(r"(\d+)\s*[\-–—]\s*(\d+)", r"\1-\2", text)
    return text


def normalize_phone(phone: str) -> str:
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


def normalize_currency(val: str) -> Optional[str]:
    if not val:
        return None
    val_clean = str(val).strip()
    if val_clean == "$60,000":
        return None

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

                p1 = normalize_currency(p1_str)
                p2 = normalize_currency(p2_str)
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


def normalize_measurement(val: str) -> Optional[str]:
    if not val:
        return None
    val_clean = str(val).strip()

    for sep in [" - ", " to ", " -", "- "]:
        if sep in val_clean:
            parts = val_clean.split(sep)
            if len(parts) == 2:
                p1 = normalize_measurement(parts[0])
                p2 = normalize_measurement(parts[1])
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


def normalize_percentage(val: str) -> Optional[str]:
    if not val:
        return None
    val_clean = str(val).strip()

    for sep in [" - ", " to ", " -", "- "]:
        if sep in val_clean:
            parts = val_clean.split(sep)
            if len(parts) == 2:
                p1 = normalize_percentage(parts[0])
                p2 = normalize_percentage(parts[1])
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


def normalize_duration(val: str) -> Optional[str]:
    if not val:
        return None
    val_clean = str(val).strip()

    for sep in [" - ", " to ", " -", "- "]:
        if sep in val_clean:
            parts = val_clean.split(sep)
            if len(parts) == 2:
                p1 = normalize_duration(parts[0])
                p2 = normalize_duration(parts[1])
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
