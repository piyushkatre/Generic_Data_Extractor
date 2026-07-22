import os
import re
import json
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("pipeline")


class ExtractionInspector:
    """
    Diagnostic tool to trace the journey of every schema field through the extraction pipeline.
    Observes intermediate files to identify where data loss occurs.
    """

    def __init__(self, debug_dir: str, schema: Dict[str, Any]):
        self.debug_dir = debug_dir
        self.schema = schema
        self.columns = schema.get("columns", [])
        self.extraction_fields = schema.get("extraction_fields", schema.get("properties", {}))
        
        # Load aliases mapping from schema_aliases.json
        self.aliases_map = {}
        try:
            with open("schemas/schema_aliases.json", "r", encoding="utf-8") as f:
                self.aliases_map = json.load(f)
        except Exception as e:
            logger.warning(f"[Inspector] Could not load schemas/schema_aliases.json: {e}")

        # Intermediate file content caches
        self.raw_html = self._read_file("01_rendered.html")
        self.clean_html = self._read_file("02_cleaned.html")
        self.relevant_dom = self._read_file("03_relevant.html")
        self.dom_blocks = self._read_json("04_blocks.json")
        self.prompt = self._read_file("05_prompt.txt")
        
        # Support both Gemini and Ollama debug outputs
        self.llm_out = self._read_json("06_gemini.json")
        if not self.llm_out:
            self.llm_out = self._read_json("06_ollama_normalized.json")
            if not self.llm_out:
                raw_ollama = self._read_file("06_ollama_raw_response.json")
                if raw_ollama:
                    try:
                        self.llm_out = json.loads(raw_ollama)
                    except Exception:
                        pass
        if not self.llm_out:
            self.llm_out = {}
            
        self.validated = self._read_json("07_validated.json") or {}
        self.mapping = self._read_json("08_mapping.json") or {}
        self.final_row = self._read_json("09_final_row.json") or {}
        self.layouts_trace = self._read_json("05_layouts.json") or []

        # Resolve deterministic & LLM solved lists from validated record metadata
        self.fields_from_dom = set()
        self.fields_from_gemini = set()
        
        metadata = self.validated.get("metadata", [])
        if isinstance(metadata, list):
            for item in metadata:
                if isinstance(item, dict):
                    k = item.get("key")
                    v = item.get("value")
                else:
                    k = getattr(item, "key", None)
                    v = getattr(item, "value", None)
                if k == "fields_from_dom" and v:
                    self.fields_from_dom = set(x.strip() for x in str(v).split(",") if x.strip())
                elif k == "fields_from_gemini" and v:
                    self.fields_from_gemini = set(x.strip() for x in str(v).split(",") if x.strip())

    def _read_file(self, filename: str) -> str:
        path = os.path.join(self.debug_dir, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return ""

    def _read_json(self, filename: str) -> Any:
        content = self._read_file(filename)
        if content:
            try:
                return json.loads(content)
            except Exception:
                pass
        return None

    def _check_text_presence(self, text: str, field: str, raw_extracted_val: Any) -> bool:
        if not text:
            return False
        
        # 1. Search by extracted value if present
        if raw_extracted_val not in (None, "", [], {}):
            if isinstance(raw_extracted_val, list):
                # Check if any list item is present
                for item in raw_extracted_val:
                    if str(item).lower().strip() in text.lower():
                        return True
            else:
                val_str = str(raw_extracted_val).lower().strip()
                if val_str and val_str in text.lower():
                    return True

        # 2. Search by key name aliases
        aliases = self.aliases_map.get(field, [])
        variations = {field, field.replace("_", " "), field.replace("_", " ").title()}
        for a in aliases:
            variations.add(a)
            variations.add(a.lower())
            variations.add(a.title())
            
        for var in variations:
            if var.lower().strip() in text.lower():
                return True
                
        return False

    def get_excel_column(self, field: str) -> Optional[str]:
        # Maps canonical key to resolved column name using SchemaMapper and AliasRegistry
        from modules.dataset_builder.schema_mapper import SchemaMapper
        try:
            mapper = SchemaMapper(excel_columns=self.columns, schema=self.schema)
            col, score, match_type = mapper.registry.resolve_field_to_column(field)
            if col:
                return col
        except Exception:
            pass
            
        # Fallback manual checks
        for alias, col_name in self.schema.get("aliases", {}).items():
            if alias.lower().strip() == field.lower().strip():
                return col_name
        return None

    def inspect_field(self, field: str) -> Dict[str, Any]:
        # Determine raw extracted values
        det_val = None
        # We can look up if it was solved in the DOM blocks/metadata
        is_det_solved = field in self.fields_from_dom
        
        llm_val = self.llm_out.get(field)
        val_val = self.validated.get(field)
        
        # Check source raw value to check in DOM/HTML
        raw_val = val_val if val_val not in (None, "", [], {}) else (llm_val if llm_val not in (None, "", [], {}) else None)
        
        # 1. Raw HTML presence
        has_raw = self._check_text_presence(self.raw_html, field, raw_val)
        
        # 2. Cleaned HTML presence
        has_clean = self._check_text_presence(self.clean_html, field, raw_val) if has_raw else False
        
        # 3. Relevant DOM presence
        has_rel = self._check_text_presence(self.relevant_dom, field, raw_val) if has_clean else False
        
        # 4. DOM Blocks presence
        # Serialize block content to search it
        blocks_text = ""
        if self.dom_blocks:
            blocks_text = json.dumps(self.dom_blocks)
        has_blocks = self._check_text_presence(blocks_text, field, raw_val) if has_rel else False

        # 5. Deterministic Solving Status
        det_status = "YES" if is_det_solved else "NO"

        # 6. Prompt Status
        prompt_status = "NOT APPLICABLE"
        if self.prompt:
            # Check solved block
            solved_match = re.search(rf"- {field} \(Type:.*?\): Sourced deterministically", self.prompt)
            if solved_match:
                prompt_status = "SKIPPED (already solved)"
            else:
                # Check guideline block
                rem_match = re.search(rf"Field: {field}\b", self.prompt)
                if rem_match:
                    prompt_status = "INCLUDED"

        # 7. LLM Output Status
        if prompt_status == "SKIPPED (already solved)":
            llm_status = "NOT REQUESTED"
        elif prompt_status == "INCLUDED":
            llm_status = "YES" if llm_val not in (None, "", [], {}) else "NULL"
        else:
            llm_status = "NOT REQUESTED"

        # 8. Validator Status
        if is_det_solved or llm_status == "YES":
            if val_val not in (None, "", [], {}):
                val_status = "PASSED"
            else:
                val_status = "REJECTED"
        else:
            val_status = "NOT EXECUTED"

        # 9. Schema Mapper Status
        excel_col = self.get_excel_column(field)
        excel_val = self.final_row.get(excel_col) if excel_col else None
        
        if val_status == "PASSED":
            if excel_val not in (None, "", [], {}):
                mapper_status = "PASSED"
            else:
                mapper_status = "DROPPED"
        else:
            mapper_status = "EMPTY"

        # 10. Excel Status
        excel_status = "WRITTEN" if mapper_status == "PASSED" else "EMPTY"

        # Determine Final Source
        if excel_status == "WRITTEN":
            final_source = "Deterministic" if is_det_solved else "LLM"
        else:
            final_source = "None"

        # Determine First Loss Stage and Reason
        first_loss = None
        reason = None

        if not has_raw:
            first_loss = "Raw HTML"
            reason = "Field does not exist on webpage."
        elif not has_clean:
            first_loss = "Cleaned HTML"
            reason = "Removed during HTML preprocessing (cleaning)."
        elif not has_rel:
            first_loss = "Relevant DOM"
            reason = "Filtered out by Relevant DOM score/pruning threshold."
        elif not has_blocks:
            first_loss = "DOM Blocks"
            reason = "Dropped by DOM semantic block builder."
        elif is_det_solved and val_status == "REJECTED":
            first_loss = "Validator"
            reason = "Deterministic value failed validation / formatting normalization."
        elif prompt_status == "INCLUDED" and llm_status == "NULL":
            first_loss = "LLM Extraction"
            reason = "Model failed to extract despite receiving the information."
        elif prompt_status == "INCLUDED" and llm_status == "YES" and val_status == "REJECTED":
            first_loss = "Validator"
            reason = "Failed validation or normalization (e.g. format/range check)."
        elif val_status == "PASSED" and mapper_status == "DROPPED":
            first_loss = "Schema Mapper"
            reason = "Dropped during mapping because the field has no target column in the destination schema."
        elif not is_det_solved and prompt_status == "NOT APPLICABLE":
            # Deterministic-only field with fallback disabled, and deterministic matching failed
            first_loss = "Deterministic Extraction"
            reason = "Deterministic regex / selector patterns failed to match."

        return {
            "field": field,
            "raw": "YES" if has_raw else "NO",
            "clean": "YES" if has_clean else "NO",
            "rel": "YES" if has_rel else "NO",
            "blocks": "YES" if has_blocks else "NO",
            "det": det_status,
            "prompt": prompt_status,
            "llm": llm_status,
            "val": val_status,
            "mapper": mapper_status,
            "excel": excel_status,
            "final_source": final_source,
            "first_loss": first_loss,
            "reason": reason
        }

    def generate_journey_report(self, output_path: str = "debug/extraction_journey.md"):
        # Make parent directories of target report file
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        fields = sorted(list(self.extraction_fields.keys()))
        if not fields:
            # Fall back to strategic registry fields if empty
            from core.field_strategy import FIELD_STRATEGY
            fields = sorted([f for f in FIELD_STRATEGY.keys() if f not in ("entities", "faq", "additional_information", "metadata")])

        journeys = []
        for field in fields:
            journey = self.inspect_field(field)
            journeys.append(journey)

        # Compute summary metrics
        total_fields = len(journeys)
        present_on_page = sum(1 for j in journeys if j["raw"] == "YES")
        lost_before_rel = sum(1 for j in journeys if j["raw"] == "YES" and j["rel"] == "NO")
        lost_in_blocks = sum(1 for j in journeys if j["rel"] == "YES" and j["blocks"] == "NO")
        lost_in_det = sum(1 for j in journeys if j["first_loss"] == "Deterministic Extraction")
        lost_in_llm = sum(1 for j in journeys if j["first_loss"] == "LLM Extraction")
        rejected_val = sum(1 for j in journeys if j["first_loss"] == "Validator")
        dropped_mapper = sum(1 for j in journeys if j["first_loss"] == "Schema Mapper")
        written_success = sum(1 for j in journeys if j["excel"] == "WRITTEN")

        # Compute stage breakdowns
        raw_count = present_on_page
        clean_count = sum(1 for j in journeys if j["clean"] == "YES")
        rel_count = sum(1 for j in journeys if j["rel"] == "YES")
        blocks_count = sum(1 for j in journeys if j["blocks"] == "YES")
        
        # Solve counts
        det_solve = sum(1 for j in journeys if j["det"] == "YES")
        llm_solve = sum(1 for j in journeys if j["llm"] == "YES")
        val_pass = sum(1 for j in journeys if j["val"] == "PASSED")
        mapper_pass = sum(1 for j in journeys if j["mapper"] == "PASSED")
        excel_written = written_success

        # Format markdown content
        md = []
        md.append("# Extraction Journey & Field Loss Diagnostic Report\n")
        md.append(f"**Target Debug Folder**: `{self.debug_dir}`  ")
        md.append(f"**Generated On**: `{os.path.basename(self.debug_dir)}`  \n")
        md.append("This report traces the complete journey of every schema field through the pipeline to locate where it was lost.\n")
        md.append("---")

        # Field Journey details
        for j in journeys:
            field = j["field"]
            md.append(f"### Field: `{field}`\n")
            md.append(f"Raw HTML ................. {j['raw']}")
            md.append(f"Cleaned HTML ............. {j['clean']}")
            md.append(f"Relevant DOM ............. {j['rel']}")
            md.append(f"DOM Blocks ............... {j['blocks']}")
            md.append(f"Deterministic ............ {j['det']}")
            md.append(f"Prompt ................... {j['prompt']}")
            md.append(f"LLM ...................... {j['llm']}")
            md.append(f"Validator ............... {j['val']}")
            md.append(f"Schema Mapper ............ {j['mapper']}")
            md.append(f"Excel .................... {j['excel']}\n")
            
            md.append(f"**Final Source**: {j['final_source']}")
            if j["first_loss"]:
                md.append(f"**First Loss Stage**: {j['first_loss']}")
                md.append(f"**Reason**: {j['reason']}\n")
            else:
                md.append("")
            md.append("---")

        # Statistics Summary section
        md.append("\n=====================================")
        md.append("EXTRACTION SUMMARY")
        md.append("=====================================")
        md.append(f"Total Schema Fields: {total_fields}")
        md.append(f"Fields Present on Page: {present_on_page}")
        md.append(f"Lost before Relevant DOM: {lost_before_rel}")
        md.append(f"Lost in DOM Builder: {lost_in_blocks}")
        md.append(f"Lost in Deterministic: {lost_in_det}")
        md.append(f"Lost in LLM: {lost_in_llm}")
        md.append(f"Rejected by Validator: {rejected_val}")
        md.append(f"Dropped by Schema Mapper: {dropped_mapper}")
        md.append(f"Successfully Written: {written_success}")
        md.append("=====================================\n")

        # Breakdown by stage
        md.append("### Stage-by-Stage Field Breakdown:")
        md.append(f"Raw HTML ............... {raw_count}")
        md.append(f"Cleaned HTML ........... {clean_count}")
        md.append(f"Relevant DOM ........... {rel_count}")
        md.append(f"DOM Blocks ............. {blocks_count}")
        md.append(f"Deterministic Solved ... {det_solve}")
        md.append(f"LLM Solved ............. {llm_solve}")
        md.append(f"Validator Passed ....... {val_pass}")
        md.append(f"Mapper Passed .......... {mapper_pass}")
        md.append(f"Excel Written .......... {excel_written}\n")

        # Compute layout statistics
        layout_metrics = {}
        total_layouts = len(self.layouts_trace)
        layouts_with_extractions = 0
        
        for entry in self.layouts_trace:
            l_type = entry.get("type", "Unknown Layout")
            fields_ext = entry.get("extracted_fields", [])
            
            if l_type not in layout_metrics:
                layout_metrics[l_type] = {
                    "count": 0,
                    "extracted_count": 0,
                    "fields": set()
                }
            layout_metrics[l_type]["count"] += 1
            if fields_ext:
                layout_metrics[l_type]["extracted_count"] += 1
                layout_metrics[l_type]["fields"].update(fields_ext)
                layouts_with_extractions += 1

        md.append("### Layout Coverage Breakdown:")
        if total_layouts > 0:
            overall_layout_coverage = (layouts_with_extractions / total_layouts) * 100
            md.append(f"Total Layouts Detected: {total_layouts}  ")
            md.append(f"Layouts with Successful Extractions: {layouts_with_extractions} ({overall_layout_coverage:.1f}%)\n")
            
            md.append("| Layout Class | Total Detected | Successfully Solved | Layout Coverage % | Fields Extracted |")
            md.append("| --- | --- | --- | --- | --- |")
            for l_type, stats in sorted(layout_metrics.items()):
                cov_pct = (stats["extracted_count"] / stats["count"]) * 100
                fields_str = ", ".join(sorted(list(stats["fields"]))) if stats["fields"] else "None"
                md.append(f"| {l_type} | {stats['count']} | {stats['extracted_count']} | {cov_pct:.1f}% | {fields_str} |")
        else:
            md.append("No layout trace data (05_layouts.json) was found or recorded.")
        md.append("\n")

        # Write report to file
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md))

        logger.info(f"[Diagnostic Inspector] Field journey diagnostic report successfully written to {output_path}")
