"""
Approval routes.

These routes support Human-in-the-Loop approval.

The frontend will call these APIs when the user:
- approves an artifact
- rejects an artifact
- requests revision
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.schemas.approval_schema import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalRevokeRequest,
    ApprovalRevokeResponse,
)
from app.services.approval_service import approval_service
from app.services.in_memory_store import store

router = APIRouter(prefix="/artifacts", tags=["Approvals"])


def _check_artifact_owned(artifact_id: str, current_user: dict) -> None:
    """
    Verify the signed-in user owns the project this artifact's feature belongs to -- mirrors
    artifacts.py's own _check_feature_owned reasoning exactly (404 either way; an ownerless
    pre-migration project is accessible to any signed-in user).
    """
    artifact = store.artifacts.get(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    feature = store.features.get(artifact["feature_id"])
    if not feature:
        raise HTTPException(status_code=404, detail="Artifact not found")

    project = store.projects.get(feature["project_id"])
    owner_id = project.get("user_id") if project else None

    if not project or (owner_id is not None and owner_id != current_user["user_id"]):
        raise HTTPException(status_code=404, detail="Artifact not found")


@router.post("/{artifact_id}/approval", response_model=ApprovalResponse)
def submit_artifact_approval(
    artifact_id: str, request: ApprovalRequest, current_user: dict = Depends(get_current_user)
):
    """
    Submit approval decision for an artifact -- only if it belongs to the signed-in user.

    request.status can be:
    - approved
    - rejected
    - revision_requested
    """
    _check_artifact_owned(artifact_id, current_user)

    approval = approval_service.submit_approval(
        artifact_id=artifact_id,
        request=request
    )

    if not approval:
        raise HTTPException(status_code=400, detail="Approval failed")

    return approval


@router.post("/{artifact_id}/approval/revoke", response_model=ApprovalRevokeResponse)
def revoke_artifact_approval(
    artifact_id: str,
    request: ApprovalRevokeRequest = ApprovalRevokeRequest(),
    current_user: dict = Depends(get_current_user),
):
    """
    Revoke an already-approved artifact's approval, moving it (and its version-sibling group)
    back to pending. For a Coder Agent code_diff artifact, also attempts to reverse the real git
    merge that approving it already ran -- see approval_service.revoke_approval's own docstring.
    Only if the artifact belongs to the signed-in user.
    """
    _check_artifact_owned(artifact_id, current_user)

    try:
        return approval_service.revoke_approval(
            artifact_id=artifact_id,
            revoked_by=request.revoked_by,
            reviewer_comment=request.reviewer_comment,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))