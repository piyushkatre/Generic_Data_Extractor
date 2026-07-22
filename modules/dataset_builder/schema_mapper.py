import os
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple, Set
from utils.logger import get_logger
from core.field_strategy import FIELD_STRATEGY

logger = get_logger(__name__)

# Module-level constants to avoid class load-order circular dependencies
IMPORTANT_BUSINESS_FIELDS = set(FIELD_STRATEGY.keys())

DEFAULT_MERGEABLE_COLUMNS = {
    "Products / Services", "Phone", "Email", "Keywords", "Support", "Products", "Services"
}

class MappingResult:
    """
    MappingResult represents the structured output of SchemaMapper.
    """
    def __init__(
        self,
        mapped_record: Dict[str, str],
        mapped_fields: List[str],
        unmapped_fields: List[str],
        merged_fields: List[str],
        confidence_scores: Dict[str, float],
        coverage_statistics: Dict[str, Any],
        normalization_statistics: Dict[str, Any],
        mapping_paths: Optional[Dict[str, str]] = None
    ):
        self.mapped_record = mapped_record
        self.mapped_fields = mapped_fields
        self.unmapped_fields = unmapped_fields
        self.merged_fields = merged_fields
        self.confidence_scores = confidence_scores
        self.coverage_statistics = coverage_statistics
        self.normalization_statistics = normalization_statistics
        self.mapping_paths = mapping_paths or {}

    def __getitem__(self, key):
        return self.mapped_record[key]

    def __setitem__(self, key, value):
        self.mapped_record[key] = value

    def __contains__(self, key):
        return key in self.mapped_record

    def get(self, key, default=None):
        return self.mapped_record.get(key, default)

    def keys(self):
        return self.mapped_record.keys()

    def values(self):
        return self.mapped_record.values()

    def items(self):
        return self.mapped_record.items()


class AliasRegistry:
    """
    Manages bidirectional mappings between canonical fields and target Excel columns
    using manual aliases and automatically generated name variations.
    Provides confidence scoring logic for resolving matching columns.
    """
    def __init__(self, excel_columns: List[str], manual_aliases: Dict[str, List[str]], schema_aliases: Dict[str, str]):
        self.excel_columns = excel_columns
        self.manual_aliases = manual_aliases
        self.schema_aliases = schema_aliases
        
        # Build registry mapping: canonical_field -> set of all alias variations
        self.canonical_aliases = {}
        
        for field in IMPORTANT_BUSINESS_FIELDS:
            aliases = set()
            # 1. Self field name
            aliases.update(self._generate_auto_aliases(field))
            # 2. Manual aliases
            for ma in manual_aliases.get(field, []):
                aliases.update(self._generate_auto_aliases(ma))
            
            # 3. Schema aliases (from adapter mapping alias_k -> col_name)
            # If col_name is mapped to this field, alias_k is an alias for this field
            for alias_k, col_name in schema_aliases.items():
                if col_name.lower().strip() == field.lower().strip() or col_name.lower().strip() in [a.lower().strip() for a in aliases]:
                    aliases.update(self._generate_auto_aliases(alias_k))
            
            self.canonical_aliases[field] = aliases

    def _generate_auto_aliases(self, base_name: str) -> List[str]:
        if not base_name:
            return []
        variations = {base_name, base_name.lower().strip()}
        
        # Replace underscores with spaces and vice versa
        space_name = base_name.replace("_", " ")
        under_name = base_name.replace(" ", "_")
        
        for name in [space_name, under_name]:
            variations.add(name)
            variations.add(name.lower())
            variations.add(name.title())
            variations.add(name.upper())
            # strip non-word characters
            variations.add(re.sub(r"\W+", "", name).lower())
            
        return sorted(list(variations))

    def _normalize_term(self, text: str) -> str:
        t = text.lower().strip()
        # strip standard helper suffixes/prefixes
        t = re.sub(r"(?i)\b(required|range|minimum|maximum|limit|number of|duration|period|details|person|link|links|url|url_url)\b", "", t)
        t = re.sub(r"\W+", "", t)
        return t

    def get_column_confidence(self, field_name: str, col: str) -> Tuple[float, str]:
        """
        Calculates confidence score between field_name and col.
        """
        f_clean = field_name.lower().strip()
        c_clean = col.lower().strip()
        
        # 1. Exact Match
        if f_clean == c_clean:
            return 1.0, "Exact Match"
            
        # 2. Alias Match
        aliases = self.canonical_aliases.get(field_name, set())
        if c_clean in [a.lower().strip() for a in aliases]:
            return 0.95, "Alias Match"
            
        # 3. Canonical Match
        f_alpha = re.sub(r"\W+", "", f_clean)
        c_alpha = re.sub(r"\W+", "", c_clean)
        if f_alpha == c_alpha and len(f_alpha) >= 3:
            return 0.90, "Canonical Match"
            
        # 4. Normalized Match
        f_norm = self._normalize_term(f_clean)
        c_norm = self._normalize_term(c_clean)
        if f_norm == c_norm and len(f_norm) >= 3:
            return 0.80, "Normalized Match"
            
        # 5. Fuzzy Match
        if len(f_alpha) >= 4 and (f_alpha in c_alpha or c_alpha in f_alpha):
            return 0.60, "Fuzzy Match"
            
        return 0.0, "No Match"

    def resolve_field_to_column(self, field_name: str) -> Tuple[Optional[str], float, str]:
        """
        Resolves field_name to target excel column with highest confidence >= 0.50.
        Evaluates all candidate canonical fields listing field_name as alias to resolve overlaps.
        """
        best_col = None
        best_score = 0.0
        best_type = "No Match"
        
        # Find all candidate canonical fields that list field_name as an alias or name
        candidate_canonicals = []
        f_clean = field_name.lower().strip()
        for canonical, aliases in self.canonical_aliases.items():
            if f_clean == canonical.lower().strip() or f_clean in [a.lower().strip() for a in aliases]:
                candidate_canonicals.append(canonical)
                
        if not candidate_canonicals:
            candidate_canonicals = [field_name]
            
        for canonical_target in candidate_canonicals:
            for col in self.excel_columns:
                score, match_type = self.get_column_confidence(canonical_target, col)
                if field_name != canonical_target:
                    raw_score, raw_type = self.get_column_confidence(field_name, col)
                    if raw_score > score:
                        score, match_type = raw_score, raw_type
                        
                if score > best_score:
                    best_score = score
                    best_col = col
                    best_type = match_type
                    
        if best_score >= 0.50:
            return best_col, best_score, best_type
        return None, 0.0, "No Match"


