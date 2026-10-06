"""
Domain Agent Enhancement Validator.

Purpose:
Validate the Domain Agent's PROPOSED enrichment plan (a small list of
additions/modifications, not a full SRS) before it is merged into the SRS by
deterministic Python code. Critically, this is where "Domain Agent is a RAG
system" becomes an enforced fact rather than a marketing claim: every
addition/modification must cite EITHER domain knowledge that was actually
retrieved (source_document must match a real retrieved chunk) OR the
human's own comment for this run (source_document == "human_provided",
only accepted when a human comment genuinely exists) -- never the model's
own general training. A real, reported gap fixed here: the original
RAG-only version of this rule silently discarded anything a human
explicitly typed (a database schema, a business rule) that wasn't already
sitting in the vector store, even though the chat UI itself invites exactly
that ("do you have something specific to add?").

Why plan-level (not merged-output-level) validation:
The final enhanced_srs_json/domain_improvements_json are built by
deterministic Python (_apply_enrichment_plan in agent.py) from a validated
plan, so their internal consistency (no dropped IDs, correct -DOM- numbering,
consistent original_description) is guaranteed by construction -- the LLM
never retypes the SRS or invents IDs, so those classes of error can no
longer happen. Validating the LLM's small proposed plan -- before merge --
is both cheaper and catches problems (bad target_section, a modification id
that doesn't exist, fabricated citations) at the one point they can actually
originate: the LLM.

This validator is feature-independent. It does not contain e-commerce,
LMS, or any other domain-specific logic.
"""

from __future__ import annotations

from typing import Any

SECTION_KEYS = [
    "functional_requirements",
    "non_functional_requirements",
    "acceptance_criteria",
    "validation_rules",
    "user_stories",
]

# data_requirements is a plain list[str] on the SRS (see requirement_schema.py's
# RequirementBAInput.data_requirements and domain_agent/markdown_builder.py's own rendering of
# it) -- unlike the five ID-tagged sections above, it has no per-item "id" to modify, so it is
# addition-only. Kept as its own constant (not merged into SECTION_KEYS) so _validate_modifications
# can explicitly reject it with a clear message instead of the generic "id does not exist" error
# a blind SECTION_KEYS membership check would produce.
DATA_REQUIREMENTS_SECTION = "data_requirements"

# Every OTHER plain list[str] section on the SRS a real domain fact can legitimately touch --
# real, reported gap: Domain Agent only ever proposed additions/modifications to the 5 ID-tagged
# sections + data_requirements, so in practice it converged on non_functional_requirements/
# acceptance_criteria almost every run (the two sections that read most naturally as "domain
# knowledge," e.g. a compliance NFR or an edge-case AC) while genuinely relevant domain facts
# about scope boundaries, constraints, risks, dependencies, or exact API/UI expectations were
# structurally impossible to add at all -- not a model preference, a hard schema restriction.
# This list matches DOMAIN_REVISION_SYSTEM_PROMPT's pre-existing "operations" field list exactly
# (see prompt.py) minus the 5 ID-tagged sections and data_requirements, which are handled
# separately -- revision's remove/modify "operations" could already reach every one of these
# fields; only the "additions" mechanism (used by both initial generation and revision) was
# missing them. Like data_requirements, addition-only: none of these have a per-item id.
PLAIN_LIST_SECTIONS = [
    "scope",
    "out_of_scope",
    "user_roles",
    "input_requirements",
    "output_requirements",
    "ui_expectations",
    "api_expectations",
    "constraints",
    "assumptions",
    "risks",
    "dependencies",
]

ADDITION_ONLY_SECTIONS = [DATA_REQUIREMENTS_SECTION] + PLAIN_LIST_SECTIONS

ADDITION_TARGET_SECTIONS = SECTION_KEYS + ADDITION_ONLY_SECTIONS

# A citation source the LLM may use when an addition/modification's content came DIRECTLY from
# the human's own comment (e.g. "here's our database schema: ...") rather than a retrieved
# knowledge-base chunk -- see this module's own docstring update below and prompt.py's matching
# instructions. Real, reported gap: Domain Agent was built as a strict RAG system ("every
# addition must cite a retrieved [KB-N] chunk, or be rejected"), which silently discarded
# anything the human explicitly typed (a schema, a business rule) that wasn't already sitting in
# the vector store -- the exact opposite of what the chat's own "do you have something specific
# to add?" prompt promises. Only accepted when `human_comment_provided` is true for this call
# (see validate_plan's new parameter) -- the LLM cannot fabricate this source when there was no
# real human comment to ground it in.
HUMAN_PROVIDED_SOURCE = "human_provided"


