import { useState } from "react";
import { useArchitectureAgentFlowContext } from "../workspace/ArchitectureAgentFlowContext";
import ErrorBanner from "../common/ErrorBanner";

// Uses the shared plainRunMutation from ArchitectureAgentFlowContext (not its own independent
// mutation instance) specifically so this form's own pending state is visible to -- and shares one
// real in-flight request with -- every other Architecture Agent trigger surface (the chat's quick
// -action button/composer, and the Enhanced-SRS-approval auto-continue in ResultTab.jsx). Two
// separate mutation instances for this same action previously let a human fire both a plain
// /architecture/run request (from this form) and a streaming /architecture/run/stream request
// (from the chat's auto-start) for one feature's first run, producing two artifact versions with
// identical content -- see useArchitectureAgentFlow.js's own comment on plainRunMutation.
export default function ArchitectureRunForm() {
  const [useEnhancedSrs, setUseEnhancedSrs] = useState(true);
  const [architectureNotes, setArchitectureNotes] = useState("");
  const [humanComment, setHumanComment] = useState("");
  const { plainRunMutation: runArchitecture, handlePlainRun, runStream } = useArchitectureAgentFlowContext();
  // A real, separate streaming run (e.g. fired by the Enhanced-SRS-approval auto-continue in
  // ResultTab.jsx while this form happened to already be open) is a second real in-flight
  // request for the exact same action -- block submitting this form on top of it too, not just
  // on this form's own prior submission.
  const anotherRunAlreadyInFlight = runStream.isPending;

  async function handleSubmit(event) {
    event.preventDefault();
    if (runArchitecture.isPending || anotherRunAlreadyInFlight) return;
    await handlePlainRun({
      use_enhanced_srs_if_available: useEnhancedSrs,
      architecture_notes: architectureNotes.trim() || null,
      human_comment: humanComment.trim() || null,
    });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4 bg-white dark:bg-gray-900 p-6 rounded-lg shadow-sm border border-gray-200 dark:border-gray-800">
      <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">Run Architecture Agent</h3>

      <ErrorBanner error={runArchitecture.error} fallback="Architecture Agent run failed." />

      {anotherRunAlreadyInFlight && !runArchitecture.isPending && (
        <p className="text-xs text-amber-700 dark:text-amber-400 italic">
          Architecture Agent is already running for this feature -- wait for it to finish before starting another run.
        </p>
      )}

      <label className="flex items-center gap-2 text-sm text-gray-900 dark:text-gray-200">
        <input
          type="checkbox"
          checked={useEnhancedSrs}
          onChange={(e) => setUseEnhancedSrs(e.target.checked)}
        />
        Use approved Enhanced SRS if available
      </label>

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Architecture Notes (optional)</label>
        <textarea
          value={architectureNotes}
          onChange={(e) => setArchitectureNotes(e.target.value)}
          rows={2}
          placeholder="Keep it simple: a single Item resource with standard CRUD REST endpoints."
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <div>
        <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Human Comment (optional)</label>
        <textarea
          value={humanComment}
          onChange={(e) => setHumanComment(e.target.value)}
          rows={2}
          className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
        />
      </div>

      <button
        type="submit"
        disabled={runArchitecture.isPending || anotherRunAlreadyInFlight}
        className="self-start bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
      >
        {runArchitecture.isPending ? "Generating Architecture Plan..." : "Run Architecture Agent"}
      </button>
    </form>
  );
}
