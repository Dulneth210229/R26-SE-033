"""
Unit tests for UIUXAgent's component-reuse fix (app/agents/uiux_agent/agent.py).

Bug this locks in: the model correctly sets reused_from_design_system=True
on ui_metadata for a component that already exists in the project's design
system, but nothing previously stopped a fresh (and possibly drifted) copy
from being generated anyway. _load_existing_approved_component must find and
return the exact, previously-approved file content instead. No LLM involved.

Components are HTML+Tailwind fragments (ArtifactFormat.HTML), not JSX -- see
CLAUDE.md's UI/UX Agent HTML rework entry for the full rationale.
"""

import tempfile
from pathlib import Path

from app.agents.uiux_agent.agent import UIUXAgent
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


def _seed_approved_component_artifact(project_id: str, feature_id: str, component_name: str, html_content: str, version: int = 1):
    tmp_dir = Path(tempfile.mkdtemp())
    file_path = tmp_dir / f"{component_name.lower()}_v{version}.html"
    file_path.write_text(html_content, encoding="utf-8")

    artifact_id = generate_id("artifact")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_id,
        "feature_id": feature_id,
        "agent_name": AgentName.UIUX.value,
        "artifact_type": ArtifactType.UI_COMPONENT_CODE.value,
        "artifact_format": ArtifactFormat.HTML.value,
        "approval_status": ApprovalStatus.APPROVED.value,
        "file_path": str(file_path),
        "version": version,
    }
    return artifact_id, tmp_dir


def test_load_existing_approved_component_returns_verbatim_content():
    agent = UIUXAgent()
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    html = '<form class="flex flex-col gap-3"><input class="border rounded p-2" placeholder="Email"></form>'

    artifact_id, tmp_dir = _seed_approved_component_artifact(project_id, feature_id, "LoginForm", html)

    try:
        result = agent._load_existing_approved_component(project_id, "LoginForm")
        assert result == html
    finally:
        store.database["artifacts"].delete_one({"artifact_id": artifact_id})
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_load_existing_approved_component_returns_none_when_absent():
    agent = UIUXAgent()
    project_id = generate_id("project")

    assert agent._load_existing_approved_component(project_id, "NoSuchComponent") is None


def test_load_existing_approved_component_ignores_other_projects():
    agent = UIUXAgent()
    project_id = generate_id("project")
    other_project_id = generate_id("project")
    feature_id = generate_id("feature")
    html = '<button class="bg-accent-600 text-white px-4 py-2 rounded">Submit</button>'

    artifact_id, tmp_dir = _seed_approved_component_artifact(other_project_id, feature_id, "Button", html)

    try:
        assert agent._load_existing_approved_component(project_id, "Button") is None
    finally:
        store.database["artifacts"].delete_one({"artifact_id": artifact_id})
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_load_existing_approved_component_picks_latest_version():
    agent = UIUXAgent()
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    artifact_id_v1, tmp_dir_v1 = _seed_approved_component_artifact(
        project_id, feature_id, "LoginForm", "<div>old content</div>", version=1
    )
    artifact_id_v2, tmp_dir_v2 = _seed_approved_component_artifact(
        project_id, feature_id, "LoginForm", "<div>new content</div>", version=2
    )

    try:
        result = agent._load_existing_approved_component(project_id, "LoginForm")
        assert result == "<div>new content</div>"
    finally:
        store.database["artifacts"].delete_one({"artifact_id": artifact_id_v1})
        store.database["artifacts"].delete_one({"artifact_id": artifact_id_v2})
        import shutil

        shutil.rmtree(tmp_dir_v1, ignore_errors=True)
        shutil.rmtree(tmp_dir_v2, ignore_errors=True)
