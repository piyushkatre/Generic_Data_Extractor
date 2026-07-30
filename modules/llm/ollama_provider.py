import os
import json
import time
import typing
from typing import Dict, Any, Optional, Type, List, get_origin, get_args
import httpx
from pydantic import BaseModel, ValidationError
from utils.logger import get_logger
from modules.llm.base import BaseLLMProvider
from modules.llm.gemini_provider import repair_json_string

logger = get_logger(__name__)


class OllamaModelUnavailableError(Exception):
    """
    Raised when Ollama reports that the requested model doesn't exist on the
    server (e.g. it was never pulled). Deliberately NOT a subclass of any
    httpx error - it is raised from a successfully-received HTTP response,
    not a transport failure, and it is never retried: retrying cannot make
    a missing model appear, so retrying would only waste
    (MAX_RETRIES + 1) * OLLAMA_TIMEOUT seconds before failing anyway.
    """


def get_latest_debug_dir() -> Optional[str]:
    """
    Scans the debug directory to find the most recent 'run_*' folder.
    """
    debug_root = "debug"
    if not os.path.exists(debug_root):
        return None
    try:
        subdirs = [
            os.path.join(debug_root, d)
            for d in os.listdir(debug_root)
            if d.startswith("run_") and os.path.isdir(os.path.join(debug_root, d))
        ]
        if not subdirs:
            return None
        # Sort by directory modification time (most recent first)
        subdirs.sort(key=os.path.getmtime, reverse=True)
        return subdirs[0]
    except Exception:
        return None


def resolve_schema(schema: Any, root_schema: dict) -> dict:
    """
    Recursively dereferences $ref keys in the JSON schema.
    Also handles combinators like anyOf, oneOf, and allOf to extract the array schema.
    """
    if not isinstance(schema, dict):
        return {}
    if "$ref" in schema:
        ref_path = schema["$ref"]
        parts = ref_path.lstrip("#/").split("/")
        current = root_schema
        for part in parts:
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                return {}
        return resolve_schema(current, root_schema)
        
    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in schema:
            sub_schemas = schema[combinator]
            if isinstance(sub_schemas, list):
                # Search for a sub-schema that is an array type (preferred)
                for sub in sub_schemas:
                    resolved_sub = resolve_schema(sub, root_schema)
                    if resolved_sub.get("type") == "array":
                        return resolved_sub
                # Fallback to the first non-null sub-schema
                for sub in sub_schemas:
                    resolved_sub = resolve_schema(sub, root_schema)
                    if resolved_sub.get("type") != "null":
                        return resolved_sub
    return schema


def is_list_type(annotation: Any) -> bool:
    """
    Fallback checker: checks if a type annotation represents a list/sequence.
    """
    if annotation is None:
        return False
    if annotation is list or annotation is List:
        return True
    origin = get_origin(annotation)
    if origin is list or origin is List or origin is set or origin is typing.Sequence:
        return True
    if origin is typing.Union or (hasattr(typing, "UnionType") and origin is typing.UnionType):
        return any(is_list_type(arg) for arg in get_args(annotation))
    return False


def get_nested_model_class(annotation: Any) -> Optional[Type[BaseModel]]:
    """
    Fallback checker: extracts nested Pydantic model class from annotations.
    """
    if annotation is None:
        return None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return annotation
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is typing.Union or (hasattr(typing, "UnionType") and origin is typing.UnionType):
        for arg in args:
            res = get_nested_model_class(arg)
            if res:
                return res
    if origin is list or origin is List or origin is set or origin is typing.Sequence:
        if args:
            return get_nested_model_class(args[0])
    return None


def is_key_value_item_schema(schema: dict) -> bool:
    if not isinstance(schema, dict):
        return False
    if schema.get("type") != "object":
        return False
    properties = schema.get("properties", {})
    return "key" in properties and "value" in properties


def is_key_value_item_model(model_cls: type) -> bool:
    if not (isinstance(model_cls, type) and issubclass(model_cls, BaseModel)):
        return False
    return "key" in model_cls.model_fields and "value" in model_cls.model_fields


