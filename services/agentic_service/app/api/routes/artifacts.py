"""
Artifact routes.

These APIs allow users or frontend to:
- list artifacts for a feature
- view artifact metadata
- read an artifact's actual file content (text/JSON/image)
"""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response

from app.api.deps import get_current_user
from app.agents.architecture_agent.pdf_builder import build_architecture_plan_html
from app.agents.domain_agent.pdf_builder import build_enhanced_srs_html
from app.agents.requirement_agent.pdf_builder import build_srs_html
from app.agents.security_agent.pdf_builder import build_security_report_html
from app.agents.qa_agent.pdf_builder import build_qa_report_html
from app.core.enums import ArtifactFormat, ArtifactType
from app.schemas.artifact_schema import ArtifactResponse, SkippedFindingUpdateRequest
from app.services import pdf_service
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store

_DOWNLOAD_MEDIA_TYPES = {
    ArtifactFormat.PNG: "image/png",
    ArtifactFormat.JSON: "application/json",
    ArtifactFormat.MARKDOWN: "text/markdown",
    ArtifactFormat.HTML: "text/html",
}

# The document types this PDF-export route supports, each mapped to the HTML template builder
# that mirrors its own frontend document viewer.
_PDF_BUILDERS = {
    ArtifactType.SRS: build_srs_html,
    ArtifactType.ENHANCED_SRS: build_enhanced_srs_html,
    ArtifactType.ARCHITECTURE_PLAN: build_architecture_plan_html,
    ArtifactType.SECURITY_REPORT: build_security_report_html,
    ArtifactType.QA_REPORT: build_qa_report_html,
}

router = APIRouter(tags=["Artifacts"])


def _check_feature_owned(feature_id: str, current_user: dict) -> None:
    """
    Verify the signed-in user owns feature_id's parent project -- mirrors features.py's
    _get_owned_project/_get_owned_feature reasoning exactly (404 either way; an ownerless
    pre-migration project is accessible to any signed-in user). Only raises; callers that
    already fetched the artifact/feature reuse that object themselves.
    """
    feature = store.features.get(feature_id)

    if not feature:
        raise HTTPException(status_code=404, detail="Artifact not found")

    project = store.projects.get(feature["project_id"])
    owner_id = project.get("user_id") if project else None

    if not project or (owner_id is not None and owner_id != current_user["user_id"]):
        raise HTTPException(status_code=404, detail="Artifact not found")


def _get_owned_artifact(artifact_id: str, current_user: dict):
    artifact = artifact_service.get_artifact(artifact_id)

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    _check_feature_owned(artifact.feature_id, current_user)

    return artifact


