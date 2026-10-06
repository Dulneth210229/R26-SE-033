import { useState } from "react";
import { useApprovalMutation } from "../../hooks/useApprovalMutation";
import ErrorBanner from "../common/ErrorBanner";

// `onApproveClick`, when provided (every stage with an APPROVE_CONTINUATION_BY_STAGE entry in
// ResultTab.jsx -- currently Requirement/Domain/Architecture/UI-UX), is called with the trimmed
// comment instead of approving directly -- the caller (ResultTab, via GovernancePanel or
// UiuxVersionGroupList) owns the confirm-dialog + auto-continue orchestration for that case. This
// component itself must NOT own that orchestration: it gets unmounted the instant the artifact's
// approval_status stops being "pending" (this component's own parent swaps it out for a plain
// status line), which happens mid-flight the moment the approval call succeeds -- an async
// sequence started here would be abandoned right after that first step, never reaching the
// "start the next agent" part. Reject/Request Revision have no such multi-step follow-up, so they
// stay handled locally.
export default function ApprovalPanel({ featureId, artifact, warning, onApproveClick, approveLocked = false }) {
  const [comment, setComment] = useState("");
  const approval = useApprovalMutation(featureId);

  function submit(status) {
    approval.mutate({ artifactId: artifact.artifact_id, status, reviewer_comment: comment.trim() || null });
  }

  function handleApproveClick() {
    if (onApproveClick) {
      onApproveClick(comment.trim() || null);
      return;
    }
    submit("approved");
  }

  return (
    <div className="bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-200 dark:border-yellow-500/30 rounded-lg p-4 mt-3">
      <p className="text-sm font-semibold text-yellow-900 dark:text-yellow-200 mb-2">
        Awaiting your review (v{artifact.version})
      </p>

      {warning && (
        <div className="bg-white dark:bg-gray-900 border border-yellow-300 dark:border-yellow-500/30 rounded p-3 text-xs text-gray-700 dark:text-gray-300 mb-3">
          {warning}
        </div>
      )}

      <ErrorBanner error={approval.error} fallback="Failed to submit approval decision." />

      <textarea
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        placeholder="Optional comment..."
        rows={2}
        className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md mb-2 focus:outline-none focus:border-accent-500"
      />

      <div className="flex gap-2">
        <button
          onClick={handleApproveClick}
          disabled={approval.isPending || approveLocked}
          title={approveLocked ? "Another version is already approved -- reject it first to approve a different one" : undefined}
          className="bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm font-semibold py-1.5 px-3 rounded"
        >
          Approve
        </button>
        <button
          onClick={() => submit("revision_requested")}
          disabled={approval.isPending}
          className="bg-orange-500 hover:bg-orange-600 disabled:opacity-50 text-white text-sm font-semibold py-1.5 px-3 rounded"
        >
          Request Revision
        </button>
        <button
          onClick={() => submit("rejected")}
          disabled={approval.isPending}
          className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm font-semibold py-1.5 px-3 rounded"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
