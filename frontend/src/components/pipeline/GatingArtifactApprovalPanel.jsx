import { useState } from "react";
import ApprovalPanel from "./ApprovalPanel";
import ConfirmDialog from "../common/ConfirmDialog";
import ErrorBanner from "../common/ErrorBanner";
import { ARTIFACT_TYPE_LABELS } from "../../lib/artifactTypeMeta";
import { useApprovalMutation, useRevokeApprovalMutation } from "../../hooks/useApprovalMutation";
import { useDeleteArtifact } from "../../hooks/useArtifacts";

// The consolidated approval surface for CONSOLIDATED_APPROVAL_STAGES (requirement/domain/
// architecture -- see pipelineStages.js) -- mirrors Security Agent's own already-shipped "one
// version dropdown + one inline approval control" pattern (ResultTab.jsx's security branch)
// instead of the generic stacked "All Artifacts" list + separate Governance panel those stages
// used to render. Always renders for exactly ONE artifact: whichever version the dropdown above
// currently has selected (ResultTab.jsx's `selectedVersionArtifact`) -- never a list.
//
// `canRevoke` is computed by the caller (ResultTab.jsx), not here -- it depends on pipeline-wide
// state (has the next stage started, is it currently generating) that this component has no
// access to and shouldn't need to.
export default function GatingArtifactApprovalPanel({ featureId, artifact, approveLocked, canRevoke, onApproveClick }) {
  const [confirmingRevoke, setConfirmingRevoke] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const approval = useApprovalMutation(featureId);
  const revokeApproval = useRevokeApprovalMutation(featureId);
  const deleteArtifact = useDeleteArtifact(featureId);

  const label = ARTIFACT_TYPE_LABELS[artifact.artifact_type] || artifact.artifact_type;
  // Matches ArtifactRow.jsx's own canDelete exactly: an approved artifact is permanent history,
  // only a pending/rejected/revision_requested version can ever be removed.
  const canDelete = artifact.approval_status !== "approved";

  // Matches ArtifactRow.jsx's showInlineApproval / GovernancePanel.jsx's isAwaitingReview exactly
  // -- ONLY "pending" gets live Approve/Reject/Request-Revision controls. "revision_requested" is
  // itself a terminal decision already made on this specific version (same as "rejected", just
  // worded as "please revise"), so it falls into the plain-status-line branch below like rejected
  // does -- a fresh revision arrives as a brand NEW pending version, not a status flip back.
  if (artifact.approval_status === "pending") {
    return (
      <div className="flex flex-col gap-2">
        <ApprovalPanel
          featureId={featureId}
          artifact={artifact}
          onApproveClick={onApproveClick ? (comment) => onApproveClick(artifact.artifact_id, comment) : undefined}
          approveLocked={approveLocked}
        />
        <div>
          <button
            type="button"
            onClick={() => setConfirmingDelete(true)}
            title="Delete this unapproved version"
            className="text-xs font-semibold text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400"
          >
            Delete v{artifact.version}
          </button>
        </div>
        <ConfirmDialog
          open={confirmingDelete}
          onClose={() => {
            if (!deleteArtifact.isPending) setConfirmingDelete(false);
          }}
          onConfirm={() => deleteArtifact.mutate(artifact.artifact_id, { onSuccess: () => setConfirmingDelete(false) })}
          title="Delete this artifact version?"
          message={`This permanently deletes ${label} v${artifact.version}. This cannot be undone.`}
          confirmLabel="Delete"
          confirmingLabel="Deleting..."
          confirming={deleteArtifact.isPending}
          error={deleteArtifact.error}
          errorFallback="Failed to delete artifact."
        />
      </div>
    );
  }

  return (
    <div className="flex items-center justify-between flex-wrap gap-2">
      <p className="text-xs text-gray-400 dark:text-gray-500">
        v{artifact.version} is {artifact.approval_status}.
      </p>
      <div className="flex items-center gap-3">
        {artifact.approval_status === "approved" && canRevoke && (
          <button
            type="button"
            onClick={() => setConfirmingRevoke(true)}
            title="Revoke this approval and return to Pending review"
            className="text-xs font-semibold text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400"
          >
            Revoke approval
          </button>
        )}
        {canDelete && (
          <button
            type="button"
            onClick={() => setConfirmingDelete(true)}
            title="Delete this unapproved version"
            className="text-xs font-semibold text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400"
          >
            Delete v{artifact.version}
          </button>
        )}
      </div>

      <ErrorBanner error={approval.error} fallback="Failed to submit approval decision." />

      <ConfirmDialog
        open={confirmingRevoke}
        onClose={() => {
          if (!revokeApproval.isPending) setConfirmingRevoke(false);
        }}
        onConfirm={() =>
          revokeApproval.mutate({ artifactId: artifact.artifact_id }, { onSuccess: () => setConfirmingRevoke(false) })
        }
        title={`Revoke approval for v${artifact.version}?`}
        message={`This returns ${label} v${artifact.version} to Pending review, and any real artifact/diagram that was cascaded along with this approval reverts with it.`}
        confirmLabel="Revoke approval"
        confirmingLabel="Revoking..."
        confirming={revokeApproval.isPending}
        error={revokeApproval.error}
        errorFallback="Failed to revoke the approval."
      />

      <ConfirmDialog
        open={confirmingDelete}
        onClose={() => {
          if (!deleteArtifact.isPending) setConfirmingDelete(false);
        }}
        onConfirm={() => deleteArtifact.mutate(artifact.artifact_id, { onSuccess: () => setConfirmingDelete(false) })}
        title="Delete this artifact version?"
        message={`This permanently deletes ${label} v${artifact.version}. This cannot be undone.`}
        confirmLabel="Delete"
        confirmingLabel="Deleting..."
        confirming={deleteArtifact.isPending}
        error={deleteArtifact.error}
        errorFallback="Failed to delete artifact."
      />
    </div>
  );
}