def normalize_val(val: Any, field_schema: dict, root_schema: dict, field_name: str, normalization_logs: list[str]) -> Any:
    """
    Recursively normalizes a field value based on its JSON schema configuration.
    """
    field_schema = resolve_schema(field_schema, root_schema)
    if val is None:
        return None

    is_list = field_schema.get("type") == "array"

    if is_list:
        items_schema = resolve_schema(field_schema.get("items", {}), root_schema)
        
        # Check if the list element is a KeyValueItem schema
        if is_key_value_item_schema(items_schema):
            target_dict = None
            if isinstance(val, dict):
                target_dict = val
            elif isinstance(val, list) and len(val) == 1 and isinstance(val[0], dict):
                target_dict = val[0]
            
            if target_dict is not None and not ("key" in target_dict and "value" in target_dict):
                converted = []
                for k, v in target_dict.items():
                    converted.append({"key": k, "value": v})
                
                normalization_logs.append(
                    f"Compatibility normalization:\n"
                    f"{field_name}\n"
                    f"dict\n"
                    f"↓\n"
                    f"List[KeyValueItem]\n"
                    f"Generated {len(converted)} key-value entries."
                )
                val = converted

        # If the expected field is a list, but we got a primitive, dict, or string:
        if not isinstance(val, list):
            prev_type = type(val).__name__
            # Intelligent string split: expects array of strings, received comma/newline separated string
            if isinstance(val, str) and items_schema.get("type") == "string":
                if "\n" in val:
                    items = [item.strip() for item in val.split("\n") if item.strip()]
                elif "," in val:
                    items = [item.strip() for item in val.split(",") if item.strip()]
                else:
                    items = [val]
                
                normalization_logs.append(f"• {field_name} : {prev_type} → list ({len(items)} items)")
                val = items
            else:
                # Wrap dict or other primitives in list
                normalization_logs.append(f"• {field_name} : {prev_type} → list")
                val = [val]

        # Recurse into list items
        normalized_list = []
        for item in val:
            normalized_list.append(normalize_val(item, items_schema, root_schema, f"{field_name} item", normalization_logs))
        return normalized_list

    elif field_schema.get("type") == "string" and isinstance(val, list):
        prev_type = type(val).__name__
        items_str = ", ".join(str(item) for item in val)
        normalization_logs.append(f"• {field_name} : {prev_type} → string")
        return items_str

    elif field_schema.get("type") == "string" and isinstance(val, dict):
        prev_type = type(val).__name__
        min_val = val.get("min")
        max_val = val.get("max")
        if min_val is not None or max_val is not None:
            parts = []
            if min_val is not None:
                parts.append(str(min_val))
            if max_val is not None:
                parts.append(str(max_val))
            val_str = " - ".join(parts)
        else:
            val_str = ", ".join(f"{k}: {v}" for k, v in val.items())
        normalization_logs.append(f"• {field_name} : {prev_type} → string ('{val_str}')")
        return val_str

    elif isinstance(val, dict) and field_schema.get("type") == "object":
        properties = field_schema.get("properties", {})
        normalized_dict = {}
        for k, v in val.items():
            if k in properties:
                normalized_dict[k] = normalize_val(v, properties[k], root_schema, k, normalization_logs)
            else:
                normalized_dict[k] = v
        return normalized_dict

    return val


