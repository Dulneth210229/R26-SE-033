"""
Unit tests for artifact_service's new optional `approval_status` override on
save_text_artifact/save_json_artifact/save_binary_artifact/_register_artifact --
added so an agent whose stage requires no human decision at all (UI/UX Agent) can save an
artifact already APPROVED. Confirms the parameter defaults to PENDING (every existing caller's
behavior, unchanged) and that an explicit override is honored and persisted. No LLM/Docker.
"""

import shutil
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id
from app.utils.slugify import slugify


@pytest.fixture
def project_and_feature():
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    project = {"project_id": project_id, "project_name": f"Approval Status Test {project_id}"}
    feature = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Approval Status Feature",
    }
    store.projects[project_id] = project
    store.features[feature_id] = feature

    yield project, feature

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    for artifact_id in [
        a["artifact_id"] for a in store.artifacts.values() if a["feature_id"] == feature_id
    ]:
        store.database["artifacts"].delete_one({"artifact_id": artifact_id})
    root = Path(settings.OUTPUT_DIR) / slugify(project["project_name"])
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)


def test_save_text_artifact_defaults_to_pending(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_text_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_PAGE_HTML,
        artifact_format=ArtifactFormat.HTML,
        filename="test_page_v{version}.html",
        content="<section>hi</section>",
    )

    assert response.approval_status == ApprovalStatus.PENDING


def test_save_text_artifact_honors_explicit_approved(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_text_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_PAGE_HTML,
        artifact_format=ArtifactFormat.HTML,
        filename="test_page_v{version}.html",
        content="<section>hi</section>",
        approval_status=ApprovalStatus.APPROVED,
    )

    assert response.approval_status == ApprovalStatus.APPROVED
    refetched = artifact_service.get_artifact(response.artifact_id)
    assert refetched.approval_status == ApprovalStatus.APPROVED


def test_save_json_artifact_defaults_to_pending(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_json_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_METADATA,
        filename="test_metadata_v{version}.json",
        data={"pages": []},
    )

    assert response.approval_status == ApprovalStatus.PENDING


def test_save_json_artifact_honors_explicit_approved(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_json_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_METADATA,
        filename="test_metadata_v{version}.json",
        data={"pages": []},
        approval_status=ApprovalStatus.APPROVED,
    )

    assert response.approval_status == ApprovalStatus.APPROVED
    refetched = artifact_service.get_artifact(response.artifact_id)
    assert refetched.approval_status == ApprovalStatus.APPROVED


def test_save_binary_artifact_defaults_to_pending(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_binary_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT,
        artifact_format=ArtifactFormat.PNG,
        filename="test_screenshot_v{version}.png",
        binary_content=b"fake-png-bytes",
    )

    assert response.approval_status == ApprovalStatus.PENDING


def test_save_binary_artifact_honors_explicit_approved(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_binary_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT,
        artifact_format=ArtifactFormat.PNG,
        filename="test_screenshot_v{version}.png",
        binary_content=b"fake-png-bytes",
        approval_status=ApprovalStatus.APPROVED,
    )

    assert response.approval_status == ApprovalStatus.APPROVED
    refetched = artifact_service.get_artifact(response.artifact_id)
    assert refetched.approval_status == ApprovalStatus.APPROVED


def test_save_binary_artifact_honors_version_override(project_and_feature):
    """
    Real, confirmed bug this fixes: save_binary_artifact previously had NO version_override
    support at all (unlike the other 3 save methods), so multiple binary artifacts saved within
    one run (e.g. a UI/UX run's several page screenshots) each got their OWN incrementing version
    via this method's own internal get_next_version() call, instead of sharing the run's one
    version like every other artifact type. Confirms two binary artifacts saved with the same
    version_override genuinely share that version, not two different auto-incremented ones.
    """
    project, feature = project_and_feature

    first = artifact_service.save_binary_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT,
        artifact_format=ArtifactFormat.PNG,
        filename="page_one_v7.png",
        binary_content=b"fake-png-bytes-one",
        version_override=7,
    )
    second = artifact_service.save_binary_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.UIUX,
        artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT,
        artifact_format=ArtifactFormat.PNG,
        filename="page_two_v7.png",
        binary_content=b"fake-png-bytes-two",
        version_override=7,
    )

    assert first.version == 7
    assert second.version == 7
    assert first.artifact_id != second.artifact_id


def test_existing_callers_without_approval_status_param_are_unaffected(project_and_feature):
    """Regression guard: a caller that never knew about this new parameter (i.e. every other
    agent in this codebase) must keep getting PENDING, exactly as before."""
    project, feature = project_and_feature

    response = artifact_service.save_json_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.REQUIREMENT,
        artifact_type=ArtifactType.SRS,
        filename="test_srs_v{version}.json",
        data={"feature_name": "x"},
    )

    assert response.approval_status == ApprovalStatus.PENDING
