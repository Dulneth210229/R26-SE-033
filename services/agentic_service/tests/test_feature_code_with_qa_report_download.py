"""
Unit tests for the combined feature-code + QA-report zip download:
workspace_service.export_feature_code_with_extra_files_zip (real git repos via
workspace_service, same fixture convention as test_workspace_undo_merge.py) and
GET /features/{feature_id}/code-with-qa-report/download (real TestClient, a real QA_REPORT
artifact seeded on disk via tmp_path, same convention as test_artifact_download_pdf_route.py).
"""

import io
import json
import os
import shutil
import stat
import zipfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.main import app
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id

client = TestClient(app)


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_id():
    pid = generate_id("project")
    store.projects[pid] = {"project_id": pid, "project_name": f"Zip Download Test {pid}"}

    yield pid

    repo_path = workspace_service.get_repo_path(pid)
    if (repo_path / ".git").exists():
        workspace_service.ensure_project_repo(pid).close()
    store.database["projects"].delete_one({"project_id": pid})
    if repo_path.parent.exists():
        shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def _seed_feature(project_id: str) -> str:
    feature_id = generate_id("feature")
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Zip Download Test Feature",
    }
    return feature_id


def _seed_qa_report_artifact(tmp_path, project_id, feature_id, artifact_format, content, *, version=1):
    artifact_id = generate_id("artifact")
    suffix = "json" if artifact_format == ArtifactFormat.JSON else "md"
    file_path = tmp_path / f"{artifact_id}.{suffix}"
    if artifact_format == ArtifactFormat.JSON:
        file_path.write_text(json.dumps(content), encoding="utf-8")
    else:
        file_path.write_text(content, encoding="utf-8")

    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.QA.value,
        "artifact_type": ArtifactType.QA_REPORT.value,
        "artifact_format": artifact_format.value,
        "approval_status": ApprovalStatus.APPROVED.value,
        "file_path": str(file_path),
        "version": version,
        "created_at": datetime.utcnow(),
    }
    return artifact_id


def test_export_feature_code_with_extra_files_zip_contains_real_code_and_extra_files(project_id):
    feature_id = _seed_feature(project_id)
    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "real_feature_file.ts").write_text("// real generated code", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "add real feature file")

    zip_bytes = workspace_service.export_feature_code_with_extra_files_zip(
        project_id, feature_id,
        extra_files=[("_QA_REPORT/qa_report.json", b'{"tests_generated": 1}'),
                     ("_QA_REPORT/qa_report.md", b"# QA Report")],
    )

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        names = set(archive.namelist())
        assert "lib/real_feature_file.ts" in names
        assert "_QA_REPORT/qa_report.json" in names
        assert "_QA_REPORT/qa_report.md" in names
        assert archive.read("_QA_REPORT/qa_report.json") == b'{"tests_generated": 1}'
        assert archive.read("lib/real_feature_file.ts") == b"// real generated code"

    store.database["features"].delete_one({"feature_id": feature_id})


def test_download_route_bundles_real_code_and_qa_report(tmp_path, project_id):
    feature_id = _seed_feature(project_id)
    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "real_feature_file.ts").write_text("// real generated code", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "add real feature file")

    _seed_qa_report_artifact(tmp_path, project_id, feature_id, ArtifactFormat.JSON, {"tests_generated": 2})
    _seed_qa_report_artifact(tmp_path, project_id, feature_id, ArtifactFormat.MARKDOWN, "# Real QA Report")

    response = client.get(f"/api/v1/features/{feature_id}/code-with-qa-report/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "lib/real_feature_file.ts" in names
        assert "_QA_REPORT/qa_report.json" in names
        assert "_QA_REPORT/qa_report.md" in names
        assert archive.read("_QA_REPORT/qa_report.md") == b"# Real QA Report"

    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


def test_download_route_omits_qa_report_when_none_exists(project_id):
    feature_id = _seed_feature(project_id)
    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "real_feature_file.ts").write_text("// real generated code", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "add real feature file")

    response = client.get(f"/api/v1/features/{feature_id}/code-with-qa-report/download")

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert "lib/real_feature_file.ts" in names
        assert not any(name.startswith("_QA_REPORT/") for name in names)

    store.database["features"].delete_one({"feature_id": feature_id})


def test_download_route_404s_for_unknown_feature():
    response = client.get("/api/v1/features/feature_does_not_exist/code-with-qa-report/download")

    assert response.status_code == 404
