import { useArtifactContent } from "../../hooks/useArtifacts";
import { useSecurityAgentFlowContext } from "../workspace/SecurityAgentFlowContext";
import { useSetFindingSkippedMutation } from "../../hooks/useSkippedFindingsMutation";
import { DISPLAY_TIERS, groupFindingsByTier, toDisplayTier } from "../../lib/severityTiers";
import { classifySecurityFindings } from "../../lib/securityFindingsComparison";
import { computeSecurityGateBlocksQa } from "../../lib/securityGate";
import SeverityBadge from "./SeverityBadge";
import ScanProgressBar from "../common/ScanProgressBar";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

const GATE_BANNER_STYLE = {
  fail: "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30 text-red-800 dark:text-red-300",
  review: "bg-orange-50 dark:bg-orange-500/10 border-orange-200 dark:border-orange-500/30 text-orange-800 dark:text-orange-300",
  pass: "bg-green-50 dark:bg-green-500/10 border-green-200 dark:border-green-500/30 text-green-800 dark:text-green-300",
  // A distinct 4th state (not one of the backend's own gate_decision values) -- every Critical
  // finding has been explicitly skipped, so the gate no longer blocks, but this is a deliberate
  // accepted-risk state, not a clean "pass," so it gets its own honest wording/color rather than
  // silently reusing "pass".
  skipped: "bg-blue-50 dark:bg-blue-500/10 border-blue-200 dark:border-blue-500/30 text-blue-800 dark:text-blue-300",
};

const GATE_BANNER_TEXT = {
  fail: "Critical vulnerabilities found -- review before proceeding.",
  review: "Moderate-severity findings to review.",
  pass: "No Critical or Moderate findings.",
  skipped: "All Critical vulnerabilities have been skipped -- safe to continue to QA Agent.",
};

const TIER_HEADING = { critical: "Critical", moderate: "Moderate", warning: "Warning" };

function FindingRow({ finding, skipped, onToggleSkip }) {
  const loc = finding.line ? `${finding.file}:${finding.line}` : finding.file;
  return (
    <div
      className={`flex items-start gap-3 py-2 border-b border-gray-100 dark:border-gray-800 last:border-0 ${
        skipped ? "opacity-50" : ""
      }`}
    >
      <SeverityBadge tier={toDisplayTier(finding.severity)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="text-sm text-gray-800 dark:text-gray-200">{finding.message}</p>
          {skipped && (
            <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-white/10 rounded-full px-2 py-0.5">
              Skipped
            </span>
          )}
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5">
          {finding.rule_id} -- {loc} -- {finding.cwe}
        </p>
        {finding.root_cause && (
          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
            <span className="font-semibold">Root cause:</span> {finding.root_cause}
          </p>
        )}
        {finding.recommendation && (
          <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
            <span className="font-semibold">Suggested fix:</span> {finding.recommendation}
          </p>
        )}
      </div>
      {/* Direct user request: only "Skip" is a real control -- "Open" is just the default,
          unskipped state, not something a human needs to click back to. A single checkbox (not a
          lone radio) is the correct native element here: a radio, once checked, can't be
          unchecked by clicking it again, so a lone "Skip" radio would let a human skip a finding
          but never un-skip it. */}
      <div className="shrink-0 pl-2">
        <label className="flex items-center gap-1.5 text-xs text-gray-600 dark:text-gray-300 cursor-pointer">
          <input
            type="checkbox"
            checked={Boolean(skipped)}
            onChange={(event) => onToggleSkip(finding.id, event.target.checked)}
            className="accent-accent-600 cursor-pointer"
          />
          Skip
        </label>
      </div>
    </div>
  );
}

const SCAN_TYPE_LABEL = {
  ai_model_deep_scan: "AI model deep scan",
  standard: "Standard scan",
};

const COMPARISON_GROUP_STYLE = {
  resolved: {
    label: "Fixed",
    box: "bg-green-50 dark:bg-green-500/10 border-green-200 dark:border-green-500/30",
    heading: "text-green-700 dark:text-green-400",
    swatch: "bg-green-500",
    legend: "Fixed since the previous scan",
  },
  stillPresent: {
    label: "Still Present",
    box: "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30",
    heading: "text-red-700 dark:text-red-400",
    swatch: "bg-red-500",
    legend: "Unresolved from the previous scan",
  },
  introduced: {
    label: "New",
    box: "bg-orange-50 dark:bg-orange-500/10 border-orange-200 dark:border-orange-500/30",
    heading: "text-orange-700 dark:text-orange-400",
    swatch: "bg-orange-500",
    legend: "Not present in the previous scan",
  },
  ambiguous: {
    label: "Ambiguous -- could not confidently match",
    box: "bg-gray-50 dark:bg-white/5 border-gray-200 dark:border-gray-700",
    heading: "text-gray-600 dark:text-gray-400",
    swatch: "bg-gray-400",
    legend: "Could not be confidently matched between scans",
  },
};

// Order matches the grid below (resolved, stillPresent, introduced, ambiguous) so the legend
// reads left-to-right/top-to-bottom in the same order the color-coded boxes appear in.
const COMPARISON_LEGEND_ORDER = ["resolved", "stillPresent", "introduced", "ambiguous"];

function ComparisonLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {COMPARISON_LEGEND_ORDER.map((groupKey) => {
        const style = COMPARISON_GROUP_STYLE[groupKey];
        return (
          <div key={groupKey} className="flex items-center gap-1.5" title={style.legend}>
            <span className={`inline-block w-2.5 h-2.5 rounded-full ${style.swatch}`} />
            <span className="text-xs text-gray-500 dark:text-gray-400">{style.label}</span>
          </div>
        );
      })}
    </div>
  );
}

