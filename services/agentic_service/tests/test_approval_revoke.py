"""
Unit tests for approval_service.revoke_approval -- the one status transition submit_approval
never exposes (approved -> pending). Real Mongo-backed `store` seeding (established convention,
see test_approval_srs_exclusivity.py), workspace_service.undo_merge_feature_branch mocked here
(its own real-git behavior is covered by test_workspace_undo_merge.py) so these tests focus on
the approval-status/cascade logic in isolation.
"""

import json
from unittest.mock import patch

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
def feature(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P", "project_type": "E-commerce", "target_stack": "MERN"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F", "feature_description": "d"}

    yield {"project_id": project_id, "feature_id": feature_id, "tmp_path": tmp_path}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["approvals"].delete_many({"feature_id": feature_id})


def test_revoke_moves_an_approved_artifact_back_to_pending(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
    )

    response = approval_service.revoke_approval(artifact_id)

    assert store.artifacts.get(artifact_id)["approval_status"] == ApprovalStatus.PENDING.value
    assert response.status == ApprovalStatus.PENDING
    assert response.reverted_artifact_ids == [artifact_id]
    assert response.git_reverted is False

    # A real, honest approval record was written for the revoke itself.
    revoke_records = [a for a in store.approvals.values() if a["artifact_id"] == artifact_id]
    assert any(r["status"] == ApprovalStatus.PENDING.value for r in revoke_records)


def test_revoke_raises_for_an_artifact_that_isnt_approved(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=1, approval_status=ApprovalStatus.PENDING.value,
    )

    with pytest.raises(ValueError, match="Only an approved artifact"):
        approval_service.revoke_approval(artifact_id)


def test_revoke_raises_for_an_unknown_artifact():
    with pytest.raises(ValueError, match="not found"):
        approval_service.revoke_approval("artifact_does_not_exist")


def test_revoke_reverts_the_whole_json_markdown_version_pair_together(feature):
    json_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
        artifact_format=ArtifactFormat.JSON.value,
    )
    markdown_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
        artifact_format=ArtifactFormat.MARKDOWN.value,
    )

    response = approval_service.revoke_approval(json_id)

    assert store.artifacts.get(json_id)["approval_status"] == ApprovalStatus.PENDING.value
    assert store.artifacts.get(markdown_id)["approval_status"] == ApprovalStatus.PENDING.value
    assert set(response.reverted_artifact_ids) == {json_id, markdown_id}


def test_revoke_never_touches_a_different_versions_sibling(feature):
    v1_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
    )
    v2_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=2, approval_status=ApprovalStatus.PENDING.value,
    )

    approval_service.revoke_approval(v1_id)

    assert store.artifacts.get(v2_id)["approval_status"] == ApprovalStatus.PENDING.value  # untouched, was already pending


def test_revoke_cascades_architecture_plan_to_its_diagrams(feature):
    plan_json_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, artifact_format=ArtifactFormat.JSON.value,
        agent_name=AgentName.ARCHITECTURE.value,
    )
    plan_md_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, artifact_format=ArtifactFormat.MARKDOWN.value,
        agent_name=AgentName.ARCHITECTURE.value,
    )
    usecase_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.USE_CASE_DIAGRAM.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, agent_name=AgentName.ARCHITECTURE.value,
    )

    response = approval_service.revoke_approval(plan_json_id)

    assert store.artifacts.get(plan_json_id)["approval_status"] == ApprovalStatus.PENDING.value
    assert store.artifacts.get(plan_md_id)["approval_status"] == ApprovalStatus.PENDING.value
    assert store.artifacts.get(usecase_id)["approval_status"] == ApprovalStatus.PENDING.value
    # Each real sibling reverted exactly once (no double-revert from both the generic same-type
    # loop and the dedicated cascade running on the same artifact).
    assert response.reverted_artifact_ids.count(plan_md_id) == 1
    assert response.reverted_artifact_ids.count(usecase_id) == 1


def test_revoke_a_code_diff_artifact_calls_undo_merge_and_reports_it(feature):
    code_diff_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.CODE_DIFF.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, agent_name=AgentName.CODER.value,
    )

    with patch(
        "app.services.approval_service.workspace_service.undo_merge_feature_branch",
        return_value="feature/login-and-signup",
    ) as mock_undo:
        response = approval_service.revoke_approval(code_diff_id)

    mock_undo.assert_called_once_with(feature["project_id"], feature["feature_id"])
    assert response.git_reverted is True
    assert response.restored_branch == "feature/login-and-signup"


