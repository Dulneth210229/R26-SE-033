"""
Unit tests for the new `supports_tool_calling` per-agent override field
(AgentLLMOverrideUpdateRequest/AgentLLMSettingsResponse, llm_provider_service.set_agent_override/
clear_agent_override/_agent_response) -- the human escape hatch model_capabilities.py's own
auto-detection checks first.

Deliberately mocks store.llm_settings entirely (MagicMock, matching test_model_capabilities.py's
own idiom) rather than touching the real one -- store.llm_settings is a live, shared MongoDB
Atlas document real per-agent model configuration lives in; an earlier version of this file called
the real store directly with a naive `agent_overrides = {}` reset in a test fixture, which wiped
the entire real, live agent_overrides document (not just the one field under test) and had to be
restored by hand afterward. Never repeat that -- always mock store for anything that touches
agent_overrides.
"""

from unittest.mock import MagicMock

from app.schemas.llm_schema import AgentLLMOverrideUpdateRequest
from app.services.llm_provider_service import llm_provider_service


def _mock_store_with_document(document):
    mock_store = MagicMock()
    mock_store.llm_settings.get_document.return_value = document
    return mock_store, {}


def _base_document(agent_overrides=None):
    return {
        "provider": "ollama",
        "model": "qwen2.5-coder:14b",
        "base_url": "http://localhost:11434",
        "temperature": 0.3,
        "max_tokens": 4097,
        "streaming_enabled": True,
        "timeout_seconds": 600,
        "agent_overrides": agent_overrides or {},
    }


def test_setting_supports_tool_calling_true_persists_and_is_returned(monkeypatch):
    document = _base_document()
    written = {}

    class _FakeCollectionProxy:
        def get_document(self):
            return document

        def __setitem__(self, key, value):
            written[key] = value

    monkeypatch.setattr("app.services.llm_provider_service.store.llm_settings", _FakeCollectionProxy())

    response = llm_provider_service.set_agent_override(
        "coder_agent", AgentLLMOverrideUpdateRequest(supports_tool_calling=True)
    )

    assert response.supports_tool_calling_override is True
    assert written["agent_overrides"]["coder_agent"]["supports_tool_calling"] is True


def test_setting_supports_tool_calling_false_persists_distinctly_from_unset(monkeypatch):
    document = _base_document()
    written = {}

    class _FakeCollectionProxy:
        def get_document(self):
            return document

        def __setitem__(self, key, value):
            written[key] = value

    monkeypatch.setattr("app.services.llm_provider_service.store.llm_settings", _FakeCollectionProxy())

    response = llm_provider_service.set_agent_override(
        "coder_agent", AgentLLMOverrideUpdateRequest(supports_tool_calling=False)
    )

    # False must round-trip as False, not be treated as "not provided" the way None is.
    assert response.supports_tool_calling_override is False
    assert written["agent_overrides"]["coder_agent"]["supports_tool_calling"] is False


def test_no_override_set_returns_none_meaning_auto_detect(monkeypatch):
    document = _base_document()

    class _FakeCollectionProxy:
        def get_document(self):
            return document

        def __setitem__(self, key, value):
            pass

    monkeypatch.setattr("app.services.llm_provider_service.store.llm_settings", _FakeCollectionProxy())

    response = llm_provider_service.set_agent_override(
        "coder_agent", AgentLLMOverrideUpdateRequest(model="qwen3-coder:latest")
    )

    assert response.supports_tool_calling_override is None


def test_setting_other_fields_does_not_clear_an_existing_supports_tool_calling_override(monkeypatch):
    document = _base_document(agent_overrides={"coder_agent": {"supports_tool_calling": False}})

    class _FakeCollectionProxy:
        def get_document(self):
            return document

        def __setitem__(self, key, value):
            document[key] = value

    monkeypatch.setattr("app.services.llm_provider_service.store.llm_settings", _FakeCollectionProxy())

    response = llm_provider_service.set_agent_override(
        "coder_agent", AgentLLMOverrideUpdateRequest(temperature=0.5)
    )

    assert response.supports_tool_calling_override is False


def test_clear_agent_override_removes_supports_tool_calling_too(monkeypatch):
    document = _base_document(agent_overrides={"coder_agent": {"supports_tool_calling": True}})

    class _FakeCollectionProxy:
        def get_document(self):
            return document

        def __setitem__(self, key, value):
            document[key] = value

    monkeypatch.setattr("app.services.llm_provider_service.store.llm_settings", _FakeCollectionProxy())

    response = llm_provider_service.clear_agent_override("coder_agent")

    assert response.supports_tool_calling_override is None
