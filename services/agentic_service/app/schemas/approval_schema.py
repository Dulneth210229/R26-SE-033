"""
Approval schemas.

Approval gates are mandatory after every agent.

The backend should never allow the next agent to run unless
the previous required artifact is approved.
"""

from datetime import datetime
from pydantic import BaseModel, Field
from app.core.enums import ApprovalStatus, AgentName


class ApprovalRequest(BaseModel):
    """
    Request body for approve, reject, or revision request.
    """
    status: ApprovalStatus = Field(..., example="approved")
    reviewer_comment: str | None = Field(
        default=None,
        example="Approved. Continue to the next agent."
    )
    approved_by: str = Field(default="human_user")


class ApprovalResponse(BaseModel):
    """
    API response after an approval action.
    """
    approval_id: str
    artifact_id: str
    # Optional + defaulted: approval records created before this field was added won't have it
    # in Mongo -- resolves to None for those rather than failing validation on an old record.
    feature_id: str | None = None
    agent_name: AgentName
    status: ApprovalStatus
    reviewer_comment: str | None
    approved_by: str
    approved_at: datetime


class ApprovalRevokeRequest(BaseModel):
    """
    Request body for revoking an already-approved artifact's approval back to pending -- entirely
    optional (an empty body is a valid revoke), unlike ApprovalRequest.
    """
    reviewer_comment: str | None = Field(
        default=None,
        example="Approval revoked to request changes.",
    )
    revoked_by: str = Field(default="human_user")


class ApprovalRevokeResponse(BaseModel):
    """
    API response after revoking an artifact's approval. `reverted_artifact_ids` is every artifact
    (this one plus any version-sibling/cascade it took along, e.g. an Architecture Plan's own
    Markdown pair and diagrams) that moved back to pending. `git_reverted`/`restored_branch` are
    only ever meaningful for a Coder Agent code_diff artifact whose approval had already run a
    real git merge -- see workspace_service.undo_merge_feature_branch.
    """
    artifact_id: str
    status: ApprovalStatus
    reverted_artifact_ids: list[str]
    git_reverted: bool
    restored_branch: str | None = None