from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type
from pydantic import BaseModel

class BaseLLMProvider(ABC):
    """
    Abstract Base Class for LLM providers.
    Defines the unified interface for structured data extraction.
    """
    @abstractmethod
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
        """
        Extracts structured data from HTML content using the LLM.
        """
        pass

    @abstractmethod
    def generate_schema(self, model_class: Type[BaseModel]) -> Any:
        """
        Generates a schema representation of the model for the provider.
        """
        pass
