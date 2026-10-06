"""
Feature routes.

A feature is one SDLC unit.

Example:
- Login
- Signup
- Product Listing

When a feature is created, the artifact folder structure is also created.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import ValidationError

from app.api.deps import get_current_user
from app.core.enums import FeatureStatus, AgentName, ArtifactFormat, ArtifactType
from app.schemas.approval_schema import ApprovalResponse
from app.schemas.feature_schema import FeatureCreateRequest, FeatureResponse, SetActiveArtifactSelectionRequest
from app.schemas.stage_event_schema import StageEventResponse
from app.services.approval_service import approval_service
from app.services.artifact_service import artifact_service
from app.services.graph_orchestrator_service import graph_orchestrator_service
from app.services.in_memory_store import store
from app.services.stage_event_service import stage_event_service
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id
from app.utils.logger import get_logger
from app.utils.slugify import slugify

logger = get_logger(__name__)

router = APIRouter(tags=["Features"])


def _get_owned_project(project_id: str, current_user: dict):
    """
    Look up a project and verify the signed-in user owns it -- see projects.py's identical
    helper for why this is a 404, not a 403, and why an ownerless (pre-migration legacy)
    project is treated as accessible rather than locked out.
    """
    project = store.projects.get(project_id)
    owner_id = project.get("user_id") if project else None

    if not project or (owner_id is not None and owner_id != current_user["user_id"]):
        raise HTTPException(status_code=404, detail="Project not found")

    return project


def _get_owned_feature(feature_id: str, current_user: dict):
    """
    Look up a feature and verify the signed-in user owns its PARENT PROJECT (features have no
    owner field of their own -- ownership is always inherited from the project).
    """
    feature = store.features.get(feature_id)

    if not feature:
        raise HTTPException(status_code=404, detail="Feature not found")

    _get_owned_project(feature["project_id"], current_user)

    return feature


@router.post("/projects/{project_id}/features", response_model=FeatureResponse)
def create_feature(project_id: str, request: FeatureCreateRequest, current_user: dict = Depends(get_current_user)):
    """
    Create a feature inside a project.

    This also creates the required artifact folders.
    """
    project = _get_owned_project(project_id, current_user)

    now = datetime.utcnow()
    feature_id = generate_id("feature")

    feature = {
        "feature_id": feature_id,
        "project_id": project_id,
        "feature_name": request.feature_name,
        "feature_description": request.feature_description,
        "feature_status": FeatureStatus.CREATED,
        "current_agent": AgentName.REQUIREMENT,
        "created_at": now,
        "updated_at": now,
    }

    store.features[feature_id] = feature

    # Create artifact folder structure immediately.
    artifact_service.create_feature_artifact_root(
        project_name=project["project_name"],
        feature_name=feature["feature_name"]
    )

    return FeatureResponse(**feature)


@router.get("/projects/{project_id}/features", response_model=list[FeatureResponse])
def list_project_features(project_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return all features for a project -- only if it belongs to the signed-in user.

    Skips (and logs a warning for) any individual record that fails to validate -- a
    malformed/legacy feature document should not break this list for every other, valid
    feature in the same project.
    """
    _get_owned_project(project_id, current_user)

    results = []

    for feature in store.features.values():
        if feature["project_id"] != project_id:
            continue

        try:
            results.append(FeatureResponse(**feature))
        except ValidationError as error:
            logger.warning("Skipping unparseable feature %s: %s", feature.get("feature_id"), error)

    return results


