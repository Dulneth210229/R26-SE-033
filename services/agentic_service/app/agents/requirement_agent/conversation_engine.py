"""
Requirement Agent conversation engine.

Core, mostly-LLM-optional logic behind the conversational gap-filling loop (see
RequirementAgent.start_conversation / reply_to_conversation / confirm_conversation in agent.py):

- extract_json_object / project_ba_input_to_srs_shape: pure, no-LLM building blocks also reused
  by agent.py's existing JSON-parsing and fallback-SRS-generation paths -- see their own
  docstrings for exactly which behavior moved here and why.
- run_gap_analysis: the one LLM call this loop makes per turn -- deliberately small and separate
  from the full SRS-generation call in agent.py, since "what's still missing, ask at most 3
  questions about it" is a much cheaper, more reliable task than generating a full SRS, and this
  loop may run many times per conversation while the real SRS is only ever generated once (at
  confirm time).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.requirement_agent.prompt import (
    GAP_ANALYSIS_SYSTEM_PROMPT,
    build_gap_analysis_user_prompt,
)
from app.core.enums import AgentName
from app.services.llm_provider_service import llm_provider_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_QUESTIONS_PER_TURN = 3

# Fields the Architecture Agent depends on most heavily for a correct plan (confirmed by reading
# app/agents/architecture_agent/agent.py directly, and by a real, documented failure in this
# project's CLAUDE.md: a vague data_requirements pair produced a genuinely broken Architecture
# Plan -- single-field pseudo-entities instead of one coherent entity). Kept here (not just in the
# prompt) so conversation_quality_gate.py can weigh these the same way without re-deriving the
# list.
#
# api_expectations/ui_expectations are deliberately NOT Tier 1, per direct user feedback: forcing
# a human to spell out exact endpoints/UI details is unnecessary friction the LLM can resolve on
# its own by inferring REST-conventional endpoints and reasonable UI expectations from
# functional_requirements/data_requirements (see REQUIREMENT_AGENT_SYSTEM_PROMPT's matching rule).
# They stay fully optional, not removed: if the human volunteers concrete endpoints/UI details in
# a reply, run_gap_analysis still extracts and keeps them like any other known_answers field.
TIER_1_FIELDS = ["functional_requirements", "data_requirements"]
TIER_2_FIELDS = [
    "business_goal",
    "user_roles",
    "non_functional_requirements",
    "acceptance_criteria",
    "out_of_scope",
]
TIER_3_FIELDS = ["target_stack", "architectural_style", "constraints", "ui_expectations", "api_expectations"]


def extract_json_object(text: str) -> dict:
    """
    Extract a JSON object from LLM output that may have markdown fences or leading/trailing
    prose around it. Shared, generic primitive -- RequirementAgent._extract_json_object (used by
    the existing SRS-generation parse ladder) delegates to this exact function; its behavior is
    unchanged by moving it here.
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

    return json.loads(cleaned[start:end + 1])


def _make_requirement_items(
    prefix: str, items: list[str], extra_key: str | None = None, extra_value: str | None = None
) -> list[dict[str, Any]]:
    """
    Convert simple strings into requirement objects with stable IDs. Moved here from
    RequirementAgent so project_ba_input_to_srs_shape can use it without an agent instance;
    RequirementAgent._make_requirement_items delegates to this, behavior unchanged.
    """
    result = []
    for index, item in enumerate(items, start=1):
        record = {"id": f"{prefix}-{index:03d}", "description": item}
        if prefix == "FR":
            record["priority"] = "Must Have"
        if extra_key and extra_value:
            record[extra_key] = extra_value
        result.append(record)
    return result


def _make_user_stories(ba_input: dict) -> list[dict[str, str]]:
    """Moved here from RequirementAgent for the same reason as _make_requirement_items."""
    roles = ba_input.get("user_roles", []) or ["User"]
    feature_name = ba_input.get("feature_name", "feature")
    return [
        {
            "id": f"US-{index:03d}",
            "role": role,
            "goal": f"use the {feature_name} feature",
            "benefit": "complete the intended business process",
        }
        for index, role in enumerate(roles, start=1)
    ]


