"""
Live preview routes.

Explicit Start/Stop/Status for a feature's Coder Agent-generated Next.js app,
mirroring agents.py's existing per-feature route scoping style.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.services.in_memory_store import store
from app.services.preview_service import (
    PreviewConflictError,
    PreviewNotBuiltError,
    PreviewUnsupportedStackError,
    preview_service,
)

router = APIRouter(tags=["Preview"])


def _require_feature(feature_id: str, current_user: dict) -> None:
    """
    Verify the signed-in user owns feature_id's parent project -- see features.py's
    _get_owned_feature for the identical, full reasoning (ownerless pre-migration data stays
    accessible to any signed-in user).
    """
    feature = store.features.get(feature_id)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    project = store.projects.get(feature["project_id"])
    owner_id = project.get("user_id") if project else None

    if not project or (owner_id is not None and owner_id != current_user["user_id"]):
        raise HTTPException(status_code=404, detail="Feature not found")


@router.post("/features/{feature_id}/preview/start")
def start_preview(feature_id: str, current_user: dict = Depends(get_current_user)):
    _require_feature(feature_id, current_user)

    try:
        return preview_service.start_preview(feature_id)
    except PreviewUnsupportedStackError as error:
        raise HTTPException(status_code=400, detail={"reason": "unsupported_stack", "message": str(error)})
    except PreviewNotBuiltError as error:
        raise HTTPException(status_code=409, detail={"reason": "not_built", "message": str(error)})
    except PreviewConflictError as error:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": "conflict",
                "message": str(error),
                "conflicting_feature_id": error.conflicting_feature_id,
                "conflicting_feature_name": error.conflicting_feature_name,
            },
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.get("/features/{feature_id}/preview/status")
def get_preview_status(feature_id: str, current_user: dict = Depends(get_current_user)):
    _require_feature(feature_id, current_user)

    return preview_service.get_status(feature_id)


@router.post("/features/{feature_id}/preview/stop")
def stop_preview(feature_id: str, current_user: dict = Depends(get_current_user)):
    _require_feature(feature_id, current_user)

    preview_service.stop_preview(feature_id)

    return {"status": "stopped"}
