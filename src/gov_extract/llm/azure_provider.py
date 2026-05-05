"""Azure OpenAI provider — subclasses OpenAIProvider with Azure-specific init."""

from __future__ import annotations

import os

import structlog

from gov_extract.llm.openai_provider import OpenAIProvider

logger = structlog.get_logger()


class AzureOpenAIProvider(OpenAIProvider):
    """LLM provider backed by Azure OpenAI deployments."""

    def __init__(
        self,
        deployment: str | None = None,
        temperature: int = 0,
        reasoning_effort: str | None = None,
        timeout: int = 120,
    ) -> None:
        """Initialise the Azure OpenAI client.

        Args:
            deployment: Azure deployment name. Falls back to AZURE_OPENAI_DEPLOYMENT.
            temperature: Sampling temperature. Ignored for reasoning-effort deployments.
            reasoning_effort: Reasoning effort level ("low", "medium", "high").
                If provided, overrides temperature. If None, auto-detected from the
                deployment name using the same heuristic as OpenAIProvider.
            timeout: Request timeout in seconds.
        """
        import openai

        from gov_extract.llm.openai_provider import _model_uses_reasoning_effort

        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        api_key = os.environ.get("AZURE_OPENAI_API_KEY")
        api_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
        resolved_deployment = deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT")

        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is not set")
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY environment variable is not set")
        if not resolved_deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT environment variable is not set")

        self._client = openai.AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=api_version,
        )
        # For Azure, the deployment name is used as the model parameter
        self.model = resolved_deployment
        self.temperature = temperature
        self.reasoning_effort: str | None = reasoning_effort if reasoning_effort is not None else (
            "medium" if _model_uses_reasoning_effort(resolved_deployment) else None
        )
        self.reasoning_or_temperature: dict = (
            {"reasoning_effort": self.reasoning_effort, "temperature": 1}   
            if self.reasoning_effort is not None
            else {"temperature": self.temperature}
        )
