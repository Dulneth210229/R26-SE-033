"""
Unit tests for DELETE /features/{feature_id} (app.api.routes.features.delete_feature) -- scoped
cascade delete of one feature's artifacts/approvals/stage_events/requirement_conversation, never
touching sibling features or the project itself. Real Mongo-backed `store` seeding (established
test convention, e.g. test_artifact_active_selection.py), no LLM/Docker.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.main import app
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

client = TestClient(app)


def _seed_artifact(tmp_path, project_id, feature_id, *, version=1):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"{artifact_id}.json"
    file_path.write_text(json.dumps({"version": version}), encoding="utf-8")

    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.REQUIREMENT.value,
        "artifact_type": ArtifactType.SRS.value,
        "artifact_format": ArtifactFormat.JSON.value,
        "approval_status": ApprovalStatus.APPROVED.value,
        "file_path": str(file_path),
        "version": version,
    }
    return artifact_id


@pytest.fixture
def project_with_two_features(tmp_path):
    project_id = generate_id("project")
    keep_feature_id = generate_id("feature")
    delete_feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": "Deletion Test Project",
        "project_type": "E-commerce",
        "target_stack": "MERN",
    }
    store.features[keep_feature_id] = {
        "project_id": project_id,
        "feature_id": keep_feature_id,
        "feature_name": "Keep Me",
        "feature_description": "should survive the other feature's deletion",
    }
    store.features[delete_feature_id] = {
        "project_id": project_id,
        "feature_id": delete_feature_id,
        "feature_name": "Delete Me",
        "feature_description": "should be fully removed",
    }

    keep_artifact_id = _seed_artifact(tmp_path, project_id, keep_feature_id)
    delete_artifact_id = _seed_artifact(tmp_path, project_id, delete_feature_id)

    store.requirement_conversations[delete_feature_id] = {
        "feature_id": delete_feature_id,
        "known_answers": {},
        "srs_preview": {},
        "open_questions": [],
        "assumptions_flagged": [],
        "turn_history": [],
        "status": "gathering",
        "quality_gate": None,
    }

    store.stage_events.collection.insert_one(
        {"event_id": generate_id("event"), "feature_id": delete_feature_id, "agent_name": "requirement_agent",
         "event_type": "run", "comment": None}
    )

    approval_id = generate_id("approval")
    store.approvals.collection.insert_one(
        {"approval_id": approval_id, "artifact_id": delete_artifact_id, "feature_id": delete_feature_id,
         "agent_name": "requirement_agent", "status": "approved", "reviewer_comment": None,
         "approved_by": "human_user", "approved_at": "2026-01-01T00:00:00Z"}
    )

    yield {
        "project_id": project_id,
        "keep_feature_id": keep_feature_id,
        "delete_feature_id": delete_feature_id,
        "keep_artifact_id": keep_artifact_id,
    }

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_many({"project_id": project_id})
    store.database["artifacts"].delete_many({"project_id": project_id})
    store.database["approvals"].delete_many({"feature_id": {"$in": [keep_feature_id, delete_feature_id]}})
    store.database["stage_events"].delete_many({"feature_id": {"$in": [keep_feature_id, delete_feature_id]}})
    store.database["requirement_conversations"].delete_many(
        {"feature_id": {"$in": [keep_feature_id, delete_feature_id]}}
    )


def test_delete_feature_removes_everything_scoped_to_it(project_with_two_features):
    delete_feature_id = project_with_two_features["delete_feature_id"]

    response = client.delete(f"/api/v1/features/{delete_feature_id}")

    assert response.status_code == 204
    assert store.features.get(delete_feature_id) is None
    assert not any(
        a.get("feature_id") == delete_feature_id for a in store.artifacts.values()
    )
    assert store.database["approvals"].count_documents({"feature_id": delete_feature_id}) == 0
    assert store.database["stage_events"].count_documents({"feature_id": delete_feature_id}) == 0
    assert store.requirement_conversations.get(delete_feature_id) is None


def test_delete_feature_never_touches_sibling_features(project_with_two_features):
    keep_feature_id = project_with_two_features["keep_feature_id"]
    delete_feature_id = project_with_two_features["delete_feature_id"]
    keep_artifact_id = project_with_two_features["keep_artifact_id"]

    client.delete(f"/api/v1/features/{delete_feature_id}")

    assert store.features.get(keep_feature_id) is not None
    assert store.artifacts.get(keep_artifact_id) is not None


def test_delete_feature_404s_for_unknown_feature():
    response = client.delete(f"/api/v1/features/{generate_id('feature')}")
    assert response.status_code == 404
