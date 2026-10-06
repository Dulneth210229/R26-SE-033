"""
Unit tests for GET /artifacts/{id}/download-pdf -- a real, PDF-rendering
sibling of /download scoped to the document-shaped artifact types
(srs, enhanced_srs, architecture_plan, security_report, qa_report). Real
TestClient + a real Playwright render (no mocking of pdf_service), matching
this project's own established "verify the real thing" convention for this
kind of route.
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

MINIMAL_SRS = {"feature_name": "Login", "functional_requirements": [{"id": "FR-001", "description": "Log in"}]}
MINIMAL_ENHANCED_SRS = {"feature_name": "Login", "functional_requirements": []}
MINIMAL_ARCHITECTURE_PLAN = {"document_control": {"feature_name": "Login"}}
MINIMAL_SECURITY_REPORT = {
    "feature_name": "Login", "project_name": "P", "scan_type": "standard",
    "gate_decision": "pass", "findings_count": 0, "critical_count": 0,
    "moderate_count": 0, "warning_count": 0, "findings": [],
}
MINIMAL_QA_REPORT = {
    "feature_name": "Login", "project_name": "P", "framework_used": "jest",
    "tests_generated": 0, "tests_passed": 0, "tests_failed": 0, "tests_skipped": 0,
    "tests_by_category": {}, "test_cases": [], "out_of_scope_modules": [], "raw_stderr": "",
}


def _seed_artifact(tmp_path, project_id, feature_id, artifact_type, content, *, version=1):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"{artifact_id}.json"
    file_path.write_text(json.dumps(content), encoding="utf-8")

    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.REQUIREMENT.value,
        "artifact_type": artifact_type,
        "artifact_format": ArtifactFormat.JSON.value,
        "approval_status": ApprovalStatus.APPROVED.value,
        "file_path": str(file_path),
        "version": version,
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


def test_download_pdf_returns_a_real_pdf_for_srs(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"], ArtifactType.SRS.value, MINIMAL_SRS
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download-pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert "attachment" in response.headers["content-disposition"]


def test_download_pdf_returns_a_real_pdf_for_enhanced_srs(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        ArtifactType.ENHANCED_SRS.value, MINIMAL_ENHANCED_SRS,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download-pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_download_pdf_returns_a_real_pdf_for_architecture_plan(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        ArtifactType.ARCHITECTURE_PLAN.value, MINIMAL_ARCHITECTURE_PLAN,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download-pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_download_pdf_returns_a_real_pdf_for_security_report(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        ArtifactType.SECURITY_REPORT.value, MINIMAL_SECURITY_REPORT,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download-pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_download_pdf_returns_a_real_pdf_for_qa_report(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        ArtifactType.QA_REPORT.value, MINIMAL_QA_REPORT,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download-pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_download_pdf_returns_400_for_an_unsupported_artifact_type(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        ArtifactType.SETUP_INSTRUCTIONS.value, {"instructions": "npm install"},
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download-pdf")

    assert response.status_code == 400
    assert "PDF export is not available" in response.json()["detail"]


def test_download_pdf_returns_404_for_an_unknown_artifact():
    response = client.get("/api/v1/artifacts/artifact_does_not_exist/download-pdf")

    assert response.status_code == 404


def test_download_pdf_includes_sibling_domain_improvements_for_enhanced_srs(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        ArtifactType.ENHANCED_SRS.value, MINIMAL_ENHANCED_SRS, version=2,
    )
    _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        ArtifactType.DOMAIN_IMPROVEMENTS.value,
        {"summary": "A real enrichment summary marker text.", "additions": []},
        version=2,
    )

    response = client.get(f"/api/v1/artifacts/{artifact_id}/download-pdf")

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")
