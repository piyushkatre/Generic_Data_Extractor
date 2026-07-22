import json
from typing import Dict, Any, List


class ExtractionPromptBuilder:
    """
    Programmatic prompt builder that constructs instructions and schemas dynamically.
    Produces a model-agnostic prompt containing only schema details, solved fields,
    remaining guidelines, and the DOM context.
    """
    @staticmethod
    def build_prompt(
        website_name: str,
        schema: Dict[str, Any],
        structured_dom: List[Dict[str, Any]],
        extraction_rules: List[str] = None,
        deterministic_fields: List[str] = None
    ) -> str:
        if extraction_rules is None:
            extraction_rules = []
        if deterministic_fields is None:
            deterministic_fields = []

        from modules.dataset_builder.deterministic_extractor import CONCEPT_REGISTRY

        # Compact Schema serialization
        simplified_schema = {}
        ext_fields = schema.get("extraction_fields", schema.get("properties", {}))
        for field_name, info in ext_fields.items():
            simplified_schema[field_name] = {
                "type": info.get("type", "string"),
                "description": info.get("description", "")
            }
        schema_compact = json.dumps(simplified_schema)

        # 1. Identify unresolved fields and build relevance keywords
        unresolved_keywords = set()
        solved_fields_list = []
        remaining_fields_list = []

        for field_name, info in ext_fields.items():
            is_deterministic_solved = field_name in deterministic_fields

            if is_deterministic_solved:
                solved_fields_list.append(field_name)
            else:
                remaining_fields_list.append(field_name)
                unresolved_keywords.add(field_name.lower())
                unresolved_keywords.update(field_name.lower().split("_"))
                
                # Add CONCEPT_REGISTRY aliases
                aliases = CONCEPT_REGISTRY.get(field_name, [])
                for alias in aliases:
                    unresolved_keywords.add(alias.lower())
                    unresolved_keywords.update(alias.lower().split(" "))
                
                # Add key words from field description
                desc = info.get("description", "").lower()
                desc_words = [w.strip(".,;:?!()\"'") for w in desc.split() if len(w.strip(".,;:?!()\"'")) > 3]
                unresolved_keywords.update(desc_words)

        unresolved_keywords = {kw for kw in unresolved_keywords if kw and len(kw) > 2}

        # 2. Score semantic blocks in structured_dom
        scored_blocks = []
        for idx, block in enumerate(structured_dom):
            score = 0.0
            block_type = block.get("type", "")
            block_text = ""

            if block_type in ("heading", "paragraph", "link", "image", "input"):
                block_text = block.get("text", "") or block.get("placeholder", "") or block.get("alt", "") or ""
            elif block_type == "list":
                block_text = " ".join(block.get("items", []))
            elif block_type == "definition_list":
                items_texts = []
                for item in block.get("items", []):
                    items_texts.append(f"{item.get('key', '')} {item.get('value', '')}")
                block_text = " ".join(items_texts)
            elif block_type == "table":
                row_texts = []
                for row in block.get("rows", []):
                    row_texts.append(" ".join(str(cell) for cell in row))
                block_text = " ".join(row_texts)

            block_text_lower = block_text.lower()

            # Base type score
            if block_type == "heading":
                score += 15.0
            elif block_type in ("table", "definition_list", "list"):
                score += 5.0

            # Keyword matches
            for kw in unresolved_keywords:
                if kw in block_text_lower:
                    score += 15.0

            scored_blocks.append({
                "index": idx,
                "block": block,
                "score": score,
                "tokens": max(5, len(json.dumps(block)) // 4)
            })

        # Apply heading proximity boost
        for i in range(len(scored_blocks)):
            if scored_blocks[i]["block"].get("type") == "heading" and scored_blocks[i]["score"] > 15.0:
                for offset in (1, 2):
                    if i + offset < len(scored_blocks):
                        scored_blocks[i + offset]["score"] += 8.0

        # Sort by score descending to rank blocks
        scored_blocks.sort(key=lambda x: x["score"], reverse=True)

        selected_indices = set()
        current_tokens = 0
        max_budget = 4000

        # High priority structural headings first
        for sb in scored_blocks:
            if sb["block"].get("type") == "heading" and sb["score"] >= 15.0:
                selected_indices.add(sb["index"])
                current_tokens += sb["tokens"]

        # Greedy fill remaining budget
        for sb in scored_blocks:
            if sb["index"] in selected_indices:
                continue
            if current_tokens + sb["tokens"] <= max_budget:
                selected_indices.add(sb["index"])
                current_tokens += sb["tokens"]
            elif sb["score"] > 20.0 and current_tokens < 6000:
                selected_indices.add(sb["index"])
                current_tokens += sb["tokens"]

        # Ensure minimal default coverage
        if len(selected_indices) < 10:
            for sb in sorted(scored_blocks, key=lambda x: x["score"], reverse=True)[:15]:
                selected_indices.add(sb["index"])

        # Sort back to original page index order to keep document flow
        ranked_dom = [structured_dom[i] for i in sorted(list(selected_indices))]
        dom_compact = json.dumps(ranked_dom)

        # Additional Site Rules
        rules_block = ""
        if extraction_rules:
            rules_block = "\n### ADDITIONAL SITE RULES:\n" + "\n".join(f"- {rule}" for rule in extraction_rules)

        prompt = f"""Role: Structured business data extraction engine for {website_name}.

Task: Extract structured details matching the Target Schema from the DOM Blocks.

Core Rules:
1. Extract data ONLY from the supplied DOM Blocks. No external inference.
2. If evidence is missing for a field, or if it is already solved, return null.
3. Every populated field must be supported by text in the DOM.

Target Schema:
{schema_compact}

DOM Blocks:
{dom_compact}

Output Format:
- Return ONLY a single flat JSON object.
- No markdown formatting, comments, or explanations.

### ALREADY SOLVED FIELDS (Do NOT extract, return null):
{", ".join(solved_fields_list) if solved_fields_list else "None"}

### REMAINING FIELDS TO EXTRACT (Populate with value from DOM Blocks if present, otherwise return null):
{", ".join(remaining_fields_list) if remaining_fields_list else "None"}
{rules_block}
"""
        return prompt
