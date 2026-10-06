"""
Golden-file style unit tests for the Coder Agent's diff_builder module.

No LLM involved -- given a fixed code_plan_json and a fixed diff dict, assert
the exact structures produced. Fully reproducible.
"""

from app.agents.coder_agent.diff_builder import (
    build_code_manifest,
    build_file_tree,
    build_merge_report_markdown,
    build_requirement_code_map,
    build_setup_instructions_markdown,
)

CODE_PLAN = {
    "files": [
        {
            "path": "server/src/routes/auth.routes.js",
            "action": "create",
            "rationale": "Login and forgot-password endpoints.",
            "maps_to": ["/api/auth/login", "FR-001"],
        },
        {
            "path": "server/src/models/UserCredentials.js",
            "action": "create",
            "rationale": "Persist user credentials.",
            "maps_to": ["User Credentials"],
        },
    ],
    "new_dependencies": ["bcrypt", "jsonwebtoken"],
    "env_vars_needed": ["JWT_SECRET"],
    "summary": "Implement login.",
}

# The agent touched everything in the plan, plus one unplanned file.
DIFF = {
    "added": [
        "server/src/routes/auth.routes.js",
        "server/src/models/UserCredentials.js",
        "server/src/utils/jwt.js",  # unplanned
    ],
    "modified": ["package.json"],
    "deleted": [],
    "diff_text": "diff --git a/server/src/routes/auth.routes.js ...",
}


def test_build_file_tree():
    assert build_file_tree(DIFF) == {
        "added": DIFF["added"],
        "modified": DIFF["modified"],
        "deleted": DIFF["deleted"],
    }


def test_build_code_manifest_marks_all_planned_files_touched():
    manifest = build_code_manifest(CODE_PLAN, DIFF)
    paths_touched = {f["path"]: f["actually_touched"] for f in manifest["files"]}

    assert paths_touched == {
        "server/src/routes/auth.routes.js": True,
        "server/src/models/UserCredentials.js": True,
    }


def test_build_code_manifest_flags_untouched_planned_file():
    diff_missing_one = {**DIFF, "added": ["server/src/routes/auth.routes.js"]}
    manifest = build_code_manifest(CODE_PLAN, diff_missing_one)
    paths_touched = {f["path"]: f["actually_touched"] for f in manifest["files"]}

    assert paths_touched["server/src/models/UserCredentials.js"] is False


def test_build_requirement_code_map_includes_unplanned_file():
    req_map = build_requirement_code_map(CODE_PLAN, DIFF)
    by_path = {entry["path"]: entry for entry in req_map["files"]}

    assert by_path["server/src/utils/jwt.js"]["planned"] is False
    assert by_path["server/src/utils/jwt.js"]["maps_to"] == []

    assert by_path["server/src/routes/auth.routes.js"]["planned"] is True
    assert by_path["server/src/routes/auth.routes.js"]["maps_to"] == ["/api/auth/login", "FR-001"]

    # package.json was modified but isn't in the plan -- also unplanned.
    assert by_path["package.json"]["planned"] is False


def test_build_setup_instructions_with_deps_and_env_vars():
    markdown = build_setup_instructions_markdown(CODE_PLAN)

    assert "npm install" in markdown
    assert "npm run dev" in markdown
    assert "`bcrypt`" in markdown
    assert "`jsonwebtoken`" in markdown
    assert "`JWT_SECRET`" in markdown


def test_build_setup_instructions_empty_case():
    markdown = build_setup_instructions_markdown({"new_dependencies": [], "env_vars_needed": []})

    # The run instructions are always present -- there's always a working
    # scaffold to run, regardless of whether this specific feature added
    # anything new.
    assert "npm install" in markdown
    assert "npm run dev" in markdown
    assert "New dependencies added by this feature" not in markdown
    assert "Required environment variables" not in markdown


def test_build_merge_report_shows_pass_and_fail_status():
    passing = build_merge_report_markdown(
        "Login", DIFF, {"passed": True, "steps": [{"name": "npm install", "status": "passed"}]}, 1
    )
    assert "PASSED" in passing

    failing = build_merge_report_markdown(
        "Login", DIFF, {"passed": False, "steps": [{"name": "npm run build", "status": "failed"}]}, 3
    )
    assert "FAILED" in failing
    assert "Coding attempts used:** 3" in failing


def test_build_merge_report_surfaces_output_for_failed_and_info_steps_only():
    report = build_merge_report_markdown(
        "Login",
        DIFF,
        {
            "passed": False,
            "steps": [
                {"name": "npm install (server)", "status": "passed", "output": "added 10 packages"},
                {
                    "name": "endpoint route coverage",
                    "status": "failed",
                    "output": "These planned endpoints have no matching route registration found:\n- /api/auth/signup",
                },
                {
                    "name": "placeholder-stub scan",
                    "status": "info",
                    "output": "Found possible placeholder/stub logic:\n- server/src/routes/auth.routes.js:57: in a real app",
                },
            ],
        },
        1,
    )

    assert "/api/auth/signup" in report
    assert "in a real app" in report
    assert "added 10 packages" not in report  # passed steps stay terse


def test_build_merge_report_lists_files_changed():
    report = build_merge_report_markdown("Login", DIFF, {"passed": True, "steps": []}, 1)

    assert "server/src/utils/jwt.js" in report
    assert "package.json" in report
