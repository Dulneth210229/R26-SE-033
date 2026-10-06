"""
Approval service.

This handles human approval decisions.

Important rule:
No agent output should move to the next agent unless the artifact is approved.
"""

from datetime import datetime

from app.agents.coder_agent.agent import coder_agent
from app.agents.uiux_agent.agent import uiux_agent
from app.core.enums import AgentName, ApprovalStatus, ArtifactType
from app.schemas.approval_schema import ApprovalRequest, ApprovalResponse, ApprovalRevokeResponse
from app.services.graph_orchestrator_service import (
    GraphNotRunningError,
    graph_orchestrator_service,
)
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Artifact types that are singleton documents-with-versions, where only one version may hold
# "approved" at a time -- approving a new version supersedes whichever OTHER version (if any) was
# previously approved for this feature, reverting it back to "pending". Direct user report: seeing
# two SRS versions simultaneously "Approved" was confusing (which one does Domain Agent actually
# use?) -- ENHANCED_SRS joins this set for the exact same reason, now that approving it can
# auto-start Architecture Agent against "the" approved version. ARCHITECTURE_PLAN joins for the
# same reason, per direct user request: only one Architecture Plan version is ever "the approved
# one". UI_PREVIEW_SCREENSHOT joins too, per direct user request restoring human approval for the
# UI/UX stage: only one version's worth of UI/UX output (screenshot(s) + everything that rides
# along with it, see _cascade_uiux_screenshot_decision) is ever "the approved one". Deliberately
# narrow, not every gating artifact_type: e.g. UI/UX's ui_component_code artifacts are NOT here --
# they're not independently approved at all anymore (see the cascade below), so there's nothing
# for exclusivity to apply to.
EXCLUSIVE_VERSIONED_ARTIFACT_TYPES = {
    ArtifactType.SRS, ArtifactType.ENHANCED_SRS, ArtifactType.ARCHITECTURE_PLAN,
    ArtifactType.UI_PREVIEW_SCREENSHOT,
}

# The 3 diagram artifact types that ride along with every Architecture Plan generation, always
# sharing its exact version number (confirmed: _save_architecture_artifacts computes ONE version
# via get_next_version and reuses it for the plan's own JSON+Markdown pair AND all 3 diagrams'
# PUML+PNG pairs). Per direct user request, these no longer have their own independent approval
# decision -- approving/rejecting/requesting revision on the Architecture Plan cascades the same
# decision to every one of these, of the SAME version, automatically.
ARCHITECTURE_SIBLING_DIAGRAM_TYPES = {
    ArtifactType.USE_CASE_DIAGRAM, ArtifactType.SEQUENCE_DIAGRAM, ArtifactType.CLASS_DIAGRAM,
}

# Every UI/UX artifact_type EXCEPT the screenshot itself -- these ride along with every UI/UX
# generation, always sharing its exact version number (_save_artifacts computes ONE version and
# reuses it for all of them). Per direct user request, only the Preview Screenshot is ever an
# independent human approval decision -- approving/rejecting/requesting revision on it cascades
# the same decision to all of these, of the SAME version, automatically. Other screenshots of the
# SAME version (a feature with more than one page) are handled separately in
# _cascade_uiux_screenshot_decision -- they're the same artifact_type as the one just decided on,
# not a "sibling type", so this set alone doesn't cover them.
UIUX_SIBLING_ARTIFACT_TYPES = {
    ArtifactType.UI_METADATA, ArtifactType.UI_INTEGRATION_MANIFEST,
    ArtifactType.UI_COMPONENT_CODE, ArtifactType.UI_PAGE_HTML,
}


# Maps each of these 3 gating types to the artifact_type that signals the NEXT pipeline stage has
# already produced output -- once that's true, revoking THIS approval is permanently refused.
# Direct user request: unlike every other revoke, this one must become impossible once the
# pipeline has moved on, even navigating back to this agent later. Deliberately narrow (only these
# 3 transitions) -- Coder Agent's code_diff and UI/UX's Preview Screenshot revoke keep their
# current, more permissive behavior unchanged (out of scope; they already carry their own
# real-git-merge-undo consequences, a different kind of "consequential" than this).
_NEXT_STAGE_GATING_TYPE = {
    ArtifactType.SRS: ArtifactType.ENHANCED_SRS,
    ArtifactType.ENHANCED_SRS: ArtifactType.ARCHITECTURE_PLAN,
    ArtifactType.ARCHITECTURE_PLAN: ArtifactType.UI_PREVIEW_SCREENSHOT,
}


