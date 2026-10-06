"""
Domain Agent.

Purpose:
- Retrieve domain knowledge (RAG: embed query -> ChromaDB similarity search -> top-K chunks)
  for the approved SRS of one feature.
- Ask the LLM to propose a SMALL enrichment plan (new items + description enrichments, citing
  only the retrieved knowledge) -- never to retype the whole SRS.
- Deterministically merge the validated plan into a full copy of the SRS in Python, producing
  the Enhanced SRS JSON (inline-flagged with what was added/changed) and a human-readable
  Domain Improvements JSON summary.
- Convert JSON to Markdown inside Domain Agent (mirrors Requirement Agent's approach).
- Save Markdown, Enhanced SRS JSON, and Domain Improvements JSON as a shared-version artifact
  group.

This file does not change:
- LLM provider
- shared markdown utilities

Deliberate exception to "other agents stay untouched" above: revise()/revise_stream() import
Requirement Agent's `apply_revision_operations` (revision_patcher.py) to apply direct
remove/modify/set edits to the Enhanced SRS -- a real, reported gap: Domain Agent's own
enrichment-plan schema (additions/modifications) can only ADD or enrich-describe existing items,
with no way to express "remove this" or "replace this outright," so a human asking to remove or
edit something already in the document was silently ignored. `apply_revision_operations` is a
generic, feature-independent SRS-shaped-document patcher with no Requirement-Agent-specific
dependencies (matches by field name + id/text, same document shape the Enhanced SRS shares) --
reusing it directly avoids re-implementing ~300 lines of already-working, already-tested matching
logic. It is NOT modified here, only imported.

Retrieval is deterministic Python (via domain_knowledge_service), never an LLM tool-calling
loop -- the Domain Agent stays on the one-shot BaseLLMProvider path like Requirement and
Architecture Agents, per this repo's build spec.

Design note (why the LLM never retypes the SRS -- see also prompt.py):
An earlier version of this agent asked the LLM to return the ENTIRE enhanced SRS JSON verbatim
plus a separate improvements summary in one response. Real end-to-end testing against three
different locally-hosted models (qwen3-coder, gemma4, llama3) showed this reliably fails --
models silently dropped required sections, omitted top-level keys, or produced
truncated/malformed JSON. The LLM now proposes only a small enrichment PLAN (see
_apply_enrichment_plan below); Python performs the actual merge, so required LLM output stays
small regardless of SRS size and IDs are never invented by the model.
"""

import copy
import json
import re
from datetime import datetime, timezone

from app.agents.domain_agent.domain_validator import (
    ADDITION_ONLY_SECTIONS,
    DomainEnhancementValidator,
)
from app.agents.domain_agent.markdown_builder import DomainEnhancedSRSMarkdownBuilder
from app.agents.domain_agent.prompt import (
    DOMAIN_AGENT_SYSTEM_PROMPT,
    DOMAIN_REVISION_SYSTEM_PROMPT,
    JSON_REPAIR_PROMPT,
    build_domain_revision_prompt,
    build_domain_user_prompt,
    build_json_repair_prompt,
)
from app.agents.domain_agent.schemas import DomainAgentOutput
from app.agents.requirement_agent.revision_patcher import apply_revision_operations
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType, FeatureStatus
from app.schemas.agent_schema import AgentRunResponse
from app.schemas.domain_schema import DomainAgentReviseRequest, DomainAgentRunRequest
from app.services.artifact_service import artifact_service
from app.services.domain_knowledge_service import domain_knowledge_service
from app.services.in_memory_store import store
from app.services.llm_provider_service import llm_provider_service
from app.utils.file_manager import read_json_file
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Maximum characters of SRS prose fed into the retrieval query embedding. Capped to keep the
# query focused on dense, domain-relevant text rather than the entire SRS JSON dump.
RETRIEVAL_QUERY_MAX_CHARS = 3000

# Caps for "/"-pinned document chunks, sized defensively against a real gap: Domain Agent's
# one-shot provider path (llm_provider_service.get_provider -> provider.invoke_agent) sets no
# explicit num_ctx anywhere (only the Coder/Architecture tool-calling path does), so it runs at
# Ollama's server-side default context window. A pinned document larger than
# MAX_CHUNKS_PER_PINNED_DOCUMENT is re-ranked by relevance to the query (not truncated
# front-to-back) so the most useful excerpts survive the cap.
MAX_CHUNKS_PER_PINNED_DOCUMENT = 6
MAX_TOTAL_PINNED_CHUNKS = 12
MAX_TOTAL_RETRIEVED_CHUNKS = 16

# Section -> new-ID prefix, for deterministic "-DOM-" ID assignment (never left to the LLM).
SECTION_PREFIX_MAP = {
    "functional_requirements": "FR",
    "non_functional_requirements": "NFR",
    "acceptance_criteria": "AC",
    "validation_rules": "VR",
    "user_stories": "US",
}