def _build_traceability(functional_requirements: list[dict]) -> list[dict]:
    """
    One traceability row per functional requirement -- correct regardless of how many FRs exist.
    The original inline fallback hardcoded a single FR-001 entry, which was only ever right by
    coincidence when exactly one FR was present; this projection now runs every conversational
    turn, often with several real FRs by the time gaps are filled in, so getting this right
    matters more than it did as a rare LLM-failure-only path.
    """
    if not functional_requirements:
        return []
    return [
        {
            "requirement_id": fr["id"],
            "related_acceptance_criteria": [],
            "notes": "Generated by deterministic SRS projection -- refine once acceptance criteria are finalized.",
        }
        for fr in functional_requirements
    ]


def project_ba_input_to_srs_shape(project: dict, feature: dict, ba_input: dict) -> tuple[dict, list[str]]:
    """
    Deterministically project a (possibly partial) ba_input dict into the full SRS JSON shape,
    with no LLM call. Returns (srs_json, defaulted_fields) -- defaulted_fields names every field
    that was filled with a generic default rather than real supplied content, so callers can
    honestly flag every one instead of silently baking it in (the original inline version silently
    defaulted output_requirements/validation_rules with no flag at all -- fixed here).

    Shared core behind:
    - RequirementAgent._build_fallback_srs_json (LLM-generation-failure recovery -- wraps this
      with its own failure-reason assumption line; unchanged behavior for that path).
    - The conversational gap-filling loop's live SRS preview, called every turn with no failure
      involved at all -- must never claim one, which is why the failure-reason line lives only in
      the wrapper, not here.
    """
    defaulted_fields: list[str] = []

    def default_if_missing(key: str, default_value):
        value = ba_input.get(key)
        if value:
            return value
        defaulted_fields.append(key)
        return default_value

    functional_requirements = _make_requirement_items(
        prefix="FR", items=ba_input.get("functional_requirements", [])
    )
    non_functional_requirements = _make_requirement_items(
        prefix="NFR",
        items=ba_input.get("non_functional_requirements", []),
        extra_key="category",
        extra_value="General",
    )
    acceptance_criteria = _make_requirement_items(
        prefix="AC", items=ba_input.get("acceptance_criteria", [])
    )
    if not acceptance_criteria:
        acceptance_criteria = [
            {
                "id": "AC-001",
                "description": "The feature must satisfy the approved functional requirements.",
            }
        ]
        defaulted_fields.append("acceptance_criteria")

    if not ba_input.get("functional_requirements"):
        defaulted_fields.append("functional_requirements")
    if not ba_input.get("api_expectations"):
        defaulted_fields.append("api_expectations")
    if not ba_input.get("data_requirements"):
        defaulted_fields.append("data_requirements")
    if not ba_input.get("user_roles"):
        defaulted_fields.append("user_roles")
    if not ba_input.get("non_functional_requirements"):
        defaulted_fields.append("non_functional_requirements")

    business_goal = default_if_missing(
        "business_goal",
        f"Deliver the {feature['feature_name']} feature for the {project['project_type']} application.",
    )
    scope = default_if_missing("scope", [f"Implement the {feature['feature_name']} feature only."])
    out_of_scope = default_if_missing(
        "out_of_scope", ["Unrelated features are not included in this iteration."]
    )
    target_stack = default_if_missing("target_stack", project["target_stack"])
    architectural_style = default_if_missing("architectural_style", "modular")
    output_requirements = default_if_missing(
        "output_requirements", ["The system should return a clear success or failure response."]
    )

    validation_rules_raw = ba_input.get("validation_rules")
    if validation_rules_raw:
        validation_rules = validation_rules_raw
    else:
        validation_rules = [
            {"id": "VR-001", "description": "Input values must be validated before processing."}
        ]
        defaulted_fields.append("validation_rules")

    srs_json = {
        "project_id": project["project_id"],
        "project_name": project["project_name"],
        "project_type": project["project_type"],
        "feature_id": feature["feature_id"],
        "feature_name": feature["feature_name"],
        "target_stack": target_stack,
        "architectural_style": architectural_style,
        "business_goal": business_goal,
        "scope": scope,
        "out_of_scope": out_of_scope,
        "user_roles": ba_input.get("user_roles", []),
        "functional_requirements": functional_requirements,
        "non_functional_requirements": non_functional_requirements,
        "user_stories": _make_user_stories(ba_input),
        "acceptance_criteria": acceptance_criteria,
        "input_requirements": ba_input.get("data_requirements", []),
        "output_requirements": output_requirements,
        "ui_expectations": ba_input.get("ui_expectations", []),
        "api_expectations": ba_input.get("api_expectations", []),
        "data_requirements": ba_input.get("data_requirements", []),
        "validation_rules": validation_rules,
        "constraints": ba_input.get("constraints", []),
        "assumptions": list(ba_input.get("assumptions", [])),
        "risks": [],
        "dependencies": [],
        "traceability": _build_traceability(functional_requirements),
    }

    return srs_json, defaulted_fields


