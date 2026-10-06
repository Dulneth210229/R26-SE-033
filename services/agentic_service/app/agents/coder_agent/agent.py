"""
Coder Agent.

Pipeline:
1. Load context: approved SRS, optional approved Enhanced SRS, approved
   Architecture Plan, optional approved UI/UX integration manifest, and the
   project's manifest.
2. Plan (planner.py), with up to MAX_PLANNING_ATTEMPTS: if plan_validator
   rejects a plan, re-prompt with the specific coverage gap before spending
   any workspace/agentic-loop cost.
3. Prepare workspace: start a fresh feature branch.
4. Code + verify, with up to MAX_CODING_ATTEMPTS: run the agentic coding loop
   (coding_loop.py), commit whatever it wrote, then run the deterministic
   sandboxed build/lint/test gate (verify.py). A failing attempt's failure
   text is fed back into the next coding attempt. If every attempt fails
   verification, proceed anyway with verification_passed=False rather than
   silently retrying forever -- the human still has to explicitly approve,
   and the report makes the failure impossible to miss.
5. Build diff/manifest/setup-instructions deterministically from the real
   git diff (diff_builder.py) -- never from the coding loop's self-report.
6. Save all artifacts for human review.
7. Merge-on-approval / discard-on-rejection happens via
   merge_approved_feature()/discard_rejected_feature(), invoked from
   approval_service.py's approval hook (mirrors UIUXAgent's
   apply_design_system_patch pattern).

See services/agentic_service/instructions .md section 5 for the full plan.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, AsyncGenerator

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.errors import GraphRecursionError

from app.agents.coder_agent import batch_coder
from app.agents.coder_agent.coding_loop import build_coder_react_agent, build_task_message
from app.agents.coder_agent.diff_builder import (
    build_code_manifest,
    build_file_tree,
    build_merge_report_markdown,
    build_requirement_code_map,
    build_setup_instructions_markdown,
)
from app.agents.coder_agent.env_uri import (
    extract_mongodb_uri,
    is_machine_generated_revision,
    is_uri_only,
    strip_uri_from_comment,
)
from app.agents.coder_agent.plan_validator import CodePlanValidationError, code_plan_validator
from app.agents.coder_agent.planner import CodePlanGenerationError, code_planner
from app.agents.coder_agent.revision_file_tokens import (
    REVISION_FILE_TOKEN_RE,
    extract_file_tokens,
    resolve_tokens_against_known_paths,
)
from app.agents.coder_agent.prompt import (
    CODE_PLAN_JSON_REPAIR_PROMPT,
    CODE_PLANNER_SYSTEM_PROMPT,
    build_code_plan_repair_prompt,
    build_code_planner_user_prompt,
    build_implementation_spec_for_single_file,
    build_implementation_spec_section,
)
from app.agents.coder_agent.schemas import CoderAgentEnvSaveResult, CoderAgentInput, CoderAgentOutput
from app.agents.coder_agent.tools import _resolve_within, search_workspace_content
from app.agents.coder_agent.verify import coder_verifier
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.schemas.coder_schema import CoderAgentReviseRequest, CoderAgentRunRequest
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.services.llm_provider_service import llm_provider_service
from app.services import model_capabilities
from app.services.project_memory_service import project_memory_service
from app.services.preview_service import preview_service
from app.services.workspace_service import MAIN_BRANCH, workspace_service
from app.utils.file_manager import read_json_file
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Bumped 2 -> 4. The long-documented "planner under-plans backend files" gap (see CLAUDE.md)
# was retested for real against a fresh feature (QuickCart/Item Management): attempt 1 omitted
# "maps_to" entirely from every file; attempt 2 (after specific feedback) added it but still
# left some endpoints/entities/FR-ids uncovered -- real, incremental convergence identical in
# shape to what UI/UX Agent's metadata validation needed 4 attempts to fully resolve, just cut
# off here at 2 before finishing. The retry loop already does the right thing (exact validation
# error + previous plan + "fix only these gaps" framing, see prompt.py's validation_feedback
# section) -- this was a budget problem, not a prompt-wording problem.
MAX_PLANNING_ATTEMPTS = 4
MAX_CODING_ATTEMPTS = 3
# Bumped 50 -> 65 -> 100. 65 (raised specifically to accommodate the new
# list_unimplemented_planned_files/check_syntax self-check tool calls) still hit
# GraphRecursionError on a real 8-file plan (2 of which were "modify an existing
# component" patches) before the model reached a stop condition -- confirmed via a
# real run against the TaskFlow/Task Comments feature. GraphRecursionError is now
# also caught in _code_with_retries (treated as a failed attempt, not a crash), so
# this limit no longer needs to be exactly right -- just generous enough that a
# realistically-sized plan can usually finish in one attempt.
CODING_LOOP_RECURSION_LIMIT = 100

# Relocated to revision_file_tokens.py (security_finding_coverage_checker.py, imported by
# verify.py, needs the exact same regex/resolution logic -- putting it there instead of here
# avoids a circular import, since agent.py already imports from verify.py). Re-exported under its
# original name so any existing caller importing it from this module keeps working unchanged.
_REVISION_FILE_TOKEN_RE = REVISION_FILE_TOKEN_RE

# Used by _meaningful_stems (Tier 1a/1b's keyword extraction) -- generic English filler words
# PLUS domain-generic words that would match almost every generated Next.js file (page,
# component, file, code, app, feature, function...) and so carry no real distinguishing signal.
# "not" is included because contraction preprocessing (see _split_into_words) turns "doesn't"
# into "does not" -- without it, a negated request ("the button does NOT work") would spuriously
# treat "not" as a keyword.
_KEYWORD_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for", "with", "at", "by",
    "from", "into", "onto", "is", "are", "was", "were", "be", "been", "being", "it", "its",
    "this", "that", "these", "those", "i", "you", "we", "they", "there", "here",
    "add", "adds", "adding", "make", "makes", "fix", "fixes", "fixed", "update", "updates",
    "please", "need", "needs", "want", "wants", "should", "must", "can", "could", "would",
    "when", "once", "also", "not", "does", "do", "did", "doing", "get", "gets", "getting",
    "page", "pages", "component", "components", "file", "files", "code", "app", "apps",
    "feature", "features", "project", "function", "functions", "issue", "bug", "problem",
    "just", "some", "any", "all", "new", "still", "again", "properly", "correctly",
}

# Used by _meaningful_stems -- a small local suffix-stripper. Deliberately its OWN copy, not
# imported from app.agents.architecture_agent.usecase_modeler's own _stem_word -- mirrors this
# codebase's own established convention that each deterministic module keeps its own copy rather
# than sharing files across agent boundaries (usecase_validator.py/sequence_validator.py each
# already have their own separate copies of the same idea).
def _stem_word(word: str) -> str:
    for suffix in ("ations", "ation", "ments", "ment", "ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 3:
            return word[: -len(suffix)]
    return word


def _split_into_words(text: str) -> list[str]:
    """
    Splits text into individual lowercase words, handling both plain prose AND CamelCase/
    PascalCase identifiers identically -- this one function tokenizes a human's revision
    comment ("the login form doesn't clear") AND a file's basename ("LoginForm.tsx" ->
    "LoginForm") into the SAME shape of word list, so "CommentList" typed in a comment and
    CommentList.jsx on disk produce overlapping stems even though the comment never names a
    file extension (which _find_well_specified_target_files' regex requires).

    Contractions are expanded first ("doesn't" -> "does not") so an apostrophe never leaves
    stray single-letter noise ("t") or an unstrippable partial word ("doesn") behind.
    """
    text = re.sub(r"n't\b", " not", text, flags=re.IGNORECASE)
    words: list[str] = []
    for chunk in re.findall(r"[A-Za-z]+", text):
        words.extend(re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", chunk))
    return [word.lower() for word in words]


def _meaningful_stems(text: str) -> set[str]:
    """
    Real, filtered keyword stems from `text` -- drops stopwords/domain-generic filler
    (_KEYWORD_STOPWORDS) and anything under 4 characters (too short to carry real signal),
    stems what's left with _stem_word. Used by both _find_keyword_matched_known_files
    (Tier 1a, matched against a file's own basename) and _find_keyword_hint_files (Tier 1b,
    matched against real file content).
    """
    stems = set()
    for word in _split_into_words(text):
        if word in _KEYWORD_STOPWORDS or len(word) < 4:
            continue
        stems.add(_stem_word(word))
    return stems

# Human-readable label builders for each real coding-loop tool (app/agents/coder_agent/tools.py)
# -- used to turn a live AIMessage.tool_calls entry into a {"type": "tool_activity"} NDJSON
# event so a human watching the chat can see real, incremental progress during the coding loop
# (an opaque, tool-calling LangGraph agent with zero token-level output of its own) instead of a
# single static phase label sitting unchanged for however long the whole attempt takes. Verified
# directly against a real .astream(stream_mode="values") run: a ToolCall is always
# {"name", "args", "id", "type"}, and `args` uses each tool's own real parameter names below.
_TOOL_ACTIVITY_LABELS: dict[str, Any] = {
    "list_dir": lambda args: f"Listing {args.get('path', '.')}",
    "read_file": lambda args: f"Reading {args.get('path', '?')}",
    "write_file": lambda args: f"Writing {args.get('path', '?')}",
    "apply_patch": lambda args: f"Editing {args.get('path', '?')}",
    "run_shell": lambda args: f"Running: {args.get('command', '?')}",
    "search_code": lambda args: f"Searching codebase for \"{args.get('query', '?')}\"",
    "read_project_manifest": lambda args: "Checking the project manifest",
    "read_ui_component_design": lambda args: f"Reading UI design for {args.get('component_name', '?')}",
    "read_ui_page_design": lambda args: f"Reading UI page design for {args.get('page_id_or_route', '?')}",
    "list_unread_ui_designs": lambda args: "Checking which approved UI designs remain unread",
    "list_unimplemented_planned_files": lambda args: "Checking which planned files remain",
    "check_syntax": lambda args: f"Checking syntax of {args.get('path', '?')}",
    "check_component_styling": lambda args: "Scanning component styling",
    "submit_code_plan": lambda args: "Finalizing the plan",
}

_TOOL_ACTIVITY_RESULT_MAX_CHARS = 120


def _build_tool_activity_events(message: Any) -> list[dict[str, Any]]:
    """
    Given one new message from a react_agent.astream(stream_mode="values") step, return zero or
    more {"type": "tool_activity", ...} events to surface live: one per tool call on an
    AIMessage (a single turn can carry several), or a terse follow-up for a ToolMessage result.
    Never raises -- an unrecognized tool/shape just falls back to a generic label rather than
    breaking the stream over a cosmetic detail.
    """
    events: list[dict[str, Any]] = []

    if isinstance(message, AIMessage) and message.tool_calls:
        for call in message.tool_calls:
            name = call.get("name", "tool")
            args = call.get("args") or {}
            label_fn = _TOOL_ACTIVITY_LABELS.get(name)
            label = label_fn(args) if label_fn else f"Calling {name}"
            events.append({"type": "tool_activity", "tool": name, "label": label})
    elif isinstance(message, ToolMessage):
        content = str(message.content or "").strip().replace("\n", " ")
        if len(content) > _TOOL_ACTIVITY_RESULT_MAX_CHARS:
            content = content[:_TOOL_ACTIVITY_RESULT_MAX_CHARS] + "..."
        events.append(
            {
                "type": "tool_activity",
                "tool": message.name or "tool",
                "label": f"→ {content}" if content else f"→ {message.name} finished",
            }
        )

    return events


class CoderAgent:
    """
    Main Coder Agent class.
    """

    def __init__(self):
        self.planner = code_planner
        self.plan_validator = code_plan_validator
        self.verifier = coder_verifier

    async def run(self, feature_id: str, request: CoderAgentRunRequest) -> CoderAgentOutput:
        """
        Run the full Coder Agent pipeline (plan -> code -> verify -> diff).

        Rule:
            Coder Agent can only run after Requirement Agent SRS JSON and
            Architecture Agent's Architecture Plan JSON are approved. The
            UI/UX integration manifest is optional context (some features
            are backend-only).
        """

        logger.info("Coder Agent started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        # A URI is saved unconditionally whenever found, but run() never short-circuits on it --
        # there's no existing build/preview to protect, and skipping feature generation on a
        # URI-only first message would leave the human with nothing (see env_uri.py's module
        # docstring for why revise() is where the short-circuit actually matters).
        human_comment_for_planning = request.human_comment
        uri = extract_mongodb_uri(request.human_comment)
        if uri:
            workspace_service.write_env_local(project["project_id"], {"MONGODB_URI": uri})
            human_comment_for_planning = strip_uri_from_comment(request.human_comment, uri)

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.JSON,
        )
        if not srs_artifact:
            raise ValueError(
                "No approved SRS JSON artifact found. "
                "Approve Requirement Agent SRS JSON before running Coder Agent."
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
                "Approve Architecture Agent output before running Coder Agent."
            )

        ui_integration_manifest_json = self._load_approved_ui_integration_manifest(feature_id)
        project_manifest_json = project_memory_service.load_project_manifest(project["project_id"])

        agent_input = CoderAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_plan_json=architecture_plan_json,
            ui_integration_manifest_json=ui_integration_manifest_json,
            project_manifest_json=project_manifest_json,
            human_comment=human_comment_for_planning,
        )

        srs_for_planning = enhanced_srs_json or srs_json
        code_plan_json = await self._plan_with_retries(agent_input, srs_for_planning)

        preview_service.stop_preview_if_running(feature_id)
        workspace_service.start_feature_branch(project["project_id"], feature_id)
        revision_start_sha = workspace_service.ensure_project_repo(
            project["project_id"]
        ).head.commit.hexsha

        verify_result, coding_attempts = await self._run_coding_phase(
            project["project_id"],
            feature_id,
            code_plan_json,
            revision_start_sha,
            human_comment_for_planning,
            ui_integration_manifest_json,
            srs_json=srs_for_planning,
            architecture_plan_json=architecture_plan_json,
        )

        diff = workspace_service.diff_against_main(project["project_id"], feature_id)
        real_database_configured = bool(
            workspace_service.read_env_local(project["project_id"]).get("MONGODB_URI")
        )

        output = CoderAgentOutput(
            code_plan_json=code_plan_json,
            verification_passed=verify_result["passed"],
            file_tree_json=build_file_tree(diff),
            code_manifest_json=build_code_manifest(code_plan_json, diff),
            requirement_code_map_json=build_requirement_code_map(code_plan_json, diff),
            setup_instructions_markdown=build_setup_instructions_markdown(code_plan_json),
            merge_report_markdown=build_merge_report_markdown(
                feature["feature_name"], diff, verify_result, coding_attempts, real_database_configured
            ),
        )

        output.artifact_ids = self._save_artifacts(dict(project), dict(feature), output)

        logger.info(
            "Coder Agent completed for feature_id=%s verification_passed=%s attempts=%d artifacts=%s",
            feature_id,
            verify_result["passed"],
            coding_attempts,
            output.artifact_ids,
        )

        return output

    async def revise(
        self, feature_id: str, request: CoderAgentReviseRequest
    ) -> CoderAgentOutput | CoderAgentEnvSaveResult:
        """
        Revise the latest Coder Agent output for a feature that already has
        a real prior run -- mirrors RequirementAgent.revise()/
        ArchitectureAgent.revise()'s established pattern (load latest
        output, apply a human revision comment, save as a new version,
        never overwriting), adapted for the fact that this agent's output
        is a live git branch, not just a JSON document.

        Key difference from run(): builds on the EXISTING feature branch
        (workspace_service.resume_feature_branch, never resets it) instead
        of starting fresh from main -- a revision is a targeted change on
        top of already-verified work, not a new attempt at the same plan.
        This is what lets a human iterate by prompt (this session's
        explicit ask) instead of only getting one automatic shot.

        Rule:
            Requires a prior Coder Agent run for this feature (a CODE_PLAN
            artifact and a feature branch must already exist) -- there is
            nothing to revise otherwise.
        """
        logger.info("Coder Agent revision started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        latest_plan_artifact = self._find_latest_code_plan_artifact(feature_id)
        if not latest_plan_artifact:
            raise ValueError(
                "No existing Coder Agent output found for this feature. "
                "Run the Coder Agent before requesting a revision."
            )
        existing_plan_json = read_json_file(latest_plan_artifact["file_path"])

        # Short-circuit around the whole plan/code/verify cycle when the revision comment is
        # JUST a MongoDB URI -- this is the actual point of env_uri.py's mechanism: avoid a real
        # multi-minute cycle just to update one env var. If a URI arrives alongside other real
        # instructions, the file is still saved here, but the normal revise flow proceeds below
        # with the URI stripped out (no restart triggered here -- the normal path below already
        # calls stop_preview_if_running right before touching the workspace).
        revision_comment_for_planning = request.revision_comment
        uri = extract_mongodb_uri(request.revision_comment)
        if uri and not is_machine_generated_revision(request.revised_by):
            workspace_service.write_env_local(project["project_id"], {"MONGODB_URI": uri})
            if is_uri_only(request.revision_comment, uri):
                restarted = preview_service.restart_if_running(feature_id)
                message = (
                    "Database connection saved. Restarting the live preview to use your real data."
                    if restarted
                    else "Database connection saved. No live preview is currently running -- it "
                    "will use this connection the next time a preview is started."
                )
                logger.info(
                    "Coder Agent revision short-circuited for feature_id=%s: MongoDB URI saved, "
                    "preview_restarted=%s",
                    feature_id,
                    restarted,
                )
                return CoderAgentEnvSaveResult(saved=True, preview_restarted=restarted, message=message)
            revision_comment_for_planning = strip_uri_from_comment(request.revision_comment, uri)
        # else: a machine-generated comment (a Security/QA finding quoting source code that
        # happens to contain a URI-shaped substring) is left completely untouched -- no write, no
        # strip -- see env_uri.py's own MACHINE_GENERATED_REVISION_SOURCES comment for why.

        srs_artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.JSON,
        )
        if not srs_artifact:
            raise ValueError(
                "No approved SRS JSON artifact found. "
                "Approve Requirement Agent SRS JSON before revising the Coder Agent."
            )
        srs_json = read_json_file(srs_artifact["file_path"])

        architecture_plan_json = self._load_approved_architecture_plan(feature_id)
        if architecture_plan_json is None:
            raise ValueError(
                "No approved Architecture Plan (or legacy SDS) JSON artifact found."
            )

        ui_integration_manifest_json = self._load_approved_ui_integration_manifest(feature_id)
        project_manifest_json = project_memory_service.load_project_manifest(project["project_id"])

        agent_input = CoderAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=None,
            architecture_plan_json=architecture_plan_json,
            ui_integration_manifest_json=ui_integration_manifest_json,
            project_manifest_json=project_manifest_json,
            human_comment=revision_comment_for_planning,
        )

        # Frames the existing plan honestly, as a revision request rather than a
        # validation rejection -- reusing _plan_with_retries' rejection-retry
        # mechanism (see that method's docstring) would otherwise tell the model
        # its already-good, already-coded plan was "REJECTED by a deterministic
        # coverage check," which is simply false and would confuse the model
        # about what actually needs to change.
        revision_feedback = (
            "This is a HUMAN-REQUESTED REVISION of an already-implemented and verified "
            "feature, not a validation rejection. The plan below already passed validation "
            "and was successfully coded once. Apply ONLY the specific change described in "
            "the human revision comment above -- keep every existing file entry that "
            "doesn't need to change; add or modify entries only for what this revision "
            "requires."
        )

        coverage_baseline_files = self._collect_cumulative_plan_files(feature_id)
        well_specified_files = self._find_well_specified_target_files(
            revision_comment_for_planning, coverage_baseline_files
        )
        keyword_matched_files = (
            set()
            if well_specified_files
            else self._find_keyword_matched_known_files(
                revision_comment_for_planning, coverage_baseline_files
            )
        )
        prefer_single_shot = bool(well_specified_files) or bool(keyword_matched_files)

        # Must happen BEFORE planning, not after: the agentic revision planner's
        # tools (list_dir/read_file/search_code) read whatever is currently
        # checked out in the workspace, so the feature branch's real, current
        # file content must already be checked out when planning starts.
        preview_service.stop_preview_if_running(feature_id)
        workspace_service.resume_feature_branch(project["project_id"], feature_id)
        revision_start_sha = workspace_service.ensure_project_repo(
            project["project_id"]
        ).head.commit.hexsha

        # Cheap and deterministic (no LLM) -- always computed so exploration has a head start
        # whether it's used from the start (prefer_single_shot False) or as a fallback after a
        # Tier 0/1a fast-path guess fails (see _find_keyword_hint_files' own docstring).
        keyword_hint_files = self._find_keyword_hint_files(
            revision_comment_for_planning, workspace_service.get_repo_path(project["project_id"])
        )

        code_plan_json = await self._plan_with_retries(
            agent_input,
            srs_json,
            previous_plan_json=existing_plan_json,
            validation_feedback=revision_feedback,
            coverage_baseline_files=coverage_baseline_files,
            exploration_context=(project["project_id"], feature_id),
            prefer_single_shot=prefer_single_shot,
            keyword_hint_files=keyword_hint_files,
        )

        verify_result, coding_attempts = await self._run_coding_phase(
            project["project_id"],
            feature_id,
            code_plan_json,
            revision_start_sha,
            revision_comment_for_planning,
            ui_integration_manifest_json,
            srs_json=srs_json,
            architecture_plan_json=architecture_plan_json,
        )

        diff = workspace_service.diff_against_main(project["project_id"], feature_id)
        real_database_configured = bool(
            workspace_service.read_env_local(project["project_id"]).get("MONGODB_URI")
        )

        output = CoderAgentOutput(
            code_plan_json=code_plan_json,
            verification_passed=verify_result["passed"],
            file_tree_json=build_file_tree(diff),
            code_manifest_json=build_code_manifest(code_plan_json, diff),
            requirement_code_map_json=build_requirement_code_map(code_plan_json, diff),
            setup_instructions_markdown=build_setup_instructions_markdown(code_plan_json),
            merge_report_markdown=build_merge_report_markdown(
                feature["feature_name"], diff, verify_result, coding_attempts, real_database_configured
            ),
        )

        output.artifact_ids = self._save_artifacts(dict(project), dict(feature), output)

        logger.info(
            "Coder Agent revision completed for feature_id=%s verification_passed=%s "
            "attempts=%d artifacts=%s",
            feature_id,
            verify_result["passed"],
            coding_attempts,
            output.artifact_ids,
        )

        return output

    async def run_stream(
        self, feature_id: str, request: CoderAgentRunRequest
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming variant of run() -- same NDJSON event shape as Domain/Architecture Agent's
        streaming endpoints. Deliberately NOT a thin wrapper around run(): planning is inlined
        here so its single LLM call (code_planner.generate()'s underlying provider call) can be
        token-streamed, and the coding/verify tail is delegated to _code_with_retries_stream so
        its attempt/verify boundaries can be surfaced as phase events -- coding_loop.py has no
        token-level streaming at all (an opaque, unbounded tool-calling loop), so that tail is
        phase events only, never tokens. Mirrors generate()'s own parse-failure-is-terminal
        behavior (a JSON parse failure on both the raw and repaired output is NOT retried across
        planning attempts, exactly like the non-streaming path) -- only a plan_validator
        rejection drives the attempt loop, exactly like _plan_with_retries.

        Events:
            {"type": "token", "text": "..."}
            {"type": "phase", "phase": "...", "label": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "verification_passed": bool, "status": "...", "message": "..."}
        """
        logger.info("Coder Agent (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        # Unconditional save, never a short-circuit (see run()'s own identical comment) -- the
        # credential is stripped out of the comment before it ever reaches the planner prompt.
        human_comment_for_planning = request.human_comment
        uri = extract_mongodb_uri(request.human_comment)
        if uri:
            workspace_service.write_env_local(project["project_id"], {"MONGODB_URI": uri})
            human_comment_for_planning = strip_uri_from_comment(request.human_comment, uri)
            yield {
                "type": "phase",
                "phase": "database_connection_saved",
                "label": "Saved your database connection -- it will be used once this feature is built.",
            }

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
                    "Approve Requirement Agent SRS JSON before running Coder Agent."
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
                    "Approve Architecture Agent output before running Coder Agent."
                ),
            }
            return

        ui_integration_manifest_json = self._load_approved_ui_integration_manifest(feature_id)
        project_manifest_json = project_memory_service.load_project_manifest(project["project_id"])

        agent_input = CoderAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_plan_json=architecture_plan_json,
            ui_integration_manifest_json=ui_integration_manifest_json,
            project_manifest_json=project_manifest_json,
            human_comment=human_comment_for_planning,
        )

        srs_for_planning = enhanced_srs_json or srs_json
        provider = llm_provider_service.get_provider(agent_name=AgentName.CODER.value)

        code_plan_json: dict[str, Any] | None = None
        last_error: CodePlanValidationError | None = None
        previous_plan_json: dict[str, Any] | None = None
        validation_feedback: str | None = None

        for attempt in range(1, MAX_PLANNING_ATTEMPTS + 1):
            yield {
                "type": "phase",
                "phase": f"planning_attempt_{attempt}_of_{MAX_PLANNING_ATTEMPTS}",
                "label": f"Planning (attempt {attempt} of {MAX_PLANNING_ATTEMPTS})...",
            }

            prompt = build_code_planner_user_prompt(
                project=agent_input.project,
                feature=agent_input.feature,
                srs_json=srs_for_planning,
                architecture_plan_json=agent_input.architecture_plan_json,
                ui_integration_manifest_json=agent_input.ui_integration_manifest_json,
                project_manifest_json=agent_input.project_manifest_json,
                human_comment=agent_input.human_comment,
                previous_plan_json=previous_plan_json,
                validation_feedback=validation_feedback,
            )

            raw_chunks: list[str] = []
            try:
                async for chunk in provider.stream(prompt=prompt, system_prompt=CODE_PLANNER_SYSTEM_PROMPT):
                    raw_chunks.append(chunk)
                    yield {"type": "token", "text": chunk}
            except Exception as stream_error:
                logger.warning(
                    "Streamed Coder Agent planning failed mid-stream for feature_id=%s: %s",
                    feature_id,
                    stream_error,
                )

            raw_output = "".join(raw_chunks)

            try:
                attempt_plan_json = self.planner._extract_json_object(raw_output)
            except ValueError:
                repaired_output = await provider.invoke_agent(
                    [
                        {"role": "system", "content": CODE_PLAN_JSON_REPAIR_PROMPT},
                        {"role": "user", "content": build_code_plan_repair_prompt(raw_output)},
                    ]
                )
                try:
                    attempt_plan_json = self.planner._extract_json_object(repaired_output)
                except ValueError as error:
                    # Matches generate()'s own behavior: a JSON parse failure on both the raw
                    # and the repaired output is a terminal failure, not retried across
                    # planning attempts -- only a plan_validator rejection retries.
                    yield {
                        "type": "error",
                        "message": (
                            "Coder Agent planner could not produce valid code_plan_json after "
                            f"one repair attempt: {error}"
                        ),
                    }
                    return

            try:
                self.plan_validator.validate(
                    srs_for_planning,
                    agent_input.architecture_plan_json,
                    attempt_plan_json,
                    enforce_endpoint_coverage=True,
                )
                code_plan_json = attempt_plan_json
                break
            except CodePlanValidationError as error:
                logger.warning(
                    "Streamed plan attempt %d/%d failed validation: %s",
                    attempt,
                    MAX_PLANNING_ATTEMPTS,
                    error,
                )
                last_error = error
                previous_plan_json = attempt_plan_json
                validation_feedback = str(error)

        if code_plan_json is None:
            yield {
                "type": "error",
                "message": (
                    f"Coder Agent could not produce a valid plan after {MAX_PLANNING_ATTEMPTS} "
                    f"attempts: {last_error}"
                ),
            }
            return

        yield {"type": "phase", "phase": "preparing_workspace", "label": "Preparing the workspace..."}
        preview_service.stop_preview_if_running(feature_id)
        workspace_service.start_feature_branch(project["project_id"], feature_id)
        revision_start_sha = workspace_service.ensure_project_repo(
            project["project_id"]
        ).head.commit.hexsha

        result_holder: dict[str, Any] = {}
        if await model_capabilities.supports_tool_calling(AgentName.CODER.value):
            coding_stream = self._code_with_retries_stream(
                project["project_id"],
                feature_id,
                code_plan_json,
                result_holder,
                revision_start_sha=revision_start_sha,
                original_request=human_comment_for_planning,
                ui_integration_manifest_json=ui_integration_manifest_json,
                srs_json=srs_for_planning,
                architecture_plan_json=agent_input.architecture_plan_json,
            )
        else:
            logger.info(
                "coder_agent's current model does not support real tool-calling -- using the "
                "non-agentic batch coding path for feature_id=%s", feature_id,
            )
            coding_stream = self._code_with_batch_generation_stream(
                project["project_id"],
                feature_id,
                code_plan_json,
                result_holder,
                revision_start_sha=revision_start_sha,
                original_request=human_comment_for_planning,
                srs_json=srs_for_planning,
                architecture_plan_json=agent_input.architecture_plan_json,
            )

        async for event in coding_stream:
            yield event

        verify_result = result_holder["verify_result"]
        coding_attempts = result_holder["coding_attempts"]

        yield {"type": "phase", "phase": "diffing", "label": "Building the diff and manifest..."}
        diff = workspace_service.diff_against_main(project["project_id"], feature_id)
        real_database_configured = bool(
            workspace_service.read_env_local(project["project_id"]).get("MONGODB_URI")
        )

        output = CoderAgentOutput(
            code_plan_json=code_plan_json,
            verification_passed=verify_result["passed"],
            file_tree_json=build_file_tree(diff),
            code_manifest_json=build_code_manifest(code_plan_json, diff),
            requirement_code_map_json=build_requirement_code_map(code_plan_json, diff),
            setup_instructions_markdown=build_setup_instructions_markdown(code_plan_json),
            merge_report_markdown=build_merge_report_markdown(
                feature["feature_name"], diff, verify_result, coding_attempts, real_database_configured
            ),
        )

        output.artifact_ids = self._save_artifacts(dict(project), dict(feature), output)

        logger.info(
            "Coder Agent (streamed) completed for feature_id=%s verification_passed=%s "
            "attempts=%d artifacts=%s",
            feature_id,
            verify_result["passed"],
            coding_attempts,
            output.artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": output.artifact_ids,
            "verification_passed": verify_result["passed"],
            "status": "completed" if verify_result["passed"] else "completed_with_verification_failures",
            "message": (
                "Coder Agent completed and verification passed. Requires human approval."
                if verify_result["passed"]
                else "Coder Agent completed but verification failed. Requires human review before approval."
            ),
        }

    async def revise_stream(
        self, feature_id: str, request: CoderAgentReviseRequest
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming variant of revise() -- same event shape as run_stream(). Unlike run_stream,
        planning is NOT inlined for token streaming: revise()'s planner is the agentic
        exploration loop (generate_via_exploration), which -- like Architecture Agent's own
        agentic exploration tier -- only ever produces a plan as arguments to a final tool call,
        never as incremental text, so there is nothing to stream token-by-token. CLAUDE.md items
        22/23 document, at real cost, that this exploration planner is specifically what lets a
        vague, file-unspecified revision request be correctly scoped -- silently downgrading to
        the single-shot planner just to get token output would reintroduce that exact,
        already-fixed regression, so this method keeps it unconditionally.

        This deliberately reuses _plan_with_retries UNCHANGED (not reimplemented inline) to
        avoid duplicating its exploration-retry logic, which is extensively, carefully tuned
        (turn budgets, efficiency-hint retry feedback, coverage-baseline unioning) -- hand-
        duplicating it here would risk silently drifting out of sync with revise()'s own
        behavior. The tradeoff: one "planning" phase event covers the whole (possibly
        multi-attempt) exploration ladder, with an elapsed-time counter carrying the "still
        working" signal, rather than a phase event per attempt.

        Events: same shape as run_stream.
        """
        logger.info("Coder Agent revision (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        latest_plan_artifact = self._find_latest_code_plan_artifact(feature_id)
        if not latest_plan_artifact:
            yield {
                "type": "error",
                "message": (
                    "No existing Coder Agent output found for this feature. "
                    "Run the Coder Agent before requesting a revision."
                ),
            }
            return
        existing_plan_json = read_json_file(latest_plan_artifact["file_path"])

        # Same short-circuit as revise() -- see that method's own comment for the full
        # reasoning. Here the confirmation is streamed as phase + done events instead of a
        # returned CoderAgentEnvSaveResult.
        revision_comment_for_planning = request.revision_comment
        uri = extract_mongodb_uri(request.revision_comment)
        if uri and not is_machine_generated_revision(request.revised_by):
            workspace_service.write_env_local(project["project_id"], {"MONGODB_URI": uri})
            if is_uri_only(request.revision_comment, uri):
                restarted = preview_service.restart_if_running(feature_id)
                yield {"type": "phase", "phase": "database_connection_saved", "label": "Database connection saved."}
                if restarted:
                    yield {
                        "type": "phase",
                        "phase": "restarting_preview",
                        "label": "Restarting the live preview to use your real data...",
                    }
                yield {
                    "type": "done",
                    "status": "database_connection_saved",
                    "artifact_ids": [],
                    "verification_passed": None,
                    "message": (
                        "Database connection saved. Restarting the live preview to use your real data."
                        if restarted
                        else "Database connection saved. No live preview is currently running -- it "
                        "will use this connection the next time a preview is started."
                    ),
                }
                return
            revision_comment_for_planning = strip_uri_from_comment(request.revision_comment, uri)
        # else: a machine-generated comment is left completely untouched -- see revise()'s own
        # identical comment above for the full reasoning.

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
                    "Approve Requirement Agent SRS JSON before revising the Coder Agent."
                ),
            }
            return
        srs_json = read_json_file(srs_artifact["file_path"])

        architecture_plan_json = self._load_approved_architecture_plan(feature_id)
        if architecture_plan_json is None:
            yield {
                "type": "error",
                "message": "No approved Architecture Plan (or legacy SDS) JSON artifact found.",
            }
            return

        ui_integration_manifest_json = self._load_approved_ui_integration_manifest(feature_id)
        project_manifest_json = project_memory_service.load_project_manifest(project["project_id"])

        agent_input = CoderAgentInput(
            project=dict(project),
            feature=dict(feature),
            srs_json=srs_json,
            enhanced_srs_json=None,
            architecture_plan_json=architecture_plan_json,
            ui_integration_manifest_json=ui_integration_manifest_json,
            project_manifest_json=project_manifest_json,
            human_comment=revision_comment_for_planning,
        )

        revision_feedback = (
            "This is a HUMAN-REQUESTED REVISION of an already-implemented and verified "
            "feature, not a validation rejection. The plan below already passed validation "
            "and was successfully coded once. Apply ONLY the specific change described in "
            "the human revision comment above -- keep every existing file entry that "
            "doesn't need to change; add or modify entries only for what this revision "
            "requires."
        )

        coverage_baseline_files = self._collect_cumulative_plan_files(feature_id)
        well_specified_files = self._find_well_specified_target_files(
            revision_comment_for_planning, coverage_baseline_files
        )
        keyword_matched_files = (
            set()
            if well_specified_files
            else self._find_keyword_matched_known_files(
                revision_comment_for_planning, coverage_baseline_files
            )
        )
        prefer_single_shot = bool(well_specified_files) or bool(keyword_matched_files)

        yield {"type": "phase", "phase": "preparing_workspace", "label": "Preparing the workspace..."}
        # Must happen BEFORE planning, not after -- the agentic revision planner's tools
        # (list_dir/read_file/search_code) read whatever is currently checked out, so the
        # feature branch's real, current content must already be checked out first (same
        # ordering revise() itself uses, and load-bearing for the same reason).
        preview_service.stop_preview_if_running(feature_id)
        workspace_service.resume_feature_branch(project["project_id"], feature_id)
        revision_start_sha = workspace_service.ensure_project_repo(
            project["project_id"]
        ).head.commit.hexsha

        # Cheap and deterministic (no LLM) -- always computed so exploration has a head start
        # whether it's used from the start or as a fallback after a Tier 0/1a fast-path guess
        # fails (see _find_keyword_hint_files' own docstring).
        keyword_hint_files = self._find_keyword_hint_files(
            revision_comment_for_planning, workspace_service.get_repo_path(project["project_id"])
        )

        if well_specified_files:
            planning_label = "Drafting a plan for the file(s) you mentioned..."
        elif keyword_matched_files:
            planning_label = "Drafting a plan based on your description..."
        else:
            planning_label = "Exploring the codebase and planning your revision..."

        yield {"type": "phase", "phase": "planning", "label": planning_label}

        try:
            code_plan_json = await self._plan_with_retries(
                agent_input,
                srs_json,
                previous_plan_json=existing_plan_json,
                validation_feedback=revision_feedback,
                coverage_baseline_files=coverage_baseline_files,
                exploration_context=(project["project_id"], feature_id),
                prefer_single_shot=prefer_single_shot,
                keyword_hint_files=keyword_hint_files,
            )
        except (CodePlanValidationError, CodePlanGenerationError) as error:
            yield {
                "type": "error",
                "message": f"Coder Agent could not produce a valid revision plan: {error}",
            }
            return

        result_holder: dict[str, Any] = {}
        if await model_capabilities.supports_tool_calling(AgentName.CODER.value):
            coding_stream = self._code_with_retries_stream(
                project["project_id"],
                feature_id,
                code_plan_json,
                result_holder,
                revision_start_sha=revision_start_sha,
                original_request=revision_comment_for_planning,
                ui_integration_manifest_json=ui_integration_manifest_json,
                srs_json=srs_json,
                architecture_plan_json=architecture_plan_json,
            )
        else:
            logger.info(
                "coder_agent's current model does not support real tool-calling -- using the "
                "non-agentic batch coding path for feature_id=%s", feature_id,
            )
            coding_stream = self._code_with_batch_generation_stream(
                project["project_id"],
                feature_id,
                code_plan_json,
                result_holder,
                revision_start_sha=revision_start_sha,
                original_request=revision_comment_for_planning,
                srs_json=srs_json,
                architecture_plan_json=architecture_plan_json,
            )

        async for event in coding_stream:
            yield event

        verify_result = result_holder["verify_result"]
        coding_attempts = result_holder["coding_attempts"]

        yield {"type": "phase", "phase": "diffing", "label": "Building the diff and manifest..."}
        diff = workspace_service.diff_against_main(project["project_id"], feature_id)
        real_database_configured = bool(
            workspace_service.read_env_local(project["project_id"]).get("MONGODB_URI")
        )

        output = CoderAgentOutput(
            code_plan_json=code_plan_json,
            verification_passed=verify_result["passed"],
            file_tree_json=build_file_tree(diff),
            code_manifest_json=build_code_manifest(code_plan_json, diff),
            requirement_code_map_json=build_requirement_code_map(code_plan_json, diff),
            setup_instructions_markdown=build_setup_instructions_markdown(code_plan_json),
            merge_report_markdown=build_merge_report_markdown(
                feature["feature_name"], diff, verify_result, coding_attempts, real_database_configured
            ),
        )

        output.artifact_ids = self._save_artifacts(dict(project), dict(feature), output)

        logger.info(
            "Coder Agent revision (streamed) completed for feature_id=%s verification_passed=%s "
            "attempts=%d artifacts=%s",
            feature_id,
            verify_result["passed"],
            coding_attempts,
            output.artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": output.artifact_ids,
            "verification_passed": verify_result["passed"],
            "status": "revised" if verify_result["passed"] else "revised_with_verification_failures",
            "message": (
                "Coder Agent revision completed and verification passed. "
                "A new version was created and requires human approval."
                if verify_result["passed"]
                else "Coder Agent revision completed but verification failed. "
                "A new version was created and requires human review before approval."
            ),
        }

    async def _code_with_retries_stream(
        self,
        project_id: str,
        feature_id: str,
        code_plan_json: dict[str, Any],
        result_holder: dict[str, Any],
        revision_start_sha: str | None = None,
        original_request: str | None = None,
        ui_integration_manifest_json: dict[str, Any] | None = None,
        srs_json: dict[str, Any] | None = None,
        architecture_plan_json: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming counterpart to _code_with_retries -- identical retry/gap-detection/verify
        logic, but yields a `phase` event at each attempt/verify boundary (coding_loop.py has
        no token-level streaming, so this is phase events only) and writes its result into
        result_holder (an async generator can't `return` a value) instead of returning a tuple.
        _code_with_retries itself is untouched and still used by the non-streaming run()/revise().

        Also closes a real gap the non-streaming _code_with_retries doesn't have to worry about:
        a genuine Stop (client disconnect -> Starlette cancels the StreamingResponse generator)
        raises asyncio.CancelledError from inside `await react_agent.ainvoke(...)`, which the
        existing `except GraphRecursionError:` clause does not catch -- left unhandled, it would
        propagate past the commit_changes() call that normally runs right after every attempt,
        silently leaving whatever was written uncommitted. Catching it here and committing first,
        then re-raising, makes Stop's guarantee identical regardless of whether the loop stopped
        itself (recursion limit) or was stopped by a human: partial progress is always committed
        to the feature branch (safe -- nothing merges or gets approved automatically), just
        unverified.

        verify() is a blocking, synchronous call (multiple sequential Docker containers over
        several real minutes) -- run via asyncio.to_thread so it doesn't block the shared event
        loop the streaming route runs on (unlike the non-streaming path, which is already
        insulated from this by FastAPI's automatic sync-route threadpool).
        """
        prior_failure_output = None
        already_touched: dict[str, list[str]] | None = None
        verify_result: dict[str, Any] = {"passed": False, "steps": []}
        # See the identical comment in _code_with_retries -- created once for the whole call,
        # not per-attempt.
        ui_design_read_tracker: dict[str, set[str]] = {"components": set(), "pages": set()}
        implementation_spec_section = build_implementation_spec_section(
            code_plan_json, srs_json or {}, architecture_plan_json or {}
        )

        for attempt in range(1, MAX_CODING_ATTEMPTS + 1):
            yield {
                "type": "phase",
                "phase": f"coding_attempt_{attempt}_of_{MAX_CODING_ATTEMPTS}",
                "label": f"Coding (attempt {attempt} of {MAX_CODING_ATTEMPTS})...",
            }

            attempt_start_sha = workspace_service.ensure_project_repo(project_id).head.commit.hexsha
            react_agent = build_coder_react_agent(
                project_id, feature_id, code_plan_json, ui_integration_manifest_json, ui_design_read_tracker
            )
            task_message = build_task_message(
                code_plan_json, prior_failure_output, already_touched, original_request,
                implementation_spec_section=implementation_spec_section,
            )
            hit_recursion_limit = False
            attempt_error: str | None = None

            try:
                seen_messages = 0
                async for state in react_agent.astream(
                    {"messages": [{"role": "user", "content": task_message}]},
                    config={"recursion_limit": CODING_LOOP_RECURSION_LIMIT},
                    stream_mode="values",
                ):
                    messages = state.get("messages", [])
                    for message in messages[seen_messages:]:
                        for event in _build_tool_activity_events(message):
                            yield event
                    seen_messages = len(messages)
            except GraphRecursionError:
                hit_recursion_limit = True
                logger.warning(
                    "Streamed coding attempt %d/%d for feature_id=%s hit the recursion limit "
                    "(%d) before finishing -- committing partial progress and retrying with a "
                    "note to work efficiently.",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                    CODING_LOOP_RECURSION_LIMIT,
                )
            except asyncio.CancelledError:
                logger.warning(
                    "Streamed coding attempt %d/%d for feature_id=%s was stopped -- "
                    "committing partial progress.",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                )
                workspace_service.commit_changes(
                    project_id,
                    feature_id,
                    message=f"Coder Agent attempt {attempt} (stopped): {feature_id}",
                )
                raise
            except Exception as error:
                # Any OTHER failure (malformed tool-call JSON, a transport hiccup, an
                # unexpected tool error against the local model) previously propagated
                # uncaught, skipping commit_changes/verify/_save_artifacts entirely --
                # confirmed as a real bug: a revision request crashed mid-attempt with zero
                # saved artifact and a dirty, uncommitted workspace, indistinguishable to the
                # human from "the agent did nothing" (the route's own catch-all DOES turn this
                # into a real {"type": "error"} event, but nothing upstream of this point ever
                # got the chance to save real progress or a real merge report). Treat it like
                # a failed attempt instead: commit whatever was written, retry with an honest
                # message.
                attempt_error = str(error)
                logger.exception(
                    "Streamed coding attempt %d/%d for feature_id=%s raised an unexpected "
                    "error -- committing partial progress and retrying.",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                )

            try:
                workspace_service.commit_changes(
                    project_id, feature_id, message=f"Coder Agent attempt {attempt}: {feature_id}"
                )
            except Exception as commit_error:
                logger.exception(
                    "Streamed coding attempt %d/%d for feature_id=%s: commit_changes itself "
                    "failed",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                )
                attempt_error = attempt_error or f"Failed to commit changes: {commit_error}"

            touched_error: str | None = None
            try:
                already_touched = workspace_service.get_touched_files(
                    project_id, feature_id, since=revision_start_sha or MAIN_BRANCH
                )
            except Exception as touched_exc:
                logger.exception(
                    "Streamed coding attempt %d/%d for feature_id=%s: get_touched_files "
                    "itself failed",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                )
                touched_error = str(touched_exc)
                already_touched = {"added": [], "modified": [], "deleted": []}

            gaps = self._find_plan_gaps(code_plan_json, already_touched)

            # Skipped entirely (not just short-circuited inside the helper) when there's no
            # manifest to check against -- see the identical comment in _code_with_retries.
            design_gap: str | None = None
            if ui_integration_manifest_json:
                try:
                    this_attempt_touched = workspace_service.get_touched_files(
                        project_id, feature_id, since=attempt_start_sha
                    )
                    design_gap = self._find_unread_ui_design_gap(
                        ui_integration_manifest_json, this_attempt_touched, ui_design_read_tracker
                    )
                except Exception:
                    # Non-fatal by design -- this is an additive quality check, not a
                    # correctness gate; a failure here (e.g. get_touched_files itself erroring)
                    # just means this one attempt skips the check rather than the whole run
                    # failing over it.
                    logger.exception(
                        "Streamed coding attempt %d/%d for feature_id=%s: UI-fidelity gap check "
                        "itself failed -- skipping the check for this attempt",
                        attempt,
                        MAX_CODING_ATTEMPTS,
                        feature_id,
                    )

            if gaps or hit_recursion_limit or attempt_error or touched_error or design_gap:
                logger.warning(
                    "Streamed coding attempt %d/%d for feature_id=%s left %d planned file(s) "
                    "untouched",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                    len(gaps),
                )
                prior_failure_output = self._format_plan_gaps(gaps)
                if hit_recursion_limit:
                    prior_failure_output = (
                        "The previous attempt ran out of turns before finishing -- work "
                        "efficiently this time: do not re-read files you already know the "
                        "contents of, do not call check_syntax more than once per file, and "
                        "prioritize finishing every remaining planned file over polishing ones "
                        "that are already correct.\n\n" + (prior_failure_output or "")
                    )
                if attempt_error:
                    prior_failure_output = (
                        f"The previous attempt failed with an unexpected error: {attempt_error}\n\n"
                        + (prior_failure_output or "")
                    )
                if touched_error:
                    prior_failure_output = (
                        "Could not determine which files were touched by the previous attempt "
                        f"(error: {touched_error}) -- proceed carefully and re-check your work.\n\n"
                        + (prior_failure_output or "")
                    )
                if design_gap:
                    prior_failure_output = design_gap + "\n\n" + (prior_failure_output or "")
                verify_result = {
                    "passed": False,
                    "steps": [
                        {
                            "name": "planned files touched",
                            "status": "failed",
                            "output": prior_failure_output,
                        }
                    ],
                }
                continue

            yield {
                "type": "phase",
                "phase": f"verifying_attempt_{attempt}",
                "label": f"Verifying (attempt {attempt} of {MAX_CODING_ATTEMPTS})...",
            }
            verify_result = await asyncio.to_thread(
                self.verifier.verify, project_id, feature_id, code_plan_json, original_request
            )

            if verify_result["passed"]:
                result_holder["verify_result"] = verify_result
                result_holder["coding_attempts"] = attempt
                return

            logger.warning(
                "Streamed coding attempt %d/%d failed verification for feature_id=%s",
                attempt,
                MAX_CODING_ATTEMPTS,
                feature_id,
            )
            prior_failure_output = self._summarize_verify_failure(verify_result)

        result_holder["verify_result"] = verify_result
        result_holder["coding_attempts"] = MAX_CODING_ATTEMPTS

    def _find_latest_code_plan_artifact(self, feature_id: str) -> dict | None:
        """
        Find the latest CODE_PLAN JSON artifact for this feature, regardless
        of approval status -- a revision should be possible even before the
        prior version has been approved/merged (a human may want several
        rounds of feedback before approving anything).
        """
        matching = self._find_all_code_plan_artifacts(feature_id)

        if not matching:
            return None

        return max(matching, key=lambda item: item.get("version", 1))

    def _find_all_code_plan_artifacts(self, feature_id: str) -> list[dict]:
        return [
            artifact
            for artifact in store.artifacts.values()
            if artifact.get("feature_id") == feature_id
            and artifact.get("agent_name") in [AgentName.CODER, AgentName.CODER.value]
            and artifact.get("artifact_type") in [ArtifactType.CODE_PLAN, ArtifactType.CODE_PLAN.value]
            and artifact.get("artifact_format") in [ArtifactFormat.JSON, ArtifactFormat.JSON.value]
        ]

    def _collect_cumulative_plan_files(self, feature_id: str) -> list[dict[str, Any]]:
        """
        Union of every file entry across EVERY CODE_PLAN version ever saved
        for this feature -- not just the latest one.

        Each revise() call's own saved code_plan_json only lists the delta
        it actually touched (see _plan_with_retries' coverage_baseline_files
        docstring for why), so the *latest* version alone is not a complete
        picture of everything this feature has ever implemented. Confirmed
        necessary by a real, second revision request: the first revision's
        corrected artifact set was saved with only its own delta plan
        (just the one file it touched) as the "latest" CODE_PLAN, so a
        second revision's coverage baseline -- built from only that latest
        version -- silently lost every file the *original* plan had
        implemented, reproducing the exact "does not cover these API
        endpoints" rejection this whole mechanism exists to prevent. Later
        versions win when the same path appears in more than one version
        (its most recent maps_to/action is the accurate one).
        """
        matching = sorted(
            self._find_all_code_plan_artifacts(feature_id), key=lambda item: item.get("version", 1)
        )

        files_by_path: dict[str, dict[str, Any]] = {}
        for artifact in matching:
            plan = read_json_file(artifact["file_path"])
            if not isinstance(plan, dict):
                continue
            for file_entry in plan.get("files", []) or []:
                path = file_entry.get("path") if isinstance(file_entry, dict) else None
                if path:
                    files_by_path[path] = file_entry

        return list(files_by_path.values())

    def _find_well_specified_target_files(
        self, revision_comment: str | None, known_files: list[dict[str, Any]]
    ) -> set[str]:
        """
        Cheap, deterministic heuristic: does the human's revision comment already name a REAL
        file this feature has previously touched? If so, the agentic exploration planner's whole
        reason for existing (scoping a VAGUE, file-unspecified request by looking at the real
        codebase -- see _plan_with_retries' exploration_context docstring) doesn't apply, and a
        single, fast, one-call planner attempt can go straight to drafting a plan against the
        named file(s) instead of spending up to REVISION_PLANNING_RECURSION_LIMIT real
        tool-calling turns "discovering" a file the human already named. Confirmed real: a
        request as simple as "fix the typo in components/Footer.tsx" was taking 80+ minutes
        under the old unconditional-exploration design.

        Deliberately conservative -- returns an empty set (never guesses) unless the comment
        contains something that actually looks like a file reference:
        - A token with a real extension is required (a bare word like "footer" never matches).
        - A token that already looks like a qualified path (contains "/") is only trusted on an
          EXACT match against a real path -- a qualified-but-not-exact token isn't guessed at
          further.
        - A bare filename (no "/") is only trusted if it's the ONE file in the whole project with
          that basename -- guards against generic Next.js filenames (page.tsx/route.ts/
          layout.tsx) that legitimately exist under many different directories once a project has
          more than one feature; an ambiguous match falls through to full exploration rather than
          picking one at random.

        Returns the set of matched real paths (empty if nothing qualifies) -- the caller only
        needs to know whether this is non-empty ("well-specified"), but the real paths are also
        useful for logging/debugging.
        """
        if not revision_comment or not known_files:
            return set()

        tokens = extract_file_tokens(revision_comment)
        if not tokens:
            return set()

        known_paths = {
            entry.get("path")
            for entry in known_files
            if isinstance(entry, dict) and entry.get("path")
        }
        if not known_paths:
            return set()

        return resolve_tokens_against_known_paths(tokens, known_paths)

    def _find_keyword_matched_known_files(
        self, revision_comment: str | None, known_files: list[dict[str, Any]]
    ) -> set[str]:
        """
        Tier 1a: sibling to _find_well_specified_target_files, for the common case a human
        describes a change in plain English WITHOUT naming a file at all (e.g. "the login
        form doesn't clear after submit") -- fuzzy-matches the comment's keyword stems
        against each known file's own basename stems (CamelCase/kebab/snake-aware, see
        _split_into_words). This is what lets "the login form" resolve to LoginForm.tsx even
        though the comment never types a real file extension, which
        _find_well_specified_target_files' regex requires.

        Deliberately metadata-only (no filesystem access) -- safe to call at the exact same
        point _find_well_specified_target_files already is (before
        workspace_service.resume_feature_branch has checked out this feature's real branch).
        Content-based matching (which CAN find plausible-but-wrong files -- confirmed real:
        grepping for "tailwind"/"css" on a "styles are missing" request finds the files that
        ALREADY correctly use Tailwind, not the one broken, unstyled file) is a separate,
        deliberately less-trusted mechanism -- see _find_keyword_hint_files.

        Mirrors _find_well_specified_target_files' own "never guess an ambiguous case"
        philosophy: requires >=2 shared stems (a single generic shared word is not real
        signal) AND a UNIQUE top-scoring file across known_files (a tie is treated as
        ambiguous, not guessed at -- falls through to exploration same as 0 matches).
        """
        if not revision_comment or not known_files:
            return set()

        comment_stems = _meaningful_stems(revision_comment)
        if len(comment_stems) < 2:
            return set()

        scored: dict[str, int] = {}
        for entry in known_files:
            if not isinstance(entry, dict) or not entry.get("path"):
                continue
            if entry.get("action") == "delete":
                # A stale, no-longer-real filename shouldn't be matchable.
                continue

            path = entry["path"]
            basename = path.rsplit("/", 1)[-1]
            basename = re.sub(r"\.(tsx|ts|jsx|js|css|json|mjs)$", "", basename, flags=re.IGNORECASE)
            overlap = comment_stems & _meaningful_stems(basename)
            if len(overlap) >= 2:
                scored[path] = len(overlap)

        if not scored:
            return set()

        top_score = max(scored.values())
        top_matches = {path for path, score in scored.items() if score == top_score}
        if len(top_matches) != 1:
            # Multiple files tied for the best match -- genuinely ambiguous, don't guess.
            return set()

        return top_matches

    def _find_keyword_hint_files(
        self, revision_comment: str | None, workspace_root: Path, max_hints: int = 8
    ) -> list[str]:
        """
        Tier 1b: a cheap, deterministic keyword search of the REAL workspace content, fed
        into the agentic exploration planner's prompt as an unverified starting-point hint --
        never trusted to skip exploration (unlike Tier 0/1a). Must be called AFTER
        workspace_service.resume_feature_branch (needs this feature's real, current files on
        disk, not whatever happens to already be checked out).

        Deliberately never promoted to prefer_single_shot: content/keyword matching can find
        files that mention a topic without being the actually-broken one (the Tailwind
        example above is this exact project's own documented counter-example -- see
        tools.py's check_component_styling, built for precisely this blind spot). The
        exploration model keeps every one of its own tools, so a wrong hint just gets
        ignored or overridden, never silently acted on.

        Returns paths only (no content) -- mirrors _build_cumulative_touched_files_section's
        own already-proven pattern of rendering only a path list, never file content, for the
        planner's file-level create/modify decisions.
        """
        if not revision_comment:
            return []

        stems = _meaningful_stems(revision_comment)
        if len(stems) < 2:
            return []

        try:
            pattern = re.compile("|".join(re.escape(stem) for stem in stems), re.IGNORECASE)
        except re.error:
            return []

        matches = search_workspace_content(workspace_root, pattern, max_results=500)

        scores: dict[str, int] = {}
        for match in matches:
            # "path:line:content" -- path itself never contains ":" on this project's
            # supported platforms, so split on the first two colons only.
            path = match.split(":", 2)[0]
            if not path or path == "...":
                continue
            path_bonus = 3 if any(stem in path.lower() for stem in stems) else 0
            scores[path] = scores.get(path, 0) + 1 + path_bonus

        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        return [path for path, _score in ranked[:max_hints]]

    async def _plan_with_retries(
        self,
        agent_input: CoderAgentInput,
        srs_for_planning: dict[str, Any],
        previous_plan_json: dict[str, Any] | None = None,
        validation_feedback: str | None = None,
        coverage_baseline_files: list[dict[str, Any]] | None = None,
        exploration_context: tuple[str, str] | None = None,
        prefer_single_shot: bool = False,
        keyword_hint_files: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        previous_plan_json/validation_feedback can be pre-seeded by a caller
        (revise() does this, framing the existing plan + a human revision
        request rather than a validation rejection) -- if plan_validator
        then rejects THAT plan, the retry loop below takes over normally
        from there, with the standard "was rejected" framing, since at that
        point it genuinely would be a rejection.

        coverage_baseline_files: for revise() only -- the file list of the
        already-implemented, already-verified prior plan. A revision's own
        code_plan_json only needs to describe the delta (what this specific
        change touches), not re-declare every endpoint/entity/requirement the
        prior plan already covered -- confirmed necessary against a real
        revise() run, where the model (reasonably) returned only the files
        relevant to the requested change and plan_validator then rejected it
        for "missing" endpoints that were, in fact, already implemented and
        untouched by this revision. Coverage is validated against the union
        of the baseline's files and this attempt's own files; the plan
        actually returned (and coded) is still just this attempt's delta.

        exploration_context: (project_id, feature_id), for revise() only --
        when set, each attempt calls planner.generate_via_exploration(...)
        (an agentic, tool-using planner that can look at the real codebase)
        instead of planner.generate() (a single-shot call with zero
        visibility into it). Confirmed necessary: the single-shot planner
        could only correctly scope a revision when the human named the exact
        file(s) to change -- a vague, file-unspecified request (e.g. "styles
        are missing, add tailwind css") needs the model to actually look at
        the codebase to know which files are affected. Everything else about
        the retry loop (coverage validation, feedback framing) is unchanged.

        prefer_single_shot: for revise()'s fast path only (see
        CoderAgent._find_well_specified_target_files) -- when the human's revision comment
        already names a real file this feature has previously touched, exploring the codebase
        via up to REVISION_PLANNING_RECURSION_LIMIT tool-calling turns just to "discover" a file
        the human already named is pure waste (confirmed real: 80+ minutes for a request as
        simple as "fix the typo in components/Footer.tsx"). When True, ONLY attempt 1 skips
        exploration in favor of the single-shot planner.generate() (one plain LLM call, no
        tool-calling turns) -- exploration_context itself stays truthy throughout regardless
        (deliberately: it's what keeps enforce_endpoint_coverage relaxed for revisions below,
        independent of which planner actually ran). If attempt 1 fails for ANY reason
        (validation rejection or an unexpected exception), attempts 2-4 fall through to the
        normal, thorough exploration path -- a wrong fast guess self-corrects instead of
        permanently degrading reliability.

        keyword_hint_files: for revise() only -- an unverified starting-point hint from
        CoderAgent._find_keyword_hint_files ("Tier 1b"), a cheap keyword search of the real
        workspace against the human's comment. Threaded into every exploration attempt
        (whenever exploration actually runs, whether that's from the start or because a
        Tier 0/1a fast-path guess failed and fell through) -- never affects prefer_single_shot
        itself, only gives exploration a head start instead of starting blind.
        """
        last_error: CodePlanValidationError | CodePlanGenerationError | None = None

        for attempt in range(1, MAX_PLANNING_ATTEMPTS + 1):
            use_exploration = exploration_context and not (prefer_single_shot and attempt == 1)

            if use_exploration:
                project_id, feature_id = exploration_context
                try:
                    code_plan_json, _raw = await self.planner.generate_via_exploration(
                        project_id=project_id,
                        feature_id=feature_id,
                        project=agent_input.project,
                        feature=agent_input.feature,
                        srs_json=srs_for_planning,
                        architecture_plan_json=agent_input.architecture_plan_json,
                        ui_integration_manifest_json=agent_input.ui_integration_manifest_json,
                        project_manifest_json=agent_input.project_manifest_json,
                        human_comment=agent_input.human_comment,
                        previous_plan_json=previous_plan_json,
                        validation_feedback=validation_feedback,
                        coverage_baseline_files=coverage_baseline_files or [],
                        keyword_hint_files=keyword_hint_files,
                    )
                except CodePlanGenerationError as error:
                    # The exploration loop ran out of its turn budget before
                    # calling submit_code_plan -- confirmed a real, reachable
                    # failure mode on a genuinely vague, multi-file revision
                    # request. Treat exactly like a rejected attempt (same
                    # retry mechanism below), not an uncaught crash -- mirrors
                    # _code_with_retries' GraphRecursionError handling.
                    logger.warning(
                        "Exploration-planning attempt %d/%d did not finish in time: %s",
                        attempt,
                        MAX_PLANNING_ATTEMPTS,
                        error,
                    )
                    last_error = error
                    # NOTE: this fresh attempt has zero memory of what the previous one
                    # actually explored (a new agent conversation, not a continuation) --
                    # so the feedback can only be a general strategy change, not "don't
                    # redo X" (it has no idea what X was). Point it at the tools that
                    # answer a question directly instead of requiring per-file reads.
                    validation_feedback = (
                        "Your previous attempt ran out of exploration turns before calling "
                        "submit_code_plan. This is a fresh attempt with no memory of what you "
                        "explored last time, so change strategy rather than trying to pick up "
                        "where you left off: prefer a summarizing tool (check_component_styling, "
                        "read_project_manifest, search_code) over reading each candidate file's "
                        "full content one at a time -- your job here is only to decide WHICH "
                        "files need a plan entry, not to draft the actual code change (a later "
                        "coding step does that and will read each file itself). Call "
                        "submit_code_plan as soon as you can name the affected file(s), without "
                        "verifying every one by reading its source."
                    )
                    continue
                except Exception as error:
                    # Any OTHER failure (a transient Ollama/langchain-ollama transport error --
                    # already documented elsewhere in this project's history as a real, if rare,
                    # occurrence -- a malformed tool call, etc.) previously propagated all the way
                    # out of _plan_with_retries uncaught, meaning revise()/revise_stream() never
                    # even reached the coding loop, let alone _save_artifacts. Treat it like a
                    # rejected/incomplete attempt instead -- retry with an honest message, same
                    # mechanism as the CodePlanGenerationError branch above.
                    logger.exception(
                        "Exploration-planning attempt %d/%d for feature_id=%s raised an "
                        "unexpected error.",
                        attempt,
                        MAX_PLANNING_ATTEMPTS,
                        feature_id,
                    )
                    last_error = CodePlanGenerationError(
                        f"Exploration-planning attempt raised an unexpected error: {error}"
                    )
                    validation_feedback = (
                        "Your previous attempt failed with an unexpected error before it could "
                        f"submit a plan ({error}). This is a fresh attempt with no memory of what "
                        "you explored last time -- try again, and call submit_code_plan as soon "
                        "as you're confident, without over-exploring."
                    )
                    continue
            else:
                try:
                    code_plan_json, _raw = await self.planner.generate(
                        project=agent_input.project,
                        feature=agent_input.feature,
                        srs_json=srs_for_planning,
                        architecture_plan_json=agent_input.architecture_plan_json,
                        ui_integration_manifest_json=agent_input.ui_integration_manifest_json,
                        project_manifest_json=agent_input.project_manifest_json,
                        human_comment=agent_input.human_comment,
                        previous_plan_json=previous_plan_json,
                        validation_feedback=validation_feedback,
                        coverage_baseline_files=coverage_baseline_files,
                    )
                except Exception as error:
                    # Previously uncaught -- a JSON-parse failure (both raw and repaired) or any
                    # other exception (a real, if rare, transient Ollama/langchain-ollama error --
                    # already documented elsewhere in this project's history) would propagate
                    # straight out of _plan_with_retries, crashing the whole run()/revise() call.
                    # Treat it like a rejected attempt instead, same mechanism as the exploration
                    # branch above -- for the fast path specifically, this is what makes attempt
                    # 2 correctly fall through to full exploration (use_exploration is only False
                    # when attempt == 1) instead of the whole revision crashing on a bad guess.
                    logger.warning(
                        "Single-shot planning attempt %d/%d failed: %s",
                        attempt,
                        MAX_PLANNING_ATTEMPTS,
                        error,
                    )
                    last_error = (
                        error
                        if isinstance(error, CodePlanGenerationError)
                        else CodePlanGenerationError(f"Planning attempt raised an unexpected error: {error}")
                    )
                    if exploration_context:
                        validation_feedback = (
                            "Your previous attempt (a quick, targeted guess based on the file(s) "
                            f"you named) failed: {error}. This attempt will explore the codebase "
                            "more thoroughly instead."
                        )
                    else:
                        validation_feedback = f"Your previous attempt failed with an error: {error}. Try again."
                    continue

            plan_for_coverage_check = code_plan_json
            if coverage_baseline_files:
                plan_for_coverage_check = {
                    **code_plan_json,
                    "files": list(code_plan_json.get("files", []) or []) + coverage_baseline_files,
                }

            try:
                self.plan_validator.validate(
                    srs_for_planning,
                    agent_input.architecture_plan_json,
                    plan_for_coverage_check,
                    enforce_endpoint_coverage=exploration_context is None,
                )
                return code_plan_json
            except CodePlanValidationError as error:
                logger.warning(
                    "Plan attempt %d/%d failed validation: %s", attempt, MAX_PLANNING_ATTEMPTS, error
                )
                last_error = error
                previous_plan_json = code_plan_json
                validation_feedback = str(error)

        raise last_error

    async def _run_coding_phase(
        self,
        project_id: str,
        feature_id: str,
        code_plan_json: dict[str, Any],
        revision_start_sha: str | None,
        original_request: str | None,
        ui_integration_manifest_json: dict[str, Any] | None,
        srs_json: dict[str, Any] | None = None,
        architecture_plan_json: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        """
        Single dispatch point shared by run()/revise() -- checks whether coder_agent's currently
        selected model genuinely supports real tool-calling
        (model_capabilities.supports_tool_calling, see that module's own docstring for the full
        detection story) and routes to the real, iterative agentic coding loop if so, or the
        non-agentic batch generator (batch_coder.py, see its own module docstring for the honest
        scope tradeoff) if not. Fully automatic based on whichever model is currently selected for
        coder_agent in Settings -- no separate manual mode toggle.

        srs_json/architecture_plan_json, when given, are threaded into whichever coding path runs
        so the real spec (not just the terse code_plan_json) reaches the step that actually
        writes file content -- see build_implementation_spec_section/_for_single_file's own
        docstrings in prompt.py for why this exists.
        """
        if await model_capabilities.supports_tool_calling(AgentName.CODER.value):
            return await self._code_with_retries(
                project_id, feature_id, code_plan_json,
                revision_start_sha=revision_start_sha, original_request=original_request,
                ui_integration_manifest_json=ui_integration_manifest_json,
                srs_json=srs_json, architecture_plan_json=architecture_plan_json,
            )

        logger.info(
            "coder_agent's current model does not support real tool-calling -- using the "
            "non-agentic batch coding path for feature_id=%s", feature_id,
        )
        return await self._code_with_batch_generation(
            project_id, feature_id, code_plan_json,
            revision_start_sha=revision_start_sha, original_request=original_request,
            srs_json=srs_json, architecture_plan_json=architecture_plan_json,
        )

    async def _code_with_batch_generation(
        self,
        project_id: str,
        feature_id: str,
        code_plan_json: dict[str, Any],
        revision_start_sha: str | None = None,
        original_request: str | None = None,
        srs_json: dict[str, Any] | None = None,
        architecture_plan_json: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        """
        Non-agentic counterpart to _code_with_retries -- see batch_coder.py's own module
        docstring for the full design and its honest scope limit. Same outer MAX_CODING_ATTEMPTS
        retry shape and (verify_result, attempts_used) return contract as the agentic path, so
        every caller downstream of this (diffing, artifact-saving, merge-report building) needs
        zero changes regardless of which coding path actually ran.

        srs_json/architecture_plan_json, when given, feed
        prompt.build_implementation_spec_for_single_file per planned file -- see that function's
        own docstring for why (the plan's own rationale/maps_to are deliberately terse).
        """
        workspace_root = workspace_service.get_repo_path(project_id)
        prior_failure_output: str | None = None
        verify_result: dict[str, Any] = {"passed": False, "steps": []}

        for attempt in range(1, MAX_CODING_ATTEMPTS + 1):
            written_paths: list[str] = []
            missing_paths: list[str] = []

            for file_entry in code_plan_json.get("files", []) or []:
                path = file_entry.get("path", "")
                action = file_entry.get("action")

                if action == "delete":
                    target = workspace_root / path
                    if target.exists():
                        target.unlink()
                    written_paths.append(path)
                    continue

                target = _resolve_within(workspace_root, path)
                current_content = target.read_text(encoding="utf-8") if target.exists() else None

                implementation_spec = build_implementation_spec_for_single_file(
                    file_entry, srs_json or {}, architecture_plan_json or {}
                )
                content = await batch_coder.generate_file_content(
                    feature_id, file_entry, current_content, written_paths, prior_failure_output,
                    implementation_spec=implementation_spec,
                )

                if content is None:
                    missing_paths.append(path)
                    logger.warning(
                        "Batch coding attempt %d/%d for feature_id=%s: no content produced for %s",
                        attempt, MAX_CODING_ATTEMPTS, feature_id, path,
                    )
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
                written_paths.append(path)

            try:
                workspace_service.commit_changes(
                    project_id, feature_id, message=f"Coder Agent batch attempt {attempt}: {feature_id}"
                )
            except Exception as commit_error:
                logger.exception(
                    "Batch coding attempt %d/%d for feature_id=%s: commit_changes itself failed",
                    attempt, MAX_CODING_ATTEMPTS, feature_id,
                )
                missing_paths.append(f"(commit failed: {commit_error})")

            if missing_paths:
                prior_failure_output = (
                    "The previous batch attempt failed to produce content for these planned "
                    "file(s), fix them this time:\n" + "\n".join(f"- {path}" for path in missing_paths)
                )
                verify_result = {
                    "passed": False,
                    "steps": [{"name": "batch file generation", "status": "failed", "output": prior_failure_output}],
                }
                continue

            verify_result = self.verifier.verify(
                project_id, feature_id, code_plan_json, original_request,
                ui_expectations=(srs_json or {}).get("ui_expectations"),
            )

            if verify_result["passed"]:
                return verify_result, attempt

            logger.warning(
                "Batch coding attempt %d/%d failed verification for feature_id=%s",
                attempt, MAX_CODING_ATTEMPTS, feature_id,
            )
            prior_failure_output = self._summarize_verify_failure(verify_result)

        return verify_result, MAX_CODING_ATTEMPTS

    async def _code_with_batch_generation_stream(
        self,
        project_id: str,
        feature_id: str,
        code_plan_json: dict[str, Any],
        result_holder: dict[str, Any],
        revision_start_sha: str | None = None,
        original_request: str | None = None,
        srs_json: dict[str, Any] | None = None,
        architecture_plan_json: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming counterpart to _code_with_batch_generation. There is no meaningful token-level
        streaming for a sequence of one-shot, non-agentic file-generation calls (unlike the
        agentic loop's live tool activity) -- this wraps the real, already-verified
        _code_with_batch_generation logic with one "phase" event announcing the mode, then
        populates result_holder exactly like _code_with_retries_stream does, so callers can
        dispatch between the two without any other change.
        """
        yield {
            "type": "phase",
            "phase": "batch_coding",
            "label": "coder_agent's current model doesn't support real tool-calling -- writing "
            "each planned file with a direct, non-agentic generation call instead...",
        }
        verify_result, coding_attempts = await self._code_with_batch_generation(
            project_id, feature_id, code_plan_json,
            revision_start_sha=revision_start_sha, original_request=original_request,
            srs_json=srs_json, architecture_plan_json=architecture_plan_json,
        )
        result_holder["verify_result"] = verify_result
        result_holder["coding_attempts"] = coding_attempts

    async def _code_with_retries(
        self,
        project_id: str,
        feature_id: str,
        code_plan_json: dict[str, Any],
        revision_start_sha: str | None = None,
        original_request: str | None = None,
        ui_integration_manifest_json: dict[str, Any] | None = None,
        srs_json: dict[str, Any] | None = None,
        architecture_plan_json: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        prior_failure_output = None
        already_touched: dict[str, list[str]] | None = None
        verify_result: dict[str, Any] = {"passed": False, "steps": []}
        # Created ONCE for the whole call, not per-attempt -- see _find_unread_ui_design_gap's
        # own docstring for why. Once any attempt of this run has genuinely read a relevant
        # design, that satisfies "did this run consult the approved design at all" for every
        # later attempt too, even one that only re-touches an unrelated frontend file (e.g. a
        # nav-link patch) while fixing something else -- a real run confirmed re-demanding a
        # fresh read on every single attempt could consume the run's last attempt on repeated
        # compliance instead of ever reaching a second real verify() call.
        ui_design_read_tracker: dict[str, set[str]] = {"components": set(), "pages": set()}
        # Also computed ONCE, not per-attempt -- invariant across retries (same rationale as the
        # tracker above), and gives every attempt the real SRS/implementation_plan detail the
        # plan's own terse rationale/maps_to never carry (see prompt.build_implementation_spec_
        # section's own docstring).
        implementation_spec_section = build_implementation_spec_section(
            code_plan_json, srs_json or {}, architecture_plan_json or {}
        )

        for attempt in range(1, MAX_CODING_ATTEMPTS + 1):
            attempt_start_sha = workspace_service.ensure_project_repo(project_id).head.commit.hexsha
            react_agent = build_coder_react_agent(
                project_id, feature_id, code_plan_json, ui_integration_manifest_json, ui_design_read_tracker
            )
            task_message = build_task_message(
                code_plan_json, prior_failure_output, already_touched, original_request,
                implementation_spec_section=implementation_spec_section,
            )
            hit_recursion_limit = False
            attempt_error: str | None = None

            try:
                await react_agent.ainvoke(
                    {"messages": [{"role": "user", "content": task_message}]},
                    config={"recursion_limit": CODING_LOOP_RECURSION_LIMIT},
                )
            except GraphRecursionError:
                # A larger plan (several files, some "modify" patches, plus the
                # self-check tool calls the prompt now encourages) can burn through
                # the turn budget before the model calls a final, tool-free answer.
                # Treat this exactly like an incomplete attempt rather than letting
                # it crash the whole run uncaught: commit whatever was finished,
                # then let the existing gap-detection logic below report precisely
                # what's still missing for the next attempt.
                hit_recursion_limit = True
                logger.warning(
                    "Coding attempt %d/%d for feature_id=%s hit the recursion limit "
                    "(%d) before finishing -- committing partial progress and "
                    "retrying with a note to work efficiently.",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                    CODING_LOOP_RECURSION_LIMIT,
                )
            except Exception as error:
                # Any OTHER failure -- a real, plausible occurrence against a local Ollama
                # model (malformed tool-call JSON, a transport hiccup, an unexpected tool
                # error) -- previously propagated uncaught, skipping commit_changes/verify/
                # _save_artifacts entirely and leaving no trace of the attempt at all (a
                # confirmed real bug: a revision request could crash mid-attempt with zero
                # saved artifact and a dirty, uncommitted workspace, indistinguishable from
                # "the agent did nothing"). Treat it exactly like a failed attempt instead --
                # commit whatever was written before the crash, and let the caller see an
                # honest failure message rather than the request silently vanishing.
                attempt_error = str(error)
                logger.exception(
                    "Coding attempt %d/%d for feature_id=%s raised an unexpected error -- "
                    "committing partial progress and retrying.",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                )

            try:
                workspace_service.commit_changes(
                    project_id, feature_id, message=f"Coder Agent attempt {attempt}: {feature_id}"
                )
            except Exception as commit_error:
                logger.exception(
                    "Coding attempt %d/%d for feature_id=%s: commit_changes itself failed",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                )
                attempt_error = attempt_error or f"Failed to commit changes: {commit_error}"

            touched_error: str | None = None
            try:
                already_touched = workspace_service.get_touched_files(
                    project_id, feature_id, since=revision_start_sha or MAIN_BRANCH
                )
            except Exception as touched_exc:
                logger.exception(
                    "Coding attempt %d/%d for feature_id=%s: get_touched_files itself failed",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                )
                touched_error = str(touched_exc)
                already_touched = {"added": [], "modified": [], "deleted": []}

            gaps = self._find_plan_gaps(code_plan_json, already_touched)

            # Skipped entirely (not just short-circuited inside the helper) when there's no
            # manifest to check against -- both an optimization (one fewer real get_touched_files
            # call for the common case of a feature with no approved UI/UX design at all) and
            # what keeps this a strictly additive change for every existing caller that never
            # passes ui_integration_manifest_json.
            design_gap: str | None = None
            if ui_integration_manifest_json:
                try:
                    this_attempt_touched = workspace_service.get_touched_files(
                        project_id, feature_id, since=attempt_start_sha
                    )
                    design_gap = self._find_unread_ui_design_gap(
                        ui_integration_manifest_json, this_attempt_touched, ui_design_read_tracker
                    )
                except Exception:
                    # Non-fatal by design -- see the identical comment in
                    # _code_with_retries_stream.
                    logger.exception(
                        "Coding attempt %d/%d for feature_id=%s: UI-fidelity gap check itself "
                        "failed -- skipping the check for this attempt",
                        attempt,
                        MAX_CODING_ATTEMPTS,
                        feature_id,
                    )

            if gaps or hit_recursion_limit or attempt_error or touched_error or design_gap:
                logger.warning(
                    "Coding attempt %d/%d for feature_id=%s left %d planned file(s) untouched",
                    attempt,
                    MAX_CODING_ATTEMPTS,
                    feature_id,
                    len(gaps),
                )
                prior_failure_output = self._format_plan_gaps(gaps)
                if hit_recursion_limit:
                    prior_failure_output = (
                        "The previous attempt ran out of turns before finishing -- work "
                        "efficiently this time: do not re-read files you already know the "
                        "contents of, do not call check_syntax more than once per file, and "
                        "prioritize finishing every remaining planned file over polishing ones "
                        "that are already correct.\n\n" + (prior_failure_output or "")
                    )
                if attempt_error:
                    prior_failure_output = (
                        f"The previous attempt failed with an unexpected error: {attempt_error}\n\n"
                        + (prior_failure_output or "")
                    )
                if touched_error:
                    prior_failure_output = (
                        "Could not determine which files were touched by the previous attempt "
                        f"(error: {touched_error}) -- proceed carefully and re-check your work.\n\n"
                        + (prior_failure_output or "")
                    )
                if design_gap:
                    prior_failure_output = design_gap + "\n\n" + (prior_failure_output or "")
                verify_result = {
                    "passed": False,
                    "steps": [
                        {
                            "name": "planned files touched",
                            "status": "failed",
                            "output": prior_failure_output,
                        }
                    ],
                }
                continue

            verify_result = self.verifier.verify(
                project_id, feature_id, code_plan_json, original_request,
                ui_expectations=(srs_json or {}).get("ui_expectations"),
            )

            if verify_result["passed"]:
                return verify_result, attempt

            logger.warning(
                "Coding attempt %d/%d failed verification for feature_id=%s",
                attempt,
                MAX_CODING_ATTEMPTS,
                feature_id,
            )
            prior_failure_output = self._summarize_verify_failure(verify_result)

        return verify_result, MAX_CODING_ATTEMPTS

    def _find_plan_gaps(
        self, code_plan_json: dict[str, Any], touched: dict[str, list[str]]
    ) -> list[dict[str, str]]:
        """
        Deterministically compute which planned files were never created,
        modified, or deleted this attempt -- computed from git (via
        workspace_service.get_touched_files), never trusted from the coding
        loop's own self-report that it "finished." Runs before the expensive
        verify.py gate (npm install x2, server boot, client build) so a
        plan that's silently incomplete fails fast and cheaply instead of
        only being caught after minutes of infra checks that were never
        going to matter.
        """
        touched_paths = set(touched["added"]) | set(touched["modified"]) | set(touched["deleted"])

        return [
            {
                "path": file_entry["path"],
                "action": file_entry.get("action", ""),
                "rationale": file_entry.get("rationale", ""),
            }
            for file_entry in code_plan_json.get("files", [])
            if file_entry.get("path") and file_entry["path"] not in touched_paths
        ]

    def _format_plan_gaps(self, gaps: list[dict[str, str]]) -> str:
        lines = [f"- {gap['path']} (action: {gap['action']}, rationale: {gap['rationale']})" for gap in gaps]
        return (
            "The following planned files were never created, modified, or deleted in this "
            "attempt -- implement these before doing anything else:\n" + "\n".join(lines)
        )

    def _find_unread_ui_design_gap(
        self,
        ui_integration_manifest_json: dict[str, Any] | None,
        this_attempt_touched: dict[str, list[str]],
        ui_design_read_tracker: dict[str, set[str]],
    ) -> str | None:
        """
        Deterministic backstop for the advisory list_unread_ui_designs self-check tool: if an
        approved UI/UX design exists for this feature and THIS ATTEMPT (checked per-attempt via
        the caller's `since=attempt_start_sha` -- a plan can naturally split backend-first, so
        whichever attempt is the one that actually writes frontend code is the one this needs to
        catch, regardless of its number) wrote/modified a frontend file (under app/ or
        components/, the Next.js scaffold's real frontend roots, matching
        style_checker.check_component_styling's own established scan scope) while
        `ui_design_read_tracker` (an object the CALLER creates ONCE per whole `_code_with_retries`
        call, not per attempt -- see that method's own comment) is still completely empty, treat
        it like a plan gap and retry with an explicit instruction to read the design first --
        rather than trusting the prompt-only instruction alone, this codebase's own
        repeatedly-documented "ask nicely -> decide deterministically" lesson.

        Deliberately coarse in TWO ways, both accepted tradeoffs, not oversights:
        1. "Was anything read at ALL," not "was the SPECIFIC relevant design read" -- avoids
           needing a reliable path->component/page mapping this pipeline doesn't otherwise have;
           still catches the single most likely real failure mode, the model ignoring the design
           reference outright.
        2. Per-RUN, not per-attempt, since the tracker persists across every attempt of one call:
           once ANY attempt has read a relevant design, every LATER attempt is free to touch a
           DIFFERENT, never-read design (or re-touch an unrelated frontend file, e.g. a nav-link
           patch, while fixing something else entirely) without tripping this check again. A real,
           live run confirmed the per-attempt-reset alternative is actively harmful: a later
           attempt trying to fix a genuine bug got rejected by this exact check for re-touching an
           already-correct nav-link file without a fresh read that attempt, consuming the run's
           last attempt before its real fix could ever reach a second real verify() call. Weaker
           as a per-page/component guarantee, but matches what a human reviewer actually means by
           "did this run consult the approved design" -- once, not every single time.
        """
        if not ui_integration_manifest_json or not ui_integration_manifest_json.get("pages"):
            return None

        touched_paths = set(this_attempt_touched.get("added", [])) | set(
            this_attempt_touched.get("modified", [])
        )
        # .tsx specifically (not just an app/ prefix) is what actually distinguishes a real
        # page/component file from an app/api/.../route.ts backend file -- both live under app/
        # in Next.js's file-based routing, but only pages/components (.tsx) are ever a UI/UX
        # visual-fidelity concern.
        touched_frontend = any(
            path.startswith(("app/", "components/")) and path.endswith(".tsx") for path in touched_paths
        )

        if not touched_frontend:
            return None

        read_any = bool(ui_design_read_tracker.get("components")) or bool(
            ui_design_read_tracker.get("pages")
        )
        if read_any:
            return None

        return (
            "This attempt wrote or modified frontend code (under app/ or components/) but never "
            "called read_ui_component_design or read_ui_page_design, even though an approved "
            "UI/UX design exists for this feature. Call list_unread_ui_designs, then read the "
            "design(s) relevant to the page/component you are writing, and make your TSX "
            "faithfully match its layout, Tailwind classes, and content before continuing."
        )

    def _summarize_verify_failure(self, verify_result: dict[str, Any]) -> str:
        failed_steps = [step for step in verify_result["steps"] if step["status"] == "failed"]
        return "\n\n".join(f"[{step['name']}]\n{step['output']}" for step in failed_steps)

    def _save_artifacts(self, project: dict, feature: dict, output: CoderAgentOutput) -> list[str]:
        version = artifact_service.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=AgentName.CODER,
            artifact_type=ArtifactType.CODE_PLAN,
        )

        feature_slug = self._feature_slug(feature)
        artifact_ids = []

        plan_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.CODER,
            artifact_type=ArtifactType.CODE_PLAN,
            filename=f"{feature_slug}_code_plan_v{{version}}.json",
            data=output.code_plan_json,
            version_override=version,
            summary=output.code_plan_json.get("summary") if output.code_plan_json else None,
        )
        artifact_ids.append(plan_artifact.artifact_id)

        file_tree_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.CODER,
            artifact_type=ArtifactType.CODE_DIFF,
            filename=f"{feature_slug}_file_tree_v{{version}}.json",
            data=output.file_tree_json,
            version_override=version,
        )
        artifact_ids.append(file_tree_artifact.artifact_id)

        merge_report_artifact = artifact_service.save_text_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.CODER,
            artifact_type=ArtifactType.CODE_DIFF,
            artifact_format=ArtifactFormat.MARKDOWN,
            filename=f"{feature_slug}_merge_report_v{{version}}.md",
            content=output.merge_report_markdown,
            version_override=version,
        )
        artifact_ids.append(merge_report_artifact.artifact_id)

        manifest_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.CODER,
            artifact_type=ArtifactType.CODE_MANIFEST,
            filename=f"{feature_slug}_code_manifest_v{{version}}.json",
            data=output.code_manifest_json,
            version_override=version,
        )
        artifact_ids.append(manifest_artifact.artifact_id)

        req_map_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.CODER,
            artifact_type=ArtifactType.REQUIREMENT_CODE_MAP,
            filename=f"{feature_slug}_requirement_code_map_v{{version}}.json",
            data=output.requirement_code_map_json,
            version_override=version,
        )
        artifact_ids.append(req_map_artifact.artifact_id)

        setup_artifact = artifact_service.save_text_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.CODER,
            artifact_type=ArtifactType.SETUP_INSTRUCTIONS,
            artifact_format=ArtifactFormat.MARKDOWN,
            filename=f"{feature_slug}_setup_instructions_v{{version}}.md",
            content=output.setup_instructions_markdown,
            version_override=version,
        )
        artifact_ids.append(setup_artifact.artifact_id)

        return artifact_ids

    def merge_approved_feature(self, feature_id: str, version: int) -> None:
        """
        Merge an approved feature branch into main and update the project
        manifest so the next feature's plan_node sees what now exists.

        Called from approval_service.py only after the CODE_DIFF artifact for
        this exact version has been approved -- never before.
        """
        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project_id = feature["project_id"]

        patch = self._build_project_manifest_patch(feature_id, feature, version)

        workspace_service.merge_feature_branch(project_id, feature_id)
        project_memory_service.update_project_manifest(project_id, patch)

        logger.info(
            "Merged feature_id=%s version=%s into main; project manifest updated.",
            feature_id,
            version,
        )

    def discard_rejected_feature(self, feature_id: str) -> None:
        """
        Discard a rejected feature branch's changes.
        """
        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        workspace_service.discard_feature_branch(feature["project_id"], feature_id)
        logger.info("Discarded rejected feature branch for feature_id=%s", feature_id)

    def _build_project_manifest_patch(
        self, feature_id: str, feature: dict, version: int
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {
            "routes": [],
            "api_endpoints": [],
            "models": [],
            "shared_components": [],
            "features": {},
        }

        plan_artifact = self._find_artifact_by_version(
            feature_id, AgentName.CODER, ArtifactType.CODE_PLAN, ArtifactFormat.JSON, version
        )
        file_tree_artifact = self._find_artifact_by_version(
            feature_id, AgentName.CODER, ArtifactType.CODE_DIFF, ArtifactFormat.JSON, version
        )

        if not plan_artifact or not file_tree_artifact:
            return patch

        code_plan_json = read_json_file(plan_artifact["file_path"])
        file_tree_json = read_json_file(file_tree_artifact["file_path"])
        touched = set(file_tree_json.get("added", [])) | set(file_tree_json.get("modified", []))

        for file_entry in code_plan_json.get("files", []):
            path = file_entry.get("path")
            if path not in touched:
                continue

            if "/routes/" in path:
                patch["routes"].append(path)
            elif "/models/" in path:
                patch["models"].append(path)
            elif "/components/" in path:
                patch["shared_components"].append(path)

            for mapped in file_entry.get("maps_to", []):
                if isinstance(mapped, str) and mapped.startswith("/"):
                    patch["api_endpoints"].append(mapped)

        patch["features"][feature_id] = {
            "feature_name": feature.get("feature_name"),
            "files": sorted(touched),
        }

        return patch

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
        Tries the current ArtifactType.ARCHITECTURE_PLAN first, then falls
        back to the legacy ArtifactType.SDS (see UIUXAgent for the same
        pattern and rationale).
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

    def _load_approved_ui_integration_manifest(self, feature_id: str) -> dict | None:
        artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            agent_name=AgentName.UIUX,
            artifact_type=ArtifactType.UI_INTEGRATION_MANIFEST,
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


coder_agent = CoderAgent()
