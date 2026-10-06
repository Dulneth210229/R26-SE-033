"""
Architecture Agent diagram-generation tools.

Read-only-plus-validate tools for the two dedicated agentic diagram
generation steps (ArchitectureAgent._generate_sequence_diagram_via_exploration
/ _generate_class_diagram_via_exploration). Kept separate from tools.py
(the main plan's workspace/project-manifest exploration tools) since this
tool set is diagram-specific and needs no workspace/store access at all --
everything is bound at construction from already-loaded data.

Deliberately no "read a previous feature's diagram" tool on either builder:
the whole point of this rewrite is diagrams grounded in THIS feature's real
content, not a structural precedent that risks pulling the model back
toward the same fixed shape every time.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.agents.architecture_agent.class_validator import ClassDiagramValidationError
from app.agents.architecture_agent.sequence_validator import SequenceDiagramValidationError
from app.agents.architecture_agent.usecase_validator import UseCaseValidationError

# After this many failed validate calls without reaching "VALID", the tool's
# own return text nudges the model to submit its current best draft instead
# of continuing to iterate -- matches this codebase's established
# "efficiency-hint feedback" idiom (documented in CLAUDE.md for the Coder
# Agent's revision planner) so an unproductive loop is more likely to still
# submit something before the hard recursion-limit backstop discards
# everything.
VALIDATE_NUDGE_THRESHOLD = 3


def _interface_and_data_context(architecture_plan_json: dict[str, Any]) -> dict[str, Any]:
    design_views = architecture_plan_json.get("design_views", {}) if isinstance(architecture_plan_json, dict) else {}
    if not isinstance(design_views, dict):
        design_views = {}
    return {
        "interface_view": design_views.get("interface_view", {}),
        "data_view": design_views.get("data_view", {}),
    }


def build_sequence_diagram_tools(
    srs_json: dict[str, Any],
    architecture_plan_json: dict[str, Any],
    sequence_modeler: Any,
    sequence_validator: Any,
) -> tuple[list[BaseTool], dict[str, Any]]:
    """
    Build the dedicated sequence-diagram generation tools.

    Returns (tools, captured): `captured` is the dict
    submit_sequence_specification writes into (key "sequence_json"); the
    caller reads it after the agent loop ends.
    """

    captured: dict[str, Any] = {}
    failed_validate_attempts = {"count": 0}

    @tool
    def read_functional_requirements() -> str:
        """Return this feature's real SRS functional requirements as JSON text."""
        return json.dumps(srs_json.get("functional_requirements", []), indent=2, default=str)

    @tool
    def read_acceptance_criteria() -> str:
        """Return this feature's real SRS acceptance criteria as JSON text."""
        return json.dumps(srs_json.get("acceptance_criteria", []), indent=2, default=str)

    @tool
    def read_interface_and_data_context() -> str:
        """Return the approved architecture plan's real API endpoints, request/response models, and data entities as JSON text."""
        return json.dumps(_interface_and_data_context(architecture_plan_json), indent=2, default=str)

    @tool
    def validate_sequence_draft(specification_json: str) -> str:
        """Validate a draft sequence_specification_json (as a JSON string) and return "VALID" or the exact validation errors to fix."""
        try:
            draft = json.loads(specification_json)
        except json.JSONDecodeError as error:
            return f"Invalid JSON: {error}"

        if not isinstance(draft, dict):
            return "Draft must be a JSON object."

        try:
            sequence_diagram_json = sequence_modeler.build(
                srs_json=srs_json,
                sds_json=architecture_plan_json,
                sequence_specification_json=draft,
            )
            sequence_validator.validate(srs_json, sequence_diagram_json)
        except SequenceDiagramValidationError as error:
            failed_validate_attempts["count"] += 1
            message = str(error)
            if failed_validate_attempts["count"] >= VALIDATE_NUDGE_THRESHOLD:
                message += (
                    " -- further validation attempts are unlikely to help; submit your "
                    "current best draft now via submit_sequence_specification."
                )
            return message
        except Exception as error:
            return f"Could not build/validate this draft: {error}"

        return "VALID"

    @tool
    def submit_sequence_specification(specification_json: str) -> str:
        """Submit your final sequence_specification_json (as a JSON string) exactly once, when confident."""
        captured["sequence_json"] = specification_json
        return "Sequence specification submitted."

    return [
        read_functional_requirements,
        read_acceptance_criteria,
        read_interface_and_data_context,
        validate_sequence_draft,
        submit_sequence_specification,
    ], captured