function ComparisonFindingLine({ finding }) {
  const loc = finding.line ? `${finding.file}:${finding.line}` : finding.file;
  return (
    <p className="text-xs text-gray-700 dark:text-gray-300 py-1 border-b border-black/5 dark:border-white/5 last:border-0">
      <span className="font-mono text-gray-400 dark:text-gray-500">{loc}</span> -- {finding.message}
    </p>
  );
}

// One group of the "Compared to vN" section -- a plain array of findings for resolved/introduced/
// ambiguous, or an array of {previous, current} pairs for stillPresent (shows the CURRENT
// finding's own up-to-date location/message, since that's what a human reviewing right now cares
// about -- the previous half of the pair only matters for the matching logic itself).
function ComparisonGroup({ groupKey, items }) {
  if (!items || items.length === 0) return null;
  const style = COMPARISON_GROUP_STYLE[groupKey];
  return (
    <div className={`rounded-lg border px-3 py-2 ${style.box}`}>
      <h5 className={`text-xs font-bold uppercase tracking-wide mb-1 ${style.heading}`}>
        {style.label} ({items.length})
      </h5>
      {items.map((item, index) => (
        <ComparisonFindingLine key={index} finding={groupKey === "stillPresent" ? item.current : item} />
      ))}
    </div>
  );
}

