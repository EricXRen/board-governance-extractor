"""Factory function: build an LLMProvider from configuration."""

from __future__ import annotations

import structlog

from gov_extract.config import Config
from gov_extract.llm.base import LLMProvider

logger = structlog.get_logger()

_PROVIDERS = {
    "anthropic": "gov_extract.llm.anthropic_provider.AnthropicProvider",
    "openai":    "gov_extract.llm.openai_provider.OpenAIProvider",
    "deepseek":  "gov_extract.llm.openai_provider.OpenAIProvider",
    "azure_openai": "gov_extract.llm.azure_provider.AzureOpenAIProvider",
}


def get_provider(
    config: Config, provider_name: str | None = None, model: str | None = None
) -> LLMProvider:
    """Build and return an LLMProvider instance.

    Args:
        config: Application configuration.
        provider_name: Override for the provider (e.g. "anthropic"). Falls back
            to config.llm.default_provider.
        model: Override for the model ID. Falls back to config.llm.default_model.

    Returns:
        An initialised LLMProvider.

    Raises:
        ValueError: If the provider name is not recognised.
    """
    resolved_provider = provider_name or config.llm.default_provider
    resolved_model = model or config.llm.default_model

    if resolved_provider not in _PROVIDERS:
        raise ValueError(
            f"Unknown provider '{resolved_provider}'. Supported: {list(_PROVIDERS.keys())}"
        )

    dotted = _PROVIDERS[resolved_provider]
    module_path, class_name = dotted.rsplit(".", 1)

    import importlib

    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)

    logger.info("provider_init", provider=resolved_provider, model=resolved_model)

    if resolved_provider == "anthropic":
        return cls(
            model=resolved_model,
            temperature=config.llm.temperature,
            timeout=config.llm.timeout_seconds,
        )  # type: ignore[return-value]
    elif resolved_provider == "openai":
        return cls(
            model=resolved_model,
            temperature=config.llm.temperature,
            reasoning_effort=config.llm.reasoning_effort,
            timeout=config.llm.timeout_seconds,
        )  # type: ignore[return-value]
    elif resolved_provider == "azure_openai":
        return cls(
            deployment=resolved_model,
            temperature=config.llm.temperature,
            reasoning_effort=config.llm.reasoning_effort,
            timeout=config.llm.timeout_seconds,
        )  # type: ignore[return-value]
    else:
        return cls()  # type: ignore[return-value]
