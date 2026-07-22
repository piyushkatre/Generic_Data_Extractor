import os
import csv
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from modules.gemini import ExtractionResult
from modules.evaluation.validators import OfflineValidator
from modules.evaluation.dom_checker import DOMChecker
from modules.evaluation.report import EvaluationReport
from utils.logger import get_logger

logger = get_logger(__name__)

class ExtractionQualityEvaluator:
    """
    Evaluates extraction results offline, computing advanced confidence rating
    incorporating critical fields weightings, validation success, hallucination penalties,
    and logs benchmark metrics.
    """

    CRITICAL_FIELDS = [
        "franchise_name",
        "investment_required",
        "area_required",
        "phone",
        "email",
        "website",
        "business_model",
        "business_support"
    ]

    ALL_SCHEMA_FIELDS = [
        "page_type",
        "source_url",
        "franchise_name",
        "brand",
        "industry",
        "category",
        "description",
        "about",
        "business_model",
        "investment_required",
        "franchise_fee",
        "royalty",
        "roi",
        "payback_period",
        "area_required",
        "store_size",
        "products",
        "services",
        "training",
        "marketing_support",
        "business_support",
        "contact_person",
        "phone",
        "email",
        "website",
        "address",
        "city",
        "state",
        "country",
        "facebook",
        "instagram",
        "linkedin",
        "youtube",
        "faq",
        "images",
        "documents",
        "additional_information"
    ]

    def evaluate(
        self,
        result: ExtractionResult,
        html_content: str,
        execution_time: float = 0.0,
        token_count: int = 0,
        schema_required: Optional[List[str]] = None,
        source_url: str = ""
    ) -> Dict[str, Any]:
        """
        Runs advanced offline quality checks and computes a realistic confidence score.
        """
        if result is None:
            return {
                "coverage_ratio": "0 / 0",
                "coverage_percentage": 0.0,
                "confidence_score": 0.0,
                "completeness_score": 0.0,
                "dom_match_score": 0.0,
                "field_statuses": {},
                "likely_missed_fields": [],
                "missing_on_page_fields": [],
                "hallucinations": [],
                "validation_warnings": []
            }

        result_dict = result.model_dump()
        dom = DOMChecker(html_content)

        fields_extracted = 0
        total_fields = len(self.ALL_SCHEMA_FIELDS)
        
        field_statuses = {}
        likely_missed_fields = []
        missing_on_page_fields = []
        hallucinations = []
        validation_warnings = []
        
        non_empty_extracted = 0

        # Normalise schema required fields to check completion
        norm_required = []
        if schema_required:
            for req in schema_required:
                rc = req.strip().lower().replace(" / ", "_").replace(" ", "_")
                norm_required.append(rc)
        else:
            # Fallback to standard required fields
            norm_required = ["franchise_name", "source_url"]

        req_fields_populated = 0
        total_req_fields = len(norm_required)

        critical_fields_missing_list = []

        for field in self.ALL_SCHEMA_FIELDS:
            val = result_dict.get(field)
            
            is_populated = False
            if val is not None:
                if isinstance(val, list):
                    is_populated = len(val) > 0
                elif isinstance(val, str):
                    is_populated = len(val.strip()) > 0
                else:
                    is_populated = True

            # Track required field completion
            if field in norm_required:
                if is_populated:
                    req_fields_populated += 1

            if is_populated:
                fields_extracted += 1
                non_empty_extracted += 1
                
                # Validation checks (distinct per field)
                warnings = self._run_offline_validation(field, val)
                validation_warnings.extend(warnings)
                
                # Hallucination check (semantic matching - skip metadata fields)
                if field in ("page_type", "source_url", "additional_information"):
                    field_statuses[field] = "Extracted Successfully"
                else:
                    in_dom = dom.is_value_in_dom(val, field)
                    if not in_dom:
                        hallucinations.append({
                            "field": field,
                            "value": val,
                            "warning": f"Possible Hallucination: value '{val}' not found in DOM."
                        })
                        field_statuses[field] = "Possible Hallucination"
                    else:
                        field_statuses[field] = "Extracted Successfully"
            else:
                # Field is missing. Run value-aware patterns checker
                if field in ("page_type", "source_url", "additional_information"):
                    field_statuses[field] = "Null"
                    missing_on_page_fields.append(field)
                    continue

                has_actual_val = dom.has_actual_value_in_dom(field)
                if has_actual_val:
                    field_statuses[field] = "Likely Missed"
                    likely_missed_fields.append(field)
                    if field in self.CRITICAL_FIELDS:
                        critical_fields_missing_list.append(field)
                else:
                    field_statuses[field] = "Missing on Page"
                    missing_on_page_fields.append(field)
                    if field in self.CRITICAL_FIELDS:
                        critical_fields_missing_list.append(field)

        # ── Step 5: Advanced Confidence Score Formulation ──
        
        # 1. Coverage Score (30% weight)
        # Coverage = Extracted and Valid / Fields Actually Present On Page
        fields_extracted_and_valid = fields_extracted - len(hallucinations)
        fields_actually_present = max(1, fields_extracted_and_valid + len(likely_missed_fields))
        coverage_percentage = (fields_extracted_and_valid / fields_actually_present) * 100
        
        # Completeness Score (for report payload)
        completeness_score = (non_empty_extracted / fields_extracted * 100) if fields_extracted > 0 else 0.0

        # 2. DOM Match Score (30% weight)
        # Deduct based on missed and hallucinated fields
        dom_deductions = (len(likely_missed_fields) * 15) + (len(hallucinations) * 25)
        dom_match_score = max(0.0, 100.0 - dom_deductions)
        
        # 3. Required Fields Completion (20% weight)
        req_completion_score = (req_fields_populated / total_req_fields * 100) if total_req_fields > 0 else 100.0
        
        # 4. Validation Success Rate (20% weight)
        # Deduct proportion of invalid fields
        val_warnings_count = len(validation_warnings)
        validation_success = max(0.0, 100.0 - (val_warnings_count * 10))
        
        # Base confidence calculation
        base_score = (
            (coverage_percentage * 0.3) +
            (dom_match_score * 0.3) +
            (req_completion_score * 0.2) +
            (validation_success * 0.2)
        )
        
        # 5. Penalties
        # Hallucination Penalty: -15 points per hallucination
        hallucination_penalty = len(hallucinations) * 15.0
        
        # Critical Fields Missing Penalties:
        # -10 for Likely Missed (present in DOM but Gemini missed)
        # -3 for Missing on Page (absent in DOM)
        critical_penalty = 0.0
        for cf in self.CRITICAL_FIELDS:
            status = field_statuses.get(cf)
            if status == "Likely Missed":
                critical_penalty += 10.0
            elif status == "Missing on Page":
                critical_penalty += 3.0

        confidence_score = max(0.0, min(100.0, base_score - hallucination_penalty - critical_penalty))

        report_data = {
            "coverage_ratio": f"{fields_extracted_and_valid} / {fields_actually_present}",
            "coverage_percentage": coverage_percentage,
            "confidence_score": confidence_score,
            "completeness_score": completeness_score,
            "dom_match_score": dom_match_score,
            "field_statuses": field_statuses,
            "likely_missed_fields": likely_missed_fields,
            "missing_on_page_fields": missing_on_page_fields,
            "hallucinations": hallucinations,
            "validation_warnings": validation_warnings
        }

        # ── Step 7: Benchmark Metrics Logger ──
        log_metrics = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "url": source_url or result.source_url or "Unknown URL",
            "coverage": report_data["coverage_ratio"],
            "dom_match": f"{dom_match_score:.1f}%",
            "confidence": f"{confidence_score:.1f}%",
            "hallucinations": len(hallucinations),
            "critical_fields_missing": ", ".join(critical_fields_missing_list) or "None",
            "execution_time_sec": f"{execution_time:.2f}",
            "token_count": token_count
        }
        self._log_benchmark(log_metrics)

        # ── Step 8: Logging ──
        report_text = EvaluationReport.generate_summary_text(report_data)
        logger.info(f"\n{report_text}")

        return report_data

    def _log_benchmark(self, metrics: Dict[str, Any], filepath: str = "benchmarks/benchmark_log.csv"):
        """
        Appends quality metrics and performance benchmarks to a local CSV file.
        """
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            file_exists = os.path.exists(filepath)
            
            with open(filepath, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=[
                    "timestamp", "url", "coverage", "dom_match", "confidence",
                    "hallucinations", "critical_fields_missing", "execution_time_sec", "token_count"
                ])
                if not file_exists:
                    writer.writeheader()
                writer.writerow(metrics)
                
            logger.info(f"Quality benchmarks logged to {os.path.abspath(filepath)}")
        except Exception as e:
            logger.error(f"Failed to log quality benchmarks: {e}", exc_info=True)

    def _run_offline_validation(self, field: str, val: Any) -> List[str]:
        warnings = []
        if not val:
            return warnings

        if field == "email":
            warnings.extend(OfflineValidator.validate_email(val))
        elif field == "phone":
            warnings.extend(OfflineValidator.validate_phone(val))
        elif field in ("website", "facebook", "instagram", "linkedin", "youtube"):
            warnings.extend(OfflineValidator.validate_url(val, field))
        elif field in ("investment_required", "franchise_fee", "royalty"):
            warnings.extend(OfflineValidator.validate_investment(val))
        elif field == "roi":
            warnings.extend(OfflineValidator.validate_roi(val))
        elif field == "area_required":
            warnings.extend(OfflineValidator.validate_area(val))
        elif field in ("products", "services", "faq", "images", "documents"):
            warnings.extend(OfflineValidator.validate_list_field(val, field))
        elif field in ("established_year", "franchise_since"):
            warnings.extend(OfflineValidator.validate_date(val, field))
            
        return warnings
