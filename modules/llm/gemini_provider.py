import os
import json
import time
import random
from typing import List, Dict, Any, Optional, Union, Type
from pydantic import BaseModel
from utils.logger import get_logger
from modules.llm.base import BaseLLMProvider

logger = get_logger(__name__)

class QuotaManager:
    _quota_exhausted = False

    @classmethod
    def is_exhausted(cls) -> bool:
        return cls._quota_exhausted

    @classmethod
    def set_exhausted(cls, status: bool = True):
        cls._quota_exhausted = status

_cached_gemini_schema = None

def get_cached_gemini_schema() -> Any:
    global _cached_gemini_schema
    if _cached_gemini_schema is None:
        try:
            from modules.adapter_loader import ExtractionResult
            _cached_gemini_schema = generate_gemini_schema(ExtractionResult)
            logger.info("Successfully generated and cached Gemini response schema.")
        except Exception as e:
            logger.error(f"Failed to generate Gemini response schema: {e}")
            return None
    return _cached_gemini_schema


def repair_json_string(raw_json: str) -> str:
    """
    Attempts to repair basic JSON malformations, such as trailing commas,
    unterminated strings, and unclosed braces/brackets (truncation).
    """
    import re
    raw_json = raw_json.strip()
    
    # Strip markdown wrapping if present
    if raw_json.startswith("```"):
        lines = raw_json.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw_json = "\n".join(lines).strip()

    # Basic cleanup: remove trailing commas before closing braces/brackets
    raw_json = re.sub(r',\s*([\}\]])', r'\1', raw_json)

    try:
        # If it parses directly, return
        json.loads(raw_json)
        return raw_json
    except ValueError:
        pass

    # Balance braces/brackets and strings for truncated inputs
    in_string = False
    escape = False
    stack = []
    clean_chars = []

    i = 0
    while i < len(raw_json):
        char = raw_json[i]
        if in_string:
            if escape:
                escape = False
            elif char == '\\':
                escape = True
            elif char == '"':
                in_string = False
            clean_chars.append(char)
        else:
            if char == '"':
                in_string = True
                clean_chars.append(char)
            elif char in ('{', '['):
                stack.append(char)
                clean_chars.append(char)
            elif char in ('}', ']'):
                if stack:
                    last = stack[-1]
                    if (char == '}' and last == '{') or (char == ']' and last == '['):
                        stack.pop()
                clean_chars.append(char)
            else:
                clean_chars.append(char)
        i += 1

    # Terminate trailing unclosed string
    if in_string:
        if clean_chars and clean_chars[-1] == '\\':
            clean_chars.pop()
        clean_chars.append('"')

    # Close unclosed brackets and braces
    while stack:
        last = stack.pop()
        if last == '{':
            clean_chars.append('}')
        elif last == '[':
            clean_chars.append(']')

    repaired = "".join(clean_chars)
    # Remove any new trailing commas before closing braces/brackets
    repaired = re.sub(r',\s*([\}\]])', r'\1', repaired)

    return repaired


