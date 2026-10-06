"""
LLM schemas.

These schemas define the shape of LLM settings API data.

Important:
This file should NOT control the real selected Ollama/OpenAI model.

The real model should come from:

.env
  -> app/core/config.py
  -> app/services/in_memory_store.py
  -> app/services/llm_provider_service.py

This schema file only validates and documents API request/response data.
"""

from pydantic import BaseModel, Field


class LLMSettings(BaseModel):
    """
    Current LLM provider settings returned by the API.

    Do not put real default model values here.
    The actual values must be passed from llm_provider_service.py.
    """

    provider: str = Field(..., example="ollama")
    model: str = Field(..., example="gemma4")
    base_url: str = Field(..., example="http://localhost:11434")

    api_key_reference: str | None = Field(
        default=None,
        example="OPENAI_API_KEY_CONFIGURED"
    )

    temperature: float = Field(..., ge=0.0, le=2.0, example=0.2)
    max_tokens: int = Field(..., ge=1, example=4097)
    streaming_enabled: bool = Field(..., example=True)
    timeout_seconds: int = Field(..., ge=1, example=120)


class LLMSettingsUpdateRequest(BaseModel):
    """
    Request body for updating LLM settings.

    All fields are optional because the user may update only one setting.

    Example:
    {
      "provider": "ollama",
      "model": "gemma4",
      "base_url": "http://localhost:11434"
    }
    """

    provider: str | None = Field(default=None, example="ollama")
    model: str | None = Field(default=None, example="gemma4")
    base_url: str | None = Field(default=None, example="http://localhost:11434")

    api_key: str | None = Field(
        default=None,
        description="Real API key. Do not return this in responses."
    )

    temperature: float | None = Field(default=None, ge=0.0, le=2.0, example=0.3)
    max_tokens: int | None = Field(default=None, ge=1, example=4097)
    streaming_enabled: bool | None = Field(default=None, example=True)
    timeout_seconds: int | None = Field(default=None, ge=1, example=120)


class AgentLLMOverrideUpdateRequest(BaseModel):
    """
    Request body for setting a per-agent LLM override.

    All fields optional -- an unset field means "use the global default for that field."
    Setting every field to null (or DELETE-ing the override) clears the override entirely.
    """

    provider: str | None = Field(default=None, example="ollama")
    model: str | None = Field(default=None, example="qwen3-coder:latest")
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: int | None = Field(default=None, ge=1)
    supports_tool_calling: bool | None = Field(
        default=None,
        description="Human override for whether this agent's current model genuinely supports "
        "real tool-calling (only meaningful for coder_agent today). null (the default) means "
        "'auto-detect' -- see app/services/model_capabilities.py. Only set this explicitly if "
        "the auto-detected result is known to be wrong for your setup.",
    )


class AgentLLMSettingsResponse(BaseModel):
    """
    One agent's effective LLM settings -- either the global default, or a global default with
    one or more fields overridden specifically for this agent.
    """

    agent_name: str = Field(..., example="coder_agent")
    provider: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    is_override: bool = Field(
        ..., description="True if any field above differs from the global default."
    )
    supports_tool_calling_override: bool | None = Field(
        default=None,
        description="The raw human override, if any (null means auto-detect is in effect). See "
        "AgentLLMOverrideUpdateRequest's own field for the full explanation.",
    )


class LLMGenerateRequest(BaseModel):
    """
    Request body used to test the selected LLM provider.
    """

    prompt: str = Field(..., example="Say hello from AutoForge.")

    system_prompt: str | None = Field(
        default=None,
        example="You are a helpful AI assistant."
    )


class LLMGenerateResponse(BaseModel):
    """
    Response returned after testing the LLM provider.
    """

    provider: str
    model: str
    output: str


class OllamaModelsResponse(BaseModel):
    """
    Response for GET /settings/llm/models -- the model names currently available on the
    Ollama server configured in LLMSettings.base_url (i.e. `ollama list`/`GET /api/tags`
    against whatever server the user has live-configured, not a hardcoded default).
    """

    models: list[str] = Field(default_factory=list)


class AnthropicModelsResponse(BaseModel):
    """
    Response for GET /settings/llm/anthropic/models -- the real, current model IDs Anthropic's
    own GET /v1/models reports for this account (never a hardcoded list, same "always live"
    precedent as OllamaModelsResponse). Empty if ANTHROPIC_API_KEY isn't configured -- a missing
    key degrades this to "no Claude models to offer," not an error.
    """

    models: list[str] = Field(default_factory=list)


class OllamaAvailableModel(BaseModel):
    """One locally-pulled model, from `GET /api/tags` -- available to run, but not necessarily
    currently loaded into memory."""

    name: str
    size_bytes: int = Field(..., example=4700000000)
    modified_at: str | None = None


class OllamaRunningModel(BaseModel):
    """One model Ollama currently has loaded into memory, from `GET /api/ps` -- this is what's
    actually resident right now, distinct from what's merely configured or available. `size_vram_bytes`
    vs `size_bytes` is the direct signal for the GPU/VRAM-mismatch class of issue this project has
    hit before (a model too big for the GPU gets mostly offloaded to CPU, silently making every
    call take minutes instead of seconds) -- `vram_percent` makes that ratio explicit for the UI
    without it needing to duplicate the math.
    """

    name: str
    size_bytes: int
    size_vram_bytes: int
    vram_percent: float = Field(..., description="size_vram_bytes / size_bytes * 100, rounded.")
    expires_at: str | None = Field(default=None, description="When Ollama will unload this model if idle.")


class OllamaStatusResponse(BaseModel):
    """
    Live status of the Ollama server configured in LLMSettings.base_url -- distinct from the
    LLMSettings/AgentLLMSettingsResponse endpoints, which only ever reflect what's *configured*,
    never whether that server is actually reachable or what it's actually doing right now.
    """

    reachable: bool
    base_url: str
    error: str | None = Field(default=None, description="Set only when reachable is false.")
    available_models: list[OllamaAvailableModel] = Field(default_factory=list)
    running_models: list[OllamaRunningModel] = Field(default_factory=list)