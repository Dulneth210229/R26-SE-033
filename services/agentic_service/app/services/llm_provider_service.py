"""
LLM provider service.

This service is the main entry point for agents.

Agents should not directly create OllamaProvider or OpenAIProvider.
Instead, agents should call:

    llm_provider_service.get_provider()

Why:
- Keeps provider selection centralized.
- Allows switching provider from settings.
- Avoids repeating configuration code in every agent.
"""

import httpx

from app.core.config import settings
from app.providers.anthropic_provider import ANTHROPIC_API_VERSION, AnthropicProvider
from app.providers.base_provider import BaseLLMProvider
from app.providers.ollama_provider import OllamaProvider
from app.providers.openai_provider import OpenAIProvider
from app.schemas.llm_schema import (
    AgentLLMOverrideUpdateRequest,
    AgentLLMSettingsResponse,
    LLMSettings,
    LLMSettingsUpdateRequest,
    OllamaAvailableModel,
    OllamaRunningModel,
    OllamaStatusResponse,
)

from app.services.in_memory_store import store

# Every agent that can have its own LLM override configured through the UI. security_agent/
# qa_agent's own chat composer already renders a real, live ModelSelect control (the same shared
# component every agent uses) -- before this list included them, picking a model there was a
# silent dead end (PUT /settings/llm/agents/{name} raised ValueError -> 400, never surfaced to the
# human). get_provider(agent_name=...) and _resolve_effective_settings are already agent-name-
# agnostic, so listing an agent here is the ONLY thing needed to make its already-rendered picker
# actually work end-to-end (chat, and for security_agent, the deep scan + LLM review layer too --
# all three already resolve their model through this exact same call).
OVERRIDABLE_AGENTS = [
    "requirement_agent",
    "domain_agent",
    "architecture_agent",
    "uiux_agent",
    "coder_agent",
    "security_agent",
    "qa_agent",
]


