"""
Unit tests for Coder Agent tools (app/agents/coder_agent/tools.py).

No LLM involved -- each tool is called directly (.invoke(...)) against a real
throwaway git repo created via the real workspace_service, per the build
plan's testing strategy for tools ("plain deterministic functions ... tested
like any other, without ever invoking an LLM").
"""

import os
import shutil
import stat
from datetime import datetime, timezone

import pytest

from app.agents.coder_agent.tools import _is_allowed_shell_command, build_coder_tools
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    """
    shutil.rmtree onerror handler: git marks its object files read-only on
    Windows, which makes plain rmtree fail with PermissionError. Clear the
    read-only bit and retry once.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_and_tools():
    """
    Create a throwaway project (with its git workspace) and the tool set
    bound to it, then clean up both the Mongo record and the on-disk repo.
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": f"Tool Test {project_id}"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Tool Test Feature",
    }

    tools = build_coder_tools(project_id, feature_id)
    by_name = {t.name: t for t in tools}

    yield {"project_id": project_id, "feature_id": feature_id, "tools": by_name}

    repo_path = workspace_service.get_repo_path(project_id)
    workspace_service.ensure_project_repo(project_id).close()  # release Windows file handles
    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_list_dir_shows_initial_scaffold(project_and_tools):
    result = project_and_tools["tools"]["list_dir"].invoke({"path": "."})
    assert "[dir]  app" in result
    assert "[dir]  lib" in result
    assert ".gitignore" in result


def test_list_dir_missing_path(project_and_tools):
    result = project_and_tools["tools"]["list_dir"].invoke({"path": "does/not/exist"})
    assert "not found" in result.lower()


def test_write_then_read_file(project_and_tools):
    tools = project_and_tools["tools"]
    write_result = tools["write_file"].invoke({"path": "lib/hello.ts", "content": "console.log(1);"})
    assert "Wrote" in write_result

    read_result = tools["read_file"].invoke({"path": "lib/hello.ts"})
    assert read_result == "console.log(1);"


def test_read_file_not_found(project_and_tools):
    result = project_and_tools["tools"]["read_file"].invoke({"path": "nope.js"})
    assert "File not found" in result