# Fields ensure_srs_completeness backstops -- every one of these was confirmed (by reading
# REQUIREMENT_AGENT_SYSTEM_PROMPT and project_ba_input_to_srs_shape directly) to have NO
# "must not be empty" guarantee on at least one of the two real generation paths (the real LLM
# call, or the deterministic fallback) before this fix. scope/out_of_scope/output_requirements/
# validation_rules/acceptance_criteria/functional_requirements/non_functional_requirements are
# deliberately excluded -- already reliably populated by both paths today.
_COMPLETENESS_BACKSTOP_FIELDS = {
    "user_stories", "user_roles", "constraints", "api_expectations", "ui_expectations",
    "input_requirements", "risks", "dependencies",
}


def ensure_srs_completeness(srs_json: dict) -> tuple[dict, list[str]]:
    """
    Final, deterministic, no-LLM guarantee that no SRS section is left genuinely empty -- runs on
    ANY fully-shaped srs_json regardless of how it was produced (validated real LLM output,
    JSON-repaired output, or project_ba_input_to_srs_shape's own fallback projection). Confirmed
    real, reported bug this closes: REQUIREMENT_AGENT_SYSTEM_PROMPT has no "must not be empty"
    instruction for user_stories (or several other fields) at all, so the real LLM path could --
    and did -- produce "user_stories": [] with nothing catching it before this fix.

    Returns (srs_json, notes) -- srs_json is mutated in place AND returned for convenience; notes
    is a list of human-readable strings the caller should append to srs_json["assumptions"] so a
    backstopped field is never silently presented as if it were genuinely known -- matching this
    project's own established honesty convention (see project_ba_input_to_srs_shape's own
    defaulted_fields/assumptions handling).

    Deliberately grounds every backstop in content that's ALREADY reliably present by this point
    (target_stack/architectural_style/data_requirements/user_stories) rather than fabricating
    specifics -- and never claims an empty risks/dependencies list as a genuine "no risks found"
    conclusion, only "not evaluated."
    """
    notes: list[str] = []

    user_stories = srs_json.get("user_stories")
    if not isinstance(user_stories, list) or not user_stories:
        srs_json["user_stories"] = _make_user_stories(
            {"user_roles": srs_json.get("user_roles") or [], "feature_name": srs_json.get("feature_name", "feature")}
        )
        notes.append("user_stories was empty -- generated a default entry per user role.")

    user_roles = srs_json.get("user_roles")
    if not isinstance(user_roles, list) or not user_roles:
        inferred_roles = sorted({
            story.get("role") for story in srs_json.get("user_stories", [])
            if isinstance(story, dict) and story.get("role")
        })
        srs_json["user_roles"] = inferred_roles or ["User"]
        notes.append("user_roles was empty -- inferred from user_stories (or defaulted to 'User').")

    constraints = srs_json.get("constraints")
    if not isinstance(constraints, list) or not constraints:
        target_stack = srs_json.get("target_stack") or "the specified stack"
        architectural_style = srs_json.get("architectural_style") or "the specified architecture"
        srs_json["constraints"] = [
            f"Must be implemented using {target_stack}.",
            f"Must follow a {architectural_style} architectural style.",
        ]
        notes.append("constraints was empty -- derived from target_stack/architectural_style.")

    for field, description in (("api_expectations", "API endpoints"), ("ui_expectations", "UI elements")):
        value = srs_json.get(field)
        if not isinstance(value, list) or not value:
            srs_json[field] = [
                f"{description} inferred from functional/data requirements -- exact details to be "
                "finalized during Architecture/UI-UX Agent review."
            ]
            notes.append(f"{field} was empty -- a placeholder inference note was added.")

    input_requirements = srs_json.get("input_requirements")
    if not isinstance(input_requirements, list) or not input_requirements:
        data_requirements = srs_json.get("data_requirements") or []
        if data_requirements:
            srs_json["input_requirements"] = list(data_requirements)
            notes.append("input_requirements was empty -- copied from data_requirements.")
        else:
            srs_json["input_requirements"] = [
                "No additional input requirements beyond what's captured in functional requirements."
            ]
            notes.append("input_requirements was empty -- no data_requirements to derive from either.")

    for field, placeholder in (
        ("risks", "No feature-specific risks were identified during generation -- this has not "
                  "been reviewed for risk, not confirmed risk-free."),
        ("dependencies", "No external dependencies were identified during generation -- this has "
                          "not been reviewed for dependencies, not confirmed to have none."),
    ):
        value = srs_json.get(field)
        if not isinstance(value, list) or not value:
            srs_json[field] = [placeholder]
            notes.append(f"{field} was empty -- an honest 'not evaluated' placeholder was added, not a claim of none.")

    return srs_json, notes


