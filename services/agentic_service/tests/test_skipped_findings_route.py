"""
Unit tests for PUT /artifacts/{artifact_id}/skipped-findings -- the route's own wiring (404 vs
200, request/response shape). artifact_service.set_finding_skipped's actual logic is covered by
test_security_finding_skip.py; real TestClient (established convention, see
test_approval_revoke_route.py).
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.main import app
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

client = TestClient(app)


@pytest.fixture
def security_report_artifact(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    artifact_id = generate_id("artifact")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Skip Route Test"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F"}

    file_path = tmp_path / f"{artifact_id}.json"
    file_path.write_text(json.dumps({"findings": []}), encoding="utf-8")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.SECURITY.value,
        "artifact_type": ArtifactType.SECURITY_REPORT.value,
        "artifact_format": ArtifactFormat.JSON.value,
        "approval_status": ApprovalStatus.PENDING.value,
        "file_path": str(file_path),
        "version": 1,
        "created_at": datetime.utcnow(),
    }

    yield {"project_id": project_id, "feature_id": feature_id, "artifact_id": artifact_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


def test_marking_a_finding_skipped_returns_200_with_the_updated_artifact(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]

    response = client.put(
        f"/api/v1/artifacts/{artifact_id}/skipped-findings",
        json={"finding_id": "SEC-A:1", "skipped": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["artifact_id"] == artifact_id
    assert body["skipped_finding_ids"] == ["SEC-A:1"]


def test_unmarking_a_finding_returns_200_with_it_removed(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]
    client.put(f"/api/v1/artifacts/{artifact_id}/skipped-findings", json={"finding_id": "SEC-A:1", "skipped": True})

    response = client.put(
        f"/api/v1/artifacts/{artifact_id}/skipped-findings",
        json={"finding_id": "SEC-A:1", "skipped": False},
    )

    assert response.status_code == 200
    assert response.json()["skipped_finding_ids"] == []


def test_unknown_artifact_returns_404():
    response = client.put(
        "/api/v1/artifacts/artifact_does_not_exist/skipped-findings",
        json={"finding_id": "SEC-A:1", "skipped": True},
    )

    assert response.status_code == 404


def test_get_artifact_route_reflects_the_skip_state(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]
    client.put(f"/api/v1/artifacts/{artifact_id}/skipped-findings", json={"finding_id": "SEC-A:1", "skipped": True})

    response = client.get(f"/api/v1/artifacts/{artifact_id}")

    assert response.status_code == 200
    assert response.json()["skipped_finding_ids"] == ["SEC-A:1"]
