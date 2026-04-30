"""LLMProvider protocol definition."""

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM provider implementations must satisfy."""

    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        """Extract structured data using the LLM.

        Args:
            system_prompt: Instructions for the LLM role and output format.
            user_prompt: The text chunk to extract from.
            response_model: Pydantic model class defining the expected structure.

        Returns:
            Validated Pydantic model instance populated from the LLM response.
        """
        ...

    def extract_raw_json(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Fallback extraction returning raw JSON string.

        Args:
            system_prompt: Instructions for the LLM role and output format.
            user_prompt: The text chunk to extract from.

        Returns:
            Raw JSON string from the LLM response.
        """
        ...

    def extract_text(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """Free-text extraction with no JSON or structured-output constraints.

        Used by the two_pass_markdown strategy for the first (markdown) round.

        Args:
            system_prompt: Instructions for the LLM role and output format.
            user_prompt: The text chunk to extract from.

        Returns:
            Plain text (e.g. Markdown) response from the LLM.
        """
        ...
