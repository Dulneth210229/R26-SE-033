"""
Unit tests for build_revision_planning_tools (app/agents/coder_agent/tools.py)
-- the read-only tool set + structured submit_code_plan tool used by the
agentic revision planner (planner.py's generate_via_exploration). No LLM
involved, same real-throwaway-git-repo pattern as test_coder_tools.py.
"""

import os
import shutil
import stat

import pytest

from app.agents.coder_agent.tools import REVISION_PLANNING_TOOL_NAMES, build_revision_planning_tools
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_and_tools():
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": f"Revision Tool Test {project_id}"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Revision Tool Test Feature",
    }

    tools, captured = build_revision_planning_tools(project_id, feature_id)
    by_name = {t.name: t for t in tools}

    yield {"project_id": project_id, "feature_id": feature_id, "tools": by_name, "captured": captured}

    repo_path = workspace_service.get_repo_path(project_id)
    workspace_service.ensure_project_repo(project_id).close()
    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_tool_set_excludes_write_capable_tools(project_and_tools):
    names = set(project_and_tools["tools"].keys())

    assert names == REVISION_PLANNING_TOOL_NAMES | {"check_component_styling", "submit_code_plan"}
    assert "write_file" not in names
    assert "apply_patch" not in names
    assert "run_shell" not in names
    assert "check_syntax" not in names
    assert "list_unimplemented_planned_files" not in names


def test_read_only_tools_still_work_against_the_real_scaffold(project_and_tools):
    result = project_and_tools["tools"]["list_dir"].invoke({"path": "."})
    assert "[dir]  app" in result
    assert "[dir]  lib" in result


def test_submit_code_plan_captures_its_argument(project_and_tools):
    plan_json = '{"files": [{"path": "a.tsx", "action": "modify", "rationale": "r", "maps_to": []}]}'

    result = project_and_tools["tools"]["submit_code_plan"].invoke({"plan_json": plan_json})

    assert "submitted" in result.lower()
    assert project_and_tools["captured"]["plan_json"] == plan_json


def test_check_component_styling_reports_on_the_real_workspace(project_and_tools):
    # The fresh Next.js scaffold already has app/page.tsx (unlike the old
    # MERN scaffold, which had no client/src/pages until a feature added
    # one) -- it should be reported, not treated as "nothing to scan".
    result = project_and_tools["tools"]["check_component_styling"].invoke({})
    assert "app/page.tsx" in result
