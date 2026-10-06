"""
Unit tests for GET /artifacts/{id}/content and GET /artifacts/{id}/download when the artifact's
own record exists (in Mongo) but its referenced file is missing on disk -- a real, live-found bug:
a shared Mongo Atlas record whose local outputs/ file was never present in (or was removed from)
a given checkout used to crash with an unhandled 500 (read_artifact_content's raw
open(file_path, ...) raising FileNotFoundError uncaught), which the browser reported as a bare
"Network Error" with no message at all (an unhandled exception skips the exception-handling
pipeline that normally re-applies CORSMiddleware's headers). Real TestClient (established
convention, see test_security_agent_routes.py).
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


def _seed_artifact(tmp_path, project_id, feature_id, *, file_exists, artifact_format=ArtifactFormat.JSON.value):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"{artifact_id}.{ 'png' if artifact_format == ArtifactFormat.PNG.value else 'json' }"
    if file_exists:
        if artifact_format == ArtifactFormat.PNG.value:
            file_path.write_bytes(b"\x89PNG\r\n\x1a\n fake png bytes")
        else:
            file_path.write_text(json.dumps({"a": 1}), encoding="utf-8")

    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.REQUIREMENT.value,
        "artifact_type": ArtifactType.SRS.value,
        "artifact_format": artifact_format,
        "approval_status": ApprovalStatus.APPROVED.value,
        "file_path": str(file_path),
        "version": 1,
        "created_at": datetime.utcnow(),
    }
    return artifact_id


@pytest.fixture
def feature(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F"}

    yield {"project_id": project_id, "feature_id": feature_id, "tmp_path": tmp_path}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


def test_content_returns_404_with_a_clear_message_when_the_file_is_missing(feature):
    artifact_id = _seed_artifact(feature["tmp_path"], feature["project_id"], feature["feature_id"], file_exists=False)

    response = client.get(f"/api/v1/artifacts/{artifact_id}/content")

    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "could not be found on disk" in detail


def test_content_still_works_normally_when_the_file_is_present(feature):
    artifact_id = _seed_artifact(feature["tmp_path"], feature["project_id"], feature["feature_id"], file_exists=True)

    response = client.get(f"/api/v1/artifacts/{artifact_id}/content")

    assert response.status_code == 200
    body = response.json()
    assert body["content_json"] == {"a": 1}


def test_content_returns_404_for_a_missing_png_file(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        file_exists=False, artifact_format=ArtifactFormat.PNG.value,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/content")

    assert response.status_code == 404
    assert "could not be found on disk" in response.json()["detail"]


def test_download_returns_404_with_a_clear_message_when_the_file_is_missing(feature):
    artifact_id = _seed_artifact(feature["tmp_path"], feature["project_id"], feature["feature_id"], file_exists=False)

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")

    assert response.status_code == 404
    assert "could not be found on disk" in response.json()["detail"]


def test_download_still_works_normally_when_the_file_is_present(feature):
    artifact_id = _seed_artifact(feature["tmp_path"], feature["project_id"], feature["feature_id"], file_exists=True)

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download")

    assert response.status_code == 200
