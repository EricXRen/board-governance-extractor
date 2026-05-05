"""OpenAI / DeepSeek provider using structured output or JSON mode."""

from __future__ import annotations

import json
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

# Model name prefixes that use reasoning_effort instead of temperature.
# gpt-5 and later reasoning models dropped the temperature parameter.
_REASONING_EFFORT_PREFIXES = ("o1", "o3", "o4", "gpt-5")


def _model_uses_reasoning_effort(model: str) -> bool:
    """Return True if the model uses reasoning_effort instead of temperature.

    Args:
        model: Model ID string, e.g. "gpt-5", "o3-mini", "gpt-4o".

    Returns:
        True for o1/o3/o4/gpt-5 series models; False otherwise.
    """
    lower = model.lower()
    return any(lower == prefix or lower.startswith(prefix + "-") for prefix in _REASONING_EFFORT_PREFIXES)


class OpenAIProvider:
    """LLM provider backed by OpenAI-compatible APIs (OpenAI, DeepSeek)."""

    def __init__(
        self,
        model: str,
        temperature: int = 0,
        reasoning_effort: str | None = None,
        timeout: int = 120,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Initialise the OpenAI client.

        Args:
            model: Model ID, e.g. "gpt-4o" or "gpt-5".
            temperature: Sampling temperature. Ignored for reasoning-effort models.
            reasoning_effort: Reasoning effort level ("low", "medium", "high").
                If provided, overrides temperature for any model. If None, the
                provider auto-detects based on the model name.
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
        # Explicit reasoning_effort takes priority; otherwise auto-detect from model name.
        self.reasoning_effort: str | None = reasoning_effort if reasoning_effort is not None else (
            "medium" if _model_uses_reasoning_effort(model) else None
        )
        self.reasoning_or_temperature: dict = (
            {"reasoning_effort": self.reasoning_effort, "temperature": 1}   
            if self.reasoning_effort is not None
            else {"temperature": self.temperature}
        )
        

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
                **self.reasoning_or_temperature,
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
        try:
            return response_model.model_validate_json(raw)
        except Exception:
            # json_object mode always returns a dict; RootModel[list[...]] expects
            # an array. Azure OpenAI doesn't support root-level array schemas, so
            # the model may wrap the list under a key or return a single object.
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                # Empty dict → no results; map to an empty list for list-typed models.
                if not parsed:
                    try:
                        return response_model.model_validate([])
                    except Exception:
                        pass
                for key in ("root", "directors", "items", "data", "results"):
                    if key in parsed:
                        try:
                            return response_model.model_validate(parsed[key])
                        except Exception:
                            continue
                # Non-empty dict with no known key: treat as a single-item list.
                if parsed:
                    try:
                        return response_model.model_validate([parsed])
                    except Exception:
                        pass
            raise

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def extract_text(self, system_prompt: str, user_prompt: str) -> str:
        """Extract free-form text (e.g. Markdown) with no structured-output constraints.

        Args:
            system_prompt: System instructions.
            user_prompt: User message with text to extract from.

        Returns:
            Plain text response from the model.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            **self.reasoning_or_temperature,
        )
        usage = response.usage
        logger.info(
            "llm_call",
            provider="openai",
            model=self.model,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )
        return response.choices[0].message.content or ""

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
            **self.reasoning_or_temperature,
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