@router.get("/features/{feature_id}", response_model=FeatureResponse)
def get_feature(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return one feature by ID -- only if it belongs to the signed-in user.
    """
    feature = _get_owned_feature(feature_id, current_user)

    return FeatureResponse(**feature)


@router.put("/features/{feature_id}/artifacts/active-selection", response_model=FeatureResponse)
def set_active_artifact_selection(
    feature_id: str, request: SetActiveArtifactSelectionRequest, current_user: dict = Depends(get_current_user)
):
    """
    Pin which APPROVED version of one artifact_type should feed the next pipeline stage for this
    feature -- e.g. which approved SRS version the Domain Agent reads, when more than one SRS
    version has been approved and the latest one isn't the one a human wants to proceed with.
    Only an approved artifact of the given type can be selected (400 otherwise).
    """
    _get_owned_feature(feature_id, current_user)

    try:
        artifact_service.set_active_artifact_selection(
            feature_id=feature_id,
            artifact_type=request.artifact_type,
            artifact_id=request.artifact_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return FeatureResponse(**store.features.get(feature_id))


@router.delete("/features/{feature_id}", status_code=204)
def delete_feature(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Permanently delete one feature (only if it belongs to the signed-in user): its artifacts,
    approvals, stage events, and requirement conversation record. Scoped to this feature only --
    unlike delete_project, never touches the project's knowledge documents or the whole workspace
    repo (other features in the same project may still need those). Best-effort discards this
    feature's own git branch, but ONLY if the project's workspace repo already exists on disk
    with a real branch for this feature -- never creates a workspace as a side effect of deleting
    a feature that never advanced far enough to have one (ensure_project_repo, which
    discard_feature_branch calls internally, would otherwise do exactly that).
    """
    feature = _get_owned_feature(feature_id, current_user)

    project_id = feature["project_id"]
    artifact_ids = [a["artifact_id"] for a in store.artifacts.values() if a.get("feature_id") == feature_id]

    store.artifacts.collection.delete_many({"feature_id": feature_id})
    store.approvals.collection.delete_many(
        {"$or": [{"feature_id": feature_id}, {"artifact_id": {"$in": artifact_ids}}]}
    )
    store.stage_events.collection.delete_many({"feature_id": feature_id})
    store.requirement_conversations.collection.delete_one({"feature_id": feature_id})
    store.qa_conversations.collection.delete_one({"feature_id": feature_id})
    store.security_conversations.collection.delete_one({"feature_id": feature_id})

    repo_path = workspace_service.get_repo_path(project_id)
    if (repo_path / ".git").exists():
        try:
            workspace_service.discard_feature_branch(project_id, feature_id)
        except Exception as error:
            logger.warning("Failed to discard git branch for deleted feature_id=%s: %s", feature_id, error)

    store.features.collection.delete_one({"feature_id": feature_id})


@router.post("/features/{feature_id}/start")
def start_feature_pipeline(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Start this feature's LangGraph pipeline run -- only if it belongs to the signed-in user.

    This kicks off the graph for the first time; every step after that is
    driven by approval decisions hitting POST /artifacts/{artifact_id}/approval,
    which resume the same paused run (see graph_orchestrator_service).
    """
    feature = _get_owned_feature(feature_id, current_user)

    graph_orchestrator_service.start(
        project_id=feature["project_id"],
        feature_id=feature_id,
    )

    return graph_orchestrator_service.get_status(feature_id)


@router.get("/features/{feature_id}/graph-status")
def get_feature_graph_status(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return this feature's current LangGraph pipeline state: {"next": [...], "values": {...}}.
    Only if the feature belongs to the signed-in user.

    Previously this shape was only ever returned once, inline, as POST /start's response
    body -- this route exposes the same, already-existing graph_orchestrator_service.get_status
    lookup so the frontend can poll it at any time (e.g. to detect Domain/UI-UX/Coder Agent
    auto-completing after a prior stage's approval). Before /start has ever been called for a
    feature, this returns an idle snapshot ("next": [] and empty "values") -- not an error.
    """
    feature = _get_owned_feature(feature_id, current_user)

    return graph_orchestrator_service.get_status(feature_id)


@router.get("/features/{feature_id}/approvals", response_model=list[ApprovalResponse])
def list_feature_approvals(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return every approval decision recorded for this feature, oldest first -- only if it
    belongs to the signed-in user.

    Powers the frontend's per-stage activity timeline -- a real record of every
    approve/reject/revision-request decision and its reviewer_comment, not previously
    retrievable at all (only POST /artifacts/{id}/approval existed before this).
    """
    _get_owned_feature(feature_id, current_user)

    return approval_service.list_feature_approvals(feature_id)


@router.get("/features/{feature_id}/events", response_model=list[StageEventResponse])
def list_feature_events(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return every recorded run()/revise() request for this feature, oldest first -- the "ask"
    half of the frontend's per-stage activity timeline (paired with each artifact's own
    created_at as the "agent responded" half, and /approvals as the "reviewer decision" half).
    Only if the feature belongs to the signed-in user.
    """
    _get_owned_feature(feature_id, current_user)

    return stage_event_service.list_feature_events(feature_id)


@router.get("/features/{feature_id}/code/download")
def download_feature_code(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Download this feature's actual generated code as a zip -- the real project the Coder Agent
    built, not its documentation artifacts (code_plan/code_diff/etc, already downloadable
    individually via GET /artifacts/{id}/download). Zips the feature's own branch if it still
    exists (so a reviewer can try the code locally before approving), otherwise `main` (the
    branch is deleted once merged). Only if the feature belongs to the signed-in user.
    """
    feature = _get_owned_feature(feature_id, current_user)

    try:
        content = workspace_service.export_feature_code_zip(feature["project_id"], feature_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    filename = f"{slugify(feature['feature_name'])}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/features/{feature_id}/code-with-qa-report/download")
def download_feature_code_with_qa_report(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Same real generated code as download_feature_code, bundled together with the feature's
    latest QA report (JSON + Markdown, under a _QA_REPORT/ prefix so it never collides with real
    generated app files) in one zip. Only if the feature belongs to the signed-in user.
    """
    feature = _get_owned_feature(feature_id, current_user)

    extra_files: list[tuple[str, bytes]] = []
    for artifact_format, arcname in (
        (ArtifactFormat.JSON, "_QA_REPORT/qa_report.json"),
        (ArtifactFormat.MARKDOWN, "_QA_REPORT/qa_report.md"),
    ):
        qa_artifact = artifact_service.get_selected_or_latest_approved_artifact(
            feature_id, ArtifactType.QA_REPORT, artifact_format
        )
        if not qa_artifact:
            continue
        try:
            with open(qa_artifact["file_path"], "rb") as file:
                extra_files.append((arcname, file.read()))
        except (FileNotFoundError, OSError):
            continue

    try:
        content = workspace_service.export_feature_code_with_extra_files_zip(
            feature["project_id"], feature_id, extra_files
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    filename = f"{slugify(feature['feature_name'])}-with-qa-report.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/features/{feature_id}/uiux-images/{version}/download")
def download_uiux_images(feature_id: str, version: int, current_user: dict = Depends(get_current_user)):
    """
    Download every UI/UX preview screenshot generated for ONE version of this feature, bundled
    together as a single zip -- direct user request: "download all the generated images at once
    per version." Only if the feature belongs to the signed-in user.
    """
    feature = _get_owned_feature(feature_id, current_user)

    artifacts = artifact_service.list_feature_artifacts(feature_id)
    screenshot_ids = [
        artifact.artifact_id
        for artifact in artifacts
        if artifact.artifact_type == ArtifactType.UI_PREVIEW_SCREENSHOT and artifact.version == version
    ]

    if not screenshot_ids:
        raise HTTPException(status_code=404, detail=f"No UI/UX preview images found for version {version}.")

    content = artifact_service.export_artifacts_zip(screenshot_ids)

    filename = f"{slugify(feature['feature_name'])}-uiux-images-v{version}.zip"
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )