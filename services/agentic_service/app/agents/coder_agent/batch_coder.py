"""
Coder Agent batch (non-agentic) code generator.

Purpose: gives the Coder Agent a real, working coding path for a model that does not (or cannot
be confirmed to) support real tool-calling -- see app/services/model_capabilities.py, which
CoderAgent.run()/run_stream()/revise()/revise_stream() all consult before choosing between this
path and the existing agentic one. Instead of the agentic loop's live, iterative write_file/
apply_patch/check_syntax calls, ONE single-shot LLM call is made PER PLANNED FILE (never one giant
call for the whole plan -- a real token-budget wall, confirmed against this project's own real
generated features: this exact codebase's own Item Listing CRUD feature's files, sent as one
combined JSON response, would blow past this app's own default LLM_MAX_TOKENS and truncate
mid-file). Each call is asked to return that one file's COMPLETE content as a small structured
JSON response, applied deterministically -- a plain write, never `apply_patch`'s exact-match
find-and-replace, since a one-shot call has no live read-then-patch loop the way that tool's own
contract requires; a "modify" action is always a full-file overwrite instead, given the file's
current content as context and asked for the complete new version.

Honest, stated scope limit: this path has no mid-generation self-correction (no check_syntax
between files, no ability to look up an import path it wasn't told about, no live workspace
exploration) -- expected to be less reliable than the agentic path for a feature needing genuine
cross-file discovery, matching this project's own established precedent that a non-agentic
fallback rung is real and useful, never claimed to be equal quality. Its one real strength over
the agentic path: the relevant approved UI/UX design reference (if any) is always, unconditionally
attached to a page/component file's own prompt (see _design_reference_for_file) -- not something
the model has to remember to request via a tool call the way the agentic loop's
list_unread_ui_designs gate requires.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agents.coder_agent.prompt import BATCH_CODE_GENERATOR_SYSTEM_PROMPT
from app.agents.coder_agent.tools import (
    _find_approved_component_artifact,
    _find_approved_page_html_artifact,
)
from app.core.enums import AgentName
from app.utils.json_utils import extract_json_object
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _design_reference_for_file(feature_id: str, path: str) -> str | None:
    """
    Best-effort, fully automatic equivalent of the agentic loop's read_ui_component_design/
    read_ui_page_design tools -- there is no live model turn to ask for a design by name here, so
    this attaches whichever approved design the file's OWN path/name resolves to, unconditionally.
    Returns None (not an error) for any file that isn't a page/component, or one with no matching
    approved design.
    """
    if path.startswith("app/") and path.endswith("/page.tsx"):
        page_id = path[len("app/"):-len("/page.tsx")]
        artifact = _find_approved_page_html_artifact(feature_id, page_id)
    elif path.startswith("components/") and path.endswith(".tsx"):
        artifact = _find_approved_component_artifact(feature_id, Path(path).stem)
    else:
        return None

    if not artifact:
        return None

    try:
        return Path(artifact["file_path"]).read_text(encoding="utf-8")
    except OSError:
        return None


def _build_user_content(
    feature_id: str,
    file_entry: dict[str, Any],
    current_content: str | None,
    sibling_files_written: list[str],
    prior_failure_output: str | None,
    implementation_spec: str | None = None,
) -> str:
    path = file_entry.get("path", "")
    parts = [
        f"File to write: {path}",
        f"Action: {file_entry.get('action')}",
        f"Purpose/rationale: {file_entry.get('rationale', '')}",
        f"maps_to: {file_entry.get('maps_to', [])}",
    ]

    if current_content is not None:
        parts.append(f"Current content (your response REPLACES this entirely):\n```\n{current_content}\n```")

    if sibling_files_written:
        parts.append(
            "Files already written this run (names only, for import-path awareness): "
            + ", ".join(sibling_files_written)
        )

    design_reference = _design_reference_for_file(feature_id, path)
    if design_reference:
        parts.append(f"Approved UI/UX design reference for this file:\n```html\n{design_reference}\n```")

    if implementation_spec:
        parts.append(
            "Real spec detail for this file (from the approved SRS + Architecture Plan "
            "implementation_plan -- rationale/maps_to above are deliberately short IDs, this is "
            "what this file is actually supposed to do):\n" + implementation_spec
        )

    if prior_failure_output:
        parts.append(f"The previous attempt's real failure -- fix this in your response:\n{prior_failure_output}")

    return "\n\n".join(parts)


async def generate_file_content(
    feature_id: str,
    file_entry: dict[str, Any],
    current_content: str | None,
    sibling_files_written: list[str],
    prior_failure_output: str | None = None,
    implementation_spec: str | None = None,
) -> str | None:
    """
    One single-shot LLM call for exactly one planned file. Returns the file's real, complete
    content, or None on any failure/malformed/empty response -- never raises. A None result is
    treated by the caller (CoderAgent._code_with_batch_generation) exactly like a planned file
    that was never touched, feeding into the same retry machinery every other coding path uses.

    implementation_spec, when given, is the bounded, per-file spec slice built by
    prompt.build_implementation_spec_for_single_file -- see that function's own docstring for why
    this exists (the plan's own rationale/maps_to are deliberately terse).
    """
    from app.services.llm_provider_service import llm_provider_service

    user_content = _build_user_content(
        feature_id, file_entry, current_content, sibling_files_written, prior_failure_output, implementation_spec
    )

    try:
        provider = llm_provider_service.get_provider(agent_name=AgentName.CODER.value)
        raw_output = await provider.invoke_agent([
            {"role": "system", "content": BATCH_CODE_GENERATOR_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ])
        parsed = extract_json_object(raw_output)
        content = parsed.get("content")
        if not content or not str(content).strip():
            return None
        return content
    except Exception as error:  # noqa: BLE001 -- one bad file must never crash the whole batch run
        logger.warning("Batch code generation failed for %s: %s", file_entry.get("path"), error)
        return None