@router.get("/features/{feature_id}/artifacts", response_model=list[ArtifactResponse])
def list_feature_artifacts(feature_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return all artifacts generated for a feature -- only if it belongs to the signed-in user.
    """
    _check_feature_owned(feature_id, current_user)

    return artifact_service.list_feature_artifacts(feature_id)


@router.get("/artifacts/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(artifact_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return artifact metadata by artifact ID -- only if it belongs to the signed-in user.
    """
    return _get_owned_artifact(artifact_id, current_user)


@router.put("/artifacts/{artifact_id}/skipped-findings", response_model=ArtifactResponse)
def update_skipped_finding(
    artifact_id: str, request: SkippedFindingUpdateRequest, current_user: dict = Depends(get_current_user)
):
    """
    Mark (or unmark) one security finding as skipped -- a human choosing to accept the risk and
    proceed without fixing it. Does not touch the artifact's content_json (see
    artifact_service.set_finding_skipped's own docstring); only its side-channel
    skipped_finding_ids metadata field. Only if the artifact belongs to the signed-in user.
    """
    _get_owned_artifact(artifact_id, current_user)

    artifact = artifact_service.set_finding_skipped(
        artifact_id=artifact_id, finding_id=request.finding_id, skipped=request.skipped
    )

    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return artifact


@router.delete("/artifacts/{artifact_id}", status_code=204)
def delete_artifact(artifact_id: str, current_user: dict = Depends(get_current_user)):
    """
    Permanently delete one unapproved artifact version (e.g. a rejected/pending SRS revision a
    human wants to clear out of the version list). Refuses (400) to delete an approved artifact.
    Only if the artifact belongs to the signed-in user.
    """
    _get_owned_artifact(artifact_id, current_user)

    try:
        artifact_service.delete_artifact(artifact_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return Response(status_code=204)


@router.get("/artifacts/{artifact_id}/content")
def get_artifact_content(artifact_id: str, current_user: dict = Depends(get_current_user)):
    """
    Return an artifact's actual file content -- not just metadata. Only if it belongs to the
    signed-in user.

    PNG artifacts are served as raw binary (image/png) so the frontend can use
    the URL directly in an <img src>. Everything else (markdown/json/text/code)
    is returned as a JSON body with the raw text always present, plus a
    best-effort parsed content_json when the format is "json" (never raises on
    a parse failure -- content_json is simply null in that case).
    """
    artifact = _get_owned_artifact(artifact_id, current_user)

    # Real, live-found bug: read_artifact_content/read_artifact_binary raise a raw
    # FileNotFoundError when the referenced file is missing on disk (e.g. a shared Mongo Atlas
    # record whose local outputs/ file was never present in, or was removed from, this checkout --
    # confirmed for a real project this way). Left uncaught, this propagates as an unhandled 500
    # -- which the browser reports as a bare "Network Error" with no message at all (an unhandled
    # exception here skips FastAPI's normal exception-handling pipeline, which is also what
    # normally re-applies CORSMiddleware's headers to the response; without them the browser
    # can't even read the 500, so axios reports connection failure, not "500"). A real,
    # graceful HTTPException goes through that pipeline correctly and reaches the frontend as an
    # honest, readable error instead.
    try:
        if artifact.artifact_format == ArtifactFormat.PNG:
            return Response(content=artifact_service.read_artifact_binary(artifact_id), media_type="image/png")

        text = artifact_service.read_artifact_content(artifact_id)
    except (FileNotFoundError, OSError):
        raise HTTPException(
            status_code=404,
            detail=(
                f"This artifact's file could not be found on disk (path: {artifact.file_path}). "
                "It may have been deleted, moved, or never synced to this environment."
            ),
        )

    content_type = "json" if artifact.artifact_format == ArtifactFormat.JSON else "text"
    content_json = None

    if content_type == "json":
        try:
            content_json = json.loads(text)
        except ValueError:
            content_json = None

    return {
        "artifact_id": artifact_id,
        "artifact_format": artifact.artifact_format,
        "content_type": content_type,
        "content": text,
        "content_json": content_json,
    }


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str, current_user: dict = Depends(get_current_user)):
    """
    Download an artifact's raw file, exactly as generated -- sibling of /content (which wraps
    the same bytes in a JSON envelope for in-app viewing). This one sets Content-Disposition so
    a browser saves it as a real file instead of rendering/parsing it. Only if it belongs to
    the signed-in user.
    """
    artifact = _get_owned_artifact(artifact_id, current_user)

    filename = Path(artifact.file_path).name
    media_type = _DOWNLOAD_MEDIA_TYPES.get(artifact.artifact_format, "text/plain")

    # Same missing-file gotcha as /content above -- same graceful-404 fix.
    try:
        if artifact.artifact_format == ArtifactFormat.PNG:
            body = artifact_service.read_artifact_binary(artifact_id)
        else:
            body = artifact_service.read_artifact_content(artifact_id).encode("utf-8")
    except (FileNotFoundError, OSError):
        raise HTTPException(
            status_code=404,
            detail=(
                f"This artifact's file could not be found on disk (path: {artifact.file_path}). "
                "It may have been deleted, moved, or never synced to this environment."
            ),
        )

    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/artifacts/{artifact_id}/download-pdf")
def download_artifact_pdf(artifact_id: str, current_user: dict = Depends(get_current_user)):
    """
    Download an artifact as a real, formatted PDF instead of its raw JSON file --
    a sibling of /download, scoped to the document-shaped artifact types
    registered in _PDF_BUILDERS (SRS, Enhanced SRS, Architecture Plan, Security
    Report, QA Report) that each have a dedicated pdf_builder HTML template.
    Every other artifact type's /download behavior is unchanged. Only if the artifact belongs
    to the signed-in user.
    """
    artifact = _get_owned_artifact(artifact_id, current_user)

    builder = _PDF_BUILDERS.get(artifact.artifact_type)
    if builder is None:
        supported = ", ".join(sorted(t.value for t in _PDF_BUILDERS))
        raise HTTPException(
            status_code=400,
            detail=(
                f"PDF export is not available for artifact_type='{artifact.artifact_type}'. "
                f"Only {supported} support PDF export."
            ),
        )

    try:
        raw_text = artifact_service.read_artifact_content(artifact_id)
    except (FileNotFoundError, OSError):
        raise HTTPException(
            status_code=404,
            detail=(
                f"This artifact's file could not be found on disk (path: {artifact.file_path}). "
                "It may have been deleted, moved, or never synced to this environment."
            ),
        )

    try:
        content_json = json.loads(raw_text)
    except ValueError:
        raise HTTPException(status_code=400, detail="This artifact's content is not valid JSON.")

    if artifact.artifact_type == ArtifactType.ENHANCED_SRS:
        domain_improvements_json = _find_domain_improvements_json(artifact.feature_id, artifact.version)
        html = builder(content_json, domain_improvements_json)
    else:
        html = builder(content_json)

    pdf_bytes = pdf_service.render_html_to_pdf(html)

    document_name = f"{artifact.artifact_type.value}_v{artifact.version}.pdf"

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{document_name}"'},
    )


def _find_domain_improvements_json(feature_id: str, version: int) -> dict | None:
    """
    Load the Domain Improvements artifact saved alongside an Enhanced SRS at the
    same version (the same sibling lookup the frontend already does), so the
    Enhanced SRS PDF can render a "Domain Improvements" section -- returns None
    if no such sibling exists or its content can't be read/parsed.
    """
    siblings = artifact_service.list_feature_artifacts(feature_id)
    for sibling in siblings:
        if sibling.artifact_type == ArtifactType.DOMAIN_IMPROVEMENTS and sibling.version == version:
            try:
                return json.loads(artifact_service.read_artifact_content(sibling.artifact_id))
            except (FileNotFoundError, OSError, ValueError):
                return None
    return None