// Renders a Security Agent report (the JSON artifact security_agent/agent.py's run() saves),
// grouped into Critical/Moderate/Warning per the severity taxonomy (severityTiers.js, mirroring
// the backend's severity.py). Rendered from ResultTab.jsx's `stage === "security"` branch instead
// of the generic ArtifactContentView, since a flat JSON tree doesn't serve this report's own
// "categorize and color-code" requirement the way a dedicated view does.
//
// Deliberately has NO "send to Coder Agent" action of its own -- the report now requires real
// human approval (agent.py's run() saves it PENDING, not auto-approved), and choosing to send it
// to the Coder Agent only happens through SecurityDecisionDialog.jsx, which opens right after
// approving. Letting this view trigger that same action directly would let a human bypass
// approval entirely, defeating the point of requiring it. "Re-run Scan" stays here since it's an
// independent, non-approval-gated action (just re-scanning, not accepting/escalating anything).
export default function SecurityReportView({ artifact, previousArtifact }) {
  const { data, isLoading, error } = useArtifactContent(artifact?.artifact_id ?? null);
  const report = data?.content_json;
  // Only fetched/rendered for an AI-model-deep-scan report (direct user decision) -- that's the
  // layer with real run-to-run scan variance; the deterministic scanners are already fully
  // reproducible, so a resolved/still-present/new comparison for them would rarely say anything
  // interesting. Fires in parallel with the main report fetch (previousArtifact's id is already
  // known from the versions list, not derived from `data` above), and safely no-ops (no fetch,
  // `data` stays undefined) when there is no previous version yet -- same disabled-query
  // convention already used elsewhere in this component.
  const previousReportQuery = useArtifactContent(previousArtifact?.artifact_id ?? null);
  const previousReport = previousReportQuery.data?.content_json;
  // Shared with ResultTab.jsx's Coder-Agent-approval auto-trigger (see SecurityAgentFlowContext's
  // own docstring) -- not a fresh useRunSecurityAgent(featureId) instance, so a scan started from
  // the approval popup shows its real progress here too, not just wherever it was started.
  const { runSecurity, securityDeepScanFlow } = useSecurityAgentFlowContext();
  const { deepScanStream, handleDeepScanStream, stopDeepScanStream, progress, phaseLabel, scanError, inFlightBatches } = securityDeepScanFlow;
  const anyScanPending = runSecurity.isPending || deepScanStream.isPending;
  const setFindingSkipped = useSetFindingSkippedMutation(artifact?.feature_id);
  function handleToggleSkip(findingId, skip) {
    if (!artifact) return;
    setFindingSkipped.mutate({ artifactId: artifact.artifact_id, finding_id: findingId, skipped: skip });
  }

  // No report exists yet (never scanned, or the feature has no generated code yet) -- Security
  // Agent has no revise() flow (a re-run IS the whole operation), so this empty-state action is
  // one of two real ways to trigger a first run (SecurityAgentChat's own empty-state button is
  // the other, sharing the same useSecurityAgentFlowContext() mutation -- see ResultTab.jsx's own
  // comment on why this branch renders regardless of whether an artifact exists).
  if (!artifact) {
    return (
      <div className="flex flex-col items-start gap-3">
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">
          No security scan has been run yet for this feature.
        </p>
        <ErrorBanner error={runSecurity.error} fallback="Failed to run the security scan." />
        <ErrorBanner error={scanError ? { message: scanError } : deepScanStream.error} fallback="Failed to run the AI model scan." />
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => runSecurity.mutate({})}
            disabled={anyScanPending}
            className="text-sm bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
          >
            {runSecurity.isPending ? "Scanning..." : "Run Security Scan"}
          </button>
          <button
            type="button"
            onClick={() => handleDeepScanStream({})}
            disabled={anyScanPending}
            title="Have the configured AI model read the real generated source code directly and look for vulnerabilities"
            className="text-sm bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
          >
            {deepScanStream.isPending ? "Scanning with model..." : "Scan with AI Model"}
          </button>
        </div>
        {deepScanStream.isPending && (
          <ScanProgressBar progress={progress} phaseLabel={phaseLabel} onStop={stopDeepScanStream} inFlightBatches={inFlightBatches} />
        )}
      </div>
    );
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading security report..." />;
  }

  if (error || !report) {
    return <ErrorBanner error={error} fallback="Failed to load the security report." />;
  }

  const findings = report.findings || [];
  const skippedFindingIds = artifact.skipped_finding_ids || [];
  const groups = groupFindingsByTier(findings);
  const hasFindings = findings.length > 0;
  const skippedSet = new Set(skippedFindingIds);
  const skippedCount = findings.filter((finding) => skippedSet.has(finding.id)).length;
  // Skip-aware (direct user request): drives both the banner below and the disabled state of
  // ResultTab.jsx's "Continue to QA Agent" button (same shared helper, same answer).
  const criticalStillBlocks = computeSecurityGateBlocksQa(findings, skippedFindingIds);
  const effectiveGateKey = report.gate_decision === "fail" && !criticalStillBlocks ? "skipped" : report.gate_decision;

  const showComparison = report.scan_type === "ai_model_deep_scan" && Boolean(previousArtifact) && Boolean(previousReport);
  const comparison = showComparison
    ? classifySecurityFindings(previousReport.findings || [], report.findings || [])
    : null;

  return (
    <div className="flex flex-col gap-5">
      <div className={`rounded-lg border px-4 py-3 flex items-center justify-between flex-wrap gap-3 ${GATE_BANNER_STYLE[effectiveGateKey] || ""}`}>
        <div className="min-w-0">
          <p className="text-sm font-bold">{GATE_BANNER_TEXT[effectiveGateKey] || "Scan complete."}</p>
          <p className="text-xs opacity-80 mt-0.5">
            {report.findings_count} finding(s) -- {report.critical_count} critical, {report.moderate_count} moderate,{" "}
            {report.warning_count} warning
            {skippedCount > 0 && ` -- ${skippedCount} skipped`}
          </p>
          <p className="text-xs opacity-70 mt-0.5">
            Scan type: {SCAN_TYPE_LABEL[report.scan_type] || "Standard scan"}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => runSecurity.mutate({})}
            disabled={anyScanPending}
            title="Re-scan the current code without going through the Coder Agent"
            className="text-sm bg-white dark:bg-white/10 hover:bg-gray-50 dark:hover:bg-white/20 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 disabled:opacity-50 font-semibold px-3 py-1.5 rounded-md"
          >
            {runSecurity.isPending ? "Scanning..." : "Re-run Scan"}
          </button>
          <button
            type="button"
            onClick={() => handleDeepScanStream({})}
            disabled={anyScanPending}
            title="Have the configured AI model read the real generated source code directly and look for vulnerabilities"
            className="text-sm bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
          >
            {deepScanStream.isPending ? "Scanning with model..." : "Scan with AI Model"}
          </button>
        </div>
      </div>

      {deepScanStream.isPending && (
        <ScanProgressBar progress={progress} phaseLabel={phaseLabel} onStop={stopDeepScanStream} />
      )}

      <ErrorBanner error={runSecurity.error} fallback="Failed to run the security scan." />
      <ErrorBanner error={scanError ? { message: scanError } : deepScanStream.error} fallback="Failed to run the AI model scan." />

      {!hasFindings ? (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">No findings from any scan layer.</p>
      ) : (
        <>
          {/* Direct user request #4: clearly distinguish Fixed/Open/Skipped. Open/Skipped are
              this report's own current findings (below); Fixed findings (present in the previous
              scan, gone from this one) appear in "Compared to vN" further down when available. */}
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-gray-500 dark:text-gray-400">
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-600 dark:bg-gray-300" />
              Open
            </div>
            <div className="flex items-center gap-1.5">
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-gray-300 dark:bg-gray-600" />
              Skipped -- accepted risk, excluded from Fix Vulnerabilities
            </div>
            {showComparison && <span>Fixed findings appear in "Compared to vN" below.</span>}
          </div>
          <ErrorBanner error={setFindingSkipped.error} fallback="Failed to update the finding's skip status." />
          {DISPLAY_TIERS.map((tier) =>
            groups[tier].length === 0 ? null : (
              <div key={tier}>
                <h4 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">
                  {TIER_HEADING[tier]} ({groups[tier].length})
                </h4>
                <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-3">
                  {groups[tier].map((finding) => (
                    <FindingRow
                      key={finding.id}
                      finding={finding}
                      skipped={skippedSet.has(finding.id)}
                      onToggleSkip={handleToggleSkip}
                    />
                  ))}
                </div>
              </div>
            )
          )}
        </>
      )}

      <div className="pt-4 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400 space-y-1">
        <p>
          <span className="font-semibold">Dependency scan:</span> npm audit exit code{" "}
          {report.dependency_scan?.audit_exit_code} (
          {report.dependency_scan?.audit_ran_offline ? "offline" : "online"})
        </p>
        <p>
          <span className="font-semibold">LLM review layer:</span> {report.llm_review_status}
        </p>
      </div>

      {comparison && (
        <div className="flex flex-col gap-2 pt-4 border-t border-gray-100 dark:border-gray-800">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <h4 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide">
              Compared to v{previousArtifact.version}
            </h4>
            <ComparisonLegend />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <ComparisonGroup groupKey="resolved" items={comparison.resolved} />
            <ComparisonGroup groupKey="stillPresent" items={comparison.stillPresent} />
            <ComparisonGroup groupKey="introduced" items={comparison.introduced} />
            <ComparisonGroup groupKey="ambiguous" items={comparison.ambiguous} />
          </div>
        </div>
      )}
    </div>
  );
}
