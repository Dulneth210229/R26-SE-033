"""
Architecture Agent.

Purpose:
- Load approved SRS JSON from Requirement Agent.
- Optionally load approved Enhanced SRS JSON from Domain Agent.
- Generate Architecture Plan JSON and usecase_specification_json using LLM.
- Derive UML Use Case, Sequence, and Class diagram models from SRS/Architecture Plan.
- Validate Architecture Plan coverage against SRS.
- Validate UML diagram quality.
- Convert Architecture Plan JSON into Markdown.
- Convert diagram JSON into PlantUML.
- Render PlantUML into PNG.
- Save all Architecture Agent artifacts.

Important:
This implementation does not generate:
- API contract JSON
- OpenAPI YAML
- code
- UI
- component diagram

This implementation now generates:
- use case diagram
- sequence diagram
- class diagram

Outputs:
- Architecture Plan Markdown
- Architecture Plan JSON
- Use Case Diagram PUML
- Use Case Diagram PNG
- Sequence Diagram PUML
- Sequence Diagram PNG
- Class Diagram PUML
- Class Diagram PNG
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from app.agents.architecture_agent.markdown_builder import ArchitecturePlanMarkdownBuilder
from app.agents.architecture_agent.revision_patcher import apply_architecture_revision_operations
from app.agents.architecture_agent.reviewer_note_builder import build_human_approval_note
from app.agents.architecture_agent.prompt import (
    ARCHITECTURE_AGENT_AGENTIC_SYSTEM_PROMPT,
    ARCHITECTURE_AGENT_SYSTEM_PROMPT,
    JSON_REPAIR_PROMPT,
    USECASE_REPAIR_SYSTEM_PROMPT,
    SEQUENCE_REPAIR_SYSTEM_PROMPT,
    CLASS_REPAIR_SYSTEM_PROMPT,
    SEQUENCE_DIAGRAM_AGENTIC_SYSTEM_PROMPT,
    CLASS_DIAGRAM_AGENTIC_SYSTEM_PROMPT,
    USECASE_DIAGRAM_AGENTIC_SYSTEM_PROMPT,
    DIAGRAM_FOCUSED_BOTH_SYSTEM_PROMPT,
    DIAGRAM_FOCUSED_CLASS_ONLY_SYSTEM_PROMPT,
    USECASE_DIAGRAM_FOCUSED_SYSTEM_PROMPT,
    build_agentic_architecture_user_prompt,
    build_architecture_user_prompt,
    build_architecture_plan_revision_prompt,
    build_json_repair_prompt,
    build_usecase_repair_prompt,
    build_sequence_repair_prompt,
    build_class_repair_prompt,
    build_sequence_diagram_user_prompt,
    build_class_diagram_user_prompt,
    build_usecase_diagram_user_prompt,
    build_diagram_focused_both_prompt,
    build_diagram_focused_class_only_prompt,
    build_usecase_diagram_focused_prompt,
    ARCHITECTURE_REVISION_SYSTEM_PROMPT,
)
from app.agents.architecture_agent.tools import build_architecture_planning_tools
from app.agents.architecture_agent.diagram_tools import (
    build_sequence_diagram_tools,
    build_class_diagram_tools,
    build_usecase_diagram_tools,
)
from app.agents.architecture_agent.schemas import (
    ArchitectureAgentInput,
    ArchitectureAgentOutput,
)
from app.agents.architecture_agent.sds_validator import (
    ArchitecturePlanValidator,
    ArchitecturePlanValidationError,
)
from app.agents.architecture_agent.usecase_modeler import ArchitectureUseCaseModeler
from app.agents.architecture_agent.usecase_builder import ArchitectureUseCasePlantUMLBuilder
from app.agents.architecture_agent.usecase_renderer import UseCaseDiagramRenderer
from app.agents.architecture_agent.usecase_validator import (
    UseCaseQualityValidator,
    UseCaseValidationError,
)
from app.agents.architecture_agent.sequence_modeler import ArchitectureSequenceModeler
from app.agents.architecture_agent.sequence_builder import ArchitectureSequencePlantUMLBuilder
from app.agents.architecture_agent.sequence_validator import (
    SequenceDiagramValidator,
    SequenceDiagramValidationError,
)
from app.agents.architecture_agent.class_modeler import ArchitectureClassModeler
from app.agents.architecture_agent.class_builder import ArchitectureClassPlantUMLBuilder
from app.agents.architecture_agent.class_validator import (
    ClassDiagramValidator,
    ClassDiagramValidationError,
)
from app.core.enums import (
    AgentName,
    ApprovalStatus,
    ArtifactFormat,
    ArtifactType,
    FeatureStatus,
)
from app.schemas.agent_schema import AgentRunResponse
from app.schemas.architecture_schema import (
    ArchitectureAgentRunRequest,
    ArchitectureAgentReviseRequest,
)
from app.providers.agentic_model_factory import get_agentic_chat_model
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.services.llm_provider_service import llm_provider_service
from app.services.project_memory_service import project_memory_service
from app.utils.file_manager import read_json_file, write_json_file, write_text_file
from app.utils.id_generator import generate_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Same rationale (and same value) as the Coder Agent's revision planner:
# read-only exploration is cheap, this exists only so a model that never
# calls submit_architecture_plan can't loop forever. Hitting it is a
# recoverable failure -- generation falls back to the single-shot rung.
ARCHITECTURE_PLANNING_RECURSION_LIMIT = 80

# Mirrors CoderAgent._plan_with_retries' MAX_PLANNING_ATTEMPTS idiom: a
# small, cheap, TARGETED repair loop for a use case specification that fails
# quality validation -- fixes only the flagged issues, without re-running
# the entire architecture-plan generation.
MAX_USECASE_REPAIR_ATTEMPTS = 2

# Same idiom, fully independent repair loops for the sequence and class
# diagram specifications -- never share state or calls with the use-case
# repair loop above.
MAX_SEQUENCE_REPAIR_ATTEMPTS = 2
MAX_CLASS_REPAIR_ATTEMPTS = 2

# Recursion limits for the three dedicated diagram-generation agentic loops.
# Smaller than ARCHITECTURE_PLANNING_RECURSION_LIMIT because each loop
# covers one narrow artifact (read context once or twice, draft, validate,
# fix, submit) rather than a whole architecture plan -- treat these as a
# hypothesis validated by real E2E runs, not a settled number.
SEQUENCE_DIAGRAM_RECURSION_LIMIT = 20
CLASS_DIAGRAM_RECURSION_LIMIT = 20
USECASE_DIAGRAM_RECURSION_LIMIT = 20

# Matches a single per-field SRS `data_requirements` string, e.g.
# "price (number, required, minimum value 0.01)" -> ("price", "number, required, minimum
# value 0.01"). requirement_schema.py documents data_requirements as "the concrete fields of
# ONE coherent entity" -- this is what lets the deterministic fallback below parse a real field
# name/type/required-ness out of each item instead of (the real bug this fixes) treating every
# item as its own separate entity.
DATA_FIELD_DEFINITION_PATTERN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)")

# Matches a single per-endpoint SRS `api_expectations` string, e.g. "POST /api/items" ->
# ("POST", "/api/items"). Without this, every endpoint silently defaulted to GET (a real,
# confirmed bug: 4 distinct CRUD endpoints collapsed into 4 duplicate GETs).
API_ENDPOINT_DEFINITION_PATTERN = re.compile(
    r"^\s*(GET|POST|PUT|PATCH|DELETE)\s+(\S+)", re.IGNORECASE
)


class ArchitectureAgent:
    """
    Main Architecture Agent class.

    This class controls:
    1. Approved input artifact loading.
    2. LLM architecture generation.
    3. Architecture Plan validation.
    4. UML use case, sequence, and class diagram validation.
    5. Architecture Plan Markdown generation.
    6. PlantUML generation.
    7. PNG rendering.
    8. Artifact saving.
    """

    REQUIRED_TOP_LEVEL_KEYS = [
        "architecture_plan_json",
    ]

    # NOTE: implementation_plan is deliberately NOT in this list. The prompt
    # requires the LLM to produce it, but presence is guaranteed by
    # _ensure_implementation_plan (mechanical synthesis from design_views/SRS
    # when the LLM omitted it, and for every legacy/fallback plan), so an
    # otherwise-good LLM plan is never discarded just for missing it.
    REQUIRED_ARCHITECTURE_PLAN_KEYS = [
        "document_control",
        "feature_overview",
        "requirement_interpretation",
        "architecture_approach",
        "design_views",
        "frontend_architecture_plan",
        "backend_architecture_plan",
        "validation_plan",
        "coder_implementation_tasks",
        "traceability_matrix",
        "assumptions",
        "constraints",
        "risks",
        "dependencies",
        "human_approval_note",
    ]

    REQUIRED_DESIGN_VIEW_KEYS = [
        "context_view",
        "logical_view",
        "interface_view",
        "data_view",
        "behavior_view",
        "error_handling_view",
        "security_authorization_view",
        "quality_attributes_view",
    ]

    REQUIRED_USECASE_KEYS = [
        "system_boundary",
        "diagram_title",
        "actors",
        "use_cases",
        "relationships",
        "notes",
    ]

    REQUIRED_IMPLEMENTATION_PLAN_KEYS = [
        "backend",
        "frontend",
        "implementation_order",
        "constraints",
    ]

    def __init__(self):
        """
        Initialize Architecture Agent helpers.

        These helpers are Architecture-Agent-specific.
        No common/shared files are changed.
        """

        self.markdown_builder = ArchitecturePlanMarkdownBuilder()
        self.architecture_plan_validator = ArchitecturePlanValidator()

        # Use Case pipeline:
        # LLM/specification -> modeler -> validator -> PlantUML builder -> PNG renderer
        self.usecase_modeler = ArchitectureUseCaseModeler()
        self.usecase_builder = ArchitectureUseCasePlantUMLBuilder()
        self.usecase_validator = UseCaseQualityValidator()

        # Sequence diagram pipeline:
        # SRS/Architecture Plan -> modeler -> validator -> PlantUML builder -> PNG renderer
        self.sequence_modeler = ArchitectureSequenceModeler()
        self.sequence_builder = ArchitectureSequencePlantUMLBuilder()
        self.sequence_validator = SequenceDiagramValidator()

        # Class diagram pipeline:
        # SRS/Architecture Plan -> modeler -> validator -> PlantUML builder -> PNG renderer
        self.class_modeler = ArchitectureClassModeler()
        self.class_builder = ArchitectureClassPlantUMLBuilder()
        self.class_validator = ClassDiagramValidator()

        # Existing renderer can render any PlantUML file into PNG.
        self.diagram_renderer = UseCaseDiagramRenderer()

    async def run(self, feature_id: str, request: ArchitectureAgentRunRequest) -> AgentRunResponse:
        """
        Run Architecture Agent for one feature.

        Rule:
            Architecture Agent can only run after Requirement Agent SRS JSON
            is approved by a human.
        """

        logger.info("Architecture Agent started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)

        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])

        if not project:
            raise ValueError("Project not found for this feature.")

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.JSON
        )

        if not srs_artifact:
            raise ValueError(
                "No approved SRS JSON artifact found. "
                "Approve Requirement Agent SRS JSON before running Architecture Agent."
            )

        srs_json = read_json_file(srs_artifact["file_path"])

        enhanced_srs_json = None

        if request.use_enhanced_srs_if_available:
            enhanced_srs_artifact = self._find_latest_approved_artifact(
                feature_id=feature_id,
                artifact_type=ArtifactType.ENHANCED_SRS,
                artifact_format=ArtifactFormat.JSON
            )

            if enhanced_srs_artifact:
                enhanced_srs_json = read_json_file(enhanced_srs_artifact["file_path"])

        feature["feature_status"] = FeatureStatus.IN_PROGRESS
        feature["current_agent"] = AgentName.ARCHITECTURE

        previous_architecture_plans = self._load_previous_architecture_plans(
            project_id=feature["project_id"],
            exclude_feature_id=feature_id,
        )
        project_manifest_json = project_memory_service.load_project_manifest(feature["project_id"])

        agent_input = ArchitectureAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_notes=request.architecture_notes,
            human_comment=request.human_comment,
            previous_architecture_plans=previous_architecture_plans,
            project_manifest_json=project_manifest_json,
        )

        output = await self._generate_architecture_output(agent_input)

        artifact_ids = self._save_architecture_artifacts(
            project=dict(project),
            feature=dict(feature),
            output=output
        )

        logger.info(
            "Architecture Agent completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids
        )

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.ARCHITECTURE,
            status="completed",
            message=(
                "Architecture Agent completed successfully. "
                "Architecture Plan, Use Case Diagram, Sequence Diagram, and Class Diagram artifacts were generated. "
                "Human approval is required before UI/UX Agent or Coder Agent can run."
            ),
            artifact_ids=artifact_ids
        )

    async def run_stream(self, feature_id: str, request: ArchitectureAgentRunRequest):
        """
        Streaming variant of run() -- same NDJSON event shape as DomainAgent.run_stream/
        RequirementAgent.revise_stream (see those methods' own docstrings): the architecture
        plan JSON "types" in live instead of a blocking wait.

        Deliberately NOT a thin wrapper around _generate_architecture_output's existing ladder:
        that ladder's FIRST rung (_generate_raw_output_via_exploration) is an agentic,
        tool-calling loop -- the plan text only ever exists as arguments to a final tool call, not
        as incremental tokens, so there is no stream to forward from it. This method instead
        starts directly at the single-shot rung (the one _generate_architecture_output falls back
        to on any exploration failure) and streams THAT LLM call; diagram generation also skips
        its own agentic tier (attempt_agentic=False) for the same reason revise() already does
        ("a human is synchronously waiting", see _complete_diagram_models' own docstring) -- this
        is the live, responsive path. The full agentic-exploration-first ladder remains completely
        unchanged and reachable via the non-streaming run() (still used by POST /architecture/run,
        kept reachable in the UI as an explicit "deep exploration mode" -- see
        ArchitectureAgentChat.jsx) for whoever wants the more thorough but much slower and
        non-live path.

        Events:
            {"type": "token", "text": "..."}
            {"type": "phase", "phase": "...", "label": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "message": "..."}
        """

        logger.info("Architecture Agent (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id, artifact_type=ArtifactType.SRS, artifact_format=ArtifactFormat.JSON
        )
        if not srs_artifact:
            yield {
                "type": "error",
                "message": (
                    "No approved SRS JSON artifact found. "
                    "Approve Requirement Agent SRS JSON before running Architecture Agent."
                ),
            }
            return

        srs_json = read_json_file(srs_artifact["file_path"])

        enhanced_srs_json = None
        if request.use_enhanced_srs_if_available:
            enhanced_srs_artifact = self._find_latest_approved_artifact(
                feature_id=feature_id, artifact_type=ArtifactType.ENHANCED_SRS, artifact_format=ArtifactFormat.JSON
            )
            if enhanced_srs_artifact:
                enhanced_srs_json = read_json_file(enhanced_srs_artifact["file_path"])

        feature["feature_status"] = FeatureStatus.IN_PROGRESS
        feature["current_agent"] = AgentName.ARCHITECTURE

        previous_architecture_plans = self._load_previous_architecture_plans(
            project_id=feature["project_id"],
            exclude_feature_id=feature_id,
        )
        project_manifest_json = project_memory_service.load_project_manifest(feature["project_id"])

        agent_input = ArchitectureAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_notes=request.architecture_notes,
            human_comment=request.human_comment,
            previous_architecture_plans=previous_architecture_plans,
            project_manifest_json=project_manifest_json,
        )

        provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)
        srs_for_generation = agent_input.enhanced_srs_json or agent_input.srs_json
        feature_name = agent_input.feature.get("feature_name", "Feature")

        prompt = build_architecture_user_prompt(
            project=agent_input.project,
            feature=agent_input.feature,
            srs_json=agent_input.srs_json,
            enhanced_srs_json=agent_input.enhanced_srs_json,
            architecture_notes=agent_input.architecture_notes,
            human_comment=agent_input.human_comment,
            previous_architecture_plans=agent_input.previous_architecture_plans,
            project_manifest_json=agent_input.project_manifest_json,
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=ARCHITECTURE_AGENT_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed Architecture Plan generation failed mid-stream for feature_id=%s: %s",
                feature_id,
                stream_error,
            )

        raw_output = "".join(raw_chunks)

        yield {"type": "phase", "phase": "validating", "label": "Validating the architecture plan..."}

        try:
            parsed = self._parse_and_validate_output(raw_output, srs_for_generation, feature_name)

        except Exception as first_error:
            logger.warning("Streamed Architecture output validation failed: %s", first_error)

            repair_prompt = build_json_repair_prompt(raw_output)
            # A transport/timeout failure from this call itself (e.g. an httpx.ReadTimeout, whose
            # str() is frequently empty) must be treated exactly like an unparseable repair
            # response -- never left to propagate uncaught, or the whole request crashes with a
            # blank error message instead of falling through to the deterministic fallback below.
            try:
                repaired_output = await provider.invoke_agent([
                    {"role": "system", "content": JSON_REPAIR_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ])
            except Exception as repair_call_error:
                logger.warning(
                    "Streamed Architecture JSON repair call itself failed (not just its output) "
                    "for feature_id=%s: %s", feature_id, repair_call_error,
                )
                repaired_output = ""

            try:
                parsed = self._parse_and_validate_output(repaired_output, srs_for_generation, feature_name)
                raw_output = repaired_output

            except Exception as second_error:
                logger.warning("Streamed Architecture JSON repair failed: %s", second_error)

                parsed = self._build_fallback_architecture_output(
                    agent_input=agent_input, reason=str(second_error)
                )
                raw_output = json.dumps(parsed, indent=2, default=str)

        yield {"type": "phase", "phase": "usecase", "label": "Building the use case model..."}
        # attempt_agentic=False -- same rationale _complete_diagram_models'
        # own call right below already applies: a human is synchronously
        # watching this stream, so skip the expensive agentic tool-using
        # tier and go straight to whatever the main plan call already
        # embedded (still real, feature-grounded content, not a template).
        parsed = await self._complete_usecase_model(agent_input, parsed, attempt_agentic=False)

        yield {"type": "phase", "phase": "diagrams", "label": "Generating sequence and class diagrams..."}
        # attempt_agentic=False, no diagram_generation_state -- same rationale
        # _complete_diagram_models' own docstring already gives for revise():
        # a human is synchronously watching this stream, so skip the
        # expensive agentic tool-using tier and go straight to the focused,
        # feature-grounded single-shot tier.
        parsed = await self._complete_diagram_models(agent_input, parsed, None, attempt_agentic=False)

        try:
            self._validate_full_output(agent_input, parsed)
        except Exception as validation_error:
            logger.warning(
                "Streamed Architecture output failed final validation for feature_id=%s "
                "-- proceeding anyway for human review: %s",
                feature_id,
                validation_error,
            )
            parsed["architecture_plan_json"]["human_approval_note"] = build_human_approval_note(
                parsed["architecture_plan_json"].get("human_approval_note", ""),
                validation_error,
            )

        output = self._build_output_from_parsed(parsed, raw_output=raw_output)

        yield {"type": "phase", "phase": "rendering", "label": "Rendering diagram images and saving artifacts..."}

        # _save_architecture_artifacts makes blocking subprocess.run PlantUML/JVM calls -- run it
        # off the event loop so those seconds don't stall this still-open NDJSON stream.
        artifact_ids = await asyncio.to_thread(
            self._save_architecture_artifacts,
            project=dict(project),
            feature=dict(feature),
            output=output,
        )

        logger.info(
            "Architecture Agent (streamed) completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": (
                "Architecture Agent completed successfully. "
                "Architecture Plan, Use Case Diagram, Sequence Diagram, and Class Diagram artifacts were generated. "
                "Human approval is required before UI/UX Agent or Coder Agent can run."
            ),
        }

    async def _generate_architecture_output(self, agent_input: ArchitectureAgentInput) -> ArchitectureAgentOutput:
        """
        Generate Architecture Agent output.

        Flow:
        1. Ask LLM for JSON only.
        2. Parse and validate JSON structure.
        3. Validate Architecture Plan against approved SRS.
        4. Build and validate use case, sequence, and class diagrams.
        5. If LLM output is invalid, repair once.
        6. If still invalid, build dynamic IEEE-style fallback from SRS.
        7. Convert Architecture Plan JSON to Markdown.
        8. Convert diagram JSON models to PlantUML.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)

        srs_for_generation = agent_input.enhanced_srs_json or agent_input.srs_json
        feature_name = agent_input.feature.get("feature_name", "Feature")

        # Threaded through every _complete_diagram_models call in this
        # method (all of which get attempt_agentic=True, the default) so
        # the expensive agentic diagram tier is attempted AT MOST ONCE per
        # run() call, however many rungs cascade -- and so a successful
        # result is reused for free on a later rung instead of discarded.
        diagram_generation_state: dict[str, Any] = {}

        # Rung 0 (primary): agentic, tool-using, project-aware exploration --
        # the model reads previous features' approved plans / the project
        # manifest / the real workspace before submitting its plan. Any
        # failure here (turn limit, no submission, parse or validation
        # failure) falls through to the battle-tested single-shot ->
        # repair -> deterministic-fallback ladder below, which is never
        # replaced -- only preceded.
        try:
            exploration_output = await self._generate_raw_output_via_exploration(agent_input)
            parsed = self._parse_and_validate_output(exploration_output, srs_for_generation, feature_name)
            parsed = await self._complete_usecase_model(agent_input, parsed, diagram_generation_state)
            parsed = await self._complete_diagram_models(agent_input, parsed, diagram_generation_state)
            self._validate_full_output(agent_input, parsed)

            return self._build_output_from_parsed(parsed, raw_output=exploration_output)

        except Exception as exploration_error:
            logger.warning(
                "Agentic architecture exploration failed for feature_id=%s -- "
                "falling back to single-shot generation: %s",
                agent_input.feature.get("feature_id"),
                exploration_error,
            )

        prompt = build_architecture_user_prompt(
            project=agent_input.project,
            feature=agent_input.feature,
            srs_json=agent_input.srs_json,
            enhanced_srs_json=agent_input.enhanced_srs_json,
            architecture_notes=agent_input.architecture_notes,
            human_comment=agent_input.human_comment,
            previous_architecture_plans=agent_input.previous_architecture_plans,
            project_manifest_json=agent_input.project_manifest_json,
        )

        # A transport/timeout failure from invoke_agent() itself (e.g. an httpx.ReadTimeout, whose
        # str() is frequently empty) must be treated exactly like an unparseable response -- never
        # left to propagate uncaught, or this whole rung crashes with a blank error message instead
        # of falling through to repair/fallback like every other failure mode already does.
        try:
            raw_output = await provider.invoke_agent([
                {
                    "role": "system",
                    "content": ARCHITECTURE_AGENT_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ])
        except Exception as invoke_error:
            logger.warning(
                "Architecture single-shot generation call itself failed (not just its output) "
                "for feature_id=%s: %s", agent_input.feature.get("feature_id"), invoke_error,
            )
            raw_output = ""

        try:
            parsed = self._parse_and_validate_output(raw_output, srs_for_generation, feature_name)
            parsed = await self._complete_usecase_model(agent_input, parsed, diagram_generation_state)
            parsed = await self._complete_diagram_models(agent_input, parsed, diagram_generation_state)
            self._validate_full_output(agent_input, parsed)

        except Exception as first_error:
            logger.warning("Architecture output validation failed: %s", first_error)

            repair_prompt = build_json_repair_prompt(raw_output)

            try:
                repaired_output = await provider.invoke_agent([
                    {
                        "role": "system",
                        "content": JSON_REPAIR_PROMPT
                    },
                    {
                        "role": "user",
                        "content": repair_prompt
                    }
                ])
            except Exception as repair_call_error:
                logger.warning(
                    "Architecture JSON repair call itself failed (not just its output) for "
                    "feature_id=%s: %s", agent_input.feature.get("feature_id"), repair_call_error,
                )
                repaired_output = ""

            try:
                parsed = self._parse_and_validate_output(repaired_output, srs_for_generation, feature_name)
                parsed = await self._complete_usecase_model(agent_input, parsed, diagram_generation_state)
                parsed = await self._complete_diagram_models(agent_input, parsed, diagram_generation_state)
                self._validate_full_output(agent_input, parsed)
                raw_output = repaired_output

            except Exception as second_error:
                logger.warning("Architecture JSON repair failed: %s", second_error)

                parsed = self._build_fallback_architecture_output(
                    agent_input=agent_input,
                    reason=str(second_error)
                )
                # The plan text itself already needed the deterministic
                # fallback (the model failed at least twice) -- this is
                # supposed to be the fast, reliable safety net, so this
                # rung skips BOTH the expensive agentic tier AND the
                # focused single-shot fallback for the use case model
                # (attempt_agentic=False, attempt_focused_fallback left at
                # its default False -- making yet another LLM call from the
                # rung whose whole purpose is "the LLM already failed
                # twice" would defeat its purpose, same rationale the
                # pre-existing repair loop below already uses). Still reuses
                # a cached result from an earlier rung's successful agentic
                # attempt via diagram_generation_state, if one exists.
                # Diagrams keep their own existing focused-fallback tier
                # unconditionally, per _complete_diagram_models' own design.
                parsed = await self._complete_usecase_model(
                    agent_input, parsed, diagram_generation_state, attempt_agentic=False,
                )
                parsed = await self._complete_diagram_models(
                    agent_input, parsed, diagram_generation_state, attempt_agentic=False
                )

                # The fallback is generated deterministically from the approved SRS, so it
                # should normally pass -- but it is still built from LLM-authored diagram
                # content (use case/sequence/class models), so it can still fail a heuristic
                # validator on a genuinely ambiguous edge case. This is the last resort: there
                # is no further fallback to try, and this whole feature blocks the UI/UX and
                # Coder Agents until an Architecture Plan exists for a human to review. Rather
                # than crash the entire run over a heuristic-validator false positive (or a
                # genuinely borderline case a human can judge in seconds), record the failure
                # plainly on the plan itself and let it through for human review -- mirrors the
                # Coder Agent's "proceed anyway with verification_passed=False" precedent.
                try:
                    self._validate_full_output(agent_input, parsed)
                except Exception as third_error:
                    logger.warning(
                        "Architecture fallback output also failed validation for feature_id=%s "
                        "-- proceeding anyway for human review: %s",
                        agent_input.feature.get("feature_id"),
                        third_error,
                    )
                    parsed["architecture_plan_json"]["human_approval_note"] = build_human_approval_note(
                        parsed["architecture_plan_json"].get("human_approval_note", ""),
                        third_error,
                        context="even on the deterministic SRS-derived fallback",
                    )

                raw_output = json.dumps(parsed, indent=2, default=str)

        return self._build_output_from_parsed(parsed, raw_output=raw_output)

    def _build_output_from_parsed(
        self, parsed: dict[str, Any], raw_output: str
    ) -> ArchitectureAgentOutput:
        """
        Build the final ArchitectureAgentOutput (markdown + PlantUML) from a
        fully-completed, validated `parsed` dict -- shared by every
        generation rung (agentic exploration, single-shot, repair, fallback).
        """

        architecture_plan_json = parsed["architecture_plan_json"]
        usecase_analysis_json = parsed["usecase_analysis_json"]
        usecase_json = parsed["usecase_json"]
        sequence_diagram_json = parsed["sequence_diagram_json"]
        class_diagram_json = parsed["class_diagram_json"]

        architecture_plan_markdown = self.markdown_builder.build(architecture_plan_json)
        usecase_puml = self.usecase_builder.build(usecase_json)
        sequence_puml = self.sequence_builder.build(sequence_diagram_json)
        class_puml = self.class_builder.build(class_diagram_json)

        return ArchitectureAgentOutput(
            architecture_plan_json=architecture_plan_json,
            architecture_plan_markdown=architecture_plan_markdown,
            usecase_analysis_json=usecase_analysis_json,
            usecase_json=usecase_json,
            usecase_puml=usecase_puml,
            sequence_diagram_json=sequence_diagram_json,
            sequence_puml=sequence_puml,
            class_diagram_json=class_diagram_json,
            class_puml=class_puml,
            raw_llm_output=raw_output
        )

    async def _generate_raw_output_via_exploration(
        self, agent_input: ArchitectureAgentInput
    ) -> str:
        """
        Agentic (tool-using) generation rung: the model explores previous
        features' approved plans, the project manifest, and the real
        workspace with read-only tools, then submits its full output via
        submit_architecture_plan -- mirroring the Coder Agent's proven
        generate_via_exploration pattern.

        Returns the submitted raw JSON string; raises if the loop ended
        (normally or via the recursion limit) without a submission -- the
        caller treats any raise as "fall back to the single-shot rung".
        """

        tools, captured = build_architecture_planning_tools(
            project_id=agent_input.project.get("project_id", ""),
            previous_architecture_plans=agent_input.previous_architecture_plans,
        )

        agent = create_agent(
            model=get_agentic_chat_model(agent_name=AgentName.ARCHITECTURE.value),
            tools=tools,
            system_prompt=ARCHITECTURE_AGENT_AGENTIC_SYSTEM_PROMPT,
        )

        user_prompt = build_agentic_architecture_user_prompt(
            project=agent_input.project,
            feature=agent_input.feature,
            srs_json=agent_input.srs_json,
            enhanced_srs_json=agent_input.enhanced_srs_json,
            architecture_notes=agent_input.architecture_notes,
            human_comment=agent_input.human_comment,
            previous_architecture_plans=agent_input.previous_architecture_plans,
            project_manifest_json=agent_input.project_manifest_json,
        )

        try:
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]},
                config={"recursion_limit": ARCHITECTURE_PLANNING_RECURSION_LIMIT},
            )
        except GraphRecursionError:
            pass  # handled uniformly below -- "plan_json" simply won't be captured

        if "plan_json" not in captured:
            raise ValueError(
                "Agentic architecture exploration ended without calling "
                "submit_architecture_plan (stopped early or hit the exploration "
                f"turn limit of {ARCHITECTURE_PLANNING_RECURSION_LIMIT})."
            )

        return captured["plan_json"]

    async def _generate_sequence_diagram_via_exploration(
        self,
        agent_input: ArchitectureAgentInput,
        architecture_plan_json: dict[str, Any],
        feature_name: str,
    ) -> dict[str, Any]:
        """
        Dedicated, narrow agentic (tool-using) generation step for JUST the
        sequence diagram specification -- mirrors
        _generate_raw_output_via_exploration's exact create_agent/ainvoke/
        GraphRecursionError pattern, but scoped to one small artifact
        instead of the whole architecture plan, with dedicated read tools
        grounding it in this feature's real SRS/plan content plus a
        validate-in-the-loop tool for proactive self-correction.

        Returns the parsed sequence_specification_json dict; raises if the
        loop ended without a submission -- the caller falls through to the
        focused single-shot tier.
        """

        srs_for_modeling = agent_input.enhanced_srs_json or agent_input.srs_json

        tools, captured = build_sequence_diagram_tools(
            srs_json=srs_for_modeling,
            architecture_plan_json=architecture_plan_json,
            sequence_modeler=self.sequence_modeler,
            sequence_validator=self.sequence_validator,
        )

        agent = create_agent(
            model=get_agentic_chat_model(agent_name=AgentName.ARCHITECTURE.value),
            tools=tools,
            system_prompt=SEQUENCE_DIAGRAM_AGENTIC_SYSTEM_PROMPT,
        )

        user_prompt = build_sequence_diagram_user_prompt(feature_name)

        try:
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]},
                config={"recursion_limit": SEQUENCE_DIAGRAM_RECURSION_LIMIT},
            )
        except GraphRecursionError:
            pass  # handled uniformly below -- "sequence_json" simply won't be captured

        if "sequence_json" not in captured:
            raise ValueError(
                "Sequence diagram exploration ended without calling "
                "submit_sequence_specification (stopped early or hit the "
                f"exploration turn limit of {SEQUENCE_DIAGRAM_RECURSION_LIMIT})."
            )

        parsed = self._extract_json_object(captured["sequence_json"])
        if not isinstance(parsed, dict):
            raise ValueError("Submitted sequence specification was not a JSON object.")

        return parsed

    async def _generate_class_diagram_via_exploration(
        self,
        agent_input: ArchitectureAgentInput,
        architecture_plan_json: dict[str, Any],
        feature_name: str,
        sequence_specification_json: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Same shape as _generate_sequence_diagram_via_exploration, for the
        class diagram specification. Only ever called after the sequence
        step has already succeeded -- its read_finalized_sequence_names
        tool is what structurally keeps the two diagrams' naming
        consistent, rather than hoping a shared prompt keeps them in sync.
        """

        srs_for_modeling = agent_input.enhanced_srs_json or agent_input.srs_json

        tools, captured = build_class_diagram_tools(
            srs_json=srs_for_modeling,
            architecture_plan_json=architecture_plan_json,
            sequence_specification_json=sequence_specification_json,
            class_modeler=self.class_modeler,
            class_validator=self.class_validator,
        )

        agent = create_agent(
            model=get_agentic_chat_model(agent_name=AgentName.ARCHITECTURE.value),
            tools=tools,
            system_prompt=CLASS_DIAGRAM_AGENTIC_SYSTEM_PROMPT,
        )

        user_prompt = build_class_diagram_user_prompt(feature_name)

        try:
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]},
                config={"recursion_limit": CLASS_DIAGRAM_RECURSION_LIMIT},
            )
        except GraphRecursionError:
            pass  # handled uniformly below -- "class_json" simply won't be captured

        if "class_json" not in captured:
            raise ValueError(
                "Class diagram exploration ended without calling "
                "submit_class_specification (stopped early or hit the "
                f"exploration turn limit of {CLASS_DIAGRAM_RECURSION_LIMIT})."
            )

        parsed = self._extract_json_object(captured["class_json"])
        if not isinstance(parsed, dict):
            raise ValueError("Submitted class specification was not a JSON object.")

        return parsed

    async def _generate_usecase_diagram_via_exploration(
        self,
        agent_input: ArchitectureAgentInput,
        architecture_plan_json: dict[str, Any],
        feature_name: str,
    ) -> dict[str, Any]:
        """
        Dedicated, narrow agentic (tool-using) generation step for JUST the use case diagram
        specification -- exact structural mirror of _generate_sequence_diagram_via_exploration/
        _generate_class_diagram_via_exploration, gives use case diagrams the same reliability
        tier the other two already had (previously the one diagram type still stuck on the older
        single-shot-embedded-in-the-main-plan-call pipeline, with zero LLM involvement at all on
        every revise() call -- see _complete_usecase_model's own docstring for the full fix).

        Returns the parsed usecase_specification_json dict; raises if the loop ended without a
        submission -- the caller falls through to whatever the main plan call already produced,
        or the focused single-shot fallback.
        """

        srs_for_modeling = agent_input.enhanced_srs_json or agent_input.srs_json

        tools, captured = build_usecase_diagram_tools(
            srs_json=srs_for_modeling,
            architecture_plan_json=architecture_plan_json,
            usecase_modeler=self.usecase_modeler,
            usecase_validator=self.usecase_validator,
        )

        agent = create_agent(
            model=get_agentic_chat_model(agent_name=AgentName.ARCHITECTURE.value),
            tools=tools,
            system_prompt=USECASE_DIAGRAM_AGENTIC_SYSTEM_PROMPT,
        )

        user_prompt = build_usecase_diagram_user_prompt(feature_name)

        try:
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]},
                config={"recursion_limit": USECASE_DIAGRAM_RECURSION_LIMIT},
            )
        except GraphRecursionError:
            pass  # handled uniformly below -- "usecase_json" simply won't be captured

        if "usecase_json" not in captured:
            raise ValueError(
                "Use case diagram exploration ended without calling "
                "submit_usecase_specification (stopped early or hit the "
                f"exploration turn limit of {USECASE_DIAGRAM_RECURSION_LIMIT})."
            )

        parsed = self._extract_json_object(captured["usecase_json"])
        if not isinstance(parsed, dict):
            raise ValueError("Submitted use case specification was not a JSON object.")

        return parsed

    async def _complete_diagram_models(
        self,
        agent_input: ArchitectureAgentInput,
        parsed: dict[str, Any],
        diagram_generation_state: dict[str, Any] | None = None,
        attempt_agentic: bool = True,
    ) -> dict[str, Any]:
        """
        Populate parsed["sequence_specification_json"]/
        parsed["class_specification_json"] via a dedicated, narrow
        generation mechanism -- fully decoupled from however
        parsed["architecture_plan_json"] itself was produced -- then hand
        off to the existing _complete_sequence_model/_complete_class_model
        (unchanged internally) for modeling and the existing reactive
        repair loop.

        Three tiers, most-dynamic first: (1) two SEQUENTIAL agentic
        tool-using loops (sequence, then class informed by the finalized
        sequence names -- this ordering is what structurally keeps the two
        diagrams' naming consistent, not a hoped-for prompt convention);
        (2) a focused, non-agentic single-shot call for whichever
        specification(s) are still missing (both together if the sequence
        agentic step itself failed, since there's nothing meaningful yet to
        keep class consistent with; class-only, with the finalized sequence
        embedded, if only class failed); (3) the existing deterministic
        fallback inside the modelers themselves, reached only if both above
        produce nothing.

        `diagram_generation_state` is a plain dict the CALLER creates once
        and threads through every call within one run()/revise() invocation
        (unlike `parsed`, which is recreated fresh at each ladder rung, so
        memoizing inside `parsed` would not survive a rung cascade). It
        caches whether the agentic tier has already been attempted this
        invocation (so a diagram-specific validation failure on one rung
        cannot re-trigger a fresh ~20-40 turn agentic attempt from every
        subsequent rung) AND caches a successful agentic result outright, so
        a later rung reuses it for free instead of regenerating anything.
        Pass `None` for a single-invocation caller (the deterministic
        fallback rung, revise()) where cross-rung memoization does not
        apply.

        `attempt_agentic=False` skips tier 1 entirely -- used for the
        deterministic-fallback rung and revise(), where the plan itself
        already needed its own fallback / a human is synchronously waiting,
        so a potentially long agentic diagram attempt is a poor trade; they
        still get real, feature-grounded content via tier 2 instead of a
        fixed template.
        """

        if diagram_generation_state is None:
            diagram_generation_state = {}

        architecture_plan_json = parsed["architecture_plan_json"]
        feature_name = agent_input.feature.get("feature_name", "Feature")
        srs_for_modeling = agent_input.enhanced_srs_json or agent_input.srs_json
        feature_id = agent_input.feature.get("feature_id")

        sequence_specification_json: dict[str, Any] = diagram_generation_state.get(
            "sequence_specification_json"
        ) or {}
        class_specification_json: dict[str, Any] = diagram_generation_state.get(
            "class_specification_json"
        ) or {}

        if (
            attempt_agentic
            and not diagram_generation_state.get("attempted")
            and not (sequence_specification_json and class_specification_json)
        ):
            diagram_generation_state["attempted"] = True

            try:
                sequence_specification_json = await self._generate_sequence_diagram_via_exploration(
                    agent_input, architecture_plan_json, feature_name,
                )
                diagram_generation_state["sequence_specification_json"] = sequence_specification_json
            except Exception as error:
                logger.warning(
                    "Agentic sequence diagram exploration failed for feature_id=%s: %s",
                    feature_id, error,
                )

            if sequence_specification_json:
                try:
                    class_specification_json = await self._generate_class_diagram_via_exploration(
                        agent_input, architecture_plan_json, feature_name, sequence_specification_json,
                    )
                    diagram_generation_state["class_specification_json"] = class_specification_json
                except Exception as error:
                    logger.warning(
                        "Agentic class diagram exploration failed for feature_id=%s: %s",
                        feature_id, error,
                    )

        if not sequence_specification_json and not class_specification_json:
            try:
                provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)
                raw_output = await provider.invoke_agent([
                    {"role": "system", "content": DIAGRAM_FOCUSED_BOTH_SYSTEM_PROMPT},
                    {"role": "user", "content": build_diagram_focused_both_prompt(
                        feature_name=feature_name,
                        srs_json=srs_for_modeling,
                        architecture_plan_json=architecture_plan_json,
                    )},
                ])
                combined = self._extract_json_object(raw_output)
                if isinstance(combined, dict):
                    candidate_sequence = combined.get("sequence_specification_json")
                    candidate_class = combined.get("class_specification_json")
                    if isinstance(candidate_sequence, dict):
                        sequence_specification_json = candidate_sequence
                    if isinstance(candidate_class, dict):
                        class_specification_json = candidate_class
            except Exception as error:
                logger.warning(
                    "Focused single-shot diagram generation (both) failed for feature_id=%s: %s",
                    feature_id, error,
                )
        elif not class_specification_json:
            try:
                provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)
                raw_output = await provider.invoke_agent([
                    {"role": "system", "content": DIAGRAM_FOCUSED_CLASS_ONLY_SYSTEM_PROMPT},
                    {"role": "user", "content": build_diagram_focused_class_only_prompt(
                        feature_name=feature_name,
                        srs_json=srs_for_modeling,
                        architecture_plan_json=architecture_plan_json,
                        sequence_specification_json=sequence_specification_json,
                    )},
                ])
                candidate_class = self._extract_json_object(raw_output)
                if isinstance(candidate_class, dict):
                    class_specification_json = candidate_class
            except Exception as error:
                logger.warning(
                    "Focused single-shot diagram generation (class-only) failed for feature_id=%s: %s",
                    feature_id, error,
                )

        parsed["sequence_specification_json"] = sequence_specification_json
        parsed["class_specification_json"] = class_specification_json

        parsed = await self._complete_sequence_model(agent_input, parsed)
        parsed = await self._complete_class_model(agent_input, parsed)

        return parsed

    async def _complete_usecase_model(
        self,
        agent_input: ArchitectureAgentInput,
        parsed: dict[str, Any],
        diagram_generation_state: dict[str, Any] | None = None,
        attempt_agentic: bool = True,
        attempt_focused_fallback: bool = False,
    ) -> dict[str, Any]:
        """
        Build the final use case model using the dedicated modeler, then run
        the full UseCaseQualityValidator right here -- moved earlier than
        before (previously only run once, later, from _validate_full_output)
        -- so a quality failure (garbled names, CRUD fragmentation, etc.)
        gets a chance at a cheap, TARGETED repair before this rung's overall
        validation ever sees it. The later _validate_full_output call
        becomes a final, harmless re-confirmation, not the only gate.

        The LLM may provide usecase_specification_json, usecase_analysis_json,
        or usecase_json. However, the final diagram must always pass through
        ArchitectureUseCaseModeler so that actors, use cases, relationships,
        and notes are normalized using feature-independent UML rules.

        `diagram_generation_state` is the SAME shared dict a caller threads
        through every `_complete_diagram_models` call within one
        run()/revise() invocation (see that method's own docstring) --
        reused here under the new "usecase_attempted"/
        "usecase_specification_json" keys, not a second state dict. When
        `attempt_agentic` is true and the agentic use case exploration
        hasn't already been attempted this invocation, it's tried first;
        any failure falls through to whatever specification `parsed`
        already carries (never discarded). When `attempt_focused_fallback`
        is true and the specification is still empty afterward, one
        focused, non-agentic single-shot call is made instead of jumping
        straight to the deterministic fallback -- this is what gives
        revise() real LLM-grounded use case content instead of always
        regenerating from the empty-specification template with zero LLM
        involvement.

        Never raises for a QUALITY validation failure -- once repair
        attempts are exhausted (or skipped, see below) it just returns the
        best model it has, and lets the existing _validate_full_output ->
        outer reliability ladder handle it, exactly as before this change.
        The pre-existing structural _ensure_keys/_validate_usecase_json
        checks may still raise, unchanged.
        """

        if diagram_generation_state is None:
            diagram_generation_state = {}

        srs_for_modeling = agent_input.enhanced_srs_json or agent_input.srs_json
        feature_name = agent_input.feature.get("feature_name", "Feature")
        architecture_plan_json = parsed["architecture_plan_json"]
        feature_id = agent_input.feature.get("feature_id")

        usecase_specification_json = diagram_generation_state.get("usecase_specification_json")
        if not isinstance(usecase_specification_json, dict) or not usecase_specification_json:
            usecase_specification_json = parsed.get("usecase_specification_json")
        if not isinstance(usecase_specification_json, dict):
            usecase_specification_json = {}

        if (
            attempt_agentic
            and not diagram_generation_state.get("usecase_attempted")
            and not usecase_specification_json.get("use_cases")
        ):
            diagram_generation_state["usecase_attempted"] = True

            try:
                usecase_specification_json = await self._generate_usecase_diagram_via_exploration(
                    agent_input, architecture_plan_json, feature_name,
                )
                diagram_generation_state["usecase_specification_json"] = usecase_specification_json
            except Exception as error:
                logger.warning(
                    "Agentic use case diagram exploration failed for feature_id=%s: %s",
                    feature_id, error,
                )

        if attempt_focused_fallback and not usecase_specification_json.get("use_cases"):
            try:
                provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)
                raw_output = await provider.invoke_agent([
                    {"role": "system", "content": USECASE_DIAGRAM_FOCUSED_SYSTEM_PROMPT},
                    {"role": "user", "content": build_usecase_diagram_focused_prompt(
                        feature_name=feature_name,
                        srs_json=srs_for_modeling,
                        architecture_plan_json=architecture_plan_json,
                    )},
                ])
                candidate = self._extract_json_object(raw_output)
                if isinstance(candidate, dict) and candidate.get("use_cases"):
                    usecase_specification_json = candidate
                    diagram_generation_state["usecase_specification_json"] = usecase_specification_json
            except Exception as error:
                logger.warning(
                    "Focused single-shot use case diagram generation failed for feature_id=%s: %s",
                    feature_id, error,
                )

        usecase_analysis_json, usecase_json = self.usecase_modeler.build(
            srs_json=srs_for_modeling,
            sds_json=parsed["architecture_plan_json"],
            usecase_specification_json=usecase_specification_json,
        )

        # Only the true last-resort deterministic-fallback rung reaches here
        # with a genuinely empty specification (no use_cases at all) -- making
        # a new LLM call from the rung whose whole purpose is "the LLM
        # already failed twice" would defeat its purpose, so the repair loop
        # is gated off entirely in that case.
        if usecase_specification_json.get("use_cases"):
            provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)

            for repair_attempt in range(MAX_USECASE_REPAIR_ATTEMPTS):
                try:
                    self.usecase_validator.validate(
                        srs_for_modeling,
                        parsed["architecture_plan_json"],
                        usecase_analysis_json,
                        usecase_json,
                    )
                    break
                except UseCaseValidationError as error:
                    logger.warning(
                        "Use case quality validation failed (repair attempt %d/%d): %s",
                        repair_attempt + 1,
                        MAX_USECASE_REPAIR_ATTEMPTS,
                        error,
                    )

                    repaired_specification = await self._repair_usecase_specification(
                        provider=provider,
                        srs_json=srs_for_modeling,
                        usecase_specification_json=usecase_specification_json,
                        feature_name=feature_name,
                        error_text=str(error),
                    )
                    if repaired_specification is None:
                        break

                    usecase_specification_json = repaired_specification
                    usecase_analysis_json, usecase_json = self.usecase_modeler.build(
                        srs_json=srs_for_modeling,
                        sds_json=parsed["architecture_plan_json"],
                        usecase_specification_json=usecase_specification_json,
                    )

        parsed["usecase_specification_json"] = usecase_specification_json
        parsed["usecase_analysis_json"] = usecase_analysis_json
        parsed["usecase_json"] = usecase_json

        self._ensure_keys(usecase_json, self.REQUIRED_USECASE_KEYS)
        self._validate_usecase_json(usecase_json)

        return parsed

    async def _repair_usecase_specification(
        self,
        provider: Any,
        srs_json: dict[str, Any],
        usecase_specification_json: dict[str, Any],
        feature_name: str,
        error_text: str,
    ) -> dict[str, Any] | None:
        """
        One small, targeted LLM call to fix a use case specification that
        failed quality validation -- cheaper and faster than re-running the
        entire architecture-plan generation just to fix a naming or
        fragmentation problem. Never raises: returns None on any failure
        (call error or unparseable output) so the caller can stop repairing
        and fall through to the existing outer reliability ladder gracefully.
        """

        repair_prompt = build_usecase_repair_prompt(
            srs_json=srs_json,
            usecase_specification_json=usecase_specification_json,
            validation_error=error_text,
            feature_name=feature_name,
        )

        try:
            raw_output = await provider.invoke_agent([
                {"role": "system", "content": USECASE_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ])
            repaired = self._extract_json_object(raw_output)
        except Exception as error:
            logger.warning("Use case specification repair call failed: %s", error)
            return None

        return repaired if isinstance(repaired, dict) else None

    async def _complete_sequence_model(
        self,
        agent_input: ArchitectureAgentInput,
        parsed: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Build the final sequence diagram model using the dedicated modeler,
        then run the full SequenceDiagramValidator right here so a quality
        failure (duplicate messages, unbalanced fragments, etc.) gets a
        chance at a cheap, TARGETED repair before the outer
        _validate_full_output ever sees it -- mirrors
        _complete_usecase_model's shape exactly, but fully independent (own
        specification field, own repair prompt/method, own attempt cap).

        The LLM may provide sequence_specification_json. The final diagram
        always passes through ArchitectureSequenceModeler so participants
        and interactions are normalized/id-assigned consistently.

        Never raises for a QUALITY validation failure -- once repair
        attempts are exhausted (or skipped, see below) it just returns the
        best model it has, and lets the existing outer reliability ladder
        handle it, exactly as before this change.
        """

        srs_for_modeling = agent_input.enhanced_srs_json or agent_input.srs_json
        feature_name = agent_input.feature.get("feature_name", "Feature")

        sequence_specification_json = parsed.get("sequence_specification_json")
        if not isinstance(sequence_specification_json, dict):
            sequence_specification_json = {}

        sequence_diagram_json = self.sequence_modeler.build(
            srs_json=srs_for_modeling,
            sds_json=parsed["architecture_plan_json"],
            sequence_specification_json=sequence_specification_json,
        )

        # Only the true last-resort deterministic-fallback rung reaches here
        # with a genuinely empty specification (no participants/interactions
        # at all) -- making a new LLM call from the rung whose whole purpose
        # is "the LLM already failed twice" would defeat its purpose, so the
        # repair loop is gated off entirely in that case.
        if sequence_specification_json.get("participants") and sequence_specification_json.get("interactions"):
            provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)

            for repair_attempt in range(MAX_SEQUENCE_REPAIR_ATTEMPTS):
                try:
                    self.sequence_validator.validate(srs_for_modeling, sequence_diagram_json)
                    break
                except SequenceDiagramValidationError as error:
                    logger.warning(
                        "Sequence diagram quality validation failed (repair attempt %d/%d): %s",
                        repair_attempt + 1,
                        MAX_SEQUENCE_REPAIR_ATTEMPTS,
                        error,
                    )

                    repaired_specification = await self._repair_sequence_specification(
                        provider=provider,
                        srs_json=srs_for_modeling,
                        sequence_specification_json=sequence_specification_json,
                        feature_name=feature_name,
                        error_text=str(error),
                    )
                    if repaired_specification is None:
                        break

                    sequence_specification_json = repaired_specification
                    sequence_diagram_json = self.sequence_modeler.build(
                        srs_json=srs_for_modeling,
                        sds_json=parsed["architecture_plan_json"],
                        sequence_specification_json=sequence_specification_json,
                    )

        parsed["sequence_specification_json"] = sequence_specification_json
        parsed["sequence_diagram_json"] = sequence_diagram_json

        return parsed

    async def _repair_sequence_specification(
        self,
        provider: Any,
        srs_json: dict[str, Any],
        sequence_specification_json: dict[str, Any],
        feature_name: str,
        error_text: str,
    ) -> dict[str, Any] | None:
        """
        One small, targeted LLM call to fix a sequence diagram specification
        that failed quality validation. Never raises: returns None on any
        failure (call error or unparseable output) so the caller can stop
        repairing and fall through to the existing outer reliability ladder
        gracefully. Fully independent of _repair_usecase_specification --
        no shared state or calls.
        """

        repair_prompt = build_sequence_repair_prompt(
            srs_json=srs_json,
            sequence_specification_json=sequence_specification_json,
            validation_error=error_text,
            feature_name=feature_name,
        )

        try:
            raw_output = await provider.invoke_agent([
                {"role": "system", "content": SEQUENCE_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ])
            repaired = self._extract_json_object(raw_output)
        except Exception as error:
            logger.warning("Sequence specification repair call failed: %s", error)
            return None

        return repaired if isinstance(repaired, dict) else None

    async def _complete_class_model(
        self,
        agent_input: ArchitectureAgentInput,
        parsed: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Build the final class diagram model using the dedicated modeler,
        then run the full ClassDiagramValidator right here so a quality
        failure (missing multiplicity, anemic DTO/entity, etc.) gets a
        chance at a cheap, TARGETED repair before the outer
        _validate_full_output ever sees it -- mirrors
        _complete_usecase_model's shape exactly, but fully independent (own
        specification field, own repair prompt/method, own attempt cap).

        The LLM may provide class_specification_json. The final diagram
        always passes through ArchitectureClassModeler so classes and
        relationships are normalized/id-assigned/deduped consistently.

        Never raises for a QUALITY validation failure -- once repair
        attempts are exhausted (or skipped, see below) it just returns the
        best model it has, and lets the existing outer reliability ladder
        handle it, exactly as before this change.
        """

        srs_for_modeling = agent_input.enhanced_srs_json or agent_input.srs_json
        feature_name = agent_input.feature.get("feature_name", "Feature")

        class_specification_json = parsed.get("class_specification_json")
        if not isinstance(class_specification_json, dict):
            class_specification_json = {}

        class_diagram_json = self.class_modeler.build(
            srs_json=srs_for_modeling,
            sds_json=parsed["architecture_plan_json"],
            class_specification_json=class_specification_json,
        )

        # Only the true last-resort deterministic-fallback rung reaches here
        # with a genuinely empty specification (no classes at all) -- making
        # a new LLM call from the rung whose whole purpose is "the LLM
        # already failed twice" would defeat its purpose, so the repair loop
        # is gated off entirely in that case.
        if class_specification_json.get("classes"):
            provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)

            for repair_attempt in range(MAX_CLASS_REPAIR_ATTEMPTS):
                try:
                    self.class_validator.validate(srs_for_modeling, class_diagram_json)
                    break
                except ClassDiagramValidationError as error:
                    logger.warning(
                        "Class diagram quality validation failed (repair attempt %d/%d): %s",
                        repair_attempt + 1,
                        MAX_CLASS_REPAIR_ATTEMPTS,
                        error,
                    )

                    repaired_specification = await self._repair_class_specification(
                        provider=provider,
                        srs_json=srs_for_modeling,
                        class_specification_json=class_specification_json,
                        feature_name=feature_name,
                        error_text=str(error),
                    )
                    if repaired_specification is None:
                        break

                    class_specification_json = repaired_specification
                    class_diagram_json = self.class_modeler.build(
                        srs_json=srs_for_modeling,
                        sds_json=parsed["architecture_plan_json"],
                        class_specification_json=class_specification_json,
                    )

        parsed["class_specification_json"] = class_specification_json
        parsed["class_diagram_json"] = class_diagram_json

        return parsed

    async def _repair_class_specification(
        self,
        provider: Any,
        srs_json: dict[str, Any],
        class_specification_json: dict[str, Any],
        feature_name: str,
        error_text: str,
    ) -> dict[str, Any] | None:
        """
        One small, targeted LLM call to fix a class diagram specification
        that failed quality validation. Never raises: returns None on any
        failure (call error or unparseable output) so the caller can stop
        repairing and fall through to the existing outer reliability ladder
        gracefully. Fully independent of _repair_usecase_specification --
        no shared state or calls.
        """

        repair_prompt = build_class_repair_prompt(
            srs_json=srs_json,
            class_specification_json=class_specification_json,
            validation_error=error_text,
            feature_name=feature_name,
        )

        try:
            raw_output = await provider.invoke_agent([
                {"role": "system", "content": CLASS_REPAIR_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ])
            repaired = self._extract_json_object(raw_output)
        except Exception as error:
            logger.warning("Class specification repair call failed: %s", error)
            return None

        return repaired if isinstance(repaired, dict) else None

    def _validate_full_output(
        self,
        agent_input: ArchitectureAgentInput,
        parsed: dict[str, Any]
    ) -> None:
        """
        Run full Architecture Plan and UML diagram validations.
        """

        srs_for_validation = agent_input.enhanced_srs_json or agent_input.srs_json

        self.architecture_plan_validator.validate(
            srs_json=srs_for_validation,
            architecture_plan_json=parsed["architecture_plan_json"]
        )

        self.usecase_validator.validate(
            srs_json=srs_for_validation,
            sds_json=parsed["architecture_plan_json"],
            usecase_analysis_json=parsed["usecase_analysis_json"],
            usecase_json=parsed["usecase_json"],
        )

        self.sequence_validator.validate(
            srs_json=srs_for_validation,
            sequence_json=parsed["sequence_diagram_json"],
        )

        self.class_validator.validate(
            srs_json=srs_for_validation,
            class_json=parsed["class_diagram_json"],
        )

    def _parse_and_validate_output(
        self,
        raw_output: str,
        srs_json: dict[str, Any] | None = None,
        feature_name: str = "",
    ) -> dict[str, Any]:
        """
        Parse and validate Architecture Agent JSON structure.

        srs_json/feature_name feed _ensure_implementation_plan's mechanical
        synthesis when the LLM omitted the implementation_plan section.
        """

        parsed = self._extract_json_object(raw_output)

        # Backward compatibility: if an older prompt/provider returns sds_json,
        # convert it into architecture_plan_json before validation.
        if "architecture_plan_json" not in parsed and isinstance(parsed.get("sds_json"), dict):
            parsed["architecture_plan_json"] = self._convert_sds_to_architecture_plan(
                sds_json=parsed.pop("sds_json"),
                srs_json=srs_json or {},
            )

        self._ensure_keys(parsed, self.REQUIRED_TOP_LEVEL_KEYS)

        architecture_plan_json = parsed.get("architecture_plan_json")

        if not isinstance(architecture_plan_json, dict):
            raise ValueError("architecture_plan_json must be a JSON object.")

        self._remove_diagram_reference_sections(architecture_plan_json)

        self._ensure_keys(architecture_plan_json, self.REQUIRED_ARCHITECTURE_PLAN_KEYS)

        design_views = architecture_plan_json.get("design_views", {})

        if not isinstance(design_views, dict):
            raise ValueError("architecture_plan_json.design_views must be a JSON object.")

        self._ensure_keys(design_views, self.REQUIRED_DESIGN_VIEW_KEYS)

        self._ensure_implementation_plan(
            architecture_plan_json,
            srs_json=srs_json,
            feature_name=feature_name
            or architecture_plan_json.get("document_control", {}).get("feature_name", "Feature"),
        )

        # Use case output is intentionally completed by _complete_usecase_model().
        # This prevents weak or random LLM usecase_json from becoming the final diagram.
        return parsed

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        """
        Extract JSON object from LLM output.
        """

        cleaned = text.strip()

        cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        start = cleaned.find("{")
        end = cleaned.rfind("}")

        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in Architecture Agent output.")

        return json.loads(cleaned[start:end + 1])

    def _ensure_keys(self, data: dict[str, Any], required_keys: list[str]) -> None:
        """
        Validate required keys.
        """

        missing = [key for key in required_keys if key not in data]

        if missing:
            raise ValueError(f"Missing required keys: {missing}")

    def _validate_usecase_json(self, usecase_json: dict[str, Any]) -> None:
        """
        Validate basic use case diagram structure.
        """

        actors = usecase_json.get("actors", [])
        use_cases = usecase_json.get("use_cases", [])
        relationships = usecase_json.get("relationships", [])
        notes = usecase_json.get("notes", [])

        if not isinstance(actors, list) or not actors:
            raise ValueError("usecase_json.actors must be a non-empty list.")

        if not isinstance(use_cases, list) or not use_cases:
            raise ValueError("usecase_json.use_cases must be a non-empty list.")

        if not isinstance(relationships, list) or not relationships:
            raise ValueError("usecase_json.relationships must be a non-empty list.")

        if not isinstance(notes, list):
            raise ValueError("usecase_json.notes must be a list.")

        for actor in actors:
            if not actor.get("id") or not actor.get("name"):
                raise ValueError("Each actor must have id and name.")

        for use_case in use_cases:
            if not use_case.get("id") or not use_case.get("name"):
                raise ValueError("Each use case must have id and name.")

        for relationship in relationships:
            if not relationship.get("from") or not relationship.get("to"):
                raise ValueError("Each relationship must have from and to.")

            if relationship.get("type") not in [
                "association",
                "include",
                "extend",
                "generalization",
            ]:
                raise ValueError(
                    f"Invalid use case relationship type: {relationship.get('type')}"
                )

    async def revise(self, feature_id: str, request: ArchitectureAgentReviseRequest) -> AgentRunResponse:
        """
        Revise the latest Architecture Plan and regenerate diagrams.

        Diagram generation files are not manually edited here.
        If the human asks for a diagram change, the Architecture Plan sections
        that feed the diagrams are revised, then the existing deterministic
        diagram pipeline regenerates Use Case, Sequence, and Class diagrams.
        """

        logger.info("Architecture Agent revision started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        latest_plan_artifact = self._find_latest_architecture_plan_json_artifact(feature_id)
        if not latest_plan_artifact:
            raise ValueError(
                "No existing Architecture Plan JSON artifact found. "
                "Run Architecture Agent before requesting revision."
            )

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.JSON
        )
        if not srs_artifact:
            raise ValueError(
                "No approved SRS JSON artifact found. "
                "Approve Requirement Agent SRS JSON before revising Architecture Agent output."
            )

        existing_architecture_plan_json = read_json_file(latest_plan_artifact["file_path"])
        srs_json = read_json_file(srs_artifact["file_path"])

        # Real, reported gap: a revision previously ignored the Enhanced SRS entirely (always
        # regenerated diagrams against the plain SRS, silently discarding domain enrichment) --
        # loaded the same pin-aware way run() does, so a revision built on the same enriched
        # content the original plan was.
        enhanced_srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            artifact_type=ArtifactType.ENHANCED_SRS,
            artifact_format=ArtifactFormat.JSON
        )
        enhanced_srs_json = read_json_file(enhanced_srs_artifact["file_path"]) if enhanced_srs_artifact else None

        output = await self._revise_architecture_plan_output(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            existing_architecture_plan_json=existing_architecture_plan_json,
            revision_comment=request.revision_comment,
            revised_by=request.revised_by,
        )

        artifact_ids = self._save_architecture_artifacts(
            project=dict(project),
            feature=dict(feature),
            output=output
        )

        logger.info(
            "Architecture Agent revision completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids
        )

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.ARCHITECTURE,
            status="revised",
            message=(
                "Architecture Plan revised successfully. "
                "Use Case, Sequence, and Class diagrams were regenerated from the revised plan. "
                "A new Architecture Agent version was created and requires human approval."
            ),
            artifact_ids=artifact_ids
        )

    async def revise_stream(self, feature_id: str, request: ArchitectureAgentReviseRequest):
        """
        Streaming variant of revise() -- same event shape as run_stream (see its own docstring),
        built from _revise_architecture_plan_output's already-cheap shape (no agentic exploration
        at all, one single-shot LLM call): that one provider.invoke_agent call becomes
        provider.stream(...) with token yields; everything after (fallback, implementation-plan
        synthesis, usecase model, attempt_agentic=False diagram regeneration, the tolerant
        _validate_full_output block) is the existing logic with phase events interleaved.

        Events:
            {"type": "token", "text": "..."}
            {"type": "phase", "phase": "...", "label": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "message": "..."}
        """

        logger.info("Architecture Agent revision (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        latest_plan_artifact = self._find_latest_architecture_plan_json_artifact(feature_id)
        if not latest_plan_artifact:
            yield {
                "type": "error",
                "message": (
                    "No existing Architecture Plan JSON artifact found. "
                    "Run Architecture Agent before requesting revision."
                ),
            }
            return

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id, artifact_type=ArtifactType.SRS, artifact_format=ArtifactFormat.JSON
        )
        if not srs_artifact:
            yield {
                "type": "error",
                "message": (
                    "No approved SRS JSON artifact found. "
                    "Approve Requirement Agent SRS JSON before revising Architecture Agent output."
                ),
            }
            return

        existing_architecture_plan_json = read_json_file(latest_plan_artifact["file_path"])
        srs_json = read_json_file(srs_artifact["file_path"])

        enhanced_srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id, artifact_type=ArtifactType.ENHANCED_SRS, artifact_format=ArtifactFormat.JSON
        )
        enhanced_srs_json = read_json_file(enhanced_srs_artifact["file_path"]) if enhanced_srs_artifact else None
        srs_for_generation = enhanced_srs_json or srs_json

        provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)

        prompt = build_architecture_plan_revision_prompt(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_for_generation,
            existing_architecture_plan_json=existing_architecture_plan_json,
            revision_comment=request.revision_comment,
            revised_by=request.revised_by,
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=ARCHITECTURE_REVISION_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed Architecture Plan revision failed mid-stream for feature_id=%s: %s",
                feature_id,
                stream_error,
            )

        raw_output = "".join(raw_chunks)

        # Same reliability ladder as _revise_architecture_plan_output (see its own comment): the
        # streamed tokens are now the small {"revision_summary", "operations"} plan, not the whole
        # document -- a real UX improvement on its own, since a human sees a short, readable plan
        # typing in rather than an 800-line JSON dump.
        try:
            plan = self._parse_architecture_revision_plan(raw_output)
            revised_architecture_plan_json = self._apply_architecture_revision_plan(
                existing_architecture_plan_json=existing_architecture_plan_json,
                plan=plan,
                revision_comment=request.revision_comment,
                revised_by=request.revised_by,
            )
            raw_output = json.dumps(plan, indent=2, default=str)

        except Exception as first_error:
            logger.warning(
                "Streamed Architecture Plan revision plan parsing failed, attempting JSON repair. "
                "Error=%s", first_error,
            )

            repair_prompt = build_json_repair_prompt(raw_output)
            try:
                repaired_output = await provider.invoke_agent([
                    {"role": "system", "content": JSON_REPAIR_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ])
            except Exception as repair_call_error:
                logger.warning(
                    "Streamed Architecture Plan revision JSON repair call itself failed (not "
                    "just its output) for feature_id=%s: %s", feature_id, repair_call_error,
                )
                repaired_output = ""

            try:
                plan = self._parse_architecture_revision_plan(repaired_output)
                revised_architecture_plan_json = self._apply_architecture_revision_plan(
                    existing_architecture_plan_json=existing_architecture_plan_json,
                    plan=plan,
                    revision_comment=request.revision_comment,
                    revised_by=request.revised_by,
                )
                raw_output = json.dumps(plan, indent=2, default=str)

            except Exception as second_error:
                logger.warning(
                    "Streamed Architecture Plan revision JSON repair failed. Using fallback "
                    "revision. Error=%s", second_error,
                )

                revised_architecture_plan_json = self._fallback_revise_architecture_plan_json(
                    existing_architecture_plan_json=existing_architecture_plan_json,
                    revision_comment=request.revision_comment,
                    revised_by=request.revised_by,
                    reason=str(second_error),
                )
                raw_output = json.dumps(revised_architecture_plan_json, indent=2, default=str)

        self._ensure_implementation_plan(
            revised_architecture_plan_json,
            srs_json=srs_for_generation,
            feature_name=feature.get("feature_name", "Feature"),
        )

        agent_input = ArchitectureAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_notes=None,
            human_comment=request.revision_comment,
        )

        parsed = {
            "architecture_plan_json": revised_architecture_plan_json,
            "usecase_specification_json": {},
        }

        yield {"type": "phase", "phase": "usecase", "label": "Updating the use case model..."}
        # revise() always uses an empty usecase specification (only the plan
        # text itself is revised by the LLM) -- attempt_focused_fallback=True
        # is what gives the use case diagram a real, feature-grounded LLM
        # generation attempt here instead of always rebuilding from the
        # empty-specification deterministic template with zero LLM
        # involvement (the confirmed real gap this whole change fixes).
        # attempt_agentic=False skips only the expensive agentic tool-using
        # tier, since a human is synchronously watching this stream.
        parsed = await self._complete_usecase_model(
            agent_input, parsed, attempt_agentic=False, attempt_focused_fallback=True,
        )

        yield {"type": "phase", "phase": "diagrams", "label": "Regenerating sequence and class diagrams..."}
        parsed = await self._complete_diagram_models(agent_input, parsed, attempt_agentic=False)

        try:
            self._validate_full_output(agent_input, parsed)
        except Exception as validation_error:
            logger.warning(
                "Streamed Architecture Plan revision diagram validation failed for feature_id=%s "
                "-- proceeding anyway for human review: %s",
                feature_id,
                validation_error,
            )
            parsed["architecture_plan_json"]["human_approval_note"] = build_human_approval_note(
                parsed["architecture_plan_json"].get("human_approval_note", ""),
                validation_error,
                context="on the revised diagrams",
            )

        architecture_plan_markdown = self.markdown_builder.build(revised_architecture_plan_json)
        usecase_puml = self.usecase_builder.build(parsed["usecase_json"])
        sequence_puml = self.sequence_builder.build(parsed["sequence_diagram_json"])
        class_puml = self.class_builder.build(parsed["class_diagram_json"])

        output = ArchitectureAgentOutput(
            architecture_plan_json=revised_architecture_plan_json,
            architecture_plan_markdown=architecture_plan_markdown,
            usecase_analysis_json=parsed["usecase_analysis_json"],
            usecase_json=parsed["usecase_json"],
            usecase_puml=usecase_puml,
            sequence_diagram_json=parsed["sequence_diagram_json"],
            sequence_puml=sequence_puml,
            class_diagram_json=parsed["class_diagram_json"],
            class_puml=class_puml,
            raw_llm_output=raw_output,
        )

        yield {"type": "phase", "phase": "rendering", "label": "Rendering diagram images and saving artifacts..."}

        artifact_ids = await asyncio.to_thread(
            self._save_architecture_artifacts,
            project=dict(project),
            feature=dict(feature),
            output=output,
        )

        logger.info(
            "Architecture Agent revision (streamed) completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": (
                "Architecture Plan revised successfully. "
                "Use Case, Sequence, and Class diagrams were regenerated from the revised plan. "
                "A new Architecture Agent version was created and requires human approval."
            ),
        }

    async def _revise_architecture_plan_output(
        self,
        project: dict,
        feature: dict,
        srs_json: dict,
        existing_architecture_plan_json: dict,
        revision_comment: str,
        revised_by: str,
        enhanced_srs_json: dict | None = None,
    ) -> ArchitectureAgentOutput:
        """
        Use the LLM to revise the Architecture Plan, then regenerate diagrams.

        enhanced_srs_json (when available) supersedes the plain srs_json entirely for both the
        LLM prompt and diagram regeneration -- srs_for_generation = enhanced_srs_json or
        srs_json, same convention used throughout the rest of this agent (see the module's own
        _generate_architecture_output). Previously this method hardcoded enhanced_srs_json=None,
        so every revision silently regenerated diagrams against the plain SRS even when the
        original plan (and this feature's real Enhanced SRS) had real domain enrichment -- a real,
        reported gap.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.ARCHITECTURE.value)
        srs_for_generation = enhanced_srs_json or srs_json

        prompt = build_architecture_plan_revision_prompt(
            project=project,
            feature=feature,
            srs_json=srs_for_generation,
            existing_architecture_plan_json=existing_architecture_plan_json,
            revision_comment=revision_comment,
            revised_by=revised_by,
        )

        # A transport/timeout failure from this call itself (e.g. an httpx.ReadTimeout, whose
        # str() is frequently empty) must be treated exactly like an unparseable response -- never
        # left to propagate uncaught, or this whole revision crashes with a blank error message
        # instead of falling through to _fallback_revise_architecture_plan_json below.
        try:
            raw_output = await provider.invoke_agent([
                {
                    "role": "system",
                    "content": ARCHITECTURE_REVISION_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ])
        except Exception as invoke_error:
            logger.warning(
                "Architecture Plan revision generation call itself failed (not just its output) "
                "for feature_id=%s: %s", feature.get("feature_id"), invoke_error,
            )
            raw_output = ""

        # Reliability ladder: parse the small {"revision_summary", "operations"} plan (never a
        # full-document retype -- see ARCHITECTURE_REVISION_SYSTEM_PROMPT's own rationale) and
        # apply it deterministically via revision_patcher. A PARSE failure specifically gets one
        # JSON-repair retry; only if that also fails does this fall through to the existing,
        # unchanged _fallback_revise_architecture_plan_json (now a much rarer true last resort).
        try:
            plan = self._parse_architecture_revision_plan(raw_output)
            revised_architecture_plan_json = self._apply_architecture_revision_plan(
                existing_architecture_plan_json=existing_architecture_plan_json,
                plan=plan,
                revision_comment=revision_comment,
                revised_by=revised_by,
            )
            raw_output = json.dumps(plan, indent=2, default=str)

        except Exception as first_error:
            logger.warning(
                "Architecture Plan revision plan parsing failed, attempting JSON repair. Error=%s",
                first_error,
            )

            repair_prompt = build_json_repair_prompt(raw_output)
            try:
                repaired_output = await provider.invoke_agent([
                    {"role": "system", "content": JSON_REPAIR_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ])
            except Exception as repair_call_error:
                logger.warning(
                    "Architecture Plan revision JSON repair call itself failed (not just its "
                    "output) for feature_id=%s: %s", feature.get("feature_id"), repair_call_error,
                )
                repaired_output = ""

            try:
                plan = self._parse_architecture_revision_plan(repaired_output)
                revised_architecture_plan_json = self._apply_architecture_revision_plan(
                    existing_architecture_plan_json=existing_architecture_plan_json,
                    plan=plan,
                    revision_comment=revision_comment,
                    revised_by=revised_by,
                )
                raw_output = json.dumps(plan, indent=2, default=str)

            except Exception as second_error:
                logger.warning(
                    "Architecture Plan revision JSON repair failed. Using fallback revision. "
                    "Error=%s", second_error,
                )

                revised_architecture_plan_json = self._fallback_revise_architecture_plan_json(
                    existing_architecture_plan_json=existing_architecture_plan_json,
                    revision_comment=revision_comment,
                    revised_by=revised_by,
                    reason=str(second_error),
                )
                raw_output = json.dumps(revised_architecture_plan_json, indent=2, default=str)

        # A revision of a legacy (pre-implementation_plan) plan must not fail
        # downstream validation just because the original never had one --
        # synthesize mechanically, same guarantee as the run() path.
        self._ensure_implementation_plan(
            revised_architecture_plan_json,
            srs_json=srs_for_generation,
            feature_name=feature.get("feature_name", "Feature"),
        )

        agent_input = ArchitectureAgentInput(
            project=project,
            feature=feature,
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_notes=None,
            human_comment=revision_comment,
        )

        parsed = {
            "architecture_plan_json": revised_architecture_plan_json,
            "usecase_specification_json": {},
        }
        # revise() always uses an empty usecase specification (only the plan
        # text itself is revised by the LLM) -- attempt_focused_fallback=True
        # is what gives the use case diagram a real, feature-grounded LLM
        # generation attempt here instead of always rebuilding from the
        # empty-specification deterministic template with zero LLM
        # involvement (the confirmed real gap this whole change fixes).
        parsed = await self._complete_usecase_model(
            agent_input, parsed, attempt_agentic=False, attempt_focused_fallback=True,
        )
        # Diagrams still get a real, feature-grounded generation attempt via
        # the focused single-shot tier -- attempt_agentic=False skips only
        # the expensive agentic tool-using tier, since a human is
        # synchronously waiting on what's usually a small plan-text edit,
        # not the potentially long diagram exploration. No
        # diagram_generation_state is threaded through since revise() only
        # calls this once (no cascading rungs to memoize across).
        parsed = await self._complete_diagram_models(agent_input, parsed, attempt_agentic=False)

        # This still tolerates a heuristic-validator failure (proceed with a
        # caveat noted on the plan, since there is no further fallback to
        # try) rather than crashing -- mirrors the main generation ladder's
        # true last-resort rung.
        try:
            self._validate_full_output(agent_input, parsed)
        except Exception as validation_error:
            logger.warning(
                "Architecture Plan revision diagram validation failed for feature_id=%s "
                "-- proceeding anyway for human review: %s",
                feature.get("feature_id"),
                validation_error,
            )
            parsed["architecture_plan_json"]["human_approval_note"] = build_human_approval_note(
                parsed["architecture_plan_json"].get("human_approval_note", ""),
                validation_error,
                context="on the revised diagrams",
            )

        architecture_plan_markdown = self.markdown_builder.build(revised_architecture_plan_json)
        usecase_puml = self.usecase_builder.build(parsed["usecase_json"])
        sequence_puml = self.sequence_builder.build(parsed["sequence_diagram_json"])
        class_puml = self.class_builder.build(parsed["class_diagram_json"])

        return ArchitectureAgentOutput(
            architecture_plan_json=revised_architecture_plan_json,
            architecture_plan_markdown=architecture_plan_markdown,
            usecase_analysis_json=parsed["usecase_analysis_json"],
            usecase_json=parsed["usecase_json"],
            usecase_puml=usecase_puml,
            sequence_diagram_json=parsed["sequence_diagram_json"],
            sequence_puml=sequence_puml,
            class_diagram_json=parsed["class_diagram_json"],
            class_puml=class_puml,
            raw_llm_output=raw_output,
        )

    def _parse_and_validate_architecture_plan_json(self, raw_output: str) -> dict[str, Any]:
        """
        Parse a revised Architecture Plan JSON object returned by the LLM.
        """

        parsed = self._extract_json_object(raw_output)

        if "architecture_plan_json" in parsed and isinstance(parsed["architecture_plan_json"], dict):
            parsed = parsed["architecture_plan_json"]

        if "sds_json" in parsed and isinstance(parsed["sds_json"], dict):
            parsed = self._convert_sds_to_architecture_plan(
                sds_json=parsed["sds_json"],
                srs_json={},
            )

        if not isinstance(parsed, dict):
            raise ValueError("Revised Architecture Plan must be a JSON object.")

        self._remove_diagram_reference_sections(parsed)
        self._ensure_keys(parsed, self.REQUIRED_ARCHITECTURE_PLAN_KEYS)

        design_views = parsed.get("design_views", {})
        if not isinstance(design_views, dict):
            raise ValueError("architecture_plan_json.design_views must be a JSON object.")
        self._ensure_keys(design_views, self.REQUIRED_DESIGN_VIEW_KEYS)

        return parsed

    def _parse_architecture_revision_plan(self, raw_output: str) -> dict:
        """
        Parse the small {"revision_summary", "operations"} shape a revision call now returns (see
        ARCHITECTURE_REVISION_SYSTEM_PROMPT) -- deliberately NOT
        _parse_and_validate_architecture_plan_json's full-document REQUIRED_ARCHITECTURE_PLAN_KEYS
        check, since a revision call no longer returns a full Architecture Plan document.
        """
        parsed = self._extract_json_object(raw_output)
        if not isinstance(parsed, dict):
            raise ValueError("Revision plan output was not a JSON object.")
        operations = parsed.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("Revision plan 'operations' field must be a list.")
        return {"revision_summary": parsed.get("revision_summary", ""), "operations": operations}

    def _apply_architecture_revision_plan(
        self,
        existing_architecture_plan_json: dict,
        plan: dict,
        revision_comment: str,
        revised_by: str,
    ) -> dict:
        """
        Deterministically apply a parsed revision plan's operations to the existing Architecture
        Plan (see revision_patcher.apply_architecture_revision_operations). Any operation the
        patcher couldn't confidently match, and the case where the LLM proposed zero operations at
        all, are surfaced directly in the revised plan's own `assumptions` array -- so a human
        reviewer sees explicitly when a requested change did NOT happen, instead of it silently
        failing to happen at all.
        """
        operations = plan.get("operations", [])
        patched, applied, unmatched = apply_architecture_revision_operations(
            existing_architecture_plan_json, operations
        )
        patched["revision_metadata"] = {
            "revision_type": "architecture_plan_revision",
            "revision_comment": revision_comment,
            "revised_by": revised_by,
            "revision_summary": plan.get("revision_summary", ""),
            "applied_changes": applied,
            "unmatched_operations": unmatched,
        }
        assumptions = patched.get("assumptions", [])
        if not isinstance(assumptions, list):
            assumptions = []
        for note in unmatched:
            assumptions.append(f"Revision could not be fully applied -- {note}")
        if not operations:
            assumptions.append(
                f"No Architecture Plan changes were made for revision comment: {revision_comment!r} -- "
                f"agent's response: {plan.get('revision_summary') or '(no summary given)'}"
            )
        patched["assumptions"] = assumptions
        return patched

    def _fallback_revise_architecture_plan_json(
        self,
        existing_architecture_plan_json: dict,
        revision_comment: str,
        revised_by: str,
        reason: str,
    ) -> dict[str, Any]:
        """
        Create a safe fallback revision when LLM revision fails.
        """

        revised = dict(existing_architecture_plan_json)
        self._remove_diagram_reference_sections(revised)

        revised["revision_metadata"] = {
            "revision_type": "architecture_plan_revision",
            "revision_comment": revision_comment,
            "revised_by": revised_by,
            "fallback_used": True,
            "fallback_reason": reason,
        }

        tasks = revised.get("coder_implementation_tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        tasks.append({
            "task_id": f"TASK-{len(tasks) + 1:03d}",
            "task": f"Review and manually apply architecture revision request: {revision_comment}",
            "layer": "review",
            "suggested_files": [],
            "related_requirements": [],
        })
        revised["coder_implementation_tasks"] = tasks

        revised["human_approval_note"] = (
            "This Architecture Plan revision used a safe fallback. "
            "Human review is required before the UI/UX Agent or Coder Agent starts."
        )

        return revised

    def _load_previous_architecture_plans(
        self, project_id: str, exclude_feature_id: str
    ) -> list[dict[str, Any]]:
        """
        Load the latest APPROVED Architecture Plan JSON of every OTHER
        feature in this project -- the project-wide context that makes a new
        feature's plan consistent with (and reuse-aware of) what already
        exists, instead of being planned blind.

        Includes plans stored under the legacy `sds` artifact type (the live
        e-commerce project's Login plan is one), same fallback the Coder
        Agent's own architecture-plan lookup applies.

        Returns [{"feature_id", "feature_name", "architecture_plan_json"}],
        one entry per feature, latest approved version winning.
        """

        candidates: list[dict[str, Any]] = []
        for artifact_type in [ArtifactType.ARCHITECTURE_PLAN, ArtifactType.SDS]:
            candidates.extend(
                artifact_service.list_project_artifacts(
                    project_id=project_id,
                    agent_name=AgentName.ARCHITECTURE,
                    artifact_type=artifact_type,
                    artifact_format=ArtifactFormat.JSON,
                    approval_status=ApprovalStatus.APPROVED,
                )
            )

        latest_by_feature: dict[str, dict[str, Any]] = {}
        for artifact in candidates:
            feature_id = artifact.get("feature_id")
            if not feature_id or feature_id == exclude_feature_id:
                continue
            current_best = latest_by_feature.get(feature_id)
            if current_best is None or artifact.get("version", 1) > current_best.get("version", 1):
                latest_by_feature[feature_id] = artifact

        previous_plans: list[dict[str, Any]] = []
        for feature_id, artifact in latest_by_feature.items():
            try:
                plan_json = read_json_file(artifact["file_path"])
            except Exception as error:
                logger.warning(
                    "Could not read previous architecture plan for feature_id=%s: %s",
                    feature_id,
                    error,
                )
                continue

            # Unwrap known historical envelope shapes; a legacy SDS-shaped
            # document (has "introduction", predates the plan shape) converts
            # so its design_views/implementation info render consistently.
            if isinstance(plan_json.get("architecture_plan_json"), dict):
                plan_json = plan_json["architecture_plan_json"]
            if isinstance(plan_json.get("sds_json"), dict):
                plan_json = plan_json["sds_json"]
            if "introduction" in plan_json and "feature_overview" not in plan_json:
                plan_json = self._convert_sds_to_architecture_plan(sds_json=plan_json, srs_json={})

            feature_record = store.features.get(feature_id, {})
            previous_plans.append({
                "feature_id": feature_id,
                "feature_name": feature_record.get(
                    "feature_name",
                    plan_json.get("document_control", {}).get("feature_name", feature_id),
                ),
                "architecture_plan_json": plan_json,
            })

        return previous_plans

    def _find_latest_architecture_plan_json_artifact(self, feature_id: str) -> dict | None:
        """
        Find the latest Architecture Plan JSON artifact for this feature.
        """

        matching_artifacts = []

        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue

            if artifact.get("agent_name") not in [AgentName.ARCHITECTURE, AgentName.ARCHITECTURE.value]:
                continue

            if artifact.get("artifact_type") not in [
                ArtifactType.ARCHITECTURE_PLAN,
                ArtifactType.ARCHITECTURE_PLAN.value,
            ]:
                continue

            if artifact.get("artifact_format") not in [ArtifactFormat.JSON, ArtifactFormat.JSON.value]:
                continue

            matching_artifacts.append(artifact)

        if not matching_artifacts:
            return None

        return max(matching_artifacts, key=lambda item: item.get("version", 1))

    def _remove_diagram_reference_sections(self, architecture_plan_json: dict[str, Any]) -> None:
        """
        Architecture Plan must not include diagram reference sections.
        Diagram files are saved as separate artifacts instead.
        """

        for key in [
            "use_case_diagram_reference",
            "sequence_diagram_reference",
            "class_diagram_reference",
        ]:
            architecture_plan_json.pop(key, None)

    def _find_latest_approved_artifact(
        self,
        feature_id: str,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat
    ) -> dict | None:
        """
        Find the artifact that should feed this run -- a human-pinned APPROVED version if one was
        explicitly selected (see artifact_service.set_active_artifact_selection / the frontend's
        per-version radio button on approved rows), otherwise the latest APPROVED version by
        version number.

        Delegates to artifact_service.get_selected_or_latest_approved_artifact -- previously this
        was a private, enum-and-.value-tolerant duplicate of the same "latest approved" lookup
        (like the one every other agent still has its own copy of), with no awareness of a pinned
        selection at all. Dropped the agent_name filter in the process: the shared helper doesn't
        filter on it, and artifact_type (srs vs enhanced_srs) already disambiguates which agent
        produced it for every call site in this class.
        """

        return artifact_service.get_selected_or_latest_approved_artifact(
            feature_id, artifact_type.value, artifact_format.value
        )

    def _save_architecture_artifacts(
        self,
        project: dict,
        feature: dict,
        output: ArchitectureAgentOutput
    ) -> list[str]:
        """
        Save Architecture Agent artifacts.

        Files:
        - {feature}_architecture_plan_v1.md
        - {feature}_architecture_plan_v1.json
        - {feature}_usecase_v1.puml / .png
        - {feature}_sequence_v1.puml / .png
        - {feature}_class_v1.puml / .png
        """

        version = artifact_service.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=AgentName.ARCHITECTURE,
            artifact_type=ArtifactType.ARCHITECTURE_PLAN
        )

        stage_folder = artifact_service.get_stage_folder(
            project_name=project["project_name"],
            feature_name=feature["feature_name"],
            agent_name=AgentName.ARCHITECTURE
        )

        feature_slug = self._feature_slug(feature)

        architecture_plan_md_path = stage_folder / f"{feature_slug}_architecture_plan_v{version}.md"
        architecture_plan_json_path = stage_folder / f"{feature_slug}_architecture_plan_v{version}.json"
        usecase_puml_path = stage_folder / f"{feature_slug}_usecase_v{version}.puml"
        sequence_puml_path = stage_folder / f"{feature_slug}_sequence_v{version}.puml"
        class_puml_path = stage_folder / f"{feature_slug}_class_v{version}.puml"

        saved_architecture_plan_md = write_text_file(architecture_plan_md_path, output.architecture_plan_markdown)
        saved_architecture_plan_json = write_json_file(architecture_plan_json_path, output.architecture_plan_json)
        saved_puml = write_text_file(usecase_puml_path, output.usecase_puml)
        saved_sequence_puml = write_text_file(sequence_puml_path, output.sequence_puml)
        saved_class_puml = write_text_file(class_puml_path, output.class_puml)

        png_path = self.diagram_renderer.render_png(Path(saved_puml))
        sequence_png_path = self.diagram_renderer.render_png(Path(saved_sequence_puml))
        class_png_path = self.diagram_renderer.render_png(Path(saved_class_puml))

        artifact_ids = []
        created_at = datetime.now(timezone.utc)

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.ARCHITECTURE_PLAN,
                artifact_format=ArtifactFormat.MARKDOWN,
                file_path=saved_architecture_plan_md,
                version=version,
                created_at=created_at
            )
        )

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.ARCHITECTURE_PLAN,
                artifact_format=ArtifactFormat.JSON,
                file_path=saved_architecture_plan_json,
                version=version,
                created_at=created_at
            )
        )

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.USE_CASE_DIAGRAM,
                artifact_format=ArtifactFormat.TEXT,
                file_path=saved_puml,
                version=version,
                created_at=created_at
            )
        )

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.USE_CASE_DIAGRAM,
                artifact_format=ArtifactFormat.PNG,
                file_path=str(png_path),
                version=version,
                created_at=created_at
            )
        )

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.SEQUENCE_DIAGRAM,
                artifact_format=ArtifactFormat.TEXT,
                file_path=saved_sequence_puml,
                version=version,
                created_at=created_at
            )
        )

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.SEQUENCE_DIAGRAM,
                artifact_format=ArtifactFormat.PNG,
                file_path=str(sequence_png_path),
                version=version,
                created_at=created_at
            )
        )

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.CLASS_DIAGRAM,
                artifact_format=ArtifactFormat.TEXT,
                file_path=saved_class_puml,
                version=version,
                created_at=created_at
            )
        )

        artifact_ids.append(
            self._register_artifact(
                project=project,
                feature=feature,
                artifact_type=ArtifactType.CLASS_DIAGRAM,
                artifact_format=ArtifactFormat.PNG,
                file_path=str(class_png_path),
                version=version,
                created_at=created_at
            )
        )

        return artifact_ids

    def _register_artifact(
        self,
        project: dict,
        feature: dict,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat,
        file_path: str,
        version: int,
        created_at: datetime
    ) -> str:
        """
        Register artifact metadata in store.
        """

        artifact_id = generate_id("artifact")

        store.artifacts[artifact_id] = {
            "artifact_id": artifact_id,
            "project_id": project["project_id"],
            "feature_id": feature["feature_id"],
            "agent_name": AgentName.ARCHITECTURE,
            "artifact_type": artifact_type,
            "artifact_format": artifact_format,
            "file_path": file_path,
            "version": version,
            "approval_status": ApprovalStatus.PENDING,
            "created_at": created_at,
        }

        return artifact_id

    def _feature_slug(self, feature: dict) -> str:
        """
        Build safe file name slug from feature name.
        """

        feature_name = feature.get("feature_name", "feature")
        slug = feature_name.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        slug = slug.strip("_")

        return slug or "feature"

    def _build_fallback_architecture_output(
        self,
        agent_input: ArchitectureAgentInput,
        reason: str
    ) -> dict[str, Any]:
        """
        Build dynamic fallback architecture output.

        This fallback is feature-independent.
        It reads the approved SRS and builds Architecture Plan sections from SRS fields.
        """

        srs = agent_input.enhanced_srs_json or agent_input.srs_json
        feature = agent_input.feature
        project = agent_input.project

        project_id = project.get("project_id", srs.get("project_id", "project"))
        project_name = project.get("project_name", srs.get("project_name", "Project"))
        project_type = project.get("project_type", srs.get("project_type", "General"))
        feature_id = feature.get("feature_id", srs.get("feature_id", "feature"))
        feature_name = feature.get("feature_name", srs.get("feature_name", "Feature"))
        target_stack = project.get("target_stack", srs.get("target_stack", "Next.js"))
        architecture_style = srs.get("preferred_architectural_style", srs.get("architecture_style", srs.get("architectural_style", "mvc")))

        base_sds_json = self._build_base_design_from_srs(
            srs=srs,
            project_id=project_id,
            project_name=project_name,
            project_type=project_type,
            feature_id=feature_id,
            feature_name=feature_name,
            target_stack=target_stack,
            architecture_style=architecture_style,
            reason=reason,
        )

        architecture_plan_json = self._convert_sds_to_architecture_plan(
            sds_json=base_sds_json,
            srs_json=srs,
        )

        # usecase_analysis_json/usecase_json are deliberately NOT set here --
        # the caller (_generate_architecture_output) always immediately runs
        # _complete_usecase_model right after this, which unconditionally
        # rebuilds both from ArchitectureUseCaseModeler. Computing them here
        # too was confirmed dead work (the result was always overwritten).
        return {
            "architecture_plan_json": architecture_plan_json,
        }

    def _convert_sds_to_architecture_plan(
        self,
        sds_json: dict[str, Any],
        srs_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Convert the older SDS-shaped design JSON into the new Architecture Plan shape.

        This keeps diagram generation unchanged because design_views are preserved.
        """

        srs_json = srs_json or {}
        document_control = dict(sds_json.get("document_control", {}))
        introduction = sds_json.get("introduction", {})
        design_context = sds_json.get("design_context", {})
        design_considerations = sds_json.get("design_considerations", {})
        architecture_overview = sds_json.get("architecture_overview", {})
        design_views = sds_json.get("design_views", {})

        feature_name = (
            document_control.get("feature_name")
            or srs_json.get("feature_name")
            or "Feature"
        )

        document_control["document_title"] = f"Architecture Plan: {feature_name}"
        document_control["document_type"] = "Feature Architecture Plan"
        document_control.pop("standard_basis", None)
        document_control.setdefault("generated_by", "Architecture Agent")
        document_control.setdefault("approval_status", "pending")

        architecture_plan_json = {
            "document_control": document_control,
            "feature_overview": {
                "business_goal": design_context.get("business_goal", srs_json.get("business_goal", "")),
                "scope": introduction.get("scope", srs_json.get("scope", [])),
                "out_of_scope": introduction.get("out_of_scope", srs_json.get("out_of_scope", [])),
                "user_roles": design_context.get("user_roles", srs_json.get("user_roles", [])),
                "feature_boundary": design_context.get("feature_boundary", f"This plan covers only the {feature_name} feature."),
            },
            "requirement_interpretation": {
                "functional_requirements": self._as_record_list(srs_json.get("functional_requirements", [])),
                "acceptance_criteria": self._as_record_list(srs_json.get("acceptance_criteria", [])),
                "validation_rules": self._as_record_list(srs_json.get("validation_rules", [])),
                "non_functional_requirements": self._as_record_list(srs_json.get("non_functional_requirements", [])),
            },
            "architecture_approach": {
                "architecture_style": architecture_overview.get("architecture_style", document_control.get("architecture_style", "modular")),
                "architecture_rationale": architecture_overview.get("architecture_rationale", ""),
                "frontend_overview": architecture_overview.get("frontend_overview", ""),
                "backend_overview": architecture_overview.get("backend_overview", ""),
                "data_overview": architecture_overview.get("data_overview", ""),
                "integration_overview": architecture_overview.get("integration_overview", ""),
                "design_tradeoffs": design_considerations.get("design_tradeoffs", []),
            },
            "design_views": design_views,
            "frontend_architecture_plan": {
                "responsibilities": design_views.get("logical_view", {}).get("frontend_modules", []),
                "pages_or_components": self._as_record_list(srs_json.get("ui_expectations", [])),
                "state_and_feedback": [
                    self._item_description(item)
                    for item in self._as_record_list(srs_json.get("acceptance_criteria", []))
                    if self._contains_any(self._item_description(item).lower(), ["display", "show", "message", "redirect", "direct"])
                ],
            },
            "backend_architecture_plan": {
                "responsibilities": design_views.get("logical_view", {}).get("backend_modules", []),
                "layers": (
                    design_views.get("logical_view", {}).get("domain_services", [])
                    + design_views.get("logical_view", {}).get("data_modules", [])
                ),
                "integration_points": design_views.get("logical_view", {}).get("integration_points", []),
            },
            # processing_validation deliberately mirrors input_validation's own source
            # (data_view.data_validation_rules), NOT error_handling_view.validation_errors --
            # the deterministic fallback has no reliable signal to split "checked at the API
            # boundary" from "checked during processing," and pointing at error_handling_view
            # made the Validation Plan and Error Handling Plan render as literal duplicates (a
            # real, reported bug) since error_handling_view describes response BEHAVIOR, a
            # conceptually different section that must stay independent.
            "validation_plan": {
                "input_validation": design_views.get("data_view", {}).get("data_validation_rules", []),
                "processing_validation": design_views.get("data_view", {}).get("data_validation_rules", []),
            },
            "coder_implementation_tasks": self._build_coder_implementation_tasks(
                feature_name=feature_name,
                srs=srs_json,
                design_views=design_views,
            ),
            "implementation_plan": self._build_implementation_plan(
                feature_name=feature_name,
                srs_json=srs_json,
                design_views=design_views,
            ),
            "traceability_matrix": self._convert_traceability_to_architecture_plan(
                sds_json.get("traceability_matrix", [])
            ),
            "assumptions": design_context.get("assumptions", sds_json.get("assumptions", [])),
            "constraints": design_considerations.get("constraints", sds_json.get("constraints", [])),
            "risks": design_considerations.get("risks", sds_json.get("risks", [])),
            "dependencies": design_context.get("dependencies", sds_json.get("dependencies", [])),
            "revision_metadata": None,
            "human_approval_note": "This Architecture Plan must be reviewed and approved before the UI/UX Agent or Coder Agent starts.",
        }

        self._remove_diagram_reference_sections(architecture_plan_json)
        architecture_plan_json = self._clean_architecture_plan_text(architecture_plan_json)
        return architecture_plan_json

    def _ensure_implementation_plan(
        self,
        architecture_plan_json: dict[str, Any],
        srs_json: dict[str, Any] | None,
        feature_name: str,
    ) -> None:
        """
        Guarantee a structurally-valid implementation_plan exists on the plan.

        The prompt requires the LLM to author one (an LLM-authored plan is
        richer), but an otherwise-good plan must never be discarded -- or a
        legacy/fallback plan rejected downstream -- just because it predates
        or omitted this section. Synthesizes mechanically from the plan's own
        design_views + the SRS when missing or malformed.
        """

        existing = architecture_plan_json.get("implementation_plan")

        if isinstance(existing, dict) and all(
            key in existing for key in self.REQUIRED_IMPLEMENTATION_PLAN_KEYS
        ):
            return

        if existing is not None:
            logger.warning(
                "implementation_plan was present but malformed (missing keys) -- "
                "replacing with a mechanically-derived one."
            )

        architecture_plan_json["implementation_plan"] = self._build_implementation_plan(
            feature_name=feature_name,
            srs_json=srs_json or {},
            design_views=architecture_plan_json.get("design_views", {}) or {},
        )

    def _build_implementation_plan(
        self,
        feature_name: str,
        srs_json: dict[str, Any],
        design_views: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Mechanically derive an end-to-end implementation plan for the Coder
        Agent from the plan's own design_views + the SRS.

        This is the deterministic floor: the LLM (single-shot or agentic) is
        prompted to author a richer version, but every plan -- including the
        SRS-derived fallback and converted legacy SDS plans -- must carry a
        real, structurally-valid implementation_plan, because the Coder Agent
        treats it as the blueprint to realize. File paths follow the exact
        Next.js App Router + TypeScript scaffold conventions the Coder
        Agent's own planner prompt teaches (app/api/<resource>/route.ts,
        app/<route>/page.tsx, the FEATURE_LINKS_END marker) -- with no
        "mount the router" step at all, since Next.js's file-based routing
        makes a Route Handler live the instant its file exists.
        """

        slug = self._slug(feature_name)
        pascal = self._pascal_case(feature_name)
        camel = self._camel_case(feature_name)

        interface_view = design_views.get("interface_view", {}) or {}
        data_view = design_views.get("data_view", {}) or {}
        error_view = design_views.get("error_handling_view", {}) or {}

        api_endpoints = [e for e in interface_view.get("api_endpoints", []) or [] if isinstance(e, dict)]
        data_entities = [e for e in data_view.get("data_entities", []) or [] if isinstance(e, dict)]
        request_models_by_name = {
            model.get("name"): model
            for model in interface_view.get("request_models", []) or []
            if isinstance(model, dict) and model.get("name")
        }

        # Group endpoints by the Route Handler file their path resolves to --
        # a collection endpoint ("/api/tasks") and an item endpoint
        # ("/api/tasks/:id") ALWAYS resolve to two separate files
        # (app/api/tasks/route.ts vs. app/api/tasks/[id]/route.ts), since
        # Next.js routes by folder path, not by an Express-style single
        # router file handling every method+path combination.
        endpoints_by_route_file: dict[str, list[dict[str, Any]]] = {}
        for endpoint in api_endpoints:
            endpoint_path = str(endpoint.get("endpoint") or f"/api/{slug}")
            endpoints_by_route_file.setdefault(self._endpoint_route_file(endpoint_path), []).append(endpoint)

        backend_files: list[dict[str, Any]] = []
        for route_file, group_endpoints in endpoints_by_route_file.items():
            implements = [e.get("endpoint") for e in group_endpoints if e.get("endpoint")]
            methods = ", ".join(sorted({str(e.get("method", "GET")).upper() for e in group_endpoints}))
            backend_files.append({
                "path": route_file,
                "action": "create",
                "purpose": f"Next.js Route Handler implementing {methods} for {feature_name} "
                           f"({', '.join(implements)}), with request validation before any handler logic.",
                "implements_endpoints": implements,
            })

        models: list[dict[str, Any]] = []
        for entity in data_entities:
            entity_name = str(entity.get("name") or f"{pascal}Data")
            model_file = f"models/{self._pascal_case(entity_name)}.ts"

            fields = []
            for field in entity.get("fields", []) or []:
                if isinstance(field, dict):
                    fields.append({
                        "name": field.get("name", "field"),
                        "type": field.get("type", "string"),
                        "constraints": str(
                            field.get("constraints")
                            or field.get("format")
                            or field.get("description")
                            or ""
                        ),
                    })

            models.append({"name": entity_name, "file": model_file, "fields": fields})
            backend_files.append({
                "path": model_file,
                "action": "create",
                "purpose": f"Mongoose model for the {entity_name} entity (must use the "
                           f"`mongoose.models.{self._pascal_case(entity_name)} || mongoose.model(...)` "
                           "guard to avoid OverwriteModelError).",
                "implements_endpoints": [],
            })

        error_case_hints = [
            str(item)
            for item in (error_view.get("validation_errors", []) or [])[:3]
        ]

        endpoints: list[dict[str, Any]] = []
        for endpoint in api_endpoints:
            request_fields = []
            request_model = request_models_by_name.get(endpoint.get("request_model"))
            if request_model:
                for field in request_model.get("fields", []) or []:
                    if isinstance(field, dict):
                        request_fields.append({
                            "field": field.get("name", "field"),
                            "type": field.get("type", "string"),
                            "required": bool(field.get("required", True)),
                            "validation": str(field.get("format") or field.get("description") or ""),
                        })

            endpoints.append({
                "method": endpoint.get("method", "GET"),
                "path": endpoint.get("endpoint", f"/api/{slug}"),
                "request_body": request_fields,
                "response": str(
                    endpoint.get("success_response_model")
                    or endpoint.get("purpose")
                    or "JSON response"
                ),
                "error_cases": (
                    ["400 when required request fields are missing or invalid"]
                    + error_case_hints
                    + ["500 when an unexpected server error occurs"]
                ),
            })

        page_name = f"{pascal}Page"
        route_path = f"/{slug}"
        ui_expectations = self._as_record_list(srs_json.get("ui_expectations", []))
        page_purpose = f"Main page for the {feature_name} feature."
        if ui_expectations:
            page_purpose += " UI expectations: " + "; ".join(
                self._item_description(item) for item in ui_expectations[:5]
            )

        pages = [{
            "path": f"app/{slug}/page.tsx",
            "route": route_path,
            "purpose": page_purpose,
            "uses_components": [],
        }]

        service_functions = []
        for endpoint in endpoints:
            method = str(endpoint.get("method", "GET")).upper()
            path = str(endpoint.get("path", ""))
            static_segments = [
                segment for segment in path.strip("/").split("/")
                if segment and not segment.startswith(":") and segment != "api"
            ]
            target = self._pascal_case(static_segments[-1]) if static_segments else pascal
            service_functions.append({
                "name": f"{method.lower()}{target}",
                "calls_endpoint": f"{method} {path}",
            })

        frontend = {
            "pages": pages,
            "components_to_reuse": [],
            "services": [{
                "path": f"lib/api/{camel}.ts",
                "functions": service_functions,
            }] if service_functions else [],
            "routing": {
                "new_routes": [{"path": route_path, "component": page_name}],
                "nav_links": [{"to": route_path, "label": feature_name}],
            },
        }

        implementation_order = []
        if models:
            implementation_order.append(
                "Create the Mongoose model(s): " + ", ".join(model["file"] for model in models)
            )
        for route_file, group_endpoints in endpoints_by_route_file.items():
            implements = ", ".join(str(e.get("endpoint")) for e in group_endpoints if e.get("endpoint"))
            implementation_order.append(
                f"Create {route_file} implementing {implements}, validating required request "
                "fields before use (400 on missing/malformed) -- it is automatically live the "
                "instant the file exists, no separate mount step needed."
            )
        if service_functions:
            implementation_order.append(
                f"Create lib/api/{camel}.ts with one function per endpoint."
            )
        implementation_order.append(
            f"Create app/{slug}/page.tsx (a Client Component, `\"use client\"` as its first line), "
            "reusing approved UI/UX components where available instead of re-authoring their markup."
        )
        implementation_order.append(
            f"Register a real <Link href=\"{route_path}\"> in app/page.tsx at the FEATURE_LINKS "
            "markers -- a page with no link to it is not complete."
        )

        return {
            "backend": {
                "files": backend_files,
                "endpoints": endpoints,
                "models": models,
            },
            "frontend": frontend,
            "implementation_order": implementation_order,
            "constraints": [
                "The Next.js App Router scaffold already exists and works -- never recreate "
                "app/layout.tsx, next.config.mjs, tsconfig.json, or lib/mongodb.ts.",
                "A Route Handler (route.ts) is live the instant it exists -- there is no router "
                "to mount it on, unlike an Express app.js.",
                "Register new pages by adding a real <Link href=\"...\"> in app/page.tsx (FEATURE_LINKS "
                "markers) -- an unreachable page is not done.",
                "Every Mongoose model file must use the `mongoose.models.X || mongoose.model(...)` "
                "guard to avoid OverwriteModelError.",
                "Approved UI/UX output is a visual reference, not code to import -- use "
                "read_ui_component_design/read_ui_page_design to see the approved HTML+Tailwind "
                "design, then write real TSX that faithfully matches its structure/classes/"
                "content.",
            ],
        }

    def _endpoint_route_file(self, endpoint_path: str) -> str:
        """
        Translate an endpoint path (e.g. "/api/tasks/:id") into the Next.js
        Route Handler file path that must implement it (e.g.
        "app/api/tasks/[id]/route.ts") -- a dynamic segment ":name" becomes
        a "[name]" folder, mirroring coder_agent/route_checker.py's own
        translation (kept as a small, separate copy here rather than a
        cross-agent import, since this fallback and that checker are
        independent, deterministic pieces with no other coupling).
        """
        segments = [segment for segment in endpoint_path.strip("/").split("/") if segment]
        translated = [
            f"[{segment[1:]}]" if segment.startswith(":") else segment
            for segment in segments
        ]
        return "app/" + "/".join(translated) + "/route.ts"

    def _clean_architecture_plan_text(self, value: Any) -> Any:
        """
        Remove old SDS wording from Architecture Plan values.
        """

        replacements = {
            "Software Design Specification": "Architecture Plan",
            "software design specification": "architecture plan",
            "IEEE 1016-style Software Design Description": "Feature-level implementation design plan",
            "This SDS": "This Architecture Plan",
            "this SDS": "this Architecture Plan",
            "SDS must": "Architecture Plan must",
            "SDS was": "Architecture Plan was",
            "approval-ready SDS": "approval-ready Architecture Plan",
            "Fallback SDS": "Fallback Architecture Plan",
        }

        if isinstance(value, dict):
            return {key: self._clean_architecture_plan_text(val) for key, val in value.items()}

        if isinstance(value, list):
            return [self._clean_architecture_plan_text(item) for item in value]

        if isinstance(value, str):
            cleaned = value
            for old, new in replacements.items():
                cleaned = cleaned.replace(old, new)
            return cleaned

        return value

    def _convert_traceability_to_architecture_plan(self, traceability_items: list[Any]) -> list[dict[str, Any]]:
        """
        Rename old SDS traceability section labels to Architecture Plan labels.
        """

        converted = []
        for item in traceability_items or []:
            if not isinstance(item, dict):
                continue
            record = dict(item)
            if "sds_section" in record:
                record["architecture_plan_section"] = str(record.pop("sds_section")).replace("SDS", "Architecture Plan")
            elif "architecture_plan_section" in record:
                record["architecture_plan_section"] = str(record["architecture_plan_section"]).replace("SDS", "Architecture Plan")
            converted.append(record)
        return converted

    def _build_coder_implementation_tasks(
        self,
        feature_name: str,
        srs: dict[str, Any],
        design_views: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build feature-independent Coder Agent tasks from SRS and Architecture Plan design views.
        """

        tasks: list[dict[str, Any]] = []
        feature_slug = self._slug(feature_name).replace("-", "_")
        functional_ids = self._collect_requirement_ids(self._as_record_list(srs.get("functional_requirements", [])))
        validation_ids = self._collect_requirement_ids(self._as_record_list(srs.get("validation_rules", [])))
        acceptance_ids = self._collect_requirement_ids(self._as_record_list(srs.get("acceptance_criteria", [])))
        nfr_ids = self._collect_requirement_ids(self._as_record_list(srs.get("non_functional_requirements", [])))

        interface_view = design_views.get("interface_view", {}) if isinstance(design_views, dict) else {}
        data_view = design_views.get("data_view", {}) if isinstance(design_views, dict) else {}

        if srs.get("ui_expectations") or srs.get("input_requirements"):
            tasks.append({
                "task_id": f"TASK-{len(tasks) + 1:03d}",
                "task": f"Create or update frontend screen/components for the {feature_name} feature.",
                "layer": "frontend",
                "suggested_files": [
                    f"app/{feature_slug.replace('_', '-')}/page.tsx",
                    f"components/{self._pascal_case(feature_name)}Form.tsx",
                ],
                "related_requirements": functional_ids + acceptance_ids,
            })

        if interface_view.get("api_endpoints") or srs.get("api_expectations"):
            tasks.append({
                "task_id": f"TASK-{len(tasks) + 1:03d}",
                "task": f"Implement Next.js Route Handler(s) for the {feature_name} API expectations.",
                "layer": "backend",
                "suggested_files": [
                    f"app/api/{feature_slug.replace('_', '-')}/route.ts",
                    f"models/{self._pascal_case(feature_name)}.ts",
                ],
                "related_requirements": functional_ids + acceptance_ids,
            })

        if data_view.get("data_entities") or srs.get("data_requirements"):
            tasks.append({
                "task_id": f"TASK-{len(tasks) + 1:03d}",
                "task": f"Create or update data model/repository required by the {feature_name} feature.",
                "layer": "data",
                "suggested_files": [
                    f"backend/models/{feature_slug}.model.js",
                    f"backend/repositories/{feature_slug}.repository.js",
                ],
                "related_requirements": functional_ids,
            })

        if validation_ids:
            tasks.append({
                "task_id": f"TASK-{len(tasks) + 1:03d}",
                "task": "Implement validation rules before processing feature requests.",
                "layer": "validation",
                "suggested_files": [
                    f"backend/validators/{feature_slug}.validator.js",
                ],
                "related_requirements": validation_ids,
            })

        if acceptance_ids:
            tasks.append({
                "task_id": f"TASK-{len(tasks) + 1:03d}",
                "task": "Implement success, alternative, and exception handling according to acceptance criteria.",
                "layer": "backend/frontend",
                "suggested_files": [],
                "related_requirements": acceptance_ids,
            })

        security_text = str(srs).lower()
        if self._contains_any(security_text, ["auth", "token", "jwt", "password", "role", "permission", "secure"]):
            tasks.append({
                "task_id": f"TASK-{len(tasks) + 1:03d}",
                "task": "Implement security controls required by the feature, including authentication/authorization or sensitive data handling where applicable.",
                "layer": "security",
                "suggested_files": [],
                "related_requirements": functional_ids + nfr_ids,
            })

        if not tasks:
            tasks.append({
                "task_id": "TASK-001",
                "task": f"Implement the {feature_name} feature according to the approved SRS and Architecture Plan.",
                "layer": "implementation",
                "suggested_files": [],
                "related_requirements": functional_ids,
            })

        return tasks

    def _build_base_design_from_srs(
        self,
        srs: dict[str, Any],
        project_id: str,
        project_name: str,
        project_type: str,
        feature_id: str,
        feature_name: str,
        target_stack: str,
        architecture_style: str,
        reason: str,
    ) -> dict[str, Any]:
        """
        Build a base Architecture Plan design structure from SRS.

        This method maps SRS sections into generic design views.
        """

        scope = self._as_text_list(srs.get("scope", []))
        out_of_scope = self._as_text_list(srs.get("out_of_scope", []))
        user_roles = self._as_text_list(srs.get("user_roles", []))
        assumptions = self._as_text_list(srs.get("assumptions", []))
        constraints = self._as_text_list(srs.get("constraints", []))
        dependencies = self._as_text_list(srs.get("dependencies", []))
        risks = self._as_record_list(srs.get("risks", []))
        nfrs = self._as_record_list(srs.get("non_functional_requirements", []))
        functional_requirements = self._as_record_list(srs.get("functional_requirements", []))
        acceptance_criteria = self._as_record_list(srs.get("acceptance_criteria", []))
        validation_rules = self._as_record_list(srs.get("validation_rules", []))
        api_expectations = self._as_record_list(srs.get("api_expectations", []))
        input_requirements = self._as_record_list(srs.get("input_requirements", []))
        output_requirements = self._as_record_list(srs.get("output_requirements", []))
        data_requirements = self._as_record_list(srs.get("data_requirements", []))
        ui_expectations = self._as_record_list(srs.get("ui_expectations", []))
        business_goal = srs.get("business_goal", f"Support the {feature_name} feature.")

        interface_view = self._build_interface_view(
            feature_name=feature_name,
            api_expectations=api_expectations,
            input_requirements=input_requirements,
            output_requirements=output_requirements,
            functional_requirements=functional_requirements,
        )

        data_view = self._build_data_view(
            feature_name=feature_name,
            data_requirements=data_requirements,
            validation_rules=validation_rules,
            functional_requirements=functional_requirements,
        )

        behavior_view = self._build_behavior_view(
            feature_name=feature_name,
            acceptance_criteria=acceptance_criteria,
            functional_requirements=functional_requirements,
        )

        error_handling_view = self._build_error_handling_view(
            validation_rules=validation_rules,
            acceptance_criteria=acceptance_criteria,
            nfrs=nfrs,
        )

        security_view = self._build_security_view(
            constraints=constraints,
            risks=risks,
            functional_requirements=functional_requirements,
            nfrs=nfrs,
        )

        quality_view = self._build_quality_view(nfrs=nfrs)

        traceability_matrix = self._build_architecture_traceability_matrix(
            srs=srs,
            interface_view=interface_view,
            data_view=data_view,
            behavior_view=behavior_view,
            error_handling_view=error_handling_view,
            security_view=security_view,
            quality_view=quality_view,
        )

        srs_related_ids = self._collect_requirement_ids(functional_requirements)

        return {
            "document_control": {
                "document_title": f"Architecture Plan: {feature_name}",
                "document_type": "Feature Architecture Plan",
                "project_id": project_id,
                "project_name": project_name,
                "project_type": project_type,
                "feature_id": feature_id,
                "feature_name": feature_name,
                "target_stack": target_stack,
                "architecture_style": architecture_style,
                "version": "v1",
                "generated_by": "Architecture Agent",
                "input_artifacts": ["Approved SRS JSON", "Approved Enhanced SRS JSON if available"],
                "approval_status": "pending"
            },
            "introduction": {
                "purpose": f"Describe the software design for the {feature_name} feature based on the approved SRS.",
                "scope": scope or [f"Design the approved {feature_name} feature only."],
                "out_of_scope": out_of_scope,
                "intended_audience": [
                    "Human reviewer",
                    "UI/UX Agent",
                    "Coder Agent",
                    "Project supervisor",
                    "Software engineering team"
                ],
                "definitions": self._build_definitions_from_srs(srs)
            },
            "design_context": {
                "business_goal": business_goal,
                "user_roles": user_roles,
                "feature_boundary": f"This Architecture Plan covers only the {feature_name} feature and excludes unrelated features.",
                "operating_environment": f"Generated application target stack: {target_stack}.",
                "dependencies": dependencies,
                "assumptions": assumptions
            },
            "design_considerations": {
                "constraints": constraints,
                "non_functional_requirements": nfrs,
                "risks": risks,
                "design_tradeoffs": [
                    "Design is derived directly from the approved SRS to preserve traceability and feature scope.",
                    "Design is kept feature-scoped to preserve feature-by-feature SDLC development.",
                    "Internal generation or repair details are kept in backend logs and are not exposed in the approval-ready Architecture Plan."
                ]
            },
            "architecture_overview": {
                "architecture_style": architecture_style,
                "architecture_rationale": (
                    f"Use {architecture_style} to keep the {feature_name} feature separated into presentation, "
                    "business logic, and data responsibilities where applicable."
                ),
                "frontend_overview": self._build_frontend_overview(ui_expectations, input_requirements),
                "backend_overview": self._build_backend_overview(functional_requirements, validation_rules),
                "data_overview": self._build_data_overview(data_requirements),
                "integration_overview": self._build_integration_overview(api_expectations, dependencies)
            },
            "design_views": {
                "context_view": {
                    "actors": user_roles,
                    "external_systems": dependencies,
                    "feature_boundary": f"{feature_name} feature boundary.",
                    "main_interactions": self._build_main_interactions(user_roles, functional_requirements, feature_name)
                },
                "logical_view": {
                    "frontend_modules": self._build_logical_modules("frontend", feature_name, ui_expectations, input_requirements),
                    "backend_modules": self._build_logical_modules("backend", feature_name, functional_requirements, validation_rules),
                    "domain_services": self._build_domain_services(feature_name, functional_requirements),
                    "data_modules": self._build_data_modules(feature_name, data_requirements),
                    "integration_points": self._build_integration_points(api_expectations, dependencies)
                },
                "interface_view": interface_view,
                "data_view": data_view,
                "behavior_view": behavior_view,
                "error_handling_view": error_handling_view,
                "security_authorization_view": security_view,
                "quality_attributes_view": quality_view
            },
            "detailed_design_decisions": self._build_design_decisions(
                feature_name=feature_name,
                functional_requirements=functional_requirements,
                acceptance_criteria=acceptance_criteria,
                validation_rules=validation_rules,
                nfrs=nfrs,
                risks=risks,
                api_expectations=api_expectations,
                data_requirements=data_requirements,
            ),
            "traceability_matrix": traceability_matrix,
            "assumptions": assumptions,
            "constraints": constraints,
            "risks": risks,
            "dependencies": dependencies,
            "human_approval_note": "This Architecture Plan must be reviewed and approved before the UI/UX Agent or Coder Agent starts."
        }

    def _build_interface_view(
        self,
        feature_name: str,
        api_expectations: list[dict[str, Any]],
        input_requirements: list[dict[str, Any]],
        output_requirements: list[dict[str, Any]],
        functional_requirements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build interface view generically from API/input/output requirements.
        """

        request_model_name = f"{self._pascal_case(feature_name)}Request"
        success_model_name = f"{self._pascal_case(feature_name)}SuccessResponse"
        error_model_name = f"{self._pascal_case(feature_name)}ErrorResponse"

        request_model = {
            "name": request_model_name,
            "fields": [
                {
                    "name": item.get("field", item.get("name", "field")),
                    "type": item.get("type", "string"),
                    "format": item.get("format", item.get("description", "")),
                    "required": True
                }
                for item in input_requirements
            ],
            "related_requirements": self._collect_requirement_ids(functional_requirements)
        }

        success_fields = []
        error_fields = []

        for item in output_requirements:
            field_text = str(item.get("field", item.get("name", item))).lower()

            field_record = {
                "name": item.get("field", item.get("name", "field")),
                "type": item.get("type", "string"),
                "description": item.get("description", "")
            }

            if "error" in field_text or "message" in field_text:
                error_fields.append(field_record)
            else:
                success_fields.append(field_record)

        if not success_fields and output_requirements:
            success_fields = output_requirements

        response_models = [
            {
                "name": success_model_name,
                "type": "success",
                "fields": success_fields,
                "related_requirements": self._collect_requirement_ids(functional_requirements)
            },
            {
                "name": error_model_name,
                "type": "error",
                "fields": error_fields,
                "related_requirements": []
            }
        ]

        endpoints = []

        for item in api_expectations:
            parsed = self._parse_endpoint_definition(item.get("description", ""))
            endpoint = item.get("endpoint") or (parsed[1] if parsed else "")
            method = item.get("method") or (parsed[0] if parsed else "GET")
            payload = item.get("payload", item.get("purpose", ""))
            related_ids = self._infer_related_requirement_ids_from_text(
                text=f"{endpoint} {method} {payload}",
                requirement_items=functional_requirements
            )

            endpoints.append({
                "endpoint": endpoint or f"/api/{self._slug(feature_name)}",
                "method": method,
                "purpose": payload or f"Support the {feature_name} feature.",
                "request_model": request_model_name,
                "success_response_model": success_model_name,
                "error_response_model": error_model_name,
                "related_requirements": related_ids
            })

        if not endpoints:
            endpoints.append({
                "endpoint": f"/api/{self._slug(feature_name)}",
                "method": "POST",
                "purpose": f"Support the {feature_name} feature.",
                "request_model": request_model_name,
                "success_response_model": success_model_name,
                "error_response_model": error_model_name,
                "related_requirements": self._collect_requirement_ids(functional_requirements)
            })

        return {
            "api_endpoints": endpoints,
            "request_models": [request_model],
            "response_models": response_models
        }

    def _build_data_view(
        self,
        feature_name: str,
        data_requirements: list[dict[str, Any]],
        validation_rules: list[dict[str, Any]],
        functional_requirements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build data view from data and validation requirements.
        """

        data_entities = []

        # data_requirements describes the fields of ONE coherent entity (see
        # requirement_schema.py's own field description, and
        # DATA_FIELD_DEFINITION_PATTERN's docstring above) -- every item is aggregated into a
        # single entity's field list, never treated as its own separate entity. Earlier code
        # looped `enumerate(data_requirements, start=1)` and created one entity PER ITEM, which
        # for a real 9-field "Item" feature produced 9 disconnected one-field Mongoose
        # collections instead of one real Item model -- a confirmed, live bug.
        if data_requirements:
            fields = []
            combined_text_parts = []

            for item in data_requirements:
                description = item.get("description") or str(item)
                combined_text_parts.append(description)
                parsed_field = self._parse_field_definition(description)
                if parsed_field:
                    fields.append(parsed_field)
                else:
                    fields.extend(self._infer_fields_from_text(description))

            combined_text = " ".join(combined_text_parts)

            data_entities.append({
                "name": f"{self._pascal_case(feature_name)}Data",
                "purpose": f"Core data entity for the {feature_name} feature.",
                "fields": fields,
                "relationships": [],
                "indexes_or_constraints": self._infer_data_constraints_from_text(combined_text),
                "related_requirements": self._infer_related_requirement_ids_from_text(
                    text=combined_text,
                    requirement_items=functional_requirements
                )
            })

        if not data_entities:
            data_entities.append({
                "name": f"{self._pascal_case(feature_name)}Data",
                "purpose": f"Data needed to support the {feature_name} feature.",
                "fields": [],
                "relationships": [],
                "indexes_or_constraints": [],
                "related_requirements": self._collect_requirement_ids(functional_requirements)
            })

        return {
            "data_entities": data_entities,
            "storage_rules": [
                item.get("description", str(item))
                for item in data_requirements
            ] or [f"Store only data required for the {feature_name} feature."],
            "data_validation_rules": [
                {
                    "rule_id": item.get("id", f"VR-{index:03d}"),
                    "rule": item.get("description", str(item)),
                    "related_requirements": [item.get("id")] if item.get("id") else []
                }
                for index, item in enumerate(validation_rules, start=1)
            ]
        }

    def _build_behavior_view(
        self,
        feature_name: str,
        acceptance_criteria: list[dict[str, Any]],
        functional_requirements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build behavior view from acceptance criteria and FRs.
        """

        main_success_flow = []
        alternative_flows = []
        exception_flows = []

        for item in acceptance_criteria:
            text = item.get("description", str(item))
            text_lower = text.lower()

            record = {
                "id": item.get("id", ""),
                "description": text,
                "related_requirements": self._infer_related_requirement_ids_from_text(text, functional_requirements)
            }

            if self._contains_any(text_lower, ["invalid", "error", "fail", "denied", "prevent"]):
                exception_flows.append(record)
            elif self._contains_any(text_lower, ["click", "optional", "alternative", "redirect", "directed", "recover", "forgot", "reset"]):
                alternative_flows.append(record)
            else:
                main_success_flow.append(record)

        if not main_success_flow:
            main_success_flow = [
                {
                    "step": 1,
                    "description": f"Actor initiates the {feature_name} feature.",
                    "related_requirements": self._collect_requirement_ids(functional_requirements)
                },
                {
                    "step": 2,
                    "description": "System validates the request according to approved SRS rules.",
                    "related_requirements": []
                },
                {
                    "step": 3,
                    "description": "System returns the expected result or a clear error response.",
                    "related_requirements": []
                }
            ]

        return {
            "main_success_flow": main_success_flow,
            "alternative_flows": alternative_flows,
            "exception_flows": exception_flows,
            "state_changes": self._infer_state_changes(feature_name, functional_requirements, acceptance_criteria)
        }

    def _build_error_handling_view(
        self,
        validation_rules: list[dict[str, Any]],
        acceptance_criteria: list[dict[str, Any]],
        nfrs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build error handling view generically.
        """

        # condition/handling deliberately do NOT restate the rule's own description (that's what
        # data_view.data_validation_rules/validation_plan already state) -- this view exists to
        # describe the system's RESPONSE when a rule is violated, not the rule itself. A prior
        # version duplicated the rule text here and hardcoded one identical "handling" sentence
        # for every row, making the Validation Plan and Error Handling Plan render as near-
        # duplicates (a real, reported bug).
        validation_errors = [
            {
                "source_id": item.get("id", ""),
                "condition": f"Violation of {item.get('id') or 'a validation rule'}",
                "handling": (
                    f"Reject the request with an HTTP 400 response referencing "
                    f"{item.get('id') or 'this rule'}, show the user a message identifying the "
                    f"invalid field(s), and do not process or persist the request."
                ),
            }
            for item in validation_rules
        ]

        business_errors = []
        authorization_errors = []

        for item in acceptance_criteria:
            text = item.get("description", str(item))
            text_lower = text.lower()

            if self._contains_any(text_lower, ["invalid", "error", "fail", "prevent", "incorrect"]):
                business_errors.append({
                    "source_id": item.get("id", ""),
                    "condition": text,
                    "handling": "Return a clear, user-friendly error and prevent the invalid action."
                })

            if self._contains_any(text_lower, ["unauthorized", "forbidden", "access", "permission"]):
                authorization_errors.append({
                    "source_id": item.get("id", ""),
                    "condition": text,
                    "handling": "Prevent unauthorized access and return an authorization-safe response."
                })

        user_message_rules = [
            item.get("description", str(item))
            for item in nfrs
            if "error" in str(item).lower() or "clear" in str(item).lower()
        ]

        return {
            "validation_errors": validation_errors,
            "business_errors": business_errors,
            "authorization_errors": authorization_errors,
            "system_errors": [
                "Unexpected system errors should return safe generic messages without exposing internal details."
            ],
            "user_message_rules": user_message_rules or [
                "All user-facing errors must be clear, non-technical, and aligned with the approved SRS."
            ]
        }

    def _build_security_view(
        self,
        constraints: list[str],
        risks: list[dict[str, Any]],
        functional_requirements: list[dict[str, Any]],
        nfrs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build security/authorization view only from SRS-related security hints.
        """

        security_text = " ".join(map(str, constraints + risks + functional_requirements + nfrs)).lower()

        authentication_design = []
        authorization_design = []
        sensitive_data_rules = []

        if self._contains_any(security_text, ["auth", "login", "token", "jwt", "credential", "password"]):
            authentication_design.append(
                "Apply authentication behaviour required by the SRS and selected architecture."
            )

        if self._contains_any(security_text, ["role", "admin", "customer", "permission", "authorize", "access"]):
            authorization_design.append(
                "Apply role/access rules required by the SRS."
            )

        if self._contains_any(security_text, ["password", "token", "secret", "credential", "personal", "sensitive"]):
            sensitive_data_rules.append(
                "Sensitive values must not be exposed in responses, logs, or generated artifacts."
            )

        risk_mitigations = []

        for risk in risks:
            risk_mitigations.append({
                "risk": risk.get("risk", str(risk)),
                "mitigation": risk.get("mitigation", "Apply suitable mitigation based on project security policy."),
                "related_requirements": self._infer_related_requirement_ids_from_text(
                    text=str(risk),
                    requirement_items=functional_requirements
                )
            })

        return {
            "authentication_design": authentication_design,
            "authorization_design": authorization_design,
            "sensitive_data_rules": sensitive_data_rules,
            "risk_mitigations": risk_mitigations
        }

    def _build_quality_view(self, nfrs: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Build quality attributes view from NFR category or text.
        """

        quality_view = {
            "performance": [],
            "usability": [],
            "reliability": [],
            "scalability": [],
            "maintainability": [],
            "accessibility": []
        }

        for item in nfrs:
            description = item.get("description", str(item))
            category = str(item.get("category", "")).lower()
            text = f"{category} {description}".lower()

            record = {
                "nfr_id": item.get("id", ""),
                "description": description,
                "design_decision": self._quality_decision_from_nfr(description)
            }

            if "performance" in text or "fast" in text or "response" in text or "load" in text:
                quality_view["performance"].append(record)
            elif "usability" in text or "responsive" in text or "user" in text or "clear" in text:
                quality_view["usability"].append(record)
            elif "reliability" in text or "available" in text or "recover" in text:
                quality_view["reliability"].append(record)
            elif "scalability" in text or "scale" in text or "peak" in text:
                quality_view["scalability"].append(record)
            elif "accessibility" in text or "wcag" in text:
                quality_view["accessibility"].append(record)
            else:
                quality_view["maintainability"].append(record)

        return quality_view

    def _build_architecture_traceability_matrix(
        self,
        srs: dict[str, Any],
        interface_view: dict[str, Any],
        data_view: dict[str, Any],
        behavior_view: dict[str, Any],
        error_handling_view: dict[str, Any],
        security_view: dict[str, Any],
        quality_view: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build generic requirement-to-design traceability matrix.
        """

        traceability = []

        traceability.extend(self._trace_items(srs.get("functional_requirements", []), "FR", "Design Views / Detailed Design Decisions"))
        traceability.extend(self._trace_items(srs.get("acceptance_criteria", []), "AC", "Behavior View / Error Handling View"))
        traceability.extend(self._trace_items(srs.get("validation_rules", []), "VR", "Interface View / Data View / Error Handling View"))
        traceability.extend(self._trace_items(srs.get("non_functional_requirements", []), "NFR", "Quality Attributes View"))
        traceability.extend(self._trace_non_id_items(srs.get("constraints", []), "Constraint", "Design Considerations / Architecture Overview"))
        traceability.extend(self._trace_non_id_items(srs.get("risks", []), "Risk", "Design Considerations / Security and Authorization View"))
        traceability.extend(self._trace_non_id_items(srs.get("dependencies", []), "Dependency", "Design Context / Logical View"))
        traceability.extend(self._trace_non_id_items(srs.get("data_requirements", []), "Data", "Data View"))
        traceability.extend(self._trace_non_id_items(srs.get("api_expectations", []), "API", "Interface View"))
        traceability.extend(self._trace_non_id_items(srs.get("ui_expectations", []), "UI", "Context View / Logical View"))

        return traceability

    def _trace_items(self, items: list[Any], source_type: str, section: str) -> list[dict[str, Any]]:
        records = []

        for index, item in enumerate(items, start=1):
            if isinstance(item, dict):
                source_id = item.get("id", f"{source_type}-{index:03d}")
                description = item.get("description", str(item))
            else:
                source_id = f"{source_type}-{index:03d}"
                description = str(item)

            records.append({
                "source_id": source_id,
                "source_type": source_type,
                "architecture_plan_section": section,
                "design_element": description,
                "coverage_status": "covered"
            })

        return records

    def _trace_non_id_items(self, items: list[Any], source_type: str, section: str) -> list[dict[str, Any]]:
        records = []

        for index, item in enumerate(items, start=1):
            source_id = f"{source_type.upper()}-{index:03d}"
            description = self._item_description(item)

            records.append({
                "source_id": source_id,
                "source_type": source_type,
                "architecture_plan_section": section,
                "design_element": description,
                "coverage_status": "covered"
            })

        return records

    def _build_design_decisions(
        self,
        feature_name: str,
        functional_requirements: list[dict[str, Any]],
        acceptance_criteria: list[dict[str, Any]],
        validation_rules: list[dict[str, Any]],
        nfrs: list[dict[str, Any]],
        risks: list[dict[str, Any]],
        api_expectations: list[dict[str, Any]],
        data_requirements: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Build detailed design decisions from SRS items.
        """

        decisions = []
        counter = 1

        for group_name, items in [
            ("functional requirement", functional_requirements),
            ("acceptance criterion", acceptance_criteria),
            ("validation rule", validation_rules),
            ("non-functional requirement", nfrs),
            ("risk", risks),
            ("API expectation", api_expectations),
            ("data requirement", data_requirements),
        ]:
            for item in items:
                related_ids = [item.get("id")] if isinstance(item, dict) and item.get("id") else []

                decisions.append({
                    "decision_id": f"DD-{counter:03d}",
                    "decision": f"Design must address {group_name}: {self._item_description(item)}",
                    "rationale": f"This design decision is derived from the approved SRS {group_name}.",
                    "related_requirements": related_ids
                })

                counter += 1

        return decisions

    # ---------------------------------------------------------------------
    # Generic helper methods
    # ---------------------------------------------------------------------

    def _build_definitions_from_srs(self, srs: dict[str, Any]) -> list[dict[str, str]]:
        definitions = [
            {
                "term": "Architecture Plan",
                "definition": "Feature-level implementation design plan generated by the Architecture Agent."
            }
        ]

        target_stack = srs.get("target_stack")

        if target_stack:
            definitions.append({
                "term": "Target Stack",
                "definition": str(target_stack)
            })

        return definitions

    def _build_frontend_overview(self, ui_expectations: list[dict[str, Any]], input_requirements: list[dict[str, Any]]) -> str:
        if ui_expectations or input_requirements:
            return "Frontend design should provide the user-facing entry points, inputs, states, and feedback required by the approved SRS."

        return "Frontend design should support the approved feature interactions where applicable."

    def _build_backend_overview(self, functional_requirements: list[dict[str, Any]], validation_rules: list[dict[str, Any]]) -> str:
        if functional_requirements or validation_rules:
            return "Backend design should process feature requests, enforce business rules, validate inputs, and return structured responses."

        return "Backend design should support the approved feature responsibilities."

    def _build_data_overview(self, data_requirements: list[dict[str, Any]]) -> str:
        if data_requirements:
            return "Data design should support the data requirements defined in the approved SRS."

        return "No explicit data requirement was provided; data design should remain minimal and feature-scoped."

    def _build_integration_overview(self, api_expectations: list[dict[str, Any]], dependencies: list[str]) -> str:
        if api_expectations or dependencies:
            return "Integration design should follow the API expectations and dependencies listed in the approved SRS."

        return "No explicit external integration is required beyond the approved feature boundary."

    def _build_main_interactions(self, user_roles: list[str], functional_requirements: list[dict[str, Any]], feature_name: str) -> list[str]:
        interactions = []

        for role in user_roles or ["User"]:
            interactions.append(f"{role} interacts with the {feature_name} feature.")

        for requirement in functional_requirements:
            interactions.append(requirement.get("description", str(requirement)))

        return interactions

    def _build_logical_modules(self, layer: str, feature_name: str, primary_items: list[dict[str, Any]], secondary_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": f"{self._pascal_case(feature_name)}{layer.title()}Module",
                "responsibility": f"Handle {layer} responsibilities for the {feature_name} feature.",
                "derived_from": [self._item_description(item) for item in primary_items + secondary_items]
            }
        ]

    def _build_domain_services(self, feature_name: str, functional_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": f"{self._pascal_case(feature_name)}Service",
                "responsibility": f"Apply business rules for the {feature_name} feature.",
                "related_requirements": self._collect_requirement_ids(functional_requirements)
            }
        ]

    def _build_data_modules(self, feature_name: str, data_requirements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": f"{self._pascal_case(feature_name)}DataModule",
                "responsibility": "Manage data access required by the feature.",
                "derived_from": [self._item_description(item) for item in data_requirements]
            }
        ]

    def _build_integration_points(self, api_expectations: list[dict[str, Any]], dependencies: list[str]) -> list[dict[str, Any]]:
        points = []

        for item in api_expectations:
            points.append({
                "type": "API",
                "description": self._item_description(item)
            })

        for dependency in dependencies:
            points.append({
                "type": "Dependency",
                "description": dependency
            })

        return points

    def _parse_field_definition(self, description: str) -> dict[str, Any] | None:
        """
        Parses one `data_requirements` item written as "name (details)", e.g.
        "price (number, required, minimum value 0.01)" ->
        {"name": "price", "type": "Number", "required": True}. Returns None when the text
        doesn't match this shape, so the caller can fall back to _infer_fields_from_text.
        """
        match = DATA_FIELD_DEFINITION_PATTERN.match(description)
        if not match:
            return None

        field_name, detail = match.group(1), match.group(2).lower()

        if any(keyword in detail for keyword in ("number", "integer", "float", "decimal")):
            field_type = "Number"
        elif any(keyword in detail for keyword in ("timestamp", "date")):
            field_type = "Date"
        elif "boolean" in detail or re.search(r"\bbool\b", detail):
            field_type = "Boolean"
        else:
            field_type = "String"

        required = any(
            keyword in detail for keyword in ("required", "auto-generated", "auto-updated")
        )

        return {"name": self._camel_case(field_name), "type": field_type, "required": required}

    def _parse_endpoint_definition(self, description: str) -> tuple[str, str] | None:
        """
        Parses one `api_expectations` item written as "METHOD /path", e.g.
        "POST /api/items" -> ("POST", "/api/items"). Returns None when the text doesn't start
        with a real HTTP method, so the caller can fall back to its existing GET default.
        """
        match = API_ENDPOINT_DEFINITION_PATTERN.match(description)
        if not match:
            return None

        return match.group(1).upper(), match.group(2)

    def _infer_fields_from_text(self, text: str) -> list[dict[str, Any]]:
        words = re.findall(r"[A-Za-z][A-Za-z0-9_ ]{1,30}", text)

        if not words:
            return []

        # Keep this generic: use noun-like phrases only as candidate fields.
        fields = []

        for word in words[:5]:
            cleaned = word.strip()
            if len(cleaned) < 3:
                continue

            fields.append({
                "name": self._camel_case(cleaned),
                "type": "String",
                "required": False
            })

        return fields

    def _infer_data_constraints_from_text(self, text: str) -> list[str]:
        constraints = []
        text_lower = text.lower()

        if "unique" in text_lower:
            constraints.append("Unique constraint required where applicable.")

        if "secure" in text_lower or "sensitive" in text_lower:
            constraints.append("Secure storage required where applicable.")

        if "hashed" in text_lower or "encrypted" in text_lower:
            constraints.append("Protected value storage required where applicable.")

        return constraints

    def _infer_state_changes(self, feature_name: str, functional_requirements: list[dict[str, Any]], acceptance_criteria: list[dict[str, Any]]) -> list[dict[str, Any]]:
        records = []

        for item in functional_requirements + acceptance_criteria:
            text = self._item_description(item)
            if self._contains_any(text.lower(), ["redirect", "return", "update", "create", "delete", "change", "status", "receive"]):
                records.append({
                    "description": text,
                    "related_requirements": [item.get("id")] if isinstance(item, dict) and item.get("id") else []
                })

        if not records:
            records.append({
                "description": f"Feature state changes should follow the approved {feature_name} acceptance criteria.",
                "related_requirements": []
            })

        return records

    def _quality_decision_from_nfr(self, description: str) -> str:
        text = description.lower()

        if self._contains_any(text, ["fast", "response", "performance", "load", "ms", "second"]):
            return "Optimize design to satisfy the stated performance expectation."

        if self._contains_any(text, ["responsive", "mobile", "desktop", "usability", "clear"]):
            return "Design frontend/user-facing behaviour to satisfy the stated usability expectation."

        if self._contains_any(text, ["secure", "privacy", "auth", "protect"]):
            return "Apply secure design controls aligned with the stated quality expectation."

        return "Design must satisfy this non-functional requirement."

    def _infer_related_requirement_ids_from_text(self, text: str, requirement_items: list[dict[str, Any]]) -> list[str]:
        related = []
        text_tokens = set(re.findall(r"[a-zA-Z0-9]+", text.lower()))

        for item in requirement_items:
            item_text = self._item_description(item)
            item_tokens = set(re.findall(r"[a-zA-Z0-9]+", item_text.lower()))

            if text_tokens and item_tokens and len(text_tokens.intersection(item_tokens)) >= 2:
                if item.get("id"):
                    related.append(item["id"])

        if not related:
            related = self._collect_requirement_ids(requirement_items)

        return related

    def _collect_requirement_ids(self, items: list[Any]) -> list[str]:
        ids = []

        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))

        return ids

    def _as_text_list(self, value: Any) -> list[str]:
        if value is None:
            return []

        if isinstance(value, list):
            return [self._item_description(item) for item in value]

        return [str(value)]

    def _as_record_list(self, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []

        if isinstance(value, list):
            records = []

            for item in value:
                if isinstance(item, dict):
                    records.append(dict(item))
                else:
                    records.append({"description": str(item)})

            return records

        if isinstance(value, dict):
            return [dict(value)]

        return [{"description": str(value)}]

    def _item_description(self, item: Any) -> str:
        if isinstance(item, dict):
            for key in ["description", "expectation", "payload", "risk", "mitigation", "data_point", "field", "endpoint", "name"]:
                if item.get(key):
                    return str(item[key])

            return str(item)

        return str(item)

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _guess_source_type(self, requirement_id: str) -> str:
        if requirement_id.startswith("FR"):
            return "FR"

        if requirement_id.startswith("AC"):
            return "AC"

        if requirement_id.startswith("VR"):
            return "VR"

        if requirement_id.startswith("NFR"):
            return "NFR"

        return "Requirement"

    def _pascal_case(self, text: str) -> str:
        parts = re.findall(r"[a-zA-Z0-9]+", text)
        return "".join(part[:1].upper() + part[1:] for part in parts) or "Feature"

    def _camel_case(self, text: str) -> str:
        pascal = self._pascal_case(text)
        return pascal[:1].lower() + pascal[1:] if pascal else "field"

    def _slug(self, text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "-", slug)
        return slug.strip("-") or "feature"


architecture_agent = ArchitectureAgent()
