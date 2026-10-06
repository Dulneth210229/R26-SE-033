"""
OpenAI-compatible LLM provider.

This provider calls OpenAI Chat Completions API style endpoints.

Default base URL:
    https://api.openai.com/v1

Endpoint used:
    POST /chat/completions

This can also support OpenAI-compatible APIs later if they follow
the same /chat/completions format.
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.providers.base_provider import BaseLLMProvider


class OpenAIProvider(BaseLLMProvider):
    """
    Provider implementation for OpenAI-compatible APIs.
    """

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        """
        Generate a complete non-streaming response.
        """
        if not self.api_key:
            raise ValueError("OpenAI API key is missing.")

        messages = self._build_messages(prompt, system_prompt)

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers
            )

        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]

    async def stream(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncGenerator[str, None]:
        """
        Stream response chunks from OpenAI-compatible chat completions API.
        """
        if not self.api_key:
            raise ValueError("OpenAI API key is missing.")

        messages = self._build_messages(prompt, system_prompt)

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    # OpenAI streams lines like:
                    # data: {"choices":[{"delta":{"content":"Hello"}}]}
                    if not line.startswith("data: "):
                        continue

                    raw_data = line.replace("data: ", "").strip()

                    if raw_data == "[DONE]":
                        break

                    try:
                        data = json.loads(raw_data)
                    except json.JSONDecodeError:
                        continue

                    delta = data["choices"][0].get("delta", {})
                    chunk = delta.get("content")

                    if chunk:
                        yield chunk

    def _build_messages(self,  prompt: str, system_prompt: str | None = None) -> list[dict[str, str]]:
        """
        Build OpenAI-style chat messages.
        """
        messages: list[dict[str, str]] = []

        if system_prompt:
            messages.append({
                "role": "system",
                "content": system_prompt
            })

        messages.append({
            "role": "user",
            "content": prompt
        })

        return messages