"""
UI/UX Agent.

Pipeline:
1. Load context: approved SRS, optional approved Enhanced SRS, approved
   Architecture Plan, and the project's design system.
2. Generate ui_metadata_json (one-shot LLM call via metadata_modeler.py).
3. Validate SRS coverage (metadata_validator.py) -- fail loudly on gaps.
4. Generate each component's HTML + Tailwind fragment (component_generator.py), scoped
   per-component so a single broken component can be retried alone. Every fragment passes a
   deterministic content-quality gate (real, populated content -- never an empty/placeholder
   message) before it's accepted, with a bounded, targeted repair loop if it doesn't.
5. Deterministically assemble each page's component fragments into one full, self-contained
   HTML document (page_html_builder.py -- pure string concatenation, cannot fail) -- this is
   the artifact a human previews live and the Coder Agent later reads as a visual reference.
6. Best-effort: render one PNG screenshot per assembled page (preview_renderer.py, Playwright)
   for the "Page Previews" thumbnail gallery -- secondary, never blocking.
7. Save all artifacts: ui_metadata_json, one .html fragment per component, one full-page .html
   document per page, one PNG per page (if it rendered), ui_design_markdown, and the
   integration manifest for the Coder Agent.
8. Update design_system.json with any new tokens/components -- gated on human
   approval (see apply_design_system_patch, invoked from approval_service.py)
   so a rejected run never pollutes the shared design system.
9. Human approval gate happens outside this class (existing approval flow).

See services/agentic_service/instructions .md section 4 for the full plan.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agents.uiux_agent.component_generator import ComponentGenerationError, UIUXComponentGenerator
from app.agents.uiux_agent.design_system_service import uiux_design_system_service
from app.agents.uiux_agent.integration_manifest_builder import uiux_integration_manifest_builder
from app.agents.uiux_agent.markdown_builder import uiux_markdown_builder
from app.agents.uiux_agent.metadata_modeler import UIMetadataGenerationError, UIUXMetadataModeler
from app.agents.uiux_agent.metadata_validator import UIMetadataValidationError, UIMetadataValidator
from app.agents.uiux_agent.page_html_builder import uiux_page_html_builder
from app.agents.uiux_agent.preview_renderer import PreviewRenderError, uiux_preview_renderer
from app.agents.uiux_agent.prompt import (
    UIUX_METADATA_SYSTEM_PROMPT,
    UIUX_REVISION_JSON_REPAIR_PROMPT,
    UIUX_REVISION_SYSTEM_PROMPT,
    build_uiux_metadata_user_prompt,
    build_uiux_revision_json_repair_prompt,
    build_uiux_revision_prompt,
)
from app.agents.uiux_agent.revision_patcher import apply_uiux_revision_operations
from app.agents.uiux_agent.schemas import UIUXAgentInput, UIUXAgentOutput
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.schemas.uiux_schema import UIUXAgentReviseRequest, UIUXAgentRunRequest
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.services.llm_provider_service import llm_provider_service
from app.services.project_memory_service import project_memory_service
from app.utils.file_manager import read_json_file
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UIUXAgent:
    """
    Main UI/UX Agent class.
    """

    # Slightly more headroom than Requirement/Domain/Architecture Agent's usual "one repair
    # attempt" -- UI/UX Agent has no deterministic fallback rung by design (see module
    # docstring: a guessed-at UI plan is worse than none), so it gets more real LLM attempts
    # before failing loudly instead of a synthetic fallback to fall back to. Real testing
    # against llama3:latest showed the missing-requirement-ID error genuinely shrinking each
    # repair round (6 missing -> 4 -> 1), i.e. real convergence, not flailing -- worth a bit
    # more headroom than 2 attempts to let it actually finish converging.
    MAX_VALIDATION_REPAIR_ATTEMPTS = 4

    # Bounded, targeted repair for a component fragment that fails the deterministic
    # content-quality gate (component_generator.detect_placeholder_content) -- e.g. it rendered
    # a generic "no data"/"unknown state" message instead of real, populated content. Smaller
    # than the old render-failure repair loop this replaces: a phrase-based check gives the model
    # a precise, unambiguous violation to fix (not a flaky browser error), so fewer rounds should
    # be needed to converge.
    MAX_CONTENT_QUALITY_REPAIR_ATTEMPTS = 2

    def __init__(self):
        self.metadata_modeler = UIUXMetadataModeler()
        self.metadata_validator = UIMetadataValidator()
        self.component_generator = UIUXComponentGenerator()

    async def run(self, feature_id: str, request: UIUXAgentRunRequest) -> UIUXAgentOutput:
        """
        Run the full UI/UX Agent pipeline (steps 1-6; step 7 is triggered
        separately by approval_service.py once the resulting artifact is
        approved).

        Rule:
            UI/UX Agent can only run after Requirement Agent SRS JSON and
            Architecture Agent's Architecture Plan JSON are approved.
        """

        logger.info("UI/UX Agent started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.JSON,
        )

        if not srs_artifact:
            raise ValueError(
                "No approved SRS JSON artifact found. "
                "Approve Requirement Agent SRS JSON before running UI/UX Agent."
            )

        srs_json = read_json_file(srs_artifact["file_path"])

        enhanced_srs_json = None
        if request.use_enhanced_srs_if_available:
            enhanced_srs_artifact = self._find_latest_approved_artifact(
                feature_id=feature_id,
                agent_name=AgentName.DOMAIN,
                artifact_type=ArtifactType.ENHANCED_SRS,
                artifact_format=ArtifactFormat.JSON,
            )
            if enhanced_srs_artifact:
                enhanced_srs_json = read_json_file(enhanced_srs_artifact["file_path"])

        architecture_plan_json = self._load_approved_architecture_plan(feature_id)

        if architecture_plan_json is None:
            raise ValueError(
                "No approved Architecture Plan (or legacy SDS) JSON artifact found. "
                "Approve Architecture Agent output before running UI/UX Agent."
            )

        design_system_json = uiux_design_system_service.load(project["project_id"])

        agent_input = UIUXAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_plan_json=architecture_plan_json,
            design_system_json=design_system_json,
            ui_preferences=request.ui_preferences,
            human_comment=request.human_comment,
        )

        ui_metadata_json, raw_llm_output = await self._generate_and_validate_metadata(agent_input)

        component_files, page_component_order = await self._generate_components(
            agent_input, ui_metadata_json
        )

        page_html_files, page_screenshots = await self._assemble_and_render_pages(
            ui_metadata_json, component_files, page_component_order
        )

        integration_manifest_json = uiux_integration_manifest_builder.build(ui_metadata_json)
        ui_design_markdown = uiux_markdown_builder.build(
            feature_name=feature["feature_name"],
            ui_metadata_json=ui_metadata_json,
            integration_manifest_json=integration_manifest_json,
        )

        output = UIUXAgentOutput(
            ui_metadata_json=ui_metadata_json,
            component_files=component_files,
            page_html_files=page_html_files,
            page_screenshots=page_screenshots,
            integration_manifest_json=integration_manifest_json,
            ui_design_markdown=ui_design_markdown,
            raw_llm_output=raw_llm_output,
        )

        artifact_ids, version = self._save_artifacts(project=dict(project), feature=dict(feature), output=output)
        output.artifact_ids = artifact_ids

        logger.info(
            "UI/UX Agent completed for feature_id=%s artifacts=%s",
            feature_id,
            output.artifact_ids,
        )

        return output

    async def run_stream(self, feature_id: str, request: UIUXAgentRunRequest):
        """
        Streaming variant of run() -- same NDJSON event shape as DomainAgent.run_stream/
        ArchitectureAgent.run_stream (see those methods' own docstrings): the ui_metadata_json
        "types" in live instead of a blocking wait. Streams only the initial metadata-generation
        LLM call; the JSON-parse repair (on malformed output) and the coverage/structure
        validation repair loop (_validate_metadata_with_repair) are non-streamed, same as every
        other agent's streaming variant in this codebase -- only the primary generation is live,
        rarely-hit repair rungs are not. Component generation and page assembly are reported via
        {"type": "phase"} events, the same mechanism Architecture Agent uses for its own
        non-streamable tail (diagram generation/rendering).

        UI/UX Agent has no deterministic fallback by design (see module docstring: a guessed-at
        UI plan is worse than none) -- unlike Domain/Architecture Agent's run_stream, if metadata
        generation and every repair attempt fail, this yields an error event rather than falling
        back to synthesized content.

        Events:
            {"type": "token", "text": "..."}
            {"type": "phase", "phase": "...", "label": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "message": "..."}
        """

        logger.info("UI/UX Agent (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.JSON,
        )
        if not srs_artifact:
            yield {
                "type": "error",
                "message": (
                    "No approved SRS JSON artifact found. "
                    "Approve Requirement Agent SRS JSON before running UI/UX Agent."
                ),
            }
            return

        srs_json = read_json_file(srs_artifact["file_path"])

        enhanced_srs_json = None
        if request.use_enhanced_srs_if_available:
            enhanced_srs_artifact = self._find_latest_approved_artifact(
                feature_id=feature_id,
                agent_name=AgentName.DOMAIN,
                artifact_type=ArtifactType.ENHANCED_SRS,
                artifact_format=ArtifactFormat.JSON,
            )
            if enhanced_srs_artifact:
                enhanced_srs_json = read_json_file(enhanced_srs_artifact["file_path"])

        architecture_plan_json = self._load_approved_architecture_plan(feature_id)
        if architecture_plan_json is None:
            yield {
                "type": "error",
                "message": (
                    "No approved Architecture Plan (or legacy SDS) JSON artifact found. "
                    "Approve Architecture Agent output before running UI/UX Agent."
                ),
            }
            return

        design_system_json = uiux_design_system_service.load(project["project_id"])

        agent_input = UIUXAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_plan_json=architecture_plan_json,
            design_system_json=design_system_json,
            ui_preferences=request.ui_preferences,
            human_comment=request.human_comment,
        )

        provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)
        prompt = build_uiux_metadata_user_prompt(
            project=agent_input.project,
            feature=agent_input.feature,
            srs_json=agent_input.srs_json,
            enhanced_srs_json=agent_input.enhanced_srs_json,
            architecture_plan_json=agent_input.architecture_plan_json,
            design_system_json=agent_input.design_system_json,
            ui_preferences=agent_input.ui_preferences,
            human_comment=agent_input.human_comment,
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=UIUX_METADATA_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed UI/UX metadata generation failed mid-stream for feature_id=%s: %s",
                feature_id, stream_error,
            )

        raw_output = "".join(raw_chunks)

        try:
            ui_metadata_json = self.metadata_modeler._extract_json_object(raw_output)
        except ValueError as parse_error:
            logger.warning(
                "Streamed UI/UX metadata failed to parse for feature_id=%s: %s -- attempting repair.",
                feature_id, parse_error,
            )
            try:
                # repair_until_valid gives this several real repair rounds (not just one) --
                # see metadata_modeler.py's module docstring for the real failure this fixes.
                ui_metadata_json, raw_output = await self.metadata_modeler.repair_until_valid(
                    raw_output, provider
                )
            except UIMetadataGenerationError as repair_error:
                logger.warning(
                    "Streamed UI/UX metadata repair also failed for feature_id=%s: %s",
                    feature_id, repair_error,
                )
                yield {
                    "type": "error",
                    "message": str(repair_error),
                }
                return

        yield {"type": "phase", "phase": "validating", "label": "Checking coverage against the approved SRS..."}

        srs_for_validation = agent_input.enhanced_srs_json or agent_input.srs_json

        try:
            ui_metadata_json, raw_output = await self._validate_metadata_with_repair(
                ui_metadata_json, raw_output, srs_for_validation
            )
        except UIMetadataValidationError as validation_error:
            yield {
                "type": "error",
                "message": (
                    f"UI/UX Agent's generated plan did not pass coverage validation after "
                    f"repair attempts: {validation_error}"
                ),
            }
            return

        yield {"type": "phase", "phase": "components", "label": "Generating components (HTML + Tailwind)..."}

        component_files, page_component_order = await self._generate_components(agent_input, ui_metadata_json)

        yield {"type": "phase", "phase": "assembly", "label": "Assembling pages and rendering previews..."}

        page_html_files, page_screenshots = await self._assemble_and_render_pages(
            ui_metadata_json, component_files, page_component_order
        )

        integration_manifest_json = uiux_integration_manifest_builder.build(ui_metadata_json)
        ui_design_markdown = uiux_markdown_builder.build(
            feature_name=feature["feature_name"],
            ui_metadata_json=ui_metadata_json,
            integration_manifest_json=integration_manifest_json,
        )

        output = UIUXAgentOutput(
            ui_metadata_json=ui_metadata_json,
            component_files=component_files,
            page_html_files=page_html_files,
            page_screenshots=page_screenshots,
            integration_manifest_json=integration_manifest_json,
            ui_design_markdown=ui_design_markdown,
            raw_llm_output=raw_output,
        )

        artifact_ids, version = self._save_artifacts(project=dict(project), feature=dict(feature), output=output)

        logger.info(
            "UI/UX Agent (streamed) completed for feature_id=%s artifacts=%s",
            feature_id, artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": "UI/UX Agent completed. Pages, components, and previews were generated.",
        }

    async def _generate_and_validate_metadata(
        self, agent_input: UIUXAgentInput
    ) -> tuple[dict[str, Any], str]:
        ui_metadata_json, raw_llm_output = await self.metadata_modeler.generate(
            project=agent_input.project,
            feature=agent_input.feature,
            srs_json=agent_input.srs_json,
            enhanced_srs_json=agent_input.enhanced_srs_json,
            architecture_plan_json=agent_input.architecture_plan_json,
            design_system_json=agent_input.design_system_json,
            ui_preferences=agent_input.ui_preferences,
            human_comment=agent_input.human_comment,
        )

        srs_for_validation = agent_input.enhanced_srs_json or agent_input.srs_json

        return await self._validate_metadata_with_repair(ui_metadata_json, raw_llm_output, srs_for_validation)

    async def _validate_metadata_with_repair(
        self, ui_metadata_json: dict[str, Any], raw_llm_output: str, srs_for_validation: dict
    ) -> tuple[dict[str, Any], str]:
        """
        Coverage/structure validation with a bounded repair loop -- factored out of
        _generate_and_validate_metadata so run_stream can reuse the exact same repair ladder
        starting from an already-obtained (ui_metadata_json, raw_llm_output) pair (e.g. from a
        streamed initial call) instead of generating one itself.
        """

        last_error: UIMetadataValidationError | None = None

        for attempt in range(1, self.MAX_VALIDATION_REPAIR_ATTEMPTS + 2):  # +1 initial, +1 inclusive range
            try:
                self.metadata_validator.validate(srs_for_validation, ui_metadata_json)
                return ui_metadata_json, raw_llm_output

            except UIMetadataValidationError as error:
                last_error = error

                if attempt > self.MAX_VALIDATION_REPAIR_ATTEMPTS:
                    break

                logger.warning(
                    "UI metadata validation failed (repair attempt %s/%s): %s",
                    attempt, self.MAX_VALIDATION_REPAIR_ATTEMPTS, error
                )

                ui_metadata_json, raw_llm_output = await self.metadata_modeler.repair_for_validation(
                    raw_llm_output, str(error)
                )

        # No fallback here by design (see module docstring) -- once repair attempts are
        # exhausted, fail loudly rather than proceed with a guessed-at UI plan.
        raise last_error

    async def _generate_components(
        self,
        agent_input: UIUXAgentInput,
        ui_metadata_json: dict[str, Any],
        touched_components: set[str] | None = None,
        carry_over_version: int | None = None,
    ) -> tuple[dict[str, str], dict[str, list[str]]]:
        """
        Generate every component's HTML fragment, one LLM call per component. A freshly
        generated fragment that fails the deterministic content-quality gate
        (component_generator.detect_placeholder_content) gets up to
        MAX_CONTENT_QUALITY_REPAIR_ATTEMPTS targeted repairs, the exact violation fed back each
        time -- this is what structurally prevents the real, confirmed "Unknown state."/"No data
        available" bug class from ever reaching a saved artifact (see component_generator.py's
        module docstring for the full root-cause story this replaces).

        touched_components/carry_over_version are set ONLY by revise()/revise_stream() (run()/
        run_stream() leave both None, preserving this method's original fresh-generation
        behavior exactly): when touched_components is not None, this is a revision -- a
        component NOT in that set is carried over VERBATIM from carry_over_version's own saved
        artifact instead of being regenerated (falling through to fresh generation only if that
        lookup unexpectedly finds nothing), and the "reused_from_design_system" cross-feature
        lookup is skipped entirely (it only makes sense for a brand-new run, not a revision of an
        already-generated feature).

        Returns:
            component_files: component name -> HTML fragment source text
            page_component_order: page_id -> [component_name, ...] in the same order
                ui_metadata_json.pages[].components already lists them (the order page assembly
                renders them in).
        """

        data_entities = (
            agent_input.architecture_plan_json.get("design_views", {})
            .get("data_view", {})
            .get("data_entities", [])
        )
        # Chosen ONCE by the metadata step (see UIUX_METADATA_SYSTEM_PROMPT rule 10), not
        # re-decided per component -- this is what keeps every component on every page of this
        # feature visually consistent instead of each independent LLM call picking its own accent
        # color. "indigo" is a safe, reasonable default if the model ever omits the field --
        # deliberately not a validator/repair-loop concern, since a missing color_theme is
        # cosmetic, not a correctness failure.
        color_theme = ui_metadata_json.get("color_theme") or "indigo"

        is_revision = touched_components is not None
        feature_id = agent_input.feature.get("feature_id")

        component_files: dict[str, str] = {}
        page_component_order: dict[str, list[str]] = {}

        for page in ui_metadata_json.get("pages", []):
            ordered_names: list[str] = []

            for component_metadata in page.get("components", []) or []:
                component_name = component_metadata["name"]
                ordered_names.append(component_name)

                if is_revision and component_name not in touched_components:
                    carried_html = self._load_component_html_by_name(
                        feature_id, carry_over_version, component_name
                    )
                    if carried_html is not None:
                        component_files[component_name] = carried_html
                        continue

                    logger.warning(
                        "Revision: could not find prior HTML for untouched component '%s' at "
                        "version %s -- generating it fresh instead.",
                        component_name, carry_over_version,
                    )

                elif not is_revision and component_metadata.get("reused_from_design_system"):
                    reused_html = self._load_existing_approved_component(
                        agent_input.project["project_id"], component_name
                    )

                    if reused_html is not None:
                        component_files[component_name] = reused_html
                        continue

                    logger.warning(
                        "Component '%s' was flagged reused_from_design_system=True but no "
                        "approved component with that name exists yet in this project -- "
                        "generating it instead.",
                        component_name,
                    )

                component_files[component_name] = await self._generate_component_with_quality_gate(
                    agent_input, page, component_metadata, data_entities, color_theme
                )

            page_component_order[page["page_id"]] = ordered_names

        return component_files, page_component_order

    def _load_component_html_by_name(
        self, feature_id: str, version: int | None, component_name: str
    ) -> str | None:
        """
        Read a specific PRIOR version's saved UI_COMPONENT_CODE artifact for this exact
        component name, for the "carry untouched components over verbatim" side of a revision --
        matches the same filename slug convention _save_artifacts writes
        ("{feature_slug}_{component_slug}_v{version}.html"), scoped to this feature and exact
        version (unlike _load_existing_approved_component, which searches ANY approved version
        across the whole project for cross-feature reuse -- a different purpose).
        """

        if version is None:
            return None

        slug = self._slug(component_name)
        marker = f"_{slug}_v{version}.html"

        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue
            if artifact.get("agent_name") not in [AgentName.UIUX, AgentName.UIUX.value]:
                continue
            if artifact.get("artifact_type") not in [
                ArtifactType.UI_COMPONENT_CODE, ArtifactType.UI_COMPONENT_CODE.value,
            ]:
                continue
            if artifact.get("version") != version:
                continue
            if not str(artifact.get("file_path", "")).endswith(marker):
                continue

            return Path(artifact["file_path"]).read_text(encoding="utf-8")

        return None

    async def _generate_component_with_quality_gate(
        self,
        agent_input: UIUXAgentInput,
        page: dict[str, Any],
        component_metadata: dict[str, Any],
        data_entities: list,
        color_theme: str = "indigo",
    ) -> str:
        """
        Generate one component's HTML fragment, then enforce the content-quality gate with a
        bounded, targeted repair loop. Raises ComponentGenerationError (same "fail loudly rather
        than save something known-broken" philosophy already used by metadata validation, see
        _generate_and_validate_metadata) if the violation survives every repair attempt --
        an artifact a human reviews and the Coder Agent later reads as a visual reference must
        never silently contain a placeholder/empty state.
        """

        generated, _raw = await self.component_generator.generate(
            project=agent_input.project,
            feature=agent_input.feature,
            page_metadata=page,
            component_metadata=component_metadata,
            data_entities=data_entities,
            design_system_json=agent_input.design_system_json,
            ui_preferences=agent_input.ui_preferences,
            human_comment=agent_input.human_comment,
            color_theme=color_theme,
        )
        html_code = generated["html_code"]
        component_name = component_metadata.get("name", "unknown")

        for attempt in range(1, self.MAX_CONTENT_QUALITY_REPAIR_ATTEMPTS + 1):
            violation = self.component_generator.detect_placeholder_content(html_code)
            if violation is None:
                return html_code

            logger.warning(
                "Component '%s' failed the content quality gate (repair attempt %s/%s): %s",
                component_name, attempt, self.MAX_CONTENT_QUALITY_REPAIR_ATTEMPTS, violation,
            )
            repaired, _raw = await self.component_generator.repair(html_code, violation)
            html_code = repaired["html_code"]

        final_violation = self.component_generator.detect_placeholder_content(html_code)
        if final_violation:
            raise ComponentGenerationError(
                f"Component '{component_name}' still fails the content quality gate after "
                f"{self.MAX_CONTENT_QUALITY_REPAIR_ATTEMPTS} repair attempts: {final_violation}"
            )

        return html_code

    async def _assemble_and_render_pages(
        self,
        ui_metadata_json: dict[str, Any],
        component_files: dict[str, str],
        page_component_order: dict[str, list[str]],
        touched_components: set[str] | None = None,
        carry_over_version: int | None = None,
        feature_id: str | None = None,
    ) -> tuple[dict[str, str], dict[str, bytes]]:
        """
        Deterministically assemble each page's ordered component fragments into one full,
        self-contained HTML document (page_html_builder -- pure string concatenation, cannot
        fail) -- this is the artifact a human previews live and the Coder Agent later reads as a
        visual reference. Then attempt a best-effort PNG screenshot of it for the "Page Previews"
        thumbnail gallery. Playwright's sync API is used inside preview_renderer.py, so it is
        called via asyncio.to_thread here -- it cannot run inside this already-running event loop.

        Unlike the old JSX-mounting render path, a screenshot failure here has nothing left to
        repair: the content-quality gate in _generate_components already guarantees real,
        populated content before this step ever runs, so a render failure at this point would be
        an environmental/Playwright issue, not a content problem a regeneration could fix. It is
        simply skipped and logged (not fatal to the run) if it happens.

        touched_components/carry_over_version/feature_id are set ONLY by revise()/revise_stream(),
        mirroring _generate_components' own revision-only parameters exactly: when
        touched_components is not None, a page whose components are ALL untouched (no real content
        change) is guaranteed to reassemble to byte-identical HTML, so its screenshot is carried
        over verbatim from carry_over_version instead of re-rendered -- Playwright rendering is the
        single slowest step in this pipeline, and re-running it for pages nothing actually changed
        on contradicts this agent's own "only regenerate what's touched" revision philosophy.
        Falls through to a fresh render if no prior screenshot is found (matches
        _generate_components' own carry-over-miss fallback).
        """

        page_metadata_by_id = {page["page_id"]: page for page in ui_metadata_json.get("pages", [])}

        page_html_files: dict[str, str] = {}
        page_screenshots: dict[str, bytes] = {}

        for page_id, component_names in page_component_order.items():
            page_metadata = page_metadata_by_id.get(page_id, {"page_id": page_id})
            fragments = [component_files[name] for name in component_names if name in component_files]

            page_html = uiux_page_html_builder.build(page_metadata, fragments)
            page_html_files[page_id] = page_html

            page_is_untouched = (
                touched_components is not None
                and not any(name in touched_components for name in component_names)
            )

            if page_is_untouched:
                carried_png = self._load_page_screenshot_by_id(feature_id, carry_over_version, page_id)
                if carried_png is not None:
                    page_screenshots[page_id] = carried_png
                    continue

                logger.warning(
                    "Revision: could not find prior screenshot for untouched page '%s' at "
                    "version %s -- rendering it fresh instead.",
                    page_id, carry_over_version,
                )

            try:
                page_screenshots[page_id] = await asyncio.to_thread(
                    uiux_preview_renderer.render_page_png, page_html
                )
            except PreviewRenderError as error:
                logger.error(
                    "Preview screenshot failed for page_id=%s -- skipping its thumbnail, "
                    "continuing without it (the live HTML preview is unaffected): %s",
                    page_id, error,
                )

        return page_html_files, page_screenshots

    def _load_page_screenshot_by_id(
        self, feature_id: str | None, version: int | None, page_id: str
    ) -> bytes | None:
        """
        Read a specific PRIOR version's saved UI_PREVIEW_SCREENSHOT artifact for this exact page,
        for the "carry an untouched page's screenshot over verbatim" side of a revision -- mirrors
        _load_component_html_by_name exactly, matching the same filename slug convention
        _save_artifacts writes ("{feature_slug}_{page_slug}_v{version}.png").
        """

        if not feature_id or version is None:
            return None

        slug = self._slug(page_id)
        marker = f"_{slug}_v{version}.png"

        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue
            if artifact.get("agent_name") not in [AgentName.UIUX, AgentName.UIUX.value]:
                continue
            if artifact.get("artifact_type") not in [
                ArtifactType.UI_PREVIEW_SCREENSHOT, ArtifactType.UI_PREVIEW_SCREENSHOT.value,
            ]:
                continue
            if artifact.get("version") != version:
                continue
            if not str(artifact.get("file_path", "")).endswith(marker):
                continue

            return Path(artifact["file_path"]).read_bytes()

        return None

    def _load_existing_approved_component(self, project_id: str, component_name: str) -> str | None:
        """
        Look up an already-approved component .html fragment from ANY feature in
        this project (not just the current one) by name, and return its
        exact content verbatim.

        This is what makes "reused_from_design_system: true" an actual reuse
        mechanism instead of just a label the model writes down while a
        fresh (and possibly drifted) copy gets generated anyway -- the
        precise bug this method fixes, found during M8's real second-feature
        test (Signup correctly flagged LoginForm as reused, but nothing
        previously stopped a brand-new LoginForm.jsx from being generated).
        """
        slug = self._slug(component_name)

        matching = []

        for artifact in store.artifacts.values():
            if artifact.get("project_id") != project_id:
                continue
            if artifact.get("agent_name") not in [AgentName.UIUX, AgentName.UIUX.value]:
                continue
            if artifact.get("artifact_type") not in [
                ArtifactType.UI_COMPONENT_CODE,
                ArtifactType.UI_COMPONENT_CODE.value,
            ]:
                continue
            if artifact.get("artifact_format") not in [ArtifactFormat.HTML, ArtifactFormat.HTML.value]:
                continue
            if artifact.get("approval_status") not in [
                ApprovalStatus.APPROVED,
                ApprovalStatus.APPROVED.value,
            ]:
                continue
            if slug not in str(artifact.get("file_path", "")).lower():
                continue

            matching.append(artifact)

        if not matching:
            return None

        latest = max(matching, key=lambda item: item.get("version", 1))
        return Path(latest["file_path"]).read_text(encoding="utf-8")

    def _save_artifacts(self, project: dict, feature: dict, output: UIUXAgentOutput) -> tuple[list[str], int]:
        """
        Save all UI/UX Agent artifacts for this run, all sharing one version
        number (mirrors architecture_agent's markdown+json+diagrams pattern).

        Every artifact is saved PENDING (the default) -- per direct user request, human approval
        is required again: only a human clicking Approve on the Preview Screenshot decides the
        output is good (see approval_service.py's UI/UX cascade, which then triggers
        apply_design_system_patch -- never called directly from this class).

        Returns (artifact_ids, version) -- the version is needed by callers that also need to know
        which version this save produced (e.g. for logging or a follow-up lookup).
        """

        version = artifact_service.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=AgentName.UIUX,
            artifact_type=ArtifactType.UI_METADATA,
        )

        feature_slug = self._feature_slug(feature)
        artifact_ids: list[str] = []

        metadata_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.UIUX,
            artifact_type=ArtifactType.UI_METADATA,
            filename=f"{feature_slug}_ui_metadata_v{{version}}.json",
            data=output.ui_metadata_json,
            version_override=version,
        )
        artifact_ids.append(metadata_artifact.artifact_id)

        manifest_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.UIUX,
            artifact_type=ArtifactType.UI_INTEGRATION_MANIFEST,
            filename=f"{feature_slug}_integration_manifest_v{{version}}.json",
            data=output.integration_manifest_json,
            version_override=version,
        )
        artifact_ids.append(manifest_artifact.artifact_id)

        markdown_artifact = artifact_service.save_text_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.UIUX,
            artifact_type=ArtifactType.UI_METADATA,
            artifact_format=ArtifactFormat.MARKDOWN,
            filename=f"{feature_slug}_ui_design_v{{version}}.md",
            content=output.ui_design_markdown,
            version_override=version,
        )
        artifact_ids.append(markdown_artifact.artifact_id)

        for component_name, html_code in output.component_files.items():
            component_slug = self._slug(component_name)
            component_artifact = artifact_service.save_text_artifact(
                project=project,
                feature=feature,
                agent_name=AgentName.UIUX,
                artifact_type=ArtifactType.UI_COMPONENT_CODE,
                artifact_format=ArtifactFormat.HTML,
                filename=f"{feature_slug}_{component_slug}_v{{version}}.html",
                content=html_code,
                version_override=version,
            )
            artifact_ids.append(component_artifact.artifact_id)

        for page_id, page_html in output.page_html_files.items():
            page_slug = self._slug(page_id)
            page_html_artifact = artifact_service.save_text_artifact(
                project=project,
                feature=feature,
                agent_name=AgentName.UIUX,
                artifact_type=ArtifactType.UI_PAGE_HTML,
                artifact_format=ArtifactFormat.HTML,
                filename=f"{feature_slug}_{page_slug}_page_v{{version}}.html",
                content=page_html,
                version_override=version,
            )
            artifact_ids.append(page_html_artifact.artifact_id)

        for page_id, png_bytes in output.page_screenshots.items():
            page_slug = self._slug(page_id)
            screenshot_artifact = artifact_service.save_binary_artifact(
                project=project,
                feature=feature,
                agent_name=AgentName.UIUX,
                artifact_type=ArtifactType.UI_PREVIEW_SCREENSHOT,
                artifact_format=ArtifactFormat.PNG,
                filename=f"{feature_slug}_{page_slug}_v{version}.png",
                binary_content=png_bytes,
                # Real, confirmed bug fixed here: save_binary_artifact previously had no
                # version_override support (unlike the other 3 save methods above, which all
                # correctly share this run's one `version`) -- its own internal get_next_version()
                # call incremented on every page saved within the SAME run, so multiple pages'
                # screenshots ended up as separate versions (v1, v2, v3...) instead of one shared
                # version. Now consistent with every other artifact this method saves.
                version_override=version,
            )
            artifact_ids.append(screenshot_artifact.artifact_id)

        return artifact_ids, version

    def apply_design_system_patch(self, feature_id: str, version: int) -> None:
        """
        Merge new components/tokens from a UI/UX run into the project's shared
        design_system.json.

        Called directly and unconditionally by run()/run_stream()/revise()/revise_stream() at
        the end of every generation -- no longer approval-triggered (previously called from
        approval_service.py only after a human approved the run's screenshot; there is no more
        human approval step for this stage at all, see _save_artifacts' own docstring).
        """

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        metadata_artifact = self._find_artifact_by_version(
            feature_id=feature_id,
            agent_name=AgentName.UIUX,
            artifact_type=ArtifactType.UI_METADATA,
            artifact_format=ArtifactFormat.JSON,
            version=version,
        )

        if not metadata_artifact:
            logger.warning(
                "apply_design_system_patch: no ui_metadata artifact found for "
                "feature_id=%s version=%s -- skipping.",
                feature_id,
                version,
            )
            return

        ui_metadata_json = read_json_file(metadata_artifact["file_path"])
        design_system_json = project_memory_service.load_design_system(project["project_id"])

        design_system_json.setdefault("components", {})
        design_system_json.setdefault("tokens", {})

        new_component_count = 0
        new_token_count = 0

        for page in ui_metadata_json.get("pages", []):
            for component in page.get("components", []) or []:
                if component.get("reused_from_design_system"):
                    continue

                name = component.get("name")
                if not name or name in design_system_json["components"]:
                    continue

                design_system_json["components"][name] = {
                    "content_elements": component.get("content_elements") or [],
                    "introduced_by_feature": feature["feature_name"],
                }
                new_component_count += 1

            for token in page.get("new_design_tokens", []) or []:
                token_name = token.get("token")
                if not token_name or token_name in design_system_json["tokens"]:
                    continue

                design_system_json["tokens"][token_name] = {
                    "value": token.get("value"),
                    "introduced_by_feature": feature["feature_name"],
                }
                new_token_count += 1

        if new_component_count or new_token_count:
            project_memory_service.save_design_system(project["project_id"], design_system_json)

        logger.info(
            "apply_design_system_patch: feature_id=%s version=%s merged %d new components, "
            "%d new tokens.",
            feature_id,
            version,
            new_component_count,
            new_token_count,
        )

    async def revise(self, feature_id: str, request: UIUXAgentReviseRequest) -> UIUXAgentOutput:
        """
        Revise the latest UI/UX output for a feature via a small, explicit human-directed change.

        Unlike run() (a fresh generation), this loads the CURRENT ui_metadata_json, asks the LLM
        for a SMALL ops plan describing exactly what should change (mirrors the same "small ops
        plan + deterministic patcher" pattern already proven for Requirement/Architecture/Domain
        Agent's own revisions -- see revision_patcher.py's module docstring), applies it
        deterministically, and only regenerates the HTML of components the plan actually touched
        -- every other component is carried over verbatim from the prior version. This is what
        makes a revision a real, targeted change rather than a full, silent regeneration.
        """

        logger.info("UI/UX Agent revision started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        metadata_artifact = self._find_latest_uiux_artifact(feature_id, ArtifactType.UI_METADATA)
        if not metadata_artifact:
            raise ValueError(
                "No existing UI/UX output found. Run UI/UX Agent first before requesting a revision."
            )

        current_ui_metadata_json = read_json_file(metadata_artifact["file_path"])
        current_version = metadata_artifact.get("version", 1)

        agent_input = self._build_revision_agent_input(project, feature, request.revision_comment)

        provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)
        prompt = build_uiux_revision_prompt(
            project=agent_input.project,
            feature=agent_input.feature,
            current_ui_metadata_json=current_ui_metadata_json,
            revision_comment=request.revision_comment,
            revised_by=request.revised_by,
            target_page_ids=request.target_page_ids,
        )

        raw_output = await provider.invoke_agent([
            {"role": "system", "content": UIUX_REVISION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])

        revision_plan = await self._resolve_uiux_revision_plan(provider, raw_output)

        patched_metadata, touched_components = self._prepare_revision(
            current_ui_metadata_json, revision_plan, request.revision_comment, request.revised_by,
            target_page_ids=request.target_page_ids,
        )

        component_files, page_component_order = await self._generate_components(
            agent_input, patched_metadata, touched_components=touched_components, carry_over_version=current_version
        )

        page_html_files, page_screenshots = await self._assemble_and_render_pages(
            patched_metadata, component_files, page_component_order,
            touched_components=touched_components, carry_over_version=current_version, feature_id=feature_id,
        )

        integration_manifest_json = uiux_integration_manifest_builder.build(patched_metadata)
        ui_design_markdown = uiux_markdown_builder.build(
            feature_name=feature["feature_name"],
            ui_metadata_json=patched_metadata,
            integration_manifest_json=integration_manifest_json,
        )

        output = UIUXAgentOutput(
            ui_metadata_json=patched_metadata,
            component_files=component_files,
            page_html_files=page_html_files,
            page_screenshots=page_screenshots,
            integration_manifest_json=integration_manifest_json,
            ui_design_markdown=ui_design_markdown,
            raw_llm_output=raw_output,
        )

        artifact_ids, version = self._save_artifacts(project=dict(project), feature=dict(feature), output=output)
        output.artifact_ids = artifact_ids

        logger.info(
            "UI/UX Agent revision completed for feature_id=%s artifacts=%s",
            feature_id, artifact_ids,
        )

        return output

    async def revise_stream(self, feature_id: str, request: UIUXAgentReviseRequest):
        """
        Streaming variant of revise() -- same event shape/tail as run_stream (see that method's
        own docstring). Streams the small ops-plan LLM call live, then yields {"type": "phase"}
        events for the non-streamable tail (component regeneration for only the touched
        components, then page reassembly/rendering).

        Events:
            {"type": "token", "text": "..."}
            {"type": "phase", "phase": "...", "label": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "message": "..."}
        """

        logger.info("UI/UX Agent revision (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        metadata_artifact = self._find_latest_uiux_artifact(feature_id, ArtifactType.UI_METADATA)
        if not metadata_artifact:
            yield {
                "type": "error",
                "message": "No existing UI/UX output found. Run UI/UX Agent first before requesting a revision.",
            }
            return

        current_ui_metadata_json = read_json_file(metadata_artifact["file_path"])
        current_version = metadata_artifact.get("version", 1)

        agent_input = self._build_revision_agent_input(project, feature, request.revision_comment)

        provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)
        prompt = build_uiux_revision_prompt(
            project=agent_input.project,
            feature=agent_input.feature,
            current_ui_metadata_json=current_ui_metadata_json,
            revision_comment=request.revision_comment,
            revised_by=request.revised_by,
            target_page_ids=request.target_page_ids,
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=UIUX_REVISION_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed UI/UX revision failed mid-stream for feature_id=%s: %s",
                feature_id, stream_error,
            )

        raw_output = "".join(raw_chunks)
        revision_plan = await self._resolve_uiux_revision_plan(provider, raw_output)

        patched_metadata, touched_components = self._prepare_revision(
            current_ui_metadata_json, revision_plan, request.revision_comment, request.revised_by,
            target_page_ids=request.target_page_ids,
        )

        yield {"type": "phase", "phase": "components", "label": "Updating affected components..."}

        component_files, page_component_order = await self._generate_components(
            agent_input, patched_metadata, touched_components=touched_components, carry_over_version=current_version
        )

        yield {"type": "phase", "phase": "assembly", "label": "Reassembling pages and rendering previews..."}

        page_html_files, page_screenshots = await self._assemble_and_render_pages(
            patched_metadata, component_files, page_component_order,
            touched_components=touched_components, carry_over_version=current_version, feature_id=feature_id,
        )

        integration_manifest_json = uiux_integration_manifest_builder.build(patched_metadata)
        ui_design_markdown = uiux_markdown_builder.build(
            feature_name=feature["feature_name"],
            ui_metadata_json=patched_metadata,
            integration_manifest_json=integration_manifest_json,
        )

        output = UIUXAgentOutput(
            ui_metadata_json=patched_metadata,
            component_files=component_files,
            page_html_files=page_html_files,
            page_screenshots=page_screenshots,
            integration_manifest_json=integration_manifest_json,
            ui_design_markdown=ui_design_markdown,
            raw_llm_output=raw_output,
        )

        artifact_ids, version = self._save_artifacts(project=dict(project), feature=dict(feature), output=output)

        logger.info(
            "UI/UX Agent revision (streamed) completed for feature_id=%s artifacts=%s",
            feature_id, artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": "UI/UX Agent revision completed. Only the affected components were regenerated.",
        }

    def _build_revision_agent_input(self, project: dict, feature: dict, human_comment: str | None) -> UIUXAgentInput:
        """
        Build a minimal UIUXAgentInput for a revision -- srs_json/enhanced_srs_json are not
        needed (revision never re-generates ui_metadata_json's coverage from scratch, only
        patches it), but architecture_plan_json (for data entity fields) and design_system_json
        are still loaded fresh so component regeneration has the same real context run() uses.
        """

        architecture_plan_json = self._load_approved_architecture_plan(feature["feature_id"]) or {}
        design_system_json = uiux_design_system_service.load(project["project_id"])

        return UIUXAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json={},
            enhanced_srs_json=None,
            architecture_plan_json=architecture_plan_json,
            design_system_json=design_system_json,
            ui_preferences={},
            human_comment=human_comment,
        )

    def _prepare_revision(
        self,
        current_ui_metadata_json: dict,
        revision_plan: dict,
        revision_comment: str,
        revised_by: str | None,
        target_page_ids: list[str] | None = None,
    ) -> tuple[dict, set[str]]:
        """
        Deterministically apply a revision plan's operations to a copy of the current
        ui_metadata_json, returning the patched metadata (with revision_metadata stamped) and the
        set of component names that need fresh HTML generation (added/modified by this revision).
        Never raises -- operations that match nothing (including anything outside
        target_page_ids, see revision_patcher.py's allowed_page_ids enforcement) just produce an
        honest, unchanged result with the reason recorded in revision_metadata (see
        apply_uiux_revision_operations' own "report, don't guess" contract).
        """

        operations = revision_plan.get("operations", [])
        allowed_page_ids = set(target_page_ids) if target_page_ids else None
        patched_metadata, applied, unmatched = apply_uiux_revision_operations(
            current_ui_metadata_json, operations, allowed_page_ids=allowed_page_ids
        )

        touched_components: set[str] = set()
        for page in patched_metadata.get("pages", []):
            for component in page.get("components", []) or []:
                if component.pop("_revision_touched", False):
                    touched_components.add(component["name"])

        # A genuine color_theme change (see UIUX_REVISION_SYSTEM_PROMPT rule 7) means every
        # surviving component's HTML needs regenerating to match, not just a metadata-field
        # edit -- reuses the exact same "touched -> regenerate" pipeline as an add/modify
        # operation, no separate generation pathway needed. Still respects target_page_ids: only
        # components on a selected page (if any were selected) are marked touched, same
        # "selected screens only" discipline as every other operation.
        new_color_theme = revision_plan.get("color_theme")
        color_theme_changed = bool(new_color_theme) and new_color_theme != patched_metadata.get("color_theme")
        if color_theme_changed:
            patched_metadata["color_theme"] = new_color_theme
            for page in patched_metadata.get("pages", []):
                if allowed_page_ids and page.get("page_id") not in allowed_page_ids:
                    continue
                for component in page.get("components", []) or []:
                    touched_components.add(component["name"])
            applied = [*applied, f"Changed color_theme to '{new_color_theme}' (every component regenerated to match)."]

        revision_metadata = {
            "revision_type": "uiux_revision",
            "revision_summary": revision_plan.get("revision_summary", ""),
            "revision_comment": revision_comment,
            "revised_by": revised_by,
            "applied_changes": applied,
            "unmatched_operations": unmatched,
        }

        if not applied and not operations:
            revision_metadata["no_changes_note"] = (
                revision_plan.get("revision_summary")
                or "No actionable UI change was identified for this request."
            )

        patched_metadata["revision_metadata"] = revision_metadata

        return patched_metadata, touched_components

    async def _resolve_uiux_revision_plan(self, provider, raw_output: str) -> dict:
        """
        Parse the LLM's small revision operations plan, with one JSON-repair attempt on
        structural failure -- mirrors Domain/Architecture Agent's own resolve-with-repair
        pattern. Never raises: a plan that still can't be parsed after repair resolves to an
        honest, empty-operations plan (nothing changes, with a clear reason recorded) rather than
        crashing the whole revision request.
        """

        try:
            return self._parse_uiux_revision_plan(raw_output)
        except ValueError as first_error:
            logger.warning(
                "UI/UX revision plan parse failed: %s -- attempting repair.", first_error
            )

            try:
                repair_prompt = build_uiux_revision_json_repair_prompt(raw_output)
                repaired_output = await provider.invoke_agent([
                    {"role": "system", "content": UIUX_REVISION_JSON_REPAIR_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ])
                return self._parse_uiux_revision_plan(repaired_output)
            except Exception as second_error:
                logger.warning("UI/UX revision plan repair also failed: %s", second_error)
                return {
                    "revision_summary": (
                        f"Could not parse a revision plan from the agent's response: {second_error}"
                    ),
                    "operations": [],
                }

    def _parse_uiux_revision_plan(self, raw_output: str) -> dict:
        cleaned = raw_output.strip()

        cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")

            if start == -1 or end == -1 or end <= start:
                raise ValueError("No JSON object found in UI/UX Agent revision output.")

            parsed = json.loads(cleaned[start:end + 1])

        if not isinstance(parsed, dict):
            raise ValueError("UI/UX Agent revision output must be a JSON object.")

        if not isinstance(parsed.get("operations"), list):
            raise ValueError("Revision output missing required 'operations' list.")

        return parsed

    def _find_latest_uiux_artifact(
        self, feature_id: str, artifact_type: ArtifactType, artifact_format: ArtifactFormat = ArtifactFormat.JSON
    ) -> dict | None:
        """
        Find the latest UI/UX Agent artifact of the given type/format for this feature,
        REGARDLESS of approval status (every UI/UX artifact is always approved now, but this
        stays robust even against legacy pre-migration data) -- a revision must build on the
        latest generated version, mirroring Domain Agent's own
        _find_latest_domain_json_artifact.
        """

        matching_artifacts = []

        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue
            if artifact.get("agent_name") not in [AgentName.UIUX, AgentName.UIUX.value]:
                continue
            if artifact.get("artifact_type") not in [artifact_type, artifact_type.value]:
                continue
            if artifact.get("artifact_format") not in [artifact_format, artifact_format.value]:
                continue

            matching_artifacts.append(artifact)

        if not matching_artifacts:
            return None

        return max(matching_artifacts, key=lambda item: item.get("version", 1))

    def _find_artifact_by_version(
        self,
        feature_id: str,
        agent_name: AgentName,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat,
        version: int,
    ) -> dict | None:
        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue
            if artifact.get("agent_name") not in [agent_name, agent_name.value]:
                continue
            if artifact.get("artifact_type") not in [artifact_type, artifact_type.value]:
                continue
            if artifact.get("artifact_format") not in [artifact_format, artifact_format.value]:
                continue
            if artifact.get("version") != version:
                continue

            return artifact

        return None

    def _load_approved_architecture_plan(self, feature_id: str) -> dict | None:
        """
        Load the approved Architecture Agent design output.

        Tries the current ArtifactType.ARCHITECTURE_PLAN first, then falls
        back to the legacy ArtifactType.SDS -- some approved artifacts predate
        the SDS -> Architecture Plan rename and were never regenerated under
        the new type. Both shapes carry a "design_views" section, which is
        all this agent actually reads.
        """

        artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            agent_name=AgentName.ARCHITECTURE,
            artifact_type=ArtifactType.ARCHITECTURE_PLAN,
            artifact_format=ArtifactFormat.JSON,
        )

        if not artifact:
            artifact = self._find_latest_approved_artifact(
                feature_id=feature_id,
                agent_name=AgentName.ARCHITECTURE,
                artifact_type=ArtifactType.SDS,
                artifact_format=ArtifactFormat.JSON,
            )

        if not artifact:
            return None

        return read_json_file(artifact["file_path"])

    def _find_latest_approved_artifact(
        self,
        feature_id: str,
        agent_name: AgentName,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat,
    ) -> dict | None:
        """
        Find latest approved artifact matching the given filters.
        """

        matching_artifacts = []

        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue
            if artifact.get("agent_name") not in [agent_name, agent_name.value]:
                continue
            if artifact.get("artifact_type") not in [artifact_type, artifact_type.value]:
                continue
            if artifact.get("artifact_format") not in [artifact_format, artifact_format.value]:
                continue
            if artifact.get("approval_status") not in [
                ApprovalStatus.APPROVED,
                ApprovalStatus.APPROVED.value,
            ]:
                continue

            matching_artifacts.append(artifact)

        if not matching_artifacts:
            return None

        return max(matching_artifacts, key=lambda item: item.get("version", 1))

    def _feature_slug(self, feature: dict) -> str:
        return self._slug(feature.get("feature_name", "feature"))

    def _slug(self, value: str) -> str:
        slug = value.lower().strip()
        slug = re.sub(r"[^a-z0-9]+", "_", slug)
        return slug.strip("_") or "item"


uiux_agent = UIUXAgent()
