"""
Unit tests for approval_service.submit_approval's Architecture Plan cascade: approving,
rejecting, or requesting revision on the Architecture Plan artifact must apply the exact same
decision to its own other-format sibling (JSON<->Markdown) and all 3 diagram artifacts (use case/
sequence/class, both PUML and PNG formats) of the SAME version -- diagrams no longer have an
independent approval decision at all, per direct user request. Also covers the new cross-version
exclusivity rule for Architecture Plan (mirrors SRS/Enhanced SRS) and its interaction with the
cascade: superseding an old Plan version must also revert that old version's own diagrams.

Real Mongo-backed `store` seeding (established convention, see test_approval_srs_exclusivity.py),
no LLM/graph.
"""

import json

import pytest

from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.schemas.approval_schema import ApprovalRequest
from app.services.approval_service import approval_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


def _seed_artifact(
    tmp_path, project_id, feature_id, *, artifact_type, artifact_format, version, approval_status,
    agent_name=AgentName.ARCHITECTURE.value,
):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"{artifact_id}.dat"
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


def _seed_full_architecture_generation(tmp_path, project_id, feature_id, version, approval_status):
    """Seeds all 8 artifact rows one real Architecture Agent run/revise call produces for a single
    version -- Plan JSON+Markdown, and PUML+PNG for each of the 3 diagram types."""
    ids = {}
    ids["plan_json"] = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.ARCHITECTURE_PLAN.value,
        artifact_format=ArtifactFormat.JSON.value, version=version, approval_status=approval_status,
    )
    ids["plan_markdown"] = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.ARCHITECTURE_PLAN.value,
        artifact_format=ArtifactFormat.MARKDOWN.value, version=version, approval_status=approval_status,
    )
    for diagram_type in (ArtifactType.USE_CASE_DIAGRAM, ArtifactType.SEQUENCE_DIAGRAM, ArtifactType.CLASS_DIAGRAM):
        ids[f"{diagram_type.value}_text"] = _seed_artifact(
            tmp_path, project_id, feature_id, artifact_type=diagram_type.value,
            artifact_format=ArtifactFormat.TEXT.value, version=version, approval_status=ApprovalStatus.PENDING.value,
        )
        ids[f"{diagram_type.value}_png"] = _seed_artifact(
            tmp_path, project_id, feature_id, artifact_type=diagram_type.value,
            artifact_format=ArtifactFormat.PNG.value, version=version, approval_status=ApprovalStatus.PENDING.value,
        )
    return ids


@pytest.fixture
def feature_with_one_architecture_generation(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id, "project_name": "Cascade Test Project",
        "project_type": "E-commerce", "target_stack": "Next.js",
    }
    store.features[feature_id] = {
        "project_id": project_id, "feature_id": feature_id,
        "feature_name": "Cascade Test Feature", "feature_description": "test feature",
    }

    ids = _seed_full_architecture_generation(tmp_path, project_id, feature_id, version=1, approval_status=ApprovalStatus.PENDING.value)

    yield {"project_id": project_id, "feature_id": feature_id, **ids}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["approvals"].delete_many({"feature_id": feature_id})


