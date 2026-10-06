"""
Requirement Agent.

Purpose:
- Generate initial SRS for one feature.
- Ask LLM to generate JSON only.
- Convert JSON to Markdown inside Requirement Agent.
- Save both JSON and Markdown artifacts.
- Keep all logic Requirement-Agent-specific.

This file does not change:
- LLM provider
- shared markdown utilities
- other agents
"""

import json
import re

from app.agents.requirement_agent.conversation_engine import (
    _deterministic_gap_checklist,
    ensure_srs_completeness,
    extract_json_object,
    parse_gap_analysis_response,
    project_ba_input_to_srs_shape,
    run_gap_analysis,
)
from app.agents.requirement_agent.conversation_quality_gate import assess as assess_quality_gate
from app.agents.requirement_agent.revision_patcher import apply_revision_operations
from app.agents.requirement_agent.markdown_builder import RequirementSRSMarkdownBuilder
from app.agents.requirement_agent.prompt import (
    GAP_ANALYSIS_SYSTEM_PROMPT,
    JSON_REPAIR_PROMPT,
    REQUIREMENT_AGENT_SYSTEM_PROMPT,
    build_gap_analysis_user_prompt,
    build_json_repair_prompt,
    build_requirement_user_prompt,
    REQUIREMENT_REVISION_SYSTEM_PROMPT,
    build_requirement_revision_prompt,
)
from datetime import datetime, timezone
from app.agents.requirement_agent.schemas import RequirementAgentOutput
from app.core.enums import AgentName, ArtifactFormat, ArtifactType, FeatureStatus
from app.schemas.agent_schema import AgentRunResponse
from app.schemas.requirement_conversation_schema import (
    RequirementConversationConfirmRequest,
    RequirementConversationReplyRequest,
    RequirementConversationState,
)
from app.schemas.requirement_schema import (
    RequirementAgentRunRequest,
    RequirementAgentReviseRequest,
    RequirementBAInput,
)
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.services.llm_provider_service import llm_provider_service
from app.utils.logger import get_logger
# from app.schemas.requirement_schema import RequirementAgentReviseRequest
from app.core.enums import ApprovalStatus
from app.utils.file_manager import read_json_file, write_json_file, write_text_file
from app.utils.id_generator import generate_id
from app.core.config import settings
from pathlib import Path
from app.services.rag.loaders import SUPPORTED_EXTENSIONS, load_text_from_bytes

logger = get_logger(__name__)

# A document attached to a conversational reply is scraped for its FULL text (not chunked/
# retrieved like Domain Agent's RAG library -- there's no meaningful "top K similar chunks"
# concept for a single one-off attachment where the whole point is not to lose anything). Capped
# defensively before it ever reaches the prompt: this project's own history documents Ollama's
# one-shot provider path (the same kind of call gap analysis makes) as having no explicit num_ctx
# override, so an unbounded document could silently get truncated by Ollama itself mid-JSON-field
# instead of cleanly at a text boundary the human can see.
MAX_ATTACHED_DOCUMENT_CHARS = 8000

# SRS fields the schema documents as list[str] (RequirementBAInput / requirement_schema.py) --
# distinct from the 5 ID-tagged sections (functional_requirements/non_functional_requirements/
# acceptance_criteria/validation_rules/user_stories), which are SUPPOSED to be
# {"id", "description", ...}-shaped objects. Used by _normalize_plain_list_fields, below.
PLAIN_LIST_SRS_FIELDS = [
    "scope", "out_of_scope", "user_roles", "input_requirements", "output_requirements",
    "ui_expectations", "api_expectations", "data_requirements", "constraints",
    "assumptions", "risks", "dependencies",
]


