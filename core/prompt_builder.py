import json
from typing import Dict, Any, List

from core.field_matching import normalize_field_name


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

        ext_fields = schema.get("extraction_fields", schema.get("properties", {}))
        all_field_names = list(ext_fields.keys())

        # 1. Identify unresolved fields and build relevance keywords
        unresolved_keywords = set()
        solved_fields_list = []
        remaining_fields_list = []

        # Deterministic field names come from DeterministicExtractor's own
        # canonical snake_case vocabulary, which won't generally match a
        # schema's own field names verbatim (e.g. "Franchise Fee" vs
        # "franchise_fee") - compare normalized identities instead. The
        # schema's own field_name (never the normalized form) is what gets
        # used everywhere else below (prompt text, column names, etc).
        normalized_deterministic_fields = {normalize_field_name(f) for f in deterministic_fields}

        for field_name, info in ext_fields.items():
            is_deterministic_solved = normalize_field_name(field_name) in normalized_deterministic_fields

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

        # 3. Human-readable field definitions - remaining fields ONLY. A
        # field already solved deterministically doesn't need its
        # description/aliases explained to the LLM at all (it's never
        # asked to touch that field), so skipping solved fields here keeps
        # this section's token cost proportional to what the LLM actually
        # has to do, not to the schema's total size. One line per field:
        # "- Name: description. (aliases: a, b, c)" - each clause included
        # only when the schema actually declares it, so a bare field with
        # neither produces just "- Name".
        field_definition_lines = []
        for field_name in remaining_fields_list:
            info = ext_fields[field_name]
            line = f"- {field_name}"
            description = (info.get("description") or "").strip()
            if description:
                line += f": {description}"
            # Some schemas list the field's own name as one of its own
            # aliases (a harmless authoring pattern - the field-identity
            # matching elsewhere already handles this fine). It carries no
            # information here, so it's dropped to keep this line as short
            # as the genuinely distinct aliases warrant.
            aliases = [a for a in (info.get("aliases") or []) if a.strip().lower() != field_name.strip().lower()]
            if aliases:
                line += f" (aliases: {', '.join(aliases)})"
            field_definition_lines.append(line)
        schema_fields_block = "\n".join(field_definition_lines) if field_definition_lines else "None"

        # Additional site rules (from WebsiteConfig.extraction_rules) fold
        # into General Rules as an optional tail, rather than a separate
        # section - same content as before, just relocated.
        site_rules_block = ""
        if extraction_rules:
            site_rules_block = "\n" + "\n".join(f"- {rule}" for rule in extraction_rules)

        prompt = f"""Role: Structured business data extraction engine for {website_name}.

## 1. TASK
Extract values for the fields listed in "SCHEMA FIELDS" below, using ONLY the content in "DOM CONTENT". Fields listed under "ALREADY EXTRACTED FIELDS" were already found deterministically - always return null for those, never re-extract or contradict them.

## 2. GENERAL RULES
- Search the ENTIRE DOM Content before deciding a field is missing - relevant values can appear anywhere, not just near the top.
- A field's aliases are alternate labels/wording for the exact same concept - a page heading or label phrased differently from the field's own name still counts as that field if it matches one of its aliases.
- A value may appear in a table, a key-value pair, a paragraph, a list, or a card - check all of these, not just one format.
- Prefer explicit values stated on the page. Never invent, guess, or infer a value that is not clearly present - hallucinated values are worse than a null.
- Return null ONLY when the information is genuinely absent from the DOM Content, not because it was hard to find.
- Ignore navigation menus, advertisements, cookie/consent notices, and unrelated boilerplate content.
- Preserve the page's exact original wording for descriptive/free-text fields - do not paraphrase, summarize, or reword.
- Keep structured values (numbers, dates, currency, measurements) in their original format - do not normalize, convert, or reformat unless the field's description explicitly asks for it.
- If multiple candidate values exist for one field, choose the one that most directly answers that field, not a tangential mention.
- Deterministic values (see "ALREADY EXTRACTED FIELDS") are authoritative - never overwrite or second-guess them.{site_rules_block}

## 3. SCHEMA FIELDS
{schema_fields_block}

## 4. ALREADY EXTRACTED FIELDS (return null for these - do not re-extract)
{", ".join(solved_fields_list) if solved_fields_list else "None"}

## 5. REMAINING FIELDS TO EXTRACT
{", ".join(remaining_fields_list) if remaining_fields_list else "None"}

## 6. DOM CONTENT
{dom_compact}

## 7. EXPECTED JSON OUTPUT
Return ONLY one flat JSON object, nothing else:
- Include exactly these keys, spelled exactly as given: {", ".join(all_field_names) if all_field_names else "None"}.
- Every key must appear exactly once - no duplicates, no extra/renamed keys.
- Use null (not the string "null") for any field with no supporting evidence.
- No markdown formatting, code fences, comments, or explanatory text - JSON only.
"""
        return prompt
