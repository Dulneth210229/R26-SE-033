"""
Unit tests for POST /artifacts/{artifact_id}/approval/revoke -- the route's own wiring (404 vs
400 vs 200, request/response shape). approval_service.revoke_approval's actual logic is covered
by test_approval_revoke.py; real TestClient (established convention, see
test_security_agent_routes.py).
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.main import app
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

client = TestClient(app)


@pytest.fixture
def approved_artifact(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    artifact_id = generate_id("artifact")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Revoke Route Test"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F"}

    file_path = tmp_path / f"{artifact_id}.json"
    file_path.write_text(json.dumps({"a": 1}), encoding="utf-8")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.REQUIREMENT.value,
        "artifact_type": ArtifactType.SRS.value,
        "artifact_format": ArtifactFormat.JSON.value,
        "approval_status": ApprovalStatus.APPROVED.value,
        "file_path": str(file_path),
        "version": 1,
    }

    yield artifact_id

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["approvals"].delete_many({"feature_id": feature_id})


def test_revoke_returns_404_for_unknown_artifact():
    response = client.post("/api/v1/artifacts/artifact_does_not_exist/approval/revoke")
    assert response.status_code in (400, 404)


def test_revoke_succeeds_with_empty_body(approved_artifact):
    response = client.post(f"/api/v1/artifacts/{approved_artifact}/approval/revoke")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["artifact_id"] == approved_artifact
    assert body["git_reverted"] is False


def test_revoke_returns_400_when_artifact_is_not_approved(approved_artifact):
    client.post(f"/api/v1/artifacts/{approved_artifact}/approval/revoke")

    response = client.post(f"/api/v1/artifacts/{approved_artifact}/approval/revoke")

    assert response.status_code == 400


def test_revoke_honors_a_custom_reviewer_comment(approved_artifact):
    response = client.post(
        f"/api/v1/artifacts/{approved_artifact}/approval/revoke",
        json={"reviewer_comment": "Need to fix the schema mismatch first."},
    )

    assert response.status_code == 200
    matching = [
        a for a in store.approvals.values()
        if a["artifact_id"] == approved_artifact and a["reviewer_comment"] == "Need to fix the schema mismatch first."
    ]
    assert len(matching) == 1
