"""
Coder Agent tools.

These are the tools handed to the agentic coding loop (M4's
create_react_agent). All path-taking tools are hard-scoped to
workspaces/{project_slug}/repo -- any path that would resolve outside that
root is rejected, never executed.

Each tool returns a plain string, even on failure ("file not found",
"find text did not match exactly once", a rejected shell command, etc.)
rather than raising, so the agent loop can read the failure and react to it
instead of crashing.

Tools are built per-run by build_coder_tools(project_id, feature_id) rather
than defined as bare module-level @tool functions, because every tool needs
to already be bound to one project's workspace (and, for
read_ui_component_design/read_ui_page_design, one feature's approved UI/UX
output) -- the LLM-facing signatures below take no project_id/feature_id
argument at all, matching the build plan's literal tool signatures.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.agents.coder_agent.style_checker import check_component_styling as _check_component_styling
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.in_memory_store import store
from app.services.project_memory_service import project_memory_service
from app.services.sandbox_service import sandbox_service
from app.services.workspace_service import workspace_service

ALLOWED_SHELL_COMMANDS = {"npm", "npx", "node"}
ALLOWED_GIT_SUBCOMMANDS = {"status", "diff"}

SEARCH_EXCLUDED_DIRS = {".git", "node_modules", ".next"}
SEARCH_MAX_RESULTS = 200
SEARCH_MAX_FILE_BYTES = 2_000_000  # skip huge/binary-ish files


class PathEscapesWorkspaceError(Exception):
    """Raised internally when a tool argument would resolve outside the workspace root."""


def search_workspace_content(
    workspace_root: Path, pattern: re.Pattern, max_results: int = SEARCH_MAX_RESULTS
) -> list[str]:
    """
    Walk workspace_root for lines matching `pattern`, returning "path:line:content"
    strings (like ripgrep), capped at max_results. Shared by the search_code tool
    (build_coder_tools, below) and CoderAgent._find_keyword_hint_files (agent.py's
    Tier 1b keyword-hint pre-retrieval, called directly as a plain function -- not
    through the LangChain @tool wrapper, since it runs before any LLM call) so the
    walking/exclusion logic has exactly one source of truth.
    """
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

                if len(matches) >= max_results:
                    matches.append(f"... truncated at {max_results} matches ...")
                    return matches

    return matches


def _resolve_within(workspace_root: Path, path: str) -> Path:
    """
    Resolve `path` relative to workspace_root and guarantee the result stays
    inside it. Handles both '..'-style traversal and absolute-path arguments
    (pathlib silently discards the left operand when the right side of `/`
    is itself absolute, so the check must happen on the final resolved path,
    not on the raw string).
    """
    candidate = (workspace_root / path).resolve()

    if not candidate.is_relative_to(workspace_root):
        raise PathEscapesWorkspaceError(f"Path escapes workspace root: {path!r}")

    return candidate


def _is_allowed_shell_command(command: str) -> bool:
    tokens = command.strip().split()

    if not tokens:
        return False

    if tokens[0] in ALLOWED_SHELL_COMMANDS:
        return True

    if tokens[0] == "git" and len(tokens) >= 2 and tokens[1] in ALLOWED_GIT_SUBCOMMANDS:
        return True

    return False


def build_coder_tools(
    project_id: str,
    feature_id: str,
    code_plan_json: dict[str, Any] | None = None,
    ui_integration_manifest_json: dict[str, Any] | None = None,
    ui_design_read_tracker: dict[str, set[str]] | None = None,
) -> list[BaseTool]:
    """
    Build the Coder Agent tools, scoped to one project's workspace, one
    feature's approved UI/UX output, and (for list_unimplemented_planned_files)
    one run's approved code_plan_json.

    code_plan_json is optional so existing callers/tests that only need the
    file/shell tools don't have to supply a plan -- list_unimplemented_planned_files
    degrades to reporting "no plan available" rather than raising when omitted.

    ui_integration_manifest_json/ui_design_read_tracker are a matched pair for
    list_unread_ui_designs: the manifest is what to check against (the real
    pages/components an approved UI/UX design exists for), and the tracker is
    an EXTERNALLY-OWNED, plain mutable dict the CALLER creates fresh per
    coding attempt (e.g. {"components": set(), "pages": set()}) and passes in
    -- read_ui_component_design/read_ui_page_design write into it whenever
    they successfully resolve a real artifact, so the caller can inspect,
    after this agent instance's turn ends, whether any design was actually
    read (a tool closure has no other way to report anything back out). Both
    are optional and independent of code_plan_json so existing callers/tests
    are unaffected; list_unread_ui_designs degrades to reporting "nothing to
    check" when either is omitted.
    """

    workspace_service.ensure_project_repo(project_id)
    workspace_root = workspace_service.get_repo_path(project_id).resolve()

    @tool
    def list_dir(path: str = ".") -> str:
        """List files and folders under `path` (relative to the workspace root)."""
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
    def read_file(path: str) -> str:
        """Read a file's contents as text."""
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
    def write_file(path: str, content: str) -> str:
        """Create a new file (or fully overwrite an existing one) with `content`."""
        try:
            target = _resolve_within(workspace_root, path)
        except PathEscapesWorkspaceError as error:
            return str(error)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        return f"Wrote {len(content)} characters to {path}"

    @tool
    def apply_patch(path: str, find: str, replace: str) -> str:
        """
        Replace an exact snippet in an existing file. `find` must match the
        file's current content exactly once -- if it matches zero or more
        than one time, nothing is written and an error explaining why is
        returned so the file can be re-read and retried.
        """
        try:
            target = _resolve_within(workspace_root, path)
        except PathEscapesWorkspaceError as error:
            return str(error)

        if not target.exists() or not target.is_file():
            return f"File not found: {path}"

        content = target.read_text(encoding="utf-8")
        occurrences = content.count(find)

        if occurrences == 0:
            return (
                "Patch failed: `find` text was not found in the file. "
                "Re-read the file and retry with an exact snippet."
            )

        if occurrences > 1:
            return (
                f"Patch failed: `find` text matched {occurrences} times, but must match "
                "exactly once. Include more surrounding context to make it unique."
            )

        target.write_text(content.replace(find, replace, 1), encoding="utf-8")

        return f"Patched {path} (1 replacement)."

    @tool
    def run_shell(command: str, cwd: str = ".", timeout: int = 120) -> str:
        """
        Run an allowlisted shell command (npm, npx, node, git status, git diff)
        inside a sandboxed container with the workspace mounted.
        """
        if not _is_allowed_shell_command(command):
            return (
                f"Command rejected: only npm, npx, node, 'git status', and 'git diff' "
                f"are allowed. Got: {command!r}"
            )

        result = sandbox_service.run_command(
            project_id=project_id, command=command, cwd=cwd, timeout=timeout
        )

        return (
            f"exit_code: {result['exit_code']}\n"
            f"stdout:\n{result['stdout']}\n"
            f"stderr:\n{result['stderr']}"
        )

    @tool
    def search_code(query: str) -> str:
        """
        Search the workspace for a regex pattern, returning path:line:content
        results (like ripgrep). Capped to avoid dumping unbounded output.
        """
        try:
            pattern = re.compile(query)
        except re.error:
            pattern = re.compile(re.escape(query))

        matches = search_workspace_content(workspace_root, pattern)

        if not matches:
            return f"No matches found for: {query}"

        return "\n".join(matches)

    @tool
    def read_project_manifest() -> str:
        """Return the project's manifest (existing routes/models/components) as JSON text."""
        manifest = project_memory_service.load_project_manifest(project_id)
        return json.dumps(manifest, indent=2, default=str)

    @tool
    def read_ui_component_design(component_name: str) -> str:
        """
        Read the approved HTML+Tailwind VISUAL REFERENCE the UI/UX Agent produced for one
        component of this feature. This is a static design reference, NOT working code -- read
        its structure/Tailwind classes/content, then write real Next.js TSX that faithfully
        matches it (same layout, classes, and content), wired to real props/state/data-fetching.
        Never dangerouslySetInnerHTML the raw HTML.
        """
        artifact = _find_approved_component_artifact(feature_id, component_name)

        if not artifact:
            return f"No approved UI component design found for this feature named: {component_name}"

        if ui_design_read_tracker is not None:
            ui_design_read_tracker.setdefault("components", set()).add(_slugify(component_name))

        return Path(artifact["file_path"]).read_text(encoding="utf-8")

    @tool
    def read_ui_page_design(page_id_or_route: str) -> str:
        """
        Read the approved, fully-assembled HTML+Tailwind VISUAL REFERENCE for one whole page of
        this feature (all of that page's components combined into one document, in their real
        layout order) -- use this for full-page layout/structure context beyond a single
        component. Same rule as read_ui_component_design: this is a design reference to
        re-implement faithfully as real TSX, not code to import or embed verbatim.
        """
        artifact = _find_approved_page_html_artifact(feature_id, page_id_or_route)

        if not artifact:
            return f"No approved UI page design found for this feature matching: {page_id_or_route}"

        if ui_design_read_tracker is not None:
            ui_design_read_tracker.setdefault("pages", set()).add(_slugify(page_id_or_route))

        return Path(artifact["file_path"]).read_text(encoding="utf-8")

    @tool
    def list_unread_ui_designs() -> str:
        """
        Report which of this feature's approved UI/UX page/component designs you have NOT yet
        read via read_ui_component_design/read_ui_page_design during this attempt. Call this
        before ending your turn whenever an approved UI/UX design exists for this feature (it
        will tell you plainly if none does) -- read whatever it lists before finishing, so the
        frontend code you write actually matches the approved visual design instead of being a
        freehand guess.
        """
        if not ui_integration_manifest_json:
            return "No approved UI/UX design exists for this feature -- nothing to check."

        pages = ui_integration_manifest_json.get("pages") or []
        if not pages:
            return "No approved UI/UX design exists for this feature -- nothing to check."

        read_pages = (ui_design_read_tracker or {}).get("pages", set())
        read_components = (ui_design_read_tracker or {}).get("components", set())

        unread: list[str] = []
        for page in pages:
            page_id = page.get("page_id")
            if page_id and _slugify(page_id) not in read_pages:
                unread.append(f"- page '{page_id}' -- call read_ui_page_design({page_id!r})")

            for component in page.get("components") or []:
                name = component.get("name")
                if name and _slugify(name) not in read_components:
                    unread.append(f"- component '{name}' -- call read_ui_component_design({name!r})")

        if not unread:
            return "Every approved UI/UX page/component design has been read this attempt."

        return (
            "The following approved UI/UX designs have NOT been read yet -- read the ones "
            "relevant to whatever frontend page/component you are about to write, before "
            "ending your turn:\n" + "\n".join(unread)
        )

    @tool
    def list_unimplemented_planned_files() -> str:
        """
        Compare the approved plan's file list against what has actually been
        created/modified/deleted so far in this workspace (computed from git,
        not from memory of your own tool calls) and report any planned file
        you have not yet touched. Call this before ending your turn -- do not
        rely on your own recollection of what you've done; check here first.
        """
        if not code_plan_json:
            return "No code_plan_json was provided for this run -- nothing to check against."

        touched = workspace_service.get_touched_files(project_id, feature_id)
        touched_paths = set(touched["added"]) | set(touched["modified"]) | set(touched["deleted"])

        gaps = []
        for file_entry in code_plan_json.get("files", []):
            path = file_entry.get("path")
            action = file_entry.get("action")

            if not path or path in touched_paths:
                continue

            gaps.append(f"- {path} (action: {action}, rationale: {file_entry.get('rationale', '')})")

        if not gaps:
            return "All planned files have been created, modified, or deleted as required."

        return (
            "The following planned files have NOT been touched yet -- address these "
            "before ending your turn:\n" + "\n".join(gaps)
        )

    @tool
    def check_syntax(path: str) -> str:
        """
        Run a fast syntax check on a single .js/.jsx/.ts/.tsx file you just
        wrote or patched, without the cost of a full install/build. Use this
        right after write_file/apply_patch on any such file, before moving
        on. This is syntax-only, not type-checking -- real type errors are
        still caught by `next build` at the end (a separate `tsc --noEmit`
        gate here would double the slowest step in the loop for marginal
        extra coverage).
        """
        try:
            target = _resolve_within(workspace_root, path)
        except PathEscapesWorkspaceError as error:
            return str(error)

        if not target.exists() or not target.is_file():
            return f"File not found: {path}"

        suffix = target.suffix.lower()
        if suffix not in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
            return f"check_syntax only supports .js/.jsx/.mjs/.cjs/.ts/.tsx files, got: {path}"

        relative_path = target.relative_to(workspace_root).as_posix()

        # .ts and .tsx need DIFFERENT @babel/parser plugin sets -- combining
        # 'jsx' with 'typescript' on a plain .ts file breaks parsing of
        # `<T>expr` type-assertion syntax (ambiguous with JSX), a real Babel
        # limitation, not a guess. Plain .js/.mjs/.cjs get Node's own
        # --check instead (no Babel needed at all for those).
        plugins_by_suffix = {
            ".jsx": "['jsx']",
            ".ts": "['typescript']",
            ".tsx": "['jsx', 'typescript']",
        }

        if suffix in plugins_by_suffix:
            check_script = (
                "const fs = require('fs');"
                "const { parse } = require('@babel/parser');"
                f"const code = fs.readFileSync('{relative_path}', 'utf-8');"
                "try {"
                f"  parse(code, {{ sourceType: 'module', plugins: {plugins_by_suffix[suffix]} }});"
                "  console.log('SYNTAX_OK');"
                "} catch (error) {"
                "  console.error('SYNTAX_ERROR: ' + error.message);"
                "  process.exit(1);"
                "}"
            )
            command = f"node -e \"{check_script}\""
        else:
            command = f"node --check {relative_path}"

        result = sandbox_service.run_command(project_id=project_id, command=command, cwd=".", timeout=30)

        if result["exit_code"] == 0:
            return f"{path}: syntax OK."

        return f"{path}: syntax error.\n{result['stderr'] or result['stdout']}"

    return [
        list_dir,
        read_file,
        write_file,
        apply_patch,
        run_shell,
        search_code,
        read_project_manifest,
        read_ui_component_design,
        read_ui_page_design,
        list_unread_ui_designs,
        list_unimplemented_planned_files,
        check_syntax,
    ]


