"""
Coder Agent coding loop.

This is the one non-deterministic step in the Coder Agent pipeline: an
agentic, tool-using loop that executes a pre-validated code_plan_json against
the project's real workspace. Everything around it (planning, plan
validation, workspace prep, verification, diffing) is deterministic code --
this module is intentionally small and does not try to make the loop itself
deterministic, only to scope what it's allowed to touch (via the tools it's
given) and what it's told to do (via the validated plan).

Milestone note: as of M4, this is invoked manually (see
scripts/run_coder_loop_manual.py), not from CoderAgent.run() or the graph --
that wiring happens once M5's verify/diff/merge steps exist to wrap it.
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents import create_agent
from langchain_core.runnables import Runnable

from app.agents.coder_agent.prompt import CODER_AGENT_SYSTEM_PROMPT
from app.agents.coder_agent.tools import build_coder_tools
from app.providers.agentic_model_factory import get_agentic_chat_model


def build_coder_react_agent(
    project_id: str,
    feature_id: str,
    code_plan_json: dict[str, Any] | None = None,
    ui_integration_manifest_json: dict[str, Any] | None = None,
    ui_design_read_tracker: dict[str, set[str]] | None = None,
) -> Runnable:
    """
    Build the Coder Agent's agentic loop, with tools scoped to one project's
    workspace, one feature's approved UI/UX output, and (for
    list_unimplemented_planned_files) this run's approved plan.

    ui_integration_manifest_json/ui_design_read_tracker are passed straight through to
    build_coder_tools -- see that function's own docstring for what they're for
    (list_unread_ui_designs's deterministic "did you actually look at the approved design"
    self-check, backing CoderAgent._code_with_retries' own per-attempt UI-fidelity gate).
    """
    tools = build_coder_tools(
        project_id, feature_id, code_plan_json, ui_integration_manifest_json, ui_design_read_tracker
    )

    return create_agent(
        model=get_agentic_chat_model(),
        tools=tools,
        system_prompt=CODER_AGENT_SYSTEM_PROMPT,
    )


def build_task_message(
    code_plan_json: dict[str, Any],
    prior_failure_output: str | None = None,
    already_touched: dict[str, list[str]] | None = None,
    original_request: str | None = None,
    implementation_spec_section: str | None = None,
) -> str:
    """
    Format the validated plan (+ optional prior verification failure, for a
    retry attempt) into the initial human message for the loop.

    already_touched, when given (a retry after a previous attempt already
    made some real progress), lists exactly which files are already
    created/modified/deleted -- so a fresh agent instance (each attempt
    starts with zero memory of the previous one, see CoderAgent._code_with_retries)
    doesn't have to re-read/re-derive what's already correct, and knows not
    to redo it.

    original_request, when given, is the human's own literal words (the
    human_comment/revision_comment the plan was generated FROM) -- shown
    ahead of the plan so the coding loop can sanity-check the plan's
    rationale against what was actually asked, instead of blindly executing
    a possibly-misparsed plan step. The plan is still the authoritative HOW;
    this is a cross-check, not a replacement for it.

    implementation_spec_section, when given, is the bounded, per-file-scoped
    slice of the approved SRS + Architecture Plan implementation_plan built by
    prompt.build_implementation_spec_section -- the plan's own maps_to/rationale
    are deliberately terse (short IDs/paths only, see
    _CODE_PLANNER_SHARED_HARD_RULES), so without this the coding loop has no
    idea what a planned file is actually supposed to DO beyond its own name.
    """
    sections = [
        "Implement the following pre-approved, pre-validated code plan.",
    ]

    if original_request:
        sections.extend(
            [
                "",
                "Original human request (the plan below is HOW to satisfy this -- if a plan "
                "item's rationale seems to contradict this original request, trust the "
                "original request and flag the discrepancy in your final summary rather than "
                "blindly executing it):",
                original_request,
            ]
        )

    sections.extend(["", json.dumps(code_plan_json, indent=2, default=str)])

    if implementation_spec_section:
        sections.extend(
            [
                "",
                "Real spec detail for the planned files above (from the approved SRS + "
                "Architecture Plan implementation_plan -- the plan's own rationale/maps_to are "
                "deliberately short IDs, this is what each file is actually supposed to do; "
                "follow its exact endpoint/model/page detail where given):",
                implementation_spec_section,
            ]
        )

    if already_touched:
        touched_paths = sorted(
            set(already_touched.get("added", []))
            | set(already_touched.get("modified", []))
            | set(already_touched.get("deleted", []))
        )
        if touched_paths:
            sections.extend(
                [
                    "",
                    "The following files already exist from a previous attempt and do not need "
                    "to be redone unless the failure below specifically points at them:",
                    "\n".join(f"- {path}" for path in touched_paths),
                ]
            )

    if prior_failure_output:
        sections.extend(
            [
                "",
                "A previous attempt at this plan failed verification. Fix the issue below, "
                "then continue:",
                prior_failure_output,
            ]
        )

    return "\n".join(sections)
