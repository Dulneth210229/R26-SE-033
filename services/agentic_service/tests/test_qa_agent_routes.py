"""
Unit tests for POST /features/{feature_id}/agents/qa/run, GET .../qa/chat, and
POST .../qa/chat/stream. Real TestClient (established convention, see
test_security_agent_routes.py); qa_agent.run()/chat_stream() are mocked -- their own real
behavior is covered by test_qa_agent_matching.py/test_qa_generator_fallback.py/
test_qa_jest_parser.py. This file only exercises the routes' own wiring.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agents.qa_agent.schemas import QAAgentOutput
from app.main import app
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

client = TestClient(app)


@pytest.fixture
def feature_id():
    project_id = generate_id("project")
    fid = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "QA Route Test"}
    store.features[fid] = {
        "feature_id": fid,
        "project_id": project_id,
        "feature_name": "QA Route Test Feature",
    }

    yield fid

    store.database["features"].delete_one({"feature_id": fid})
    store.database["projects"].delete_one({"project_id": project_id})
    store.database["qa_conversations"].delete_one({"feature_id": fid})


def test_run_returns_404_for_unknown_feature():
    response = client.post("/api/v1/features/feature_does_not_exist/agents/qa/run", json={})
    assert response.status_code == 404


def test_run_returns_agent_run_response_shape(feature_id):
    fake_output = QAAgentOutput(
        status="completed",
        framework_used="jest",
        tests_generated=3,
        tests_passed=2,
        tests_failed=1,
        artifact_ids=["artifact_json", "artifact_md"],
        message="2 passed, 1 failed.",
    )

    with patch("app.api.routes.agents.qa_agent.run", new=AsyncMock(return_value=fake_output)):
        response = client.post(f"/api/v1/features/{feature_id}/agents/qa/run", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["feature_id"] == feature_id
    assert body["agent_name"] == "qa_agent"
    assert body["status"] == "completed"
    assert body["artifact_ids"] == ["artifact_json", "artifact_md"]
    assert "2 passed" in body["message"]


def test_run_accepts_optional_human_comment(feature_id):
    fake_output = QAAgentOutput(status="completed", artifact_ids=[], message="0 passed, 0 failed.")

    with patch("app.api.routes.agents.qa_agent.run", new=AsyncMock(return_value=fake_output)):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/qa/run",
            json={"human_comment": "Re-run after the Coder Agent's fix."},
        )

    assert response.status_code == 200


def test_run_translates_unexpected_exception_to_500(feature_id):
    with patch(
        "app.api.routes.agents.qa_agent.run",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        response = client.post(f"/api/v1/features/{feature_id}/agents/qa/run", json={})

    assert response.status_code == 500
    assert "QA Agent failed" in response.json()["detail"]


def test_get_chat_history_returns_404_for_unknown_feature():
    response = client.get("/api/v1/features/feature_does_not_exist/agents/qa/chat")
    assert response.status_code == 404


def test_get_chat_history_returns_empty_when_no_conversation_yet(feature_id):
    response = client.get(f"/api/v1/features/{feature_id}/agents/qa/chat")

    assert response.status_code == 200
    assert response.json() == {"turns": []}


def test_get_chat_history_returns_persisted_turns(feature_id):
    store.qa_conversations[feature_id] = {
        "feature_id": feature_id,
        "turns": [
            {"role": "user", "content": "Why did it fail?", "created_at": "2026-08-18T00:00:00+00:00"},
            {"role": "assistant", "content": "Because X.", "created_at": "2026-08-18T00:00:01+00:00"},
        ],
    }

    response = client.get(f"/api/v1/features/{feature_id}/agents/qa/chat")

    assert response.status_code == 200
    turns = response.json()["turns"]
    assert len(turns) == 2
    assert turns[0]["content"] == "Why did it fail?"
    assert turns[1]["role"] == "assistant"


def test_chat_stream_returns_404_for_unknown_feature():
    response = client.post(
        "/api/v1/features/feature_does_not_exist/agents/qa/chat/stream", json={"message": "hi"}
    )
    assert response.status_code == 404


def _fake_chat_stream(events):
    async def _gen(**kwargs):
        for event in events:
            yield event
    return _gen


def test_chat_stream_yields_ndjson_events(feature_id):
    events = [
        {"type": "token", "text": "Hel"},
        {"type": "token", "text": "lo"},
        {"type": "done", "message": "Hello"},
    ]

    with patch("app.api.routes.agents.qa_agent.chat_stream", new=_fake_chat_stream(events)):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/qa/chat/stream", json={"message": "hi"}
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed == events


def test_chat_stream_surfaces_error_event_on_unexpected_exception(feature_id):
    async def _raising_gen(**kwargs):
        raise RuntimeError("provider unreachable")
        yield  # pragma: no cover -- makes this a generator

    with patch("app.api.routes.agents.qa_agent.chat_stream", new=_raising_gen):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/qa/chat/stream", json={"message": "hi"}
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1]["type"] == "error"
    assert "QA chat failed" in parsed[-1]["message"]


def test_edit_chat_turn_stream_returns_404_for_unknown_feature():
    response = client.post(
        "/api/v1/features/feature_does_not_exist/agents/qa/chat/turns/1/edit/stream",
        json={"message": "edited"},
    )
    assert response.status_code == 404


def test_edit_chat_turn_stream_yields_ndjson_events_and_passes_turn_index(feature_id):
    events = [{"type": "token", "text": "edited answer"}, {"type": "done", "message": "edited answer"}]
    captured = {}

    def _fake_edit_chat_turn_stream(**kwargs):
        captured.update(kwargs)

        async def _gen():
            for event in events:
                yield event
        return _gen()

    with patch("app.api.routes.agents.qa_agent.edit_chat_turn_stream", new=_fake_edit_chat_turn_stream):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/qa/chat/turns/2/edit/stream",
            json={"message": "edited question"},
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed == events
    assert captured["turn_index"] == 2
    assert captured["new_message"] == "edited question"
    assert captured["feature_id"] == feature_id


def test_edit_chat_turn_stream_surfaces_error_event_on_unexpected_exception(feature_id):
    async def _raising_gen(**kwargs):
        raise RuntimeError("boom")
        yield  # pragma: no cover -- makes this a generator

    with patch("app.api.routes.agents.qa_agent.edit_chat_turn_stream", new=_raising_gen):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/qa/chat/turns/1/edit/stream",
            json={"message": "edited"},
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1]["type"] == "error"
    assert "Failed to edit QA chat turn" in parsed[-1]["message"]
