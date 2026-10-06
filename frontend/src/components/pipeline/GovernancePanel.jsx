import { useState, useMemo } from "react";
import { getOperativeGatingArtifact } from "../../lib/deriveStageStatus";
import { ARTIFACT_TYPE_LABELS } from "../../lib/artifactTypeMeta";
import { artifactDownloadUrl } from "../../api/client";
import { useArtifactContent } from "../../hooks/useArtifacts";
import { useRevokeApprovalMutation } from "../../hooks/useApprovalMutation";
import ApprovalPanel from "./ApprovalPanel";
import ConfirmDialog from "../common/ConfirmDialog";
import LoadingSpinner from "../common/LoadingSpinner";

const APPROVAL_WARNINGS = {
  coder: (
    <>
      Approving this runs a real <code>git merge --no-ff</code> into <code>main</code> and{" "}
      <strong>permanently deletes</strong> the feature branch. Rejecting runs{" "}
      <code>git branch -D</code>, <strong>discarding all commits</strong>. Revoking the approval
      afterward attempts to reverse the merge with a real <code>git revert</code> and restore the
      feature branch (see the "Revoke approval" action below once approved) -- still a heavyweight
      action worth pausing over, no longer literally undoable-never.
    </>
  ),
};

// Per-stage explanation shown in the revoke confirmation popup -- only "coder" has a real,
// consequential side effect to name (the same git merge APPROVAL_WARNINGS.coder describes);
// every other stage is a plain, low-stakes data flip.
const REVOKE_WARNINGS = {
  coder: "This will attempt to reverse the git merge into main (via a real git revert) and restore the feature branch, so you can request changes.",
};

function formatBytes(bytes) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function extractTraceLinks(contentJson) {
  if (!contentJson) return [];

  if (Array.isArray(contentJson.traceability)) {
    return contentJson.traceability
      .filter((t) => t.requirement_id)
      .map((t) => ({
        id: t.requirement_id,
        related: t.related_acceptance_criteria || [],
      }));
  }

  if (Array.isArray(contentJson.traceability_matrix)) {
    return contentJson.traceability_matrix
      .filter((t) => t.source_id)
      .map((t) => ({
        id: t.source_id,
        related: t.coverage_status ? [t.coverage_status] : [],
      }));
  }

  return [];
}

