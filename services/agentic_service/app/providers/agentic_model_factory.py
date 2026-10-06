"""
Agentic (tool-calling) model factory.

The existing `llm_provider_service` / `BaseLLMProvider` stack is one-shot only
(generate/stream/invoke_agent) and is kept unchanged for Requirement, Domain,
Architecture, and UI/UX agents -- none of them need tool calling.

Agentic nodes (currently only the Coder Agent's ReAct loop) need a real
tool-calling chat model. `init_chat_model` already dispatches to
langchain-anthropic / langchain-openai / langchain-ollama based on a
"provider:model" string, so it is used directly here rather than hand-writing
per-provider wrappers.

The provider comes from the same shared `store.llm_settings` document the rest
of the app uses, so switching provider in one place still works. The *model*
prefers a per-agent override set through the LLM Settings UI
(`store.llm_settings["agent_overrides"]["coder_agent"]`, same mechanism
`llm_provider_service.get_provider(agent_name=...)` uses for the one-shot
agents), then falls back to `settings.AGENTIC_MODEL_OVERRIDE` (.env) if no
override has ever been set, then the shared `llm_settings["model"]` -- because
the one-shot prose model and the agentic coding model have different quality
tradeoffs and are usually not the same model in practice.
"""

from langchain.chat_models import init_chat_model
from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import settings
from app.services.in_memory_store import store


def get_agentic_chat_model(agent_name: str = "coder_agent") -> BaseChatModel:
    """
    Build the chat model used by agentic (tool-calling) LangGraph nodes.
    """
    # One round-trip for the whole document, not one per field -- each `store.llm_settings["x"]`
    # access independently re-fetches the entire document from MongoDB Atlas (a real, non-local
    # cluster), so reading several fields one at a time here previously cost several round-trips
    # per agentic call (see llm_provider_service.py's get_document() docstring for the full story
    # -- this function had the identical anti-pattern).
    llm_settings = store.llm_settings.get_document()
    override = llm_settings.get("agent_overrides", {}).get(agent_name, {})
    provider = override.get("provider") or llm_settings.get("provider", settings.DEFAULT_LLM_PROVIDER)

    # AGENTIC_MODEL_OVERRIDE (.env) was always specifically "the Coder Agent's tool-calling
    # model" -- it must never leak into another agent's agentic calls (e.g. Architecture
    # Agent's own exploration loops) just because that agent has no override configured yet.
    env_fallback = settings.AGENTIC_MODEL_OVERRIDE if agent_name == "coder_agent" else None
    model = override.get("model") or env_fallback or llm_settings.get("model")

    model_string = f"{provider}:{model}"

    extra_kwargs = {}

    if provider == "ollama":
        # Ollama's server-side default context window (often 2048-4096) is far
        # smaller than this model's actual capability, and is easily blown past
        # by a single tool result containing a real file's contents (e.g.
        # read_ui_component_design returning a whole .html file) -- which silently
        # truncates the conversation and produces degenerate/empty completions
        # rather than an error. Set explicitly, well within the model's real
        # context length, for the agentic path specifically.
        extra_kwargs["num_ctx"] = settings.AGENTIC_OLLAMA_NUM_CTX

    if provider == "anthropic":
        # Two real bugs confirmed via live testing when this path is switched to Anthropic
        # (only ever tested against Ollama until now):
        # 1. init_chat_model/ChatAnthropic has no knowledge of this app's own Settings object --
        #    it only ever resolves credentials from a real ANTHROPIC_API_KEY *OS environment
        #    variable*. A real call without this fails with "Could not resolve authentication
        #    method" even though settings.ANTHROPIC_API_KEY is genuinely set (loaded from .env
        #    into our own pydantic Settings object, which python-dotenv/pydantic-settings
        #    deliberately does NOT also mirror into os.environ). Passed explicitly per-call
        #    instead of exporting to os.environ globally, so this stays scoped to this one model
        #    instance rather than mutating process-wide environment state.
        # 2. `temperature` -- see below, the identical fix already made for the one-shot
        #    AnthropicProvider (app/providers/anthropic_provider.py's own comment has the full
        #    story: this model generation rejects the field outright with a 400, not just
        #    ignores it).
        extra_kwargs["api_key"] = settings.ANTHROPIC_API_KEY

    timeout = override.get("timeout_seconds")
    if timeout is None:
        timeout = llm_settings.get("timeout_seconds", settings.LLM_TIMEOUT_SECONDS)

    chat_model_kwargs: dict = {"timeout": timeout, **extra_kwargs}

    if provider != "anthropic":
        temperature = override.get("temperature")
        if temperature is None:
            temperature = llm_settings.get("temperature", settings.LLM_TEMPERATURE)
        chat_model_kwargs["temperature"] = temperature

    return init_chat_model(model_string, **chat_model_kwargs)
