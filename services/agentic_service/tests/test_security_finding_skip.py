"""
Unit tests for artifact_service.set_finding_skipped -- lets a human mark (or unmark) one security
finding as skipped, accepting the risk instead of fixing it. Stored as a side-channel
skipped_finding_ids field on the artifact record (mirroring approval_status's own in-place
convention), via an atomic Mongo $addToSet/$pull rather than a read-modify-write on the whole
record -- confirmed safe for rapid repeated toggles. Real Mongo-backed `store` seeding, no LLM.
"""

import json
from datetime import datetime

import pytest

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


@pytest.fixture
def security_report_artifact(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    artifact_id = generate_id("artifact")

    store.projects[project_id] = {"project_id": project_id, "project_name": "P"}
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


def test_marking_a_finding_skipped_adds_its_id(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]

    result = artifact_service.set_finding_skipped(artifact_id, "SEC-X:app/a.ts:1", skipped=True)

    assert result.skipped_finding_ids == ["SEC-X:app/a.ts:1"]


def test_unmarking_a_finding_removes_its_id(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]
    artifact_service.set_finding_skipped(artifact_id, "SEC-X:app/a.ts:1", skipped=True)

    result = artifact_service.set_finding_skipped(artifact_id, "SEC-X:app/a.ts:1", skipped=False)

    assert result.skipped_finding_ids == []


def test_marking_the_same_finding_skipped_twice_does_not_duplicate(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]

    artifact_service.set_finding_skipped(artifact_id, "SEC-X:app/a.ts:1", skipped=True)
    result = artifact_service.set_finding_skipped(artifact_id, "SEC-X:app/a.ts:1", skipped=True)

    assert result.skipped_finding_ids == ["SEC-X:app/a.ts:1"]


def test_unmarking_a_finding_that_was_never_skipped_is_a_safe_no_op(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]

    result = artifact_service.set_finding_skipped(artifact_id, "SEC-X:app/a.ts:1", skipped=False)

    assert result.skipped_finding_ids == []


def test_multiple_findings_can_be_skipped_independently(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]

    artifact_service.set_finding_skipped(artifact_id, "SEC-A:1", skipped=True)
    artifact_service.set_finding_skipped(artifact_id, "SEC-B:2", skipped=True)
    result = artifact_service.set_finding_skipped(artifact_id, "SEC-A:1", skipped=False)

    assert result.skipped_finding_ids == ["SEC-B:2"]


def test_unknown_artifact_id_returns_none():
    result = artifact_service.set_finding_skipped("artifact_does_not_exist", "SEC-A:1", skipped=True)

    assert result is None


def test_get_artifact_reflects_the_skip_state(security_report_artifact):
    artifact_id = security_report_artifact["artifact_id"]

    artifact_service.set_finding_skipped(artifact_id, "SEC-A:1", skipped=True)
    result = artifact_service.get_artifact(artifact_id)

    assert result.skipped_finding_ids == ["SEC-A:1"]


def test_a_freshly_created_artifact_has_no_skipped_findings_by_default(security_report_artifact):
    result = artifact_service.get_artifact(security_report_artifact["artifact_id"])

    assert result.skipped_finding_ids == []
