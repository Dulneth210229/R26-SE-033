"""
Coder Agent planner.

Purpose:
- One-shot LLM call (via llm_provider_service, NOT the agentic model factory --
  this step doesn't need tool calling) that reads the approved SRS,
  Architecture Plan, UI/UX integration manifest, and project manifest, and
  produces code_plan_json: a scoped, traceable list of files to create,
  modify, or delete for exactly one feature.

This plan becomes the task description handed to the agentic coding loop
(M4) -- the loop executes a pre-validated plan rather than improvising
architecture itself.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain.agents import create_agent
from langgraph.errors import GraphRecursionError

from app.agents.coder_agent.prompt import (
    CODE_PLAN_JSON_REPAIR_PROMPT,
    CODE_PLANNER_AGENTIC_REVISION_SYSTEM_PROMPT,
    CODE_PLANNER_SYSTEM_PROMPT,
    build_agentic_revision_planner_user_prompt,
    build_code_plan_repair_prompt,
    build_code_planner_user_prompt,
)
from app.agents.coder_agent.tools import build_revision_planning_tools
from app.core.enums import AgentName
from app.providers.agentic_model_factory import get_agentic_chat_model
from app.services.llm_provider_service import llm_provider_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Read-only exploration (list_dir/read_file/search_code) is cheap -- no
# Docker/npm involved, just filesystem reads -- so this can be generous
# without meaningfully slowing down a revision. Exists purely so a model
# that never calls submit_code_plan can't loop forever.
# Bumped 25 -> 50: a real run against a genuinely vague, multi-file revision
# request ("styles are missing, add tailwind css") used 16 real tool-calling
# turns and still hadn't called submit_code_plan when the original 25-turn
# budget ran out -- the same class of exhaustion CODING_LOOP_RECURSION_LIMIT
# hit and was bumped for (65 -> 100). CodePlanGenerationError from hitting
# this limit is now also caught in _plan_with_retries and treated as a
# recoverable attempt (efficiency-hint retry), not a crash -- the same
# pattern _code_with_retries already uses for GraphRecursionError.
# Bumped 50 -> 80: a real user request against this same project (by then
# grown to ~11+ files across several revisions) exhausted the 50-turn budget
# too. As the project a feature touches grows, "explore everything relevant"
# genuinely costs more turns -- this alone doesn't fully solve that (see the
# prompt's new rule 1b: prefer summarizing tools like check_component_styling
# over reading every candidate file's full content, since only the later
# coding step actually needs that), but a larger budget is still the cheap,
# always-worth-doing half of the fix, since exploration itself is cheap (no
# Docker/npm, just filesystem reads).
REVISION_PLANNING_RECURSION_LIMIT = 80


class CodePlanGenerationError(Exception):
    """Raised when the LLM output could not be parsed into code_plan_json."""


class CodePlanner:
    """
    Generates code_plan_json from approved SRS + Architecture Plan + optional
    UI/UX integration manifest + the project's manifest.
    """

    async def generate(
        self,
        project: dict,
        feature: dict,
        srs_json: dict,
        architecture_plan_json: dict,
        ui_integration_manifest_json: dict | None,
        project_manifest_json: dict,
        human_comment: str | None,
        previous_plan_json: dict | None = None,
        validation_feedback: str | None = None,
        coverage_baseline_files: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """
        Returns (code_plan_json, raw_llm_output).

        previous_plan_json/validation_feedback are set when this is a retry
        after CodePlanValidator rejected an earlier attempt -- the caller
        (CoderAgent.run()) is responsible for the retry loop and budget;
        this method just knows how to build one better-informed attempt.

        coverage_baseline_files: only ever set by CoderAgent.revise()'s fast path (see
        CoderAgent._find_well_specified_target_files) -- the cumulative list of files this
        feature has already touched, so this single-shot call (which otherwise has zero
        visibility into the real codebase) knows which files genuinely already exist and
        should be planned as "modify", not "create" (a wrong "create" would let the coding
        loop's write_file tool silently overwrite real content).
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.CODER.value)

        prompt = build_code_planner_user_prompt(
            project=project,
            feature=feature,
            srs_json=srs_json,
            architecture_plan_json=architecture_plan_json,
            ui_integration_manifest_json=ui_integration_manifest_json,
            project_manifest_json=project_manifest_json,
            human_comment=human_comment,
            previous_plan_json=previous_plan_json,
            validation_feedback=validation_feedback,
            coverage_baseline_files=coverage_baseline_files,
        )

        raw_output = await provider.invoke_agent(
            [
                {"role": "system", "content": CODE_PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        try:
            return self._extract_json_object(raw_output), raw_output
        except ValueError:
            pass

        repaired_output = await provider.invoke_agent(
            [
                {"role": "system", "content": CODE_PLAN_JSON_REPAIR_PROMPT},
                {"role": "user", "content": build_code_plan_repair_prompt(raw_output)},
            ]
        )

        try:
            return self._extract_json_object(repaired_output), repaired_output
        except ValueError as error:
            raise CodePlanGenerationError(
                f"Coder Agent planner could not produce valid code_plan_json after one "
                f"repair attempt: {error}"
            ) from error

    async def generate_via_exploration(
        self,
        *,
        project_id: str,
        feature_id: str,
        project: dict,
        feature: dict,
        srs_json: dict,
        architecture_plan_json: dict,
        ui_integration_manifest_json: dict | None,
        project_manifest_json: dict,
        human_comment: str | None,
        previous_plan_json: dict | None,
        validation_feedback: str | None,
        coverage_baseline_files: list[dict[str, Any]],
        keyword_hint_files: list[str] | None = None,
    ) -> tuple[dict[str, Any], str]:
        """
        Agentic counterpart to generate() -- used only for CoderAgent.revise().

        Unlike generate() (a single-shot LLM call with zero visibility into
        the actual codebase), this gives the model read-only tools
        (list_dir/read_file/search_code/read_project_manifest/
        read_ui_component_design/read_ui_page_design) to look at the real, current feature branch
        before finalizing a plan. This is what lets a vague, file-unspecified
        revision comment (e.g. "styles are missing, add tailwind css") be
        correctly scoped to every actually-affected file, instead of only
        working when the human names each file explicitly.

        The caller MUST have already checked out the correct branch
        (workspace_service.resume_feature_branch) before calling this --
        the tools read whatever is currently on disk.

        keyword_hint_files: an unverified starting-point hint from
        CoderAgent._find_keyword_hint_files -- see
        build_agentic_revision_planner_user_prompt's own docstring for why
        this is never trusted, only offered as a lead the model's own tools
        must confirm or override.

        Returns (code_plan_json, raw_plan_json_string), mirroring generate()'s
        (code_plan_json, raw_output) shape.
        """
        tools, captured = build_revision_planning_tools(project_id, feature_id)

        agent = create_agent(
            model=get_agentic_chat_model(),
            tools=tools,
            system_prompt=CODE_PLANNER_AGENTIC_REVISION_SYSTEM_PROMPT,
        )

        user_prompt = build_agentic_revision_planner_user_prompt(
            project=project,
            feature=feature,
            srs_json=srs_json,
            architecture_plan_json=architecture_plan_json,
            ui_integration_manifest_json=ui_integration_manifest_json,
            project_manifest_json=project_manifest_json,
            human_comment=human_comment,
            previous_plan_json=previous_plan_json,
            validation_feedback=validation_feedback,
            coverage_baseline_files=coverage_baseline_files,
            keyword_hint_files=keyword_hint_files,
        )

        try:
            await agent.ainvoke(
                {"messages": [{"role": "user", "content": user_prompt}]},
                config={"recursion_limit": REVISION_PLANNING_RECURSION_LIMIT},
            )
        except GraphRecursionError:
            pass  # handled uniformly below -- "plan_json" simply won't be in `captured`
        except Exception as error:
            # Any other failure (a transient Ollama/langchain-ollama transport error, a
            # malformed tool call, etc.) -- previously propagated straight out of this method
            # uncaught. Falling through to the same "plan_json not in captured" check below
            # lets the caller (_plan_with_retries) handle it via its existing
            # CodePlanGenerationError retry path uniformly, the same as a turn-limit timeout,
            # instead of needing separate handling for this class of failure.
            logger.warning("Agentic revision planning raised an unexpected error: %s", error)

        if "plan_json" not in captured:
            raise CodePlanGenerationError(
                "Coder Agent's agentic revision planner ended without calling "
                "submit_code_plan (either it stopped early or hit the exploration "
                f"turn limit of {REVISION_PLANNING_RECURSION_LIMIT})."
            )

        raw_output = captured["plan_json"]

        try:
            return self._extract_json_object(raw_output), raw_output
        except ValueError:
            pass

        repaired_output = await llm_provider_service.get_provider(agent_name=AgentName.CODER.value).invoke_agent(
            [
                {"role": "system", "content": CODE_PLAN_JSON_REPAIR_PROMPT},
                {"role": "user", "content": build_code_plan_repair_prompt(raw_output)},
            ]
        )

        try:
            return self._extract_json_object(repaired_output), repaired_output
        except ValueError as error:
            raise CodePlanGenerationError(
                f"Coder Agent's agentic revision planner submitted a plan that could not be "
                f"parsed as valid code_plan_json, even after one repair attempt: {error}"
            ) from error

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()

        cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")

            if start == -1 or end == -1 or end <= start:
                raise ValueError("No JSON object found in Coder Agent planner output.")

            parsed = json.loads(cleaned[start : end + 1])

        if not isinstance(parsed, dict):
            raise ValueError("code_plan_json must be a JSON object.")

        if not isinstance(parsed.get("files"), list) or not parsed["files"]:
            raise ValueError("code_plan_json.files must be a non-empty list.")

        return parsed


code_planner = CodePlanner()
