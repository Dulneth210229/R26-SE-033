"""
Requirement Agent conversation schemas.

A conversation is the human-in-the-loop gap-filling exchange that happens BEFORE a real SRS
artifact is generated -- distinct from the existing RequirementBAInput/RequirementAgentRunRequest
(a single, fully-formed submission) and RequirementAgentReviseRequest (a follow-up change to an
already-generated SRS).

State lives in one Mongo document per feature_id (store.requirement_conversations), upserted in
place each turn -- not versioned like artifacts, since a turn is not a reviewable output on its
own. See conversation_engine.py / conversation_quality_gate.py for the logic that builds and
checks this state.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class QuestionWithPlaceholder(BaseModel):
    """
    One clarifying question, paired with a concrete example answer (placeholder_example) shown
    in the reply input -- turns "type a free-text answer from scratch" into "adapt this realistic
    example," which is the whole point of asking per-question instead of a single combined block.
    """

    question: str
    placeholder_example: str = ""


def _coerce_questions(value):
    """
    Accept either the current {"question", "placeholder_example"} shape or a plain string (the
    shape used before this field carried placeholders) -- lets already-persisted conversation
    documents from before this change keep working without a migration script.
    """
    if not isinstance(value, list):
        return value

    coerced = []
    for item in value:
        if isinstance(item, str):
            coerced.append({"question": item, "placeholder_example": ""})
        else:
            coerced.append(item)
    return coerced


class ConversationTurn(BaseModel):
    """
    One exchange in the conversation: the questions the agent asked, and the human's reply to
    the previous batch (None for the very first turn, which has no prior questions to reply to).
    """

    turn_index: int
    questions_asked: list[QuestionWithPlaceholder] = Field(default_factory=list)
    human_reply: str | None = None
    assumptions_flagged_this_turn: list[str] = Field(default_factory=list)
    # The agent's short, dynamically-generated natural-language response to human_reply -- e.g.
    # pointing out when a reply was irrelevant or didn't answer the question, instead of the
    # agent silently moving on with its next questions as if the reply had been useful.
    agent_reaction: str | None = None
    created_at: datetime

    # The known_answers snapshot as it existed right BEFORE this turn's human_reply was merged
    # in -- i.e. exactly what run_gap_analysis was given as its `known_answers` argument to
    # produce this turn. Stored (not derived) so a later "edit this reply" action can rewind to
    # this exact state and regenerate, mirroring ChatGPT/Claude's edit-and-regenerate flow. Not
    # exposed to the frontend as anything actionable on its own -- purely a replay anchor.
    known_answers_before: dict = Field(default_factory=dict)

    _coerce_questions_asked = field_validator("questions_asked", mode="before")(_coerce_questions)


class QualityGateResult(BaseModel):
    """
    Result of conversation_quality_gate.assess() -- a deterministic, non-LLM check of whether
    the current srs_preview is concrete enough to confirm. `ready=False` does not block a human
    from confirming anyway (see RequirementConversationConfirmRequest.override_quality_gate) --
    it only means the reasons must be surfaced and explicitly overridden, not silently ignored.
    """

    ready: bool
    reasons: list[str] = Field(default_factory=list)
    auto_assumed_tier1_count: int = 0


class RequirementConversationState(BaseModel):
    """
    Full conversation state for one feature. Returned by start/reply/get -- the frontend renders
    its entire chat view from this one object, no separate artifact-content fetches needed.
    """

    feature_id: str
    known_answers: dict = Field(default_factory=dict)
    srs_preview: dict = Field(default_factory=dict)
    open_questions: list[QuestionWithPlaceholder] = Field(default_factory=list)
    assumptions_flagged: list[str] = Field(default_factory=list)
    turn_history: list[ConversationTurn] = Field(default_factory=list)
    status: Literal["gathering", "ready_to_confirm", "confirmed"] = "gathering"
    quality_gate: QualityGateResult | None = None
    updated_at: datetime

    _coerce_open_questions = field_validator("open_questions", mode="before")(_coerce_questions)


class RequirementConversationReplyRequest(BaseModel):
    """
    Request body for replying to the current batch of open_questions. Free text -- the human
    does not need to answer every question individually; the gap-analysis LLM call extracts
    whatever it can from the reply as a whole.
    """

    reply: str = Field(
        ...,
        example="Admins can create, edit, and delete catalog items. Each item has a name, "
        "description, price, and stock quantity. Use POST/GET/PUT/DELETE /api/items.",
    )


class RequirementConversationConfirmRequest(BaseModel):
    """
    Request body for the final confirmation step. override_quality_gate must be explicitly true
    (with a reason) to confirm despite the quality gate reporting ready=False -- this is a
    deliberate human decision, not a default, and the override is recorded in the generated
    SRS's own assumptions array so it stays visible to anyone reviewing it later.
    """

    override_quality_gate: bool = False
    override_reason: str | None = Field(
        default=None,
        example="Feature is intentionally minimal; remaining gaps don't apply.",
    )
    confirmed_by: str = "human_user"