def test_approving_plan_json_cascades_to_markdown_sibling_and_all_six_diagram_rows(feature_with_one_architecture_generation):
    ids = feature_with_one_architecture_generation

    approval_service.submit_approval(ids["plan_json"], ApprovalRequest(status=ApprovalStatus.APPROVED))

    assert store.artifacts.get(ids["plan_json"])["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(ids["plan_markdown"])["approval_status"] == ApprovalStatus.APPROVED.value
    for diagram_type in ("use_case_diagram", "sequence_diagram", "class_diagram"):
        assert store.artifacts.get(ids[f"{diagram_type}_text"])["approval_status"] == ApprovalStatus.APPROVED.value
        assert store.artifacts.get(ids[f"{diagram_type}_png"])["approval_status"] == ApprovalStatus.APPROVED.value


@pytest.mark.parametrize("status", [ApprovalStatus.REJECTED, ApprovalStatus.REVISION_REQUESTED])
def test_reject_and_revision_requested_cascade_the_same_way(feature_with_one_architecture_generation, status):
    ids = feature_with_one_architecture_generation

    approval_service.submit_approval(ids["plan_json"], ApprovalRequest(status=status))

    assert store.artifacts.get(ids["plan_json"])["approval_status"] == status.value
    assert store.artifacts.get(ids["plan_markdown"])["approval_status"] == status.value
    for diagram_type in ("use_case_diagram", "sequence_diagram", "class_diagram"):
        assert store.artifacts.get(ids[f"{diagram_type}_text"])["approval_status"] == status.value
        assert store.artifacts.get(ids[f"{diagram_type}_png"])["approval_status"] == status.value


def test_cascade_never_touches_a_different_version(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P", "project_type": "E-commerce", "target_stack": "Next.js"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F", "feature_description": "d"}

    try:
        v1 = _seed_full_architecture_generation(tmp_path, project_id, feature_id, version=1, approval_status=ApprovalStatus.PENDING.value)
        v2 = _seed_full_architecture_generation(tmp_path, project_id, feature_id, version=2, approval_status=ApprovalStatus.PENDING.value)

        approval_service.submit_approval(v2["plan_json"], ApprovalRequest(status=ApprovalStatus.APPROVED))

        assert store.artifacts.get(v2["plan_json"])["approval_status"] == ApprovalStatus.APPROVED.value
        assert store.artifacts.get(v2["use_case_diagram_png"])["approval_status"] == ApprovalStatus.APPROVED.value
        # v1's rows (a different version) are completely untouched by v2's cascade.
        assert store.artifacts.get(v1["plan_json"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["plan_markdown"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["use_case_diagram_png"])["approval_status"] == ApprovalStatus.PENDING.value
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})
        store.database["artifacts"].delete_many({"feature_id": feature_id})
        store.database["approvals"].delete_many({"feature_id": feature_id})


def test_cascaded_siblings_get_an_honest_synthetic_approval_record(feature_with_one_architecture_generation):
    ids = feature_with_one_architecture_generation

    approval_service.submit_approval(ids["plan_json"], ApprovalRequest(status=ApprovalStatus.APPROVED, approved_by="human_user"))

    markdown_approvals = [
        a for a in store.approvals.values() if a["artifact_id"] == ids["plan_markdown"]
    ]
    assert len(markdown_approvals) == 1
    assert markdown_approvals[0]["approved_by"] == "system:architecture_plan_cascade"
    assert "not an independent human decision" in markdown_approvals[0]["reviewer_comment"]

    # The plan's OWN approval record is a real, human-attributed one -- the cascade must never
    # overwrite or duplicate it.
    plan_approvals = [a for a in store.approvals.values() if a["artifact_id"] == ids["plan_json"]]
    assert len(plan_approvals) == 1
    assert plan_approvals[0]["approved_by"] == "human_user"


def test_approving_a_new_plan_version_reverts_the_old_version_and_its_diagrams(tmp_path):
    """New cross-version exclusivity rule for ARCHITECTURE_PLAN (mirrors SRS/Enhanced SRS): only
    one Plan version is ever "the approved one". Superseding an old, already-approved-and-cascaded
    version must revert that old version's own diagrams too, or the old plan and its diagrams go
    out of sync."""
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P", "project_type": "E-commerce", "target_stack": "Next.js"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F", "feature_description": "d"}

    try:
        v1 = _seed_full_architecture_generation(tmp_path, project_id, feature_id, version=1, approval_status=ApprovalStatus.PENDING.value)
        # v1 already approved (and cascaded) in an earlier, real approval action.
        approval_service.submit_approval(v1["plan_json"], ApprovalRequest(status=ApprovalStatus.APPROVED))
        assert store.artifacts.get(v1["use_case_diagram_png"])["approval_status"] == ApprovalStatus.APPROVED.value

        v2 = _seed_full_architecture_generation(tmp_path, project_id, feature_id, version=2, approval_status=ApprovalStatus.PENDING.value)
        approval_service.submit_approval(v2["plan_json"], ApprovalRequest(status=ApprovalStatus.APPROVED))

        # v2 (and its diagrams) are now the approved ones.
        assert store.artifacts.get(v2["plan_json"])["approval_status"] == ApprovalStatus.APPROVED.value
        assert store.artifacts.get(v2["use_case_diagram_png"])["approval_status"] == ApprovalStatus.APPROVED.value

        # v1's plan reverted to pending (existing exclusivity rule, now covering ARCHITECTURE_PLAN)
        # AND v1's own diagrams reverted too -- the real risk this test locks in.
        assert store.artifacts.get(v1["plan_json"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["plan_markdown"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["use_case_diagram_png"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["sequence_diagram_text"])["approval_status"] == ApprovalStatus.PENDING.value
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})
        store.database["artifacts"].delete_many({"feature_id": feature_id})
        store.database["approvals"].delete_many({"feature_id": feature_id})


def test_cascade_never_bleeds_into_unrelated_artifact_types(feature_with_one_architecture_generation, tmp_path):
    ids = feature_with_one_architecture_generation
    project_id = ids["project_id"]
    feature_id = ids["feature_id"]

    unrelated = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_COMPONENT_CODE.value,
        artifact_format=ArtifactFormat.CODE.value, version=1, approval_status=ApprovalStatus.PENDING.value,
        agent_name=AgentName.UIUX.value,
    )

    approval_service.submit_approval(ids["plan_json"], ApprovalRequest(status=ApprovalStatus.APPROVED))

    assert store.artifacts.get(unrelated)["approval_status"] == ApprovalStatus.PENDING.value

    store.database["artifacts"].delete_one({"artifact_id": unrelated})