def normalize_data_fallback(data: Any, model: Type[BaseModel], normalization_logs: list[str]) -> Any:
    """
    Fallback normalizer: recursively normalizes parsed dictionary using Pydantic introspection.
    """
    if data is None:
        return None
    if not isinstance(data, dict):
        if isinstance(data, list):
            return [normalize_data_fallback(item, model, normalization_logs) for item in data]
        return data

    normalized = {}
    for field_name, field_info in model.model_fields.items():
        if field_name not in data:
            continue
        val = data[field_name]
        if val is None:
            normalized[field_name] = None
            continue

        is_list = is_list_type(field_info.annotation)
        nested_model = get_nested_model_class(field_info.annotation)

        if is_list:
            # Check if the list element is a KeyValueItem model
            if nested_model and is_key_value_item_model(nested_model):
                target_dict = None
                if isinstance(val, dict):
                    target_dict = val
                elif isinstance(val, list) and len(val) == 1 and isinstance(val[0], dict):
                    target_dict = val[0]
                
                if target_dict is not None and not ("key" in target_dict and "value" in target_dict):
                    converted = []
                    for k, v in target_dict.items():
                        converted.append({"key": k, "value": v})
                    
                    normalization_logs.append(
                        f"Compatibility normalization:\n"
                        f"{field_name}\n"
                        f"dict\n"
                        f"↓\n"
                        f"List[KeyValueItem]\n"
                        f"Generated {len(converted)} key-value entries."
                    )
                    val = converted

            if not isinstance(val, list):
                prev_type = type(val).__name__
                # Check if it expects a list of strings
                is_str_array = False
                annotation = field_info.annotation
                origin = get_origin(annotation)
                args = get_args(annotation)
                if origin is typing.Union or (hasattr(typing, "UnionType") and origin is typing.UnionType):
                    for arg in args:
                        if get_origin(arg) in (list, List) and get_args(arg) and get_args(arg)[0] is str:
                            is_str_array = True
                elif origin in (list, List) and args and args[0] is str:
                    is_str_array = True

                if isinstance(val, str) and is_str_array:
                    if "\n" in val:
                        items = [item.strip() for item in val.split("\n") if item.strip()]
                    elif "," in val:
                        items = [item.strip() for item in val.split(",") if item.strip()]
                    else:
                        items = [val]
                    normalization_logs.append(f"• {field_name} : {prev_type} → list ({len(items)} items)")
                    val = items
                else:
                    normalization_logs.append(f"• {field_name} : {prev_type} → list")
                    val = [val]

            if nested_model:
                val = [normalize_data_fallback(item, nested_model, normalization_logs) for item in val]
        else:
            is_str_field = False
            annotation = field_info.annotation
            if annotation is str:
                is_str_field = True
            else:
                origin = get_origin(annotation)
                args = get_args(annotation)
                if origin is typing.Union or (hasattr(typing, "UnionType") and origin is typing.UnionType):
                    if str in args:
                        is_str_field = True
            
            if is_str_field and isinstance(val, list):
                prev_type = type(val).__name__
                val = ", ".join(str(item) for item in val)
                normalization_logs.append(f"• {field_name} : {prev_type} → string")
            elif nested_model and isinstance(val, dict):
                val = normalize_data_fallback(val, nested_model, normalization_logs)

        normalized[field_name] = val

    for k, v in data.items():
        if k not in normalized:
            normalized[k] = v
    return normalized


def normalize_data(data: Any, model: Type[BaseModel], normalization_logs: list[str]) -> Any:
    """
    Main compatibility normalizer. Prefer schema-driven resolution with annotations fallback.
    """
    try:
        root_schema = model.model_json_schema()
    except Exception:
        root_schema = {}

    if not root_schema:
        logger.info("JSON schema unavailable. Using fallback annotation introspection for normalization.")
        return normalize_data_fallback(data, model, normalization_logs)

    if isinstance(data, dict):
        properties = root_schema.get("properties", {})
        normalized = {}
        for k, v in data.items():
            if k in properties:
                prop_schema = resolve_schema(properties[k], root_schema)
                expected_type = prop_schema.get("type", "unknown")
                actual_type = type(v).__name__
                
                # Check if it needs normalization
                needs_norm = "YES" if expected_type == "array" and not isinstance(v, list) else "NO"
                
                # Run normalization
                normalized[k] = normalize_val(v, properties[k], root_schema, k, normalization_logs)
                
                actual_type_after = type(normalized[k]).__name__
                applied = "YES" if needs_norm == "YES" and actual_type_after == "list" else "NO"
                
                logger.info(f"Field Name: {k}")
                logger.info(f"Expected Type: {expected_type}")
                logger.info(f"Actual Type: {actual_type}")
                logger.info(f"Normalization Needed: {needs_norm}")
                logger.info(f"Normalization Applied: {applied}")
            else:
                normalized[k] = v
        
        # Verify returned object type for additional_information
        if "additional_information" in normalized:
            logger.info(f"type(data['additional_information']) after normalization: {type(normalized['additional_information']).__name__}")
            
        return normalized
    elif isinstance(data, list):
        return [normalize_val(item, root_schema, root_schema, "item", normalization_logs) for item in data]
        
    return data


def classify_transport_error(exc: httpx.HTTPError) -> str:
    """
    Maps an httpx exception to one of the generic failure categories this
    provider distinguishes for logging and retry decisions. Classification
    is purely by exception TYPE (never by message text, model name, or
    website), so this works identically for any Ollama model or host.

    - "connection failure": couldn't even reach the server (it's down, the
      wrong host/port, or refusing connections). Usually means Ollama isn't
      running or OLLAMA_BASE_URL is wrong.
    - "timeout": a connection was established but no response arrived within
      the configured timeout - for a chat/generate request this almost
      always means the model is still generating. Increasing OLLAMA_TIMEOUT
      (or OLLAMA_CONNECT_TIMEOUT, if the timeout is a ConnectTimeout) is the
      fix, not more retries.
    - "transport failure": any other network/protocol-level problem, or a
      non-2xx HTTP response from a server that WAS reached (e.g. a transient
      5xx) - distinct from "connection failure" in that Ollama did respond.
    """
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "connection failure"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return "transport failure"


