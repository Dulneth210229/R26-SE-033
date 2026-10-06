"""
Unit tests for POST /features/{feature_id}/agents/security/run, GET .../security/chat, and
POST .../security/chat/stream. Real TestClient (established convention, see
test_qa_agent_routes.py, which this chat-test portion mirrors exactly); security_agent.run()/
chat_stream() are mocked -- their own real behavior is covered by test_security_agent.py and the
scanner unit tests. This file only exercises the routes' own wiring: 404 on an unknown feature,
response shapes, error translation, and NDJSON event passthrough.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.agents.security_agent.schemas import SecurityAgentOutput
from app.main import app
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

client = TestClient(app)


@pytest.fixture
def feature_id():
    project_id = generate_id("project")
    fid = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "Security Route Test"}
    store.features[fid] = {
        "feature_id": fid,
        "project_id": project_id,
        "feature_name": "Security Route Test Feature",
    }

    yield fid

    store.database["features"].delete_one({"feature_id": fid})
    store.database["projects"].delete_one({"project_id": project_id})
    store.database["security_conversations"].delete_one({"feature_id": fid})


def test_run_returns_404_for_unknown_feature():
    response = client.post(
        "/api/v1/features/feature_does_not_exist/agents/security/run", json={}
    )
    assert response.status_code == 404


def test_run_returns_agent_run_response_shape(feature_id):
    fake_output = SecurityAgentOutput(
        status="completed",
        gate_decision="review",
        findings_count=3,
        critical_count=0,
        moderate_count=2,
        warning_count=1,
        artifact_ids=["artifact_json", "artifact_md"],
        message="3 finding(s), gate=review.",
    )

    with patch(
        "app.api.routes.agents.security_agent.run", new=AsyncMock(return_value=fake_output)
    ):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/run", json={}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["feature_id"] == feature_id
    assert body["agent_name"] == "security_agent"
    assert body["status"] == "completed"
    assert body["artifact_ids"] == ["artifact_json", "artifact_md"]
    assert "3 finding" in body["message"]


def test_run_accepts_optional_human_comment(feature_id):
    fake_output = SecurityAgentOutput(status="completed", artifact_ids=[], message="0 finding(s), gate=pass.")

    with patch(
        "app.api.routes.agents.security_agent.run", new=AsyncMock(return_value=fake_output)
    ):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/run",
            json={"human_comment": "Re-scan after the fix."},
        )

    assert response.status_code == 200


def test_run_translates_unexpected_exception_to_500(feature_id):
    with patch(
        "app.api.routes.agents.security_agent.run",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/run", json={}
        )

    assert response.status_code == 500
    assert "Security Agent failed" in response.json()["detail"]


def test_scan_with_model_returns_404_for_unknown_feature():
    response = client.post(
        "/api/v1/features/feature_does_not_exist/agents/security/scan-with-model", json={}
    )
    assert response.status_code == 404


def test_scan_with_model_returns_agent_run_response_shape(feature_id):
    fake_output = SecurityAgentOutput(
        status="completed",
        gate_decision="fail",
        findings_count=5,
        critical_count=2,
        moderate_count=2,
        warning_count=1,
        artifact_ids=["artifact_json", "artifact_md"],
        message="5 finding(s), gate=fail.",
        scan_type="ai_model_deep_scan",
    )

    with patch(
        "app.api.routes.agents.security_agent.run_ai_model_scan", new=AsyncMock(return_value=fake_output)
    ):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/scan-with-model", json={}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["feature_id"] == feature_id
    assert body["agent_name"] == "security_agent"
    assert body["status"] == "completed"
    assert body["artifact_ids"] == ["artifact_json", "artifact_md"]
    assert "5 finding" in body["message"]


def test_scan_with_model_translates_unexpected_exception_to_500(feature_id):
    with patch(
        "app.api.routes.agents.security_agent.run_ai_model_scan",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/scan-with-model", json={}
        )

    assert response.status_code == 500
    assert "AI-model scan failed" in response.json()["detail"]


def _fake_agent_stream(events):
    async def _gen(**kwargs):
        for event in events:
            yield event
    return _gen


def test_scan_with_model_stream_returns_404_for_unknown_feature():
    response = client.post(
        "/api/v1/features/feature_does_not_exist/agents/security/scan-with-model/stream", json={}
    )
    assert response.status_code == 404


def test_scan_with_model_stream_yields_ndjson_events(feature_id):
    events = [
        {"type": "phase", "phase": "deterministic", "label": "Running pattern, secret, and dependency scans..."},
        {"type": "phase", "phase": "ai_scan", "label": "Starting AI model scan across 2 batch(es) of real source code..."},
        {"type": "progress", "current": 1, "total": 2, "label": "Scanned batch 1 of 2..."},
        {"type": "progress", "current": 2, "total": 2, "label": "Scanned batch 2 of 2..."},
        {"type": "phase", "phase": "saving", "label": "Saving the security report..."},
        {"type": "done", "artifact_ids": ["a1", "a2"], "message": "1 finding(s), gate=fail.", "gate_decision": "fail", "findings_count": 1},
    ]

    with patch("app.api.routes.agents.security_agent.run_ai_model_scan_stream", new=_fake_agent_stream(events)):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/scan-with-model/stream", json={}
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed == events


def test_scan_with_model_stream_surfaces_error_event_on_unexpected_exception(feature_id):
    async def _raising_gen(**kwargs):
        raise RuntimeError("provider unreachable")
        yield  # pragma: no cover -- makes this a generator

    with patch("app.api.routes.agents.security_agent.run_ai_model_scan_stream", new=_raising_gen):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/scan-with-model/stream", json={}
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1]["type"] == "error"
    assert "Security Agent AI-model scan failed" in parsed[-1]["message"]


def test_scan_with_model_stream_accepts_optional_human_comment(feature_id):
    with patch("app.api.routes.agents.security_agent.run_ai_model_scan_stream", new=_fake_agent_stream([])):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/scan-with-model/stream",
            json={"human_comment": "Re-scan after the fix."},
        )

    assert response.status_code == 200


def test_get_chat_history_returns_404_for_unknown_feature():
    response = client.get("/api/v1/features/feature_does_not_exist/agents/security/chat")
    assert response.status_code == 404


def test_get_chat_history_returns_empty_when_no_conversation_yet(feature_id):
    response = client.get(f"/api/v1/features/{feature_id}/agents/security/chat")

    assert response.status_code == 200
    assert response.json() == {"turns": []}


def test_get_chat_history_returns_persisted_turns(feature_id):
    store.security_conversations[feature_id] = {
        "feature_id": feature_id,
        "turns": [
            {"role": "user", "content": "Why is this Critical?", "created_at": "2026-08-22T00:00:00+00:00"},
            {"role": "assistant", "content": "Because X.", "created_at": "2026-08-22T00:00:01+00:00"},
        ],
    }

    response = client.get(f"/api/v1/features/{feature_id}/agents/security/chat")

    assert response.status_code == 200
    turns = response.json()["turns"]
    assert len(turns) == 2
    assert turns[0]["content"] == "Why is this Critical?"
    assert turns[1]["role"] == "assistant"


def test_chat_stream_returns_404_for_unknown_feature():
    response = client.post(
        "/api/v1/features/feature_does_not_exist/agents/security/chat/stream", json={"message": "hi"}
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

    with patch("app.api.routes.agents.security_agent.chat_stream", new=_fake_chat_stream(events)):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/chat/stream", json={"message": "hi"}
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed == events


def test_chat_stream_surfaces_error_event_on_unexpected_exception(feature_id):
    async def _raising_gen(**kwargs):
        raise RuntimeError("provider unreachable")
        yield  # pragma: no cover -- makes this a generator

    with patch("app.api.routes.agents.security_agent.chat_stream", new=_raising_gen):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/chat/stream", json={"message": "hi"}
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1]["type"] == "error"
    assert "Security chat failed" in parsed[-1]["message"]


def test_edit_chat_turn_stream_returns_404_for_unknown_feature():
    response = client.post(
        "/api/v1/features/feature_does_not_exist/agents/security/chat/turns/1/edit/stream",
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

    with patch("app.api.routes.agents.security_agent.edit_chat_turn_stream", new=_fake_edit_chat_turn_stream):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/chat/turns/2/edit/stream",
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

    with patch("app.api.routes.agents.security_agent.edit_chat_turn_stream", new=_raising_gen):
        response = client.post(
            f"/api/v1/features/{feature_id}/agents/security/chat/turns/1/edit/stream",
            json={"message": "edited"},
        )

    assert response.status_code == 200
    lines = [line for line in response.text.strip().split("\n") if line]
    parsed = [json.loads(line) for line in lines]
    assert parsed[-1]["type"] == "error"
    assert "Failed to edit security chat turn" in parsed[-1]["message"]
