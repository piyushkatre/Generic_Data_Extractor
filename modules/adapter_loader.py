from __future__ import annotations
import os
import json
from typing import Dict, Any, Optional, List, Type
from urllib.parse import urlparse
from pydantic import BaseModel, create_model, Field, model_validator

from modules.domain_profiles.base import DomainProfile
from utils.logger import get_logger

logger = get_logger(__name__)

class FAQItem(BaseModel):
    question: str = Field(description="Frequently asked question text")
    answer: str = Field(description="Answer text corresponding to the question")

class KeyValueItem(BaseModel):
    key: str = Field(description="The key/name of the attribute")
    value: Optional[Any] = Field(default=None, description="The value of the attribute")



class KeyValue(BaseModel):
    key: str = Field(description="The name of the attribute (e.g., title, price, rank, author, points, comments_count)")
    value: str = Field(description="The value of the attribute")

class ExtractedRecord(BaseModel):
    attributes: List[KeyValue] = Field(description="List of key-value attributes for this record")

class ExtractedEntity(BaseModel):
    entity_type: str = Field(description="The type of entity (e.g., Product, Article, Job Listing, Movie, Price, Comment)")
    records: List[ExtractedRecord] = Field(description="List of extracted records for this entity type.")

class CanonicalFranchiseRecord(BaseModel):
    # General
    franchise_name: Optional[str] = Field(default=None, description="Name of the primary franchise opportunity on the page")
    brand: Optional[str] = Field(default=None, description="Official brand name of the franchise")
    page_type: Optional[str] = Field(default="Franchise Opportunity", description="Type of the page (e.g., Franchise Page, Franchise Listing)")
    category: Optional[str] = Field(default=None, description="Specific business category of the franchise")
    industry: Optional[str] = Field(default=None, description="Industry sector (e.g. Education, Food & Beverage, Fitness)")
    segment: Optional[str] = Field(default=None, description="Specific segment of the industry/category")
    description: Optional[str] = Field(default=None, description="General description of the franchise opportunity")
    about: Optional[str] = Field(default=None, description="About the company, history, or background details")

    # Business
    business_model: Optional[str] = Field(default=None, description="Summary of the business concept and model")
    concept: Optional[str] = Field(default=None, description="Detailed business concept description")
    founded_year: Optional[str] = Field(default=None, description="The year the parent brand/company was founded")
    franchise_start_year: Optional[str] = Field(default=None, description="The year the company began franchising")
    operations_commenced: Optional[str] = Field(default=None, description="The date or year operations commenced")
    established_year: Optional[str] = Field(default=None, description="The year the parent brand/company was established")
    number_of_outlets: Optional[str] = Field(default=None, description="Total number of outlets or stores currently operating")
    number_of_employees: Optional[str] = Field(default=None, description="Total number of staff/employees")
    franchise_since: Optional[str] = Field(default=None, description="The year or duration since franchising commenced")

    # Financial
    investment_required: Optional[str] = Field(default=None, description="Total investment/capital required text range (e.g. Rs. 20 Lakhs - 30 Lakhs)")
    investment_min: Optional[float] = Field(default=None, description="Minimum numeric investment parsed")
    investment_max: Optional[float] = Field(default=None, description="Maximum numeric investment parsed")
    franchise_fee: Optional[str] = Field(default=None, description="One-time franchise / joining / entry fee required")
    royalty: Optional[str] = Field(default=None, description="Royalty fee details or percentage commission")
    roi: Optional[str] = Field(default=None, description="Expected ROI details")
    payback_period: Optional[str] = Field(default=None, description="Expected payback period / breakeven details")
    agreement_duration: Optional[str] = Field(default=None, description="Duration of franchise agreement")

    # Infrastructure
    area_required: Optional[str] = Field(default=None, description="Physical area/space required text range (e.g. 500-1000 sq ft)")
    area_min: Optional[float] = Field(default=None, description="Minimum numeric area space parsed")
    area_max: Optional[float] = Field(default=None, description="Maximum numeric area space parsed")

    # Support & Training
    training: Optional[str] = Field(default=None, description="Training details or program provided")
    support: Optional[str] = Field(default=None, description="Operations and business support description")
    marketing_support: Optional[str] = Field(default=None, description="Marketing and advertising support details")
    operational_support: Optional[str] = Field(default=None, description="Ongoing operational guidance and logistics")
    business_support: Optional[str] = Field(default=None, description="General business assistance description")

    # Contact & Socials
    phone: Optional[str] = Field(default=None, description="Contact phone numbers")
    email: Optional[str] = Field(default=None, description="Contact email addresses")
    website: Optional[str] = Field(default=None, description="Official website URL")
    address: Optional[str] = Field(default=None, description="Full head office address")
    city: Optional[str] = Field(default=None, description="City location of the opportunity")
    state: Optional[str] = Field(default=None, description="State location of the opportunity")
    country: Optional[str] = Field(default=None, description="Country location")
    facebook: Optional[str] = Field(default=None, description="Official Facebook link")
    instagram: Optional[str] = Field(default=None, description="Official Instagram link")
    linkedin: Optional[str] = Field(default=None, description="Official LinkedIn link")
    twitter: Optional[str] = Field(default=None, description="Official Twitter/X link")
    youtube: Optional[str] = Field(default=None, description="Official YouTube link")
    whatsapp_link: Optional[str] = Field(default=None, description="Official WhatsApp link")

    # Media & Docs
    logo: Optional[str] = Field(default=None, description="Logo alt text or filename")
    logo_url: Optional[str] = Field(default=None, description="Raw source URL of logo image")
    images: Optional[List[str]] = Field(default_factory=list, description="Array of image gallery URLs")
    brochures: Optional[List[str]] = Field(default_factory=list, description="Array of brochure document URLs")
    documents: Optional[List[str]] = Field(default_factory=list, description="Array of related PDF/doc URLs")

    # FAQ & Raw Ext
    faq: Optional[List[FAQItem]] = Field(default_factory=list, description="Frequently asked questions list")
    additional_information: Optional[List[KeyValueItem]] = Field(default_factory=list, description="Additional properties parsed")
    metadata: Optional[List[KeyValueItem]] = Field(default_factory=list, description="Metadata key-value logs")
    entities: Optional[List[ExtractedEntity]] = Field(default_factory=list, description="Extracted entity details")

    # Pipeline Meta
    source_url: Optional[str] = Field(default=None, description="The URL of the source page")
    extracted_at: Optional[str] = Field(default=None, description="ISO extraction timestamp")
    confidence: Optional[float] = Field(default=None, description="Extraction confidence score (0.0 to 1.0)")
    
    # page fields expected by evaluator/ui
    page_title: Optional[str] = Field(default=None, description="Title of the page")
    page_summary: Optional[str] = Field(default=None, description="Brief summary of the page")

    @model_validator(mode="after")
    def populate_fallbacks(self) -> CanonicalFranchiseRecord:
        # 1. Deduce from entities list if missing and entities has values (backward compatibility)
        if self.entities:
            for ent in self.entities:
                if ent.records:
                    for rec in ent.records:
                        for attr in rec.attributes:
                            k = attr.key
                            if k == "investment":
                                k = "investment_required"
                            if hasattr(self, k) and getattr(self, k) is None:
                                setattr(self, k, attr.value)

        # 2. Build entities structure if flat fields populated but entities empty
        if self.franchise_name and not self.entities:
            attrs = [
                KeyValue(key="franchise_name", value=self.franchise_name)
            ]
            if self.phone:
                attrs.append(KeyValue(key="phone", value=self.phone))
            if self.email:
                attrs.append(KeyValue(key="email", value=self.email))
            if self.investment_required:
                attrs.append(KeyValue(key="investment", value=self.investment_required))
            self.entities = [
                ExtractedEntity(
                    entity_type="Franchise Opportunity",
                    records=[ExtractedRecord(attributes=attrs)]
                )
            ]

        # 3. Handle page_title / page_summary fallbacks
        if not self.page_title:
            self.page_title = self.franchise_name or self.brand or "Franchise Opportunity"
        if not self.page_summary:
            self.page_summary = self.description or self.about or ""

        return self

    def to_clean_dict(self) -> Dict[str, Any]:
        d = self.model_dump()
        return {
            "page_title": self.page_title,
            "page_type": self.page_type or "Franchise Page",
            "page_summary": self.page_summary,
            "entities": {
                "Franchise Opportunity": [d]
            }
        }