def parse_quota_error(e: Exception) -> tuple[str, bool, str, float | None]:
    """
    Parses a 429 / RESOURCE_EXHAUSTED APIError to determine the quota type and retry rules.
    Always inspects ALL violations in the error details before deciding.
    
    Priority order:
      1. GenerateRequestsPerDayPerProjectPerModel (Stop immediately, no retry, no fallback)
      2. GenerateContentInputTokensPerDay (Stop immediately)
      3. GenerateRequestsPerMinute (Retry after retryDelay)
      4. GenerateContentInputTokensPerMinute (Retry after retryDelay)
      5. 503 Service Unavailable (Retry)
      6. Timeout (Retry)
      
    Rule: Never retry if a daily quota exists anywhere in the response.
    """
    error_str = str(e)
    detected_violations = []
    retry_delay = None

    # Step 1: Walk structured error details to gather all violations
    err_details = []
    try:
        err_dict = {}
        if hasattr(e, "details"):
            err_dict = e.details if isinstance(e.details, dict) else {}
        if "error" in err_dict and isinstance(err_dict["error"], dict):
            err_dict = err_dict["error"]
        err_details = err_dict.get("details", [])
        if not isinstance(err_details, list):
            err_details = []
    except Exception:
        err_details = []

    for d in err_details:
        if not isinstance(d, dict):
            continue
        if d.get("@type") == "type.googleapis.com/google.rpc.QuotaFailure":
            violations = d.get("violations", [])
            if isinstance(violations, list):
                for v in violations:
                    if isinstance(v, dict):
                        q_id = str(v.get("quotaId", "")).strip()
                        q_metric = str(v.get("quotaMetric", "")).strip()
                        for val in (q_id, q_metric):
                            if val:
                                detected_violations.append(val)
        if d.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
            delay_str = str(d.get("retryDelay", "")).strip()
            if delay_str.endswith("s"):
                delay_str = delay_str[:-1]
            try:
                retry_delay = float(delay_str)
            except (ValueError, TypeError):
                pass

    # Step 2: Fall back to keyword scan of the raw error string
    _KNOWN_METRICS = [
        ("GenerateRequestsPerDayPerProjectPerModel", "GenerateRequestsPerDayPerProjectPerModel"),
        ("generate_content_free_tier_requests", "GenerateRequestsPerDayPerProjectPerModel"),
        ("GenerateContentInputTokensPerModelPerDay", "GenerateContentInputTokensPerModelPerDay"),
        ("GenerateContentInputTokensPerDay", "GenerateContentInputTokensPerDay"),
        ("generate_content_free_tier_input_token_count", "GenerateContentInputTokensPerDay"),
        ("GenerateRequestsPerMinutePerProjectPerModel", "GenerateRequestsPerMinutePerProjectPerModel"),
        ("GenerateRequestsPerMinute", "GenerateRequestsPerMinute"),
        ("generate_requests_per_minute", "GenerateRequestsPerMinute"),
        ("GenerateContentInputTokensPerModelPerMinute", "GenerateContentInputTokensPerModelPerMinute"),
        ("GenerateContentInputTokensPerMinute", "GenerateContentInputTokensPerMinute"),
        ("generate_content_input_tokens_per_minute", "GenerateContentInputTokensPerMinute"),
    ]
    for term, canonical in _KNOWN_METRICS:
        if term.lower() in error_str.lower():
            detected_violations.append(canonical)

    if "503" in error_str or "unavailable" in error_str.lower():
        detected_violations.append("503")
    if "timeout" in error_str.lower() or "deadline exceeded" in error_str.lower():
        detected_violations.append("Timeout")

    # If no violations detected but it's a 429, default to Requests Per Minute
    if not detected_violations:
        if retry_delay is not None:
            detected_violations.append("GenerateRequestsPerMinute")
        else:
            detected_violations.append("GenerateRequestsPerMinute")

    # Step 3: Parse and score each violation by Priority
    scored_violations = []
    for v in detected_violations:
        v_lower = v.lower()
        if "token" in v_lower:
            if "perday" in v_lower or "per_day" in v_lower or "free_tier_input_token" in v_lower:
                priority = 2
                canonical = "GenerateContentInputTokensPerDay"
            else:
                priority = 4
                canonical = "GenerateContentInputTokensPerModelPerMinute"
        else:
            if "perday" in v_lower or "per_day" in v_lower or "free_tier_requests" in v_lower:
                priority = 1
                canonical = "GenerateRequestsPerDayPerProjectPerModel"
            elif v == "503" or "503" in v_lower:
                priority = 5
                canonical = "503 Service Unavailable"
            elif v == "Timeout" or "timeout" in v_lower:
                priority = 6
                canonical = "Timeout"
            else:
                priority = 3
                canonical = "GenerateRequestsPerMinutePerProjectPerModel"
        scored_violations.append((priority, canonical))

    # Sort so that highest priority (lowest number) is first
    scored_violations.sort(key=lambda x: x[0])
    top_priority, top_quota_type = scored_violations[0]

    # Verify if a daily quota exists ANYWHERE in the response
    has_daily_quota = any(p in (1, 2) for p, _ in scored_violations)

    if has_daily_quota:
        should_retry = False
        user_msg = (
            f"Gemini daily quota exhausted / limit hit ({top_quota_type}). "
            "Stop immediately. No retry or fallback models will be attempted."
        )
    elif top_priority in (3, 4):
        should_retry = True
        delay_display = f"{int(retry_delay)}s" if retry_delay else "back-off"
        user_msg = f"Rate limit hit ({top_quota_type}). Retry after {delay_display}."
    elif top_priority == 5:
        should_retry = True
        user_msg = "Temporary service unavailable (503). Retrying."
    elif top_priority == 6:
        should_retry = True
        user_msg = "Request timeout. Retrying."
    else:
        should_retry = True
        user_msg = f"Quota error ({top_quota_type}). Retrying with back-off."

    logger.info(
        f"\n=== Quota Priority Selection ===\n"
        f"Detected Violations: {[v for _, v in scored_violations]}\n"
        f"Selected Quota:      {top_quota_type} (Priority {top_priority})\n"
        f"Retry Decision:      {'Retry' if should_retry else 'No Retry'}\n"
        "================================"
    )

    return top_quota_type, should_retry, user_msg, retry_delay


