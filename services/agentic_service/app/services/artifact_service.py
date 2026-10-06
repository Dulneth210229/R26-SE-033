"""
Artifact service.

This service is responsible for:
- Creating artifact folders
- Writing artifact files
- Creating artifact metadata
- Finding artifacts by feature
- Versioning artifact files

Agents should not directly manage files.
They should call this service.

Important:
A single agent run may create multiple artifact files with the same version.

Example:
Requirement Agent creates:
- SRS_v1.md
- SRS_v1.json

Both files should be version 1.
That is why save_text_artifact() and save_json_artifact()
support version_override.
"""

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.core.config import settings
from app.core.enums import ApprovalStatus, AgentName, ArtifactType, ArtifactFormat
from app.schemas.artifact_schema import ArtifactResponse
from app.services.in_memory_store import store
from app.utils.file_manager import ensure_directory, write_text_file, write_json_file
from app.utils.id_generator import generate_id
from app.utils.logger import get_logger
from app.utils.slugify import slugify

logger = get_logger(__name__)


class ArtifactService:
    """
    Handles all artifact-related operations.
    """

    STAGE_FOLDER_MAP = {
        AgentName.REQUIREMENT: "01_requirements",
        AgentName.DOMAIN: "02_domain",
        AgentName.ARCHITECTURE: "03_architecture",
        AgentName.UIUX: "04_uiux",
        AgentName.CODER: "05_code",
        AgentName.SECURITY: "06_security",
        AgentName.QA: "07_qa",
    }

    def create_feature_artifact_root(self,project_name: str,feature_name: str) -> Path:
        """
        Create the base artifact folders for a feature.

        Example:
            outputs/e-commerce-platform/feature-login/
        """
        project_slug = slugify(project_name)
        feature_slug = f"feature-{slugify(feature_name)}"

        root = Path(settings.OUTPUT_DIR) / project_slug / feature_slug

        for folder in self.STAGE_FOLDER_MAP.values():
            ensure_directory(root / folder)

        return root

    def get_stage_folder(self, project_name: str, feature_name: str, agent_name: AgentName ) -> Path:
        """
        Get the correct artifact folder for a specific agent.
        """
        root = self.create_feature_artifact_root(project_name, feature_name)
        return root / self.STAGE_FOLDER_MAP[agent_name]

    def get_next_version(self, feature_id: str, agent_name: AgentName, artifact_type: ArtifactType) -> int:
        """
        Find the next version number for a new artifact group.

        Example:
            If SRS_v1 already exists, next version will be 2.
        """
        existing_versions = [
            artifact["version"]
            for artifact in store.artifacts.values()
            if artifact["feature_id"] == feature_id
            and artifact["agent_name"] == agent_name
            and artifact["artifact_type"] == artifact_type
        ]

        if not existing_versions:
            return 1

        return max(existing_versions) + 1

    def save_text_artifact(self, project: dict[str, Any],
        feature: dict[str, Any],
        agent_name: AgentName,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat,
        filename: str,
        content: str,
        version_override: int | None = None,
        approval_status: ApprovalStatus = ApprovalStatus.PENDING,
    ) -> ArtifactResponse:
        """
        Save a text-based artifact and register metadata.

        version_override lets multiple files share the same version.

        Example:
            SRS_v1.md and SRS_v1.json should both be version 1.

        approval_status defaults to PENDING (every existing caller's behavior, unchanged) --
        an agent whose stage requires no human decision at all (e.g. UI/UX Agent) can pass
        APPROVED instead so the artifact is born already approved.
        """
        version = version_override or self.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=agent_name,
            artifact_type=artifact_type
        )

        stage_folder = self.get_stage_folder(
            project_name=project["project_name"],
            feature_name=feature["feature_name"],
            agent_name=agent_name
        )

        file_path = stage_folder / filename.replace("{version}", str(version))
        saved_path = write_text_file(file_path, content)

        return self._register_artifact(
            project_id=project["project_id"],
            feature_id=feature["feature_id"],
            agent_name=agent_name,
            artifact_type=artifact_type,
            artifact_format=artifact_format,
            file_path=saved_path,
            version=version,
            approval_status=approval_status,
        )

    def save_json_artifact(
        self,
        project: dict[str, Any],
        feature: dict[str, Any],
        agent_name: AgentName,
        artifact_type: ArtifactType,
        filename: str,
        data: dict[str, Any],
        version_override: int | None = None,
        summary: str | None = None,
        approval_status: ApprovalStatus = ApprovalStatus.PENDING,
    ) -> ArtifactResponse:
        """
        Save a JSON artifact and register metadata.

        version_override lets this JSON file share the same version
        as the related Markdown artifact.

        summary, when given, is a short human-readable description of this
        artifact's content (e.g. a CODE_PLAN's own "summary" field) --
        stored alongside the artifact record so the frontend chat can show
        real, model-generated text instead of a generic placeholder.

        approval_status defaults to PENDING (every existing caller's behavior, unchanged) --
        see save_text_artifact's docstring for why an agent might pass APPROVED instead.
        """
        version = version_override or self.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=agent_name,
            artifact_type=artifact_type
        )

        stage_folder = self.get_stage_folder(
            project_name=project["project_name"],
            feature_name=feature["feature_name"],
            agent_name=agent_name
        )

        file_path = stage_folder / filename.replace("{version}", str(version))
        saved_path = write_json_file(file_path, data)

        return self._register_artifact(
            project_id=project["project_id"],
            feature_id=feature["feature_id"],
            agent_name=agent_name,
            artifact_type=artifact_type,
            artifact_format=ArtifactFormat.JSON,
            file_path=saved_path,
            version=version,
            summary=summary,
            approval_status=approval_status,
        )

    def _hydrate_artifact_response(self, artifact: dict[str, Any]) -> ArtifactResponse:
        """
        Build an ArtifactResponse, computing size_bytes from the file on disk (never stored --
        the file is the source of truth, and this stays correct even if a file changes size for
        any reason). None if the file is missing rather than raising -- purely cosmetic, so a
        missing file should degrade gracefully, not break the whole list.
        """
        size_bytes = None
        try:
            size_bytes = Path(artifact["file_path"]).stat().st_size
        except OSError:
            pass

        return ArtifactResponse(**artifact, size_bytes=size_bytes)

    def _register_artifact(
        self,
        project_id: str,
        feature_id: str,
        agent_name: AgentName,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat,
        file_path: str,
        version: int,
        summary: str | None = None,
        approval_status: ApprovalStatus = ApprovalStatus.PENDING,
    ) -> ArtifactResponse:
        """
        Create artifact metadata and store it in the temporary in-memory store.
        """
        artifact_id = generate_id("artifact")
        created_at = datetime.utcnow()

        artifact = {
            "artifact_id": artifact_id,
            "project_id": project_id,
            "feature_id": feature_id,
            "agent_name": agent_name,
            "artifact_type": artifact_type,
            "artifact_format": artifact_format,
            "file_path": file_path,
            "version": version,
            "approval_status": approval_status,
            "created_at": created_at,
            "summary": summary,
        }

        store.artifacts[artifact_id] = artifact

        return self._hydrate_artifact_response(artifact)

    def list_feature_artifacts(self, feature_id: str) -> list[ArtifactResponse]:
        """
        Return all artifacts generated for a feature.

        Skips (and logs a warning for) any individual record that fails to validate against
        ArtifactResponse -- e.g. a legacy artifact_type value no longer in the ArtifactType enum
        (confirmed real case: old qa_agent "test_cases" records predating QA Agent being
        simplified to a stub) -- rather than letting one such record break this list for every
        other, perfectly valid artifact belonging to the same feature.
        """
        results = []

        for artifact in store.artifacts.values():
            if artifact["feature_id"] != feature_id:
                continue

            try:
                results.append(self._hydrate_artifact_response(artifact))
            except ValidationError as error:
                logger.warning(
                    "Skipping unparseable artifact %s for feature_id=%s: %s",
                    artifact.get("artifact_id"), feature_id, error,
                )

        return results

    def list_project_artifacts(
        self,
        project_id: str,
        agent_name: AgentName | None = None,
        artifact_type: ArtifactType | None = None,
        artifact_format: ArtifactFormat | None = None,
        approval_status: ApprovalStatus | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return raw artifact records across EVERY feature of a project,
        optionally filtered -- the first project-scoped artifact query
        (every record already carries project_id; all other lookups are
        feature-scoped). Added for the Architecture Agent's project-aware
        generation: a new feature's plan is generated with visibility into
        the previous features' approved plans.

        Enum filters match both the enum and its .value string form, since
        records written by different code paths store either.
        """

        def _matches(value: Any, expected) -> bool:
            return expected is None or value in (expected, expected.value)

        return [
            artifact
            for artifact in store.artifacts.values()
            if artifact.get("project_id") == project_id
            and _matches(artifact.get("agent_name"), agent_name)
            and _matches(artifact.get("artifact_type"), artifact_type)
            and _matches(artifact.get("artifact_format"), artifact_format)
            and _matches(artifact.get("approval_status"), approval_status)
        ]

    def get_artifact(self, artifact_id: str) -> ArtifactResponse | None:
        """
        Return one artifact by ID.
        """
        artifact = store.artifacts.get(artifact_id)

        if not artifact:
            return None

        return self._hydrate_artifact_response(artifact)

    def set_finding_skipped(self, artifact_id: str, finding_id: str, skipped: bool) -> ArtifactResponse | None:
        """
        Mark (or unmark) one security finding as skipped on a security_report artifact -- a human
        choosing to accept the risk and proceed without fixing it. Stored as a side-channel field
        on the artifact RECORD (skipped_finding_ids), mirroring approval_status's own in-place-
        mutation precedent -- never written into content_json, since useArtifactContent's
        staleTime:Infinity on the frontend treats an artifact's JSON content as immutable once
        created; mutating the file in place would leave any already-open tab showing stale data.

        Uses an atomic Mongo $addToSet/$pull instead of a read-modify-write on the whole record
        (the pattern submit_approval uses for approval_status) deliberately -- this field gets
        toggled repeatedly, in quick succession, across many findings on one report, and a
        read-modify-write driven by possibly-stale local state risks silently losing an earlier
        click's update when a later click's write overwrites the whole array.
        """
        if not store.artifacts.get(artifact_id):
            return None

        op = (
            {"$addToSet": {"skipped_finding_ids": finding_id}}
            if skipped
            else {"$pull": {"skipped_finding_ids": finding_id}}
        )
        store.artifacts.collection.update_one({"artifact_id": artifact_id}, op)

        artifact = store.artifacts.get(artifact_id)
        return self._hydrate_artifact_response(artifact)

    @staticmethod
    def _artifact_matches(artifact: dict, feature_id: str, artifact_type: str, artifact_format: str | None) -> bool:
        if artifact.get("feature_id") != feature_id:
            return False
        stored_type = artifact.get("artifact_type")
        if stored_type != artifact_type and getattr(stored_type, "value", stored_type) != artifact_type:
            return False
        if artifact_format is not None:
            stored_format = artifact.get("artifact_format")
            if stored_format != artifact_format and getattr(stored_format, "value", stored_format) != artifact_format:
                return False
        return True

    def get_selected_or_latest_approved_artifact(
        self, feature_id: str, artifact_type: str, artifact_format: str | None = None
    ) -> dict | None:
        """
        Return the artifact a human has explicitly pinned (via set_active_artifact_selection) for
        this (feature_id, artifact_type), if one is set and still valid -- otherwise the latest
        APPROVED version by version number, which is the default every stage's own private
        "_find_latest_approved_*" duplicate (Architecture/Domain/UI-UX/Coder Agent) already used
        before this existed. A stale selection (e.g. pointing at a since-deleted artifact) falls
        through to that same default rather than raising -- pinning a version is meant to be a
        soft override, never a way to permanently break the pipeline if that version goes away.
        """

        feature = store.features.get(feature_id)
        selection_id = (feature.get("active_artifact_selection") or {}).get(artifact_type) if feature else None

        if selection_id:
            selected = store.artifacts.get(selection_id)
            if (
                selected
                and self._artifact_matches(selected, feature_id, artifact_type, artifact_format)
                and selected.get("approval_status") in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value)
            ):
                return selected

        candidates = [
            artifact
            for artifact in store.artifacts.values()
            if self._artifact_matches(artifact, feature_id, artifact_type, artifact_format)
            and artifact.get("approval_status") in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value)
        ]

        if not candidates:
            return None

        return max(candidates, key=lambda item: item.get("version", 1))

    def set_active_artifact_selection(self, feature_id: str, artifact_type: str, artifact_id: str) -> None:
        """
        Pin one APPROVED artifact as the version that feeds the next pipeline stage for this
        (feature, artifact_type) -- e.g. which of several approved SRS versions the Domain Agent
        should read, when a human wants an earlier approved version rather than always the latest.

        Raises ValueError (route layer maps this to 400) if the artifact doesn't exist, doesn't
        belong to this feature, isn't of the given type, or isn't APPROVED -- only approved
        versions are meaningful choices here; a pending/rejected one was never going to feed the
        next stage anyway.
        """

        feature = store.features.get(feature_id)
        if not feature:
            raise ValueError(f"Feature not found: {feature_id}")

        artifact = store.artifacts.get(artifact_id)
        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        if not self._artifact_matches(artifact, feature_id, artifact_type, artifact_format=None):
            raise ValueError(
                f"Artifact {artifact_id} does not belong to this feature or is not of type '{artifact_type}'."
            )

        if artifact.get("approval_status") not in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value):
            raise ValueError("Only an approved artifact version can be selected for the pipeline.")

        selection = dict(feature.get("active_artifact_selection") or {})
        selection[artifact_type] = artifact_id

        updated_feature = dict(feature)
        updated_feature["active_artifact_selection"] = selection
        store.features[feature_id] = updated_feature

    def delete_artifact(self, artifact_id: str) -> None:
        """
        Permanently remove one artifact VERSION -- e.g. an unapproved SRS/architecture-plan/etc.
        version a human decides they don't want cluttering the version history.

        Raises ValueError (the route layer maps this to 400) for: unknown artifact, OR an
        artifact whose VERSION has any sibling (same feature_id/artifact_type/version) already
        APPROVED -- approved artifacts are load-bearing history (what a human actually signed off
        on, what downstream agents/graph state may already reference) and must never be
        deletable, only superseded by a new version. Checking the whole version (not just this
        one artifact_id) matters because every gating artifact_type saves a JSON+Markdown pair at
        one shared version, and the two halves can be approved independently -- calling this
        directly on the still-pending half of an already-approved pair must be refused too, or it
        would silently orphan the approved half's sibling out from under it.

        Cascades to every OTHER sibling in the same version once the check above clears (i.e.
        every sibling in the pair is confirmed non-approved) -- the frontend's version list dedupes
        a JSON+Markdown pair into a single row (see frontend/src/lib/artifactTypeMeta.js's
        dedupeArtifactVersions), so deleting only the one artifact_id behind that row would leave
        its sibling format still in the database, which would then simply reappear as the same
        "version" the human just deleted on the next list refresh.

        Deleting each file on disk is best-effort: a missing/already-gone file just gets logged,
        never raised, since the Mongo record is the part that actually matters for "is this still
        in the version list."
        """

        artifact = store.artifacts.get(artifact_id)

        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        siblings = [
            sibling
            for sibling in store.artifacts.values()
            if sibling["artifact_id"] != artifact_id
            and sibling.get("feature_id") == artifact.get("feature_id")
            and sibling.get("artifact_type") == artifact.get("artifact_type")
            and sibling.get("version") == artifact.get("version")
        ]

        version_group = [artifact, *siblings]
        if any(
            record.get("approval_status") in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value)
            for record in version_group
        ):
            raise ValueError(
                "Cannot delete an approved artifact -- it's part of this feature's approved "
                "history. Only pending, rejected, or revision-requested versions can be deleted."
            )

        for record in version_group:
            try:
                Path(record["file_path"]).unlink(missing_ok=True)
            except OSError as error:
                logger.warning("Failed to delete artifact file for %s: %s", record["artifact_id"], error)

            store.artifacts.collection.delete_one({"artifact_id": record["artifact_id"]})

    def save_binary_artifact(
        self,
        project: dict[str, Any],
        feature: dict[str, Any],
        agent_name: AgentName,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat,
        filename: str,
        binary_content: bytes,
        approval_status: ApprovalStatus = ApprovalStatus.PENDING,
        version_override: int | None = None,
    ) -> ArtifactResponse:
        """
        Save a binary artifact.

        This is mainly used for PNG diagrams generated from PlantUML.

        Example:
            usecase_v1.png

        approval_status defaults to PENDING (every existing caller's behavior, unchanged) --
        see save_text_artifact's docstring for why an agent might pass APPROVED instead.

        version_override lets multiple binary artifacts share one version, the same way
        save_text_artifact/save_json_artifact already do -- previously missing here specifically,
        a real, confirmed bug: a UI/UX run producing multiple pages' screenshots had each one
        silently get its OWN incrementing version (via this method's own get_next_version() call
        below, run once per screenshot within the same save loop) instead of sharing the run's one
        version like every other artifact type it saves alongside.
        """
        version = version_override or self.get_next_version(
            feature_id=feature["feature_id"],
            agent_name=agent_name,
            artifact_type=artifact_type
        )

        stage_folder = self.get_stage_folder(
            project_name=project["project_name"],
            feature_name=feature["feature_name"],
            agent_name=agent_name
        )

        file_path = stage_folder / filename.replace("{version}", str(version))
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_bytes(binary_content)

        return self._register_artifact(
            project_id=project["project_id"],
            feature_id=feature["feature_id"],
            agent_name=agent_name,
            artifact_type=artifact_type,
            artifact_format=artifact_format,
            file_path=str(file_path),
            version=version,
            approval_status=approval_status,
        )

    def get_latest_approved_artifact(
        self,
        feature_id: str,
        agent_name: AgentName,
        artifact_type: ArtifactType,
        artifact_format: ArtifactFormat | None = None
    ) -> ArtifactResponse | None:
        """
        Return the latest approved artifact for a feature and agent.

        This is important for approval gates.

        Example:
        Architecture Agent should only run if:
        - approved SRS exists
        - approved Enhanced SRS exists
        """
        matching_artifacts = []

        for artifact in store.artifacts.values():
            is_same_feature = artifact["feature_id"] == feature_id
            is_same_agent = artifact["agent_name"] == agent_name
            is_same_type = artifact["artifact_type"] == artifact_type
            is_approved = artifact["approval_status"] == ApprovalStatus.APPROVED

            if not all([
                is_same_feature,
                is_same_agent,
                is_same_type,
                is_approved
            ]):
                continue

            if artifact_format is not None:
                if artifact["artifact_format"] != artifact_format:
                    continue

            matching_artifacts.append(artifact)

        if not matching_artifacts:
            return None

        latest = max(matching_artifacts, key=lambda item: item["version"])
        return self._hydrate_artifact_response(latest)

    def read_artifact_content(self, artifact_id: str) -> str:
        """
        Read artifact file content as text.

        This is used by agents to load previous approved artifacts.

        For now, Architecture Agent reads:
        - approved SRS markdown
        - approved Enhanced SRS markdown
        """
        artifact = store.artifacts.get(artifact_id)

        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        file_path = artifact["file_path"]

        with open(file_path, "r", encoding="utf-8") as file:
            return file.read()

    def read_artifact_binary(self, artifact_id: str) -> bytes:
        """
        Read artifact file content as raw bytes (PNG diagrams/screenshots).

        Sibling of read_artifact_content -- used by the artifact content-serving
        API route so the frontend can display images directly.
        """
        artifact = store.artifacts.get(artifact_id)

        if not artifact:
            raise ValueError(f"Artifact not found: {artifact_id}")

        with open(artifact["file_path"], "rb") as file:
            return file.read()

    def export_artifacts_zip(self, artifact_ids: list[str]) -> bytes:
        """
        Bundle several already-saved artifacts' raw file content into one in-memory zip, each
        entry named after its own real on-disk filename (already descriptive -- e.g. a UI/UX
        preview screenshot's own `{feature_slug}_{page_slug}_v{version}.png`). Used by the "download
        all generated images for this version as a zip" feature (direct user request) -- generic
        over any artifact_id list, not screenshot-specific, so it's reusable for a similar
        "download several artifacts at once" need elsewhere later.

        Skips (rather than raises for) any artifact_id that's unknown or whose file is missing on
        disk -- mirrors read_artifact_binary's own real-file error mode, but a caller bundling
        many files together shouldn't fail the whole zip over one gone missing.
        """
        buffer = io.BytesIO()

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
            for artifact_id in artifact_ids:
                artifact = store.artifacts.get(artifact_id)
                if not artifact:
                    continue
                try:
                    with open(artifact["file_path"], "rb") as file:
                        content = file.read()
                except (FileNotFoundError, OSError):
                    continue
                archive.writestr(Path(artifact["file_path"]).name, content)

        return buffer.getvalue()

artifact_service = ArtifactService()