ExtractionResult = CanonicalFranchiseRecord

from pydantic import model_validator

class Adapter:
    """
    Represents a single website adapter containing configuration, schema, and prompt.
    """
    def __init__(self, directory: str):
        self.directory = os.path.abspath(directory)
        self.config_path = os.path.join(self.directory, "config.json")
        self.schema_path = os.path.join(self.directory, "schema.json")
        self.prompt_path = os.path.join(self.directory, "prompt.md")
        
        self.config = self._load_json(self.config_path)
        self.schema = self._load_json(self.schema_path)
        self.prompt_template = ""
        
        self.domain = self.config.get("domain", "*")
        self.name = self.config.get("name", "Unknown")
        
        # Support registry matching upgrades (domains list, aliases list, priority, version, metadata)
        self.domains = self.config.get("domain") or []
        if isinstance(self.domains, str):
            self.domains = [self.domains]
            
        self.aliases = self.config.get("aliases") or []
        if isinstance(self.aliases, str):
            self.aliases = [self.aliases]
            
        self.priority = int(self.config.get("priority", 0))
        self.version = str(self.config.get("version", "1.0.0"))
        self.metadata = self.config.get("metadata", {})
        
        self._model_cache: Optional[Type[BaseModel]] = None

    def _load_json(self, path: str) -> Dict[str, Any]:
        if not os.path.exists(path):
            logger.warning(f"File missing in adapter directory: {path}")
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load JSON from {path}: {e}")
            return {}

    def _load_text(self, path: str) -> str:
        if not os.path.exists(path):
            logger.warning(f"File missing in adapter directory: {path}")
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Failed to load text from {path}: {e}")
            return ""

    def get_profile(self) -> DomainProfile:
        """
        Constructs and returns a DomainProfile dataclass from config.json.
        """
        removable = self.config.get("removable_elements", {})
        keep = self.config.get("keep_elements", {})
        
        return DomainProfile(
            domain=self.domain,
            name=self.name,
            remove_tag_names=removable.get("remove_tag_names", []),
            remove_heading_keywords=removable.get("remove_heading_keywords", []),
            remove_class_keywords=removable.get("remove_class_keywords", []),
            remove_id_keywords=removable.get("remove_id_keywords", []),
            remove_aria_keywords=removable.get("remove_aria_keywords", []),
            keep_heading_keywords=keep.get("keep_heading_keywords", []),
            keep_class_keywords=keep.get("keep_class_keywords", []),
            keep_id_keywords=keep.get("keep_id_keywords", []),
            keep_tables=self.config.get("keep_tables", True),
            keep_contact_blocks=self.config.get("keep_contact_blocks", True),
            heading_keep_score=self.config.get("heading_keep_score", 10.0),
            heading_remove_score=self.config.get("heading_remove_score", -8.0),
            class_keep_score=self.config.get("class_keep_score", 5.0),
            class_remove_score=self.config.get("class_remove_score", -6.0),
            tag_remove_score=self.config.get("tag_remove_score", -20.0),
            table_score=self.config.get("table_score", 8.0),
            contact_score=self.config.get("contact_score", 10.0),
            keep_threshold=self.config.get("keep_threshold", 0.0)
        )

    def get_model(self) -> Type[BaseModel]:
        """
        Dynamically constructs a Pydantic model for Gemini response validation from schema.json.
        """
        if self._model_cache is not None:
            return self._model_cache

        extraction_fields = self.schema.get("extraction_fields", {})
        fields = {}
        
        # Core standard fields expected by the UI/Merger/Validator
        fields["page_type"] = (Optional[str], Field(default=self.config.get("name", "Web Page"), description="Type of the page (e.g. Franchise Opportunity, Company Profile, etc.)"))
        fields["confidence"] = (Optional[float], Field(default=None, description="Confidence rating between 0.0 and 1.0"))
        fields["page_title"] = (Optional[str], Field(default=None, description="Title of the page"))
        fields["page_summary"] = (Optional[str], Field(default=None, description="Brief summary of the page"))
        
        # Dynamically append extraction fields from schema.json
        for field_name, field_info in extraction_fields.items():
            field_type = field_info.get("type", "string").lower()
            field_desc = field_info.get("description", "")
            
            if field_type == "array":
                fields[field_name] = (Optional[List[str]], Field(default_factory=list, description=field_desc))
            elif field_type == "integer":
                fields[field_name] = (Optional[int], Field(default=None, description=field_desc))
            elif field_type == "number":
                fields[field_name] = (Optional[float], Field(default=None, description=field_desc))
            elif field_type == "boolean":
                fields[field_name] = (Optional[bool], Field(default=None, description=field_desc))
            else:
                fields[field_name] = (Optional[str], Field(default=None, description=field_desc))
                
        fields["faq"] = (Optional[List[FAQItem]], Field(default_factory=list, description="FAQ list"))
        fields["additional_information"] = (Optional[List[KeyValueItem]], Field(default_factory=list, description="Additional info list"))
        fields["metadata"] = (Optional[List[KeyValueItem]], Field(default_factory=list, description="Internal pipeline execution metadata"))
        fields["source_url"] = (Optional[str], Field(default=None, description="The URL of the webpage being extracted"))
        fields["extracted_at"] = (Optional[str], Field(default=None, description="Timestamp of extraction run"))

        # Attach standard methods for compatibility
        def to_clean_dict(self) -> Dict[str, Any]:
            d = self.model_dump()
            return {
                "page_title": self.page_title or self.source_url or "Untitled Page",
                "page_type": self.page_type or "Web Page",
                "page_summary": self.page_summary or "",
                "entities": {
                    self.page_type or "Web Page": [d]
                }
            }
            
        DynamicModel = create_model(
            "DynamicExtractionRecord",
            **fields,
            __base__=ExtractionResult
        )
        
        # Attach method to class
        DynamicModel.to_clean_dict = to_clean_dict
        
        self._model_cache = DynamicModel
        return DynamicModel


