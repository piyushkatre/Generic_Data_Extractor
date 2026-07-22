import os
import json
from typing import Dict, Any

class SchemaLoader:
    """
    Dynamically loads schemas from the schemas/ directory based on page type.
    """
    
    def __init__(self, schemas_dir: str = "schemas"):
        # Resolve path relative to project root or use absolute path
        self.schemas_dir = os.path.abspath(schemas_dir)
        
        # Map extracted page_type categories to correct schema filenames
        self.page_type_map = {
            "franchise listing": "franchise_schema.json",
            "franchise page": "franchise_schema.json",
            "franchise": "franchise_schema.json",
            
            "company website": "company_schema.json",
            "organization": "company_schema.json",
            
            "product page": "product_schema.json",
            "product listing": "product_schema.json",
            "product": "product_schema.json",
            
            "blog": "blog_schema.json",
            "news article": "blog_schema.json",
            "article": "blog_schema.json",
            
            "government website": "government_schema.json",
            "government": "government_schema.json",
            
            "documentation": "documentation_schema.json",
            "faq": "documentation_schema.json",
            "faq page": "documentation_schema.json"
        }

    def load_schema(self, page_type: str) -> Dict[str, Any]:
        """
        Loads the appropriate schema dict for the given page_type.
        Falls back to misc_schema.json if no matching schema is found.
        """
        cleaned_type = str(page_type).strip().lower()
        filename = self.page_type_map.get(cleaned_type, "misc_schema.json")
        schema_path = os.path.join(self.schemas_dir, filename)
        
        if not os.path.exists(schema_path):
            # Fall back to misc_schema.json
            schema_path = os.path.join(self.schemas_dir, "misc_schema.json")
            if not os.path.exists(schema_path):
                # Critical fallback: default empty dictionary schema template
                return {
                    "dataset_name": "misc_dataset.xlsx",
                    "sheet_name": "General Web Data",
                    "primary_key": ["Source URL", "Title"],
                    "required_fields": ["Title", "Source URL"],
                    "aliases": {"title": "Title", "source url": "Source URL"},
                    "columns": ["Source URL", "Title", "Additional Information", "Extraction Date", "Last Updated"]
                }
                
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
