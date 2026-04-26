"""Anthropic Claude provider using tool-use for structured output."""

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


class AnthropicProvider:
    """LLM provider backed by Anthropic Claude models."""

    def __init__(self, model: str, temperature: int = 0, timeout: int = 120) -> None:
        """Initialise the Anthropic client.

        Args:
            model: Model ID, e.g. "claude-sonnet-4-6".
            temperature: Sampling temperature (must be 0 for reproducibility).
            timeout: Request timeout in seconds.
        """
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.timeout = timeout

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
        """Extract structured data via Anthropic tool use.

        Args:
            system_prompt: System instructions.
            user_prompt: User message with text to extract from.
            response_model: Pydantic model class for the response schema.

        Returns:
            Populated Pydantic model instance.
        """
        import anthropic

        schema = response_model.model_json_schema()
        tool_def = {
            "name": "extract_governance_data",
            "description": "Extract board governance data from the provided text",
            "input_schema": schema,
        }

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=8192,
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
                tools=[tool_def],
                tool_choice={"type": "any"},
            )
        except anthropic.RateLimitError as e:
            logger.warning("anthropic_rate_limit", error=str(e))
            raise
        except anthropic.APITimeoutError as e:
            logger.warning("anthropic_timeout", error=str(e))
            raise

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        logger.info(
            "llm_call",
            provider="anthropic",
            model=self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_governance_data":
                return response_model.model_validate(block.input)

        # Fallback: try to parse text content as JSON
        for block in response.content:
            if hasattr(block, "text"):
                return response_model.model_validate_json(block.text)

        raise ValueError("No structured output returned by Anthropic API")

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type(Exception),
        reraise=True,
    )
    def extract_raw_json(self, system_prompt: str, user_prompt: str) -> str:
        """Extract raw JSON string from the model.

        Args:
            system_prompt: System instructions.
            user_prompt: User message with text to extract from.

        Returns:
            Raw JSON string.
        """
        response = self._client.messages.create(
            model=self.model,
            max_tokens=8192,
            temperature=self.temperature,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        logger.info(
            "llm_call",
            provider="anthropic",
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        for block in response.content:
            if hasattr(block, "text"):
                text = block.text.strip()
                # Strip markdown code fences if present
                if text.startswith("```"):
                    lines = text.splitlines()
                    text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
                return text

        raise ValueError("No text content returned by Anthropic API")
