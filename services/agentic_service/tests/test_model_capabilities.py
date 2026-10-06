"""
Unit tests for model_capabilities.py -- no real Ollama/network calls, httpx and store are mocked
(mirrors test_llm_provider_service_anthropic_models.py's own established idiom).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import model_capabilities


def _mock_document(provider="ollama", model="qwen2.5-coder:14b", base_url="http://localhost:11434",
                    agent_overrides=None):
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "agent_overrides": agent_overrides or {},
    }


@pytest.fixture(autouse=True)
def _clear_cache():
    model_capabilities._capability_cache.clear()
    yield
    model_capabilities._capability_cache.clear()


def _mock_store(document):
    mock_store = MagicMock()
    mock_store.llm_settings.get_document.return_value = document
    return mock_store


@pytest.mark.asyncio
async def test_human_override_true_short_circuits_the_probe():
    document = _mock_document(agent_overrides={"coder_agent": {"supports_tool_calling": True}})

    with patch("app.services.model_capabilities.store", _mock_store(document)):
        result = await model_capabilities.supports_tool_calling("coder_agent")

    assert result is True


@pytest.mark.asyncio
async def test_human_override_false_short_circuits_the_probe():
    document = _mock_document(agent_overrides={"coder_agent": {"supports_tool_calling": False}})

    with patch("app.services.model_capabilities.store", _mock_store(document)):
        result = await model_capabilities.supports_tool_calling("coder_agent")

    assert result is False


@pytest.mark.asyncio
async def test_anthropic_provider_is_always_true_no_probe():
    document = _mock_document(agent_overrides={"coder_agent": {"provider": "anthropic", "model": "claude-sonnet-5"}})

    with (
        patch("app.services.model_capabilities.store", _mock_store(document)),
        patch("app.services.model_capabilities.httpx.AsyncClient") as mock_client_cls,
    ):
        result = await model_capabilities.supports_tool_calling("coder_agent")

    assert result is True
    mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_ollama_model_with_tools_capability_returns_true():
    # Deliberately NOT "coder_agent" -- that agent has its own real .env-driven fallback
    # (AGENTIC_MODEL_OVERRIDE, see the dedicated tests for it below), which would make this
    # test's model assertion depend on whatever the real local environment happens to have
    # configured. architecture_agent has no such fallback, isolating the plain probe behavior.
    document = _mock_document()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"capabilities": ["completion", "tools"]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.model_capabilities.store", _mock_store(document)),
        patch("app.services.model_capabilities.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await model_capabilities.supports_tool_calling("architecture_agent")

    assert result is True
    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "http://localhost:11434/api/show"
    assert call_kwargs["json"] == {"model": "qwen2.5-coder:14b"}


@pytest.mark.asyncio
async def test_ollama_model_without_tools_capability_returns_false():
    document = _mock_document()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"capabilities": ["completion"]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.model_capabilities.store", _mock_store(document)),
        patch("app.services.model_capabilities.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await model_capabilities.supports_tool_calling("coder_agent")

    assert result is False


@pytest.mark.asyncio
async def test_unreachable_ollama_server_defaults_to_false_not_true():
    import httpx

    document = _mock_document()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.model_capabilities.store", _mock_store(document)),
        patch("app.services.model_capabilities.httpx.AsyncClient", return_value=mock_client),
    ):
        result = await model_capabilities.supports_tool_calling("coder_agent")

    assert result is False


@pytest.mark.asyncio
async def test_result_is_cached_per_model_and_probe_only_runs_once():
    document = _mock_document()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"capabilities": ["tools"]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.services.model_capabilities.store", _mock_store(document)),
        patch("app.services.model_capabilities.httpx.AsyncClient", return_value=mock_client) as mock_client_cls,
    ):
        first = await model_capabilities.supports_tool_calling("coder_agent")
        second = await model_capabilities.supports_tool_calling("coder_agent")

    assert first is True
    assert second is True
    assert mock_client_cls.call_count == 1


@pytest.mark.asyncio
async def test_coder_agent_env_fallback_is_used_when_no_override_model_set():
    document = _mock_document(model="a-different-global-default")

    with (
        patch("app.services.model_capabilities.store", _mock_store(document)),
        patch("app.services.model_capabilities.settings") as mock_settings,
        patch("app.services.model_capabilities.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.AGENTIC_MODEL_OVERRIDE = "qwen3-coder:latest"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"capabilities": ["tools"]}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await model_capabilities.supports_tool_calling("coder_agent")

    call_args, call_kwargs = mock_client.post.call_args
    assert call_kwargs["json"] == {"model": "qwen3-coder:latest"}


@pytest.mark.asyncio
async def test_env_fallback_never_used_for_a_different_agent():
    document = _mock_document(model="global-default-model")

    with (
        patch("app.services.model_capabilities.store", _mock_store(document)),
        patch("app.services.model_capabilities.settings") as mock_settings,
        patch("app.services.model_capabilities.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_settings.AGENTIC_MODEL_OVERRIDE = "qwen3-coder:latest"
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {"capabilities": []}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await model_capabilities.supports_tool_calling("architecture_agent")

    call_args, call_kwargs = mock_client.post.call_args
    assert call_kwargs["json"] == {"model": "global-default-model"}
