"""
Unit tests for Milestone 2 of the Architecture Agent upgrade: project-aware
generation context. Covers the first project-scoped artifact query
(artifact_service.list_project_artifacts), the agent's previous-plans loader,
and the user-prompt sections that render them. Real Mongo-backed `store`
seeding (established test convention), no LLM.
"""

import json

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.prompt import (
    build_architecture_user_prompt,
    summarize_previous_architecture_plans,
)
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

PREVIOUS_PLAN = {
    "document_control": {"feature_name": "Login"},
    "design_views": {
        "interface_view": {
            "api_endpoints": [{"endpoint": "/api/auth/login", "method": "POST"}],
        },
        "data_view": {
            "data_entities": [{"name": "UserCredentials"}],
        },
    },
    "implementation_plan": {
        "backend": {"files": [{"path": "server/src/routes/auth.routes.js"}]},
        "frontend": {"pages": [{"path": "client/src/pages/LoginPage.jsx"}]},
        "implementation_order": ["step"],
        "constraints": ["c"],
    },
}


def _seed_artifact(tmp_path, project_id, feature_id, *, artifact_type, approval_status, version=1, data=None):
    artifact_id = generate_id("artifact")
    file_path = tmp_path / f"{artifact_id}.json"
    file_path.write_text(json.dumps(data or PREVIOUS_PLAN), encoding="utf-8")

    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.ARCHITECTURE.value,
        "artifact_type": artifact_type,
        "artifact_format": ArtifactFormat.JSON.value,
        "approval_status": approval_status,
        "file_path": str(file_path),
        "version": version,
    }
    return artifact_id


@pytest.fixture
def project_with_previous_feature(tmp_path):
    project_id = generate_id("project")
    previous_feature_id = generate_id("feature")
    current_feature_id = generate_id("feature")

    store.features[previous_feature_id] = {
        "project_id": project_id,
        "feature_id": previous_feature_id,
        "feature_name": "Login",
    }

    _seed_artifact(
        tmp_path, project_id, previous_feature_id,
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value,
        approval_status=ApprovalStatus.APPROVED.value,
    )
    # A newer but UNAPPROVED version must not shadow the approved one,
    # and the current feature's own plan must be excluded.
    _seed_artifact(
        tmp_path, project_id, previous_feature_id,
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value,
        approval_status=ApprovalStatus.PENDING.value,
        version=2,
    )
    _seed_artifact(
        tmp_path, project_id, current_feature_id,
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value,
        approval_status=ApprovalStatus.APPROVED.value,
    )
    # An artifact from a DIFFERENT project must never leak in.
    _seed_artifact(
        tmp_path, generate_id("project"), generate_id("feature"),
        artifact_type=ArtifactType.ARCHITECTURE_PLAN.value,
        approval_status=ApprovalStatus.APPROVED.value,
    )

    yield {"project_id": project_id, "previous_feature_id": previous_feature_id,
           "current_feature_id": current_feature_id}

    store.database["features"].delete_one({"feature_id": previous_feature_id})
    for artifact_id, artifact in list(store.artifacts.items()):
        if artifact.get("file_path", "").startswith(str(tmp_path)):
            store.database["artifacts"].delete_one({"artifact_id": artifact_id})


def test_list_project_artifacts_filters_by_project_and_status(project_with_previous_feature, tmp_path):
    project_id = project_with_previous_feature["project_id"]

    results = artifact_service.list_project_artifacts(
        project_id=project_id,
        agent_name=AgentName.ARCHITECTURE,
        artifact_type=ArtifactType.ARCHITECTURE_PLAN,
        approval_status=ApprovalStatus.APPROVED,
    )

    assert len(results) == 2  # previous feature v1 + current feature v1; other project excluded
    assert all(item["project_id"] == project_id for item in results)
    assert all(item["approval_status"] == ApprovalStatus.APPROVED.value for item in results)


def test_load_previous_architecture_plans_excludes_current_feature_and_unapproved(
    project_with_previous_feature,
):
    agent = ArchitectureAgent()

    plans = agent._load_previous_architecture_plans(
        project_id=project_with_previous_feature["project_id"],
        exclude_feature_id=project_with_previous_feature["current_feature_id"],
    )

    assert len(plans) == 1
    assert plans[0]["feature_name"] == "Login"
    assert plans[0]["architecture_plan_json"]["design_views"]["interface_view"]["api_endpoints"]


def test_summary_renders_endpoints_entities_and_files_compactly():
    summary = summarize_previous_architecture_plans([
        {"feature_name": "Login", "architecture_plan_json": PREVIOUS_PLAN}
    ])

    assert "Feature: Login" in summary
    assert "POST /api/auth/login" in summary
    assert "UserCredentials" in summary
    assert "server/src/routes/auth.routes.js" in summary
    assert "client/src/pages/LoginPage.jsx" in summary
    # Compactness: the full plan JSON must NOT be dumped wholesale.
    assert "implementation_order" not in summary


def test_user_prompt_includes_project_context_when_present():
    prompt = build_architecture_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Task Comments"},
        srs_json={"functional_requirements": []},
        previous_architecture_plans=[
            {"feature_name": "Login", "architecture_plan_json": PREVIOUS_PLAN}
        ],
        project_manifest_json={"routes": ["server/src/routes/auth.routes.js"]},
    )

    assert "Previous features' APPROVED architecture plans" in prompt
    assert "POST /api/auth/login" in prompt
    assert "Project manifest" in prompt
    assert "do NOT re-plan endpoints" in prompt


def test_user_prompt_omits_project_context_for_a_projects_first_feature():
    prompt = build_architecture_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Task Comments"},
        srs_json={"functional_requirements": []},
        previous_architecture_plans=[],
        project_manifest_json={},
    )

    assert "Previous features' APPROVED architecture plans" not in prompt
    assert "Project manifest" not in prompt
