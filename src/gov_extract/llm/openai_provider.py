"""OpenAI / DeepSeek provider using structured output or JSON mode."""

from __future__ import annotations

import os

import structlog
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = structlog.get_logger()


class OpenAIProvider:
    """LLM provider backed by OpenAI-compatible APIs (OpenAI, DeepSeek)."""

    def __init__(
        self,
        model: str,
        temperature: int = 0,
        timeout: int = 120,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialise the OpenAI client.

        Args:
            model: Model ID, e.g. "gpt-4o".
            temperature: Sampling temperature.
            timeout: Request timeout in seconds.
            base_url: Optional base URL override (e.g. for DeepSeek).
            api_key: API key. Falls back to OPENAI_API_KEY env var.
        """
        import openai

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not resolved_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")

        resolved_base_url = base_url or os.environ.get("OPENAI_BASE_URL")

        self._client = openai.OpenAI(
            api_key=resolved_key,
            base_url=resolved_base_url,
            timeout=timeout,
        )
        self.model = model
        self.temperature = temperature

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def extract(
        self,
        system_prompt: str,
        user_prompt: str,
        response_model: type[BaseModel],
    ) -> BaseModel:
        """Extract structured data using OpenAI structured output.

        Args:
            system_prompt: System instructions.
            user_prompt: User message with text to extract from.
            response_model: Pydantic model class for the response schema.

        Returns:
            Populated Pydantic model instance.
        """
        import openai

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            response = self._client.beta.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=response_model,
                temperature=self.temperature,
            )
            usage = response.usage
            logger.info(
                "llm_call",
                provider="openai",
                model=self.model,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
            )
            choice = response.choices[0]
            if choice.message.parsed is not None:
                return choice.message.parsed
            # Fall through to JSON mode if parsed is None
        except (openai.BadRequestError, AttributeError):
            pass

        # Fallback: JSON object mode
        raw = self.extract_raw_json(system_prompt, user_prompt)
        return response_model.model_validate_json(raw)

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def extract_raw_json(self, system_prompt: str, user_prompt: str) -> str:
        """Extract raw JSON string using JSON mode.

        Args:
            system_prompt: System instructions.
            user_prompt: User message with text to extract from.

        Returns:
            Raw JSON string.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=self.temperature,
        )
        usage = response.usage
        logger.info(
            "llm_call",
            provider="openai",
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
        return response.choices[0].message.content or "{}"