// `onApproveClick`, when provided (only the Requirement stage's SRS passes this, from ResultTab
// -- see its own docstring for why the confirm-dialog + auto-run-Domain-Agent orchestration lives
// there and not here or in ApprovalPanel), is called with (artifactId, comment) instead of
// approving directly. Reject/Request Revision have no such multi-step follow-up and stay
// immediate, handled inside ApprovalPanel itself.
export default function GovernancePanel({ stage, featureId, allArtifacts, stageArtifacts, onApproveClick }) {
  const gatingArtifact = getOperativeGatingArtifact(stage, allArtifacts);
  const isAwaitingReview = gatingArtifact?.approval_status === "pending";
  // Real, reported bug: this panel's own Approve button never respected the same "once one
  // version is approved, every other pending version's Approve is disabled" lock ArtifactList.jsx
  // already enforces for the generic "All Artifacts" list -- a human could still approve a second
  // SRS (or any other gating type) version from here even after another was already approved.
  // Same computation ArtifactList.jsx uses: a sibling of the same artifact_type, already approved.
  const approveLocked = Boolean(
    gatingArtifact &&
      stageArtifacts.some(
        (a) => a.artifact_type === gatingArtifact.artifact_type && a.approval_status === "approved" && a.artifact_id !== gatingArtifact.artifact_id
      )
  );

  const { data: gatingContent } = useArtifactContent(
    gatingArtifact?.artifact_format === "json" ? gatingArtifact.artifact_id : null
  );
  const traceLinks = useMemo(() => extractTraceLinks(gatingContent?.content_json), [gatingContent]);

  // Direct user request: an approved gating artifact previously had no way back to pending at
  // all -- see useApprovalMutation.js's useRevokeApprovalMutation and approval_service.py's
  // revoke_approval for the actual capability this triggers.
  const [confirmingRevoke, setConfirmingRevoke] = useState(false);
  const revokeApproval = useRevokeApprovalMutation(featureId);

  const sortedArtifacts = useMemo(
    () => [...stageArtifacts].sort((a, b) => b.version - a.version || a.artifact_type.localeCompare(b.artifact_type)),
    [stageArtifacts]
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="pb-4 border-b border-gray-100 dark:border-gray-800">
        <h3 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">Stage Actions</h3>
        {stage === "uiux" ? (
          // UiuxVersionGroupList (in the All Artifacts section above) already lets a human
          // approve/reject/request-revision on ANY pending version's whole batch of pages -- a
          // second ApprovalPanel here (for just whichever ONE screenshot happens to be
          // "operative") would be redundant and could show a different version than the one a
          // human just acted on above.
          <p className="text-xs text-gray-400 dark:text-gray-500">
            {gatingArtifact
              ? "Approve, reject, or request revision on each UI/UX version's whole batch of pages in All Artifacts above."
              : "No output yet for this stage."}
          </p>
        ) : gatingArtifact ? (
          isAwaitingReview ? (
            <ApprovalPanel
              featureId={featureId}
              artifact={gatingArtifact}
              warning={APPROVAL_WARNINGS[stage]}
              onApproveClick={onApproveClick ? (comment) => onApproveClick(gatingArtifact.artifact_id, comment) : undefined}
              approveLocked={approveLocked}
            />
          ) : (
            <div className="flex items-center justify-between flex-wrap gap-2">
              <p className="text-xs text-gray-400 dark:text-gray-500 min-w-0">
                Latest version (v{gatingArtifact.version}) is {gatingArtifact.approval_status}. Nothing pending.
              </p>
              {gatingArtifact.approval_status === "approved" && (
                <button
                  type="button"
                  onClick={() => setConfirmingRevoke(true)}
                  className="text-xs font-semibold text-gray-500 dark:text-gray-400 hover:text-red-600 dark:hover:text-red-400 flex-shrink-0"
                >
                  Revoke approval
                </button>
              )}
            </div>
          )
        ) : (
          <p className="text-xs text-gray-400 dark:text-gray-500">No output yet for this stage.</p>
        )}
      </div>

      {gatingArtifact && (
        <ConfirmDialog
          open={confirmingRevoke}
          onClose={() => {
            if (!revokeApproval.isPending) setConfirmingRevoke(false);
          }}
          onConfirm={() =>
            revokeApproval.mutate(
              { artifactId: gatingArtifact.artifact_id },
              { onSuccess: () => setConfirmingRevoke(false) }
            )
          }
          title={`Revoke approval for v${gatingArtifact.version}?`}
          message={
            REVOKE_WARNINGS[stage] ||
            `v${gatingArtifact.version} returns to Pending review, and any real artifact/diagram that was cascaded along with this approval reverts with it.`
          }
          confirmLabel="Revoke approval"
          confirmingLabel="Revoking..."
          tone="danger"
          confirming={revokeApproval.isPending}
          error={revokeApproval.error}
          errorFallback="Failed to revoke the approval."
        />
      )}

      {traceLinks.length > 0 && (
        <div className="pb-4 border-b border-gray-100 dark:border-gray-800">
          <h3 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">Trace Links</h3>
          <div className="flex flex-col gap-1.5 max-h-48 overflow-y-auto">
            {traceLinks.map((link) => (
              <div key={link.id} className="flex items-center gap-1 flex-wrap text-xs">
                <span className="bg-blue-50 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300 font-semibold px-1.5 py-0.5 rounded">{link.id}</span>
                {link.related.map((r) => (
                  <span key={r} className="text-gray-400 dark:text-gray-500">
                    &rarr; <span className="bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300 px-1.5 py-0.5 rounded">{r}</span>
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <h3 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">Stage Artifacts</h3>
        {sortedArtifacts.length === 0 ? (
          <p className="text-xs text-gray-400 dark:text-gray-500">No artifacts yet.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {sortedArtifacts.map((artifact) => (
              <div key={artifact.artifact_id} className="flex items-center justify-between text-xs py-1">
                <span className="text-gray-700 dark:text-gray-300 truncate" title={ARTIFACT_TYPE_LABELS[artifact.artifact_type]}>
                  {ARTIFACT_TYPE_LABELS[artifact.artifact_type] || artifact.artifact_type}
                  <span className="text-gray-400 dark:text-gray-500"> v{artifact.version}</span>
                </span>
                <span className="flex items-center gap-2 flex-shrink-0">
                  <span className="text-gray-400 dark:text-gray-500">{formatBytes(artifact.size_bytes)}</span>
                  <a
                    href={artifactDownloadUrl(artifact.artifact_id)}
                    className="text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold"
                  >
                    Download
                  </a>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