class LLMProviderService:
    """
    Service for managing LLM configuration and provider creation.
    """

    SUPPORTED_PROVIDERS = {"ollama", "openai", "anthropic"}

    def get_settings(self) -> LLMSettings:
        """
        Return current LLM settings.

        Important:
        Do not return the real API key.
        Only return whether the key is configured.
        """
        return self._build_settings_response(store.llm_settings.get_document())

    def _build_settings_response(self, document: dict) -> LLMSettings:
        """
        Same as get_settings(), but from an already-fetched document -- avoids a second
        round-trip when a caller (e.g. list_agent_overrides) already has one in hand.
        """
        return LLMSettings(
            provider=document["provider"],
            model=document["model"],
            base_url=document["base_url"],
            api_key_reference="API_KEY_CONFIGURED" if document.get("api_key") else None,
            temperature=document["temperature"],
            max_tokens=document["max_tokens"],
            streaming_enabled=document["streaming_enabled"],
            timeout_seconds=document["timeout_seconds"],
        )

    def update_settings(self, request: LLMSettingsUpdateRequest) -> LLMSettings:
        """
        Update selected LLM settings.

        Only fields provided by the user are changed.
        """
        current = store.llm_settings

        if request.provider is not None:
            provider = request.provider.lower()

            if provider not in self.SUPPORTED_PROVIDERS:
                raise ValueError(
                    f"Unsupported provider '{request.provider}'. "
                    f"Supported providers: {self.SUPPORTED_PROVIDERS}"
                )

            current["provider"] = provider

        if request.model is not None:
            current["model"] = request.model

        if request.base_url is not None:
            current["base_url"] = request.base_url.rstrip("/")

        if request.api_key is not None:
            # Store the real key internally only.
            # Never return this key through API responses.
            current["api_key"] = request.api_key

        if request.temperature is not None:
            current["temperature"] = request.temperature

        if request.max_tokens is not None:
            current["max_tokens"] = request.max_tokens

        if request.streaming_enabled is not None:
            current["streaming_enabled"] = request.streaming_enabled

        if request.timeout_seconds is not None:
            current["timeout_seconds"] = request.timeout_seconds

        return self.get_settings()

    def _resolve_effective_settings(self, document: dict, agent_name: str | None) -> dict:
        """
        Merge a per-agent override (if any) onto the global defaults -- pure, no I/O; `document`
        must already be a fetched `store.llm_settings.get_document()` result.

        `base_url`/`api_key` are intentionally never overridable per-agent for Ollama/OpenAI --
        both are one shared connection (one Ollama daemon, one OpenAI-compatible endpoint) this
        whole app talks to, and per-agent overrides only ever need to change WHICH model/
        provider/generation parameters are used, not where to connect. Anthropic is the one
        exception, and deliberately NOT handled here: get_provider() sources its base_url/api_key
        from `settings.ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY` (.env) directly, never from this
        shared document, for the same reason agentic_model_factory.py already treats Anthropic's
        credential as a separate, provider-specific value rather than the shared field -- an
        agent switched to Anthropic is deliberately using a categorically different connection
        than whatever Ollama/OpenAI endpoint the shared fields point at, not a same-family model
        swap the way choosing a different Ollama model is.
        """
        override = document.get("agent_overrides", {}).get(agent_name, {}) if agent_name else {}

        merged = dict(document)
        for field in ("provider", "model", "temperature", "max_tokens", "timeout_seconds"):
            if override.get(field) is not None:
                merged[field] = override[field]

        return merged

    def get_provider(self, agent_name: str | None = None) -> BaseLLMProvider:
        """
        Create and return the provider instance for the given agent.

        If the agent has a configured override (see agent_overrides in store.llm_settings), its
        provider/model/generation-parameter fields take priority over the global defaults.
        `agent_name` is optional so existing callers with no specific agent (e.g. the LLM Settings
        "test" endpoint, which is testing the global config itself) keep working unchanged.
        """
        current = self._resolve_effective_settings(store.llm_settings.get_document(), agent_name)

        provider_name = current["provider"]

        if provider_name == "ollama":
            return OllamaProvider(
                model=current["model"],
                base_url=current["base_url"],
                temperature=current["temperature"],
                max_tokens=current["max_tokens"],
                timeout_seconds=current["timeout_seconds"],
            )

        if provider_name == "openai":
            return OpenAIProvider(
                model=current["model"],
                base_url=current["base_url"],
                api_key=current.get("api_key"),
                temperature=current["temperature"],
                max_tokens=current["max_tokens"],
                timeout_seconds=current["timeout_seconds"],
            )

        if provider_name == "anthropic":
            # base_url/api_key come from .env (settings), not `current` -- see
            # _resolve_effective_settings's own docstring for why Anthropic is the one
            # exception to "base_url/api_key are shared, never per-agent."
            return AnthropicProvider(
                model=current["model"],
                base_url=settings.ANTHROPIC_BASE_URL,
                api_key=settings.ANTHROPIC_API_KEY,
                temperature=current["temperature"],
                max_tokens=current["max_tokens"],
                timeout_seconds=current["timeout_seconds"],
            )

        raise ValueError(f"Unsupported LLM provider: {provider_name}")

    async def list_ollama_models(self) -> list[str]:
        """
        List the model names currently available on the Ollama server configured in
        LLMSettings.base_url (i.e. the same server get_provider() would actually talk to for an
        "ollama" agent -- read from the live, user-configurable settings document, not a
        hardcoded default, so this always reflects whatever the LLM Settings page currently has
        set). Used by the chat model-picker so the frontend can offer a real, current list
        instead of a free-text field.
        """
        base_url = store.llm_settings.get_document()["base_url"]

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{base_url}/api/tags")

        response.raise_for_status()
        data = response.json()

        return [model["name"] for model in data.get("models", []) if model.get("name")]

    async def list_anthropic_models(self) -> list[str]:
        """
        List the real, current model IDs available on the Anthropic account configured via
        settings.ANTHROPIC_API_KEY (.env) -- same "always live, real, current" precedent as
        list_ollama_models, confirmed via a real call to work exactly like Anthropic's own
        documented `GET /v1/models` contract (`{"data": [{"id": "...", ...}, ...]}`).

        Returns [] (never raises) when no key is configured -- a missing key means "nothing to
        offer," not a hard failure the chat model-picker should block on.
        """
        if not settings.ANTHROPIC_API_KEY:
            return []

        headers = {
            "x-api-key": settings.ANTHROPIC_API_KEY,
            "anthropic-version": ANTHROPIC_API_VERSION,
        }

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{settings.ANTHROPIC_BASE_URL}/v1/models", headers=headers)

        response.raise_for_status()
        data = response.json()

        return [model["id"] for model in data.get("data", []) if model.get("id")]

    async def get_ollama_status(self) -> OllamaStatusResponse:
        """
        Live status of the configured Ollama server: whether it's actually reachable right now,
        which models are locally available (GET /api/tags), and -- the part no other endpoint in
        this service surfaces -- which models are actually loaded into memory right now and how
        much of each sits in VRAM vs. CPU (GET /api/ps). Never raises: a connection failure is
        reported as `reachable=False` with the error text, so the UI can render a clear
        disconnected state instead of a 500.
        """
        base_url = store.llm_settings.get_document()["base_url"]

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                tags_response = await client.get(f"{base_url}/api/tags")
                tags_response.raise_for_status()
                ps_response = await client.get(f"{base_url}/api/ps")
                ps_response.raise_for_status()
        except httpx.HTTPError as error:
            return OllamaStatusResponse(reachable=False, base_url=base_url, error=str(error))

        available = [
            OllamaAvailableModel(
                name=model["name"],
                size_bytes=model.get("size", 0),
                modified_at=model.get("modified_at"),
            )
            for model in tags_response.json().get("models", [])
            if model.get("name")
        ]

        running = []
        for model in ps_response.json().get("models", []):
            if not model.get("name"):
                continue
            size_bytes = model.get("size", 0)
            size_vram_bytes = model.get("size_vram", 0)
            vram_percent = round((size_vram_bytes / size_bytes) * 100, 1) if size_bytes else 0.0
            running.append(
                OllamaRunningModel(
                    name=model["name"],
                    size_bytes=size_bytes,
                    size_vram_bytes=size_vram_bytes,
                    vram_percent=vram_percent,
                    expires_at=model.get("expires_at"),
                )
            )

        return OllamaStatusResponse(
            reachable=True, base_url=base_url, available_models=available, running_models=running
        )

    def _agent_response(self, document: dict, global_settings: LLMSettings, agent_name: str) -> AgentLLMSettingsResponse:
        effective = self._resolve_effective_settings(document, agent_name)
        is_override = any(
            effective[field] != getattr(global_settings, field)
            for field in ("provider", "model", "temperature", "max_tokens", "timeout_seconds")
        )
        raw_override = document.get("agent_overrides", {}).get(agent_name, {})
        return AgentLLMSettingsResponse(
            agent_name=agent_name,
            provider=effective["provider"],
            model=effective["model"],
            temperature=effective["temperature"],
            max_tokens=effective["max_tokens"],
            timeout_seconds=effective["timeout_seconds"],
            is_override=is_override,
            supports_tool_calling_override=raw_override.get("supports_tool_calling"),
        )

    def list_agent_overrides(self) -> list[AgentLLMSettingsResponse]:
        """
        Return every overridable agent's effective settings, and whether each is currently
        using a custom override or just the global default.

        Fetches the settings document exactly once and reuses it for every agent -- computing
        this used to cost 30+ separate MongoDB round-trips (each `store.llm_settings["field"]`
        access independently re-fetches the whole document; 5 agents x ~6 fields + the global
        settings), observed taking 5+ seconds against the real (non-local) MongoDB Atlas cluster
        this app uses. One fetch for all 5 agents combined is the actual fix.
        """
        document = store.llm_settings.get_document()
        global_settings = self._build_settings_response(document)

        return [self._agent_response(document, global_settings, agent_name) for agent_name in OVERRIDABLE_AGENTS]

    def set_agent_override(
        self, agent_name: str, request: AgentLLMOverrideUpdateRequest
    ) -> AgentLLMSettingsResponse:
        """
        Set (merge into) one agent's override. Only fields provided are changed; fields already
        set on a prior override and not mentioned here are left as they were.
        """
        if agent_name not in OVERRIDABLE_AGENTS:
            raise ValueError(
                f"'{agent_name}' has no configurable LLM -- must be one of {OVERRIDABLE_AGENTS}"
            )

        if request.provider is not None and request.provider.lower() not in self.SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported provider '{request.provider}'. Supported providers: {self.SUPPORTED_PROVIDERS}"
            )

        document = store.llm_settings.get_document()
        all_overrides = dict(document.get("agent_overrides", {}))
        current_override = dict(all_overrides.get(agent_name, {}))

        for field in ("provider", "model", "temperature", "max_tokens", "timeout_seconds", "supports_tool_calling"):
            value = getattr(request, field)
            if value is not None:
                current_override[field] = value.lower() if field == "provider" else value

        all_overrides[agent_name] = current_override
        store.llm_settings["agent_overrides"] = all_overrides
        document["agent_overrides"] = all_overrides

        return self._agent_response(document, self._build_settings_response(document), agent_name)

    def clear_agent_override(self, agent_name: str) -> AgentLLMSettingsResponse:
        """
        Remove an agent's override entirely, reverting it to the global default.
        """
        if agent_name not in OVERRIDABLE_AGENTS:
            raise ValueError(
                f"'{agent_name}' has no configurable LLM -- must be one of {OVERRIDABLE_AGENTS}"
            )

        document = store.llm_settings.get_document()
        all_overrides = dict(document.get("agent_overrides", {}))
        all_overrides.pop(agent_name, None)
        store.llm_settings["agent_overrides"] = all_overrides
        document["agent_overrides"] = all_overrides

        return self._agent_response(document, self._build_settings_response(document), agent_name)


llm_provider_service = LLMProviderService()