def build_class_diagram_tools(
    srs_json: dict[str, Any],
    architecture_plan_json: dict[str, Any],
    sequence_specification_json: dict[str, Any],
    class_modeler: Any,
    class_validator: Any,
) -> tuple[list[BaseTool], dict[str, Any]]:
    """
    Build the dedicated class-diagram generation tools.

    `sequence_specification_json` is the already-finalized sequence
    specification for this same feature -- exposed via
    read_finalized_sequence_names so the class step can reuse its exact
    Controller/Service/Boundary names instead of inventing its own, which is
    what structurally keeps the two diagrams consistent.

    Returns (tools, captured): `captured` is the dict
    submit_class_specification writes into (key "class_json"); the caller
    reads it after the agent loop ends.
    """

    captured: dict[str, Any] = {}
    failed_validate_attempts = {"count": 0}

    @tool
    def read_functional_requirements() -> str:
        """Return this feature's real SRS functional requirements as JSON text."""
        return json.dumps(srs_json.get("functional_requirements", []), indent=2, default=str)

    @tool
    def read_acceptance_criteria() -> str:
        """Return this feature's real SRS acceptance criteria as JSON text."""
        return json.dumps(srs_json.get("acceptance_criteria", []), indent=2, default=str)

    @tool
    def read_interface_and_data_context() -> str:
        """Return the approved architecture plan's real API endpoints, request/response models, and data entities as JSON text."""
        return json.dumps(_interface_and_data_context(architecture_plan_json), indent=2, default=str)

    @tool
    def read_finalized_sequence_names() -> str:
        """Return the finalized sequence diagram's participant names/types -- reuse these exact names for cross-diagram consistency."""
        participants = sequence_specification_json.get("participants", []) if isinstance(sequence_specification_json, dict) else []
        names = [
            {"name": participant.get("name"), "type": participant.get("type")}
            for participant in participants
            if isinstance(participant, dict)
        ]
        return json.dumps(names, indent=2, default=str)

    @tool
    def validate_class_draft(specification_json: str) -> str:
        """Validate a draft class_specification_json (as a JSON string) and return "VALID" or the exact validation errors to fix."""
        try:
            draft = json.loads(specification_json)
        except json.JSONDecodeError as error:
            return f"Invalid JSON: {error}"

        if not isinstance(draft, dict):
            return "Draft must be a JSON object."

        try:
            class_diagram_json = class_modeler.build(
                srs_json=srs_json,
                sds_json=architecture_plan_json,
                class_specification_json=draft,
            )
            class_validator.validate(srs_json, class_diagram_json)
        except ClassDiagramValidationError as error:
            failed_validate_attempts["count"] += 1
            message = str(error)
            if failed_validate_attempts["count"] >= VALIDATE_NUDGE_THRESHOLD:
                message += (
                    " -- further validation attempts are unlikely to help; submit your "
                    "current best draft now via submit_class_specification."
                )
            return message
        except Exception as error:
            return f"Could not build/validate this draft: {error}"

        return "VALID"

    @tool
    def submit_class_specification(specification_json: str) -> str:
        """Submit your final class_specification_json (as a JSON string) exactly once, when confident."""
        captured["class_json"] = specification_json
        return "Class specification submitted."

    return [
        read_functional_requirements,
        read_acceptance_criteria,
        read_interface_and_data_context,
        read_finalized_sequence_names,
        validate_class_draft,
        submit_class_specification,
    ], captured