def test_revoke_a_code_diff_artifact_with_no_real_merge_found_is_a_safe_no_op(feature):
    code_diff_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.CODE_DIFF.value, version=1,
        approval_status=ApprovalStatus.APPROVED.value, agent_name=AgentName.CODER.value,
    )

    with patch(
        "app.services.approval_service.workspace_service.undo_merge_feature_branch", return_value=None,
    ):
        response = approval_service.revoke_approval(code_diff_id)

    assert response.git_reverted is False
    assert response.restored_branch is None
    assert store.artifacts.get(code_diff_id)["approval_status"] == ApprovalStatus.PENDING.value


def test_revoke_never_attempts_git_undo_for_a_non_coder_artifact(feature):
    artifact_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
    )

    with patch("app.services.approval_service.workspace_service.undo_merge_feature_branch") as mock_undo:
        approval_service.revoke_approval(artifact_id)

    mock_undo.assert_not_called()


# Direct user request: once the pipeline has moved on to the next agent, revoking an approval on
# Requirement/Domain/Architecture becomes permanently impossible, even navigating back later.
# Deliberately narrow -- only these 3 transitions; Coder/UI-UX revoke keeps its existing, more
# permissive behavior (covered by the git-undo tests above, which use types with no entry in
# _NEXT_STAGE_GATING_TYPE and so are never subject to this new check at all).


def test_revoke_srs_is_blocked_once_enhanced_srs_exists(feature):
    srs_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=2, approval_status=ApprovalStatus.APPROVED.value,
    )
    _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.ENHANCED_SRS.value, version=1, approval_status=ApprovalStatus.PENDING.value,
        agent_name=AgentName.DOMAIN.value,
    )

    with pytest.raises(ValueError, match="already moved on"):
        approval_service.revoke_approval(srs_id)

    # Refused before any mutation -- the approval must still be intact.
    assert store.artifacts.get(srs_id)["approval_status"] == ApprovalStatus.APPROVED.value


def test_revoke_srs_still_allowed_when_domain_hasnt_started(feature):
    srs_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.SRS.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
    )

    approval_service.revoke_approval(srs_id)

    assert store.artifacts.get(srs_id)["approval_status"] == ApprovalStatus.PENDING.value


def test_revoke_enhanced_srs_is_blocked_once_architecture_plan_exists(feature):
    enhanced_srs_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.ENHANCED_SRS.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
        agent_name=AgentName.DOMAIN.value,
    )
    _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value, version=1, approval_status=ApprovalStatus.PENDING.value,
        agent_name=AgentName.ARCHITECTURE.value,
    )

    with pytest.raises(ValueError, match="already moved on"):
        approval_service.revoke_approval(enhanced_srs_id)


def test_revoke_architecture_plan_is_blocked_once_uiux_screenshot_exists(feature):
    plan_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
        agent_name=AgentName.ARCHITECTURE.value,
    )
    _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT.value, version=1, approval_status=ApprovalStatus.PENDING.value,
        artifact_format=ArtifactFormat.PNG.value, agent_name=AgentName.UIUX.value,
    )

    with pytest.raises(ValueError, match="already moved on"):
        approval_service.revoke_approval(plan_id)


def test_revoke_uiux_screenshot_is_unaffected_even_if_coder_has_started(feature):
    # UI_PREVIEW_SCREENSHOT has no entry in _NEXT_STAGE_GATING_TYPE -- this new lock is scoped to
    # Requirement/Domain/Architecture only, per the user's own explicit wording.
    screenshot_id = _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT.value, version=1, approval_status=ApprovalStatus.APPROVED.value,
        artifact_format=ArtifactFormat.PNG.value, agent_name=AgentName.UIUX.value,
    )
    _seed_artifact(
        feature["tmp_path"], feature["project_id"], feature["feature_id"],
        artifact_type=ArtifactType.CODE_DIFF.value, version=1, approval_status=ApprovalStatus.PENDING.value,
        artifact_format=ArtifactFormat.MARKDOWN.value, agent_name=AgentName.CODER.value,
    )

    approval_service.revoke_approval(screenshot_id)

    assert store.artifacts.get(screenshot_id)["approval_status"] == ApprovalStatus.PENDING.value
