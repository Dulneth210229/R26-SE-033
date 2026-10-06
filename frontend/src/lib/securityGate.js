import { toDisplayTier } from "./severityTiers";

// Single source of truth for "does the latest security scan block Continue to QA Agent," used by
// both ResultTab.jsx (disables the button) and WorkspaceSelectionContext.jsx (disables the QA
// stage in the agent picker) -- previously each computed this independently from
// report.gate_decision === "fail" alone. Now also skip-aware: a Critical finding a human has
// explicitly marked Skipped no longer blocks, but an un-skipped Critical finding always does,
// regardless of Moderate/Warning findings (which never blocked before this feature either).
export function computeSecurityGateBlocksQa(findings, skippedFindingIds) {
  const skipped = new Set(skippedFindingIds || []);
  return (findings || []).some(
    (finding) => toDisplayTier(finding.severity) === "critical" && !skipped.has(finding.id)
  );
}
