"""
Real QA Agent chat -- mirrors test_security_agent.py's own TestSecurityChat exactly (no dedicated
agent-level test file existed for QA's own chat before; the streaming loop itself is only
meaningfully verified live against a real provider, these tests cover the deterministic, non-LLM
pieces: turn persistence and the new turn_index/edit_chat_turn_stream mechanism).
"""

from unittest.mock import patch

import pytest

from app.agents.qa_agent.agent import QAAgent
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


@pytest.fixture
def feature_id():
    fid = generate_id("feature")
    yield fid
    store.database["qa_conversations"].delete_one({"feature_id": fid})


@pytest.mark.asyncio
async def test_chat_stream_yields_tokens_then_done_and_persists_the_turn(feature_id):
    agent = QAAgent()

    async def _fake_stream(prompt, system_prompt=None):
        yield "Real "
        yield "answer."

    fake_provider = type("FakeProvider", (), {"stream": staticmethod(_fake_stream)})()

    with (
        patch.object(agent, "_load_latest_qa_report", return_value=None),
        patch(
            "app.services.llm_provider_service.llm_provider_service.get_provider",
            return_value=fake_provider,
        ),
    ):
        events = [event async for event in agent.chat_stream(feature_id=feature_id, message="hi")]

    assert events[0] == {"type": "token", "text": "Real "}
    assert events[1] == {"type": "token", "text": "answer."}
    assert events[-1] == {"type": "done", "message": "Real answer."}

    history = agent._get_chat_history(feature_id)
    assert len(history) == 2
    assert history[0] == {
        "role": "user", "content": "hi", "created_at": history[0]["created_at"], "turn_index": 1,
    }
    assert history[1]["content"] == "Real answer."
    assert history[1]["turn_index"] == 1


@pytest.mark.asyncio
async def test_chat_stream_yields_error_event_and_persists_nothing_when_provider_unreachable(feature_id):
    agent = QAAgent()

    with (
        patch.object(agent, "_load_latest_qa_report", return_value=None),
        patch(
            "app.services.llm_provider_service.llm_provider_service.get_provider",
            side_effect=RuntimeError("no provider configured"),
        ),
    ):
        events = [event async for event in agent.chat_stream(feature_id=feature_id, message="hi")]

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert agent._get_chat_history(feature_id) == []


@pytest.mark.asyncio
async def test_edit_chat_turn_stream_truncates_and_regenerates_from_the_edited_turn(feature_id):
    """Direct user request: editing turn N discards it and everything after, then continues as a
    fresh exchange -- mirrors security_agent's own identical mechanism."""
    agent = QAAgent()

    async def _fake_stream_1(prompt, system_prompt=None):
        yield "first answer"

    async def _fake_stream_2(prompt, system_prompt=None):
        yield "second answer"

    async def _fake_stream_3(prompt, system_prompt=None):
        yield "edited answer"

    with patch.object(agent, "_load_latest_qa_report", return_value=None):
        for fake_stream in (_fake_stream_1, _fake_stream_2):
            fake_provider = type("FakeProvider", (), {"stream": staticmethod(fake_stream)})()
            with patch(
                "app.services.llm_provider_service.llm_provider_service.get_provider",
                return_value=fake_provider,
            ):
                async for _ in agent.chat_stream(feature_id=feature_id, message="q"):
                    pass

        history_before_edit = agent._get_chat_history(feature_id)
        assert len(history_before_edit) == 4

        fake_provider = type("FakeProvider", (), {"stream": staticmethod(_fake_stream_3)})()
        with patch(
            "app.services.llm_provider_service.llm_provider_service.get_provider",
            return_value=fake_provider,
        ):
            events = [
                event async for event in
                agent.edit_chat_turn_stream(feature_id=feature_id, turn_index=1, new_message="edited q")
            ]

    assert events[-1] == {"type": "done", "message": "edited answer"}
    history_after_edit = agent._get_chat_history(feature_id)
    assert len(history_after_edit) == 2
    assert history_after_edit[0]["content"] == "edited q"
    assert history_after_edit[1]["content"] == "edited answer"
    assert history_after_edit[0]["turn_index"] == 1
    assert history_after_edit[1]["turn_index"] == 1


@pytest.mark.asyncio
async def test_edit_chat_turn_stream_yields_an_error_for_an_unknown_turn_index(feature_id):
    agent = QAAgent()

    events = [
        event async for event in
        agent.edit_chat_turn_stream(feature_id=feature_id, turn_index=99, new_message="edited q")
    ]

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "99" in events[0]["message"]
    assert agent._get_chat_history(feature_id) == []