def build_usecase_diagram_tools(
    srs_json: dict[str, Any],
    architecture_plan_json: dict[str, Any],
    usecase_modeler: Any,
    usecase_validator: Any,
) -> tuple[list[BaseTool], dict[str, Any]]:
    """
    Build the dedicated use-case-diagram generation tools -- gives use case diagrams the same
    agentic, tool-using reliability tier sequence/class diagrams already have (see
    build_sequence_diagram_tools/build_class_diagram_tools above), previously the one diagram
    type still stuck on the older single-shot-embedded-in-the-main-plan-call pipeline.

    Includes one tool the sequence/class toolsets don't need: read_user_roles_and_stories --
    actor stereotype/generalization and per-use-case participating_actors both need real SRS
    role/story context this feature's own read_functional_requirements/read_acceptance_criteria
    don't carry.

    Returns (tools, captured): `captured` is the dict submit_usecase_specification writes into
    (key "usecase_json"); the caller reads it after the agent loop ends.
    """

    captured: dict[str, Any] = {}
    failed_validate_attempts = {"count": 0}

    @tool
    def read_functional_requirements() -> str:
        """Return this feature's real SRS functional requirements as JSON text."""
        return json.dumps(srs_json.get("functional_requirements", []), indent=2, default=str)

    @tool
    def read_acceptance_criteria() -> str:
        """Return this feature's real SRS acceptance criteria as JSON text."""
        return json.dumps(srs_json.get("acceptance_criteria", []), indent=2, default=str)

    @tool
    def read_interface_and_data_context() -> str:
        """Return the approved architecture plan's real API endpoints, request/response models, and data entities as JSON text."""
        return json.dumps(_interface_and_data_context(architecture_plan_json), indent=2, default=str)

    @tool
    def read_user_roles_and_stories() -> str:
        """Return this feature's real SRS user_roles and user_stories as JSON text -- ground actor stereotype/generalization and per-use-case participating_actors in these."""
        return json.dumps(
            {
                "user_roles": srs_json.get("user_roles", []),
                "user_stories": srs_json.get("user_stories", []),
            },
            indent=2,
            default=str,
        )

    @tool
    def validate_usecase_draft(specification_json: str) -> str:
        """Validate a draft usecase_specification_json (as a JSON string) and return "VALID" or the exact validation errors to fix."""
        try:
            draft = json.loads(specification_json)
        except json.JSONDecodeError as error:
            return f"Invalid JSON: {error}"

        if not isinstance(draft, dict):
            return "Draft must be a JSON object."

        try:
            usecase_analysis_json, usecase_json = usecase_modeler.build(
                srs_json=srs_json,
                sds_json=architecture_plan_json,
                usecase_specification_json=draft,
            )
            usecase_validator.validate(srs_json, architecture_plan_json, usecase_analysis_json, usecase_json)
        except UseCaseValidationError as error:
            failed_validate_attempts["count"] += 1
            message = str(error)
            if failed_validate_attempts["count"] >= VALIDATE_NUDGE_THRESHOLD:
                message += (
                    " -- further validation attempts are unlikely to help; submit your "
                    "current best draft now via submit_usecase_specification."
                )
            return message
        except Exception as error:
            return f"Could not build/validate this draft: {error}"

        return "VALID"

    @tool
    def submit_usecase_specification(specification_json: str) -> str:
        """Submit your final usecase_specification_json (as a JSON string) exactly once, when confident."""
        captured["usecase_json"] = specification_json
        return "Use case specification submitted."

    return [
        read_functional_requirements,
        read_acceptance_criteria,
        read_interface_and_data_context,
        read_user_roles_and_stories,
        validate_usecase_draft,
        submit_usecase_specification,
    ], captured