class GapAnalysisResult:
    """
    Plain result container for run_gap_analysis -- not a Pydantic model since this is internal to
    the requirement_agent package, not an API response shape (RequirementConversationState in
    requirement_conversation_schema.py is the API-facing shape agent.py builds from this).
    """

    def __init__(
        self,
        known_answers: dict,
        questions: list[dict],
        assumptions: list[str],
        reaction: str | None = None,
    ):
        self.known_answers = known_answers
        self.questions = questions[:MAX_QUESTIONS_PER_TURN]
        self.assumptions = assumptions
        # A short, natural-language response to the human's latest reply -- see
        # GAP_ANALYSIS_SYSTEM_PROMPT for the full instruction. This is what makes an irrelevant or
        # nonsensical reply get a real, dynamically-generated reaction ("that doesn't seem to
        # answer X -- could you clarify?") instead of the agent silently moving on to its next
        # batch of questions as if nothing was wrong.
        self.reaction = reaction


def _question(text: str, placeholder_example: str) -> dict:
    """Build one structured question -- {question, placeholder_example} -- the placeholder is a
    concrete example answer shown in the reply input, so answering is a matter of adapting a
    realistic example rather than writing free text from a blank box."""
    return {"question": text, "placeholder_example": placeholder_example}


def _deterministic_gap_checklist(known_answers: dict) -> GapAnalysisResult:
    """
    Rule-based fallback used only when the gap-analysis LLM call fails entirely (parse failure on
    both the raw and repaired output) -- mirrors this codebase's established reliability-ladder
    convention (a fallback that never itself calls the LLM again). Checks Tier 1 fields first,
    then Tier 2, capped at MAX_QUESTIONS_PER_TURN.
    """
    questions = []

    if not known_answers.get("functional_requirements"):
        questions.append(
            _question(
                "What specific actions can a user perform with this feature?",
                "Admin can create, edit, and delete an item",
            )
        )
    if not known_answers.get("data_requirements"):
        questions.append(
            _question(
                "What data fields does this feature's main entity have?",
                "name, description, price, stock quantity",
            )
        )

    if len(questions) < MAX_QUESTIONS_PER_TURN and not known_answers.get("user_roles"):
        questions.append(_question("Which user role(s) can use this feature?", "Admin"))
    if len(questions) < MAX_QUESTIONS_PER_TURN and not known_answers.get("non_functional_requirements"):
        questions.append(
            _question(
                "Any performance, security, or usability requirements worth noting?",
                "Should complete within 2 seconds; only authenticated admins can access it",
            )
        )

    reaction = (
        "Let's get started -- here's what I need to know first:"
        if not known_answers.get("functional_requirements") and not known_answers.get("data_requirements")
        else "Thanks -- here's what I still need to know:"
    )

    return GapAnalysisResult(known_answers=known_answers, questions=questions, assumptions=[], reaction=reaction)


