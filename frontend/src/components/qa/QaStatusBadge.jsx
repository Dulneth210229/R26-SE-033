// Every test case resolves to "passed" or "failed" only -- never "skipped" (direct user
// requirement, see qa_agent/agent.py's own module docstring). Same color-coding convention
// SeverityBadge.jsx/StatusBadge.jsx already established -- green for a real pass, red for a real
// fail.
const STYLES = {
  passed: "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
};

const LABELS = { passed: "Passed", failed: "Failed" };

// An unrecognized status string (should never happen once the backend never emits one) does NOT
// silently fall back to a quiet, forbidden "Skipped" style -- it renders as a loud red "Unknown"
// so a future regression is visible instead of silently reintroducing the exact bug this fix
// removed.
const UNKNOWN_STYLE = "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300";

export default function QaStatusBadge({ status }) {
  const style = STYLES[status] || UNKNOWN_STYLE;
  const label = LABELS[status] || `Unknown (${status})`;
  return (
    <span className={`inline-block px-2 py-1 text-xs font-semibold rounded-full ${style}`}>{label}</span>
  );
}
