import logging

logger = logging.getLogger("pipeline")

FIELD_STRATEGY = {
    # General Fields
    "franchise_name": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Primary franchise name extracted hybridly (prefers deterministic div/meta checks first)."
    },
    "brand": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Franchise brand name, hybrid fallback."
    },
    "page_type": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Semantic page type classification."
    },
    "category": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Franchise category listing tag."
    },
    "industry": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Broad industry sector."
    },
    "segment": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Industry sub-segment."
    },
    "description": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "General opportunity description."
    },
    "about": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Detailed company background."
    },

    # Business Fields
    "business_model": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": True,
        "notes": "Concept summary model."
    },
    "concept": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Detailed business concept."
    },
    "founded_year": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Year founded, regex matched."
    },
    "franchise_start_year": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Commencement of franchising."
    },
    "operations_commenced": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Operations commencement date."
    },
    "established_year": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Established year."
    },
    "number_of_outlets": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Active store outlets count."
    },
    "number_of_employees": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Staff count."
    },
    "franchise_since": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Duration franchising active."
    },

    # Financial Fields
    "investment_required": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Required total capital range."
    },
    "investment_min": {
        "owner": "deterministic",
        "allow_fallback": False,
        "merge_policy": "deterministic_only",
        "expected_type": "float",
        "priority": False,
        "notes": "Numeric lower-bound investment."
    },
    "investment_max": {
        "owner": "deterministic",
        "allow_fallback": False,
        "merge_policy": "deterministic_only",
        "expected_type": "float",
        "priority": False,
        "notes": "Numeric upper-bound investment."
    },
    "franchise_fee": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Franchise entry fee."
    },
    "royalty": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Monthly royalty/commission."
    },
    "roi": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Expected return metrics."
    },
    "payback_period": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Estimated payback period."
    },
    "agreement_duration": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Agreement duration."
    },

    # Infrastructure
    "area_required": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Store floor space requirements."
    },
    "area_min": {
        "owner": "deterministic",
        "allow_fallback": False,
        "merge_policy": "deterministic_only",
        "expected_type": "float",
        "priority": False,
        "notes": "Lower-bound store space."
    },
    "area_max": {
        "owner": "deterministic",
        "allow_fallback": False,
        "merge_policy": "deterministic_only",
        "expected_type": "float",
        "priority": False,
        "notes": "Upper-bound store space."
    },

    # Support & Training
    "training": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Initial/ongoing training support."
    },
    "support": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "General operations support."
    },
    "marketing_support": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Marketing/branding guidelines."
    },
    "operational_support": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Logistics and operations guidance."
    },
    "business_support": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Business assistance."
    },

    # Contact & Socials
    "phone": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Contact telephone numbers."
    },
    "email": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Contact email addresses."
    },
    "website": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": True,
        "notes": "Official website URL."
    },
    "address": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Office/store physical address."
    },
    "city": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Head office city."
    },
    "state": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Head office state."
    },
    "country": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Head office country."
    },
    "facebook": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Facebook page URL."
    },
    "instagram": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Instagram profile link."
    },
    "linkedin": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "LinkedIn profile link."
    },
    "twitter": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Twitter/X link."
    },
    "youtube": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "YouTube channel link."
    },
    "whatsapp_link": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Direct WhatsApp message URL."
    },

    # Media & Docs
    "logo": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Logo alt text."
    },
    "logo_url": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Logo source image URL."
    },
    "images": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "list",
        "priority": False,
        "notes": "Store gallery image URLs."
    },
    "brochures": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "list",
        "priority": False,
        "notes": "Brochure PDFs list."
    },
    "documents": {
        "owner": "deterministic",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "list",
        "priority": False,
        "notes": "Supplementary PDFs list."
    },

    # FAQ & Raw Ext
    "faq": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "list",
        "priority": False,
        "notes": "Frequently asked questions list."
    },
    "additional_information": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "list",
        "priority": False,
        "notes": "Extra key-value pairs block."
    },
    "metadata": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "list",
        "priority": False,
        "notes": "Pipeline debugging log lists."
    },
    "entities": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "list",
        "priority": False,
        "notes": "Entity-specific mappings."
    },

    # Pipeline Meta / Evaluator UI compatibility
    "source_url": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Source webpage URL."
    },
    "extracted_at": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Extraction date-time."
    },
    "confidence": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "float",
        "priority": False,
        "notes": "Confidence score."
    },
    "page_title": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Page header title."
    },
    "page_summary": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Summary of the page."
    },
    "products": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "list",
        "priority": False,
        "notes": "List of products."
    },
    "services": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "list",
        "priority": False,
        "notes": "List of services."
    },
    "preferred_locations": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Locations preferred."
    },
    "expansion_locations": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Locations for expansion."
    },
    "expected_hours": {
        "owner": "hybrid",
        "allow_fallback": True,
        "merge_policy": "deterministic_first",
        "expected_type": "string",
        "priority": False,
        "notes": "Expected franchise hours."
    },
    "contact_person": {
        "owner": "llm",
        "allow_fallback": False,
        "merge_policy": "llm_only",
        "expected_type": "string",
        "priority": False,
        "notes": "Contact person name."
    }
}


def get_strategy(field_name: str) -> dict:
    """
    Returns the strategy configuration dictionary for a field.
    Defaults to semantic LLM configuration if unrecognized.
    """
    return FIELD_STRATEGY.get(
        field_name,
        {
            "owner": "llm",
            "allow_fallback": False,
            "merge_policy": "llm_only",
            "expected_type": "string",
            "priority": False,
            "notes": "Default fallback strategy."
        }
    )


def print_registry_summary():
    """
    Prints a clean registry summary formatted for logs.
    """
    total = len(FIELD_STRATEGY)
    det = sum(1 for f in FIELD_STRATEGY.values() if f["owner"] == "deterministic")
    hyb = sum(1 for f in FIELD_STRATEGY.values() if f["owner"] == "hybrid")
    llm = sum(1 for f in FIELD_STRATEGY.values() if f["owner"] == "llm")
    
    summary = (
        "\n--------------------------------------\n"
        "Field Strategy Registry\n"
        f"Total fields : {total}\n"
        f"Deterministic : {det}\n"
        f"Hybrid        : {hyb}\n"
        f"LLM           : {llm}\n"
        "--------------------------------------\n"
    )
    logger.info(summary)
