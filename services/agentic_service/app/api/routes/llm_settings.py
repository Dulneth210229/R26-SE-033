"""
LLM settings routes.

These APIs allow the backend or frontend to:
- view current LLM settings
- update provider/model settings
- test the selected provider

This is important before implementing agents because all agents
will call the same LLM provider service.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
import httpx

from app.schemas.llm_schema import (
    AgentLLMOverrideUpdateRequest,
    AgentLLMSettingsResponse,
    AnthropicModelsResponse,
    LLMSettings,
    LLMSettingsUpdateRequest,
    LLMGenerateRequest,
    LLMGenerateResponse,
    OllamaModelsResponse,
    OllamaStatusResponse,
)
from app.services.llm_provider_service import llm_provider_service

router = APIRouter(prefix="/settings/llm", tags=["LLM Settings"])


@router.get("", response_model=LLMSettings)
def get_llm_settings(current_user: dict = Depends(get_current_user)):
    """
    Return current LLM settings.

    Real API keys are never returned.
    """
    return llm_provider_service.get_settings()


@router.put("", response_model=LLMSettings)
def update_llm_settings(request: LLMSettingsUpdateRequest, current_user: dict = Depends(get_current_user)):
    """
    Update LLM settings.

    Example:
    Switch to Ollama:
    {
      "provider": "ollama",
      "model": "llama3.1",
      "base_url": "http://localhost:11434"
    }

    Example:
    Switch to OpenAI:
    {
      "provider": "openai",
      "model": "gpt-4o-mini",
      "base_url": "https://api.openai.com/v1",
      "api_key": "your_real_key_here"
    }
    """
    try:
        return llm_provider_service.update_settings(request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/models", response_model=OllamaModelsResponse)
async def list_ollama_models(current_user: dict = Depends(get_current_user)):
    """
    List the models currently available on the configured Ollama server (proxies its
    GET /api/tags) -- powers the chat model-picker so it can offer a real, current list instead
    of a free-text field. Only meaningful when provider is "ollama"; a non-Ollama base_url will
    simply fail to connect, surfaced as a 502 below rather than a raw 500.
    """
    try:
        models = await llm_provider_service.list_ollama_models()
        return OllamaModelsResponse(models=models)
    except httpx.HTTPError as error:
        base_url = llm_provider_service.get_settings().base_url
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach Ollama server at {base_url}: {str(error)}",
        )


@router.get("/anthropic/models", response_model=AnthropicModelsResponse)
async def list_anthropic_models(current_user: dict = Depends(get_current_user)):
    """
    List the real, current model IDs available on the configured Anthropic account (proxies its
    own GET /v1/models) -- the Claude-side counterpart to /models above, powering the same chat
    model-picker so it can offer real Claude models alongside real Ollama ones instead of Claude
    only ever appearing by accident (see ModelSelect.jsx's own history). Returns an empty list,
    not an error, when no ANTHROPIC_API_KEY is configured -- "nothing to offer" is a normal,
    renderable state here, not a failure.
    """
    models = await llm_provider_service.list_anthropic_models()
    return AnthropicModelsResponse(models=models)


@router.get("/ollama/status", response_model=OllamaStatusResponse)
async def get_ollama_status(current_user: dict = Depends(get_current_user)):
    """
    Live status of the configured Ollama server -- reachability, locally available models, and
    which models are actually loaded into memory right now (with their VRAM residency), as
    opposed to /settings/llm and /settings/llm/agents which only ever reflect what's configured.
    Never 500s on an unreachable server: `reachable: false` with the error text instead, so the
    UI can render a clear disconnected state.
    """
    return await llm_provider_service.get_ollama_status()


@router.get("/agents", response_model=list[AgentLLMSettingsResponse])
def list_agent_llm_settings(current_user: dict = Depends(get_current_user)):
    """
    Return every configurable agent's effective LLM settings (global default, or a per-agent
    override where one has been set) -- lets the UI show/configure each agent independently,
    not just one shared global config.
    """
    return llm_provider_service.list_agent_overrides()


@router.put("/agents/{agent_name}", response_model=AgentLLMSettingsResponse)
def update_agent_llm_settings(agent_name: str, request: AgentLLMOverrideUpdateRequest, current_user: dict = Depends(get_current_user)):
    """
    Set (merge into) one agent's LLM override. Only fields provided are changed.
    """
    try:
        return llm_provider_service.set_agent_override(agent_name, request)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.delete("/agents/{agent_name}", response_model=AgentLLMSettingsResponse)
def clear_agent_llm_settings(agent_name: str, current_user: dict = Depends(get_current_user)):
    """
    Remove an agent's override entirely, reverting it to the global default.
    """
    try:
        return llm_provider_service.clear_agent_override(agent_name)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/test", response_model=LLMGenerateResponse)
async def test_llm_provider(request: LLMGenerateRequest, current_user: dict = Depends(get_current_user)):
    """
    Test the currently selected LLM provider.

    This is useful before running agents.
    """
    try:
        provider = llm_provider_service.get_provider()

        output = await provider.generate(
            prompt=request.prompt,
            system_prompt=request.system_prompt
        )

        settings = llm_provider_service.get_settings()

        return LLMGenerateResponse(
            provider=settings.provider,
            model=settings.model,
            output=output
        )

    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"LLM provider test failed: {str(error)}"
        )


@router.post("/agents/{agent_name}/test", response_model=LLMGenerateResponse)
async def test_agent_llm_provider(agent_name: str, request: LLMGenerateRequest, current_user: dict = Depends(get_current_user)):
    """
    Test one agent's effective LLM settings (its override if it has one, otherwise the global
    default) -- distinct from /test, which always tests the global default regardless of any
    per-agent override.
    """
    try:
        provider = llm_provider_service.get_provider(agent_name=agent_name)

        output = await provider.generate(
            prompt=request.prompt,
            system_prompt=request.system_prompt
        )

        effective = next(
            (a for a in llm_provider_service.list_agent_overrides() if a.agent_name == agent_name),
            None,
        )

        if effective is None:
            raise HTTPException(status_code=400, detail=f"Unknown agent '{agent_name}'.")

        return LLMGenerateResponse(provider=effective.provider, model=effective.model, output=output)

    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"LLM provider test failed: {str(error)}"
        )