def _is_exclusive_versioned_type(artifact_type) -> bool:
    return any(
        artifact_type in (exclusive_type, exclusive_type.value)
        for exclusive_type in EXCLUSIVE_VERSIONED_ARTIFACT_TYPES
    )


def _is_architecture_plan_type(artifact_type) -> bool:
    return artifact_type in (ArtifactType.ARCHITECTURE_PLAN, ArtifactType.ARCHITECTURE_PLAN.value)


def _is_uiux_screenshot_type(artifact_type) -> bool:
    return artifact_type in (ArtifactType.UI_PREVIEW_SCREENSHOT, ArtifactType.UI_PREVIEW_SCREENSHOT.value)


def _next_stage_gating_type(artifact_type):
    """Returns the next-stage gating ArtifactType for one of the 3 lockable types, else None."""
    for gating_type, next_type in _NEXT_STAGE_GATING_TYPE.items():
        if artifact_type in (gating_type, gating_type.value):
            return next_type
    return None


class ApprovalService:
    """
    Handles approve, reject, and revision request logic.
    """

    def submit_approval(self, artifact_id: str,  request: ApprovalRequest) -> ApprovalResponse | None:
        """
        Save approval decision for an artifact.

        Also updates the artifact approval_status.
        """
        artifact = store.artifacts.get(artifact_id)

        if not artifact:
            return None

        approval_id = generate_id("approval")
        approved_at = datetime.utcnow()

        approval = {
            "approval_id": approval_id,
            "artifact_id": artifact_id,
            "feature_id": artifact["feature_id"],
            "agent_name": artifact["agent_name"],
            "status": request.status,
            "reviewer_comment": request.reviewer_comment,
            "approved_by": request.approved_by,
            "approved_at": approved_at,
        }

        store.approvals[approval_id] = approval

        # Update artifact status directly.
        artifact["approval_status"] = request.status

        # Feature.updated_at was previously dead data (set once at creation, never bumped) --
        # an approval decision is a real, meaningful "something happened on this feature" moment,
        # same reasoning as stage_event_service.record()'s own identical update.
        feature = store.features.get(artifact["feature_id"])
        if feature:
            feature["updated_at"] = approved_at

        is_approved = request.status in [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value]

        # See EXCLUSIVE_VERSIONED_ARTIFACT_TYPES's own docstring for why SRS/Enhanced SRS get this
        # rule. Reverts only a sibling of the SAME artifact_type (never cross-type -- approving an
        # Enhanced SRS must never revert the plain SRS the pipeline still needs approved) AND the
        # SAME artifact_format (a real, previously-reported gap: without this, approving the JSON
        # half of one version could silently revert the Markdown half of a DIFFERENT already-
        # approved version's sibling row, or vice versa, since every gating type saves a JSON+
        # Markdown pair sharing one version number -- see CLAUDE.md's own note on this).
        should_check_exclusivity = is_approved and _is_exclusive_versioned_type(artifact["artifact_type"])

        if should_check_exclusivity:
            for other in store.artifacts.values():
                if other["artifact_id"] == artifact_id:
                    continue
                if other.get("feature_id") != artifact["feature_id"]:
                    continue
                if other.get("artifact_type") != artifact["artifact_type"]:
                    continue
                if other.get("artifact_format") != artifact.get("artifact_format"):
                    continue
                if other.get("approval_status") in [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value]:
                    other["approval_status"] = ApprovalStatus.PENDING
                    # The reverted sibling is a DIFFERENT Architecture Plan/UI-UX version -- its
                    # own siblings must revert too, or that old version's parts go out of sync
                    # (e.g. plan back to pending, diagrams still showing approved).
                    if _is_architecture_plan_type(other.get("artifact_type")):
                        self._cascade_architecture_plan_decision(other, ApprovalStatus.PENDING)
                    elif _is_uiux_screenshot_type(other.get("artifact_type")):
                        self._cascade_uiux_screenshot_decision(other, ApprovalStatus.PENDING)

        # Approving/rejecting/requesting revision on the Architecture Plan applies the exact same
        # decision to its own Markdown/JSON sibling and all 3 diagram artifacts of the SAME
        # version -- per direct user request, diagrams no longer have an independent approval
        # decision at all. Fires on all three outcomes (not just approval), so self-gates on
        # artifact_type internally rather than being nested under is_approved/is_rejected below.
        self._cascade_architecture_plan_decision(artifact, request.status)

        # Same idea for the UI/UX stage's Preview Screenshot -- the human's sole approval surface
        # for that whole stage (see UIUX_SIBLING_ARTIFACT_TYPES's own docstring).
        self._cascade_uiux_screenshot_decision(artifact, request.status)

        # If this artifact belongs to a feature with an active graph run paused on
        # an approval gate, advance it. Most artifacts today are still approved
        # through the legacy manual flow (no graph run started via
        # POST /features/{id}/start), so a missing/mismatched paused run is
        # expected and not an error.
        try:
            graph_orchestrator_service.resume(
                feature_id=artifact["feature_id"],
                resume_value=request.status.value,
            )
        except GraphNotRunningError:
            pass
        except Exception:
            logger.exception(
                "Failed to resume graph run for feature_id=%s after approval",
                artifact["feature_id"],
            )

        # Coder Agent: merge the approved feature branch into main and update
        # project_manifest.json, or discard the branch on rejection -- gated
        # on this exact artifact/version, same discipline as the UI/UX hook
        # above. Never merges automatically regardless of verification result;
        # that's the human's call, informed by merge_report_markdown.
        is_rejected = request.status in [ApprovalStatus.REJECTED, ApprovalStatus.REJECTED.value]
        is_coder_diff = (
            artifact["agent_name"] in [AgentName.CODER, AgentName.CODER.value]
            and artifact["artifact_type"] in [ArtifactType.CODE_DIFF, ArtifactType.CODE_DIFF.value]
        )

        if is_coder_diff and is_approved:
            try:
                coder_agent.merge_approved_feature(
                    feature_id=artifact["feature_id"],
                    version=artifact["version"],
                )
            except Exception:
                logger.exception(
                    "Failed to merge approved feature for feature_id=%s version=%s",
                    artifact["feature_id"],
                    artifact["version"],
                )
        elif is_coder_diff and is_rejected:
            try:
                coder_agent.discard_rejected_feature(feature_id=artifact["feature_id"])
            except Exception:
                logger.exception(
                    "Failed to discard rejected feature branch for feature_id=%s",
                    artifact["feature_id"],
                )

        return ApprovalResponse(**approval)

    def revoke_approval(
        self, artifact_id: str, revoked_by: str = "human_user", reviewer_comment: str | None = None
    ) -> ApprovalRevokeResponse:
        """
        Moves an already-APPROVED artifact back to PENDING -- the one status transition
        submit_approval never exposes (approve/reject/revision_request only ever move forward).
        Direct user request: an approved artifact can't currently be un-approved to request
        changes, even though every other pipeline decision can be revised.

        Reverts the WHOLE version-sibling group (same feature_id + artifact_type + version),
        mirroring artifact_service.delete_artifact's own established "operate on the whole
        version, not one artifact_id" convention -- a gating type's JSON+Markdown pair always
        share one version and must move together. For an artifact_type with its own dedicated
        cascade (Architecture Plan's diagrams, UI/UX's Preview Screenshot siblings), that cascade
        is reused instead of the generic same-type loop (it already covers the format-pair case
        too, so running both would double-revert and write duplicate approval records).

        For a Coder Agent code_diff artifact specifically, also attempts to reverse the real git
        merge approving it already ran (see workspace_service.undo_merge_feature_branch) -- a
        genuine, consequential git operation, reported back honestly via git_reverted/
        restored_branch rather than silently left for the data model and the real code to
        disagree. Never raises for the git step failing -- the data-level revoke has already
        succeeded by that point and must not be rolled back just because the git side hit a
        problem; the failure is logged instead, matching every other post-approval hook's own
        never-raises precedent in this file.

        Raises ValueError if the artifact doesn't exist or isn't currently approved.
        """
        artifact = store.artifacts.get(artifact_id)
        if not artifact:
            raise ValueError("Artifact not found.")

        if artifact.get("approval_status") not in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value):
            raise ValueError("Only an approved artifact can have its approval revoked.")

        # Direct user request: once the pipeline has moved on to the next stage, this approval is
        # permanently locked -- checked here, before any mutation, so a refused revoke never
        # partially reverts anything. Mirrored on the frontend (deriveStageStatus.js's
        # hasNextStageStarted) so the button is normally never even shown; this is the real,
        # authoritative enforcement, not just a hidden button.
        next_type = _next_stage_gating_type(artifact.get("artifact_type"))
        if next_type and any(
            other.get("feature_id") == artifact["feature_id"] and other.get("artifact_type") in (next_type, next_type.value)
            for other in store.artifacts.values()
        ):
            raise ValueError("Cannot revoke this approval -- the pipeline has already moved on to the next stage.")

        approved_at = datetime.utcnow()
        reverted_ids: list[str] = []

        def _revert_one(target: dict, by: str, comment: str) -> None:
            target["approval_status"] = ApprovalStatus.PENDING
            revoke_id = generate_id("approval")
            store.approvals[revoke_id] = {
                "approval_id": revoke_id,
                "artifact_id": target["artifact_id"],
                "feature_id": target["feature_id"],
                "agent_name": target["agent_name"],
                "status": ApprovalStatus.PENDING,
                "reviewer_comment": comment,
                "approved_by": by,
                "approved_at": approved_at,
            }
            reverted_ids.append(target["artifact_id"])

        _revert_one(artifact, revoked_by, reviewer_comment or "Approval revoked by the user to request changes.")

        has_dedicated_cascade = _is_architecture_plan_type(
            artifact.get("artifact_type")
        ) or _is_uiux_screenshot_type(artifact.get("artifact_type"))
        if not has_dedicated_cascade:
            for other in store.artifacts.values():
                if other["artifact_id"] == artifact_id:
                    continue
                if other.get("feature_id") != artifact["feature_id"]:
                    continue
                if other.get("artifact_type") != artifact["artifact_type"]:
                    continue
                if other.get("version") != artifact.get("version"):
                    continue
                if other.get("approval_status") not in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value):
                    continue
                _revert_one(
                    other,
                    "system:approval_revoke_cascade",
                    f"Reverted together with v{artifact['version']} -- not an independent decision.",
                )

        # Both self-gate on artifact_type -- a no-op (empty list) for anything that isn't an
        # Architecture Plan/UI-UX Preview Screenshot, so calling both unconditionally is safe
        # (mirrors submit_approval's own unconditional calls to these same two methods).
        reverted_ids.extend(self._cascade_architecture_plan_decision(artifact, ApprovalStatus.PENDING))
        reverted_ids.extend(self._cascade_uiux_screenshot_decision(artifact, ApprovalStatus.PENDING))

        # Same reasoning as submit_approval's own identical update -- a revoke is a real,
        # meaningful "something happened on this feature" moment too.
        feature = store.features.get(artifact["feature_id"])
        if feature:
            feature["updated_at"] = approved_at

        git_reverted = False
        restored_branch = None
        is_coder_diff = (
            artifact["agent_name"] in [AgentName.CODER, AgentName.CODER.value]
            and artifact["artifact_type"] in [ArtifactType.CODE_DIFF, ArtifactType.CODE_DIFF.value]
        )
        if is_coder_diff:
            try:
                feature = store.features.get(artifact["feature_id"])
                project_id = feature.get("project_id") if feature else None
                if project_id:
                    restored_branch = workspace_service.undo_merge_feature_branch(
                        project_id, artifact["feature_id"]
                    )
                    git_reverted = restored_branch is not None
            except Exception:
                logger.exception(
                    "Failed to undo merge for feature_id=%s version=%s during approval revoke",
                    artifact["feature_id"],
                    artifact["version"],
                )

        return ApprovalRevokeResponse(
            artifact_id=artifact_id,
            status=ApprovalStatus.PENDING,
            reverted_artifact_ids=reverted_ids,
            git_reverted=git_reverted,
            restored_branch=restored_branch,
        )

    def _cascade_architecture_plan_decision(self, artifact: dict, status) -> list[str]:
        """
        Applies `status` to every sibling artifact generated alongside this Architecture Plan
        artifact (its own other format -- JSON/Markdown -- plus all 3 diagram types, both PUML
        and PNG formats) that shares the SAME feature_id and SAME version. Self-gates on
        artifact_type (a no-op for anything that isn't an Architecture Plan artifact), so callers
        can invoke it unconditionally.

        Writes a synthetic approval record per cascaded sibling -- without one, a cascaded
        artifact would be a silent gap in list_feature_approvals (its status visibly changed but
        no record of why/when). approved_by is deliberately "system:architecture_plan_cascade",
        never the human's own name, so a future reader can immediately tell this wasn't an
        independent click -- matches this project's "report, don't misrepresent" convention (see
        Domain Agent's honest unmatched_operations reporting).

        Never raises: a cascade failure must not prevent the human's own approval action from
        succeeding, same precedent as every other post-approval hook in this file.

        Returns the artifact_ids actually touched -- revoke_approval uses this to report an
        honest, complete reverted_artifact_ids list back to the caller (most callers, e.g.
        submit_approval, ignore the return value).
        """
        if not _is_architecture_plan_type(artifact.get("artifact_type")):
            return []

        touched_ids: list[str] = []
        try:
            approved_at = datetime.utcnow()
            for sibling in store.artifacts.values():
                if sibling["artifact_id"] == artifact["artifact_id"]:
                    continue
                if sibling.get("feature_id") != artifact["feature_id"]:
                    continue
                if sibling.get("version") != artifact.get("version"):
                    continue

                is_other_plan_format = (
                    _is_architecture_plan_type(sibling.get("artifact_type"))
                    and sibling.get("artifact_format") != artifact.get("artifact_format")
                )
                is_diagram = any(
                    sibling.get("artifact_type") in (diagram_type, diagram_type.value)
                    for diagram_type in ARCHITECTURE_SIBLING_DIAGRAM_TYPES
                )
                if not (is_other_plan_format or is_diagram):
                    continue

                sibling["approval_status"] = status

                cascade_approval_id = generate_id("approval")
                store.approvals[cascade_approval_id] = {
                    "approval_id": cascade_approval_id,
                    "artifact_id": sibling["artifact_id"],
                    "feature_id": sibling["feature_id"],
                    "agent_name": sibling["agent_name"],
                    "status": status,
                    "reviewer_comment": (
                        f"Auto-{status.value if hasattr(status, 'value') else status} together "
                        f"with Architecture Plan v{artifact['version']} -- not an independent "
                        f"human decision."
                    ),
                    "approved_by": "system:architecture_plan_cascade",
                    "approved_at": approved_at,
                }
                touched_ids.append(sibling["artifact_id"])
        except Exception:
            logger.exception(
                "Failed to cascade Architecture Plan decision for feature_id=%s version=%s",
                artifact.get("feature_id"),
                artifact.get("version"),
            )

        return touched_ids

    def _cascade_uiux_screenshot_decision(self, artifact: dict, status) -> list[str]:
        """
        Applies `status` to every other UI/UX artifact of the SAME feature_id and SAME version as
        this Preview Screenshot -- every UIUX_SIBLING_ARTIFACT_TYPES entry (metadata, integration
        manifest, every component, every page's HTML) AND any OTHER Preview Screenshot of that
        same version (a feature with more than one page/UI -- see agent.py's _save_artifacts,
        which now correctly saves every page's screenshot under one shared version). Self-gates on
        artifact_type (a no-op for anything that isn't a Preview Screenshot), so callers can invoke
        it unconditionally.

        Approving (not rejecting/requesting revision) also triggers apply_design_system_patch for
        this version -- restored to being approval-gated, exactly like every other artifact type
        in this file: a rejected/still-pending run must never pollute the shared design system.

        Writes a synthetic approval record per cascaded sibling, same "report, don't misrepresent"
        convention as _cascade_architecture_plan_decision -- approved_by is
        "system:uiux_screenshot_cascade", never the human's own name.

        Never raises: a cascade failure must not prevent the human's own approval action from
        succeeding, same precedent as every other post-approval hook in this file.

        Returns the artifact_ids actually touched -- revoke_approval uses this to report an
        honest, complete reverted_artifact_ids list back to the caller (most callers, e.g.
        submit_approval, ignore the return value).
        """
        if not _is_uiux_screenshot_type(artifact.get("artifact_type")):
            return []

        touched_ids: list[str] = []
        try:
            approved_at = datetime.utcnow()
            for sibling in store.artifacts.values():
                if sibling["artifact_id"] == artifact["artifact_id"]:
                    continue
                if sibling.get("feature_id") != artifact["feature_id"]:
                    continue
                if sibling.get("version") != artifact.get("version"):
                    continue

                is_sibling_type = any(
                    sibling.get("artifact_type") in (sibling_type, sibling_type.value)
                    for sibling_type in UIUX_SIBLING_ARTIFACT_TYPES
                )
                is_another_screenshot = _is_uiux_screenshot_type(sibling.get("artifact_type"))
                if not (is_sibling_type or is_another_screenshot):
                    continue

                sibling["approval_status"] = status

                cascade_approval_id = generate_id("approval")
                store.approvals[cascade_approval_id] = {
                    "approval_id": cascade_approval_id,
                    "artifact_id": sibling["artifact_id"],
                    "feature_id": sibling["feature_id"],
                    "agent_name": sibling["agent_name"],
                    "status": status,
                    "reviewer_comment": (
                        f"Auto-{status.value if hasattr(status, 'value') else status} together "
                        f"with UI/UX Preview Screenshot v{artifact['version']} -- not an "
                        f"independent human decision."
                    ),
                    "approved_by": "system:uiux_screenshot_cascade",
                    "approved_at": approved_at,
                }
                touched_ids.append(sibling["artifact_id"])

            if status in (ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value):
                uiux_agent.apply_design_system_patch(artifact["feature_id"], artifact["version"])
        except Exception:
            logger.exception(
                "Failed to cascade UI/UX screenshot decision for feature_id=%s version=%s",
                artifact.get("feature_id"),
                artifact.get("version"),
            )

        return touched_ids

    def list_feature_approvals(self, feature_id: str) -> list[ApprovalResponse]:
        """
        Return every approval decision recorded for a feature, oldest first -- powers the
        frontend's per-stage activity timeline (a real, chronological record of what was
        approved/rejected/revision-requested and when, not a reconstruction).

        Matches via each approval's OWN artifact's feature_id, not the approval's own
        `feature_id` field (added in submit_approval going forward) -- every approval ever made
        before that field existed would otherwise be permanently invisible here, and this
        feature's entire pre-existing approval history is exactly that case. The artifact join
        works identically for old and new records, so it's used unconditionally rather than as a
        fallback.
        """
        results = []

        for approval in store.approvals.values():
            artifact = store.artifacts.get(approval.get("artifact_id"))

            if not artifact or artifact.get("feature_id") != feature_id:
                continue

            try:
                results.append(ApprovalResponse(**approval))
            except Exception:
                logger.warning("Skipping unparseable approval %s", approval.get("approval_id"))

        results.sort(key=lambda a: a.approved_at)
        return results

    def is_artifact_approved(self, artifact_id: str) -> bool:
        """
        Check whether an artifact has been approved.
        """
        artifact = store.artifacts.get(artifact_id)

        if not artifact:
            return False

        return artifact["approval_status"] == ApprovalStatus.APPROVED


approval_service = ApprovalService()