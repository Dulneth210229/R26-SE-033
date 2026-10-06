"""
Model tool-calling capability detection.

Purpose: give the Coder Agent (and any future agentic node) a real, checkable answer to "does
this model actually support real tool-calling," instead of the tribal-knowledge-only state this
project had before -- CLAUDE.md item 74 confirmed `qwen2.5-coder:14b` silently writes a fake
tool-call as plain text instead of populating LangChain's real `tool_calls` field, and nothing in
code caught this before a real, confusing coding-loop failure. This turns that into a real,
checkable fact the Coder Agent consults automatically before choosing which coding path to run
(see agent.py's dispatch in run()/run_stream()/revise()/revise_stream()).

Resolution order, per agent:
1. A human-set override (`agent_overrides[agent].supports_tool_calling`), if present -- an
   explicit escape hatch for the rare case the probe below is wrong, or the model is hosted
   somewhere the probe can't reach.
2. Anthropic/OpenAI: always True -- both provider families reliably support real tool-calling for
   every model this app would plausibly point them at; no probe needed.
3. Ollama: probes the configured server's own `POST /api/show` (returns a real `capabilities`
   array containing "tools" when the model genuinely supports it) -- authoritative, and needs no
   hardcoded, human-maintained model list to keep updating as new models get pulled. Cached per
   (base_url, model) string for the process lifetime -- an Ollama model's own capabilities don't
   change without a human re-pulling a different tag, which already invalidates any earlier
   assumption anyway. An unreachable server or an unparseable response is treated as "no" (route
   to the safer, non-agentic path) rather than an unproven "yes" -- this is deliberately the
   conservative failure direction, matching the original real bug's own cost (a silent, confusing
   coding-loop failure) being worse than a well-scoped but slower non-agentic run.
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.in_memory_store import store

_capability_cache: dict[str, bool] = {}


def _resolve_agent_provider_and_model(agent_name: str) -> tuple[str, str, bool | None]:
    """Mirrors agentic_model_factory.get_agentic_chat_model's own provider/model resolution
    exactly -- this function exists to answer "would THAT function's own model support
    tool-calling," so it must resolve the model the same way that function does."""
    llm_settings = store.llm_settings.get_document()
    override = llm_settings.get("agent_overrides", {}).get(agent_name, {})
    provider = override.get("provider") or llm_settings.get("provider", settings.DEFAULT_LLM_PROVIDER)

    env_fallback = settings.AGENTIC_MODEL_OVERRIDE if agent_name == "coder_agent" else None
    model = override.get("model") or env_fallback or llm_settings.get("model")

    return provider, model, override.get("supports_tool_calling")


async def supports_tool_calling(agent_name: str) -> bool:
    provider, model, override_value = _resolve_agent_provider_and_model(agent_name)

    if override_value is not None:
        return override_value

    if provider != "ollama":
        return True

    base_url = store.llm_settings.get_document()["base_url"]
    cache_key = f"{base_url}::{model}"
    if cache_key in _capability_cache:
        return _capability_cache[cache_key]

    result = await _probe_ollama_capabilities(base_url, model)
    _capability_cache[cache_key] = result
    return result


async def _probe_ollama_capabilities(base_url: str, model: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(f"{base_url}/api/show", json={"model": model})
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return False

    capabilities = data.get("capabilities") or []
    return "tools" in capabilities
