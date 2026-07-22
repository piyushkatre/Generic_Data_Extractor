import re
from typing import List, Any

class OfflineValidator:
    """
    Offline data quality validation checks for specific franchise fields.
    """

    @staticmethod
    def validate_email(email: Any) -> List[str]:
        warnings = []
        if not email:
            return warnings
        
        email_clean = str(email).strip()
        # Standard email regex
        pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
        if not re.match(pattern, email_clean):
            warnings.append(f"Invalid email format: '{email}'")
        return warnings

    @staticmethod
    def validate_phone(phone: Any) -> List[str]:
        warnings = []
        if not phone:
            return warnings
            
        phone_clean = str(phone).strip()
        # Strip common formatting chars to evaluate substance
        digits = re.sub(r"\D", "", phone_clean)
        
        # Phone regex allowing +, spaces, hyphens, parenthesis, and extension annotations
        pattern = r"^[\+\d\s\-\(\)]*(?:ext|extension|Ext)?\.?\s*\d*$"
        
        if len(digits) < 7 or len(digits) > 15:
            warnings.append(f"Phone number digit count is unusual (expected 7-15 digits): '{phone}'")
        elif not re.match(pattern, phone_clean):
            warnings.append(f"Phone number contains invalid formatting characters: '{phone}'")
        return warnings

    @staticmethod
    def validate_url(url: Any, field_name: str = "website") -> List[str]:
        warnings = []
        if not url:
            return warnings
            
        url_clean = str(url).strip()
        # Basic URL matching protocol + domain structure
        pattern = r"^(https?://)?([a-zA-Z0-9-]+\.)+[a-zA-Z0-9-]+(/.*)?$"
        if not re.match(pattern, url_clean):
            warnings.append(f"Invalid URL structure for field '{field_name}': '{url}'")
        return warnings

    @staticmethod
    def validate_investment(val: Any) -> List[str]:
        warnings = []
        if not val:
            return warnings
            
        val_str = str(val).strip()
        # Investment required should contain numbers and currency indicators
        has_number = any(char.isdigit() for char in val_str)
        if not has_number:
            warnings.append(f"Investment value lacks numeric figures: '{val}'")
            return warnings
            
        # Skip unit/currency indicator warning if purely numeric or numeric range
        clean_norm_test = re.sub(r"[\d\s\-\.\,\:]", "", val_str)
        if not clean_norm_test:
            return warnings
            
        # Currency/Amount markers
        pattern = r"(?:₹|\$|rs\.?|inr|usd|lakhs?|crores?|cr|thousand|million|k)"
        if not re.search(pattern, val_str.lower()):
            warnings.append(f"Investment value lacks currency symbols or unit indicators (e.g. ₹, $, Lakhs): '{val}'")
        return warnings

    @staticmethod
    def validate_roi(val: Any) -> List[str]:
        warnings = []
        if not val:
            return warnings
            
        val_str = str(val).strip()
        # ROI validation (percentage or payback keywords)
        has_number = any(char.isdigit() for char in val_str)
        if not has_number:
            warnings.append(f"ROI value lacks numeric figures: '{val}'")
            return warnings

        # Skip indicator warning if purely numeric or numeric range
        clean_norm_test = re.sub(r"[\d\s\-\.\,\:]", "", val_str)
        if not clean_norm_test:
            return warnings

        pattern = r"(?:%|percent|p\.a\.|annual|return|multiplier|payback|months|years)"
        if not re.search(pattern, val_str.lower()):
            warnings.append(f"ROI value lacks expected percentage symbol (%) or return indicators: '{val}'")
        return warnings

    @staticmethod
    def validate_area(val: Any) -> List[str]:
        warnings = []
        if not val:
            return warnings
            
        val_str = str(val).strip()
        # Area required validation (spatial keywords and numbers)
        has_number = any(char.isdigit() for char in val_str)
        if not has_number:
            warnings.append(f"Area value lacks numeric dimensions: '{val}'")
            return warnings

        # Skip unit warning if purely numeric or numeric range
        clean_norm_test = re.sub(r"[\d\s\-\.\,\:]", "", val_str)
        if not clean_norm_test:
            return warnings

        pattern = r"(?:sq\.?\s*ft\.?|square\s*feet|sq\.?\s*m\.?|sq\.?\s*yards|acres?|carpet|built|meters?|size|floor|dimensions)"
        if not re.search(pattern, val_str.lower()):
            warnings.append(f"Area required lacks spatial unit indicators (e.g. sq ft, square feet): '{val}'")
        return warnings

    @staticmethod
    def validate_list_field(val: Any, field_name: str) -> List[str]:
        warnings = []
        if not val:
            return warnings
            
        if not isinstance(val, list):
            warnings.append(f"Field '{field_name}' should be returned as a list of strings: '{val}'")
        elif len(val) == 0:
            warnings.append(f"Field '{field_name}' list is empty")
        else:
            # Check items
            for idx, item in enumerate(val):
                if not str(item).strip():
                    warnings.append(f"Field '{field_name}' contains an empty item at index {idx}")
        return warnings

    @staticmethod
    def validate_date(val: Any, field_name: str) -> List[str]:
        warnings = []
        if not val:
            return warnings
            
        val_clean = str(val).strip()
        # Must match YYYY-MM-DD or a 4 digit year
        pattern_ymd = r"^\d{4}-\d{2}-\d{2}$"
        pattern_year = r"^\d{4}$"
        
        if not (re.match(pattern_ymd, val_clean) or re.match(pattern_year, val_clean)):
            # Check if a 4 digit year is contained anywhere
            years = re.findall(r"\b\d{4}\b", val_clean)
            if not years:
                warnings.append(f"Field '{field_name}' is not a valid date format (YYYY-MM-DD or YYYY): '{val}'")
        return warnings
