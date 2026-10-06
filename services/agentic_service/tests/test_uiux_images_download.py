"""
Unit tests for the "download all UI/UX preview images for one version as a zip" feature:
artifact_service.export_artifacts_zip and GET /features/{feature_id}/uiux-images/{version}/download
(real TestClient, real files on disk via tmp_path, same convention as
test_feature_code_with_qa_report_download.py).
"""

import io
import zipfile
from datetime import datetime

from fastapi.testclient import TestClient

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.main import app
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

client = TestClient(app)


def _seed_feature(project_id: str) -> str:
    # _get_owned_feature looks up the feature's PARENT PROJECT for ownership -- a real project
    # record must exist (an ownerless one is treated as accessible by any signed-in user).
    store.projects[project_id] = {"project_id": project_id, "project_name": "UIUX Images Download Test"}
    feature_id = generate_id("feature")
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "UIUX Images Download Test Feature",
    }
    return feature_id


def _seed_screenshot(tmp_path, project_id, feature_id, page_slug, content: bytes, *, version=1):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"feature_{page_slug}_v{version}.png"
    file_path.write_bytes(content)

    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.UIUX.value,
        "artifact_type": ArtifactType.UI_PREVIEW_SCREENSHOT.value,
        "artifact_format": ArtifactFormat.PNG.value,
        "approval_status": ApprovalStatus.PENDING.value,
        "file_path": str(file_path),
        "version": version,
        "created_at": datetime.utcnow(),
    }
    return artifact_id


def test_export_artifacts_zip_bundles_real_files_by_their_own_filename(tmp_path):
    id1 = _seed_screenshot(tmp_path, "proj_x", "feat_x", "home", b"PNGDATA1")
    id2 = _seed_screenshot(tmp_path, "proj_x", "feat_x", "detail", b"PNGDATA2")

    zip_bytes = artifact_service.export_artifacts_zip([id1, id2])

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = set(archive.namelist())
        assert "feature_home_v1.png" in names
        assert "feature_detail_v1.png" in names
        assert archive.read("feature_home_v1.png") == b"PNGDATA1"

    store.database["artifacts"].delete_many({"feature_id": "feat_x"})


def test_export_artifacts_zip_skips_unknown_and_missing_files(tmp_path):
    real_id = _seed_screenshot(tmp_path, "proj_y", "feat_y", "home", b"REALPNG")

    zip_bytes = artifact_service.export_artifacts_zip([real_id, "artifact_does_not_exist"])

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        assert archive.namelist() == ["feature_home_v1.png"]

    store.database["artifacts"].delete_many({"feature_id": "feat_y"})


def test_download_route_bundles_only_the_requested_version(tmp_path):
    project_id = "proj_z"
    feature_id = _seed_feature(project_id)
    v1_id = _seed_screenshot(tmp_path, project_id, feature_id, "home", b"V1PNG", version=1)
    v2_id = _seed_screenshot(tmp_path, project_id, feature_id, "home", b"V2PNG", version=2)

    response = client.get(f"/api/v1/features/{feature_id}/uiux-images/1/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist() == ["feature_home_v1.png"]
        assert archive.read("feature_home_v1.png") == b"V1PNG"

    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["projects"].delete_one({"project_id": project_id})


def test_download_route_404s_when_version_has_no_images(tmp_path):
    project_id = "proj_zz"
    feature_id = _seed_feature(project_id)
    _seed_screenshot(tmp_path, project_id, feature_id, "home", b"V1PNG", version=1)

    response = client.get(f"/api/v1/features/{feature_id}/uiux-images/99/download")

    assert response.status_code == 404

    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["projects"].delete_one({"project_id": project_id})


def test_download_route_404s_for_unknown_feature():
    response = client.get("/api/v1/features/feature_does_not_exist/uiux-images/1/download")

    assert response.status_code == 404
