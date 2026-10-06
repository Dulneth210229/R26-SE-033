import { useState } from "react";
import Modal from "../common/Modal";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";
import SeverityBadge from "./SeverityBadge";
import { useArtifactContent } from "../../hooks/useArtifacts";
import { useRunSecurityAgent } from "../../hooks/useSecurityAgent";
import { useCoderAgentFlowContext } from "../workspace/CoderAgentFlowContext";
import { useSetFindingSkippedMutation } from "../../hooks/useSkippedFindingsMutation";
import { buildSecurityRevisionComment } from "../../lib/securityReportToRevisionComment";

// Shown the moment a human approves a Security Report -- direct user request: approval alone
// isn't the end of the story, it's the checkpoint that decides what happens next. Two shapes:
// still has real findings -> "proceed anyway" (accept the risk, loop ends) or "send to Coder
// Agent to fix" (which automatically re-scans once that revision completes -- ResultTab.jsx's
// SECURITY_STAGE handling, agent.py's own module docstring); nothing left to act on (gate
// decision "pass") -> a single acknowledgement, since there's nothing to send. No separate
// loop-tracking state exists anywhere -- each re-scan is a new report version, which is PENDING
// again, which needs approval again, which reopens this same dialog again. That per-version
// approval requirement (not any code in this component) IS the loop.
export default function SecurityDecisionDialog({
  artifactId,
  featureId,
  skippedFindingIds = [],
  onClose,
  onFixStart,
  onFixSettled,
}) {
  const { data, isLoading, error } = useArtifactContent(artifactId);
  const report = data?.content_json;
  const { handleReviseStream, reviseStream } = useCoderAgentFlowContext();
  const runSecurity = useRunSecurityAgent(featureId);
  const setFindingSkipped = useSetFindingSkippedMutation(featureId);
  const [isSending, setIsSending] = useState(false);
  const [isProceeding, setIsProceeding] = useState(false);

  // Direct user decision: this button previously did nothing but close the dialog, so "Continue
  // to QA Agent" stayed disabled regardless -- a real, confirmed dead promise. Now it bulk-marks
  // every currently-open finding in THIS report as Skipped (accept all remaining risk), so the QA
  // gate (securityGate.js, skip-aware) genuinely unblocks afterward. Parallel mutateAsync calls
  // are safe -- the backend's $addToSet is atomic and idempotent per finding id.
  async function handleProceedAnyway() {
    const alreadySkipped = new Set(skippedFindingIds);
    const toSkip = (report?.findings || []).filter((finding) => !alreadySkipped.has(finding.id));
    if (toSkip.length === 0) {
      onClose();
      return;
    }
    setIsProceeding(true);
    try {
      await Promise.all(
        toSkip.map((finding) =>
          setFindingSkipped.mutateAsync({ artifactId, finding_id: finding.id, skipped: true })
        )
      );
    } finally {
      setIsProceeding(false);
      onClose();
    }
  }

  async function handleSendToCoder() {
    setIsSending(true);
    // Fire before the (multi-minute) await, not after -- onFixStart switches the chat/Result
    // panel to Coder Agent (so its live, themed progress view is actually visible) and closing
    // the dialog immediately stops it from covering that view for the whole duration. The
    // component stays mounted after onClose (only its own `open` prop toggles), so continuing
    // this async function afterward is safe.
    onFixStart?.();
    onClose();
    try {
      await handleReviseStream({
        revision_comment: buildSecurityRevisionComment(report),
        revised_by: "security_agent_report",
      });
      // Not awaited: the re-scan runs in the background and shows up as a new pending report
      // version whenever it finishes -- matches the existing "fire the mutation, don't block
      // the UI on it" pattern already used elsewhere in this flow.
      runSecurity.mutate({ human_comment: "Re-scan after the Coder Agent's security-driven revision." });
    } finally {
      setIsSending(false);
      onFixSettled?.();
    }
  }

  return (
    <Modal open={Boolean(artifactId)} onClose={onClose} title="Security Report Approved">
      {isLoading ? (
        <LoadingSpinner label="Loading security report..." />
      ) : error || !report ? (
        <ErrorBanner error={error} fallback="Failed to load the security report." />
      ) : report.gate_decision === "pass" ? (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-gray-700 dark:text-gray-300">
            No Critical or Moderate security issues found in this scan. You're good to proceed.
          </p>
          <div className="flex justify-end">
            <button
              type="button"
              onClick={onClose}
              className="text-sm bg-accent-600 hover:bg-accent-700 text-white font-semibold px-4 py-1.5 rounded-md"
            >
              Continue
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2">
            <SeverityBadge tier={report.gate_decision === "fail" ? "critical" : "moderate"} />
            <p className="text-sm text-gray-700 dark:text-gray-300">
              {report.findings_count} finding(s) -- {report.critical_count} critical, {report.moderate_count} moderate,{" "}
              {report.warning_count} warning.
            </p>
          </div>
          <p className="text-sm text-gray-500 dark:text-gray-400">
            You approved this report. Do you want to proceed with these vulnerabilities as-is, or
            send this report to the Coder Agent to fix them? Proceeding marks every remaining open
            finding as Skipped so Continue to QA Agent unblocks; sending automatically re-scans the
            code once the Coder Agent finishes.
          </p>

          <ErrorBanner
            error={reviseStream.error || runSecurity.error || setFindingSkipped.error}
            fallback="Failed to send the report to the Coder Agent."
          />

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={handleProceedAnyway}
              disabled={isSending || isProceeding}
              title="Mark every remaining open finding in this report as Skipped and proceed"
              className="text-sm bg-white dark:bg-white/10 hover:bg-gray-50 dark:hover:bg-white/20 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 disabled:opacity-50 font-semibold px-4 py-1.5 rounded-md"
            >
              {isProceeding ? "Proceeding..." : "Proceed Anyway"}
            </button>
            <button
              type="button"
              onClick={handleSendToCoder}
              disabled={isSending || isProceeding}
              className="text-sm bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold px-4 py-1.5 rounded-md"
            >
              {isSending ? "Sending..." : "Send to Coder Agent to Fix"}
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
