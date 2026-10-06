import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import StatusBadge from "../common/StatusBadge";
import ErrorBanner from "../common/ErrorBanner";
import ConfirmDialog from "../common/ConfirmDialog";
import {
  ARTIFACT_TYPE_LABELS,
  ARTIFACT_TYPE_STAGE,
  NON_APPROVABLE_ARTIFACT_TYPES,
  screenshotPageLabel,
} from "../../lib/artifactTypeMeta";
import { useApprovalMutation, useRevokeApprovalMutation } from "../../hooks/useApprovalMutation";
import { useDeleteArtifact } from "../../hooks/useArtifacts";

// Mirrors GovernancePanel.jsx's own REVOKE_WARNINGS -- only the coder stage's code_diff artifact
// has a real, consequential side effect (a git merge) worth naming before revoking its approval.
const REVOKE_WARNING_BY_STAGE = {
  coder: "This will attempt to reverse the git merge into main (via a real git revert) and restore the feature branch, so you can request changes.",
};

// Per-artifact approve/reject/request-revision -- every pending/rejected version of every
// artifact_type gets its own inline controls here, full stop. This used to be suppressed for
// whichever single version a stage's separate "gating" ApprovalPanel already showed, on the
// theory that only one version is ever actionable at a time -- a real, twice-reported bug: a
// human looking at [v1: pending, v2: rejected, v3: pending] could only ever approve ONE of the
// pending versions (whichever the resolver picked as "operative"), with no visible way to
// select or approve the other one at all. There is no longer any such suppression -- every row
// is independently, consistently actionable. `onApproveClick`, when provided, intercepts Approve
// specifically (see ResultTab.jsx for why SRS routes this through a confirmation +
// auto-run-Domain-Agent flow instead of approving immediately). `approveLocked`, when true,
// disables ONLY the Approve button (Reject/Request Revision stay available) -- set once a
// sibling version of the same artifact_type is already approved, so a stray click can't create
// two simultaneously-approved versions; switching which one is approved requires explicitly
// rejecting the current approval first, per direct user request.
export default function ArtifactRow({
  artifact,
  onView,
  reviseMutation,
  featureId,
  showActiveSelector = false,
  isActiveSelection = false,
  onSetActive,
  settingActive = false,
  onApproveClick,
  approveLocked = false,
}) {
  const [showRevise, setShowRevise] = useState(false);
  const [revisionComment, setRevisionComment] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [confirmingRevoke, setConfirmingRevoke] = useState(false);
  const approval = useApprovalMutation(featureId);
  const deleteArtifact = useDeleteArtifact(featureId);
  const revokeApproval = useRevokeApprovalMutation(featureId);
  const { user } = useAuth();

  async function submitRevision(event) {
    event.preventDefault();
    await reviseMutation.mutateAsync({
      revision_comment: revisionComment.trim(),
      revised_by: user?.name || user?.email || "human_user",
    });
    setShowRevise(false);
    setRevisionComment("");
  }

  // Shared signal for both "no approve/reject controls" (since there's no real decision to make
  // on this artifact) and "visually highlight this row" (it's the one artifact worth a human's
  // attention here, e.g. Setup Instructions on the Coder stage) -- both target the same set of
  // display-only artifact types, so one derived boolean covers both.
  const isNonApprovableType = NON_APPROVABLE_ARTIFACT_TYPES.includes(artifact.artifact_type);
  const showInlineApproval = Boolean(featureId) && artifact.approval_status === "pending" && !isNonApprovableType;
  // Approved artifacts are permanent history (matches the backend's own refusal to delete them) --
  // only an unapproved (pending/rejected/revision_requested) version can ever be removed.
  const canDelete = artifact.approval_status !== "approved";
  // The counterpart to canDelete -- only an APPROVED row is ever meaningful to revoke, and only
  // where there's a real featureId/decision to act on (mirrors showInlineApproval's own gating).
  const canRevoke = Boolean(featureId) && artifact.approval_status === "approved" && !isNonApprovableType;
  // Only an approved version is a meaningful pipeline input -- the backend refuses to pin
  // anything else, so the radio button only ever appears where it could actually be selected.
  const canSelectActive = showActiveSelector && artifact.approval_status === "approved";

  return (
    <div
      className={`rounded p-3 ${
        isNonApprovableType
          ? "bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30"
          : "bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800"
      }`}
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2 min-w-0">
          {canSelectActive && (
            <input
              type="radio"
              name={`active-${artifact.artifact_type}`}
              checked={isActiveSelection}
              disabled={settingActive}
              onChange={() => onSetActive?.(artifact.artifact_id)}
              title="Use this version for the next agent"
              className="accent-accent-600 disabled:opacity-50 cursor-pointer"
            />
          )}
          <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{ARTIFACT_TYPE_LABELS[artifact.artifact_type] || artifact.artifact_type}</span>
          {artifact.artifact_type === "ui_preview_screenshot" && screenshotPageLabel(artifact) && (
            <span className="text-xs text-gray-500 dark:text-gray-400 italic truncate max-w-[220px]">
              {screenshotPageLabel(artifact)}
            </span>
          )}
          <span className="text-xs text-gray-400 dark:text-gray-500">v{artifact.version}</span>
          {isActiveSelection && (
            <span className="text-[10px] font-semibold text-accent-700 dark:text-accent-400 bg-accent-50 dark:bg-accent-500/10 rounded-full px-2 py-0.5">
              In use
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {!isNonApprovableType && <StatusBadge status={artifact.approval_status} />}
          <button onClick={() => onView(artifact)} className="text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 text-sm font-semibold">
            View
          </button>
          {reviseMutation && (
            <button
              onClick={() => setShowRevise((v) => !v)}
              className="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 text-sm font-semibold"
            >
              Revise
            </button>
          )}
          {canRevoke && (
            <button
              onClick={() => setConfirmingRevoke(true)}
              title="Revoke this approval and return to Pending review"
              className="text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 text-sm font-semibold"
            >
              Revoke
            </button>
          )}
          {canDelete && (
            <button
              onClick={() => setConfirmingDelete(true)}
              title="Delete this unapproved version"
              className="text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 text-sm font-semibold"
            >
              Delete
            </button>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={canRevoke && confirmingRevoke}
        onClose={() => {
          if (!revokeApproval.isPending) setConfirmingRevoke(false);
        }}
        onConfirm={() =>
          revokeApproval.mutate(
            { artifactId: artifact.artifact_id },
            { onSuccess: () => setConfirmingRevoke(false) }
          )
        }
        title={`Revoke approval for v${artifact.version}?`}
        message={
          REVOKE_WARNING_BY_STAGE[ARTIFACT_TYPE_STAGE[artifact.artifact_type]] ||
          `This returns ${ARTIFACT_TYPE_LABELS[artifact.artifact_type] || artifact.artifact_type} v${artifact.version} to Pending review, and any real artifact/diagram cascaded along with this approval reverts with it.`
        }
        confirmLabel="Revoke approval"
        confirmingLabel="Revoking..."
        confirming={revokeApproval.isPending}
        error={revokeApproval.error}
        errorFallback="Failed to revoke the approval."
      />

      <ConfirmDialog
        open={canDelete && confirmingDelete}
        onClose={() => {
          if (!deleteArtifact.isPending) setConfirmingDelete(false);
        }}
        onConfirm={() =>
          deleteArtifact.mutate(artifact.artifact_id, { onSuccess: () => setConfirmingDelete(false) })
        }
        title="Delete this artifact version?"
        message={`This permanently deletes ${ARTIFACT_TYPE_LABELS[artifact.artifact_type] || artifact.artifact_type} v${artifact.version}. This cannot be undone.`}
        confirmLabel="Delete"
        confirmingLabel="Deleting..."
        confirming={deleteArtifact.isPending}
        error={deleteArtifact.error}
        errorFallback="Failed to delete artifact."
      />

      {showInlineApproval && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          <ErrorBanner error={approval.error} fallback="Failed to submit approval decision." />
          <div className="flex gap-2">
            <button
              onClick={() =>
                onApproveClick
                  ? onApproveClick(artifact.artifact_id)
                  : approval.mutate({ artifactId: artifact.artifact_id, status: "approved" })
              }
              disabled={approval.isPending || approveLocked}
              title={approveLocked ? "Another version is already approved -- reject it first to approve a different one." : undefined}
              className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-xs font-semibold py-1 px-2 rounded"
            >
              Approve
            </button>
            <button
              onClick={() => approval.mutate({ artifactId: artifact.artifact_id, status: "revision_requested" })}
              disabled={approval.isPending}
              className="bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-xs font-semibold py-1 px-2 rounded"
            >
              Request Revision
            </button>
            <button
              onClick={() => approval.mutate({ artifactId: artifact.artifact_id, status: "rejected" })}
              disabled={approval.isPending}
              className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-xs font-semibold py-1 px-2 rounded"
            >
              Reject
            </button>
          </div>
        </div>
      )}

      {showRevise && (
        <form onSubmit={submitRevision} className="mt-3 flex flex-col gap-2">
          <ErrorBanner error={reviseMutation.error} fallback="Revision failed." />
          <textarea
            required
            value={revisionComment}
            onChange={(e) => setRevisionComment(e.target.value)}
            placeholder="What should change?"
            rows={2}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
          <button
            type="submit"
            disabled={reviseMutation.isPending}
            className="self-start bg-gray-700 hover:bg-gray-800 dark:bg-white/10 dark:hover:bg-white/20 disabled:opacity-50 text-white dark:text-gray-100 text-sm font-semibold py-1.5 px-3 rounded"
          >
            {reviseMutation.isPending ? "Submitting..." : "Submit Revision"}
          </button>
        </form>
      )}
    </div>
  );
}