REVISION_PLANNING_TOOL_NAMES = {
    "list_dir",
    "read_file",
    "search_code",
    "read_project_manifest",
    "read_ui_component_design",
    "read_ui_page_design",
}


def build_revision_planning_tools(
    project_id: str, feature_id: str
) -> tuple[list[BaseTool], dict[str, Any]]:
    """
    Read-only subset of build_coder_tools, for the agentic revision planner
    (planner.py's CodePlanner.generate_via_exploration) to look at the real,
    current codebase before finalizing a plan -- explicitly excludes
    write_file/apply_patch/run_shell/check_syntax/list_unimplemented_planned_files,
    since planning must never touch the working tree.

    Also returns a `submit_code_plan` tool: the model's one and only way to
    finish. Its argument is a JSON-encoded string (not a nested list[dict]
    tool argument) so parsing can reuse CodePlanner._extract_json_object
    (with its existing repair-prompt fallback) instead of depending on a
    nested tool-call schema this codebase hasn't already proven works.

    Also returns a `check_component_styling` tool (style_checker.py):
    directly reports which .tsx files under app/ and components/ currently
    use Tailwind classes, raw inline styles, or neither -- confirmed
    necessary directly, not speculatively:
    a real exploration run correctly found Tailwind was already configured
    project-wide but still converged on the wrong fix (editing index.css)
    because manually finding "which file has NO className" via list_dir/
    read_file is a much harder inverse-search task than finding files that
    DO match a pattern. This tool answers it directly instead.

    Returns (tools, captured) where `captured` is a plain dict the
    submit_code_plan tool writes into (key "plan_json") -- the caller reads
    it after the agent loop ends, rather than parsing free-text chat output.
    """
    all_tools = build_coder_tools(project_id, feature_id)
    read_only_tools = [t for t in all_tools if t.name in REVISION_PLANNING_TOOL_NAMES]

    workspace_root = workspace_service.get_repo_path(project_id).resolve()
    captured: dict[str, Any] = {}

    @tool
    def check_component_styling() -> str:
        """
        Best-effort scan of every .jsx file under client/src/pages and
        client/src/components, reporting whether each one uses Tailwind
        classes (className=), only raw inline styles (style={{...}}), or
        neither. Call this when a human's revision comment describes a
        styling/CSS issue without naming specific files -- it directly
        tells you which files are affected instead of you having to infer
        it by manually reading every file yourself.
        """
        results = _check_component_styling(workspace_root)

        if not results:
            return "No .tsx files found under app/ or components/."

        return "\n".join(f"{item['path']}: {item['status']}" for item in results)

    @tool
    def submit_code_plan(plan_json: str) -> str:
        """
        Submit your final code plan as a JSON string, in the exact shape
        described in your instructions. Call this exactly once, only after
        you have explored enough to be confident about which files are
        affected -- this ends your turn.
        """
        captured["plan_json"] = plan_json
        return "Plan submitted."

    return read_only_tools + [check_component_styling, submit_code_plan], captured