class DomainAgent:
    """
    Main Domain Agent class.

    This class controls the full Domain Agent process:
    1. Read the latest approved SRS JSON for a feature.
    2. Retrieve relevant domain knowledge chunks (RAG).
    3. Ask the LLM for a small enrichment plan (additions/modifications only).
    4. Validate the plan against the raw SRS and the retrieved chunks.
    5. Deterministically merge the plan into a full SRS copy (Python, not the LLM).
    6. Build Markdown from the merged result.
    7. Save all three artifacts under one shared version.
    """

    def __init__(self):
        self.markdown_builder = DomainEnhancedSRSMarkdownBuilder()
        self.validator = DomainEnhancementValidator()

    async def run(self, feature_id: str, request: DomainAgentRunRequest) -> AgentRunResponse:
        """
        Run the Domain Agent.

        This method is called from:
            POST /features/{feature_id}/agents/domain/run
        """

        logger.info("Domain Agent started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)

        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])

        if not project:
            raise ValueError("Project not found for this feature.")

        srs_artifact = self._find_latest_approved_srs_artifact(feature_id)

        if not srs_artifact:
            raise ValueError(
                "No approved SRS JSON artifact found. "
                "Approve Requirement Agent SRS JSON before running Domain Agent."
            )

        srs_json = read_json_file(srs_artifact["file_path"])

        feature["feature_status"] = FeatureStatus.IN_PROGRESS
        feature["current_agent"] = AgentName.DOMAIN

        retrieved_chunks = self._retrieve_domain_knowledge(
            srs_json,
            project_id=project["project_id"],
            referenced_document_ids=request.referenced_document_ids,
        )

        output = await self._generate_domain_output(
            project=project,
            feature=feature,
            srs_json=srs_json,
            retrieved_chunks=retrieved_chunks,
            human_comment=request.human_comment,
            srs_version=srs_artifact.get("version", 1),
        )

        artifact_ids = self._save_domain_artifacts(project=project, feature=feature, output=output)

        logger.info(
            "Domain Agent completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids,
        )

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.DOMAIN,
            status="completed",
            message=(
                "Domain Agent completed successfully. Enhanced SRS Markdown, Enhanced SRS "
                "JSON, and Domain Improvements JSON artifacts were generated. Human approval "
                "is required before Architecture Agent uses the Enhanced SRS."
            ),
            artifact_ids=artifact_ids,
        )

    async def run_stream(self, feature_id: str, request: DomainAgentRunRequest):
        """
        Streaming variant of run() -- yields events as the enrichment plan is generated, same
        mechanism and NDJSON event shape as RequirementAgent.revise_stream (see that method's own
        docstring): the small {summary, additions, modifications} plan "types" in live instead of
        a blocking wait, exactly like Requirement Agent already does. The plan is then parsed,
        validated, and merged into the SRS the SAME deterministic, non-streamed way run() already
        does (see _resolve_enrichment_plan/_apply_enrichment_plan) -- only the first LLM call
        streams; the rare repair/fallback paths do not.
        Events:
            {"type": "token", "text": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "message": "..."}
        """

        logger.info("Domain Agent (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        srs_artifact = self._find_latest_approved_srs_artifact(feature_id)
        if not srs_artifact:
            yield {
                "type": "error",
                "message": (
                    "No approved SRS JSON artifact found. "
                    "Approve Requirement Agent SRS JSON before running Domain Agent."
                ),
            }
            return

        srs_json = read_json_file(srs_artifact["file_path"])

        feature["feature_status"] = FeatureStatus.IN_PROGRESS
        feature["current_agent"] = AgentName.DOMAIN

        retrieved_chunks = self._retrieve_domain_knowledge(
            srs_json,
            project_id=project["project_id"],
            referenced_document_ids=request.referenced_document_ids,
        )

        provider = llm_provider_service.get_provider(agent_name=AgentName.DOMAIN.value)
        prompt = build_domain_user_prompt(
            project=project,
            feature=feature,
            srs_json=srs_json,
            retrieved_chunks=retrieved_chunks,
            human_comment=request.human_comment,
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=DOMAIN_AGENT_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed Domain Agent enrichment failed mid-stream for feature_id=%s: %s",
                feature_id,
                stream_error,
            )

        raw_output = "".join(raw_chunks)

        plan, fallback_used, fallback_reason = await self._resolve_enrichment_plan(
            provider, raw_output, srs_json, retrieved_chunks, bool(request.human_comment), "enrichment"
        )

        enhanced_srs_json, domain_improvements_json = self._apply_enrichment_plan(srs_json, plan, retrieved_chunks)

        self._finalize_enhanced_srs_metadata(
            enhanced_srs_json, srs_artifact.get("version", 1), retrieved_chunks, fallback_used, fallback_reason
        )

        enhanced_srs_markdown = self.markdown_builder.build(enhanced_srs_json, domain_improvements_json)

        output = DomainAgentOutput(
            enhanced_srs_markdown=enhanced_srs_markdown,
            enhanced_srs_json=enhanced_srs_json,
            domain_improvements_json=domain_improvements_json,
        )

        artifact_ids = self._save_domain_artifacts(project=project, feature=feature, output=output)

        logger.info(
            "Domain Agent (streamed) completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": (
                "Domain Agent completed successfully. Enhanced SRS Markdown, Enhanced SRS "
                "JSON, and Domain Improvements JSON artifacts were generated. Human approval "
                "is required before Architecture Agent uses the Enhanced SRS."
            ),
        }

    def _retrieve_domain_knowledge(
        self,
        srs_json: dict,
        project_id: str | None = None,
        referenced_document_ids: list[str] | None = None,
    ) -> list[dict]:
        """
        Retrieve domain knowledge chunks relevant to this feature's SRS.

        Combines two sources: chunks explicitly "/"-pinned by document_id (guaranteed inclusion,
        see _collect_pinned_chunks) and chunks found via similarity search, scoped to this
        project's own uploads plus the legacy global corpus
        (domain_knowledge_service.retrieve(..., project_id=...) never leaks another project's
        uploaded chunks in). Never raises -- an empty knowledge base or embedding failure just
        means fewer/no chunks.
        """

        query = self._build_retrieval_query(srs_json)
        pinned_chunks = self._collect_pinned_chunks(referenced_document_ids or [], query)
        similarity_chunks = domain_knowledge_service.retrieve(query, project_id=project_id)
        return self._merge_chunks(pinned_chunks, similarity_chunks)

    def _collect_pinned_chunks(self, referenced_document_ids: list[str], query_text: str) -> list[dict]:
        """
        Fetch every chunk of each explicitly-referenced document, capping an oversized document
        (or an oversized combined set) to its most query-relevant excerpts rather than an
        arbitrary front-of-document slice.

        Each returned chunk is tagged referenced_by_human=True -- this is what lets
        _format_retrieved_chunks (prompt.py) show these to the LLM as MANDATORY-to-use content
        instead of the same "consider if relevant" framing as an ordinary similarity-search hit.
        Real, reported gap this fixes: a human explicitly picking a file via "/" got no stronger
        treatment than generic background knowledge, so the model could -- and did -- ignore a
        selected document's content entirely, the same "enrichment is static/optional" complaint
        already fixed for TYPED human comments (see HUMAN_PROVIDED_SOURCE) but never extended to
        referenced files.
        """

        all_pinned: list[dict] = []

        for document_id in referenced_document_ids:
            doc_chunks = domain_knowledge_service.get_document_chunks(document_id)

            if len(doc_chunks) > MAX_CHUNKS_PER_PINNED_DOCUMENT:
                doc_chunks = domain_knowledge_service.rank_chunks_by_relevance(doc_chunks, query_text)
                doc_chunks = doc_chunks[:MAX_CHUNKS_PER_PINNED_DOCUMENT]

            all_pinned.extend(doc_chunks)

        if len(all_pinned) > MAX_TOTAL_PINNED_CHUNKS:
            all_pinned = domain_knowledge_service.rank_chunks_by_relevance(all_pinned, query_text)
            all_pinned = all_pinned[:MAX_TOTAL_PINNED_CHUNKS]

        for chunk in all_pinned:
            chunk["referenced_by_human"] = True

        return all_pinned

    def _merge_chunks(self, pinned_chunks: list[dict], similarity_chunks: list[dict]) -> list[dict]:
        """
        Pinned chunks always win: they're kept in full (up to the caps above), and similarity
        chunks fill whatever budget remains under MAX_TOTAL_RETRIEVED_CHUNKS, skipping any
        chunk_id already present among the pinned ones.
        """

        pinned_ids = {chunk["chunk_id"] for chunk in pinned_chunks}
        filtered_similarity = [chunk for chunk in similarity_chunks if chunk["chunk_id"] not in pinned_ids]
        remaining_budget = max(0, MAX_TOTAL_RETRIEVED_CHUNKS - len(pinned_chunks))
        return pinned_chunks + filtered_similarity[:remaining_budget]

    def _build_retrieval_query(self, srs_json: dict, extra_text: str | None = None) -> str:
        """
        Build the retrieval query text from the SRS's dense, domain-relevant prose fields.

        Deliberately excludes NFRs/constraints (generic, low domain-signal) and does not dump
        the raw JSON (punctuation/keys/ids add embedding noise).
        """

        parts: list[str] = [
            str(srs_json.get("feature_name", "")),
            str(srs_json.get("business_goal", "")),
        ]

        parts.extend(str(item) for item in srs_json.get("scope", []) if item)

        parts.extend(
            item.get("description", "")
            for item in srs_json.get("functional_requirements", [])
            if isinstance(item, dict) and item.get("description")
        )

        parts.extend(
            item.get("description", "")
            for item in srs_json.get("acceptance_criteria", [])
            if isinstance(item, dict) and item.get("description")
        )

        if extra_text:
            parts.append(extra_text)

        query = " ".join(part for part in parts if part)

        return query[:RETRIEVAL_QUERY_MAX_CHARS]

    async def _generate_domain_output(
        self,
        project: dict,
        feature: dict,
        srs_json: dict,
        retrieved_chunks: list[dict],
        human_comment: str | None,
        srs_version: int,
    ) -> DomainAgentOutput:
        """
        Generate Enhanced SRS + Domain Improvements output.

        Reliability ladder (mirrors Requirement Agent):
        - one-shot LLM call for a small enrichment PLAN (not the full SRS)
        - parse + validate the plan
        - on failure, one JSON-repair LLM call
        - on failure again, a deterministic empty-plan fallback that never fails
        - the plan (real or fallback) is always merged into the SRS by the same
          deterministic Python code, so the final artifacts are always well-formed.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.DOMAIN.value)

        prompt = build_domain_user_prompt(
            project=project,
            feature=feature,
            srs_json=srs_json,
            retrieved_chunks=retrieved_chunks,
            human_comment=human_comment,
        )

        raw_output = await provider.invoke_agent([
            {"role": "system", "content": DOMAIN_AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])

        plan, fallback_used, fallback_reason = await self._resolve_enrichment_plan(
            provider, raw_output, srs_json, retrieved_chunks, bool(human_comment), "enrichment"
        )

        enhanced_srs_json, domain_improvements_json = self._apply_enrichment_plan(srs_json, plan, retrieved_chunks)

        self._finalize_enhanced_srs_metadata(
            enhanced_srs_json, srs_version, retrieved_chunks, fallback_used, fallback_reason
        )

        enhanced_srs_markdown = self.markdown_builder.build(enhanced_srs_json, domain_improvements_json)

        return DomainAgentOutput(
            enhanced_srs_markdown=enhanced_srs_markdown,
            enhanced_srs_json=enhanced_srs_json,
            domain_improvements_json=domain_improvements_json,
        )

    def _parse_and_validate_plan(
        self,
        raw_output: str,
        base_srs_json: dict,
        retrieved_chunks: list[dict],
        human_comment_provided: bool = False,
    ) -> tuple[dict, list[str]]:
        """
        Parse the LLM's small enrichment plan and filter it down to only the independently-valid
        additions/modifications (see DomainEnhancementValidator.filter_valid_plan's own docstring
        for why lenient per-item filtering, not all-or-nothing rejection, is what real generation
        should use -- a real, observed failure mode: one hallucinated modification id used to
        discard an otherwise-correct, human-requested addition right along with it).

        Only raises for genuine structural problems (unparseable JSON, missing required top-level
        keys) -- the kind of failure the repair-prompt retry below is actually suited to fix.
        Returns (filtered_plan, dropped_reasons). filtered_plan's "operations" key (direct
        remove/modify/set edit commands -- see DOMAIN_REVISION_SYSTEM_PROMPT) passes through
        unvalidated here: apply_revision_operations (called separately, only during revise) has
        its own self-contained, report-don't-guess matching logic and needs no pre-filtering.
        """

        parsed = self._extract_json_object(raw_output)

        if "additions" not in parsed or "modifications" not in parsed:
            raise ValueError("LLM output missing required keys: additions, modifications")

        filtered_plan, dropped_reasons = self.validator.filter_valid_plan(
            base_srs_json, parsed, retrieved_chunks, human_comment_provided
        )

        operations = parsed.get("operations", [])
        filtered_plan["operations"] = operations if isinstance(operations, list) else []

        return filtered_plan, dropped_reasons

    async def _resolve_enrichment_plan(
        self,
        provider,
        raw_output: str,
        base_srs_json: dict,
        retrieved_chunks: list[dict],
        human_comment_provided: bool,
        context_label: str,
    ) -> tuple[dict, bool, str | None]:
        """
        Shared parse -> filter -> (on structural failure) repair -> (on failure again) fallback
        ladder, used by run()/revise() and their streaming counterparts alike -- one place for
        this logic instead of four near-identical copies. Returns (plan, fallback_used,
        fallback_reason).
        """

        try:
            plan, dropped_reasons = self._parse_and_validate_plan(
                raw_output, base_srs_json, retrieved_chunks, human_comment_provided
            )

        except Exception as first_error:
            logger.warning(
                "Initial Domain Agent %s plan parse failed: %s", context_label, first_error
            )

            repair_prompt = build_json_repair_prompt(raw_output)

            repaired_output = await provider.invoke_agent([
                {"role": "system", "content": JSON_REPAIR_PROMPT},
                {"role": "user", "content": repair_prompt},
            ])

            try:
                plan, dropped_reasons = self._parse_and_validate_plan(
                    repaired_output, base_srs_json, retrieved_chunks, human_comment_provided
                )

            except Exception as second_error:
                logger.warning(
                    "Domain Agent %s plan repair failed. Using fallback. Error=%s", context_label, second_error
                )
                fallback_reason = str(second_error)
                plan = self._build_fallback_plan(retrieved_chunks, reason=fallback_reason)
                return plan, True, fallback_reason

        if dropped_reasons:
            logger.info(
                "Domain Agent %s: dropped %d invalid plan item(s): %s",
                context_label,
                len(dropped_reasons),
                "; ".join(dropped_reasons),
            )

            # Every proposed item failed its own check -- honest about WHY nothing landed
            # (the specific dropped reasons) rather than the generic "nothing was retrieved"
            # message, which would be misleading when the LLM in fact tried and got it wrong.
            if not plan.get("additions") and not plan.get("modifications"):
                plan = {**plan, "no_changes_note": f"The proposed enrichment could not be applied: {'; '.join(dropped_reasons)}"}

        return plan, False, None

    def _extract_json_object(self, text: str) -> dict:
        """
        Extract a JSON object from LLM output.

        This is Domain-Agent-specific. It does not change shared json_utils.py.
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
            raise ValueError("No JSON object found in LLM output.")

        possible_json = cleaned[start:end + 1]

        return json.loads(possible_json)

    def _build_fallback_plan(self, retrieved_chunks: list[dict], reason: str) -> dict:
        """
        Build a fallback enrichment plan (no additions/modifications) if LLM generation fails.

        Why no fabricated content:
        There is no sensible way to regex/keyword-enrich real domain content, and inventing
        content here would violate the RAG honesty guarantee. The fallback plan is empty and
        _apply_enrichment_plan turns that into an unchanged SRS copy plus an honest explanation
        of why no enrichment was applied.
        """

        if not retrieved_chunks:
            no_changes_note = "No relevant domain knowledge was retrieved for this feature."
        else:
            no_changes_note = f"Domain knowledge was retrieved but automatic enrichment failed: {reason}"

        return {
            "summary": "No domain enrichment was applied to this SRS.",
            "additions": [],
            "modifications": [],
            "no_changes_note": no_changes_note,
        }

    def _apply_enrichment_plan(
        self, base_srs_json: dict, plan: dict, retrieved_chunks: list[dict]
    ) -> tuple[dict, dict]:
        """
        Deterministically merge a validated enrichment plan into a full copy of base_srs_json.

        This is the core of the redesign: the LLM never retypes the SRS or invents IDs. Python
        guarantees, by construction, that every original item survives untouched, every new
        item gets a correctly-namespaced "-DOM-" ID, and domain_improvements_json stays exactly
        consistent with what was actually applied to enhanced_srs_json.
        """

        enhanced_srs_json = copy.deepcopy(base_srs_json)

        for section_key in SECTION_PREFIX_MAP:
            enhanced_srs_json.setdefault(section_key, [])

        applied_additions: list[dict] = []
        applied_modifications: list[dict] = []
        citation_tally: dict[str, set[str]] = {}

        for addition in plan.get("additions", []):
            if not isinstance(addition, dict):
                continue

            target_section = addition.get("target_section")
            description = str(addition.get("description", "")).strip()

            if not description:
                continue

            # data_requirements, scope, out_of_scope, constraints, risks, dependencies, etc. are
            # all plain list[str] fields on the SRS (see markdown_builder.py's own rendering of
            # each) -- no per-item id/prefix to assign, just append the text. This is the natural
            # home for content that doesn't fit any of the FR/NFR/AC/VR/US item shapes: a database
            # schema (data_requirements), a scope boundary domain knowledge reveals (scope/
            # out_of_scope), a real regulatory/technical constraint (constraints), a specific,
            # known risk (risks), a third-party/external dependency (dependencies), an exact
            # endpoint/security expectation (api_expectations), etc. Deliberately covers every
            # ADDITION_ONLY_SECTIONS entry with the same logic, not just data_requirements -- see
            # that constant's own docstring for why Domain Agent previously could not touch these
            # sections at all, converging on non_functional_requirements/acceptance_criteria
            # almost every run regardless of what the retrieved knowledge actually supported.
            if target_section in ADDITION_ONLY_SECTIONS:
                citation = addition.get("domain_citation") or {}
                enhanced_srs_json.setdefault(target_section, [])
                enhanced_srs_json[target_section].append(description)

                applied_additions.append({
                    "target_section": target_section,
                    "new_id": None,
                    "description": description,
                    "rationale": addition.get("rationale", ""),
                    "domain_citation": citation,
                })

                self._tally_citation(citation_tally, citation)
                continue

            prefix = SECTION_PREFIX_MAP.get(target_section)

            if not prefix:
                continue

            new_id = self._next_dom_id(enhanced_srs_json[target_section], prefix)
            citation = addition.get("domain_citation") or {}

            new_item = {
                "id": new_id,
                "description": description,
                "origin": "domain_agent",
                "domain_citation": citation,
            }

            if target_section == "functional_requirements":
                new_item["priority"] = addition.get("priority") or "Should Have"
            elif target_section == "non_functional_requirements":
                new_item["category"] = addition.get("category") or "Domain"

            enhanced_srs_json[target_section].append(new_item)

            applied_additions.append({
                "target_section": target_section,
                "new_id": new_id,
                "description": description,
                "rationale": addition.get("rationale", ""),
                "domain_citation": citation,
            })

            self._tally_citation(citation_tally, citation)

        for modification in plan.get("modifications", []):
            if not isinstance(modification, dict):
                continue

            target_section = modification.get("target_section")
            item_id = modification.get("id")
            enhanced_description = str(modification.get("enhanced_description", "")).strip()

            if target_section not in SECTION_PREFIX_MAP or not item_id or not enhanced_description:
                continue

            item = self._find_item_by_id(enhanced_srs_json.get(target_section, []), item_id)

            if item is None:
                continue

            original_description = item.get("description", "")
            citation = modification.get("domain_citation") or {}

            item["description"] = enhanced_description
            item["modified_by_domain_agent"] = True
            item["original_description"] = original_description
            item["domain_citation"] = citation

            applied_modifications.append({
                "target_section": target_section,
                "id": item_id,
                "original_description": original_description,
                "enhanced_description": enhanced_description,
                "rationale": modification.get("rationale", ""),
                "domain_citation": citation,
            })

            self._tally_citation(citation_tally, citation)

        knowledge_sources_used = [
            {"source_document": source, "chunks_used": len(chunk_ids)}
            for source, chunk_ids in sorted(citation_tally.items())
        ]

        if applied_additions or applied_modifications:
            summary = plan.get("summary") or (
                f"Added {len(applied_additions)} domain requirement(s) and enriched "
                f"{len(applied_modifications)} existing item(s) using retrieved domain knowledge."
            )
            no_changes_note = None
        else:
            summary = "No domain enrichment was applied to this SRS."
            no_changes_note = plan.get("no_changes_note") or (
                "No relevant domain knowledge was retrieved for this feature."
                if not retrieved_chunks
                else "Domain knowledge was retrieved but no enrichment was proposed."
            )

        domain_improvements_json = {
            "summary": summary,
            "knowledge_sources_used": knowledge_sources_used,
            "additions": applied_additions,
            "modifications": applied_modifications,
            "no_changes_note": no_changes_note,
        }

        return enhanced_srs_json, domain_improvements_json

    def _next_dom_id(self, section_items: list[dict], prefix: str) -> str:
        """
        Deterministically assign the next "-DOM-" ID in a section, continuing past any that
        already exist (important for revisions, which merge onto an already-enriched SRS).
        """

        marker = f"{prefix}-DOM-"
        existing_numbers = []

        for item in section_items:
            item_id = str(item.get("id", ""))

            if item_id.startswith(marker):
                suffix = item_id[len(marker):]
                if suffix.isdigit():
                    existing_numbers.append(int(suffix))

        next_number = (max(existing_numbers) + 1) if existing_numbers else 1

        return f"{marker}{next_number:03d}"

    def _tally_citation(self, tally: dict[str, set[str]], citation: dict) -> None:
        source = citation.get("source_document")

        if not source:
            return

        chunk_id = citation.get("chunk_id") or source
        tally.setdefault(source, set()).add(chunk_id)

    def _find_item_by_id(self, items: list, item_id) -> dict | None:
        for item in items:
            if isinstance(item, dict) and item.get("id") == item_id:
                return item

        return None

    def _finalize_enhanced_srs_metadata(
        self,
        enhanced_srs_json: dict,
        srs_version: int,
        retrieved_chunks: list[dict],
        fallback_used: bool,
        fallback_reason: str | None,
    ) -> None:
        """
        Deterministically set domain_enrichment_metadata -- this data must be trustworthy
        regardless of LLM behavior, so it is never taken from the LLM's output.
        """

        sources_considered = sorted({
            chunk.get("source_document") for chunk in retrieved_chunks if chunk.get("source_document")
        })

        metadata = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "based_on_srs_version": srs_version,
            "knowledge_sources_considered": sources_considered,
            "fallback_used": fallback_used,
        }

        if fallback_used and fallback_reason:
            metadata["fallback_reason"] = fallback_reason

        enhanced_srs_json["domain_enrichment_metadata"] = metadata

    async def revise(self, feature_id: str, request: DomainAgentReviseRequest) -> AgentRunResponse:
        """
        Revise the latest Enhanced SRS for a feature.

        The revision plan is merged onto the CURRENT enhanced SRS (not the original raw SRS),
        so every previous domain addition/enrichment is preserved automatically -- the LLM only
        needs to describe the new change, never carry forward or re-cite prior work.
        """

        logger.info("Domain Agent revision started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)

        if not feature:
            raise ValueError("Feature not found.")

        project = store.projects.get(feature["project_id"])

        if not project:
            raise ValueError("Project not found for this feature.")

        latest_enhanced_srs_artifact = self._find_latest_domain_json_artifact(feature_id, ArtifactType.ENHANCED_SRS)

        if not latest_enhanced_srs_artifact:
            raise ValueError(
                "No existing Enhanced SRS JSON artifact found. "
                "Run Domain Agent first before requesting revision."
            )

        latest_improvements_artifact = self._find_latest_domain_json_artifact(
            feature_id, ArtifactType.DOMAIN_IMPROVEMENTS
        )

        existing_enhanced_srs_json = read_json_file(latest_enhanced_srs_artifact["file_path"])
        existing_domain_improvements_json = (
            read_json_file(latest_improvements_artifact["file_path"]) if latest_improvements_artifact else {}
        )

        srs_artifact = self._find_latest_approved_srs_artifact(feature_id)

        if not srs_artifact:
            raise ValueError("No approved SRS JSON artifact found for this feature.")

        retrieved_chunks = self._retrieve_domain_knowledge_for_revision(
            existing_enhanced_srs_json,
            request.revision_comment,
            project_id=project["project_id"],
            referenced_document_ids=request.referenced_document_ids,
        )

        output = await self._revise_domain_output(
            project=project,
            feature=feature,
            base_srs_json=existing_enhanced_srs_json,
            existing_domain_improvements_json=existing_domain_improvements_json,
            retrieved_chunks=retrieved_chunks,
            revision_comment=request.revision_comment,
            revised_by=request.revised_by,
            srs_version=srs_artifact.get("version", 1),
        )

        artifact_ids = self._save_domain_artifacts(project=project, feature=feature, output=output)

        logger.info(
            "Domain Agent revision completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids,
        )

        return AgentRunResponse(
            feature_id=feature_id,
            agent_name=AgentName.DOMAIN,
            status="revised",
            message=(
                "Enhanced SRS revised successfully. "
                "A new version was created and requires human approval."
            ),
            artifact_ids=artifact_ids,
        )

    def _retrieve_domain_knowledge_for_revision(
        self,
        existing_enhanced_srs_json: dict,
        revision_comment: str,
        project_id: str | None = None,
        referenced_document_ids: list[str] | None = None,
    ) -> list[dict]:
        query = self._build_retrieval_query(existing_enhanced_srs_json, extra_text=revision_comment)
        pinned_chunks = self._collect_pinned_chunks(referenced_document_ids or [], query)
        similarity_chunks = domain_knowledge_service.retrieve(query, project_id=project_id)
        return self._merge_chunks(pinned_chunks, similarity_chunks)

    async def revise_stream(self, feature_id: str, request: DomainAgentReviseRequest):
        """
        Streaming variant of revise() -- same generation/save logic as revise_stream's
        counterpart on Requirement Agent (see that method's own docstring) and the same
        merge/validate ladder run_stream above uses, just seeded from the CURRENT enhanced SRS
        (existing domain additions preserved automatically) instead of the raw approved SRS.
        Events:
            {"type": "token", "text": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "message": "..."}
        """

        logger.info("Domain Agent revision (streamed) started for feature_id=%s", feature_id)

        feature = store.features.get(feature_id)
        if not feature:
            yield {"type": "error", "message": "Feature not found."}
            return

        project = store.projects.get(feature["project_id"])
        if not project:
            yield {"type": "error", "message": "Project not found for this feature."}
            return

        latest_enhanced_srs_artifact = self._find_latest_domain_json_artifact(feature_id, ArtifactType.ENHANCED_SRS)
        if not latest_enhanced_srs_artifact:
            yield {
                "type": "error",
                "message": (
                    "No existing Enhanced SRS JSON artifact found. "
                    "Run Domain Agent first before requesting revision."
                ),
            }
            return

        latest_improvements_artifact = self._find_latest_domain_json_artifact(
            feature_id, ArtifactType.DOMAIN_IMPROVEMENTS
        )

        existing_enhanced_srs_json = read_json_file(latest_enhanced_srs_artifact["file_path"])
        existing_domain_improvements_json = (
            read_json_file(latest_improvements_artifact["file_path"]) if latest_improvements_artifact else {}
        )

        srs_artifact = self._find_latest_approved_srs_artifact(feature_id)
        if not srs_artifact:
            yield {"type": "error", "message": "No approved SRS JSON artifact found for this feature."}
            return

        retrieved_chunks = self._retrieve_domain_knowledge_for_revision(
            existing_enhanced_srs_json,
            request.revision_comment,
            project_id=project["project_id"],
            referenced_document_ids=request.referenced_document_ids,
        )

        provider = llm_provider_service.get_provider(agent_name=AgentName.DOMAIN.value)
        prompt = build_domain_revision_prompt(
            project=project,
            feature=feature,
            base_srs_json=existing_enhanced_srs_json,
            existing_domain_improvements_json=existing_domain_improvements_json,
            retrieved_chunks=retrieved_chunks,
            revision_comment=request.revision_comment,
            revised_by=request.revised_by,
        )

        raw_chunks: list[str] = []
        try:
            async for chunk in provider.stream(prompt=prompt, system_prompt=DOMAIN_REVISION_SYSTEM_PROMPT):
                raw_chunks.append(chunk)
                yield {"type": "token", "text": chunk}
        except Exception as stream_error:
            logger.warning(
                "Streamed Domain Agent revision failed mid-stream for feature_id=%s: %s",
                feature_id,
                stream_error,
            )

        raw_output = "".join(raw_chunks)

        plan, fallback_used, fallback_reason = await self._resolve_enrichment_plan(
            provider,
            raw_output,
            existing_enhanced_srs_json,
            retrieved_chunks,
            bool(request.revision_comment),
            "revision",
        )

        enhanced_srs_json, domain_improvements_json, _applied_ops, _unmatched_ops = self._apply_operations_and_merge(
            existing_enhanced_srs_json, plan, retrieved_chunks
        )

        enhanced_srs_json["revision_metadata"] = {
            "revision_type": "domain_enrichment_revision",
            "revision_comment": request.revision_comment,
            "revised_by": request.revised_by,
            "fallback_used": fallback_used,
            **({"fallback_reason": fallback_reason} if fallback_used and fallback_reason else {}),
        }

        if fallback_used:
            domain_improvements_json["no_changes_note"] = (
                f"Revision requested ('{request.revision_comment}') could not be automatically "
                f"applied: {fallback_reason}. Existing enrichment was preserved unchanged."
            )

        self._finalize_enhanced_srs_metadata(
            enhanced_srs_json, srs_artifact.get("version", 1), retrieved_chunks, fallback_used, fallback_reason
        )

        enhanced_srs_markdown = self.markdown_builder.build(enhanced_srs_json, domain_improvements_json)

        output = DomainAgentOutput(
            enhanced_srs_markdown=enhanced_srs_markdown,
            enhanced_srs_json=enhanced_srs_json,
            domain_improvements_json=domain_improvements_json,
        )

        artifact_ids = self._save_domain_artifacts(project=project, feature=feature, output=output)

        logger.info(
            "Domain Agent revision (streamed) completed for feature_id=%s artifacts=%s",
            feature_id,
            artifact_ids,
        )

        yield {
            "type": "done",
            "artifact_ids": artifact_ids,
            "message": "Enhanced SRS revised successfully. A new version was created and requires human approval.",
        }

    async def _revise_domain_output(
        self,
        project: dict,
        feature: dict,
        base_srs_json: dict,
        existing_domain_improvements_json: dict,
        retrieved_chunks: list[dict],
        revision_comment: str,
        revised_by: str,
        srs_version: int,
    ) -> DomainAgentOutput:
        """
        Use the LLM to propose a small revision enrichment plan, then merge it onto
        base_srs_json (the current enhanced SRS) using the same deterministic merge as
        initial generation. If LLM generation fails, the fallback is an empty plan --
        base_srs_json (and everything it already contains) is preserved unchanged.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.DOMAIN.value)

        prompt = build_domain_revision_prompt(
            project=project,
            feature=feature,
            base_srs_json=base_srs_json,
            existing_domain_improvements_json=existing_domain_improvements_json,
            retrieved_chunks=retrieved_chunks,
            revision_comment=revision_comment,
            revised_by=revised_by,
        )

        raw_output = await provider.invoke_agent([
            {"role": "system", "content": DOMAIN_REVISION_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ])

        plan, fallback_used, fallback_reason = await self._resolve_enrichment_plan(
            provider, raw_output, base_srs_json, retrieved_chunks, bool(revision_comment), "revision"
        )

        enhanced_srs_json, domain_improvements_json, _applied_ops, _unmatched_ops = self._apply_operations_and_merge(
            base_srs_json, plan, retrieved_chunks
        )

        enhanced_srs_json["revision_metadata"] = {
            "revision_type": "domain_enrichment_revision",
            "revision_comment": revision_comment,
            "revised_by": revised_by,
            "fallback_used": fallback_used,
            **({"fallback_reason": fallback_reason} if fallback_used and fallback_reason else {}),
        }

        if fallback_used:
            domain_improvements_json["no_changes_note"] = (
                f"Revision requested ('{revision_comment}') could not be automatically applied: "
                f"{fallback_reason}. Existing enrichment was preserved unchanged."
            )

        self._finalize_enhanced_srs_metadata(
            enhanced_srs_json, srs_version, retrieved_chunks, fallback_used, fallback_reason
        )

        enhanced_srs_markdown = self.markdown_builder.build(enhanced_srs_json, domain_improvements_json)

        return DomainAgentOutput(
            enhanced_srs_markdown=enhanced_srs_markdown,
            enhanced_srs_json=enhanced_srs_json,
            domain_improvements_json=domain_improvements_json,
        )

    def _apply_operations_and_merge(
        self, base_srs_json: dict, plan: dict, retrieved_chunks: list[dict]
    ) -> tuple[dict, dict, list[str], list[str]]:
        """
        Applies any direct remove/modify/set "operations" from the plan to base_srs_json FIRST
        (see apply_revision_operations, imported from Requirement Agent -- this module's own
        docstring explains the deliberate reuse), THEN merges the plan's additions/modifications
        onto the operation-patched result -- so a modification targeting an id an operation just
        touched still resolves against the current, post-edit state, not a stale copy.

        Real, reported gap this exists for: Domain Agent's enrichment-plan schema
        (additions/modifications) can only ADD or enrich-describe existing items -- there was no
        way to express "remove this" or "replace this outright," so a human asking Domain Agent
        to remove or edit something already in the Enhanced SRS was silently ignored, and a new
        version was generated with nothing actually changed. Only ever called from revise() /
        revise_stream() -- run()/run_stream() have no existing enhanced document yet to edit, and
        their prompt never mentions "operations" at all.

        Returns (enhanced_srs_json, domain_improvements_json, applied_operations,
        unmatched_operations) -- the last two are human-readable notes, same contract as
        apply_revision_operations' own return shape.
        """

        operations = plan.get("operations", [])
        operated_srs_json, applied_operations, unmatched_operations = apply_revision_operations(
            base_srs_json, operations
        )

        enhanced_srs_json, domain_improvements_json = self._apply_enrichment_plan(
            operated_srs_json, plan, retrieved_chunks
        )

        if applied_operations or unmatched_operations:
            domain_improvements_json["applied_edits"] = applied_operations
            domain_improvements_json["unmatched_edits"] = unmatched_operations

            # Same convention Requirement Agent's own revision_patcher caller uses: an edit that
            # couldn't be confidently matched is surfaced directly in the document, not just
            # logged, so a human reviewer sees explicitly when a requested change did NOT happen.
            assumptions = enhanced_srs_json.get("assumptions", [])
            if not isinstance(assumptions, list):
                assumptions = []
            for note in unmatched_operations:
                assumptions.append(f"Requested edit could not be applied -- {note}")
            enhanced_srs_json["assumptions"] = assumptions

        return enhanced_srs_json, domain_improvements_json, applied_operations, unmatched_operations

    def _find_latest_approved_srs_artifact(self, feature_id: str) -> dict | None:
        """
        Find the SRS JSON artifact that should feed this run -- a human-pinned APPROVED version
        if one was explicitly selected (see artifact_service.set_active_artifact_selection /
        the frontend's per-version radio button on approved SRS rows), otherwise the latest
        APPROVED version by version number (this method's original, still-default behavior).

        Delegates to artifact_service.get_selected_or_latest_approved_artifact -- previously this
        was a private, enum-and-.value tolerant duplicate of the same "latest approved" lookup
        Architecture/UI-UX/Coder Agent each have their own copy of; the selection-aware behavior
        now lives once, centrally, so this is the only one of those duplicates that's pin-aware.
        """

        return artifact_service.get_selected_or_latest_approved_artifact(
            feature_id, ArtifactType.SRS.value, ArtifactFormat.JSON.value
        )

    def _find_latest_domain_json_artifact(self, feature_id: str, artifact_type: ArtifactType) -> dict | None:
        """
        Find the latest Domain Agent JSON artifact of the given type for this feature,
        regardless of approval status -- revision must build on the latest generated
        version even if it is still pending or was rejected.
        """

        matching_artifacts = []

        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue

            if artifact.get("agent_name") not in [AgentName.DOMAIN, AgentName.DOMAIN.value]:
                continue

            if artifact.get("artifact_type") not in [artifact_type, artifact_type.value]:
                continue

            if artifact.get("artifact_format") not in [ArtifactFormat.JSON, ArtifactFormat.JSON.value]:
                continue

            matching_artifacts.append(artifact)

        if not matching_artifacts:
            return None

        return max(matching_artifacts, key=lambda item: item.get("version", 1))

    def _save_domain_artifacts(self, project: dict, feature: dict, output: DomainAgentOutput) -> list[str]:
        """
        Save Enhanced SRS Markdown, Enhanced SRS JSON, and Domain Improvements JSON under one
        shared version number.
        """

        version = artifact_service.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=AgentName.DOMAIN,
            artifact_type=ArtifactType.ENHANCED_SRS,
        )

        feature_slug = self._feature_slug(feature)

        markdown_artifact = artifact_service.save_text_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.DOMAIN,
            artifact_type=ArtifactType.ENHANCED_SRS,
            artifact_format=ArtifactFormat.MARKDOWN,
            filename=f"{feature_slug}_enhanced_srs_v{version}.md",
            content=output.enhanced_srs_markdown,
            version_override=version,
        )

        json_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.DOMAIN,
            artifact_type=ArtifactType.ENHANCED_SRS,
            filename=f"{feature_slug}_enhanced_srs_v{version}.json",
            data=output.enhanced_srs_json,
            version_override=version,
        )

        improvements_artifact = artifact_service.save_json_artifact(
            project=project,
            feature=feature,
            agent_name=AgentName.DOMAIN,
            artifact_type=ArtifactType.DOMAIN_IMPROVEMENTS,
            filename=f"{feature_slug}_domain_improvements_v{version}.json",
            data=output.domain_improvements_json,
            version_override=version,
        )

        return [
            markdown_artifact.artifact_id,
            json_artifact.artifact_id,
            improvements_artifact.artifact_id,
        ]

    def _feature_slug(self, feature: dict) -> str:
        feature_name = feature.get("feature_name", "feature")

        feature_slug = feature_name.lower().strip()
        feature_slug = re.sub(r"[^a-z0-9]+", "_", feature_slug)
        feature_slug = feature_slug.strip("_")

        return feature_slug or "feature"


domain_agent = DomainAgent()
