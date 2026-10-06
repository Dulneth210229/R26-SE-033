"""
Stage event schemas.

A stage event records one human-initiated run()/revise() request -- the "ask" half of the
frontend's per-stage activity timeline (see approval_schema.py's ApprovalResponse for the
"reviewer decision" half; an artifact's own created_at is the "agent responded" half).
"""

from datetime import datetime
from pydantic import BaseModel
from app.core.enums import AgentName


class StageEventResponse(BaseModel):
    """
    API response for one recorded run()/revise() request.
    """

    event_id: str
    feature_id: str
    agent_name: AgentName
    event_type: str  # "run" | "revise"
    human_comment: str | None
    requested_by: str
    requested_at: datetime
