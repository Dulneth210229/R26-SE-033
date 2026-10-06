"""
Unit tests for OllamaProvider (app/providers/ollama_provider.py) -- confirms the
num_ctx fix: generate()/stream() previously built their Ollama `options` payload with
only temperature/num_predict, exposing this one-shot path (used by every single-shot
agent call, including CodePlanner.generate() and Requirement/Domain/Architecture
Agent's own one-shot calls) to Ollama's server-side default context window -- the
same "silently truncates a long prompt" gotcha this project already documented and
worked around defensively elsewhere, but never patched at the source. No real Ollama
server: httpx is mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.providers.ollama_provider import OllamaProvider


@pytest.fixture
def provider():
    return OllamaProvider(
        model="qwen3-coder:latest",
        base_url="http://localhost:11434",
        temperature=0.2,
        max_tokens=4096,
        timeout_seconds=120,
    )


@pytest.mark.asyncio
async def test_generate_sends_num_ctx(provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"response": "ok"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.ollama_provider.httpx.AsyncClient", return_value=mock_client):
        await provider.generate("hello", system_prompt=None)

    _, call_kwargs = mock_client.post.call_args
    assert call_kwargs["json"]["options"]["num_ctx"] == settings.AGENTIC_OLLAMA_NUM_CTX


@pytest.mark.asyncio
async def test_stream_sends_num_ctx(provider):
    async def _fake_aiter_lines():
        yield '{"response": "hi", "done": true}'

    mock_stream_response = MagicMock()
    mock_stream_response.raise_for_status = MagicMock()
    mock_stream_response.aiter_lines = _fake_aiter_lines

    class _FakeStreamContext:
        async def __aenter__(self):
            return mock_stream_response

        async def __aexit__(self, *args):
            return False

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_FakeStreamContext())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.ollama_provider.httpx.AsyncClient", return_value=mock_client):
        chunks = [chunk async for chunk in provider.stream("hello", system_prompt=None)]

    assert chunks == ["hi"]
    _, call_kwargs = mock_client.stream.call_args
    assert call_kwargs["json"]["options"]["num_ctx"] == settings.AGENTIC_OLLAMA_NUM_CTX
