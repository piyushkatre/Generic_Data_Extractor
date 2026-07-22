from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from modules.gemini import ExtractionResult, ExtractedEntity, ExtractedRecord, KeyValue
from utils.logger import get_logger

logger = get_logger(__name__)

class AIResultMerger:
    """
    AI Result Merger and Knowledge Consolidator.
    Consolidates multiple structured ExtractionResult outputs into a single cohesive structure,
    deduplicating entities and merging records.
    """

    def merge(self, results: List[ExtractionResult] | Any) -> ExtractionResult:
        """
        Merge multiple chunk-level ExtractionResult objects into one consolidated ExtractionResult.
        Supports both lists of ExtractionResult and orchestration/result wrapper shapes.
        """
        # Unwrap if we receive a wrapper model instead of a direct list
        if not isinstance(results, list):
            if hasattr(results, "chunk_results"):
                unwrapped = []
                for cr in results.chunk_results:
                    if hasattr(cr, "gemini_response") and cr.gemini_response:
                        if isinstance(cr.gemini_response, dict):
                            unwrapped.append(self._dict_to_model(cr.gemini_response))
                        else:
                            unwrapped.append(cr.gemini_response)
                results = unwrapped
            else:
                results = [results]

        valid_results = [r for r in results if r is not None]
        if not valid_results:
            return ExtractionResult()

        first = valid_results[0]
        merged_dict = first.model_dump()

        # Merge subsequent results
        for r in valid_results[1:]:
            r_dict = r.model_dump()
            for k, v in r_dict.items():
                if v is None:
                    continue
                # If current is empty or list is empty, take the new one
                current = merged_dict.get(k)
                if current is None or current == "" or current == []:
                    merged_dict[k] = v
                # Merge lists (skip entities here, we merge it below if generic)
                elif k != "entities" and isinstance(v, list) and isinstance(current, list):
                    seen = set()
                    combined = []
                    for item in current + v:
                        item_str = json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item)
                        if item_str not in seen:
                            seen.add(item_str)
                            combined.append(item)
                    merged_dict[k] = combined
                # Concatenate longer text details
                elif isinstance(v, str) and isinstance(current, str):
                    if v.strip() and v.strip() not in current:
                        if k in ("page_summary", "additional_information", "description", "about", "business_model"):
                            merged_dict[k] = current + "\n" + v

        # If generic entities exist, merge them using legacy deduplication logic
        has_generic_entities = False
        for r in valid_results:
            for ent in r.entities:
                if ent.entity_type != "Franchise Opportunity":
                    has_generic_entities = True
                    break

        if has_generic_entities:
            entity_records = {}
            for r in valid_results:
                for entity in r.entities:
                    e_type = entity.entity_type
                    if e_type not in entity_records:
                        entity_records[e_type] = []
                    for rec in entity.records:
                        is_duplicate = False
                        rec_attrs = {attr.key: attr.value for attr in rec.attributes}
                        for existing in entity_records[e_type]:
                            existing_attrs = {attr.key: attr.value for attr in existing.attributes}
                            if rec_attrs == existing_attrs:
                                is_duplicate = True
                                break
                        if not is_duplicate:
                            entity_records[e_type].append(rec)
            merged_entities = []
            for e_type, records in entity_records.items():
                merged_entities.append(ExtractedEntity(entity_type=e_type, records=records))
            merged_dict["entities"] = merged_entities

        return ExtractionResult(**merged_dict)

    def _dict_to_model(self, data: Dict[str, Any]) -> ExtractionResult:
        """
        Helper to convert a dictionary format to an ExtractionResult Pydantic model.
        """
        import json
        if "entities" in data:
            flat_data = {}
            for k, v in data.items():
                if k != "entities":
                    flat_data[k] = v
            
            raw_entities = data.get("entities", {})
            if isinstance(raw_entities, dict):
                for ent_list in raw_entities.values():
                    for item in ent_list:
                        if isinstance(item, dict):
                            for ik, iv in item.items():
                                flat_data.setdefault(ik, iv)
            elif isinstance(raw_entities, list):
                for ent in raw_entities:
                    for rec in ent.get("records", []):
                        for attr in rec.get("attributes", []):
                            flat_data.setdefault(attr.get("key", ""), attr.get("value", ""))

            return ExtractionResult(**flat_data)

        return ExtractionResult(**data)