class SchemaMapper:
    """
    Decouples Gemini extraction from spreadsheet layouts.
    Uses AliasRegistry to map CanonicalFranchiseRecord to target Excel columns.
    Performs values normalization and logs a detailed Schema Coverage Report.
    """

    IMPORTANT_BUSINESS_FIELDS = IMPORTANT_BUSINESS_FIELDS

    def __init__(self, excel_columns: List[str], aliases_path: str = "schemas/schema_aliases.json", schema_aliases: Optional[Dict[str, str]] = None, schema: Optional[Dict[str, Any]] = None):
        self.excel_columns = excel_columns
        self.schema = schema or {}
        
        self.schema_aliases = schema_aliases or self.schema.get("aliases", {})
        
        if self.schema:
            self.aliases_config = self._build_aliases_from_schema(self.schema)
        else:
            self.aliases_path = os.path.abspath(aliases_path)
            self.aliases_config = self._load_aliases()
        
        # Register standard defaults dynamically
        self.aliases_config.setdefault("about", []).extend(["About", "about", "overview", "company_profile"])
        self.aliases_config.setdefault("description", []).extend(["Description", "description", "overview", "summary"])
        self.aliases_config.setdefault("services", []).extend(["Services", "services", "offerings", "business_services"])
        self.aliases_config.setdefault("operational_support", []).extend(["Support", "support", "business_support", "operational_support"])
        self.aliases_config.setdefault("investment_required", []).extend(["Investment Required", "Investment", "capital_required", "investment_required", "Investment Range"])
        self.aliases_config.setdefault("franchise_name", []).extend(["Franchise Name", "brand_name", "franchise_name"])

        # Range fields specific defaults for alignment
        self.aliases_config.setdefault("investment_min", []).extend(["Minimum Investment", "investment_min", "min_investment", "investment min"])
        self.aliases_config.setdefault("investment_max", []).extend(["Maximum Investment", "investment_max", "max_investment", "investment max"])
        self.aliases_config.setdefault("area_min", []).extend(["Minimum Area", "area_min", "min_area", "area min"])
        self.aliases_config.setdefault("area_max", []).extend(["Maximum Area", "area_max", "max_area", "area max"])

        # Instantiate AliasRegistry
        self.registry = AliasRegistry(self.excel_columns, self.aliases_config, self.schema_aliases)

        # Mergeable columns
        schema_mergeable = self.schema.get("config", {}).get("mergeable_columns", [])
        if schema_mergeable:
            self.mergeable_columns = {col.lower().strip() for col in schema_mergeable}
        else:
            self.mergeable_columns = {col.lower().strip() for col in DEFAULT_MERGEABLE_COLUMNS}

        # Array delimiter
        self.array_delimiter = self.schema.get("config", {}).get("array_delimiter", ", ")

    def _build_aliases_from_schema(self, schema: Dict[str, Any]) -> Dict[str, List[str]]:
        aliases_config = {}
        for alias_key, col_name in schema.get("aliases", {}).items():
            aliases_config.setdefault(col_name, []).append(alias_key)
        return aliases_config

    def _load_aliases(self) -> Dict[str, List[str]]:
        if not os.path.exists(self.aliases_path):
            logger.warning(f"Aliases configuration missing at {self.aliases_path}. Using empty fallback.")
            return {}
        try:
            with open(self.aliases_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load schema aliases: {e}", exc_info=True)
            return {}

    def _format_single_investment(self, amount: int, symbol: str = "₹") -> str:
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

    def _normalize_investment_text(self, text: str) -> str:
        if not text:
            return ""
        
        # Parse using static range parser
        min_val, max_val = self.parse_investment_range(text)
        symbol = "$" if "$" in str(text) or "usd" in str(text).lower() else "₹"
        
        if min_val is not None and max_val is not None:
            return f"{self._format_single_investment(min_val, symbol=symbol)} - {self._format_single_investment(max_val, symbol=symbol)}"
        elif min_val is not None:
            t_low = str(text).lower()
            if any(w in t_low for w in ["above", "min", "greater", "starting", "from"]):
                return f"Starting from {self._format_single_investment(min_val, symbol=symbol)}"
            return self._format_single_investment(min_val, symbol=symbol)
        elif max_val is not None:
            return f"Upto {self._format_single_investment(max_val, symbol=symbol)}"
            
        # Fallback to general cleaning if range parsing failed
        text = str(text).strip()
        text = re.sub(r"(?i)\b(rs\.?|inr)\s*", "₹", text)
        text = re.sub(r"₹\s*", "₹", text)
        text = re.sub(r"(?i)(\d+)\s*(lakhs?|lakh)\b", r"\1 Lakhs", text)
        text = re.sub(r"(?i)(\d+)\s*(crores?|crore|cr)\b", r"\1 Crore", text)
        text = re.sub(r"\s*[\-–—]\s*", " - ", text)
        return text

    def _normalize_area_text(self, text: str) -> str:
        text = str(text).strip()
        if not text:
            return ""
        # Normalize space/dash between ranges to en-dash (–) or standard hyphen (-)
        text = re.sub(r"\s*[\-–—]\s*", "-", text)
        text_lower = text.lower()
        # Remove any existing unit suffix to normalize
        text = re.sub(r"(?i)\s*(sq\.?\s*f[t|eet]+|sqft|sft)\b", "", text)
        text = text.strip()
        text = f"{text} Sq.ft"
        return text

    def _normalize_hours_text(self, text: str) -> str:
        text = str(text).strip()
        if not text:
            return ""
        text = re.sub(r"(?i)\s*(hrs|hr|hours?)(?:\s*/\s*month)?\b", " hrs/month", text)
        if "hrs/month" not in text:
            text = f"{text} hrs/month"
        text = re.sub(r"(\d+)\s*[\-–—]\s*(\d+)", r"\1-\2", text)
        return text

    def _normalize_phone(self, phone: str) -> str:
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

    def _strip_tracking_params(self, url_str: str) -> str:
        if not isinstance(url_str, str) or not ("http://" in url_str or "https://" in url_str):
            return url_str
        if "?" in url_str:
            base, query = url_str.split("?", 1)
            params = []
            for param in query.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    k_low = k.lower()
                    if k_low.startswith("utm_") or k_low in ("fbclid", "gclid", "yclid", "msclkid"):
                        continue
                    params.append(f"{k}={v}")
                else:
                    params.append(param)
            if params:
                return f"{base}?{'&'.join(params)}"
            return base
        return url_str

    def _clean_data_dict(self, data: dict, mapped_fields: set, is_top_level: bool = True) -> dict:
        cleaned = {}
        for k, v in data.items():
            if not k:
                continue
            if is_top_level:
                k_clean = str(k).lower().strip().replace("_", " ").replace("-", " ")
                if k_clean in mapped_fields:
                    continue
            if v in (None, "", [], {}):
                continue
            if isinstance(v, str):
                v = v.strip()
                if not v:
                    continue
                v = self._strip_tracking_params(v)
            elif isinstance(v, dict):
                v = self._clean_data_dict(v, mapped_fields, is_top_level=False)
                if not v:
                    continue
            elif isinstance(v, list):
                new_list = []
                for item in v:
                    if isinstance(item, dict):
                        cleaned_item = self._clean_data_dict(item, mapped_fields, is_top_level=False)
                        if cleaned_item:
                            new_list.append(cleaned_item)
                    elif isinstance(item, str):
                        item_clean = self._strip_tracking_params(item.strip())
                        if item_clean:
                            new_list.append(item_clean)
                    elif item not in (None, "", [], {}):
                        new_list.append(item)
                if not new_list:
                    continue
                v = new_list
            cleaned[k] = v
        return cleaned

    def _format_value(self, val: Any) -> str:
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        if isinstance(val, list):
            formatted_items = []
            for item in val:
                if hasattr(item, "question") and hasattr(item, "answer"):
                    formatted_items.append(f"Q: {item.question} A: {item.answer}")
                elif hasattr(item, "key") and hasattr(item, "value"):
                    formatted_items.append(f"{item.key}: {item.value}")
                elif isinstance(item, dict) and "question" in item and "answer" in item:
                    formatted_items.append(f"Q: {item['question']} A: {item['answer']}")
                elif isinstance(item, dict) and "key" in item and "value" in item:
                    formatted_items.append(f"{item['key']}: {item['value']}")
                else:
                    formatted_items.append(str(item))
            
            has_custom_delim = self.schema.get("config", {}).get("array_delimiter") is not None
            if not has_custom_delim and len(formatted_items) > 1:
                return "\n".join(f"• {item}" for item in formatted_items)
            
            return self.array_delimiter.join(formatted_items)
        return str(val)

    def verify_gemini_output(self, raw_dict: Dict[str, Any]):
        """
        Validates Gemini response structure and logs warnings for unexpected fields.
        """
        logger.info("=== VERIFYING GEMINI OUTPUT SCHEMA ===")
        
        # 1. Check schema fields
        extraction_fields = self.schema.get("extraction_fields", {})
        allowed_keys = set(IMPORTANT_BUSINESS_FIELDS).union(extraction_fields.keys()).union({
            "entities", "page_title", "page_summary", "metadata", "additional_information", "source_url", "extracted_at", "confidence", "faq"
        })
        
        unexpected_keys = []
        nested_fields = []
        array_fields = []
        canonical_present = []
        
        for k, v in raw_dict.items():
            if k not in allowed_keys:
                unexpected_keys.append(k)
                logger.warning(f"[Gemini Verification] Unexpected field returned by LLM: '{k}'")
            else:
                if k in IMPORTANT_BUSINESS_FIELDS:
                    canonical_present.append(k)
                if isinstance(v, list):
                    array_fields.append(k)
                elif isinstance(v, dict):
                    nested_fields.append(k)
                    
        logger.info(f"Canonical fields present: {len(canonical_present)} {canonical_present}")
        if unexpected_keys:
            logger.warning(f"Unexpected fields present: {len(unexpected_keys)} {unexpected_keys}")
        if nested_fields:
            logger.info(f"Nested fields present: {len(nested_fields)} {nested_fields}")
        if array_fields:
            logger.info(f"Array fields present: {len(array_fields)} {array_fields}")
        logger.info("======================================")

    def map_to_excel(self, result: Any, source_url: str, html_content: Optional[str] = None) -> Dict[str, str]:
        """
        Maps CanonicalFranchiseRecord into spreadsheet columns using bidirectional AliasRegistry and confidence score matching.
        """
        raw_dict = result.model_dump() if hasattr(result, "model_dump") else dict(result)

        # Verify output keys
        self.verify_gemini_output(raw_dict)

        # ── Step 4: Normalizations ──
        # Normalization and range parsing are now fully performed by RecordValidator in the validation stage.

        if not raw_dict.get("extracted_at"):
            raw_dict["extracted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        if not raw_dict.get("source_url"):
            raw_dict["source_url"] = source_url

        # Initialize normalized record
        normalized_record = {col: "" for col in self.excel_columns}
        
        # Keep track of mapping info
        mapped_details = {} # col -> (field_name, score, match_type)
        unmapped_fields = []
        merged_log = []
        
        logger.info(f"=== STARTING SCHEMA MAPPING (Adapter: {self.schema.get('name', 'Default')}) ===")
        logger.info(f"Excel target columns: {self.excel_columns}")

        # Map available fields
        for field, val in raw_dict.items():
            if field in ("entities", "page_title", "page_summary", "metadata", "additional_information"):
                continue
            if val in (None, "", [], {}):
                continue
                
            col, score, match_type = self.registry.resolve_field_to_column(field)
            if col:
                val_str = self._format_value(val)
                is_mergeable = col.lower().strip() in self.mergeable_columns
                
                if is_mergeable:
                    if normalized_record[col]:
                        # Split and merge
                        existing = [x.strip() for x in normalized_record[col].split(self.array_delimiter) if x.strip()]
                        incoming = [x.strip() for x in val_str.split(self.array_delimiter) if x.strip()]
                        merged = existing + [x for x in incoming if x not in existing]
                        normalized_record[col] = self.array_delimiter.join(merged)
                        merged_log.append(f"{field} merged into {col}")
                        logger.info(f"Merged field '{field}' value into Excel column '{col}'")
                    else:
                        normalized_record[col] = val_str
                        mapped_details[col] = (field, score, match_type)
                else:
                    # Non-mergeable: check confidence score if column already mapped
                    if col in mapped_details:
                        prev_field, prev_score, prev_type = mapped_details[col]
                        
                        # Tie-breaking logic: prefer specific bounds (_min or _max) over general range fields
                        is_new_specific = field.endswith("_min") or field.endswith("_max")
                        is_prev_specific = prev_field.endswith("_min") or prev_field.endswith("_max")
                        
                        if score > prev_score or (score == prev_score and is_new_specific and not is_prev_specific):
                            logger.info(f"Overwriting column '{col}' with field '{field}' (score {score} >= {prev_score})")
                            normalized_record[col] = val_str
                            mapped_details[col] = (field, score, match_type)
                        else:
                            logger.info(f"Skipping field '{field}' for column '{col}' (score {score} <= {prev_score})")
                    else:
                        normalized_record[col] = val_str
                        mapped_details[col] = (field, score, match_type)
            else:
                unmapped_fields.append(field)
                logger.info(f"Field '{field}' could not be resolved to any Excel column")

        # ── Legacy/Custom Schema Aliases Fallback ──
        if self.schema_aliases:
            for raw_k, raw_v in raw_dict.items():
                if raw_v not in (None, "", [], {}):
                    for alias_k, col_name in self.schema_aliases.items():
                        if alias_k.lower().strip() == raw_k.lower().strip():
                            if col_name in normalized_record and normalized_record[col_name] == "":
                                normalized_record[col_name] = self._format_value(raw_v)
                                mapped_details[col_name] = (raw_k, 0.95, "Legacy Alias Fallback")

            if hasattr(result, "entities") and result.entities:
                for ent in result.entities:
                    for rec in ent.records:
                        for attr in rec.attributes:
                            attr_k = attr.key.lower().strip()
                            attr_v = attr.value
                            if attr_v not in (None, "", [], {}):
                                for alias_k, col_name in self.schema_aliases.items():
                                    if alias_k.lower().strip() == attr_k:
                                        if col_name in normalized_record and normalized_record[col_name] == "":
                                            normalized_record[col_name] = self._format_value(attr_v)
                                            mapped_details[col_name] = (attr_k, 0.95, "Legacy Entity Alias Fallback")

        # ── Step 5 & Step 6: Additional Information Fallback & Policy ──
        fallback_data = {}
        known_fields = set(self.aliases_config.keys()).union(IMPORTANT_BUSINESS_FIELDS)

        for k, v in raw_dict.items():
            if k not in ("entities", "page_title", "page_summary", "metadata") and v not in (None, "", [], {}):
                # If field didn't map to any column, place in Additional Info
                is_mapped = False
                for mapped_col, (f_name, _, _) in mapped_details.items():
                    if f_name == k:
                        is_mapped = True
                        break
                if not is_mapped and k != "additional_information":
                    if k not in known_fields:
                        fallback_data[k] = v
                        logger.info(f"Fallback attribute placed in Additional Information: {k}")

        raw_add_info = raw_dict.get("additional_information")
        if raw_add_info:
            if isinstance(raw_add_info, list):
                for item in raw_add_info:
                    if isinstance(item, dict):
                        k_item = item.get("key")
                        v_item = item.get("value")
                    else:
                        k_item = getattr(item, "key", None)
                        v_item = getattr(item, "value", None)
                    if k_item:
                        fallback_data[k_item] = v_item
            elif isinstance(raw_add_info, dict):
                fallback_data.update(raw_add_info)
            else:
                try:
                    loaded_info = json.loads(raw_add_info)
                    if isinstance(loaded_info, dict):
                        fallback_data.update(loaded_info)
                    else:
                        fallback_data["info"] = str(raw_add_info)
                except Exception:
                    fallback_data["info"] = str(raw_add_info)

        if hasattr(result, "entities") and result.entities:
            from modules.dataset_builder.record_mapper import PrimaryEntityDetector
            mock_schema = {"primary_key": self.excel_columns, "columns": self.excel_columns}
            detector = PrimaryEntityDetector(mock_schema)
            _, related_entities = detector.detect(result.entities)
            
            if related_entities:
                related_list = []
                for rel in related_entities:
                    rel_list = [
                        {attr.key: attr.value for attr in rec.attributes}
                        for rec in rel.records
                    ]
                    related_list.append({
                        "entity_type": rel.entity_type,
                        "records":     rel_list
                    })
                fallback_data["related_entities"] = related_list

        add_col = None
        aliases = [a.lower().strip() for a in self.aliases_config.get("additional_information", [])]
        for col in self.excel_columns:
            if col.lower().strip() in aliases or col.lower().strip() == "additional_information" or col.lower().strip() == "additional information":
                add_col = col
                break

        if add_col and add_col in normalized_record:
            mapped_fields = set()
            for col, mapped_info in mapped_details.items():
                mapped_fields.add(col.lower().strip().replace("_", " ").replace("-", " "))
                if mapped_info and len(mapped_info) > 0:
                    mapped_fields.add(str(mapped_info[0]).lower().strip().replace("_", " ").replace("-", " "))
            
            fallback_data = self._clean_data_dict(fallback_data, mapped_fields)
            if fallback_data:
                normalized_record[add_col] = json.dumps(fallback_data, ensure_ascii=False)
                mapped_details[add_col] = ("additional_information", 1.0, "Fallback Integration")
            else:
                normalized_record[add_col] = ""

        # ── Step 7: Coverage Validation & Detailed Reports ──
        metadata_list = raw_dict.get("metadata") or []
        fields_from_dom = set()
        fields_from_gemini = set()
        if isinstance(metadata_list, dict):
            fields_from_dom = set(metadata_list.get("fields_from_dom") or [])
            fields_from_gemini = set(metadata_list.get("fields_from_gemini") or [])
        else:
            for item in metadata_list:
                if isinstance(item, dict):
                    k_item = item.get("key")
                    v_item = item.get("value")
                else:
                    k_item = getattr(item, "key", None)
                    v_item = getattr(item, "value", None)
                
                if k_item == "fields_from_dom" and v_item:
                    fields_from_dom = set([x.strip() for x in str(v_item).split(",") if x.strip()])
                elif k_item == "fields_from_gemini" and v_item:
                    fields_from_gemini = set([x.strip() for x in str(v_item).split(",") if x.strip()])

        core_fields = [k for k in raw_dict.keys() if k not in ("entities", "page_title", "page_summary", "metadata", "additional_information")]
        total_schema_fields = len(core_fields)

        missing_fields = [k for k in core_fields if raw_dict.get(k) in (None, "", [], {})]
        
        # Calculate coverage details
        mapped_count = len(mapped_details)
        det_count = len([f for f in mapped_details.values() if f[0] in fields_from_dom])
        llm_count = len([f for f in mapped_details.values() if f[0] in fields_from_gemini])
        norm_count = len([k for k in ("investment_required", "franchise_fee", "royalty", "area_required", "expected_hours", "phone", "email", "website") if raw_dict.get(k)])
        merged_count = len(merged_log)
        coverage_pct = (mapped_count / len(self.excel_columns) * 100.0) if self.excel_columns else 0.0

        # Log details
        logger.info("\n=== MAPPED FIELDS REPORT ===")
        for col, (field, score, m_type) in mapped_details.items():
            logger.info(f"Mapped: {field} -> {col} (Match: {m_type}, Confidence: {score*100:.0f}%)")
            
        logger.info("\n=== UNMAPPPED FIELDS REPORT ===")
        logger.info(f"Unmapped: {unmapped_fields}")
        logger.info(f"Missing: {missing_fields}")

        logger.info(
            f"\n=== SCHEMA COVERAGE REPORT ===\n"
            f"Total Schema Fields:        {total_schema_fields}\n"
            f"Mapped Fields:              {mapped_count}\n"
            f"Deterministic Fields:        {det_count}\n"
            f"LLM Fields:                 {llm_count}\n"
            f"Normalized Fields:          {norm_count}\n"
            f"Merged Fields:              {merged_count}\n"
            f"Missing Fields:             {len(missing_fields)}\n"
            f"Unmapped Fields:            {len(unmapped_fields)}\n"
            f"Schema Coverage Percentage: {coverage_pct:.2f}%\n"
            f"=============================="
        )

        # Construct mapping paths
        mapping_paths = {}
        normalized_fields_keys = {"investment_required", "franchise_fee", "royalty", "area_required", "expected_hours", "phone", "email", "website"}
        for col, mapped_info in mapped_details.items():
            if mapped_info and len(mapped_info) == 3:
                field, score, m_type = mapped_info
                is_norm = field in normalized_fields_keys
                path_str = f"{field} -> {m_type}"
                if is_norm:
                    path_str += " -> Normalized"
                path_str += f" -> Mapped ({score*100:.0f}%)"
                mapping_paths[col] = path_str

        # Write coverage metadata back into the model for Streamlit UI consumption
        coverage_meta = {
            "total_schema_fields": total_schema_fields,
            "mapped_count": mapped_count,
            "deterministic_count": det_count,
            "llm_count": llm_count,
            "normalized_count": norm_count,
            "merged_count": merged_count,
            "missing_count": len(missing_fields),
            "unmapped_count": len(unmapped_fields),
            "coverage_percentage": f"{coverage_pct:.2f}%",
            "unmapped_fields_list": ",".join(unmapped_fields),
            "missing_fields_list": ",".join(missing_fields),
            "mapping_paths_json": json.dumps(mapping_paths)
        }
        
        if hasattr(result, "metadata") and result.metadata is not None:
            from modules.adapter_loader import KeyValueItem
            # Clean previous coverage keys to avoid duplication
            clean_meta = []
            for x in result.metadata:
                k = x.key if hasattr(x, "key") else (x.get("key") if isinstance(x, dict) else None)
                if k not in coverage_meta:
                    clean_meta.append(x)
            result.metadata = clean_meta
            
            # Determine if we should append as dict or KeyValueItem
            is_dict_list = len(result.metadata) > 0 and isinstance(result.metadata[0], dict)
            for k_meta, v_meta in coverage_meta.items():
                if is_dict_list:
                    result.metadata.append({"key": k_meta, "value": v_meta})
                else:
                    result.metadata.append(KeyValueItem(key=k_meta, value=v_meta))

        mapped_fields = list(mapped_details.keys())
        confidence_scores = {col: score for col, (_, score, _) in mapped_details.items()}
        
        return MappingResult(
            mapped_record=normalized_record,
            mapped_fields=mapped_fields,
            unmapped_fields=unmapped_fields,
            merged_fields=merged_log,
            confidence_scores=confidence_scores,
            coverage_statistics=coverage_meta,
            normalization_statistics={
                "normalized_count": norm_count,
                "merged_count": merged_count
            },
            mapping_paths=mapping_paths
        )

    @staticmethod
    def parse_investment_range(text: Any) -> Tuple[Optional[int], Optional[int]]:
        if not text:
            return None, None
        text_lower = str(text).lower()
        # Remove commas inside numbers to avoid splitting them (e.g. 60,000 -> 60000)
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

    @staticmethod
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