class OllamaProvider(BaseLLMProvider):
    """
    Ollama extraction provider using local REST API.
    """
    def generate_schema(self, model_class: Type[BaseModel]) -> Any:
        return model_class.model_json_schema()

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
        from modules.config import ExtractorConfig
        from modules.adapter_loader import ExtractionResult

        config = ExtractorConfig.load()
        model = config.OLLAMA_MODEL
        base_url = config.OLLAMA_BASE_URL

        website_name = adapter.name if adapter else "Target Website"
        system_instruction = (
            "You are a structured business data extraction engine.\n"
            f"Your mission is to extract structured franchise information ONLY from the supplied DOM for {website_name}.\n\n"
            "Rules:\n"
            "- Never use prior knowledge.\n"
            "- Never guess.\n"
            "- Never infer.\n"
            "- Never fabricate.\n"
            "- If evidence is missing, return null.\n\n"
            "Evidence Rules:\n"
            "Every populated field must be directly supported by text in the supplied DOM.\n"
            "If supporting text cannot be found, return null.\n\n"
            "Output Rules:\n"
            "Return ONLY valid JSON.\n"
            "No markdown.\n"
            "No explanation.\n"
            "No comments.\n"
            "Follow schema exactly."
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

        ollama_instructions = (
            "\n\nCRITICAL CONSTRAINTS FOR OLLAMA:\n"
            "- Return ONLY valid JSON.\n"
            "- No Markdown (do not wrap in ```json or ```).\n"
            "- No explanation.\n"
            "- Missing values must be null.\n"
            "- Arrays must remain arrays.\n"
            "- Follow schema exactly."
        )
        final_user_prompt = final_user_prompt + ollama_instructions

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": final_user_prompt}
            ],
            "stream": False,
            "options": {
                "temperature": 0.05,
                "top_p": 0.3,
                "repeat_penalty": 1.1,
                "num_ctx": config.OLLAMA_NUM_CTX,
            },
            "format": "json"
        }
        
        # num_predict sets the limit on output tokens in Ollama
        if max_output_tokens is not None:
            payload["options"]["num_predict"] = max_output_tokens
        else:
            payload["options"]["num_predict"] = 8192

        max_retries = config.MAX_RETRIES
        base_delay = config.RETRY_DELAY
        # Split transport timeout: connecting to a local Ollama server should
        # be near-instant (OLLAMA_CONNECT_TIMEOUT), while generation itself
        # is the genuinely slow, model-size-dependent phase
        # (OLLAMA_TIMEOUT) - a single flat timeout can't distinguish "Ollama
        # isn't running" from "the model is still working", but a connect
        # timeout that fires quickly vs a read timeout that fires late can.
        request_timeout = httpx.Timeout(
            connect=config.OLLAMA_CONNECT_TIMEOUT,
            read=config.OLLAMA_TIMEOUT,
            write=config.OLLAMA_CONNECT_TIMEOUT,
            pool=config.OLLAMA_CONNECT_TIMEOUT,
        )
        attempt = 0
        last_error = None

        while attempt <= max_retries:
            if context_metrics is not None:
                context_metrics["requests"] += 1

            request_start = time.time()
            try:
                # Estimate prompt tokens and verify budget safety
                prompt_len = len(system_instruction) + len(final_user_prompt)
                prompt_tokens = prompt_len // 4
                
                reserved_output = payload["options"].get("num_predict", 8192)
                context_window_val = payload["options"].get("num_ctx")
                total_budget = prompt_tokens + reserved_output
                
                if context_window_val is not None:
                    remaining = context_window_val - total_budget
                    status_str = "SAFE" if total_budget <= context_window_val else "OVERFLOW"
                    context_window_log = str(context_window_val)
                else:
                    remaining = "N/A"
                    status_str = "N/A (Model Default)"
                    context_window_log = "Default (Server/Model Defined)"
                
                logger.info(f"Ollama Request - Model Name: {model}")
                logger.info(f"Ollama Request - Prompt Length: {prompt_len} characters")
                logger.info(f"Ollama Request - Estimated Prompt Tokens: {prompt_tokens}")
                
                logger.info(f"Prompt Budget Verification:")
                logger.info(f"  Prompt Tokens   : {prompt_tokens}")
                logger.info(f"  Reserved Output : {reserved_output}")
                logger.info(f"  Context Window  : {context_window_log}")
                logger.info(f"  Remaining Space : {remaining}")
                logger.info(f"  Status          : {status_str}")
                
                if context_window_val is not None and total_budget > context_window_val:
                    logger.warning(
                        f"PROMPT BUDGET WARNING: Prompt tokens ({prompt_tokens}) + "
                        f"Reserved output ({reserved_output}) = {total_budget} which exceeds "
                        f"configured context window ({context_window_val})! Truncation will occur."
                    )
                
                logger.info(
                    f"Ollama Request - Sending to {base_url.rstrip('/')}/api/chat "
                    f"(connect_timeout={config.OLLAMA_CONNECT_TIMEOUT}s, read_timeout={config.OLLAMA_TIMEOUT}s)"
                )
                response = httpx.post(
                    f"{base_url.rstrip('/')}/api/chat",
                    json=payload,
                    timeout=request_timeout
                )
                elapsed = time.time() - request_start
                logger.info(f"Ollama Request - Response received in {elapsed:.1f}s (status {response.status_code})")

                # Ollama reports a missing/unpulled model as a 404 with an
                # {"error": ...} body - this is a successfully-received HTTP
                # response, not a transport failure, so it's checked here
                # (and raised as OllamaModelUnavailableError below) rather
                # than left to raise_for_status(), which would only produce
                # a generic HTTPStatusError that gets retried pointlessly.
                if response.status_code == 404:
                    raise OllamaModelUnavailableError(
                        f"Ollama reports model '{model}' is unavailable (HTTP 404) - "
                        f"it may not be pulled yet. Try: ollama pull {model}"
                    )

                if response.status_code != 200:
                    response.raise_for_status()

                resp_json = response.json()

                error_field = resp_json.get("error")
                if error_field:
                    raise OllamaModelUnavailableError(
                        f"Ollama reported an error for model '{model}': {error_field}"
                    )

                raw_response_text = resp_json.get("message", {}).get("content", "").strip()

                # Ollama's own token counts (accurate, unlike the estimated
                # prompt_tokens logged above) - logged when present so future
                # timeout tuning can be based on real generation length.
                prompt_eval_count = resp_json.get("prompt_eval_count")
                eval_count = resp_json.get("eval_count")
                if prompt_eval_count is not None or eval_count is not None:
                    logger.info(
                        f"Ollama Response - Server-reported prompt tokens: {prompt_eval_count}, "
                        f"response tokens: {eval_count}"
                    )

                # Issue 4: Save raw response before any validation/normalizations
                is_debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes") or os.getenv("DEVELOPER_MODE", "false").lower() in ("true", "1", "yes")
                if is_debug:
                    debug_dir = get_latest_debug_dir()
                    if debug_dir:
                        try:
                            os.makedirs(debug_dir, exist_ok=True)
                            with open(os.path.join(debug_dir, "06_ollama_raw_response.json"), "w", encoding="utf-8") as f:
                                f.write(raw_response_text)
                        except Exception as dbg_err:
                            logger.warning(f"Failed to write Ollama raw response to debug dir: {dbg_err}")

                active_model = response_model if response_model else ExtractionResult

                # First, parse raw text to dict (check if JSON validates syntactically)
                try:
                    parsed_dict = json.loads(raw_response_text)
                except Exception as json_err:
                    logger.info(f"JSON validation/parsing failed: {json_err}. Attempting JSON repair...")
                    try:
                        repaired_text = repair_json_string(raw_response_text)
                        parsed_dict = json.loads(repaired_text)
                        logger.info("=== JSON Repair Attempt ===\nStatus:      Successful\nAction:      Parsed repaired JSON\n==========================")
                    except Exception as repair_err:
                        logger.warning(f"=== JSON Repair Attempt ===\nStatus:      Failed\nReason:      {repair_err}\n==========================")
                        # Syntax error: JSON is invalid even after repair
                        raise ValueError(f"JSON syntax invalid after repair: {repair_err}") from json_err

                # Syntactically valid JSON. At this point, do NOT retry. Any validation failures raise immediately.
                try:
                    result = active_model.model_validate(parsed_dict)
                    if not result.source_url and source_url:
                        result.source_url = source_url
                    
                    if is_debug:
                        debug_dir = get_latest_debug_dir()
                        if debug_dir:
                            try:
                                with open(os.path.join(debug_dir, "06_ollama_normalized.json"), "w", encoding="utf-8") as f:
                                    json.dump(parsed_dict, f, indent=2)
                            except Exception as dbg_err:
                                logger.warning(f"Failed to write debug outputs: {dbg_err}")
                    
                    logger.info("Received Ollama response.")
                    logger.info("Raw JSON parsed successfully.")
                    logger.info("Compatibility normalization not required.")
                    logger.info("Schema validation successful.")
                    return result
                except Exception as val_err:
                    logger.info("Received Ollama response.")
                    logger.info("Raw JSON parsed successfully.")
                    
                    # Run compatibility normalizations
                    normalization_logs = []
                    normalized_dict = normalize_data(parsed_dict, active_model, normalization_logs)
                    
                    if is_debug:
                        debug_dir = get_latest_debug_dir()
                        if debug_dir:
                            try:
                                with open(os.path.join(debug_dir, "06_ollama_normalized.json"), "w", encoding="utf-8") as f:
                                    json.dump(normalized_dict, f, indent=2)
                            except Exception as dbg_err:
                                logger.warning(f"Failed to write Ollama normalized response to debug dir: {dbg_err}")

                    if normalization_logs:
                        logger.info("Compatibility normalization applied:\n" + "\n".join(normalization_logs))
                    else:
                        logger.info("Compatibility normalization not required.")

                    # Revalidate normalized dictionary once
                    try:
                        result = active_model.model_validate(normalized_dict)
                        if not result.source_url and source_url:
                            result.source_url = source_url

                        logger.info("Schema validation successful.")
                        return result
                    except Exception as reval_err:
                        logger.error(f"Schema validation failed after normalization: {reval_err}")
                        raise reval_err

            except OllamaModelUnavailableError as unavailable_err:
                # Retrying cannot make a missing/errored model appear -
                # raise immediately instead of wasting
                # (MAX_RETRIES + 1) * OLLAMA_TIMEOUT seconds on a problem
                # that will fail identically every time.
                elapsed = time.time() - request_start
                logger.error(f"Ollama model unavailable after {elapsed:.1f}s: {unavailable_err}")
                raise unavailable_err
            except httpx.HTTPError as transport_err:
                # Covers both httpx.RequestError (connection/timeout/network
                # failures - request never got a response) and
                # httpx.HTTPStatusError (a non-2xx response WAS received).
                # classify_transport_error() distinguishes these for logging
                # only; retry/backoff behavior is identical for all of them.
                elapsed = time.time() - request_start
                category = classify_transport_error(transport_err)
                logger.warning(
                    f"Ollama request failed ({category}) after {elapsed:.1f}s: {transport_err}. "
                    f"Attempt {attempt + 1}/{max_retries + 1} "
                    f"(connect_timeout={config.OLLAMA_CONNECT_TIMEOUT}s, read_timeout={config.OLLAMA_TIMEOUT}s)"
                )
                last_error = transport_err
                if attempt < max_retries:
                    if context_metrics is not None:
                        context_metrics["retries"] += 1
                    delay = base_delay * (attempt + 1)
                    logger.info(f"Retrying in {delay}s (reason: {category})...")
                    time.sleep(delay)
                    attempt += 1
                else:
                    break
            except ValidationError as val_err:
                # Do NOT retry for Pydantic schema validation errors, raise immediately
                logger.error(f"Schema validation error raised immediately: {val_err}")
                raise val_err
            except Exception as other_err:
                elapsed = time.time() - request_start
                logger.warning(f"Ollama request failed with syntax or parsing error after {elapsed:.1f}s: {other_err}. Attempt {attempt + 1}/{max_retries + 1}")
                last_error = other_err
                if attempt < max_retries:
                    if context_metrics is not None:
                        context_metrics["retries"] += 1
                    delay = base_delay * (attempt + 1)
                    logger.info(f"Retrying in {delay}s...")
                    time.sleep(delay)
                    attempt += 1
                else:
                    break

        logger.error(
            f"All Ollama attempts failed for model '{model}' after {attempt + 1} attempt(s) "
            f"(read_timeout={config.OLLAMA_TIMEOUT}s, connect_timeout={config.OLLAMA_CONNECT_TIMEOUT}s). "
            f"Last error: {last_error}"
        )
        raise last_error