def parse_gap_analysis_response(raw_output: str, known_answers: dict) -> GapAnalysisResult:
    """
    Parse one already-fetched raw LLM response into a GapAnalysisResult -- shared by
    run_gap_analysis (which fetches raw_output itself via a plain invoke_agent call) and
    RequirementAgent.reply_to_conversation_stream (which accumulates raw_output token-by-token
    from provider.stream()), so both go through identical parsing/merging logic. Raises on parse
    failure -- callers decide how to react (repair attempt, deterministic fallback, etc.),
    matching this codebase's established reliability-ladder convention.
    """
    parsed = extract_json_object(raw_output)

    # Defensive: the prompt shows an empty-string/empty-list JSON shape as an example of the
    # known_answers structure, and the model sometimes echoes that placeholder shape back for
    # fields it has no real information for instead of omitting them (the same "model anchors on
    # shown JSON shape" gotcha seen elsewhere in this codebase's other agents) -- confirmed
    # directly: a real run returned "architectural_style": "" verbatim, which then failed
    # RequirementBAInput's validator at confirm time (empty string is not None, so it skips the
    # field's normal MODULAR default and hits the allowed-values check instead). Any falsy value
    # is treated as "no real answer" and never allowed to overwrite/introduce a value.
    new_known_answers = parsed.get("known_answers") or {}
    if not isinstance(new_known_answers, dict):
        new_known_answers = {}

    updated_known_answers = dict(known_answers)
    updated_known_answers.update({key: value for key, value in new_known_answers.items() if value})

    raw_questions = parsed.get("questions") or []
    assumptions = parsed.get("assumptions") or []
    reaction = parsed.get("reaction")

    if not isinstance(raw_questions, list):
        raw_questions = []
    if not isinstance(assumptions, list):
        assumptions = []
    if not isinstance(reaction, str) or not reaction.strip():
        reaction = None

    # Each question is expected as {"question": ..., "placeholder_example": ...}, but tolerate a
    # plain string too (a model that ignores the structured shape, or a legacy caller) by wrapping
    # it with an empty placeholder rather than dropping the question outright.
    questions: list[dict] = []
    for item in raw_questions:
        if isinstance(item, dict) and item.get("question"):
            questions.append(
                {
                    "question": str(item["question"]),
                    "placeholder_example": str(item.get("placeholder_example") or ""),
                }
            )
        elif isinstance(item, str) and item.strip():
            questions.append({"question": item, "placeholder_example": ""})

    return GapAnalysisResult(
        known_answers=updated_known_answers,
        questions=questions,
        assumptions=[str(a) for a in assumptions],
        reaction=reaction.strip() if reaction else None,
    )


async def run_gap_analysis(
    project: dict, feature: dict, known_answers: dict, latest_reply: str | None
) -> GapAnalysisResult:
    """
    One small LLM call: given known_answers so far and the human's latest reply (None on the very
    first turn), extract whatever new information the reply provides into known_answers, and
    return at most MAX_QUESTIONS_PER_TURN prioritized clarifying questions for the highest-impact
    remaining gaps (see TIER_1/2/3_FIELDS + GAP_ANALYSIS_SYSTEM_PROMPT for the exact priority
    rules). On total JSON-parse failure (raw + one repair attempt), falls back to
    _deterministic_gap_checklist -- no second LLM call, matching this codebase's established
    reliability-ladder idiom (see RequirementAgent._generate_requirement_output for the same shape
    applied to full SRS generation).
    """
    provider = llm_provider_service.get_provider(agent_name=AgentName.REQUIREMENT.value)

    prompt = build_gap_analysis_user_prompt(
        project=project, feature=feature, known_answers=known_answers, latest_reply=latest_reply
    )

    try:
        raw_output = await provider.invoke_agent(
            [
                {"role": "system", "content": GAP_ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )
    except Exception as call_error:
        # Unlike the parse-failure fallback below, this call was never wrapped at all -- any LLM
        # server issue (unreachable, connection refused, timeout) crashed "Start Conversation"
        # outright with a raw, unfriendly exception message instead of degrading gracefully like
        # every other failure mode here does. Route it into the exact same deterministic
        # checklist the parse-failure ladder already falls back to, so the conversation always
        # starts even when the LLM can't be reached at all.
        logger.warning(
            "Gap analysis LLM call failed (e.g. LLM server unreachable): %s -- using deterministic checklist.",
            call_error,
        )
        return _deterministic_gap_checklist(known_answers)

    try:
        return parse_gap_analysis_response(raw_output, known_answers)
    except Exception as first_error:
        logger.warning("Gap analysis JSON parse failed: %s", first_error)

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
            return parse_gap_analysis_response(repaired, known_answers)
        except Exception as second_error:
            logger.warning(
                "Gap analysis JSON repair also failed: %s -- using deterministic checklist.",
                second_error,
            )
            return _deterministic_gap_checklist(known_answers)