class DomainEnhancementValidationError(Exception):
    """
    Raised when a proposed enrichment plan is malformed, references a
    non-existent item, or makes an enrichment claim unsupported by
    retrieved domain knowledge.
    """


class DomainEnhancementValidator:
    """
    Validates one Domain Agent enrichment plan against the SRS (or, for a
    revision, the current enhanced SRS) it will be merged into, and the
    domain knowledge chunks that were retrieved for it.
    """

    def validate_plan(
        self,
        base_srs_json: dict[str, Any],
        plan: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        human_comment_provided: bool = False,
    ) -> None:
        """
        Raises DomainEnhancementValidationError if any check fails.

        `human_comment_provided` -- whether this call actually had a non-empty human comment --
        is what makes HUMAN_PROVIDED_SOURCE a legitimate citation source rather than an LLM-
        fabricated escape hatch from the "must cite a retrieved chunk" rule: a citation claiming
        "human_provided" is only accepted when there was a real human comment for it to have come
        from.
        """

        additions = plan.get("additions", [])
        modifications = plan.get("modifications", [])

        if not isinstance(additions, list) or not isinstance(modifications, list):
            raise DomainEnhancementValidationError(
                "Enrichment plan 'additions' and 'modifications' must both be lists."
            )

        errors: list[str] = []

        errors.extend(self._validate_additions(additions))
        errors.extend(self._validate_modifications(base_srs_json, modifications))
        errors.extend(
            self._validate_citation_integrity(additions, modifications, retrieved_chunks, human_comment_provided)
        )
        errors.extend(
            self._validate_honesty_with_empty_retrieval(additions, modifications, retrieved_chunks)
        )

        if errors:
            raise DomainEnhancementValidationError("; ".join(errors))

    def _validate_additions(self, additions: list[Any]) -> list[str]:
        errors = []

        for index, addition in enumerate(additions):
            if not isinstance(addition, dict):
                errors.append(f"additions[{index}] must be an object.")
                continue

            target_section = addition.get("target_section")

            if target_section not in ADDITION_TARGET_SECTIONS:
                errors.append(
                    f"additions[{index}] has invalid target_section '{target_section}'. "
                    f"Must be one of: {ADDITION_TARGET_SECTIONS}."
                )

            if not str(addition.get("description", "")).strip():
                errors.append(f"additions[{index}] is missing a non-empty description.")

        return errors

    def _validate_modifications(self, base_srs_json: dict[str, Any], modifications: list[Any]) -> list[str]:
        errors = []

        for index, modification in enumerate(modifications):
            if not isinstance(modification, dict):
                errors.append(f"modifications[{index}] must be an object.")
                continue

            target_section = modification.get("target_section")

            if target_section in ADDITION_ONLY_SECTIONS:
                errors.append(
                    f"modifications[{index}] targets '{target_section}', which has no per-item id "
                    f"to modify -- propose an addition instead."
                )
                continue

            if target_section not in SECTION_KEYS:
                errors.append(
                    f"modifications[{index}] has invalid target_section '{target_section}'. "
                    f"Must be one of: {SECTION_KEYS}."
                )
                continue

            item_id = modification.get("id")
            existing_ids = self._collect_ids(base_srs_json.get(target_section, []))

            if not item_id or item_id not in existing_ids:
                errors.append(
                    f"modifications[{index}] references id '{item_id}' which does not exist "
                    f"in {target_section}."
                )

            if not str(modification.get("enhanced_description", "")).strip():
                errors.append(f"modifications[{index}] is missing a non-empty enhanced_description.")

        return errors

    def _is_human_provided_citation(self, citation: dict[str, Any]) -> bool:
        return citation.get("source_document") == HUMAN_PROVIDED_SOURCE

    def _validate_citation_integrity(
        self,
        additions: list[Any],
        modifications: list[Any],
        retrieved_chunks: list[dict[str, Any]],
        human_comment_provided: bool,
    ) -> list[str]:
        errors = []
        retrieved_sources = {chunk.get("source_document") for chunk in retrieved_chunks}

        for kind, records in (("addition", additions), ("modification", modifications)):
            for index, record in enumerate(records):
                if not isinstance(record, dict):
                    continue

                citation = record.get("domain_citation") or {}
                source_document = citation.get("source_document")

                if not source_document:
                    errors.append(f"{kind}s[{index}] has no domain_citation.source_document.")
                elif source_document == HUMAN_PROVIDED_SOURCE:
                    if not human_comment_provided:
                        errors.append(
                            f"{kind}s[{index}] cites '{HUMAN_PROVIDED_SOURCE}' but no human "
                            f"comment was given for this run -- that source may only be used "
                            f"when a human comment actually exists to have come from."
                        )
                elif source_document not in retrieved_sources:
                    errors.append(
                        f"{kind}s[{index}] cites source document '{source_document}' which was "
                        f"not among the retrieved chunks."
                    )

        return errors

    def _validate_honesty_with_empty_retrieval(
        self,
        additions: list[Any],
        modifications: list[Any],
        retrieved_chunks: list[dict[str, Any]],
    ) -> list[str]:
        # The "no retrieval, no enrichment" honesty rule exists to stop the LLM from hallucinating
        # domain knowledge it was never actually given -- it was never meant to block content the
        # HUMAN explicitly typed, which needs no retrieval to be trustworthy. Only records citing
        # a real (non-human-provided) source count against this check.
        if retrieved_chunks:
            return []

        non_human_records = [
            record
            for record in (*additions, *modifications)
            if isinstance(record, dict) and not self._is_human_provided_citation(record.get("domain_citation") or {})
        ]

        if non_human_records:
            return [
                "No domain knowledge chunks were retrieved for this feature, but the plan "
                "proposes additions/modifications not sourced from the human's own comment. "
                "Enrichment must never be claimed without real retrieved domain knowledge or an "
                "explicit human-provided source behind it."
            ]

        return []

    def _collect_ids(self, items: list[Any]) -> list[str]:
        ids = []

        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))

        return ids

    def filter_valid_plan(
        self,
        base_srs_json: dict[str, Any],
        plan: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        human_comment_provided: bool = False,
    ) -> tuple[dict[str, Any], list[str]]:
        """
        Lenient counterpart to validate_plan, used by the real generation/revision flow in
        agent.py instead of the strict all-or-nothing version above. Keeps every addition/
        modification that independently passes every check; never raises -- an item that fails
        is simply DROPPED, with a human-readable reason, instead of discarding the entire plan.

        Real, observed failure mode this fixes: the LLM proposed one genuinely correct,
        human-requested addition (e.g. a database schema going into "data_requirements") ALONGSIDE
        one hallucinated modification referencing a made-up id -- validate_plan's all-or-nothing
        raise discarded BOTH, even though they have nothing to do with each other. One bad guess
        must never cost every other, independently valid part of the same response.

        validate_plan itself is unchanged (and still covered by its own tests) for any caller that
        genuinely wants strict all-or-nothing semantics.

        Returns (filtered_plan, dropped_reasons) -- filtered_plan has the same
        {summary, additions, modifications, no_changes_note} shape as the input, just with
        invalid items removed.
        """

        raw_additions = plan.get("additions", [])
        raw_modifications = plan.get("modifications", [])

        additions = raw_additions if isinstance(raw_additions, list) else []
        modifications = raw_modifications if isinstance(raw_modifications, list) else []

        retrieved_sources = {chunk.get("source_document") for chunk in retrieved_chunks}
        dropped: list[str] = []

        valid_additions = []
        for index, addition in enumerate(additions):
            errors = self._check_one_addition(
                addition, index, retrieved_chunks, retrieved_sources, human_comment_provided
            )
            if errors:
                dropped.extend(errors)
            else:
                valid_additions.append(addition)

        valid_modifications = []
        for index, modification in enumerate(modifications):
            errors = self._check_one_modification(
                base_srs_json, modification, index, retrieved_chunks, retrieved_sources, human_comment_provided
            )
            if errors:
                dropped.extend(errors)
            else:
                valid_modifications.append(modification)

        filtered_plan = {
            "summary": plan.get("summary"),
            "additions": valid_additions,
            "modifications": valid_modifications,
            "no_changes_note": plan.get("no_changes_note"),
        }

        return filtered_plan, dropped

    def _check_one_addition(
        self,
        addition: Any,
        index: int,
        retrieved_chunks: list[dict[str, Any]],
        retrieved_sources: set,
        human_comment_provided: bool,
    ) -> list[str]:
        if not isinstance(addition, dict):
            return [f"additions[{index}] must be an object."]

        errors = []
        target_section = addition.get("target_section")

        if target_section not in ADDITION_TARGET_SECTIONS:
            errors.append(
                f"additions[{index}] has invalid target_section '{target_section}'. "
                f"Must be one of: {ADDITION_TARGET_SECTIONS}."
            )

        if not str(addition.get("description", "")).strip():
            errors.append(f"additions[{index}] is missing a non-empty description.")

        errors.extend(self._check_one_citation("addition", addition, index, retrieved_sources, human_comment_provided))
        errors.extend(self._check_one_honesty(addition, retrieved_chunks, "addition", index))

        return errors

    def _check_one_modification(
        self,
        base_srs_json: dict[str, Any],
        modification: Any,
        index: int,
        retrieved_chunks: list[dict[str, Any]],
        retrieved_sources: set,
        human_comment_provided: bool,
    ) -> list[str]:
        if not isinstance(modification, dict):
            return [f"modifications[{index}] must be an object."]

        # A real, observed local-model failure mode: given TWO similarly-shaped mechanisms in the
        # same prompt (this enrichment "modifications" list, and the "operations" list for direct
        # edits -- see prompt.py's DOMAIN_REVISION_SYSTEM_PROMPT), the model sometimes reaches for
        # "modifications" but fills it in with the OTHER mechanism's key names ("field"/"target"/
        # "value" instead of "target_section"/"id"/"enhanced_description"). Accepting either key
        # name (mutating `modification` in place, same pattern as the citation auto-fill above)
        # recovers the human's requested change instead of discarding it over a naming mismatch.
        if not modification.get("target_section") and modification.get("field"):
            modification["target_section"] = modification["field"]
        if not modification.get("id") and modification.get("target"):
            modification["id"] = modification["target"]
        if not modification.get("enhanced_description") and modification.get("value"):
            modification["enhanced_description"] = modification["value"]

        target_section = modification.get("target_section")

        if target_section in ADDITION_ONLY_SECTIONS:
            return [
                f"modifications[{index}] targets '{target_section}', which has no per-item id to "
                f"modify -- propose an addition instead."
            ]

        if target_section not in SECTION_KEYS:
            return [
                f"modifications[{index}] has invalid target_section '{target_section}'. "
                f"Must be one of: {SECTION_KEYS}."
            ]

        errors = []
        item_id = modification.get("id")
        existing_ids = self._collect_ids(base_srs_json.get(target_section, []))

        if not item_id or item_id not in existing_ids:
            errors.append(
                f"modifications[{index}] references id '{item_id}' which does not exist in {target_section}."
            )

        if not str(modification.get("enhanced_description", "")).strip():
            errors.append(f"modifications[{index}] is missing a non-empty enhanced_description.")

        errors.extend(
            self._check_one_citation("modification", modification, index, retrieved_sources, human_comment_provided)
        )
        errors.extend(self._check_one_honesty(modification, retrieved_chunks, "modification", index))

        return errors

    def _check_one_citation(
        self,
        kind: str,
        record: dict[str, Any],
        index: int,
        retrieved_sources: set,
        human_comment_provided: bool,
    ) -> list[str]:
        citation = record.get("domain_citation") or {}
        source_document = citation.get("source_document")

        if not source_document:
            # A real, observed local-model failure mode: the LLM correctly proposes an otherwise-
            # valid, human-requested addition/modification but forgets to fill in domain_citation
            # entirely. When there genuinely IS a human comment for this call, that's far more
            # likely a forgotten field than an unsourced hallucination -- auto-attribute it to the
            # human comment (mutates `record` in place, which filter_valid_plan keeps the same
            # object reference for) rather than discard the human's requested change over a
            # bookkeeping omission. Only relevant here, the LENIENT per-item path -- the strict
            # validate_plan above is unchanged and still requires an explicit citation.
            if human_comment_provided:
                record["domain_citation"] = {"source_document": HUMAN_PROVIDED_SOURCE, "chunk_id": None}
                return []
            return [f"{kind}s[{index}] has no domain_citation.source_document."]

        if source_document == HUMAN_PROVIDED_SOURCE:
            if not human_comment_provided:
                return [
                    f"{kind}s[{index}] cites '{HUMAN_PROVIDED_SOURCE}' but no human comment was "
                    f"given for this run."
                ]
            return []

        if source_document not in retrieved_sources:
            return [
                f"{kind}s[{index}] cites source document '{source_document}' which was not among "
                f"the retrieved chunks."
            ]

        return []

    def _check_one_honesty(
        self, record: dict[str, Any], retrieved_chunks: list[dict[str, Any]], kind: str, index: int
    ) -> list[str]:
        if retrieved_chunks:
            return []

        if self._is_human_provided_citation(record.get("domain_citation") or {}):
            return []

        return [f"{kind}s[{index}] claims enrichment with no domain knowledge retrieved and no human-provided source."]
