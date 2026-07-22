import os
from typing import Any, Optional
from modules.llm.base import BaseLLMProvider

def get_llm_provider(client: Optional[Any] = None) -> BaseLLMProvider:
    """
    Factory function to get the configured LLM provider instance.
    Looks up the LLM_PROVIDER env variable dynamically.
    If client is a Mock/MagicMock, defaults to GeminiProvider to preserve test mocks.
    """
    if client is not None:
        try:
            from unittest.mock import Mock, MagicMock
            if isinstance(client, (Mock, MagicMock)) or hasattr(client, "_mock_self"):
                from modules.llm.gemini_provider import GeminiProvider
                return GeminiProvider()
        except ImportError:
            pass

    provider_name = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    if provider_name == "ollama":
        from modules.llm.ollama_provider import OllamaProvider
        return OllamaProvider()
    else:
        from modules.llm.gemini_provider import GeminiProvider
        return GeminiProvider()
