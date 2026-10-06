"""
Security Agent API schema.

No revise-request shape here, unlike every other agent's schema file -- the Security Agent has
no "revise" concept of its own: re-running IS the whole operation, and what the human calls a
"revision" happens on the Coder Agent side (see coder_schema.py's CoderAgentReviseRequest,
already unconstrained free text with no changes needed to carry a security report's findings).
"""

from pydantic import BaseModel, Field


class SecurityAgentRunRequest(BaseModel):
    """
    Request body for running the Security Agent -- mirrors every other agent's run-request
    shape (a single optional human_comment, recorded via stage_event_service for the activity
    log) even though the agent itself doesn't consume it yet.
    """

    human_comment: str | None = Field(
        default=None,
        example="Re-scan after the Coder Agent's latest revision.",
    )


class SecurityChatMessageRequest(BaseModel):
    """One human chat turn -- see agents.py's /security/chat/stream route. Mirrors
    QAChatMessageRequest exactly."""

    message: str = Field(..., example="Why is the MongoDB credential finding marked Critical?")


class SecurityChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str
    created_at: str
    # Stable, 1-based identifier shared by a user turn and its assistant reply -- direct user
    # request: lets the frontend address "edit this exchange" by a real id rather than array
    # position (which shifts once edits start truncating history). None for a turn saved before
    # this field existed (old conversations keep working, just can't be edited retroactively).
    turn_index: int | None = None


class SecurityChatHistoryResponse(BaseModel):
    turns: list[SecurityChatTurn] = Field(default_factory=list)
