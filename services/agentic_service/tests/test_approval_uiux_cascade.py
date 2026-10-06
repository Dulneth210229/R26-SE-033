"""
Unit tests for approval_service.submit_approval's UI/UX screenshot cascade -- restored after this
session's own auto-approval work was reversed per direct user request ("only the user can approve
the generated output"). Approving, rejecting, or requesting revision on a Preview Screenshot must
apply the exact same decision to every other UI/UX artifact of the SAME version: metadata
(JSON+Markdown), integration manifest, every component, every page's HTML -- AND, the new wrinkle
vs. the original item-64 mechanism, every OTHER page's screenshot of that same version too (a
feature with more than one page/UI, now that save_binary_artifact's version_override bug is
fixed and multiple screenshots genuinely share one version). Also covers the cross-version
exclusivity rule for UI_PREVIEW_SCREENSHOT and apply_design_system_patch only firing on approval.

Real Mongo-backed `store` seeding (established convention, see test_approval_architecture_cascade.py),
no LLM/graph. apply_design_system_patch is mocked -- it does real file I/O against a project's
design_system.json, out of scope for this cascade-logic test.
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
    tmp_path, project_id, feature_id, *, artifact_type, artifact_format, version, approval_status,
    agent_name=AgentName.UIUX.value,
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


def _seed_full_uiux_generation(tmp_path, project_id, feature_id, version, approval_status, page_count=1):
    """Seeds a real UI/UX run's artifact rows for one version: metadata JSON+Markdown, integration
    manifest, one component, and `page_count` pages' worth of page-html + screenshot pairs (the
    multi-page case this cascade fix is specifically for)."""
    ids = {}
    ids["metadata_json"] = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_METADATA.value,
        artifact_format=ArtifactFormat.JSON.value, version=version, approval_status=approval_status,
    )
    ids["metadata_markdown"] = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_METADATA.value,
        artifact_format=ArtifactFormat.MARKDOWN.value, version=version, approval_status=approval_status,
    )
    ids["manifest"] = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_INTEGRATION_MANIFEST.value,
        artifact_format=ArtifactFormat.JSON.value, version=version, approval_status=approval_status,
    )
    ids["component"] = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_COMPONENT_CODE.value,
        artifact_format=ArtifactFormat.HTML.value, version=version, approval_status=approval_status,
    )

    ids["screenshots"] = []
    for i in range(page_count):
        ids[f"page_html_{i}"] = _seed_artifact(
            tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_PAGE_HTML.value,
            artifact_format=ArtifactFormat.HTML.value, version=version, approval_status=approval_status,
        )
        screenshot_id = _seed_artifact(
            tmp_path, project_id, feature_id, artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT.value,
            artifact_format=ArtifactFormat.PNG.value, version=version, approval_status=ApprovalStatus.PENDING.value,
        )
        ids[f"screenshot_{i}"] = screenshot_id
        ids["screenshots"].append(screenshot_id)

    return ids


@pytest.fixture
def feature_with_one_uiux_generation(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id, "project_name": "UIUX Cascade Test Project",
        "project_type": "E-commerce", "target_stack": "Next.js",
    }
    store.features[feature_id] = {
        "project_id": project_id, "feature_id": feature_id,
        "feature_name": "UIUX Cascade Test Feature", "feature_description": "test feature",
    }

    ids = _seed_full_uiux_generation(
        tmp_path, project_id, feature_id, version=1, approval_status=ApprovalStatus.PENDING.value, page_count=3
    )

    yield {"project_id": project_id, "feature_id": feature_id, **ids}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    store.database["approvals"].delete_many({"feature_id": feature_id})


def test_approving_one_screenshot_cascades_to_every_sibling_and_every_other_page(feature_with_one_uiux_generation):
    """The core multi-page scenario: 3 pages' screenshots share version 1 -- approving ONE of
    them must approve the metadata/manifest/component AND the other 2 pages' screenshots too."""
    ids = feature_with_one_uiux_generation

    with patch("app.services.approval_service.uiux_agent.apply_design_system_patch"):
        approval_service.submit_approval(ids["screenshot_0"], ApprovalRequest(status=ApprovalStatus.APPROVED))

    assert store.artifacts.get(ids["screenshot_0"])["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(ids["metadata_json"])["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(ids["metadata_markdown"])["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(ids["manifest"])["approval_status"] == ApprovalStatus.APPROVED.value
    assert store.artifacts.get(ids["component"])["approval_status"] == ApprovalStatus.APPROVED.value
    for i in range(3):
        assert store.artifacts.get(ids[f"page_html_{i}"])["approval_status"] == ApprovalStatus.APPROVED.value
        assert store.artifacts.get(ids[f"screenshot_{i}"])["approval_status"] == ApprovalStatus.APPROVED.value


@pytest.mark.parametrize("status", [ApprovalStatus.REJECTED, ApprovalStatus.REVISION_REQUESTED])
def test_reject_and_revision_requested_cascade_the_same_way(feature_with_one_uiux_generation, status):
    ids = feature_with_one_uiux_generation

    approval_service.submit_approval(ids["screenshot_1"], ApprovalRequest(status=status))

    assert store.artifacts.get(ids["screenshot_1"])["approval_status"] == status.value
    assert store.artifacts.get(ids["metadata_json"])["approval_status"] == status.value
    for i in range(3):
        assert store.artifacts.get(ids[f"screenshot_{i}"])["approval_status"] == status.value


def test_cascade_never_touches_a_different_version(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P", "project_type": "E-commerce", "target_stack": "Next.js"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F", "feature_description": "d"}

    try:
        v1 = _seed_full_uiux_generation(tmp_path, project_id, feature_id, version=1, approval_status=ApprovalStatus.PENDING.value, page_count=2)
        v2 = _seed_full_uiux_generation(tmp_path, project_id, feature_id, version=2, approval_status=ApprovalStatus.PENDING.value, page_count=2)

        with patch("app.services.approval_service.uiux_agent.apply_design_system_patch"):
            approval_service.submit_approval(v2["screenshot_0"], ApprovalRequest(status=ApprovalStatus.APPROVED))

        assert store.artifacts.get(v2["screenshot_0"])["approval_status"] == ApprovalStatus.APPROVED.value
        assert store.artifacts.get(v2["screenshot_1"])["approval_status"] == ApprovalStatus.APPROVED.value
        # v1's rows (a different version) are completely untouched by v2's cascade.
        assert store.artifacts.get(v1["metadata_json"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["screenshot_0"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["screenshot_1"])["approval_status"] == ApprovalStatus.PENDING.value
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})
        store.database["artifacts"].delete_many({"feature_id": feature_id})
        store.database["approvals"].delete_many({"feature_id": feature_id})


def test_cascaded_siblings_get_an_honest_synthetic_approval_record(feature_with_one_uiux_generation):
    ids = feature_with_one_uiux_generation

    with patch("app.services.approval_service.uiux_agent.apply_design_system_patch"):
        approval_service.submit_approval(
            ids["screenshot_0"], ApprovalRequest(status=ApprovalStatus.APPROVED, approved_by="human_user")
        )

    manifest_approvals = [a for a in store.approvals.values() if a["artifact_id"] == ids["manifest"]]
    assert len(manifest_approvals) == 1
    assert manifest_approvals[0]["approved_by"] == "system:uiux_screenshot_cascade"
    assert "not an independent human decision" in manifest_approvals[0]["reviewer_comment"]

    other_screenshot_approvals = [a for a in store.approvals.values() if a["artifact_id"] == ids["screenshot_1"]]
    assert len(other_screenshot_approvals) == 1
    assert other_screenshot_approvals[0]["approved_by"] == "system:uiux_screenshot_cascade"

    # The screenshot's OWN approval record is a real, human-attributed one -- the cascade must
    # never overwrite or duplicate it.
    own_approvals = [a for a in store.approvals.values() if a["artifact_id"] == ids["screenshot_0"]]
    assert len(own_approvals) == 1
    assert own_approvals[0]["approved_by"] == "human_user"


def test_approving_a_new_screenshot_version_reverts_the_old_version_and_its_siblings(tmp_path):
    """Cross-version exclusivity rule for UI_PREVIEW_SCREENSHOT (mirrors SRS/Enhanced SRS/
    Architecture Plan): only one version is ever "the approved one". Superseding an old,
    already-approved-and-cascaded version must revert that old version's own siblings too."""
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "P", "project_type": "E-commerce", "target_stack": "Next.js"}
    store.features[feature_id] = {"project_id": project_id, "feature_id": feature_id, "feature_name": "F", "feature_description": "d"}

    try:
        v1 = _seed_full_uiux_generation(tmp_path, project_id, feature_id, version=1, approval_status=ApprovalStatus.PENDING.value, page_count=2)
        with patch("app.services.approval_service.uiux_agent.apply_design_system_patch"):
            approval_service.submit_approval(v1["screenshot_0"], ApprovalRequest(status=ApprovalStatus.APPROVED))
        assert store.artifacts.get(v1["metadata_json"])["approval_status"] == ApprovalStatus.APPROVED.value

        v2 = _seed_full_uiux_generation(tmp_path, project_id, feature_id, version=2, approval_status=ApprovalStatus.PENDING.value, page_count=2)
        with patch("app.services.approval_service.uiux_agent.apply_design_system_patch"):
            approval_service.submit_approval(v2["screenshot_0"], ApprovalRequest(status=ApprovalStatus.APPROVED))

        # v2 (and its siblings) are now the approved ones.
        assert store.artifacts.get(v2["metadata_json"])["approval_status"] == ApprovalStatus.APPROVED.value
        assert store.artifacts.get(v2["screenshot_1"])["approval_status"] == ApprovalStatus.APPROVED.value

        # v1's screenshot reverted to pending (exclusivity rule) AND v1's own siblings reverted
        # too -- the real risk this test locks in.
        assert store.artifacts.get(v1["screenshot_0"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["metadata_json"])["approval_status"] == ApprovalStatus.PENDING.value
        assert store.artifacts.get(v1["screenshot_1"])["approval_status"] == ApprovalStatus.PENDING.value
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})
        store.database["artifacts"].delete_many({"feature_id": feature_id})
        store.database["approvals"].delete_many({"feature_id": feature_id})