def generate_gemini_schema(model_class: Type[BaseModel]) -> Dict[str, Any]:
    """
    Generates a fully dereferenced JSON schema from a Pydantic model,
    safe for the Gemini Developer API (no refs, no defs, no additionalProperties).
    """
    raw_schema = model_class.model_json_schema()
    defs = raw_schema.pop("$defs", {})

    def resolve_refs(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_path = node["$ref"]
                ref_name = ref_path.split("/")[-1]
                resolved = resolve_refs(defs.get(ref_name, {}))
                return resolved
            else:
                return {k: resolve_refs(v) for k, v in node.items()}
        elif isinstance(node, list):
            return [resolve_refs(item) for item in node]
        return node

    resolved_schema = resolve_refs(raw_schema)

    def simplify_anyof(node: Any) -> Any:
        if isinstance(node, dict):
            if "anyOf" in node:
                anyof_list = node.pop("anyOf")
                non_null_items = [item for item in anyof_list if isinstance(item, dict) and item.get("type") != "null"]
                if non_null_items:
                    target_item = non_null_items[0]
                    for k, v in target_item.items():
                        node[k] = v
                node["nullable"] = True
            return {k: simplify_anyof(v) for k, v in node.items()}
        elif isinstance(node, list):
            return [simplify_anyof(item) for item in node]
        return node

    resolved_schema = simplify_anyof(resolved_schema)

    def clean_node(node: Any, parent_key: Optional[str] = None) -> Any:
        if isinstance(node, dict):
            if parent_key == "properties":
                return {k: clean_node(v) for k, v in node.items()}
            allowed_keys = {"type", "properties", "required", "items", "enum", "nullable"}
            cleaned = {}
            for k, v in node.items():
                if k in allowed_keys:
                    cleaned[k] = clean_node(v, parent_key=k)
            return cleaned
        elif isinstance(node, list):
            return [clean_node(item) for item in node]
        return node

    cleaned_schema = clean_node(resolved_schema)

    # Exclude internal metadata fields so Gemini focuses only on content extraction
    if "properties" in cleaned_schema and isinstance(cleaned_schema["properties"], dict):
        keys_to_exclude = {"source_url", "extracted_at", "metadata"}
        for k in keys_to_exclude:
            cleaned_schema["properties"].pop(k, None)
        if "required" in cleaned_schema and isinstance(cleaned_schema["required"], list):
            cleaned_schema["required"] = [r for r in cleaned_schema["required"] if r not in keys_to_exclude]

    return cleaned_schema


class GeminiProvider(BaseLLMProvider):
    """
    Gemini extraction provider using the Google GenAI SDK.
    """
    def generate_schema(self, model_class: Type[BaseModel]) -> Any:
        return generate_gemini_schema(model_class)

    def extract(
        self,
        html_content: str,
        user_instructions: str = "",
        client: Optional[Any] = None,
        max_output_tokens: Optional[int] = None,
        context_metrics: Optional[Dict[str, int]] = None,
        source_url: Optional[str] = None,
        response_model: Optional[Type[BaseModel]] = None,
        adapter: Optional[Any] = None,
    ) -> Any:
        from modules.gemini import genai, types

        if QuotaManager.is_exhausted():
            logger.warning("Bypassing Gemini extraction call: Gemini daily quota exhausted.")
            raise ValueError("Gemini daily quota exhausted. Stop immediately.")

        if client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                logger.warning("GEMINI_API_KEY environment variable is missing. Live API calls will fail.")
            client = genai.Client(api_key=api_key)

        from modules.config import ExtractorConfig
        from modules.adapter_loader import ExtractionResult

        config = ExtractorConfig.load()
        models_to_try = config.GEMINI_MODELS

        website_name = adapter.name if adapter else "Target Website"
        system_instruction = (
            f"You are an expert web scraping and high-fidelity structured data extraction model tuned specifically for {website_name}.\n"
            "Your task is to analyze the provided HTML content and populate the schema fields with the maximum possible accuracy.\n\n"
            "CORE RULES:\n"
            "1. SCHEMA-DRIVEN POPULATION:\n"
            "   - Populate the schema using ONLY information explicitly available on this webpage.\n"
            "   - Map extracted information directly to the corresponding fields in the JSON schema.\n\n"
            "2. ACCURACY & LITERAL EXTRACTION:\n"
            "   - Extract exact values exactly as written. Do NOT summarize, rewrite, infer, estimate, or guess.\n"
            "   - Never fabricate or hallucinate values. If a value is not explicitly present, return null.\n\n"
            "3. IGNORE NOISE:\n"
            "   - Ignore all navigation sections, enquiry forms, advertisements, social widgets, recommendations, and unrelated competitor listings."
        )

        # Format list of schema fields and descriptions
        schema_fields_desc = []
        if adapter and adapter.schema:
            for field_name, field_info in adapter.schema.get("extraction_fields", {}).items():
                desc = field_info.get("description", "")
                schema_fields_desc.append(f"- {field_name}: {desc}")
        schema_fields_str = "\n".join(schema_fields_desc)

        if user_instructions and ("Role:" in user_instructions or "DOM Blocks:" in user_instructions):
            final_user_prompt = user_instructions
        else:
            if adapter and adapter.prompt_template:
                user_prompt = adapter.prompt_template
                user_prompt = user_prompt.replace("{{ website_name }}", adapter.name)
                user_prompt = user_prompt.replace("{{ schema_fields }}", schema_fields_str)
                user_prompt = user_prompt.replace("{{ html_content }}", html_content)
            else:
                user_prompt = f"HTML Content:\n```html\n{html_content}\n```\n"
                if schema_fields_str:
                    user_prompt += f"\nPlease extract these fields:\n{schema_fields_str}\n"

            if user_instructions:
                user_prompt += f"\nUser Extraction Instructions:\n{user_instructions}\n"
            final_user_prompt = user_prompt

        last_error = None
        out_tokens_limit = max_output_tokens if max_output_tokens is not None else 8192

        response_schema = self.generate_schema(response_model) if response_model else get_cached_gemini_schema()
        active_model = response_model if response_model else ExtractionResult

        for model in models_to_try:
            if QuotaManager.is_exhausted():
                break

            logger.info(f"LLM Provider : Gemini\nModel : {model}")
            max_retries = config.MAX_RETRIES
            base_delay = config.RETRY_DELAY
            
            has_retried_for_truncation = False
            attempt = 0
            current_out_tokens = out_tokens_limit

            while attempt <= max_retries:
                if context_metrics is not None:
                    context_metrics["requests"] += 1
                    
                try:
                    current_system_instruction = system_instruction
                    if has_retried_for_truncation:
                        current_system_instruction += (
                            "\n\nCRITICAL: Your previous response was truncated. "
                            "Please be extremely concise and prioritize only the most important target fields. "
                            "Do not output long paragraphs or nested redundancy."
                        )

                    config_args = {
                        "response_mime_type": "application/json",
                        "system_instruction": current_system_instruction,
                        "temperature": 0.1,
                        "max_output_tokens": current_out_tokens,
                    }
                    if response_schema:
                        config_args["response_schema"] = response_schema

                    try:
                        response = client.models.generate_content(
                            model=model,
                            contents=final_user_prompt,
                            config=types.GenerateContentConfig(**config_args)
                        )
                    except Exception as api_err:
                        err_msg = str(api_err).lower()
                        if "additionalproperties" in err_msg or "schema" in err_msg or "valueerror" in err_msg:
                            logger.error(f"Unsupported response schema detected: {api_err}. Falling back to response_mime_type='application/json' without schema.")
                            response_schema = None
                            config_args.pop("response_schema", None)
                            response = client.models.generate_content(
                                model=model,
                                contents=final_user_prompt,
                                config=types.GenerateContentConfig(**config_args)
                            )
                        else:
                            raise api_err
                    
                    raw_response_text = response.text or ""
                    try:
                        result = active_model.model_validate_json(raw_response_text)
                        if not result.source_url and source_url:
                            result.source_url = source_url
                        logger.info(f"Successfully extracted data using model: {model}")
                        return result
                    except Exception as val_err:
                        logger.info(f"JSON validation/parsing failed: {val_err}. Attempting JSON repair...")
                        try:
                            repaired_text = repair_json_string(raw_response_text)
                            result = active_model.model_validate_json(repaired_text)
                            if not result.source_url and source_url:
                                result.source_url = source_url
                            logger.info("=== JSON Repair Attempt ===\nStatus:      Successful\nAction:      Parsed repaired JSON\n==========================")
                            return result
                        except Exception as repair_err:
                            logger.warning(f"=== JSON Repair Attempt ===\nStatus:      Failed\nReason:      {repair_err}\n==========================")
                            
                            err_str = (str(val_err) + " " + str(repair_err)).lower()
                            trunc_indicators = ["eof", "unterminated string", "unexpected end", "closing", "expecting"]
                            is_trunc = any(ind in err_str for ind in trunc_indicators) or not raw_response_text.strip().endswith("}")
                            
                            if is_trunc and not has_retried_for_truncation:
                                has_retried_for_truncation = True
                                current_out_tokens = int(current_out_tokens * 0.9)
                                logger.info(
                                    f"=== Truncation Detected ===\n"
                                    f"Action:      Retrying same model once with reduced max_output_tokens={current_out_tokens}\n"
                                    "=========================="
                                )
                                continue
                                
                            raise val_err
                except Exception as e:
                    last_error = e
                    error_msg = str(e)
                    
                    is_validation_error = (
                        "validation error" in error_msg.lower()
                        or "json" in error_msg.lower()
                        or "parsing" in error_msg.lower()
                    )
                    is_retryable = not is_validation_error and any(
                        keyword in error_msg.upper()
                        for keyword in ["503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "RATE_LIMIT"]
                    )
                    
                    if is_retryable:
                        quota_type, should_retry, user_msg, retry_delay = parse_quota_error(e)

                        logger.info(
                            f"\n=== Quota Analysis ===\n"
                            f"Model:       {model}\n"
                            f"Quota Type:  {quota_type}\n"
                            f"Retry:       {'Yes' if should_retry else 'No'}\n"
                            f"Retry Delay: {f'{retry_delay:.0f}s' if retry_delay else 'N/A'}\n"
                            f"Attempt:     {attempt + 1}/{max_retries + 1}\n"
                            f"Message:     {user_msg}\n"
                            "====================="
                        )

                        if not should_retry:
                            QuotaManager.set_exhausted(True)
                            raise ValueError(user_msg) from e
                        
                        if attempt < max_retries:
                            if context_metrics is not None:
                                context_metrics["retries"] += 1
                                
                            delay = retry_delay if retry_delay is not None else (base_delay * (attempt + 1))
                            logger.info(f"Retrying in {int(delay)}s (attempt {attempt + 1}/{max_retries})...")
                            time.sleep(delay)
                            attempt += 1
                        else:
                            logger.warning(f"Model {model} exhausted all retries. Moving to next model.")
                            break
                    else:
                        logger.warning(f"Model {model} failed with non-retryable error: {e}. Moving to next model.")
                        break

        logger.error(f"All models failed. Last error: {last_error}")
        raise last_error