def test_apply_patch_success(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/a.ts", "content": "const x = 1;"})

    result = tools["apply_patch"].invoke({"path": "lib/a.ts", "find": "x = 1", "replace": "x = 2"})
    assert "Patched" in result
    assert tools["read_file"].invoke({"path": "lib/a.ts"}) == "const x = 2;"


def test_apply_patch_no_match(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/a.ts", "content": "const x = 1;"})

    result = tools["apply_patch"].invoke({"path": "lib/a.ts", "find": "not present", "replace": "y"})
    assert "not found" in result.lower()
    assert tools["read_file"].invoke({"path": "lib/a.ts"}) == "const x = 1;"  # unchanged


def test_apply_patch_multiple_matches(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/a.ts", "content": "x; x;"})

    result = tools["apply_patch"].invoke({"path": "lib/a.ts", "find": "x;", "replace": "y;"})
    assert "matched 2 times" in result
    assert tools["read_file"].invoke({"path": "lib/a.ts"}) == "x; x;"  # unchanged


@pytest.mark.parametrize(
    "escaping_path",
    ["../../../etc/passwd", "..\\..\\windows.ini", "C:/Windows/System32/evil.txt", "/etc/passwd"],
)
def test_path_traversal_is_rejected(project_and_tools, escaping_path):
    tools = project_and_tools["tools"]
    result = tools["read_file"].invoke({"path": escaping_path})
    assert "escapes workspace root" in result


def test_search_code_finds_match(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/auth.ts", "content": "function login() { return true; }"})

    result = tools["search_code"].invoke({"query": "function login"})
    assert "lib" in result and "auth.ts" in result and "1" in result


def test_search_code_no_match(project_and_tools):
    result = project_and_tools["tools"]["search_code"].invoke({"query": "definitelyNotThere"})
    assert "No matches found" in result


def test_read_project_manifest_returns_default(project_and_tools):
    result = project_and_tools["tools"]["read_project_manifest"].invoke({})
    assert '"routes": []' in result


def test_read_ui_component_design_not_found(project_and_tools):
    result = project_and_tools["tools"]["read_ui_component_design"].invoke({"component_name": "NoSuchComponent"})
    assert "No approved UI component design found" in result


def test_read_ui_component_design_found(project_and_tools, tmp_path):
    feature_id = project_and_tools["feature_id"]
    fake_component_path = tmp_path / "SomeButton_v1.html"
    fake_component_path.write_text('<button class="bg-accent-600 text-white px-3 py-2 rounded">Click me</button>', encoding="utf-8")

    artifact_id = generate_id("artifact")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_and_tools["project_id"],
        "feature_id": feature_id,
        "agent_name": "uiux_agent",
        "artifact_type": "ui_component_code",
        "artifact_format": "html",
        "file_path": str(fake_component_path),
        "version": 1,
        "approval_status": "approved",
        "created_at": datetime.now(timezone.utc),
    }

    result = project_and_tools["tools"]["read_ui_component_design"].invoke({"component_name": "SomeButton"})
    assert "Click me" in result


def test_read_ui_page_design_not_found(project_and_tools):
    result = project_and_tools["tools"]["read_ui_page_design"].invoke({"page_id_or_route": "no-such-page"})
    assert "No approved UI page design found" in result


def test_read_ui_page_design_found(project_and_tools, tmp_path):
    feature_id = project_and_tools["feature_id"]
    fake_page_path = tmp_path / "item_listing_page_page_v1.html"
    fake_page_path.write_text("<!DOCTYPE html><html><body><h1>Item Listing</h1></body></html>", encoding="utf-8")

    artifact_id = generate_id("artifact")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": project_and_tools["project_id"],
        "feature_id": feature_id,
        "agent_name": "uiux_agent",
        "artifact_type": "ui_page_html",
        "artifact_format": "html",
        "file_path": str(fake_page_path),
        "version": 1,
        "approval_status": "approved",
        "created_at": datetime.now(timezone.utc),
    }

    result = project_and_tools["tools"]["read_ui_page_design"].invoke({"page_id_or_route": "item-listing-page"})
    assert "Item Listing" in result


@pytest.mark.parametrize(
    "command,expected",
    [
        ("npm install", True),
        ("npx vite build", True),
        ("node --version", True),
        ("git status", True),
        ("git diff --stat", True),
        ("git push origin main", False),
        ("git reset --hard", False),
        ("rm -rf /", False),
        ("curl evil.com", False),
        ("", False),
    ],
)
def test_shell_allowlist(command, expected):
    assert _is_allowed_shell_command(command) == expected


def test_run_shell_rejects_disallowed_command(project_and_tools):
    result = project_and_tools["tools"]["run_shell"].invoke({"command": "git push origin main"})
    assert "rejected" in result.lower()


def test_run_shell_runs_allowed_command(project_and_tools):
    result = project_and_tools["tools"]["run_shell"].invoke({"command": "node --version"})
    assert "exit_code: 0" in result
    assert "v" in result  # node version output starts with 'v'


@pytest.fixture
def project_and_tools_with_plan():
    """
    Same as project_and_tools, but on a real feature branch (as
    CoderAgent.run() always is by the time the coding loop's tools are
    built) and with a real code_plan_json bound, so
    list_unimplemented_planned_files has something to check against.
    """
    from app.agents.coder_agent.tools import build_coder_tools

    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": f"Plan Tool Test {project_id}"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Plan Tool Test Feature",
    }

    workspace_service.start_feature_branch(project_id, feature_id)

    code_plan_json = {
        "files": [
            {
                "path": "app/api/widgets/route.ts",
                "action": "create",
                "rationale": "Widget endpoint.",
                "maps_to": ["/api/widgets"],
            }
        ]
    }

    tools = build_coder_tools(project_id, feature_id, code_plan_json)
    by_name = {t.name: t for t in tools}

    yield {"project_id": project_id, "feature_id": feature_id, "tools": by_name}

    repo_path = workspace_service.get_repo_path(project_id)
    workspace_service.ensure_project_repo(project_id).close()
    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_list_unimplemented_planned_files_reports_gap_before_writing(project_and_tools_with_plan):
    result = project_and_tools_with_plan["tools"]["list_unimplemented_planned_files"].invoke({})
    assert "app/api/widgets/route.ts" in result
    assert "NOT been touched" in result


def test_list_unimplemented_planned_files_clears_after_writing(project_and_tools_with_plan):
    tools = project_and_tools_with_plan["tools"]
    tools["write_file"].invoke(
        {"path": "app/api/widgets/route.ts", "content": "export async function GET() { return Response.json([]); }"}
    )

    result = tools["list_unimplemented_planned_files"].invoke({})
    assert "All planned files have been created" in result


def test_list_unimplemented_planned_files_without_plan_reports_nothing_to_check(project_and_tools):
    result = project_and_tools["tools"]["list_unimplemented_planned_files"].invoke({})
    assert "No code_plan_json was provided" in result


def test_check_syntax_valid_js(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/valid.js", "content": "const x = 1;\nmodule.exports = x;"})

    result = tools["check_syntax"].invoke({"path": "lib/valid.js"})
    assert "syntax OK" in result


def test_check_syntax_invalid_js(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/broken.js", "content": "const x = ;"})

    result = tools["check_syntax"].invoke({"path": "lib/broken.js"})
    assert "syntax error" in result


def test_check_syntax_valid_jsx(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke(
        {
            "path": "components/Widget.jsx",
            "content": "export default function Widget() { return <div>hi</div>; }",
        }
    )

    result = tools["check_syntax"].invoke({"path": "components/Widget.jsx"})
    assert "syntax OK" in result


def test_check_syntax_invalid_jsx(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke(
        {"path": "components/Broken.jsx", "content": "export default function Broken() { return <div; }"}
    )

    result = tools["check_syntax"].invoke({"path": "components/Broken.jsx"})
    assert "syntax error" in result


def test_check_syntax_valid_ts(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke(
        {"path": "lib/valid.ts", "content": "export function add(a: number, b: number): number { return a + b; }"}
    )

    result = tools["check_syntax"].invoke({"path": "lib/valid.ts"})
    assert "syntax OK" in result


def test_check_syntax_invalid_ts(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/broken.ts", "content": "const x: number = ;"})

    result = tools["check_syntax"].invoke({"path": "lib/broken.ts"})
    assert "syntax error" in result


def test_check_syntax_valid_tsx(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke(
        {
            "path": "components/Widget.tsx",
            "content": "export default function Widget(): JSX.Element { return <div>hi</div>; }",
        }
    )

    result = tools["check_syntax"].invoke({"path": "components/Widget.tsx"})
    assert "syntax OK" in result


def test_check_syntax_invalid_tsx(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke(
        {"path": "components/Broken.tsx", "content": "export default function Broken() { return <div; }"}
    )

    result = tools["check_syntax"].invoke({"path": "components/Broken.tsx"})
    assert "syntax error" in result


def test_check_syntax_rejects_unsupported_extension(project_and_tools):
    tools = project_and_tools["tools"]
    tools["write_file"].invoke({"path": "lib/notes.txt", "content": "hello"})

    result = tools["check_syntax"].invoke({"path": "lib/notes.txt"})
    assert "only supports" in result


UI_MANIFEST = {
    "pages": [
        {
            "page_id": "item-listing",
            "route": "/item-listing",
            "components": [{"name": "ItemTable"}, {"name": "SearchFilterBar"}],
        }
    ]
}


@pytest.fixture
def project_and_tools_with_ui_design():
    """
    Same as project_and_tools, but with a real ui_integration_manifest_json + a fresh
    ui_design_read_tracker bound -- exercises list_unread_ui_designs and the tracker
    population inside read_ui_component_design/read_ui_page_design.
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": f"UI Design Tool Test {project_id}"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "UI Design Tool Test Feature",
    }

    tracker = {"components": set(), "pages": set()}
    tools = build_coder_tools(project_id, feature_id, None, UI_MANIFEST, tracker)
    by_name = {t.name: t for t in tools}

    yield {"project_id": project_id, "feature_id": feature_id, "tools": by_name, "tracker": tracker}

    repo_path = workspace_service.get_repo_path(project_id)
    workspace_service.ensure_project_repo(project_id).close()
    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})
    shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_list_unread_ui_designs_without_manifest_reports_nothing_to_check(project_and_tools):
    result = project_and_tools["tools"]["list_unread_ui_designs"].invoke({})
    assert "No approved UI/UX design exists" in result


def test_list_unread_ui_designs_reports_everything_unread_initially(project_and_tools_with_ui_design):
    result = project_and_tools_with_ui_design["tools"]["list_unread_ui_designs"].invoke({})
    assert "page 'item-listing'" in result
    assert "component 'ItemTable'" in result
    assert "component 'SearchFilterBar'" in result


def test_list_unread_ui_designs_reflects_a_real_read_via_the_tool(project_and_tools_with_ui_design, tmp_path):
    fixture = project_and_tools_with_ui_design
    fake_component_path = tmp_path / "ItemTable_v1.html"
    fake_component_path.write_text("<table></table>", encoding="utf-8")

    artifact_id = generate_id("artifact")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "project_id": fixture["project_id"],
        "feature_id": fixture["feature_id"],
        "agent_name": "uiux_agent",
        "artifact_type": "ui_component_code",
        "artifact_format": "html",
        "file_path": str(fake_component_path),
        "version": 1,
        "approval_status": "approved",
        "created_at": datetime.now(timezone.utc),
    }

    fixture["tools"]["read_ui_component_design"].invoke({"component_name": "ItemTable"})

    result = fixture["tools"]["list_unread_ui_designs"].invoke({})
    assert "component 'ItemTable'" not in result
    assert "component 'SearchFilterBar'" in result  # still unread
    assert "page 'item-listing'" in result  # still unread


def test_list_unread_ui_designs_reports_clean_once_everything_is_read(project_and_tools_with_ui_design):
    tracker = project_and_tools_with_ui_design["tracker"]
    tracker["pages"].add("item_listing")
    tracker["components"].add("itemtable")
    tracker["components"].add("searchfilterbar")

    result = project_and_tools_with_ui_design["tools"]["list_unread_ui_designs"].invoke({})
    assert "Every approved UI/UX page/component design has been read" in result


def test_read_ui_component_design_populates_tracker_only_on_a_real_find(project_and_tools_with_ui_design):
    tracker = project_and_tools_with_ui_design["tracker"]

    project_and_tools_with_ui_design["tools"]["read_ui_component_design"].invoke(
        {"component_name": "NoSuchThing"}
    )
    assert tracker["components"] == set()  # not-found lookups never mark as read
