"""
Unit tests for LLMProviderService.list_anthropic_models (app/services/llm_provider_service.py) --
the Claude-side counterpart to the existing list_ollama_models, powering the chat composer's
model dropdown so Claude models are offered as real, current, selectable options instead of only
appearing by accident. No real Anthropic API call: httpx is mocked. A real, live-verified call was
already used earlier this session to confirm the actual GET /v1/models response shape this test
data mirrors.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_provider_service import llm_provider_service


@pytest.mark.asyncio
async def test_list_anthropic_models_returns_empty_list_without_api_key():
    with patch("app.services.llm_provider_service.settings") as mock_settings:
        mock_settings.ANTHROPIC_API_KEY = None

        models = await llm_provider_service.list_anthropic_models()

    assert models == []


@pytest.mark.asyncio
async def test_list_anthropic_models_returns_real_model_ids():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "data": [
            {"type": "model", "id": "claude-opus-5", "display_name": "Claude Opus 5"},
            {"type": "model", "id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"},
        ]
    }

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.llm_provider_service.settings") as mock_settings,
        patch("app.services.llm_provider_service.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test-key"
        mock_settings.ANTHROPIC_BASE_URL = "https://api.anthropic.com"

        models = await llm_provider_service.list_anthropic_models()

    assert models == ["claude-opus-5", "claude-sonnet-5"]

    call_args, call_kwargs = mock_client.get.call_args
    assert call_args[0] == "https://api.anthropic.com/v1/models"
    assert call_kwargs["headers"]["x-api-key"] == "sk-ant-test-key"
    assert "anthropic-version" in call_kwargs["headers"]
    assert "Authorization" not in call_kwargs["headers"]


@pytest.mark.asyncio
async def test_list_anthropic_models_skips_entries_without_an_id():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"data": [{"type": "model", "display_name": "no id here"}]}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.llm_provider_service.settings") as mock_settings,
        patch("app.services.llm_provider_service.httpx.AsyncClient", return_value=mock_client),
    ):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test-key"
        mock_settings.ANTHROPIC_BASE_URL = "https://api.anthropic.com"

        models = await llm_provider_service.list_anthropic_models()

    assert models == []
