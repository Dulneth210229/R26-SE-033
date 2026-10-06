"""
Unit tests for artifact_service.get_selected_or_latest_approved_artifact /
set_active_artifact_selection -- lets a human pin which APPROVED version of an artifact_type
(e.g. SRS) feeds the next pipeline stage, instead of always defaulting to the latest approved
version by version number. Real Mongo-backed `store` seeding (established test convention for
this file's siblings, e.g. test_architecture_project_context.py), no LLM.
"""

import json

import pytest

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


def _seed_srs_artifact(tmp_path, project_id, feature_id, *, version, approval_status):
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
        "approval_status": approval_status,
        "file_path": str(file_path),
        "version": version,
    }
    return artifact_id


@pytest.fixture
def feature_with_two_approved_srs_versions(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": "Selection Test Project",
        "project_type": "E-commerce",
        "target_stack": "MERN",
    }
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Selection Test Feature",
        "feature_description": "test feature",
    }

    v1_id = _seed_srs_artifact(tmp_path, project_id, feature_id, version=1, approval_status=ApprovalStatus.APPROVED.value)
    v2_id = _seed_srs_artifact(tmp_path, project_id, feature_id, version=2, approval_status=ApprovalStatus.APPROVED.value)

    yield {"project_id": project_id, "feature_id": feature_id, "v1_id": v1_id, "v2_id": v2_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


def test_defaults_to_latest_approved_when_no_selection_made(feature_with_two_approved_srs_versions):
    feature_id = feature_with_two_approved_srs_versions["feature_id"]
    v2_id = feature_with_two_approved_srs_versions["v2_id"]

    result = artifact_service.get_selected_or_latest_approved_artifact(
        feature_id, ArtifactType.SRS.value, ArtifactFormat.JSON.value
    )

    assert result["artifact_id"] == v2_id


def test_explicit_selection_overrides_the_latest_version_default(feature_with_two_approved_srs_versions):
    feature_id = feature_with_two_approved_srs_versions["feature_id"]
    v1_id = feature_with_two_approved_srs_versions["v1_id"]

    artifact_service.set_active_artifact_selection(feature_id, ArtifactType.SRS.value, v1_id)

    result = artifact_service.get_selected_or_latest_approved_artifact(
        feature_id, ArtifactType.SRS.value, ArtifactFormat.JSON.value
    )

    assert result["artifact_id"] == v1_id


def test_selecting_a_pending_artifact_is_refused(feature_with_two_approved_srs_versions, tmp_path):
    feature_id = feature_with_two_approved_srs_versions["feature_id"]
    project_id = feature_with_two_approved_srs_versions["project_id"]
    pending_id = _seed_srs_artifact(
        tmp_path, project_id, feature_id, version=3, approval_status=ApprovalStatus.PENDING.value
    )

    with pytest.raises(ValueError, match="approved"):
        artifact_service.set_active_artifact_selection(feature_id, ArtifactType.SRS.value, pending_id)


def test_selecting_an_artifact_from_another_feature_is_refused(feature_with_two_approved_srs_versions, tmp_path):
    feature_id = feature_with_two_approved_srs_versions["feature_id"]
    project_id = feature_with_two_approved_srs_versions["project_id"]
    other_feature_id = generate_id("feature")
    other_artifact_id = _seed_srs_artifact(
        tmp_path, project_id, other_feature_id, version=1, approval_status=ApprovalStatus.APPROVED.value
    )

    with pytest.raises(ValueError, match="does not belong"):
        artifact_service.set_active_artifact_selection(feature_id, ArtifactType.SRS.value, other_artifact_id)

    store.database["artifacts"].delete_one({"artifact_id": other_artifact_id})


def test_stale_selection_falls_back_to_latest_approved(feature_with_two_approved_srs_versions):
    feature_id = feature_with_two_approved_srs_versions["feature_id"]
    v1_id = feature_with_two_approved_srs_versions["v1_id"]
    v2_id = feature_with_two_approved_srs_versions["v2_id"]

    artifact_service.set_active_artifact_selection(feature_id, ArtifactType.SRS.value, v1_id)
    store.database["artifacts"].delete_one({"artifact_id": v1_id})

    result = artifact_service.get_selected_or_latest_approved_artifact(
        feature_id, ArtifactType.SRS.value, ArtifactFormat.JSON.value
    )

    assert result["artifact_id"] == v2_id


def test_architecture_agent_srs_lookup_honors_a_pin(feature_with_two_approved_srs_versions):
    """
    ArchitectureAgent._find_latest_approved_artifact previously duplicated the "latest approved"
    lookup with no pin-awareness at all -- now it just delegates to the same shared helper Domain
    Agent already uses, so a human-pinned SRS version steers Architecture Agent too.
    """
    from app.agents.architecture_agent.agent import ArchitectureAgent

    feature_id = feature_with_two_approved_srs_versions["feature_id"]
    v1_id = feature_with_two_approved_srs_versions["v1_id"]

    artifact_service.set_active_artifact_selection(feature_id, ArtifactType.SRS.value, v1_id)

    result = ArchitectureAgent()._find_latest_approved_artifact(
        feature_id=feature_id, artifact_type=ArtifactType.SRS, artifact_format=ArtifactFormat.JSON
    )

    assert result["artifact_id"] == v1_id


def test_architecture_agent_enhanced_srs_lookup_falls_back_to_latest_when_unset(tmp_path):
    """
    Same lookup, Enhanced SRS specifically, with no pin set -- must fall back to latest approved,
    exactly like the SRS lookup already does (and like it never could before this fix, since
    Enhanced SRS was never wired to the pin-aware helper at all).
    """
    from app.agents.architecture_agent.agent import ArchitectureAgent

    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": "Enhanced Selection Test Project",
        "project_type": "E-commerce",
        "target_stack": "MERN",
    }
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Enhanced Selection Test Feature",
        "feature_description": "test feature",
    }

    v1_id = generate_id("artifact")
    v2_id = generate_id("artifact")
    for artifact_id, version in ((v1_id, 1), (v2_id, 2)):
        file_path = tmp_path / f"{artifact_id}.json"
        file_path.write_text(json.dumps({"version": version}), encoding="utf-8")
        store.artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "project_id": project_id,
            "feature_id": feature_id,
            "agent_name": AgentName.DOMAIN.value,
            "artifact_type": ArtifactType.ENHANCED_SRS.value,
            "artifact_format": ArtifactFormat.JSON.value,
            "approval_status": ApprovalStatus.APPROVED.value,
            "file_path": str(file_path),
            "version": version,
        }

    try:
        result = ArchitectureAgent()._find_latest_approved_artifact(
            feature_id=feature_id,
            artifact_type=ArtifactType.ENHANCED_SRS,
            artifact_format=ArtifactFormat.JSON,
        )

        assert result["artifact_id"] == v2_id
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})
        store.database["artifacts"].delete_many({"feature_id": feature_id})
