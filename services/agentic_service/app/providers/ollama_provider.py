"""
Ollama LLM provider.

This provider calls a local Ollama server.

Default Ollama server:
    http://localhost:11434

Useful commands:
    ollama serve
    ollama pull llama3.1
    ollama pull qwen2.5-coder
    ollama list

Ollama generate endpoint:
    POST /api/generate

This provider supports:
- generate()
- stream()
- invoke_agent() inherited from BaseLLMProvider
"""

from collections.abc import AsyncGenerator
from typing import Any

import httpx

from app.core.config import settings
from app.providers.base_provider import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """
    Provider implementation for local Ollama models.
    """

    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        """
        Generate a complete response from Ollama.

        stream is set to False because this method returns full output.
        """
        final_prompt = self._build_prompt(prompt, system_prompt)

        payload = {
            "model": self.model,
            "prompt": final_prompt,
            "stream": False,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "num_predict": kwargs.get("max_tokens", self.max_tokens),
                # Without this, Ollama falls back to its own server-side default context
                # window (historically 2048-4096) and silently truncates a long prompt --
                # already confirmed as a real failure mode elsewhere in this project (the
                # agentic tool-calling path sets this same value; this one-shot path
                # previously didn't, and every one-shot agent's prompt can carry a full
                # SRS/architecture plan/project manifest).
                "num_ctx": settings.AGENTIC_OLLAMA_NUM_CTX,
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json=payload
            )

        response.raise_for_status()
        data = response.json()

        return data.get("response", "")

    async def stream(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncGenerator[str, None]:
        """
        Stream response chunks from Ollama.

        Ollama returns JSON lines when stream=True.
        Each line may contain a response chunk.
        """
        final_prompt = self._build_prompt(prompt, system_prompt)

        payload = {
            "model": self.model,
            "prompt": final_prompt,
            "stream": True,
            "options": {
                "temperature": kwargs.get("temperature", self.temperature),
                "num_predict": kwargs.get("max_tokens", self.max_tokens),
                "num_ctx": settings.AGENTIC_OLLAMA_NUM_CTX,
            },
        }

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        data = httpx.Response(
                            status_code=200,
                            content=line
                        ).json()
                    except Exception:
                        continue

                    chunk = data.get("response")

                    if chunk:
                        yield chunk

                    if data.get("done") is True:
                        break

    def _build_prompt(self, prompt: str, system_prompt: str | None = None) -> str:
        """
        Ollama /api/generate accepts one prompt string.

        We manually combine system prompt and user prompt.
        """
        if not system_prompt:
            return prompt

        return f"""SYSTEM INSTRUCTIONS:
{system_prompt}

USER INPUT:
{prompt}
"""