"""
Unit tests for ArtifactResponse/save_json_artifact's `summary` field -- lets
the frontend chat surface a real, model-generated description (e.g. a
CODE_PLAN artifact's own "summary" field) instead of a generic
"Produced X (vN)" placeholder. No LLM/Docker.
"""

import shutil
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.enums import AgentName, ArtifactType
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id
from app.utils.slugify import slugify


@pytest.fixture
def project_and_feature():
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    project = {"project_id": project_id, "project_name": f"Artifact Summary Test {project_id}"}
    feature = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Artifact Summary Feature",
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


def test_save_json_artifact_persists_summary(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_json_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.CODER,
        artifact_type=ArtifactType.CODE_PLAN,
        filename="test_code_plan_v{version}.json",
        data={"summary": "Adds a footer component and Tailwind styling.", "files": []},
        summary="Adds a footer component and Tailwind styling.",
    )

    assert response.summary == "Adds a footer component and Tailwind styling."

    refetched = artifact_service.get_artifact(response.artifact_id)
    assert refetched.summary == "Adds a footer component and Tailwind styling."


def test_save_json_artifact_summary_defaults_to_none(project_and_feature):
    project, feature = project_and_feature

    response = artifact_service.save_json_artifact(
        project=project,
        feature=feature,
        agent_name=AgentName.CODER,
        artifact_type=ArtifactType.CODE_DIFF,
        filename="test_file_tree_v{version}.json",
        data={"added": [], "modified": [], "deleted": []},
    )

    assert response.summary is None