def _slugify(value: str) -> str:
    """Same normalization _find_approved_component_artifact/_find_approved_page_html_artifact
    already use to match a queried name against a file_path -- shared here so
    list_unread_ui_designs cross-references the read tracker against the manifest using the
    IDENTICAL normalization the read tools themselves used to record a hit, regardless of exact
    phrasing differences (e.g. "item-listing" vs "Item Listing" vs "item_listing_page")."""
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def _find_approved_component_artifact(feature_id: str, component_name: str) -> dict[str, Any] | None:
    slug = _slugify(component_name)

    matching = []

    for artifact in store.artifacts.values():
        if artifact.get("feature_id") != feature_id:
            continue
        if artifact.get("agent_name") not in [AgentName.UIUX, AgentName.UIUX.value]:
            continue
        if artifact.get("artifact_type") not in [ArtifactType.UI_COMPONENT_CODE, ArtifactType.UI_COMPONENT_CODE.value]:
            continue
        if artifact.get("artifact_format") not in [ArtifactFormat.HTML, ArtifactFormat.HTML.value]:
            continue
        if artifact.get("approval_status") not in [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value]:
            continue
        if slug not in str(artifact.get("file_path", "")).lower():
            continue

        matching.append(artifact)

    if not matching:
        return None

    return max(matching, key=lambda item: item.get("version", 1))


def _find_approved_page_html_artifact(feature_id: str, page_id_or_route: str) -> dict[str, Any] | None:
    """Same lookup shape as _find_approved_component_artifact, sibling type (UI_PAGE_HTML) --
    matches a page's slugified page_id/route against the artifact's file_path, e.g. either
    "item-listing-page" or "/item-listing" resolve to the same "item_listing_page" slug."""
    slug = _slugify(page_id_or_route)

    matching = []

    for artifact in store.artifacts.values():
        if artifact.get("feature_id") != feature_id:
            continue
        if artifact.get("agent_name") not in [AgentName.UIUX, AgentName.UIUX.value]:
            continue
        if artifact.get("artifact_type") not in [ArtifactType.UI_PAGE_HTML, ArtifactType.UI_PAGE_HTML.value]:
            continue
        if artifact.get("artifact_format") not in [ArtifactFormat.HTML, ArtifactFormat.HTML.value]:
            continue
        if artifact.get("approval_status") not in [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value]:
            continue
        if slug not in str(artifact.get("file_path", "")).lower():
            continue

        matching.append(artifact)

    if not matching:
        return None

    return max(matching, key=lambda item: item.get("version", 1))
