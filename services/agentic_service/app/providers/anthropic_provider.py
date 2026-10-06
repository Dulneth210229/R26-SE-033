"""
Anthropic (Claude) LLM provider.

Calls Anthropic's real Messages API directly via httpx -- same "no SDK, just the documented REST
contract" style as OpenAIProvider, but NOT OpenAI-compatible, so none of that provider's
request/response shape can be reused: Anthropic requires `x-api-key`/`anthropic-version` headers
(never `Authorization: Bearer`), a top-level `system` field (never a message with role="system"),
a REQUIRED `max_tokens`, and a different response/streaming-event shape (a `content` block list,
not `choices[0].message`).

Default base URL:
    https://api.anthropic.com

Endpoint used:
    POST /v1/messages
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.providers.base_provider import BaseLLMProvider

ANTHROPIC_API_VERSION = "2023-06-01"


class AnthropicProvider(BaseLLMProvider):
    """
    Provider implementation for Anthropic's Messages API.
    """

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key or "",
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

    def _payload(self, prompt: str, system_prompt: str | None, stream: bool, **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }

        # `temperature` is deliberately NOT sent -- confirmed via a real, live call against this
        # model that Anthropic now rejects it outright with a 400 ("`temperature` is deprecated
        # for this model"), not just ignores it. Rather than hardcode a model-name check that
        # would silently go stale the next time Anthropic ships a model generation, this provider
        # never sends the field at all and lets the model use its own default sampling --
        # self.temperature is still stored (inherited from BaseLLMProvider, set from the same
        # per-agent settings every other provider reads) purely so a future model generation that
        # DOES accept it again is a one-line change here, not a redesign.

        # Anthropic's Messages API takes the system prompt as its own top-level field --
        # `messages` only ever accepts "user"/"assistant" roles, unlike OpenAI's convention of a
        # role="system" message.
        #
        # Prompt caching: every agent in this codebase's system prompt (CODER_AGENT_SYSTEM_PROMPT,
        # UIUX component/metadata prompts, etc.) is a large, STATIC document of rules re-sent
        # unchanged on every call -- within one UI/UX run alone, the same component-generator
        # system prompt is resent once per component; a Coder Agent coding attempt resends its
        # system prompt on every tool-calling turn. Marking it cache_control="ephemeral" lets
        # Anthropic serve every repeat of it (within the ~5 minute cache window) at a fraction of
        # normal input-token price instead of full price -- the highest-leverage, lowest-risk
        # token-cost lever available at this layer, since it changes nothing about what's sent,
        # only how it's billed. The per-call USER prompt (which genuinely varies -- different
        # component names/content each time) is deliberately NOT cached, since caching only pays
        # off for content that's actually repeated verbatim.
        if system_prompt:
            payload["system"] = [
                {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
            ]

        return payload

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        """
        Generate a complete non-streaming response.
        """
        if not self.api_key:
            raise ValueError("Anthropic API key is missing.")

        payload = self._payload(prompt, system_prompt, stream=False, **kwargs)

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/v1/messages",
                json=payload,
                headers=self._headers(),
            )

        response.raise_for_status()
        data = response.json()

        # A real Messages API response's `content` is a list of typed blocks (usually just one
        # "text" block for a plain prompt, but concatenating every text block is correct
        # regardless of how many there are, and simply skips non-text blocks like tool_use).
        return "".join(
            block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
        )

    async def stream(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncGenerator[str, None]:
        """
        Stream response chunks from Anthropic's Messages API.

        Anthropic streams several distinct SSE event types (message_start, content_block_start,
        content_block_delta, content_block_stop, message_delta, message_stop) -- only
        content_block_delta events with delta.type == "text_delta" carry actual output text;
        every other event is deliberately ignored here, not an oversight.
        """
        if not self.api_key:
            raise ValueError("Anthropic API key is missing.")

        payload = self._payload(prompt, system_prompt, stream=True, **kwargs)

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/v1/messages",
                json=payload,
                headers=self._headers(),
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue

                    raw_data = line[len("data: ") :].strip()

                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue

                    if data.get("type") != "content_block_delta":
                        continue

                    delta = data.get("delta", {})
                    if delta.get("type") == "text_delta":
                        chunk = delta.get("text")
                        if chunk:
                            yield chunk
