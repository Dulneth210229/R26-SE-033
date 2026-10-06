"""
Unit tests for approval_service.submit_approval's SRS exclusivity rule: approving one SRS
version supersedes (reverts to pending) any OTHER SRS version already approved for the same
feature, so at most one SRS version is ever "approved" at a time. Real Mongo-backed `store`
seeding (established test convention, e.g. test_artifact_active_selection.py), no LLM/graph.
"""

import json

import pytest

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.schemas.approval_schema import ApprovalRequest
from app.services.approval_service import approval_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


def _seed_artifact(
    tmp_path, project_id, feature_id, *, artifact_type, version, approval_status,
    artifact_format=ArtifactFormat.JSON.value, agent_name=AgentName.REQUIREMENT.value,
):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"{artifact_id}.json"
    file_path.write_text(json.dumps({"version": version}), encoding="utf-8")

    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": agent_name,
        "artifact_type": artifact_type,
        "artifact_format": artifact_format,
        "approval_status": approval_status,
        "file_path": str(file_path),
        "version": version,
    }
    return artifact_id


@pytest.fixture
def feature_with_one_approved_srs(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": "Exclusivity Test Project",
        "project_type": "E-commerce",
        "target_stack": "MERN",
    }
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Exclusivity Test Feature",
        "feature_description": "test feature",
    }

    v1_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.SRS.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value,
    )
    v2_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.SRS.value, version=2,
        approval_status=ApprovalStatus.PENDING.value,
    )

    yield {"project_id": project_id, "feature_id": feature_id, "v1_id": v1_id, "v2_id": v2_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["approvals"].delete_many({"feature_id": feature_id})


def test_approving_a_new_srs_version_supersedes_the_previously_approved_one(feature_with_one_approved_srs):
    v1_id = feature_with_one_approved_srs["v1_id"]
    v2_id = feature_with_one_approved_srs["v2_id"]

    approval_service.submit_approval(v2_id, ApprovalRequest(status=ApprovalStatus.APPROVED))

    assert store.artifacts.get(v2_id)["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(v1_id)["approval_status"] == ApprovalStatus.PENDING.value


def test_rejecting_or_requesting_revision_does_not_touch_other_versions(feature_with_one_approved_srs):
    v1_id = feature_with_one_approved_srs["v1_id"]
    v2_id = feature_with_one_approved_srs["v2_id"]

    approval_service.submit_approval(v2_id, ApprovalRequest(status=ApprovalStatus.REJECTED))

    assert store.artifacts.get(v2_id)["approval_status"] == ApprovalStatus.REJECTED.value
    # v1 stays approved -- only an actual APPROVAL of a sibling version supersedes it.
    assert store.artifacts.get(v1_id)["approval_status"] == ApprovalStatus.APPROVED.value


def test_exclusivity_does_not_affect_other_artifact_types(feature_with_one_approved_srs, tmp_path):
    feature_id = feature_with_one_approved_srs["feature_id"]
    project_id = feature_with_one_approved_srs["project_id"]
    v2_id = feature_with_one_approved_srs["v2_id"]

    component_a = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_COMPONENT_CODE.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value,
    )
    component_b = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_COMPONENT_CODE.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value,
    )

    approval_service.submit_approval(v2_id, ApprovalRequest(status=ApprovalStatus.APPROVED))

    # Two independently-approved UI components of the same type must both stay approved -- the
    # SRS exclusivity rule must never bleed into unrelated artifact_types.
    assert store.artifacts.get(component_a)["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(component_b)["approval_status"] == ApprovalStatus.APPROVED.value

    store.database["artifacts"].delete_many({"artifact_id": {"$in": [component_a, component_b]}})


def test_approving_a_new_enhanced_srs_version_supersedes_the_previously_approved_one(tmp_path):
    """
    Enhanced SRS joins the exclusivity rule (previously SRS-only) -- same behavior, different
    artifact_type, needed now that approving it can auto-start Architecture Agent.
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P", "project_type": "E-commerce", "target_stack": "MERN"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F", "feature_description": "d"}

    v1_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.ENHANCED_SRS.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, agent_name=AgentName.DOMAIN.value,
    )
    v2_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.ENHANCED_SRS.value, version=2,
        approval_status=ApprovalStatus.PENDING.value, agent_name=AgentName.DOMAIN.value,
    )

    try:
        approval_service.submit_approval(v2_id, ApprovalRequest(status=ApprovalStatus.APPROVED))

        assert store.artifacts.get(v2_id)["approval_status"] == ApprovalStatus.APPROVED.value
        assert store.artifacts.get(v1_id)["approval_status"] == ApprovalStatus.PENDING.value
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})
        store.database["artifacts"].delete_many({"feature_id": feature_id})
        store.database["approvals"].delete_many({"feature_id": feature_id})


def test_approving_enhanced_srs_never_touches_the_approved_plain_srs(feature_with_one_approved_srs, tmp_path):
    """
    Exclusivity is scoped per artifact_type -- approving an Enhanced SRS must never revert the
    plain SRS the pipeline still needs approved (the two are siblings in the pipeline, not
    versions of the same document).
    """
    feature_id = feature_with_one_approved_srs["feature_id"]
    project_id = feature_with_one_approved_srs["project_id"]
    srs_v1_id = feature_with_one_approved_srs["v1_id"]

    enhanced_v1_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.ENHANCED_SRS.value, version=1,
        approval_status=ApprovalStatus.PENDING.value, agent_name=AgentName.DOMAIN.value,
    )

    approval_service.submit_approval(enhanced_v1_id, ApprovalRequest(status=ApprovalStatus.APPROVED))

    assert store.artifacts.get(enhanced_v1_id)["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(srs_v1_id)["approval_status"] == ApprovalStatus.APPROVED.value

    store.database["artifacts"].delete_one({"artifact_id": enhanced_v1_id})


def test_approval_only_reverts_siblings_of_the_same_format(tmp_path):
    """
    Real, previously-reported gap: without format scoping, approving the JSON half of a version
    pair could revert an unrelated sibling's Markdown row (every gating type saves a JSON+
    Markdown pair sharing one version number). The revert must only ever touch a sibling that
    shares BOTH artifact_type and artifact_format.
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P", "project_type": "E-commerce", "target_stack": "MERN"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F", "feature_description": "d"}

    # v1: JSON approved, Markdown approved (a real version pair, both approved together).
    v1_json_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.SRS.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, artifact_format=ArtifactFormat.JSON.value,
    )
    v1_markdown_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.SRS.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, artifact_format=ArtifactFormat.MARKDOWN.value,
    )
    # v2: only the JSON half is pending (Markdown half not yet generated/approved in this scenario).
    v2_json_id = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.SRS.value, version=2,
        approval_status=ApprovalStatus.PENDING.value, artifact_format=ArtifactFormat.JSON.value,
    )

    try:
        approval_service.submit_approval(v2_json_id, ApprovalRequest(status=ApprovalStatus.APPROVED))

        assert store.artifacts.get(v2_json_id)["approval_status"] == ApprovalStatus.APPROVED.value
        # Only the same-format sibling (v1 JSON) reverts.
        assert store.artifacts.get(v1_json_id)["approval_status"] == ApprovalStatus.PENDING.value
        # The Markdown sibling of a DIFFERENT version is untouched -- it was never in competition
        # with the artifact just approved.
        assert store.artifacts.get(v1_markdown_id)["approval_status"] == ApprovalStatus.APPROVED.value
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})
        store.database["artifacts"].delete_many({"feature_id": feature_id})
        store.database["approvals"].delete_many({"feature_id": feature_id})