def test_cascade_never_bleeds_into_unrelated_artifact_types(feature_with_one_uiux_generation, tmp_path):
    ids = feature_with_one_uiux_generation
    project_id = ids["project_id"]
    feature_id = ids["feature_id"]

    unrelated = _seed_artifact(
        tmp_path, project_id, feature_id, artifact_type=ArtifactType.SRS.value,
        artifact_format=ArtifactFormat.JSON.value, version=1, approval_status=ApprovalStatus.PENDING.value,
        agent_name=AgentName.REQUIREMENT.value,
    )

    with patch("app.services.approval_service.uiux_agent.apply_design_system_patch"):
        approval_service.submit_approval(ids["screenshot_0"], ApprovalRequest(status=ApprovalStatus.APPROVED))

    assert store.artifacts.get(unrelated)["approval_status"] == ApprovalStatus.PENDING.value

    store.database["artifacts"].delete_one({"artifact_id": unrelated})


def test_apply_design_system_patch_fires_only_on_approval_not_reject(feature_with_one_uiux_generation):
    ids = feature_with_one_uiux_generation

    with patch("app.services.approval_service.uiux_agent.apply_design_system_patch") as mock_patch:
        approval_service.submit_approval(ids["screenshot_0"], ApprovalRequest(status=ApprovalStatus.REJECTED))
        mock_patch.assert_not_called()

    with patch("app.services.approval_service.uiux_agent.apply_design_system_patch") as mock_patch:
        approval_service.submit_approval(ids["screenshot_1"], ApprovalRequest(status=ApprovalStatus.APPROVED))
        mock_patch.assert_called_once_with(ids["feature_id"], 1)
