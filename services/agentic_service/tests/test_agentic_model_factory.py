"""
Unit tests for get_agentic_chat_model (app/providers/agentic_model_factory.py) -- the tool-calling
model factory used by the Coder Agent's ReAct loop and the Architecture/Coder revision planners'
exploration tools. Confirms provider dispatch and the two real bugs found when this path was
first switched to Anthropic (only ever tested against Ollama before): init_chat_model needs an
explicit api_key (it never reads this app's own Settings object, only a real OS env var), and
`temperature` must never be sent to this Anthropic model generation. No real LLM call, no real
`store` (Mongo-backed) singleton touched: both init_chat_model and the module's `store`/`settings`
references are mocked.
"""

from unittest.mock import MagicMock, patch


def _mock_store(agent_overrides=None, **overrides):
    document = {
        "provider": "ollama",
        "model": "llama3:latest",
        "temperature": 0.2,
        "timeout_seconds": 300,
        "agent_overrides": agent_overrides or {},
    }
    document.update(overrides)
    mock = MagicMock()
    mock.llm_settings.get_document.return_value = document
    return mock


def test_ollama_dispatch_includes_num_ctx_and_temperature_but_no_api_key():
    mock_store = _mock_store(agent_overrides={"coder_agent": {"provider": "ollama", "model": "qwen3-coder:latest"}})

    with (
        patch("app.providers.agentic_model_factory.store", mock_store),
        patch("app.providers.agentic_model_factory.init_chat_model") as mock_init,
    ):
        from app.providers.agentic_model_factory import get_agentic_chat_model

        get_agentic_chat_model("coder_agent")

    args, kwargs = mock_init.call_args
    assert args[0] == "ollama:qwen3-coder:latest"
    assert "num_ctx" in kwargs
    assert "temperature" in kwargs
    assert "api_key" not in kwargs


def test_anthropic_dispatch_passes_explicit_api_key():
    """
    Real, confirmed bug: init_chat_model/ChatAnthropic has no visibility into this app's own
    Settings object -- without passing api_key explicitly, a real call fails with "Could not
    resolve authentication method" even though settings.ANTHROPIC_API_KEY is genuinely set.
    """
    mock_store = _mock_store(agent_overrides={"coder_agent": {"provider": "anthropic", "model": "claude-sonnet-5"}})

    with (
        patch("app.providers.agentic_model_factory.store", mock_store),
        patch("app.providers.agentic_model_factory.init_chat_model") as mock_init,
        patch("app.providers.agentic_model_factory.settings") as mock_settings,
    ):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test-key"
        mock_settings.AGENTIC_MODEL_OVERRIDE = "qwen3-coder:latest"
        mock_settings.DEFAULT_LLM_PROVIDER = "ollama"
        mock_settings.LLM_TIMEOUT_SECONDS = 300

        from app.providers.agentic_model_factory import get_agentic_chat_model

        get_agentic_chat_model("coder_agent")

    args, kwargs = mock_init.call_args
    assert args[0] == "anthropic:claude-sonnet-5"
    assert kwargs["api_key"] == "sk-ant-test-key"


def test_anthropic_dispatch_never_sends_temperature():
    """
    Real, confirmed bug: this Anthropic model generation rejects `temperature` outright with a
    400 ("deprecated for this model") -- the identical finding already made and fixed for the
    one-shot AnthropicProvider.
    """
    mock_store = _mock_store(agent_overrides={"coder_agent": {"provider": "anthropic", "model": "claude-sonnet-5"}})

    with (
        patch("app.providers.agentic_model_factory.store", mock_store),
        patch("app.providers.agentic_model_factory.init_chat_model") as mock_init,
        patch("app.providers.agentic_model_factory.settings") as mock_settings,
    ):
        mock_settings.ANTHROPIC_API_KEY = "sk-ant-test-key"
        mock_settings.AGENTIC_MODEL_OVERRIDE = "qwen3-coder:latest"
        mock_settings.DEFAULT_LLM_PROVIDER = "ollama"
        mock_settings.LLM_TIMEOUT_SECONDS = 300

        from app.providers.agentic_model_factory import get_agentic_chat_model

        get_agentic_chat_model("coder_agent")

    _, kwargs = mock_init.call_args
    assert "temperature" not in kwargs
    assert "num_ctx" not in kwargs  # ollama-only, must not leak into an anthropic call


def test_falls_back_to_agentic_model_override_only_for_coder_agent():
    """
    AGENTIC_MODEL_OVERRIDE (.env) is specifically the Coder Agent's own tool-calling-model
    fallback -- it must never leak into another agent's agentic calls just because that agent
    has no override configured yet (e.g. Architecture Agent's own exploration tools).
    """
    mock_store = _mock_store()  # no agent_overrides at all

    with (
        patch("app.providers.agentic_model_factory.store", mock_store),
        patch("app.providers.agentic_model_factory.init_chat_model") as mock_init,
        patch("app.providers.agentic_model_factory.settings") as mock_settings,
    ):
        mock_settings.AGENTIC_MODEL_OVERRIDE = "qwen3-coder:latest"
        mock_settings.DEFAULT_LLM_PROVIDER = "ollama"
        mock_settings.LLM_TIMEOUT_SECONDS = 300
        mock_settings.AGENTIC_OLLAMA_NUM_CTX = 32768

        from app.providers.agentic_model_factory import get_agentic_chat_model

        get_agentic_chat_model("coder_agent")
        coder_model_string = mock_init.call_args[0][0]

        get_agentic_chat_model("architecture_agent")
        architecture_model_string = mock_init.call_args[0][0]

    assert coder_model_string == "ollama:qwen3-coder:latest"
    assert architecture_model_string == "ollama:llama3:latest"  # the shared global default, not qwen3-coder
