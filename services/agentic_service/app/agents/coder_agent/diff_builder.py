"""
Coder Agent diff builder.

Purpose:
Build file_tree_json, code_manifest_json, requirement_code_map_json,
setup_instructions_markdown, and merge_report_markdown deterministically from
a git diff and the validated code_plan_json -- never from an LLM's
self-report of what it changed.

requirement_code_map_json in particular is built from the *actual* touched
files (workspace_service.diff_against_main's output) as the source of truth,
joined against the plan's maps_to -- a file the agent touched that wasn't in
the original plan still shows up here, flagged "planned": false, rather than
silently disappearing.
"""

from __future__ import annotations

from typing import Any

MAX_DIFF_TEXT_CHARS = 20_000


def build_file_tree(diff: dict[str, Any]) -> dict[str, Any]:
    return {
        "added": diff.get("added", []),
        "modified": diff.get("modified", []),
        "deleted": diff.get("deleted", []),
    }


def _touched_paths(diff: dict[str, Any]) -> set[str]:
    return set(diff.get("added", [])) | set(diff.get("modified", [])) | set(diff.get("deleted", []))


def build_code_manifest(code_plan_json: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    touched = _touched_paths(diff)

    files = [
        {
            "path": file_entry.get("path"),
            "action": file_entry.get("action"),
            "description": file_entry.get("rationale"),
            "maps_to": file_entry.get("maps_to", []),
            "actually_touched": file_entry.get("path") in touched,
        }
        for file_entry in code_plan_json.get("files", [])
    ]

    return {"files": files}


def build_requirement_code_map(code_plan_json: dict[str, Any], diff: dict[str, Any]) -> dict[str, Any]:
    touched = sorted(_touched_paths(diff))
    planned_by_path = {
        file_entry.get("path"): file_entry for file_entry in code_plan_json.get("files", [])
    }

    entries = []
    for path in touched:
        planned = planned_by_path.get(path)
        entries.append(
            {
                "path": path,
                "planned": planned is not None,
                "maps_to": planned.get("maps_to", []) if planned else [],
            }
        )

    return {"files": entries}


def build_setup_instructions_markdown(code_plan_json: dict[str, Any]) -> str:
    dependencies = code_plan_json.get("new_dependencies", []) or []
    env_vars = code_plan_json.get("env_vars_needed", []) or []

    lines = [
        "# Setup Instructions",
        "",
        "## Run the app",
        "",
        "This project is a working Next.js (App Router + TypeScript) app scaffolded "
        "from the start -- these commands work for every feature, not just this one.",
        "",
        "```bash",
        "npm install",
        "cp .env.example .env.local   # first time only -- fill in real values",
        "npm run build && npm start   # production build + boot (port 3000)",
        "# or, for local development:",
        "npm run dev                  # boots the Next.js dev server (port 3000)",
        "```",
        "",
    ]

    if dependencies:
        lines.extend(
            [
                "## New dependencies added by this feature",
                "",
                "Already declared in the relevant `package.json` and installed by "
                "`npm run install:all` above; listed here for traceability:",
                "",
                *[f"- `{dependency}`" for dependency in dependencies],
                "",
            ]
        )

    if env_vars:
        lines.append("## Required environment variables (add to `server/.env`)")
        lines.append("")
        lines.extend(f"- `{name}`" for name in env_vars)
        lines.append("")

    return "\n".join(lines)


def build_merge_report_markdown(
    feature_name: str,
    diff: dict[str, Any],
    verify_result: dict[str, Any],
    coding_attempts_used: int,
    real_database_configured: bool = False,
) -> str:
    lines = [f"# Merge Report: {feature_name}", ""]

    status_line = "PASSED" if verify_result["passed"] else "FAILED -- human review required before merging"
    lines.append(f"**Verification:** {status_line}")
    lines.append(f"**Coding attempts used:** {coding_attempts_used}")
    lines.append("")

    if real_database_configured:
        # Honest, visible side effect of the mock-data-until-real-DB feature: once a human
        # provides a real MongoDB URI via chat, it's written to .env.local, which verify()'s own
        # sandbox containers mount too (same workspace directory the preview container uses) --
        # so this verification ran against a REAL database, not the guarded null-skip every prior
        # run got. Real, but not risk-free (network-dependent flakiness, a mount-time page write
        # touching real data) -- surfaced here rather than silently accepted.
        lines.append(
            "> **This verification ran against a REAL, human-provided database connection**, "
            "not the default seed-data fallback -- review any data writes accordingly."
        )
        lines.append("")

    lines.append("## Verification steps")
    for step in verify_result["steps"]:
        lines.append(f"- **{step['name']}**: {step['status']}")

        # failed/info steps' output is substantive (missing endpoints, found
        # placeholder-stub phrases, ...) and would otherwise be invisible to
        # the human reviewer here -- passed/skipped steps stay terse since
        # their output is just install/build logs nobody needs to see by
        # default.
        if step["status"] in ("failed", "info") and step.get("output"):
            lines.append("  ```")
            lines.extend(f"  {line}" for line in step["output"].splitlines())
            lines.append("  ```")
    lines.append("")

    lines.append("## Files changed")
    for label, paths in [
        ("Added", diff.get("added", [])),
        ("Modified", diff.get("modified", [])),
        ("Deleted", diff.get("deleted", [])),
    ]:
        if paths:
            lines.append(f"### {label}")
            lines.extend(f"- `{path}`" for path in paths)
    lines.append("")

    diff_text = diff.get("diff_text", "")
    truncated = len(diff_text) > MAX_DIFF_TEXT_CHARS
    lines.append("## Detailed Code Changes (Line-by-Line Diff)" + (" (truncated)" if truncated else ""))
    lines.append("```diff")
    lines.append(diff_text[:MAX_DIFF_TEXT_CHARS])
    lines.append("```")

    return "\n".join(lines)