class RequirementAgent:
    """
    Main Requirement Agent class.

    This class controls the full Requirement Agent process:
    1. Read project and feature.
    2. Read BA input.
    3. Call LLM.
    4. Parse JSON.
    5. Build Markdown from JSON.
    6. Save artifacts.
    """

    REQUIRED_KEYS = [
        "project_id",
        "project_name",
        "project_type",
        "feature_id",
        "feature_name",
        "target_stack",
        "architectural_style",
        "business_goal",
        "functional_requirements",
        "non_functional_requirements",
        "acceptance_criteria",
        "constraints",
        "assumptions",
        "traceability",
    ]

    def __init__(self):
        """
        Initialize Requirement Agent dependencies.

        markdown_builder:
            Agent-specific builder used to convert SRS JSON into SRS Markdown.
        """
        self.markdown_builder = RequirementSRSMarkdownBuilder()

    async def run(self, feature_id: str, request: RequirementAgentRunRequest) -> AgentRunResponse:
        """
        Run the Requirement Agent.

        This method is called from:
            POST /features/{feature_id}/agents/requirement/run
        """

        logger.info("Requirement Agent started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)

        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])

        if not project:
            raise ValueError("Project not found for this feature.")

        # Update feature state.
        feature["feature_status"] = FeatureStatus.IN_PROGRESS
        feature["current_agent"] = AgentName.REQUIREMENT

        # Convert Pydantic request body to normal Python dictionary.
        ba_input = request.ba_input.model_dump(mode="json")

        # Fill missing values using project and feature data.
        ba_input = self._complete_ba_input(
            project=project,
            feature=feature,
            ba_input=ba_input
        )

        # Generate SRS JSON using LLM.
        output = await self._generate_requirement_output(
            project=project,
            feature=feature,
            ba_input=ba_input,
            human_comment=request.human_comment
        )

        artifact_ids = self._save_generated_srs_artifacts(
            project=project,
            feature=feature,
            srs_json=output.srs_json,
            srs_markdown=output.srs_markdown,
        )

        logger.info("Requirement Agent completed. artifacts=%s", artifact_ids)

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            status="completed",
            message=(
                "Requirement Agent completed successfully. "
                "SRS Markdown and SRS JSON artifacts were generated. "
                "Human approval is required before Domain Agent can run."
            ),
            artifact_ids=artifact_ids
        )

    def _save_generated_srs_artifacts(self, project: dict, feature: dict, srs_json: dict, srs_markdown: str) -> list[str]:
        """
        Save a freshly-generated SRS Markdown+JSON pair at one shared version. Factored out of
        run() so confirm_conversation() (the conversational gap-filling loop's final step) can
        reuse the exact same save path -- both produce a real ArtifactType.SRS version through
        the same code, which is what lets the existing approval_service gate work unchanged
        regardless of whether a human filled a form or had a conversation.
        """

        # Compute one shared version up front so the Markdown/JSON pair are always the same
        # version -- artifact_service supports this via version_override; calling
        # save_text_artifact/save_json_artifact without it lets each call independently claim
        # the next version, producing mismatched pairs like SRS_v1.md next to SRS_v2.json.
        version = artifact_service.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS
        )

        markdown_artifact = artifact_service.save_text_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.MARKDOWN,
            filename=self._build_feature_srs_filename(
                feature=feature,
                extension="md",
                version_placeholder=False,
                version=version
            ),
            content=srs_markdown,
            version_override=version
        )

        json_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS,
            filename=self._build_feature_srs_filename(
                feature=feature,
                extension="json",
                version_placeholder=False,
                version=version
            ),
            data=srs_json,
            version_override=version
        )

        return [markdown_artifact.artifact_id, json_artifact.artifact_id]

    # ------------------------------------------------------------------
    # Conversational gap-filling loop
    #
    # This is a parallel entry point to run()/revise() -- it never touches ArtifactType.SRS
    # until confirm_conversation(), and it never bypasses _complete_ba_input()/
    # _generate_requirement_output(); it only builds up the ba_input those already-existing
    # methods consume, incrementally, through a real conversation instead of one form
    # submission. State lives in store.requirement_conversations (one document per feature_id,
    # upserted each turn -- see in_memory_store.py's own docstring for why this is not
    # versioned like artifacts).
    # ------------------------------------------------------------------

    async def start_conversation(self, feature_id: str) -> RequirementConversationState:
        """
        Begin (or resume, if one is already in progress and not yet confirmed) a requirement
        conversation, seeded from the feature's own rough feature_description.
        """

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        existing = store.requirement_conversations.get(feature_id)

        # Reloading the page / calling start twice should not discard progress or waste another
        # LLM call -- only a genuinely new conversation (none yet, or the previous one was
        # already confirmed into a real SRS) starts fresh.
        if existing and existing.get("status") != "confirmed":
            return RequirementConversationState(**existing)

        if existing and existing.get("status") == "confirmed":
            store.requirement_conversations.collection.delete_one({"feature_id": feature_id})

        known_answers = {
            "project_type": project.get("project_type", ""),
            "feature_name": feature.get("feature_name", ""),
            "target_stack": project.get("target_stack", "Next.js"),
        }

        gap_result = await run_gap_analysis(
            project=project, feature=feature, known_answers=known_answers, latest_reply=None
        )

        return self._save_conversation_turn(
            feature_id, project, feature, gap_result, human_reply=None, known_answers_before=known_answers
        )

    async def reply_to_conversation(
        self, feature_id: str, request: RequirementConversationReplyRequest
    ) -> RequirementConversationState:
        """
        Apply the human's reply to the current batch of open_questions, run another gap-analysis
        round, and return the updated conversation state.
        """

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        existing = store.requirement_conversations.get(feature_id)
        if not existing:
            raise ValueError("No conversation in progress for this feature. Start one first.")

        if existing.get("status") == "confirmed":
            raise ValueError(
                "This conversation has already been confirmed into an SRS. "
                "Start a new conversation to gather requirements for a further revision."
            )

        known_answers_before = existing.get("known_answers", {})
        gap_result = await run_gap_analysis(
            project=project,
            feature=feature,
            known_answers=known_answers_before,
            latest_reply=request.reply,
        )

        return self._save_conversation_turn(
            feature_id,
            project,
            feature,
            gap_result,
            human_reply=request.reply,
            known_answers_before=known_answers_before,
        )

    async def reply_to_conversation_stream(self, feature_id: str, reply_text: str):
        """
        Streaming variant of reply_to_conversation -- yields events (dicts; the route layer
        serializes them) as the gap-analysis response is generated, so the frontend can show the
        agent's reaction+questions "typing" live instead of a blocking wait followed by a sudden
        reveal, matching confirm_conversation_stream's existing pattern. Events:
            {"type": "token", "text": "..."}  -- one chunk of raw LLM output
            {"type": "error", "message": "..."}  -- feature/project/conversation validation failed
            {"type": "done", "state": {...}}  -- the updated RequirementConversationState (as a
                                                  JSON-safe dict), same shape reply_to_conversation
                                                  returns

        Only the FIRST gap-analysis attempt streams -- the JSON-repair retry and the deterministic
        fallback (both rare, reliability-ladder paths) run exactly as run_gap_analysis already
        does, non-streamed, since there is no meaningful "live" content to show while repairing
        already-malformed output.
        """

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        existing = store.requirement_conversations.get(feature_id)
        if not existing:
            yield {"type": "error", "message": "No conversation in progress for this feature. Start one first."}
            return

        if existing.get("status") == "confirmed":
            yield {
                "type": "error",
                "message": (
                    "This conversation has already been confirmed into an SRS. "
                    "Start a new conversation to gather requirements for a further revision."
                ),
            }
            return

        known_answers_before = existing.get("known_answers", {})
        provider = llm_provider_service.get_provider(agent_name=AgentName.REQUIREMENT.value)
        prompt = build_gap_analysis_user_prompt(
            project=project, feature=feature, known_answers=known_answers_before, latest_reply=reply_text
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=GAP_ANALYSIS_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed gap analysis failed mid-stream for feature_id=%s: %s", feature_id, stream_error
            )

        raw_output = "".join(raw_chunks)

        try:
            gap_result = parse_gap_analysis_response(raw_output, known_answers_before)
        except Exception as first_error:
            logger.warning("Streamed gap analysis JSON parse failed: %s", first_error)
            try:
                repair_prompt = f"Repair this malformed JSON and return only valid JSON:\n\n{raw_output}"
                repaired = await provider.invoke_agent(
                    [
                        {
                            "role": "system",
                            "content": "You are a JSON repair assistant. Return only valid JSON, no markdown, no explanation.",
                        },
                        {"role": "user", "content": repair_prompt},
                    ]
                )
                gap_result = parse_gap_analysis_response(repaired, known_answers_before)
            except Exception as second_error:
                logger.warning(
                    "Streamed gap analysis JSON repair also failed: %s -- using deterministic checklist.",
                    second_error,
                )
                gap_result = _deterministic_gap_checklist(known_answers_before)

        state = self._save_conversation_turn(
            feature_id,
            project,
            feature,
            gap_result,
            human_reply=reply_text,
            known_answers_before=known_answers_before,
        )

        yield {"type": "done", "state": state.model_dump(mode="json")}

    async def reply_to_conversation_with_document(
        self, feature_id: str, file_bytes: bytes, filename: str, reply_text: str | None
    ) -> RequirementConversationState:
        """
        Same as reply_to_conversation, but the human's answer is (also) a text/PDF/DOCX/MD
        document attached in the chat -- e.g. a requirements brief they already have written up --
        instead of retyping everything by hand. The document's full text is extracted and handed
        to the same gap-analysis call as if it were the human's reply, so the LLM scrapes
        functional requirements, data fields, etc. directly out of it.

        Ephemeral by design: unlike Domain Agent's uploaded knowledge documents (a persistent,
        project-level library queried via RAG), this file is read into memory just long enough to
        extract its text and is never written anywhere permanent -- it's a one-off input to this
        turn, not a document meant to be referenced again later.
        """

        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{extension}'. Supported types: {sorted(SUPPORTED_EXTENSIONS)}"
            )

        if len(file_bytes) > settings.DOMAIN_MAX_UPLOAD_BYTES:
            raise ValueError(
                f"File is too large ({len(file_bytes)} bytes). "
                f"Maximum allowed is {settings.DOMAIN_MAX_UPLOAD_BYTES} bytes."
            )

        extracted_text = load_text_from_bytes(file_bytes, filename).strip()
        if not extracted_text:
            raise ValueError(f"Could not extract any text from '{filename}'. Is it empty or scanned/image-only?")

        truncated = len(extracted_text) > MAX_ATTACHED_DOCUMENT_CHARS
        document_text = extracted_text[:MAX_ATTACHED_DOCUMENT_CHARS]
        truncation_note = (
            f" (truncated to the first {MAX_ATTACHED_DOCUMENT_CHARS} characters)" if truncated else ""
        )

        typed_prefix = f"{reply_text.strip()}\n\n" if reply_text and reply_text.strip() else ""

        # Sent to the LLM: the full extracted text, so it has everything to scrape from.
        combined_reply = (
            f"{typed_prefix}Content extracted from attached file '{filename}'{truncation_note}:\n{document_text}"
        )
        # Shown in the chat transcript: short and readable -- the human doesn't need to see a raw
        # PDF dump replayed back at them every time they scroll past this turn.
        display_reply = f"{typed_prefix}\U0001F4CE Attached {filename}"

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        existing = store.requirement_conversations.get(feature_id)
        if not existing:
            raise ValueError("No conversation in progress for this feature. Start one first.")

        if existing.get("status") == "confirmed":
            raise ValueError(
                "This conversation has already been confirmed into an SRS. "
                "Start a new conversation to gather requirements for a further revision."
            )

        known_answers_before = existing.get("known_answers", {})
        gap_result = await run_gap_analysis(
            project=project,
            feature=feature,
            known_answers=known_answers_before,
            latest_reply=combined_reply,
        )

        return self._save_conversation_turn(
            feature_id,
            project,
            feature,
            gap_result,
            human_reply=display_reply,
            known_answers_before=known_answers_before,
        )

    async def edit_turn_reply(
        self, feature_id: str, turn_index: int, new_reply: str
    ) -> RequirementConversationState:
        """
        Edit an already-submitted human reply and regenerate the conversation from that point --
        mirrors ChatGPT/Claude's "edit message" flow. The edited turn and everything built on top
        of it (its own follow-up questions, and any later turns) are discarded and replaced with a
        fresh gap-analysis round seeded from known_answers_before -- the exact known_answers
        snapshot captured on the turn at the time its ORIGINAL reply was first processed, which is
        precisely what makes this rewind possible without re-deriving state from scratch.
        """

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        existing = store.requirement_conversations.get(feature_id)
        if not existing:
            raise ValueError("No conversation in progress for this feature.")

        if existing.get("status") == "confirmed":
            raise ValueError(
                "This conversation has already been confirmed into an SRS. "
                "Start a new conversation to gather requirements for a further revision."
            )

        existing_turns = existing.get("turn_history", [])
        turn_position = next(
            (i for i, turn in enumerate(existing_turns) if turn.get("turn_index") == turn_index), None
        )
        if turn_position is None:
            raise ValueError(f"No such turn: {turn_index}.")

        known_answers_before = existing_turns[turn_position].get("known_answers_before", {})
        kept_turns = existing_turns[:turn_position]

        gap_result = await run_gap_analysis(
            project=project, feature=feature, known_answers=known_answers_before, latest_reply=new_reply
        )

        return self._save_conversation_turn(
            feature_id,
            project,
            feature,
            gap_result,
            human_reply=new_reply,
            known_answers_before=known_answers_before,
            existing_turns_override=kept_turns,
        )

    async def edit_turn_reply_stream(self, feature_id: str, turn_index: int, new_reply: str):
        """
        Streaming variant of edit_turn_reply -- same rewind-and-regenerate logic (discard this
        turn and everything built on top of it, replay known_answers_before through a fresh
        gap-analysis round), but yields events as that round is generated, matching
        reply_to_conversation_stream's exact pattern. Events:
            {"type": "token", "text": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "state": {...}}  -- the updated RequirementConversationState (as a
                                                  JSON-safe dict), same shape edit_turn_reply
                                                  returns

        Only the FIRST gap-analysis attempt streams -- the JSON-repair retry and the deterministic
        fallback (both rare, reliability-ladder paths) run non-streamed, same reasoning as
        reply_to_conversation_stream.
        """

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        existing = store.requirement_conversations.get(feature_id)
        if not existing:
            yield {"type": "error", "message": "No conversation in progress for this feature."}
            return

        if existing.get("status") == "confirmed":
            yield {
                "type": "error",
                "message": (
                    "This conversation has already been confirmed into an SRS. "
                    "Start a new conversation to gather requirements for a further revision."
                ),
            }
            return

        existing_turns = existing.get("turn_history", [])
        turn_position = next(
            (i for i, turn in enumerate(existing_turns) if turn.get("turn_index") == turn_index), None
        )
        if turn_position is None:
            yield {"type": "error", "message": f"No such turn: {turn_index}."}
            return

        known_answers_before = existing_turns[turn_position].get("known_answers_before", {})
        kept_turns = existing_turns[:turn_position]

        provider = llm_provider_service.get_provider(agent_name=AgentName.REQUIREMENT.value)
        prompt = build_gap_analysis_user_prompt(
            project=project, feature=feature, known_answers=known_answers_before, latest_reply=new_reply
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=GAP_ANALYSIS_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed turn edit failed mid-stream for feature_id=%s turn_index=%s: %s",
                feature_id, turn_index, stream_error,
            )

        raw_output = "".join(raw_chunks)

        try:
            gap_result = parse_gap_analysis_response(raw_output, known_answers_before)
        except Exception as first_error:
            logger.warning("Streamed turn edit JSON parse failed: %s", first_error)
            try:
                repair_prompt = f"Repair this malformed JSON and return only valid JSON:\n\n{raw_output}"
                repaired = await provider.invoke_agent(
                    [
                        {
                            "role": "system",
                            "content": "You are a JSON repair assistant. Return only valid JSON, no markdown, no explanation.",
                        },
                        {"role": "user", "content": repair_prompt},
                    ]
                )
                gap_result = parse_gap_analysis_response(repaired, known_answers_before)
            except Exception as second_error:
                logger.warning(
                    "Streamed turn edit JSON repair also failed: %s -- using deterministic checklist.",
                    second_error,
                )
                gap_result = _deterministic_gap_checklist(known_answers_before)

        state = self._save_conversation_turn(
            feature_id,
            project,
            feature,
            gap_result,
            human_reply=new_reply,
            known_answers_before=known_answers_before,
            existing_turns_override=kept_turns,
        )

        yield {"type": "done", "state": state.model_dump(mode="json")}

    def get_conversation(self, feature_id: str) -> RequirementConversationState | None:
        """
        Return the current conversation state for this feature, or None if none exists yet.
        """

        document = store.requirement_conversations.get(feature_id)
        if not document:
            return None

        return RequirementConversationState(**document)

    def reset_conversation(self, feature_id: str) -> None:
        """
        Discard the in-progress conversation for this feature (e.g. the human wants to start
        over). Never raises if there was nothing to discard.
        """

        store.requirement_conversations.collection.delete_one({"feature_id": feature_id})

    def _save_conversation_turn(
        self,
        feature_id: str,
        project: dict,
        feature: dict,
        gap_result,
        human_reply: str | None,
        known_answers_before: dict,
        existing_turns_override: list[dict] | None = None,
    ) -> RequirementConversationState:
        """
        Shared tail end of start_conversation/reply_to_conversation/edit_turn_reply: project the
        updated known_answers into a live SRS preview (no LLM call -- see
        project_ba_input_to_srs_shape), run the deterministic quality gate against it, append this
        turn to the conversation's history, and upsert the whole document.

        `existing_turns_override`, when given (only edit_turn_reply does), REPLACES the normal
        "read whatever's currently stored" lookup with an explicit, already-truncated turn list --
        this is what lets editing turn N discard turn N and everything after it, rather than
        appending on top of a now-stale branch. `assumptions_flagged` is recomputed from this turn
        list (each turn's own assumptions_flagged_this_turn) rather than read from the stored
        top-level field, so it's correct in both the normal-append case (identical result) and the
        truncated-edit case (a naive append would otherwise resurrect discarded turns' assumptions).
        """

        existing = store.requirement_conversations.get(feature_id) or {}
        existing_turns = existing_turns_override if existing_turns_override is not None else existing.get("turn_history", [])

        srs_preview, defaulted_fields = project_ba_input_to_srs_shape(
            project, feature, gap_result.known_answers
        )
        quality_gate = assess_quality_gate(
            srs_preview, defaulted_fields, feature.get("feature_description", "")
        )

        turn = {
            "turn_index": len(existing_turns) + 1,
            "questions_asked": gap_result.questions,
            "human_reply": human_reply,
            "assumptions_flagged_this_turn": gap_result.assumptions,
            "agent_reaction": gap_result.reaction,
            "known_answers_before": known_answers_before,
            "created_at": datetime.now(timezone.utc),
        }

        status = "ready_to_confirm" if (quality_gate.ready and not gap_result.questions) else "gathering"

        assumptions_flagged = [
            assumption
            for prior_turn in existing_turns
            for assumption in prior_turn.get("assumptions_flagged_this_turn", [])
        ] + list(gap_result.assumptions)

        document = {
            "feature_id": feature_id,
            "known_answers": gap_result.known_answers,
            "srs_preview": srs_preview,
            "open_questions": gap_result.questions,
            "assumptions_flagged": assumptions_flagged,
            "turn_history": list(existing_turns) + [turn],
            "status": status,
            "quality_gate": quality_gate.model_dump(mode="json"),
            "updated_at": datetime.now(timezone.utc),
        }

        store.requirement_conversations[feature_id] = document

        return RequirementConversationState(**document)

    async def confirm_conversation(
        self, feature_id: str, request: RequirementConversationConfirmRequest
    ) -> AgentRunResponse:
        """
        Final step: turn the conversation's accumulated known_answers into a real SRS through
        the SAME, unmodified _complete_ba_input()/_generate_requirement_output() path run() uses,
        and save it via the same _save_generated_srs_artifacts() helper -- this is what makes the
        result compose with the existing approval_service gate with zero changes to it: it only
        ever sees a normal ArtifactType.SRS artifact, exactly as today.

        The quality gate is re-checked here, server-side, regardless of what the frontend showed
        -- a direct API call cannot bypass it just by omitting override_quality_gate=True.
        """

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        conversation = store.requirement_conversations.get(feature_id)
        if not conversation:
            raise ValueError("No conversation in progress for this feature. Start one first.")

        known_answers = conversation.get("known_answers", {})

        # Normalize through RequirementBAInput for the same validation/aliasing run() already
        # gets from request.ba_input.model_dump() (e.g. architectural_style alias normalization).
        ba_input = RequirementBAInput(**known_answers).model_dump(mode="json")
        ba_input = self._complete_ba_input(project=project, feature=feature, ba_input=ba_input)

        srs_preview, defaulted_fields = project_ba_input_to_srs_shape(project, feature, ba_input)
        quality_gate = assess_quality_gate(
            srs_preview, defaulted_fields, feature.get("feature_description", "")
        )

        if not quality_gate.ready and not request.override_quality_gate:
            raise ValueError(
                "Conversation is not ready to confirm yet: "
                + "; ".join(quality_gate.reasons)
                + ". Answer the open questions, or resubmit with override_quality_gate=true "
                "and a reason."
            )

        feature["feature_status"] = FeatureStatus.IN_PROGRESS
        feature["current_agent"] = AgentName.REQUIREMENT

        output = await self._generate_requirement_output(
            project=project, feature=feature, ba_input=ba_input, human_comment=None
        )

        if not quality_gate.ready and request.override_quality_gate:
            override_note = (
                f"Human confirmed despite {len(quality_gate.reasons)} unresolved quality-gate "
                f"warning(s): {'; '.join(quality_gate.reasons)}."
            )
            if request.override_reason:
                override_note += f" Override reason: {request.override_reason}"

            output.srs_json["assumptions"] = list(output.srs_json.get("assumptions", [])) + [override_note]
            output.srs_markdown = self.markdown_builder.build(output.srs_json)

        artifact_ids = self._save_generated_srs_artifacts(
            project=project, feature=feature, srs_json=output.srs_json, srs_markdown=output.srs_markdown
        )

        conversation.update({"status": "confirmed", "updated_at": datetime.now(timezone.utc)})

        logger.info(
            "Requirement conversation confirmed for feature_id=%s artifacts=%s", feature_id, artifact_ids
        )

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            status="completed",
            message=(
                "Requirement Agent completed successfully via conversation. "
                "SRS Markdown and SRS JSON artifacts were generated. "
                "Human approval is required before Domain Agent can run."
            ),
            artifact_ids=artifact_ids,
        )

    async def confirm_conversation_stream(self, feature_id: str, request: RequirementConversationConfirmRequest):
        """
        Streaming variant of confirm_conversation -- same validation/quality-gate/save logic, but
        yields events (dicts; the route layer serializes them) as the SRS is generated, so the
        frontend can show the raw output "typing" live instead of a blocking wait followed by a
        sudden reveal. Events:
            {"type": "token", "text": "..."}  -- one chunk of raw LLM output
            {"type": "error", "message": "..."}  -- validation failed or generation errored
            {"type": "done", "artifact_ids": [...], "message": "..."}  -- saved, same shape run()
                                                                          /confirm_conversation return

        Only the FIRST generation attempt streams -- the JSON-repair retry and the deterministic
        fallback (both rare, reliability-ladder paths, not the common case) run exactly as
        _generate_requirement_output already does, non-streamed, since there is no meaningful
        "live" content to show while repairing already-malformed output.
        """

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])
        if not project:
            raise ValueError("Project not found for this feature.")

        conversation = store.requirement_conversations.get(feature_id)
        if not conversation:
            raise ValueError("No conversation in progress for this feature. Start one first.")

        known_answers = conversation.get("known_answers", {})

        ba_input = RequirementBAInput(**known_answers).model_dump(mode="json")
        ba_input = self._complete_ba_input(project=project, feature=feature, ba_input=ba_input)

        srs_preview, defaulted_fields = project_ba_input_to_srs_shape(project, feature, ba_input)
        quality_gate = assess_quality_gate(
            srs_preview, defaulted_fields, feature.get("feature_description", "")
        )

        if not quality_gate.ready and not request.override_quality_gate:
            yield {
                "type": "error",
                "message": (
                    "Conversation is not ready to confirm yet: " + "; ".join(quality_gate.reasons)
                    + ". Answer the open questions, or resubmit with override_quality_gate=true "
                    "and a reason."
                ),
            }
            return

        feature["feature_status"] = FeatureStatus.IN_PROGRESS
        feature["current_agent"] = AgentName.REQUIREMENT

        provider = llm_provider_service.get_provider(agent_name=AgentName.REQUIREMENT.value)
        prompt = build_requirement_user_prompt(
            project=project, feature=feature, ba_input=ba_input, human_comment=None
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=REQUIREMENT_AGENT_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning("Streamed SRS generation failed mid-stream for feature_id=%s: %s", feature_id, stream_error)

        raw_output = "".join(raw_chunks)

        try:
            srs_json = self._parse_and_validate_json(raw_output)
        except Exception as first_error:
            logger.warning("Streamed SRS JSON parse failed: %s", first_error)

            try:
                repair_prompt = build_json_repair_prompt(raw_output)
                repaired_output = await provider.invoke_agent(
                    [
                        {"role": "system", "content": JSON_REPAIR_PROMPT},
                        {"role": "user", "content": repair_prompt},
                    ]
                )
                srs_json = self._parse_and_validate_json(repaired_output)
            except Exception as second_error:
                logger.warning("JSON repair also failed: %s", second_error)
                srs_json = self._build_fallback_srs_json(project, feature, ba_input, reason=str(second_error))

        srs_json, srs_markdown = self._finalize_srs_json(srs_json)

        if not quality_gate.ready and request.override_quality_gate:
            override_note = (
                f"Human confirmed despite {len(quality_gate.reasons)} unresolved quality-gate "
                f"warning(s): {'; '.join(quality_gate.reasons)}."
            )
            if request.override_reason:
                override_note += f" Override reason: {request.override_reason}"

            srs_json["assumptions"] = list(srs_json.get("assumptions", [])) + [override_note]
            srs_markdown = self.markdown_builder.build(srs_json)

        artifact_ids = self._save_generated_srs_artifacts(
            project=project, feature=feature, srs_json=srs_json, srs_markdown=srs_markdown
        )

        conversation.update({"status": "confirmed", "updated_at": datetime.now(timezone.utc)})

        logger.info(
            "Requirement conversation confirmed (streamed) for feature_id=%s artifacts=%s",
            feature_id, artifact_ids
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": (
                "Requirement Agent completed successfully via conversation. "
                "SRS Markdown and SRS JSON artifacts were generated. "
                "Human approval is required before Domain Agent can run."
            ),
        }

    def _finalize_srs_json(self, srs_json: dict) -> tuple[dict, str]:
        """
        Shared tail for every code path that produces a freshly-generated srs_json (real LLM
        success, JSON-repaired output, or the deterministic fallback) -- runs
        ensure_srs_completeness (conversation_engine.py) as an unconditional, no-LLM guarantee
        that no section is left genuinely empty, appends its notes to assumptions, then builds
        the markdown.

        MUST be called from every real entry point that can produce a final srs_json, not just
        _generate_requirement_output -- confirmed real, reported bug: confirm_conversation_stream
        (the ONLY method the frontend actually calls for confirm) does not call
        _generate_requirement_output at all, it duplicates the parse/repair/fallback ladder
        inline. A completeness fix added to only one of them would silently never reach the other.
        """
        srs_json, completeness_notes = ensure_srs_completeness(srs_json)

        if completeness_notes:
            assumptions = srs_json.get("assumptions", [])
            if not isinstance(assumptions, list):
                assumptions = []
            srs_json["assumptions"] = assumptions + completeness_notes

        srs_markdown = self.markdown_builder.build(srs_json)
        return srs_json, srs_markdown

    async def _generate_requirement_output(self, project: dict, feature: dict, ba_input: dict, human_comment: str | None) -> RequirementAgentOutput:
        """
        Generate SRS output.

        Main approach:
        - Ask LLM for JSON only.
        - Try to parse JSON.
        - If parsing fails, ask LLM to repair JSON.
        - If repair fails, create fallback SRS JSON from BA input.
        - Convert final JSON to Markdown.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.REQUIREMENT.value)

        prompt = build_requirement_user_prompt(
            project=project,
            feature=feature,
            ba_input=ba_input,
            human_comment=human_comment
        )

        try:
            raw_output = await provider.invoke_agent([
                {
                    "role": "system",
                    "content": REQUIREMENT_AGENT_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ])
        except Exception as call_error:
            # This call was previously unprotected -- an unreachable LLM server crashed SRS
            # generation outright with a raw exception instead of degrading like every other
            # failure mode here does. There's nothing to "repair" when the call itself never
            # produced output, so go straight to the same deterministic fallback the repair
            # ladder below already falls back to on total failure.
            logger.warning(
                "Initial SRS generation call failed (e.g. LLM server unreachable): %s -- using fallback SRS.",
                call_error,
            )
            srs_json = self._build_fallback_srs_json(
                project=project,
                feature=feature,
                ba_input=ba_input,
                reason=str(call_error)
            )
            raw_output = json.dumps(srs_json, indent=2)
            srs_json, srs_markdown = self._finalize_srs_json(srs_json)
            return RequirementAgentOutput(
                srs_json=srs_json,
                srs_markdown=srs_markdown,
                raw_llm_output=raw_output
            )

        try:
            srs_json = self._parse_and_validate_json(raw_output)

        except Exception as first_error:
            logger.warning("Initial SRS JSON parse failed: %s", first_error)

            try:
                repair_prompt = build_json_repair_prompt(raw_output)

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

                srs_json = self._parse_and_validate_json(repaired_output)
                raw_output = repaired_output

            except Exception as second_error:
                logger.warning("JSON repair failed: %s", second_error)

                # Final safe fallback.
                # This prevents the agent from failing completely.
                srs_json = self._build_fallback_srs_json(
                    project=project,
                    feature=feature,
                    ba_input=ba_input,
                    reason=str(second_error)
                )

                raw_output = json.dumps(srs_json, indent=2)

        srs_json, srs_markdown = self._finalize_srs_json(srs_json)

        return RequirementAgentOutput(
            srs_json=srs_json,
            srs_markdown=srs_markdown,
            raw_llm_output=raw_output
        )

    def _parse_and_validate_json(self, raw_output: str) -> dict:
        """
        Parse and validate LLM JSON output.

        This method is kept inside Requirement Agent to avoid changing
        shared/common JSON utilities.
        """

        parsed = self._extract_json_object(raw_output)

        # If the model returns {"srs_json": {...}}, accept it.
        if "srs_json" in parsed and isinstance(parsed["srs_json"], dict):
            parsed = parsed["srs_json"]

        # revision_summary (see REQUIREMENT_REVISION_SYSTEM_PROMPT) is the human-facing reply
        # text, not part of the SRS document itself -- it's extracted live from the raw stream on
        # the frontend (same mechanism as the conversation's "reaction" field), so it must never
        # be saved as a real field on the artifact. Harmless no-op for the non-revision generation
        # path, which never asks the model to produce this key in the first place.
        parsed.pop("revision_summary", None)

        missing = [key for key in self.REQUIRED_KEYS if key not in parsed]

        if missing:
            raise ValueError(f"Missing required SRS keys: {missing}")

        self._validate_stable_ids(parsed)
        self._normalize_plain_list_fields(parsed)

        return parsed

    def _normalize_plain_list_fields(self, parsed: dict) -> None:
        """
        Real, confirmed bug: the LLM generating an SRS mimicked the ID-tagged
        {"id", "description"} shape functional_requirements/acceptance_criteria/etc. use for a
        field that's documented (RequirementBAInput/requirement_schema.py) as a plain list[str]
        (data_requirements) -- nothing here checked the SHAPE of these fields, only that
        required top-level keys were present, so the malformed artifact saved cleanly and later
        crashed the frontend's document viewer ("Objects are not valid as a React child").

        Coerces every PLAIN_LIST_SRS_FIELDS entry to a plain string in place -- an object entry
        has its "description" (or "text"/"value") extracted, anything else is stringified. Never
        raises: a schema violation degrades to "the text still shows up correctly" instead of a
        saved artifact that crashes on first render.
        """
        for field in PLAIN_LIST_SRS_FIELDS:
            values = parsed.get(field)
            if not isinstance(values, list):
                continue

            normalized = []
            for entry in values:
                if isinstance(entry, str):
                    normalized.append(entry)
                elif isinstance(entry, dict):
                    text = entry.get("description") or entry.get("text") or entry.get("value")
                    normalized.append(text if isinstance(text, str) else json.dumps(entry))
                else:
                    normalized.append(str(entry))

            parsed[field] = normalized

    def _extract_json_object(self, text: str) -> dict:
        """
        Extract a JSON object from LLM output. Delegates to conversation_engine.extract_json_object
        (moved there so the conversational gap-filling loop can reuse it too) -- behavior unchanged.
        """

        return extract_json_object(text)

    def _parse_revision_plan(self, raw_output: str) -> dict:
        """
        Parse the small {"revision_summary", "operations"} shape a revision call now returns (see
        REQUIREMENT_REVISION_SYSTEM_PROMPT) -- deliberately NOT _parse_and_validate_json's
        REQUIRED_KEYS check, since a revision call no longer returns a full SRS document.
        """

        parsed = self._extract_json_object(raw_output)

        if not isinstance(parsed, dict):
            raise ValueError("Revision plan output was not a JSON object.")

        operations = parsed.get("operations", [])
        if not isinstance(operations, list):
            raise ValueError("Revision plan 'operations' field must be a list.")

        return {"revision_summary": parsed.get("revision_summary", ""), "operations": operations}

    def _apply_revision_plan(self, existing_srs_json: dict, plan: dict, revision_comment: str, revised_by: str) -> dict:
        """
        Deterministically apply a parsed revision plan's operations to the existing SRS (see
        revision_patcher.apply_revision_operations). Any operation the patcher couldn't confidently
        match, and the case where the LLM proposed zero operations at all, are surfaced directly in
        the revised SRS's own `assumptions` array -- so a human reviewer sees explicitly when a
        requested change did NOT happen, instead of it silently failing to happen at all.
        """

        operations = plan.get("operations", [])
        patched, applied, unmatched = apply_revision_operations(existing_srs_json, operations)

        patched["revision_metadata"] = {
            "revision_type": "srs_revision",
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
                f"No SRS changes were made for revision comment: {revision_comment!r} -- "
                f"agent's response: {plan.get('revision_summary') or '(no summary given)'}"
            )

        patched["assumptions"] = assumptions

        return patched

    def _validate_stable_ids(self, srs_json: dict) -> None:
        """
        Validate stable IDs in key requirement sections.

        Stable IDs are needed for traceability across agents.
        """

        sections = [
            "functional_requirements",
            "non_functional_requirements",
            "acceptance_criteria",
        ]

        for section_name in sections:
            section = srs_json.get(section_name, [])

            if not isinstance(section, list) or not section:
                raise ValueError(f"{section_name} must be a non-empty list.")

            for index, item in enumerate(section):
                if not isinstance(item, dict):
                    raise ValueError(f"{section_name}[{index}] must be an object.")

                if not item.get("id"):
                    raise ValueError(f"{section_name}[{index}] missing id.")

                if not item.get("description"):
                    raise ValueError(f"{section_name}[{index}] missing description.")

    def _complete_ba_input(self, project: dict, feature: dict, ba_input: dict) -> dict:
        """
        Fill missing BA input using project and feature metadata.
        """

        completed = dict(ba_input)

        completed["project_id"] = project["project_id"]
        completed["project_name"] = project["project_name"]
        completed["feature_id"] = feature["feature_id"]

        completed.setdefault("project_type", project["project_type"])
        completed.setdefault("feature_name", feature["feature_name"])
        completed.setdefault("target_stack", project["target_stack"])
        completed.setdefault("architectural_style", "modular")

        if not completed.get("business_goal"):
            completed["business_goal"] = (
                f"Deliver the {feature['feature_name']} feature "
                f"for the {project['project_type']} application."
            )

        if not completed.get("functional_requirements"):
            completed["functional_requirements"] = [
                feature["feature_description"]
            ]

        return completed

    def _build_fallback_srs_json(self, project: dict, feature: dict, ba_input: dict, reason: str) -> dict:
        """
        Build fallback SRS JSON if LLM JSON generation fails.

        Why:
        This prevents the Requirement Agent from completely failing.
        The fallback is basic but valid and reviewable by the human.

        Delegates the actual projection to conversation_engine.project_ba_input_to_srs_shape
        (shared with the conversational gap-filling loop's live preview) and appends this
        failure-specific reason -- that reason line must never appear in the live preview, which
        is why it's added here rather than inside the shared projection itself.
        """

        srs_json, _defaulted_fields = project_ba_input_to_srs_shape(project, feature, ba_input)

        srs_json["assumptions"] = list(srs_json.get("assumptions", [])) + [
            f"Fallback SRS was generated because LLM JSON parsing failed: {reason}"
        ]
        srs_json["risks"] = list(srs_json.get("risks", [])) + [
            "Fallback SRS may need human refinement before approval."
        ]

        return srs_json

    async def revise(self, feature_id: str, request: RequirementAgentReviseRequest) -> AgentRunResponse:
        """
        Revise the latest SRS for a feature.

        Steps:
        1. Find the feature.
        2. Find the project.
        3. Load the latest SRS JSON artifact.
        4. Send existing SRS + revision comment to LLM.
        5. Validate revised SRS JSON.
        6. Build revised SRS Markdown.
        7. Save new SRS version.
        8. Return new artifact IDs.
        """

        logger.info("Requirement Agent revision started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)

        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])

        if not project:
            raise ValueError("Project not found for this feature.")

        latest_srs_artifact = self._find_latest_srs_json_artifact(feature_id)

        if not latest_srs_artifact:
            raise ValueError(
                "No existing SRS JSON artifact found. "
                "Run Requirement Agent first before requesting revision."
            )

        existing_srs_json = read_json_file(latest_srs_artifact["file_path"])

        revised_output = await self._revise_srs_json(
            project=project,
            feature=feature,
            existing_srs_json=existing_srs_json,
            revision_comment=request.revision_comment,
            revised_by=request.revised_by
        )

        artifact_ids = self._save_revised_srs_artifacts(
            project=project,
            feature=feature,
            srs_json=revised_output.srs_json,
            srs_markdown=revised_output.srs_markdown
        )

        logger.info(
            "Requirement Agent revision completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids
        )

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            status="revised",
            message=(
                "SRS revised successfully. "
                "A new SRS version was created and requires human approval."
            ),
            artifact_ids=artifact_ids
        )

    async def revise_stream(self, feature_id: str, revision_comment: str, revised_by: str):
        """
        Streaming variant of revise() -- same generation/save logic, but yields events (dicts;
        the route layer serializes them) as the revision plan is generated, so the frontend can
        show the agent's revision_summary reaction live instead of a blocking wait followed by a
        sudden reveal, matching confirm_conversation_stream's existing pattern. The streamed raw
        output is now the small {revision_summary, operations} plan, not the whole SRS (see
        REQUIREMENT_REVISION_SYSTEM_PROMPT's module docstring for why) -- the operations are then
        applied to the real document deterministically, non-streamed, once the plan is complete.
        Events:
            {"type": "token", "text": "..."}  -- one chunk of raw LLM output
            {"type": "error", "message": "..."}  -- validation failed
            {"type": "done", "artifact_ids": [...], "message": "..."}  -- saved, same shape
                                                                          revise() returns

        Only the FIRST revision attempt streams -- the JSON-repair retry and the deterministic
        fallback (both rare, reliability-ladder paths) run non-streamed, same reasoning as every
        other streaming method in this class.
        """

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        latest_srs_artifact = self._find_latest_srs_json_artifact(feature_id)
        if not latest_srs_artifact:
            yield {
                "type": "error",
                "message": (
                    "No existing SRS JSON artifact found. "
                    "Run Requirement Agent first before requesting revision."
                ),
            }
            return

        existing_srs_json = read_json_file(latest_srs_artifact["file_path"])

        provider = llm_provider_service.get_provider(agent_name=AgentName.REQUIREMENT.value)
        prompt = build_requirement_revision_prompt(
            project=project,
            feature=feature,
            existing_srs_json=existing_srs_json,
            revision_comment=revision_comment,
            revised_by=revised_by,
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=REQUIREMENT_REVISION_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed SRS revision failed mid-stream for feature_id=%s: %s", feature_id, stream_error
            )

        raw_output = "".join(raw_chunks)

        try:
            plan = self._parse_revision_plan(raw_output)
            revised_srs_json = self._apply_revision_plan(existing_srs_json, plan, revision_comment, revised_by)
        except Exception as first_error:
            logger.warning("Streamed SRS revision plan parse failed: %s", first_error)
            try:
                repair_prompt = build_json_repair_prompt(raw_output)
                repaired_output = await provider.invoke_agent(
                    [
                        {"role": "system", "content": JSON_REPAIR_PROMPT},
                        {"role": "user", "content": repair_prompt},
                    ]
                )
                plan = self._parse_revision_plan(repaired_output)
                revised_srs_json = self._apply_revision_plan(existing_srs_json, plan, revision_comment, revised_by)
            except Exception as second_error:
                logger.warning(
                    "Streamed SRS revision plan repair also failed: %s -- using fallback revision.",
                    second_error,
                )
                revised_srs_json = self._fallback_revise_srs_json(
                    existing_srs_json=existing_srs_json,
                    revision_comment=revision_comment,
                    revised_by=revised_by,
                    reason=str(second_error),
                )

        revised_markdown = self.markdown_builder.build(revised_srs_json)

        artifact_ids = self._save_revised_srs_artifacts(
            project=project, feature=feature, srs_json=revised_srs_json, srs_markdown=revised_markdown
        )

        logger.info(
            "Requirement Agent revision completed (streamed) for feature_id=%s artifacts=%s",
            feature_id, artifact_ids
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": (
                "SRS revised successfully. A new SRS version was created and requires human approval."
            ),
        }

#Adding helper method to find the latest SRS JSON artifact for a given feature.
    def _find_latest_srs_json_artifact(self, feature_id: str) -> dict | None:
        """
        Find the latest SRS JSON artifact for this feature.

        Why:
        Revision must be based on the latest generated SRS JSON.
        """

        matching_artifacts = []

        for artifact in store.artifacts.values():
            is_same_feature = artifact["feature_id"] == feature_id
            is_requirement_agent = (
                artifact["agent_name"] == AgentName.REQUIREMENT
                or artifact["agent_name"] == AgentName.REQUIREMENT.value
            )
            is_srs = (
                artifact["artifact_type"] == ArtifactType.SRS
                or artifact["artifact_type"] == ArtifactType.SRS.value
            )
            is_json = (
                artifact["artifact_format"] == ArtifactFormat.JSON
                or artifact["artifact_format"] == ArtifactFormat.JSON.value
            )

            if is_same_feature and is_requirement_agent and is_srs and is_json:
                matching_artifacts.append(artifact)

        if not matching_artifacts:
            return None

        return max(matching_artifacts, key=lambda item: item["version"])

#Adding helper method ( Use the LLM to decide WHAT to change, then apply it deterministically. If the LLM call/parse fails entirely, fallback revision is created safely.)
    async def _revise_srs_json(self, project: dict, feature: dict, existing_srs_json: dict, revision_comment: str, revised_by: str) -> RequirementAgentOutput:
        """
        Ask the LLM only for a small revision plan (see REQUIREMENT_REVISION_SYSTEM_PROMPT), then
        apply it to the existing SRS deterministically (_apply_revision_plan) -- NOT asking the
        LLM to retype the whole SRS. Same reliability ladder shape as every other Requirement
        Agent generation call: LLM call -> JSON-repair retry -> deterministic fallback.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.REQUIREMENT.value)

        prompt = build_requirement_revision_prompt(
            project=project,
            feature=feature,
            existing_srs_json=existing_srs_json,
            revision_comment=revision_comment,
            revised_by=revised_by
        )

        raw_output = await provider.invoke_agent([
            {
                "role": "system",
                "content": REQUIREMENT_REVISION_SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": prompt
            }
        ])

        try:
            plan = self._parse_revision_plan(raw_output)
        except Exception as first_error:
            logger.warning("SRS revision plan parse failed: %s", first_error)
            try:
                repair_prompt = build_json_repair_prompt(raw_output)
                repaired_output = await provider.invoke_agent([
                    {"role": "system", "content": JSON_REPAIR_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ])
                plan = self._parse_revision_plan(repaired_output)
            except Exception as second_error:
                logger.warning(
                    "SRS revision plan repair also failed: %s -- using fallback revision.", second_error
                )
                revised_srs_json = self._fallback_revise_srs_json(
                    existing_srs_json=existing_srs_json,
                    revision_comment=revision_comment,
                    revised_by=revised_by,
                    reason=str(second_error)
                )
                revised_markdown = self.markdown_builder.build(revised_srs_json)
                return RequirementAgentOutput(
                    srs_json=revised_srs_json,
                    srs_markdown=revised_markdown,
                    raw_llm_output=raw_output
                )

        revised_srs_json = self._apply_revision_plan(existing_srs_json, plan, revision_comment, revised_by)
        revised_markdown = self.markdown_builder.build(revised_srs_json)

        return RequirementAgentOutput(
            srs_json=revised_srs_json,
            srs_markdown=revised_markdown,
            raw_llm_output=raw_output
        )

#Adding a fallback revision method to create a safe revision of the existing SRS JSON if LLM revision fails.
    def _fallback_revise_srs_json(self, existing_srs_json: dict, revision_comment: str, revised_by: str, reason: str) -> dict:
        """
        Create a safe fallback revision if the LLM fails.

        This does not overwrite existing SRS.
        It appends revision information and adds a review note.
        """

        revised = dict(existing_srs_json)

        revised["revision_metadata"] = {
            "revision_type": "srs_revision",
            "revision_comment": revision_comment,
            "revised_by": revised_by,
            "fallback_used": True,
            "fallback_reason": reason
        }

        assumptions = revised.get("assumptions", [])

        if not isinstance(assumptions, list):
            assumptions = []

        assumptions.append(
            f"Revision requested by {revised_by}: {revision_comment}"
        )

        assumptions.append(
            f"Fallback revision was used because LLM revision failed: {reason}"
        )

        revised["assumptions"] = assumptions

        risks = revised.get("risks", [])

        if not isinstance(risks, list):
            risks = []

        risks.append(
            "This fallback revision should be reviewed carefully before approval."
        )

        revised["risks"] = risks

        return revised
    
#Addding artifact saving method inside Requirement Agent to save revised SRS JSON and Markdown artifacts.
    def _save_revised_srs_artifacts(self, project: dict, feature: dict,  srs_json: dict,srs_markdown: str) -> list[str]:
        """
        Save revised SRS Markdown and JSON using the same version number.

        This method is Requirement-Agent-specific.

        Why not change artifact_service.py?
        Because artifact_service.py is common for every agent.
        This keeps the SRS revision fix isolated to Requirement Agent.
        """

        version = artifact_service.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS
        )

        stage_folder = artifact_service.get_stage_folder(
            project_name=project["project_name"],
            feature_name=feature["feature_name"],
            agent_name=AgentName.REQUIREMENT
        )

        markdown_filename = self._build_feature_srs_filename(
            feature=feature,
            extension="md",
            version_placeholder=False,
            version=version
        )

        json_filename = self._build_feature_srs_filename(
            feature=feature,
            extension="json",
            version_placeholder=False,
            version=version
        )

        markdown_path = stage_folder / markdown_filename
        json_path = stage_folder / json_filename

        saved_markdown_path = write_text_file(markdown_path, srs_markdown)
        saved_json_path = write_json_file(json_path, srs_json)

        markdown_artifact_id = generate_id("artifact")
        json_artifact_id = generate_id("artifact")
        created_at = datetime.now(timezone.utc)

        store.artifacts[markdown_artifact_id] = {
            "artifact_id": markdown_artifact_id,
            "project_id": project["project_id"],
            "feature_id": feature["feature_id"],
            "agent_name": AgentName.REQUIREMENT,
            "artifact_type": ArtifactType.SRS,
            "artifact_format": ArtifactFormat.MARKDOWN,
            "file_path": saved_markdown_path,
            "version": version,
            "approval_status": ApprovalStatus.PENDING,
            "created_at": created_at,
        }

        store.artifacts[json_artifact_id] = {
            "artifact_id": json_artifact_id,
            "project_id": project["project_id"],
            "feature_id": feature["feature_id"],
            "agent_name": AgentName.REQUIREMENT,
            "artifact_type": ArtifactType.SRS,
            "artifact_format": ArtifactFormat.JSON,
            "file_path": saved_json_path,
            "version": version,
            "approval_status": ApprovalStatus.PENDING,
            "created_at": created_at,
        }

        return [
            markdown_artifact_id,
            json_artifact_id
        ]

    def _build_feature_srs_filename(self, feature: dict, extension: str, version_placeholder: bool = True, version: int | None = None) -> str:
        """
        Build Requirement Agent SRS filename based on the feature name.

        Example:
            Feature name: Login

            Markdown:
                login_srs_v1.md

            JSON:
                login_srs_v1.json

        Why this method is inside Requirement Agent:
        - This naming rule is only for Requirement Agent SRS files.
        - We do not change shared artifact_service.py.
        - Other agents can follow their own naming style later.
        """

        feature_name = feature.get("feature_name", "feature")

        # Convert feature name into safe file name.
        # Example: "Product Listing" -> "product_listing"
        feature_slug = feature_name.lower().strip()

        # Replace spaces and special characters with underscore.
        feature_slug = re.sub(r"[^a-z0-9]+", "_", feature_slug)

        # Remove starting/ending underscores.
        feature_slug = feature_slug.strip("_")

        if not feature_slug:
            feature_slug = "feature"

        if version_placeholder:
            # Used when artifact_service will inject the version.
            # Double braces are needed to keep {version} as text.
            return f"{feature_slug}_srs_v{{version}}.{extension}"

        if version is None:
            raise ValueError("version is required when version_placeholder=False")

        # Used when we manually know the version number.
        return f"{feature_slug}_srs_v{version}.{extension}"



requirement_agent = RequirementAgent()