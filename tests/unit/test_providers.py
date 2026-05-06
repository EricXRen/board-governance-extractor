"""Unit tests for OpenAI and Azure provider implementations.

HTTP calls are fully mocked — no real API keys or network access required.
Tests cover: initialisation, happy-path extract, all three fallback cases
(parsed=None, AttributeError, empty/single-item dict from json_object mode),
reasoning_effort auto-detection, and extract_text / extract_raw_json.
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from gov_extract.extraction.extractor import DirectorList
from gov_extract.llm.openai_provider import OpenAIProvider, _model_uses_reasoning_effort
from gov_extract.models.board_summary import BoardSummary


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _director_dict(name: str) -> dict:
    return {
        "biographical": {
            "full_name": name,
            "qualifications": [],
            "expertise_areas": [],
            "other_directorships": [],
        },
        "board_role": {
            "designation": "Non-Executive Director",
            "board_role": "NED",
            "independence_status": "Independent",
            "year_end_status": "Active",
            "committee_memberships": [],
            "committee_chair_of": [],
            "special_roles": [],
        },
        "attendance": {"committee_attendance": []},
    }


def _parse_response(parsed_obj: object) -> MagicMock:
    """Mock response for beta.chat.completions.parse with a given parsed value."""
    choice = MagicMock()
    choice.message.parsed = parsed_obj
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


def _create_response(content: str) -> MagicMock:
    """Mock response for chat.completions.create with given message content."""
    choice = MagicMock()
    choice.message.content = content
    resp = MagicMock()
    resp.choices = [choice]
    resp.usage.prompt_tokens = 10
    resp.usage.completion_tokens = 5
    return resp


def _make_openai_provider(model: str = "gpt-4o", **kwargs: object) -> tuple[OpenAIProvider, MagicMock]:
    """Instantiate OpenAIProvider with a mocked openai.OpenAI client."""
    mock_client = MagicMock()
    with patch("openai.OpenAI", return_value=mock_client):
        provider = OpenAIProvider(model=model, api_key="test-key", **kwargs)
    return provider, mock_client


# ---------------------------------------------------------------------------
# Reasoning-effort detection
# ---------------------------------------------------------------------------

class TestModelUsesReasoningEffort:
    @pytest.mark.parametrize("model", ["o1", "o1-mini", "o3", "o3-mini", "o4", "o4-mini", "gpt-5", "gpt-5-turbo"])
    def test_reasoning_models_detected(self, model: str) -> None:
        assert _model_uses_reasoning_effort(model) is True

    @pytest.mark.parametrize("model", ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-5.4-mini"])
    def test_non_reasoning_models_not_detected(self, model: str) -> None:
        assert _model_uses_reasoning_effort(model) is False


# ---------------------------------------------------------------------------
# OpenAIProvider initialisation
# ---------------------------------------------------------------------------

class TestOpenAIProviderInit:
    def test_temperature_used_for_standard_model(self) -> None:
        provider, _ = _make_openai_provider("gpt-4o")
        assert provider.reasoning_or_temperature == {"temperature": 0}

    def test_reasoning_effort_used_for_o3_model(self) -> None:
        provider, _ = _make_openai_provider("o3-mini")
        assert "reasoning_effort" in provider.reasoning_or_temperature

    def test_reasoning_effort_value_defaults_to_medium(self) -> None:
        provider, _ = _make_openai_provider("o3-mini")
        assert provider.reasoning_or_temperature["reasoning_effort"] == "medium"

    def test_explicit_reasoning_effort_overrides_autodetect(self) -> None:
        provider, _ = _make_openai_provider("gpt-4o", reasoning_effort="high")
        assert provider.reasoning_or_temperature["reasoning_effort"] == "high"

    def test_missing_api_key_raises_value_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch("openai.OpenAI"):
                with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                    OpenAIProvider(model="gpt-4o")


# ---------------------------------------------------------------------------
# OpenAIProvider.extract() — happy path
# ---------------------------------------------------------------------------

class TestOpenAIProviderExtractHappyPath:
    def test_returns_parsed_object_from_beta_parse(self) -> None:
        provider, mock_client = _make_openai_provider()
        expected = DirectorList(directors=[])
        mock_client.beta.chat.completions.parse.return_value = _parse_response(expected)
        result = provider.extract("sys", "user", DirectorList)
        assert result is expected

    def test_correct_model_passed(self) -> None:
        provider, mock_client = _make_openai_provider("gpt-4o")
        mock_client.beta.chat.completions.parse.return_value = _parse_response(DirectorList(directors=[]))
        provider.extract("sys", "user", DirectorList)
        assert mock_client.beta.chat.completions.parse.call_args.kwargs["model"] == "gpt-4o"

    def test_response_format_is_response_model(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.beta.chat.completions.parse.return_value = _parse_response(DirectorList(directors=[]))
        provider.extract("sys", "user", DirectorList)
        assert mock_client.beta.chat.completions.parse.call_args.kwargs["response_format"] is DirectorList

    def test_temperature_in_call_for_standard_model(self) -> None:
        provider, mock_client = _make_openai_provider("gpt-4o")
        mock_client.beta.chat.completions.parse.return_value = _parse_response(DirectorList(directors=[]))
        provider.extract("sys", "user", DirectorList)
        kwargs = mock_client.beta.chat.completions.parse.call_args.kwargs
        assert kwargs["temperature"] == 0
        assert "reasoning_effort" not in kwargs

    def test_reasoning_effort_in_call_for_o3(self) -> None:
        provider, mock_client = _make_openai_provider("o3-mini")
        mock_client.beta.chat.completions.parse.return_value = _parse_response(DirectorList(directors=[]))
        provider.extract("sys", "user", DirectorList)
        kwargs = mock_client.beta.chat.completions.parse.call_args.kwargs
        assert "reasoning_effort" in kwargs

    def test_works_for_board_summary_model(self) -> None:
        provider, mock_client = _make_openai_provider()
        expected = BoardSummary(board_size=10)
        mock_client.beta.chat.completions.parse.return_value = _parse_response(expected)
        result = provider.extract("sys", "user", BoardSummary)
        assert result is expected


# ---------------------------------------------------------------------------
# OpenAIProvider.extract() — fallback: parsed is None
# ---------------------------------------------------------------------------

class TestOpenAIProviderParsedNoneFallback:
    """When beta.parse returns parsed=None the provider falls back to json_object mode."""

    def test_directors_extracted_via_directors_key(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.beta.chat.completions.parse.return_value = _parse_response(None)
        mock_client.chat.completions.create.return_value = _create_response(
            json.dumps({"directors": [_director_dict("Alice Smith")]})
        )
        result = provider.extract("sys", "user", DirectorList)
        assert isinstance(result, DirectorList)
        assert len(result.directors) == 1
        assert result.directors[0].biographical.full_name == "Alice Smith"

    def test_multiple_directors_all_returned(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.beta.chat.completions.parse.return_value = _parse_response(None)
        raw = json.dumps({"directors": [_director_dict("A"), _director_dict("B"), _director_dict("C")]})
        mock_client.chat.completions.create.return_value = _create_response(raw)
        result = provider.extract("sys", "user", DirectorList)
        assert len(result.directors) == 3


# ---------------------------------------------------------------------------
# OpenAIProvider.extract() — fallback: beta.parse raises
# ---------------------------------------------------------------------------

class TestOpenAIProviderExceptionFallback:
    """AttributeError from beta.parse (e.g. Azure schema rejection) triggers json_object fallback."""

    def test_attribute_error_falls_back_to_json_mode(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.beta.chat.completions.parse.side_effect = AttributeError("no parsed attr")
        mock_client.chat.completions.create.return_value = _create_response(
            json.dumps({"directors": [_director_dict("Alice Smith")]})
        )
        result = provider.extract("sys", "user", DirectorList)
        assert isinstance(result, DirectorList)
        assert len(result.directors) == 1



# ---------------------------------------------------------------------------
# OpenAIProvider.extract_text()
# ---------------------------------------------------------------------------

class TestOpenAIProviderExtractText:
    def test_returns_message_content(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.chat.completions.create.return_value = _create_response("## Director A\n- Role: NED")
        assert provider.extract_text("sys", "user") == "## Director A\n- Role: NED"

    def test_none_content_returns_empty_string(self) -> None:
        provider, mock_client = _make_openai_provider()
        choice = MagicMock()
        choice.message.content = None
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage.prompt_tokens = 0
        resp.usage.completion_tokens = 0
        mock_client.chat.completions.create.return_value = resp
        assert provider.extract_text("sys", "user") == ""

    def test_no_response_format_in_call(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.chat.completions.create.return_value = _create_response("text")
        provider.extract_text("sys", "user")
        assert "response_format" not in mock_client.chat.completions.create.call_args.kwargs


# ---------------------------------------------------------------------------
# OpenAIProvider.extract_raw_json()
# ---------------------------------------------------------------------------

class TestOpenAIProviderExtractRawJson:
    def test_returns_json_string(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.chat.completions.create.return_value = _create_response('{"directors": []}')
        assert provider.extract_raw_json("sys", "user") == '{"directors": []}'

    def test_json_object_response_format_used(self) -> None:
        provider, mock_client = _make_openai_provider()
        mock_client.chat.completions.create.return_value = _create_response("{}")
        provider.extract_raw_json("sys", "user")
        kwargs = mock_client.chat.completions.create.call_args.kwargs
        assert kwargs["response_format"] == {"type": "json_object"}

    def test_none_content_returns_empty_json_object(self) -> None:
        provider, mock_client = _make_openai_provider()
        choice = MagicMock()
        choice.message.content = None
        resp = MagicMock()
        resp.choices = [choice]
        resp.usage.prompt_tokens = 0
        resp.usage.completion_tokens = 0
        mock_client.chat.completions.create.return_value = resp
        assert provider.extract_raw_json("sys", "user") == "{}"


# ---------------------------------------------------------------------------
# AzureOpenAIProvider
# ---------------------------------------------------------------------------

_AZURE_ENV = {
    "AZURE_OPENAI_ENDPOINT": "https://test.openai.azure.com",
    "AZURE_OPENAI_API_KEY": "test-azure-key",
    "AZURE_OPENAI_API_VERSION": "2024-12-01-preview",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-4o-deployment",
}


def _make_azure_provider(**kwargs: object) -> tuple:
    from gov_extract.llm.azure_provider import AzureOpenAIProvider

    mock_client = MagicMock()
    with patch.dict(os.environ, _AZURE_ENV):
        with patch("openai.AzureOpenAI", return_value=mock_client) as mock_cls:
            provider = AzureOpenAIProvider(**kwargs)
    return provider, mock_client, mock_cls


class TestAzureOpenAIProviderInit:
    def test_uses_azure_openai_client_not_openai(self) -> None:
        _, _, mock_cls = _make_azure_provider()
        mock_cls.assert_called_once()

    def test_deployment_name_used_as_model(self) -> None:
        provider, _, _ = _make_azure_provider()
        assert provider.model == "gpt-4o-deployment"

    def test_explicit_deployment_overrides_env(self) -> None:
        provider, _, _ = _make_azure_provider(deployment="custom-deployment")
        assert provider.model == "custom-deployment"

    def test_azure_endpoint_passed_to_client(self) -> None:
        _, _, mock_cls = _make_azure_provider()
        assert mock_cls.call_args.kwargs["azure_endpoint"] == "https://test.openai.azure.com"

    def test_api_version_passed_to_client(self) -> None:
        _, _, mock_cls = _make_azure_provider()
        assert mock_cls.call_args.kwargs["api_version"] == "2024-12-01-preview"

    def test_temperature_used_for_standard_deployment(self) -> None:
        provider, _, _ = _make_azure_provider()
        assert provider.reasoning_or_temperature == {"temperature": 0}

    def test_reasoning_effort_used_for_o3_deployment(self) -> None:
        from gov_extract.llm.azure_provider import AzureOpenAIProvider

        mock_client = MagicMock()
        env = {**_AZURE_ENV, "AZURE_OPENAI_DEPLOYMENT": "o3-mini-deployment"}
        with patch.dict(os.environ, env):
            with patch("openai.AzureOpenAI", return_value=mock_client):
                provider = AzureOpenAIProvider()
        assert "reasoning_effort" in provider.reasoning_or_temperature

    def test_missing_endpoint_raises(self) -> None:
        from gov_extract.llm.azure_provider import AzureOpenAIProvider

        env = {k: v for k, v in _AZURE_ENV.items() if k != "AZURE_OPENAI_ENDPOINT"}
        with patch.dict(os.environ, env, clear=True):
            with patch("openai.AzureOpenAI"):
                with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
                    AzureOpenAIProvider()

    def test_missing_api_key_raises(self) -> None:
        from gov_extract.llm.azure_provider import AzureOpenAIProvider

        env = {k: v for k, v in _AZURE_ENV.items() if k != "AZURE_OPENAI_API_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with patch("openai.AzureOpenAI"):
                with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
                    AzureOpenAIProvider()

    def test_missing_deployment_raises(self) -> None:
        from gov_extract.llm.azure_provider import AzureOpenAIProvider

        env = {k: v for k, v in _AZURE_ENV.items() if k != "AZURE_OPENAI_DEPLOYMENT"}
        with patch.dict(os.environ, env, clear=True):
            with patch("openai.AzureOpenAI"):
                with pytest.raises(ValueError, match="AZURE_OPENAI_DEPLOYMENT"):
                    AzureOpenAIProvider()


class TestAzureOpenAIProviderExtract:
    """Verify Azure provider delegates to the inherited OpenAI extract logic."""

    def test_uses_deployment_name_as_model_in_api_call(self) -> None:
        provider, mock_client, _ = _make_azure_provider()
        mock_client.beta.chat.completions.parse.return_value = _parse_response(DirectorList(directors=[]))
        provider.extract("sys", "user", DirectorList)
        assert mock_client.beta.chat.completions.parse.call_args.kwargs["model"] == "gpt-4o-deployment"

    def test_fallback_directors_key_unwrapped(self) -> None:
        provider, mock_client, _ = _make_azure_provider()
        mock_client.beta.chat.completions.parse.side_effect = AttributeError("schema rejected")
        raw = json.dumps({"directors": [_director_dict("Alice Smith"), _director_dict("Bob Jones")]})
        mock_client.chat.completions.create.return_value = _create_response(raw)
        result = provider.extract("sys", "user", DirectorList)
        assert len(result.directors) == 2
