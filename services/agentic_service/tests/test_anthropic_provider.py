"""
Unit tests for AnthropicProvider (app/providers/anthropic_provider.py) -- confirms the real
Anthropic Messages API contract is followed correctly: x-api-key/anthropic-version headers (not
Authorization: Bearer), system prompt as a top-level field (never a role="system" message),
required max_tokens, response text extracted from the `content` block list, and only
content_block_delta/text_delta SSE events treated as streamed text. No real Anthropic API call:
httpx is mocked.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.providers.anthropic_provider import ANTHROPIC_API_VERSION, AnthropicProvider


@pytest.fixture
def provider():
    return AnthropicProvider(
        model="claude-sonnet-5",
        base_url="https://api.anthropic.com",
        api_key="sk-ant-test-key",
        temperature=0.2,
        max_tokens=4096,
        timeout_seconds=120,
    )


@pytest.mark.asyncio
async def test_generate_raises_without_api_key():
    provider = AnthropicProvider(model="claude-sonnet-5", base_url="https://api.anthropic.com", api_key=None)
    with pytest.raises(ValueError, match="API key is missing"):
        await provider.generate("hello")


@pytest.mark.asyncio
async def test_generate_sends_correct_headers_and_payload_shape(provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"content": [{"type": "text", "text": "hi there"}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.generate("hello", system_prompt="be concise")

    assert result == "hi there"

    call_args, call_kwargs = mock_client.post.call_args
    assert call_args[0] == "https://api.anthropic.com/v1/messages"

    headers = call_kwargs["headers"]
    assert headers["x-api-key"] == "sk-ant-test-key"
    assert headers["anthropic-version"] == ANTHROPIC_API_VERSION
    assert "Authorization" not in headers  # never Bearer-style, unlike OpenAIProvider

    payload = call_kwargs["json"]
    # Top-level field, not a role="system" message -- and cache_control="ephemeral" so this
    # (typically large, static) system prompt is billed at the cached rate on every repeat call
    # within the cache window, instead of full price every time.
    assert payload["system"] == [{"type": "text", "text": "be concise", "cache_control": {"type": "ephemeral"}}]
    assert payload["messages"] == [{"role": "user", "content": "hello"}]
    assert payload["max_tokens"] == 4096  # required by the real API, always sent
    assert payload["stream"] is False


@pytest.mark.asyncio
async def test_generate_never_sends_temperature(provider):
    """
    Confirmed via a real, live call against the actual Anthropic API: this model rejects
    `temperature` outright with a 400 ("`temperature` is deprecated for this model"), not just
    ignores it -- so the payload must never include the field at all, regardless of what
    self.temperature/kwargs happen to hold.
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"content": [{"type": "text", "text": "ok"}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        await provider.generate("hello", temperature=0.9)

    _, call_kwargs = mock_client.post.call_args
    assert "temperature" not in call_kwargs["json"]


@pytest.mark.asyncio
async def test_generate_marks_system_prompt_ephemeral_cache_control(provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"content": [{"type": "text", "text": "ok"}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        await provider.generate("hello", system_prompt="a large, static set of rules")

    _, call_kwargs = mock_client.post.call_args
    system = call_kwargs["json"]["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    # The per-call user prompt (genuinely varies call to call) must never be cached -- only the
    # static system prompt is.
    assert "cache_control" not in call_kwargs["json"]["messages"][0]


@pytest.mark.asyncio
async def test_generate_omits_system_field_when_no_system_prompt(provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"content": [{"type": "text", "text": "ok"}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        await provider.generate("hello", system_prompt=None)

    _, call_kwargs = mock_client.post.call_args
    assert "system" not in call_kwargs["json"]


@pytest.mark.asyncio
async def test_generate_concatenates_multiple_text_blocks_and_skips_non_text(provider):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "content": [
            {"type": "text", "text": "Hello, "},
            {"type": "tool_use", "id": "x", "name": "y", "input": {}},
            {"type": "text", "text": "world."},
        ]
    }

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.generate("hello")

    assert result == "Hello, world."


@pytest.mark.asyncio
async def test_stream_raises_without_api_key():
    provider = AnthropicProvider(model="claude-sonnet-5", base_url="https://api.anthropic.com", api_key=None)
    with pytest.raises(ValueError, match="API key is missing"):
        async for _ in provider.stream("hello"):
            pass


@pytest.mark.asyncio
async def test_stream_yields_only_text_delta_content_block_events(provider):
    sse_lines = [
        'data: {"type": "message_start", "message": {}}',
        'data: {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}',
        'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}}',
        'data: {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}}',
        'data: {"type": "content_block_stop", "index": 0}',
        'data: {"type": "message_delta", "delta": {"stop_reason": "end_turn"}}',
        'data: {"type": "message_stop"}',
    ]

    async def _fake_aiter_lines():
        for line in sse_lines:
            yield line

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

    with patch("app.providers.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        chunks = [chunk async for chunk in provider.stream("hello")]

    assert chunks == ["Hel", "lo"]

    _, call_kwargs = mock_client.stream.call_args
    assert call_kwargs["json"]["stream"] is True
    assert call_kwargs["headers"]["x-api-key"] == "sk-ant-test-key"


@pytest.mark.asyncio
async def test_invoke_agent_uses_generate_via_the_shared_base_implementation(provider):
    """
    BaseLLMProvider.invoke_agent() (unchanged, inherited) converts a messages list into
    system_prompt + user prompt and calls generate() -- confirms AnthropicProvider gets this for
    free, same as OpenAIProvider/OllamaProvider, with no override needed.
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"content": [{"type": "text", "text": "agent reply"}]}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("app.providers.anthropic_provider.httpx.AsyncClient", return_value=mock_client):
        result = await provider.invoke_agent(
            [{"role": "system", "content": "be helpful"}, {"role": "user", "content": "hi"}]
        )

    assert result == "agent reply"
    _, call_kwargs = mock_client.post.call_args
    assert call_kwargs["json"]["system"][0]["text"] == "be helpful"
    assert call_kwargs["json"]["messages"] == [{"role": "user", "content": "hi"}]
