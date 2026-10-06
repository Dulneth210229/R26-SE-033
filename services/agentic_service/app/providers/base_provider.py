"""
Base LLM provider.

All LLM providers must follow this same interface.

Why this is important:
- Requirement Agent should not care whether the model is Ollama or OpenAI.
- Domain Agent should not call Ollama directly.
- Architecture Agent should use the same provider service.
- Later, we can add Anthropic, Groq, Gemini, or Azure OpenAI without changing agent logic.

Every provider must implement:
- generate()
- stream()
- invoke_agent()
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.
    """

    def __init__(
        self,
        model: str,
        base_url: str,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        timeout_seconds: int = 120,
        api_key: str | None = None,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.api_key = api_key

    @abstractmethod
    async def generate(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> str:
        """
        Generate a full non-streaming response.

        Used when the backend wants the final complete output at once.
        """
        raise NotImplementedError

    @abstractmethod
    async def stream(self, prompt: str, system_prompt: str | None = None, **kwargs: Any) -> AsyncGenerator[str, None]:
        """
        Stream output token by token or chunk by chunk.

        Used by SSE/WebSocket endpoints later.
        """
        raise NotImplementedError

    async def invoke_agent(self, messages: list[dict[str, str]],**kwargs: Any) -> str:
        """
        Generic agent invocation.

        Agents usually work with messages:
        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."}
        ]

        This method converts messages into system_prompt + user prompt.
        """
        system_prompt = None
        user_parts: list[str] = []

        for message in messages:
            role = message.get("role")
            content = message.get("content", "")

            if role == "system":
                system_prompt = content
            elif role == "user":
                user_parts.append(content)

        prompt = "\n\n".join(user_parts)

        return await self.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            **kwargs
        )