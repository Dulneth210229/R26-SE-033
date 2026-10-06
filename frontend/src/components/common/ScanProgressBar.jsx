// Real filenames can add up fast once several batches run concurrently (up to
// DEEP_SCAN_MAX_CONCURRENT_BATCHES batches at once, each covering several files) -- capped
// separately from any other "rolling activity log" convention in this app, since this is a
// UNION of everything currently in flight, not a capped trailing history.
const MAX_VISIBLE_IN_FLIGHT_FILES = 10;

// A real, live percentage progress bar -- originally built for Security Agent's AI-model deep
// scan, now shared with QA Agent's own streamed test-generation run (see useQaRunStream.js) --
// nothing in this component is Security- or QA-specific, it's a generic phase-label + percent +
// optional in-flight-files bar. Kept as a small, separate component (rather than folded into a
// report view) since it's rendered from both a stage's empty-state and populated-state branches.
// Deliberately NOT the existing LiveGenerationView (isFinalizing mode, used elsewhere for a
// non-streamable tail) -- that swaps the ENTIRE view away, which would hide surrounding controls
// (e.g. Security's version dropdown and action buttons); this renders inline, alongside
// everything else, instead.
//
// `inFlightBatches` (direct user request, Security Agent: show which files are being analyzed
// right now) is an object keyed by batch_index -> files[] (see useSecurityDeepScanFlow.js's own
// docstring for why this shape, not a rolling log) -- rendered here as the flattened union of
// every batch currently in flight, since with real concurrency several batches' files are
// genuinely "being analyzed" at the same moment, not just one. Optional -- QA Agent's own
// sequential run stream doesn't pass this at all, relying on `phaseLabel` alone to name the
// current target.
export default function ScanProgressBar({ progress, phaseLabel, onStop, inFlightBatches }) {
  const percent = progress?.percent ?? 0;
  const inFlightFiles = Object.values(inFlightBatches || {}).flat();
  const visibleFiles = inFlightFiles.slice(0, MAX_VISIBLE_IN_FLIGHT_FILES);
  const hiddenFileCount = inFlightFiles.length - visibleFiles.length;

  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-indigo-200 dark:border-indigo-500/30 bg-indigo-50 dark:bg-indigo-500/10 px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-indigo-800 dark:text-indigo-300">
          {phaseLabel || "Starting AI model scan..."}
        </p>
        <div className="flex items-center gap-3 flex-shrink-0">
          {progress && (
            <span className="text-xs font-mono text-indigo-700 dark:text-indigo-400">{percent}%</span>
          )}
          <button
            type="button"
            onClick={onStop}
            className="text-xs font-semibold text-red-600 dark:text-red-400 hover:text-red-800 dark:hover:text-red-300"
          >
            Stop Scan
          </button>
        </div>
      </div>
      <div className="h-2 w-full bg-indigo-200 dark:bg-indigo-500/20 rounded-full overflow-hidden">
        <div
          className="h-full bg-indigo-600 dark:bg-indigo-400 rounded-full transition-all duration-300"
          style={{ width: `${progress ? percent : 8}%` }}
        />
      </div>
      {visibleFiles.length > 0 && (
        <p className="text-xs text-indigo-700 dark:text-indigo-400 truncate">
          <span className="font-semibold">Analyzing:</span> {visibleFiles.join(", ")}
          {hiddenFileCount > 0 && ` +${hiddenFileCount} more`}
        </p>
      )}
    </div>
  );
}
