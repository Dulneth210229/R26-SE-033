"""
Project routes.

A project is the main application being developed.

Example:
- E-commerce Platform
- LMS Platform

Each project can have many features.
"""

import os
import shutil
import stat
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response
from git import Repo
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.core.config import settings
from app.schemas.project_schema import ProjectCreateRequest, ProjectResponse, ProjectUpdateRequest
from app.services.in_memory_store import store
from app.services.knowledge_document_service import knowledge_document_service
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id
from app.utils.logger import get_logger
from app.utils.slugify import slugify

logger = get_logger(__name__)


def _remove_readonly(func, path, _exc_info):
    """
    shutil.rmtree onerror handler: git marks its object files read-only on Windows, which makes
    a plain rmtree fail with PermissionError. Clear the read-only bit and retry once -- same
    fix already established for this exact problem in this project's own test suite.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)

router = APIRouter(prefix="/projects", tags=["Projects"])


def _normalize_project_document(project: dict) -> dict:
    """
    Fill sensible defaults for any field ProjectResponse requires but a real, pre-existing
    project document is missing. A real, confirmed gap found live: many projects in the shared
    database were never fully populated (missing project_type/target_stack/created_by/
    created_at/updated_at), and list_projects' own pre-existing validation-skip behavior was
    silently hiding every one of them -- 42 of 45 real migrated projects, in one observed case.
    Filling defaults here (instead of loosening ProjectResponse's own required fields) keeps the
    schema strict for anything created going forward while still surfacing legacy data instead
    of silently dropping it.
    """
    now = datetime.utcnow()
    return {
        "project_type": "General",
        "target_stack": "Next.js",
        "created_by": "human_user",
        "created_at": now,
        "updated_at": now,
        **project,
    }


def _get_owned_project(project_id: str, current_user: dict):
    """
    Look up a project and verify the signed-in user owns it -- 404 (not 403) when it doesn't
    belong to them, so a user can't distinguish "doesn't exist" from "exists but isn't mine" by
    probing IDs.

    A project with no user_id at all (pre-migration legacy data -- see
    scripts/migrate_existing_projects_to_user.py) is treated as accessible to any signed-in
    user rather than locked out entirely, so existing projects don't vanish for everyone the
    moment auth ships and before that script has run. This never grants access to a project
    that DOES have a real owner who isn't the caller.
    """
    project = store.projects.get(project_id)
    owner_id = project.get("user_id") if project else None

    if not project or (owner_id is not None and owner_id != current_user["user_id"]):
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@router.post("", response_model=ProjectResponse)
def create_project(request: ProjectCreateRequest, current_user: dict = Depends(get_current_user)):
    """
    Create a new project, owned by the signed-in user.

    This is the first step before creating features.
    """
    now = datetime.utcnow()
    project_id = generate_id("proj")

    project = {
        "project_id": project_id,
        "project_name": request.project_name,
        "project_type": request.project_type,
        "target_stack": request.target_stack,
        "created_by": request.created_by,
        "user_id": current_user["user_id"],
        "created_at": now,
        "updated_at": now,
    }

    store.projects[project_id] = project

    return ProjectResponse(**project)


@router.get("", response_model=list[ProjectResponse])
def list_projects(current_user: dict = Depends(get_current_user)):
    """
    Return the signed-in user's own projects, plus any ownerless legacy project (see
    _get_owned_project's own docstring -- pre-migration data, not yet stamped with a real
    user_id) so nothing silently disappears before scripts/migrate_existing_projects_to_user.py
    has run.

    Skips (and logs a warning for) any individual record that fails to validate -- a
    malformed/legacy project document should not break this list for every other, valid
    project.
    """
    results = []

    query = {"$or": [{"user_id": current_user["user_id"]}, {"user_id": {"$exists": False}}, {"user_id": None}]}
    for project in store.projects.collection.find(query):
        try:
            results.append(ProjectResponse(**_normalize_project_document(project)))
        except ValidationError as error:
            logger.warning("Skipping unparseable project %s: %s", project.get("project_id"), error)

    return results


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return one project by ID -- only if it belongs to the signed-in user.
    """
    project = _get_owned_project(project_id, current_user)

    return ProjectResponse(**_normalize_project_document(project))


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(project_id: str, request: ProjectUpdateRequest, current_user: dict = Depends(get_current_user)):
    """
    Edit an existing project's details -- only if it belongs to the signed-in user. Only the
    fields provided are changed.
    """
    project = _get_owned_project(project_id, current_user)

    if request.project_name is not None:
        project["project_name"] = request.project_name

    if request.project_type is not None:
        project["project_type"] = request.project_type

    if request.target_stack is not None:
        project["target_stack"] = request.target_stack

    project["updated_at"] = datetime.utcnow()

    return ProjectResponse(**_normalize_project_document(project))


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    Permanently delete a project (only if it belongs to the signed-in user): its features,
    artifacts, approvals, stage events, requirement conversations, and knowledge documents
    (including their vector chunks and raw files), plus the on-disk workspace repo and outputs
    directory.

    On-disk cleanup is best-effort -- every Mongo record is removed regardless of whether the
    directory cleanup succeeds, since a UI-visible dangling/undeletable project is a worse
    failure than some leftover disk usage from a locked file.
    """
    project = _get_owned_project(project_id, current_user)

    # Compute the slug/repo path BEFORE any deletion -- workspace_service derives it by looking
    # the project back up in Mongo, which would fail once the project record itself is gone.
    project_slug = slugify(project.get("project_name") or project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    feature_ids = [f["feature_id"] for f in store.features.values() if f.get("project_id") == project_id]
    artifact_ids = [a["artifact_id"] for a in store.artifacts.values() if a.get("project_id") == project_id]

    store.artifacts.collection.delete_many({"project_id": project_id})
    store.approvals.collection.delete_many(
        {"$or": [{"feature_id": {"$in": feature_ids}}, {"artifact_id": {"$in": artifact_ids}}]}
    )
    store.stage_events.collection.delete_many({"feature_id": {"$in": feature_ids}})
    store.requirement_conversations.collection.delete_many({"feature_id": {"$in": feature_ids}})
    store.qa_conversations.collection.delete_many({"feature_id": {"$in": feature_ids}})
    store.security_conversations.collection.delete_many({"feature_id": {"$in": feature_ids}})

    for document in knowledge_document_service.list_documents(project_id):
        try:
            knowledge_document_service.delete_document(document["document_id"])
        except Exception as error:
            logger.warning("Failed to delete knowledge document %s: %s", document["document_id"], error)

    store.features.collection.delete_many({"project_id": project_id})
    store.projects.collection.delete_one({"project_id": project_id})

    if (repo_path / ".git").exists():
        try:
            Repo(repo_path).close()
        except Exception as error:
            logger.warning("Failed to close repo handle for project %s: %s", project_id, error)

    for root_setting in (settings.WORKSPACE_DIR, settings.OUTPUT_DIR):
        directory = Path(root_setting) / project_slug

        if not directory.exists():
            continue

        try:
            shutil.rmtree(directory, onerror=_remove_readonly)
        except Exception as error:
            logger.warning("Failed to remove %s for deleted project %s: %s", directory, project_id, error)


@router.get("/{project_id}/code/download")
def download_project_code(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    Download the project's cumulative generated app (main branch) as a zip -- every feature
    merged into main so far, combined. Only if the project belongs to the signed-in user.
    """
    project = _get_owned_project(project_id, current_user)

    try:
        content = workspace_service.export_zip(project_id, "main")
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    filename = f"{slugify(project['project_name'])}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )