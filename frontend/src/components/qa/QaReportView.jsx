import { useState } from "react";
import { useArtifactContent } from "../../hooks/useArtifacts";
import { useQaAgentFlowContext } from "../workspace/QaAgentFlowContext";
import { useCoderAgentFlowContext } from "../workspace/CoderAgentFlowContext";
import { buildQaRevisionComment } from "../../lib/qaReportToRevisionComment";
import QaStatusBadge from "./QaStatusBadge";
import ScanProgressBar from "../common/ScanProgressBar";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

const CATEGORIES = ["unit", "integration", "regression"];
const CATEGORY_HEADING = { unit: "Unit", integration: "Integration", regression: "Regression" };

function TestCaseRow({ tc }) {
  const loc = tc.target_function ? `${tc.target_file}::${tc.target_function}` : tc.target_file;
  return (
    <div className="flex items-start gap-3 py-2.5 border-b border-gray-100 dark:border-gray-800 last:border-0">
      <QaStatusBadge status={tc.status} />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-gray-800 dark:text-gray-200 font-semibold">{tc.name}</p>
        <p className="text-xs text-gray-400 dark:text-gray-500 font-mono mt-0.5">targets {loc}</p>
        {tc.inputs && (
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            <span className="font-semibold">Inputs:</span> {tc.inputs}
          </p>
        )}
        {tc.expected_behavior && (
          <p className="text-xs text-gray-500 dark:text-gray-400">
            <span className="font-semibold">Expected:</span> {tc.expected_behavior}
          </p>
        )}
        {tc.failure_message && (
          <pre className="text-xs text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-500/10 rounded p-2 mt-1.5 whitespace-pre-wrap overflow-x-auto">
            {tc.failure_message}
          </pre>
        )}
        {/* Direct user request: explain WHY a test actually failed, not just show Jest's raw
            assertion text -- LLM-synthesized, see qa_agent's own root-cause analysis pass. */}
        {tc.root_cause && (
          <p className="text-xs text-gray-600 dark:text-gray-400 mt-1">
            <span className="font-semibold">Root cause:</span> {tc.root_cause}
          </p>
        )}
        {tc.recommendation && (
          <p className="text-xs text-gray-600 dark:text-gray-400 mt-0.5">
            <span className="font-semibold">Recommendation:</span> {tc.recommendation}
          </p>
        )}
      </div>
    </div>
  );
}

// Renders a QA Agent report (the JSON artifact qa_agent/agent.py's run()/run_stream() saves),
// grouped into Unit/Integration/Regression, each test case showing both halves: what it was
// written to verify (target file/function, inputs, expected behavior) and what actually happened
// when it ran (real status, real failure message, and -- for a failure -- the synthesized root
// cause/recommendation). Mirrors SecurityReportView.jsx's shape, but QA stays auto-approved (no
// approval gate), so "Send Failing Tests to Coder Agent" is a direct, always-visible action here
// rather than living behind a decision popup.
//
// qaRunFlow comes from the shared QaAgentFlowContext (not its own instance) -- a QA run can also
// be triggered from the Security stage's own "Continue to QA Agent" button or QaAgentChat's
// empty-state action, so this view must observe the SAME stream's pending/progress state to show
// real, live progress regardless of which surface started it.
export default function QaReportView({ artifact }) {
  const { data, isLoading, error } = useArtifactContent(artifact?.artifact_id ?? null);
  const report = data?.content_json;
  const { qaRunFlow } = useQaAgentFlowContext();
  const { runStream, handleRunStream, stopRunStream, progress, phaseLabel, runError } = qaRunFlow;
  const { handleReviseStream, reviseStream } = useCoderAgentFlowContext();
  const [isSending, setIsSending] = useState(false);

  if (!artifact) {
    return (
      <div className="flex flex-col items-start gap-3 w-full">
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">
          No QA scan has been run yet for this feature.
        </p>
        <ErrorBanner error={runError ? { message: runError } : runStream.error} fallback="Failed to run the QA scan." />
        <button
          type="button"
          onClick={() => handleRunStream({})}
          disabled={runStream.isPending}
          className="text-sm bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
        >
          {runStream.isPending ? "Running..." : "Run QA Scan"}
        </button>
        {runStream.isPending && (
          <div className="w-full">
            <ScanProgressBar progress={progress} phaseLabel={phaseLabel} onStop={stopRunStream} />
          </div>
        )}
      </div>
    );
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading QA report..." />;
  }

  if (error || !report) {
    return <ErrorBanner error={error} fallback="Failed to load the QA report." />;
  }

  const testCases = report.test_cases || [];
  const hasFailures = testCases.some((tc) => tc.status === "failed");
  const byCategory = {};
  for (const category of CATEGORIES) {
    byCategory[category] = testCases.filter((tc) => tc.category === category);
  }
  // Real per-category pass/fail counts from the backend's own tests_by_category -- not
  // recomputed client-side, so this always matches exactly what the report actually says.
  const categoryCounts = report.tests_by_category || {};

  const bannerStyle = hasFailures
    ? "bg-red-50 dark:bg-red-500/10 border-red-200 dark:border-red-500/30 text-red-800 dark:text-red-300"
    : "bg-green-50 dark:bg-green-500/10 border-green-200 dark:border-green-500/30 text-green-800 dark:text-green-300";

  async function handleSendToCoder() {
    setIsSending(true);
    try {
      await handleReviseStream({
        revision_comment: buildQaRevisionComment(report),
        revised_by: "qa_agent_report",
      });
      handleRunStream({ human_comment: "Re-run after the Coder Agent's QA-driven revision." });
    } finally {
      setIsSending(false);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className={`rounded-lg border px-4 py-3 flex items-center justify-between flex-wrap gap-3 ${bannerStyle}`}>
        <div className="min-w-0">
          <p className="text-sm font-bold">
            {hasFailures ? "Some tests are failing -- review before proceeding." : "All tests passed."}
          </p>
          <p className="text-xs opacity-80 mt-0.5">
            {report.tests_generated} test(s) written -- {report.tests_passed} passed, {report.tests_failed} failed
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => handleRunStream({})}
            disabled={runStream.isPending || isSending}
            title="Re-write and re-run tests for the current code"
            className="text-sm bg-white dark:bg-white/10 hover:bg-gray-50 dark:hover:bg-white/20 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200 disabled:opacity-50 font-semibold px-3 py-1.5 rounded-md"
          >
            {runStream.isPending ? "Running..." : "Re-run QA Scan"}
          </button>
          {hasFailures && (
            <button
              type="button"
              onClick={handleSendToCoder}
              disabled={runStream.isPending || isSending || reviseStream.isPending}
              className="text-sm bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
            >
              {isSending || reviseStream.isPending ? "Sending..." : "Send Failing Tests to Coder Agent"}
            </button>
          )}
        </div>
      </div>

      {runStream.isPending && (
        <ScanProgressBar progress={progress} phaseLabel={phaseLabel} onStop={stopRunStream} />
      )}

      <ErrorBanner
        error={runError ? { message: runError } : runStream.error || reviseStream.error}
        fallback="Failed to run the QA scan."
      />

      {report.environment_failure && (
        <div className="rounded-lg border px-4 py-3 bg-amber-50 dark:bg-amber-500/10 border-amber-200 dark:border-amber-500/30 text-amber-800 dark:text-amber-300">
          <p className="text-sm font-bold">The test run itself could not execute</p>
          <p className="text-xs opacity-80 mt-0.5">{report.environment_failure.reason}</p>
        </div>
      )}

      {testCases.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">No test cases were generated.</p>
      ) : (
        CATEGORIES.map((category) => {
          const items = byCategory[category];
          if (items.length === 0) return null;
          const counts = categoryCounts[category];
          return (
            <div key={category}>
              <h4 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">
                {CATEGORY_HEADING[category]} ({items.length})
                {counts && (
                  <span className="normal-case font-normal text-gray-400 dark:text-gray-500">
                    {" -- "}
                    {counts.passed} passed, {counts.failed} failed
                  </span>
                )}
              </h4>
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 rounded-lg px-3">
                {items.map((tc, i) => (
                  <TestCaseRow key={`${tc.test_file}-${tc.name}-${i}`} tc={tc} />
                ))}
              </div>
            </div>
          );
        })
      )}

      {report.out_of_scope_modules?.length > 0 && (
        <div className="pt-4 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400">
          <p className="font-semibold mb-1">Out of scope for this pass (no DOM renderer):</p>
          <ul className="list-disc list-inside space-y-0.5">
            {report.out_of_scope_modules.map((path) => (
              <li key={path} className="font-mono">{path}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Direct user request: surface this rather than hide it -- if the whole Jest run crashed
          before producing any per-test results, this is the only place the real reason shows up. */}
      {report.raw_stderr && (
        <div className="pt-4 border-t border-gray-100 dark:border-gray-800 text-xs text-gray-500 dark:text-gray-400">
          <p className="font-semibold mb-1">Test runner output (tail):</p>
          <pre className="bg-gray-50 dark:bg-white/5 border border-gray-200 dark:border-gray-800 rounded p-2 whitespace-pre-wrap overflow-x-auto font-mono">
            {report.raw_stderr.slice(-2000)}
          </pre>
        </div>
      )}
    </div>
  );
}
