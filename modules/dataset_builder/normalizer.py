import re
import json
from typing import Dict, Any, List

class RecordNormalizer:
    """
    Standardizes and maps extracted attributes to schema columns.
    Handles field aliases, data type standardizations, list formatting,
    and moves unmapped fields to an 'Additional Information' JSON block.
    """

    def __init__(self, schema: Dict[str, Any]):
        self.schema = schema
        self.columns = schema.get("columns", [])
        self.aliases = schema.get("aliases", {})
        self.required_fields = schema.get("required_fields", [])
        
        # Build a lowercase-normalized mapping of aliases and columns for fast lookup
        self.mapping_lookup = {}
        
        # Lowercase exact column match mapping
        for col in self.columns:
            self.mapping_lookup[col.lower().replace("_", " ").replace("-", " ").strip()] = col
            
        # Lowercase alias mapping (overrides column defaults if specified)
        for alias, col in self.aliases.items():
            self.mapping_lookup[alias.lower().replace("_", " ").replace("-", " ").strip()] = col

    def normalize_value(self, key: str, value: Any) -> str:
        """
        Normalizes a field value based on its type and key context.
        """
        if value is None:
            return ""

        # Handle lists/tuples
        if isinstance(value, (list, tuple)):
            cleaned_list = [str(x).strip() for x in value if x is not None]
            value = " | ".join(cleaned_list)
        else:
            value = str(value)

        # Standardize whitespace
        value = re.sub(r"\s+", " ", value).strip()
        key_lower = key.lower()

        # Phone numbers cleaning
        if "phone" in key_lower or "mobile" in key_lower or "contact" in key_lower:
            value = re.sub(r"[^\d\+\-\(\)\sa-zA-Z]", "", value)
            value = re.sub(r"\s+", " ", value).strip()

        # Email cleaning
        elif "email" in key_lower:
            value = value.lower().replace(" ", "")
            # Basic sanitization to check if email format contains valid characters
            match = re.search(r"[\w.\-_]+@[\w.\-_]+\.[a-zA-Z]{2,}", value)
            if match:
                value = match.group(0)

        # URL / Website cleaning
        elif "website" in key_lower or "url" in key_lower or "link" in key_lower:
            value = value.strip().replace(" ", "")
            if value and not value.startswith(("http://", "https://", "ftp://")):
                # Guess https protocol if missing
                value = "https://" + value

        # Currency cleaning
        elif "price" in key_lower or "fee" in key_lower or "investment" in key_lower or "royalty" in key_lower:
            # Retain standard currency symbols, numbers, decimal point, comma, percent signs, and ranges/dashes
            value = re.sub(r"[^\d$,.%\-\s[a-zA-Z]]", "", value)
            value = re.sub(r"\s+", " ", value).strip()

        return value

    def normalize_record(self, raw_record: Dict[str, Any], source_url: str, page_title: str) -> Dict[str, str]:
        """
        Normalizes a raw record dict and maps it directly to the target schema columns.
        """
        normalized_record = {col: "" for col in self.columns}
        additional_info = {}

        # Pre-populate source_url in normalized records
        for col_name in ["Source URL", "source_url"]:
            mapped_col = self.get_mapped_column(col_name)
            if mapped_col:
                normalized_record[mapped_col] = source_url

        # Iterate over all raw keys
        for raw_key, raw_val in raw_record.items():
            if raw_val is None or raw_val == "":
                continue
                
            mapped_col = self.get_mapped_column(raw_key)
            normalized_val = self.normalize_value(raw_key, raw_val)

            if mapped_col:
                normalized_record[mapped_col] = normalized_val
            else:
                additional_info[raw_key] = normalized_val

        # Populate missing required fields with sensible defaults (like page_title or source_url)
        for req in self.required_fields:
            if normalized_record.get(req) == "":
                if "title" in req.lower() or "name" in req.lower():
                    normalized_record[req] = page_title
                elif "url" in req.lower():
                    normalized_record[req] = source_url

        # Store any leftover unmapped properties in the 'Additional Information' JSON block
        add_col = self.get_mapped_column("Additional Information")
        if add_col:
            if additional_info:
                normalized_record[add_col] = json.dumps(additional_info, ensure_ascii=False)
            else:
                normalized_record[add_col] = ""

        return normalized_record

    def get_mapped_column(self, raw_key: str) -> str:
        """
        Looks up the alias mapping for a raw key. Returns the correct column name or None.
        """
        key_norm = str(raw_key).strip().lower().replace("_", " ").replace("-", " ")
        return self.mapping_lookup.get(key_norm)
