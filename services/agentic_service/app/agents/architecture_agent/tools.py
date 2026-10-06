"""
Architecture Agent planning tools.

Read-only tools for the agentic architecture generation rung
(ArchitectureAgent._generate_raw_output_via_exploration): the model explores
the project's real context -- previous features' approved architecture
plans, the project manifest, and the actual workspace code -- before
submitting this feature's plan. Modeled directly on the proven
coder_agent/tools.py build_revision_planning_tools pattern (read-only tools
+ a submit tool whose JSON-string argument is written into a captured dict).

Deliberately NOT built by filtering build_coder_tools: that builder calls
workspace_service.ensure_project_repo at construction time, which CREATES
the workspace repo as a side effect -- wrong for the Architecture Agent,
which runs before any code exists and must stay strictly read-only. A
project's first feature legitimately has no workspace yet; every workspace
tool degrades to a clear "no workspace yet" string instead of raising.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.agents.coder_agent.tools import (
    SEARCH_EXCLUDED_DIRS,
    SEARCH_MAX_FILE_BYTES,
    SEARCH_MAX_RESULTS,
    PathEscapesWorkspaceError,
    _resolve_within,
)
from app.services.project_memory_service import project_memory_service
from app.services.workspace_service import workspace_service

_NO_WORKSPACE_MESSAGE = (
    "No workspace exists for this project yet (this is normal for a project's "
    "first feature -- no code has been generated). Plan from the SRS, previous "
    "architecture plans, and project manifest instead."
)


def build_architecture_planning_tools(
    project_id: str,
    previous_architecture_plans: list[dict[str, Any]],
) -> tuple[list[BaseTool], dict[str, Any]]:
    """
    Build the Architecture Agent's read-only planning tools.

    previous_architecture_plans: the already-loaded
    [{"feature_id", "feature_name", "architecture_plan_json"}] list from
    ArchitectureAgent._load_previous_architecture_plans -- bound at
    construction so the tool needs no store/file access of its own.

    Returns (tools, captured): `captured` is the dict
    submit_architecture_plan writes into (key "plan_json"); the caller reads
    it after the agent loop ends instead of parsing free-text chat output.
    """

    plans_by_name = {
        str(entry.get("feature_name", "")).strip().lower(): entry
        for entry in previous_architecture_plans
        if entry.get("feature_name")
    }

    captured: dict[str, Any] = {}

    def _workspace_root() -> Path | None:
        try:
            repo_path = workspace_service.get_repo_path(project_id).resolve()
        except Exception:
            return None
        return repo_path if repo_path.is_dir() else None

    @tool
    def list_workspace_dir(path: str = ".") -> str:
        """List files and folders under `path` in the project's real code workspace (read-only)."""
        workspace_root = _workspace_root()
        if workspace_root is None:
            return _NO_WORKSPACE_MESSAGE

        try:
            target = _resolve_within(workspace_root, path)
        except PathEscapesWorkspaceError as error:
            return str(error)

        if not target.exists():
            return f"Path not found: {path}"
        if not target.is_dir():
            return f"Not a directory: {path}"

        entries = sorted(target.iterdir(), key=lambda item: item.name)
        if not entries:
            return "(empty directory)"

        return "\n".join(
            f"{'[dir] ' if entry.is_dir() else '[file]'} {entry.name}" for entry in entries
        )

    @tool
    def read_workspace_file(path: str) -> str:
        """Read one file's contents from the project's real code workspace (read-only)."""
        workspace_root = _workspace_root()
        if workspace_root is None:
            return _NO_WORKSPACE_MESSAGE

        try:
            target = _resolve_within(workspace_root, path)
        except PathEscapesWorkspaceError as error:
            return str(error)

        if not target.exists() or not target.is_file():
            return f"File not found: {path}"

        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"File is not valid UTF-8 text: {path}"

    @tool
    def search_workspace_code(query: str) -> str:
        """Search the project's real code workspace for a regex pattern, returning path:line:content results."""
        workspace_root = _workspace_root()
        if workspace_root is None:
            return _NO_WORKSPACE_MESSAGE

        try:
            pattern = re.compile(query)
        except re.error:
            pattern = re.compile(re.escape(query))

        matches: list[str] = []
        for file_path in workspace_root.rglob("*"):
            if any(part in SEARCH_EXCLUDED_DIRS for part in file_path.parts):
                continue
            if not file_path.is_file():
                continue
            try:
                if file_path.stat().st_size > SEARCH_MAX_FILE_BYTES:
                    continue
                text = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            relative_path = file_path.relative_to(workspace_root)
            for line_number, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line):
                    matches.append(f"{relative_path}:{line_number}:{line.strip()}")
                    if len(matches) >= SEARCH_MAX_RESULTS:
                        matches.append(f"... truncated at {SEARCH_MAX_RESULTS} matches ...")
                        return "\n".join(matches)

        if not matches:
            return f"No matches found for: {query}"
        return "\n".join(matches)

    @tool
    def read_project_manifest() -> str:
        """Return the project's manifest (routes/models/components already merged into the codebase) as JSON text."""
        manifest = project_memory_service.load_project_manifest(project_id)
        return json.dumps(manifest, indent=2, default=str)

    @tool
    def read_previous_architecture_plan(feature_name: str) -> str:
        """
        Read the full approved Architecture Plan JSON of a PREVIOUS feature in
        this same project, by its feature name -- use it to keep this
        feature's design consistent with (and reusing) what already exists.
        """
        entry = plans_by_name.get(str(feature_name).strip().lower())

        if entry is None:
            available = ", ".join(sorted(e.get("feature_name", "?") for e in previous_architecture_plans))
            if not available:
                return "This project has no previous features with an approved architecture plan."
            return (
                f"No previous feature named {feature_name!r}. "
                f"Available previous features: {available}"
            )

        return json.dumps(entry.get("architecture_plan_json", {}), indent=2, default=str)

    @tool
    def submit_architecture_plan(plan_json: str) -> str:
        """
        Submit your final output as a JSON string with the exact top-level
        structure described in your instructions (architecture_plan_json +
        usecase_specification_json). Call this exactly once, when you are
        confident -- this ends your turn.
        """
        captured["plan_json"] = plan_json
        return "Architecture plan submitted."

    return [
        list_workspace_dir,
        read_workspace_file,
        search_workspace_code,
        read_project_manifest,
        read_previous_architecture_plan,
        submit_architecture_plan,
    ], captured
