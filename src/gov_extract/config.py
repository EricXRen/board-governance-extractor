"""Configuration loading: config.yaml + environment variables + .env file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _load_yaml(path: Path) -> dict[str, Any]:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


class LLMConfig(BaseSettings):
    """LLM provider configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    default_provider: str = "anthropic"
    default_model: str = "claude-sonnet-4-6"
    judge_provider: str = "openai"
    judge_model: str = "gpt-4o-mini"
    temperature: int = 0
    reasoning_effort: str | None = None  # "low" | "medium" | "high"; auto-detected if None
    chunking: bool = True                # True = chunk pages; False = single pass over all pages
    extraction_rounds: int = 1           # 1 = direct structured output; 2 = markdown then structured
    max_retries: int = 5
    timeout_seconds: int = 120


class PDFConfig(BaseSettings):
    """PDF ingestion configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    cache_dir: str = "~/.gov_extract/cache"
    max_pages_per_chunk: int = 15
    governance_keywords: list[str] = [
        "board of directors",
        "directors' report",
        "our board",
        "committee report",
        "proxy statement",
        "governance",
    ]


class OutputConfig(BaseSettings):
    """Output configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    default_dir: str = "./outputs"


class LoggingConfig(BaseSettings):
    """Logging configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    level: str = "INFO"
    format: str = "json"
    file: str = "gov_extract.log"


class RegressionGateConfig(BaseSettings):
    """Thresholds for the evaluation regression gate."""

    model_config = SettingsConfigDict(extra="ignore")

    document_field_pass_rate: float = 0.90
    director_perfect_match_rate: float = 0.50
    hallucination_rate: float = 0.05


class EvaluationThresholds(BaseSettings):
    """Per-metric pass thresholds."""

    model_config = SettingsConfigDict(extra="ignore")

    fuzzy_match: float = 90.0
    list_f1: float = 0.90
    semantic_similarity: float = 0.80
    numeric_error_tolerance: float = 0.05


class EvaluationConfig(BaseSettings):
    """Evaluation harness configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    field_metrics: dict[str, str] = Field(default_factory=dict)
    thresholds: EvaluationThresholds = Field(default_factory=EvaluationThresholds)
    regression_gate: RegressionGateConfig = Field(default_factory=RegressionGateConfig)


class Config:
    """Root configuration object built from config.yaml + env overrides."""

    def __init__(self, config_path: Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config.yaml"

        raw = _load_yaml(config_path)

        self.llm = LLMConfig(**raw.get("llm", {}))
        self.pdf = PDFConfig(**raw.get("pdf", {}))
        self.output = OutputConfig(**raw.get("output", {}))
        self.logging = LoggingConfig(**raw.get("logging", {}))

        eval_raw = raw.get("evaluation", {})
        thresholds_raw = eval_raw.get("thresholds", {})
        gate_raw = eval_raw.get("regression_gate", {})

        self.evaluation = EvaluationConfig(
            field_metrics=eval_raw.get("field_metrics", {}),
            thresholds=EvaluationThresholds(**thresholds_raw),
            regression_gate=RegressionGateConfig(**gate_raw),
        )


_instance: Config | None = None


def get_config(config_path: Path | None = None) -> Config:
    """Return the singleton Config, optionally loading from a custom path."""
    global _instance
    if _instance is None or config_path is not None:
        _instance = Config(config_path)
    return _instance
