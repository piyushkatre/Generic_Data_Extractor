import os
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(".env"), override=True)

from pydantic import BaseModel, Field

class ExtractorConfig(BaseModel):
    """
    Simplified configuration for the web extraction pipeline.
    Loads settings from environment variables or uses standard defaults.
    """
    SAFE_TOKEN_LIMIT: int = Field(
        default=60000,
        description="Threshold token limit. Below this limit, DOM is sent directly. Above this limit, chunking is triggered."
    )
    MAX_BATCH_TOKENS: int = Field(
        default=60000,
        description="Greedy batch packing limit. Contiguous chunks are merged up to this limit."
    )
    MAX_RETRIES: int = Field(
        default=2,
        description="Maximum number of retry attempts for transient API rate-limit errors."
    )
    RETRY_DELAY: float = Field(
        default=2.0,
        description="Linear backoff base delay in seconds between retries."
    )
    GEMINI_MODELS: list[str] = Field(
        default=["gemini-2.5-flash", "gemini-2.0-flash"],
        description="Fallback order of Gemini models to attempt."
    )
    DEVELOPER_MODE: bool = Field(
        default=False,
        description="Whether to show developer-level components in the UI (e.g. Quality Report)."
    )
    LLM_PROVIDER: str = Field(
        default="gemini",
        description="The active LLM provider (gemini or ollama)."
    )
    OLLAMA_MODEL: str = Field(
        default="qwen2.5:7b",
        description="The Ollama model to use."
    )
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="The base URL for Ollama local REST API."
    )
    OLLAMA_NUM_CTX: int = Field(
        default=32768,
        description="Context window size to request from local Ollama instance."
    )
    OLLAMA_TIMEOUT: float = Field(
        default=600.0,
        description=(
            "Read timeout in seconds for a single Ollama generation request - "
            "how long to wait for the model to finish producing a response "
            "before treating the request as timed out. Local generation time "
            "scales with model size, so larger models (e.g. moving from a 3B "
            "to a 7B+ model) need a larger value than smaller ones."
        )
    )
    OLLAMA_CONNECT_TIMEOUT: float = Field(
        default=10.0,
        description=(
            "Connect timeout in seconds for reaching the Ollama server itself "
            "(separate from OLLAMA_TIMEOUT, which only bounds how long "
            "generation may take once connected). Kept short by default: a "
            "local Ollama server should accept a TCP connection almost "
            "instantly, so a slow connect usually means Ollama isn't running "
            "or OLLAMA_BASE_URL is wrong - failing fast on that surfaces a "
            "clear diagnosis instead of waiting the full generation timeout."
        )
    )

    @classmethod
    def load(cls) -> "ExtractorConfig":
        """
        Loads the config with env var overrides.
        """
        # Ensure we read environment variables if set, fallback to default Pydantic values
        safe_token_limit = int(os.getenv("SAFE_TOKEN_LIMIT", "60000"))
        max_batch_tokens = int(os.getenv("MAX_BATCH_TOKENS", "60000"))
        max_retries = int(os.getenv("MAX_RETRIES", "2"))
        retry_delay = float(os.getenv("RETRY_DELAY", "2.0"))
        developer_mode = os.getenv("DEVELOPER_MODE", "false").lower() in ("true", "1", "yes")
        
        llm_provider = os.getenv("LLM_PROVIDER", "gemini").lower()
        ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
        ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT", "600.0"))
        ollama_connect_timeout = float(os.getenv("OLLAMA_CONNECT_TIMEOUT", "10.0"))

        models_raw = os.getenv("GEMINI_MODELS")
        if models_raw:
            gemini_models = [m.strip() for m in models_raw.split(",") if m.strip()]
        else:
            gemini_models = ["gemini-2.5-flash", "gemini-2.0-flash"]
            
        return cls(
            SAFE_TOKEN_LIMIT=safe_token_limit,
            MAX_BATCH_TOKENS=max_batch_tokens,
            MAX_RETRIES=max_retries,
            RETRY_DELAY=retry_delay,
            GEMINI_MODELS=gemini_models,
            DEVELOPER_MODE=developer_mode,
            LLM_PROVIDER=llm_provider,
            OLLAMA_MODEL=ollama_model,
            OLLAMA_BASE_URL=ollama_base_url,
            OLLAMA_NUM_CTX=ollama_num_ctx,
            OLLAMA_TIMEOUT=ollama_timeout,
            OLLAMA_CONNECT_TIMEOUT=ollama_connect_timeout
        )

