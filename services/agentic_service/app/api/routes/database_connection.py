"""
Per-project database-connection (MongoDB URI) routes.

The standalone, agent-independent way to set/view/clear a project's real MongoDB connection
string -- mirrors knowledge.py's own /projects/{project_id}/knowledge/... shape and
_validate_project helper. The other entry point (typing/pasting a URI directly into the Coder
Agent chat) already existed before this route file -- see coder_agent/env_uri.py's own module
docstring -- and needed no changes; both paths write through the same
workspace_service.write_env_local, so either one is visible to the other immediately.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.agents.coder_agent.env_uri import MONGODB_URI_PATTERN, mask_mongodb_uri
from app.api.deps import get_current_user
from app.schemas.database_connection_schema import DatabaseConnectionResponse, DatabaseConnectionSaveRequest
from app.services.in_memory_store import store
from app.services.preview_service import preview_service
from app.services.workspace_service import workspace_service

router = APIRouter(prefix="/projects/{project_id}/database-connection", tags=["Database Connection"])


def _validate_project(project_id: str, current_user: dict):
    """
    Look up a project and verify the signed-in user owns it -- see projects.py's identical
    helper for why an ownerless (pre-migration legacy) project is treated as accessible rather
    than locked out.
    """
    project = store.projects.get(project_id)
    owner_id = project.get("user_id") if project else None

    if not project or (owner_id is not None and owner_id != current_user["user_id"]):
        raise HTTPException(status_code=404, detail="Project not found")

    return project


def _restart_any_running_preview(project_id: str) -> None:
    """
    A saved/cleared connection string only takes effect on a build/preview's NEXT start (see
    write_env_local's own docstring) -- if this project currently has a live preview running for
    ANY of its features, restart it so a human sees the change reflected immediately instead of
    silently continuing to serve the old value until they happen to stop/start it themselves.
    """
    running_feature_id = preview_service.find_running_feature_for_project(project_id)
    if running_feature_id:
        preview_service.restart_if_running(running_feature_id)


@router.get("", response_model=DatabaseConnectionResponse)
def get_database_connection(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    Whether this project has a MongoDB connection string configured, and a redacted display
    value if so -- the raw value is never returned over the API. Only if the project belongs
    to the signed-in user.
    """
    _validate_project(project_id, current_user)
    uri = workspace_service.read_env_local(project_id).get("MONGODB_URI")

    return DatabaseConnectionResponse(configured=bool(uri), masked_uri=mask_mongodb_uri(uri) if uri else None)


@router.put("", response_model=DatabaseConnectionResponse)
def save_database_connection(
    project_id: str, request: DatabaseConnectionSaveRequest, current_user: dict = Depends(get_current_user)
):
    """
    Save (or overwrite) this project's MongoDB connection string. Rejects a value that doesn't
    look like a real Mongo URI outright rather than silently writing something that would never
    actually connect. Only if the project belongs to the signed-in user.
    """
    _validate_project(project_id, current_user)
    uri = request.mongodb_uri.strip()

    if not MONGODB_URI_PATTERN.match(uri):
        raise HTTPException(
            status_code=400,
            detail="Not a valid MongoDB connection string -- it must start with mongodb:// or mongodb+srv://.",
        )

    workspace_service.write_env_local(project_id, {"MONGODB_URI": uri})
    _restart_any_running_preview(project_id)

    return DatabaseConnectionResponse(configured=True, masked_uri=mask_mongodb_uri(uri))


@router.delete("", status_code=204)
def delete_database_connection(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    Clear this project's saved MongoDB connection string -- every generated route's own guarded
    fallback (see this schema module's docstring) reverts to serving seed data on the next
    build/preview. Only if the project belongs to the signed-in user.
    """
    _validate_project(project_id, current_user)
    workspace_service.remove_env_local_keys(project_id, ["MONGODB_URI"])
    _restart_any_running_preview(project_id)