class AdapterLoader:
    """
    Scans the adapters/ directory, keeps a registry of domains, and matches URLs.
    """
    _ADAPTERS: Dict[str, Adapter] = {}
    _ADAPTER_LIST: List[Adapter] = []
    _DEFAULT: Optional[Adapter] = None
    _INITIALIZED = False

    @classmethod
    def initialize(cls, adapters_dir: str = "templates"):
        if cls._INITIALIZED:
            return

        abs_dir = os.path.abspath(adapters_dir)
        if not os.path.exists(abs_dir):
            os.makedirs(abs_dir, exist_ok=True)
            
        cls._ADAPTERS.clear()
        cls._ADAPTER_LIST.clear()
        
        # Scan subdirectories
        for entry in os.listdir(abs_dir):
            entry_path = os.path.join(abs_dir, entry)
            if os.path.isdir(entry_path):
                adapter = Adapter(entry_path)
                if adapter.domain == "*":
                    cls._DEFAULT = adapter
                else:
                    cls._ADAPTERS[adapter.domain] = adapter
                    cls._ADAPTER_LIST.append(adapter)
                    logger.info(f"Loaded Adapter '{adapter.name}' for domain '{adapter.domain}' (Priority: {adapter.priority})")
                    
        # Check fallback
        if cls._DEFAULT is None:
            default_dir = os.path.join(abs_dir, "default")
            os.makedirs(default_dir, exist_ok=True)
            cls._DEFAULT = Adapter(default_dir)
            
        cls._INITIALIZED = True

    @classmethod
    def load(cls, url: str) -> Adapter:
        """
        Returns the appropriate Adapter for the url, falling back to the Default adapter.
        """
        if not cls._INITIALIZED:
            cls.initialize()
            
        domain = cls._extract_domain(url)
        
        # Sort adapters by priority descending
        sorted_adapters = sorted(cls._ADAPTER_LIST, key=lambda x: x.priority, reverse=True)
        matched_adapter = None
        matched_domain = "*"
        
        for adapter in sorted_adapters:
            # Check primary domains and aliases
            for d in adapter.domains + adapter.aliases:
                if domain == d or domain.endswith("." + d):
                    matched_adapter = adapter
                    matched_domain = d
                    break
            if matched_adapter:
                break
                
        if not matched_adapter:
            # Fallback to key-based registry lookup if any
            for registered_domain, adapter in cls._ADAPTERS.items():
                if domain == registered_domain or domain.endswith("." + registered_domain):
                    matched_adapter = adapter
                    matched_domain = registered_domain
                    break
                    
        if not matched_adapter:
            matched_adapter = cls._DEFAULT
            matched_domain = "*"

        # Load dynamic diagnostic details
        schema_fields = list(matched_adapter.schema.get("extraction_fields", {}).keys())
        schema_aliases = list(matched_adapter.schema.get("aliases", {}).keys())
        target_workbook = matched_adapter.schema.get("dataset_name", "Unknown")
        schema_version = matched_adapter.schema.get("version", "1.0.0")
        primary_keys = matched_adapter.schema.get("primary_key", [])

        logger.info(
            f"\n=== Adapter Loaded ===\n"
            f"Adapter Name:    {matched_adapter.name}\n"
            f"Version:         {matched_adapter.version}\n"
            f"Priority:        {matched_adapter.priority}\n"
            f"Matched Domain:  {matched_domain}\n"
            f"Schema Version:  {schema_version}\n"
            f"Workbook Path:   {target_workbook}\n"
            f"Primary Keys:    {primary_keys}\n"
            f"Fields count:    {len(schema_fields)} {schema_fields}\n"
            f"Aliases count:   {len(schema_aliases)} {schema_aliases}\n"
            f"======================"
        )
        
        return matched_adapter

    @classmethod
    def get_all_adapters(cls) -> Dict[str, Adapter]:
        if not cls._INITIALIZED:
            cls.initialize()
        return cls._ADAPTERS

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            if "://" not in url:
                url = "https://" + url
            parsed = urlparse(url)
            hostname = (parsed.netloc or "").split(":")[0].strip().lower()
            if hostname.startswith("www."):
                hostname = hostname[4:]
            return hostname or url.lower()
        except Exception:
            return url.lower()
