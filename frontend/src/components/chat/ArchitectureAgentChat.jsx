import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { useArchitectureAgentFlowContext } from "../workspace/ArchitectureAgentFlowContext";
import { listGatingArtifactVersions } from "../../lib/deriveStageStatus";
import { SUGGESTION_CHIPS } from "../../lib/suggestionChips";
import { LiveReactionBubble, useElapsedLabel } from "../pipeline/RequirementConversationParts";
import { extractStreamingJsonStringField } from "../../lib/streamingJsonDisplay";
import ArchitectureRunForm from "../pipeline/ArchitectureRunForm";
import ChatBubble from "./ChatBubble";
import ChatComposerBox from "./ChatComposerBox";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

function ChatHeader({ feature, runningStage }) {
  return (
    <div className="flex items-center justify-between gap-2 flex-shrink-0 pb-3 border-b border-gray-100 dark:border-gray-800">
      <div className="min-w-0">
        <h2 className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate">{feature?.feature_name || "..."}</h2>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">{feature?.feature_description}</p>
      </div>
      {runningStage && (
        <div className="flex items-center gap-1.5 bg-accent-50 dark:bg-accent-500/10 text-accent-700 dark:text-accent-300 text-xs font-semibold rounded-full px-2.5 py-1 flex-shrink-0">
          <span className="relative flex h-1.5 w-1.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-500" />
          </span>
          Agent running
        </div>
      )}
    </div>
  );
}

// Architecture Agent's own dedicated chat, mirroring DomainAgentChat.jsx -- live token-by-token
// plan streaming, composer clears and an optimistic bubble appears immediately on submit, a Stop
// button while a stream is in flight. Two differences from Domain's chat, both deliberate:
//   1. No "/" document-mention picker or proactive "add domain knowledge?" prompt -- Architecture
//      Agent has nothing analogous to guide with before its first run (it either auto-starts
//      after Enhanced SRS approval -- see ResultTab.jsx's APPROVE_CONTINUATION_BY_STAGE -- or a
//      human can just type a note here).
//   2. Carries the "deep exploration mode" escape hatch (ArchitectureRunForm, calling the
//      non-streaming /architecture/run, which still uses the full agentic, tool-calling,
//      project-aware exploration tier this chat's own live stream deliberately skips for speed --
//      see ArchitectureAgent.run_stream's own docstring for why skipping is a precondition for
//      streaming existing at all, not just a latency choice). Relabeled from ChatPanel's old
//      "Prefer a detailed form instead?" to name the actual trade-off plainly.
export default function ArchitectureAgentChat({
  featureId,
  feature,
  runningStage,
  selectedAgent,
  selectAgent,
  timeline,
  allArtifacts,
  onViewArtifact,
  isLoadingTimeline,
}) {
  const { user } = useAuth();
  const {
    runStream,
    handleRunStream,
    stopRunStream,
    runStreamedText,
    runStreamStarted,
    runPhase,
    runPhaseStartedAt,
    runStreamError,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
    revisionPhase,
    revisionPhaseStartedAt,
    revisionStreamError,
    plainRunMutation,
  } = useArchitectureAgentFlowContext();

  const [comment, setComment] = useState("");
  const [pendingHumanReply, setPendingHumanReply] = useState(null);
  const [showExplorationForm, setShowExplorationForm] = useState(false);

  const versions = listGatingArtifactVersions("architecture", allArtifacts);
  const hasOutput = versions.length > 0;

  const activeStream = hasOutput ? reviseStream : runStream;
  const streamedText = hasOutput ? revisionStreamedText : runStreamedText;
  const streamStarted = hasOutput ? revisionStreamStarted : runStreamStarted;
  const stopActiveStream = hasOutput ? stopReviseStream : stopRunStream;
  // Set from a real {"type": "error"} NDJSON line -- unlike activeStream.error (only set on a
  // genuine promise rejection), this is the only signal available when the stream completed
  // "successfully" from fetch's point of view but the agent itself crashed mid-attempt.
  const streamError = hasOutput ? revisionStreamError : runStreamError;
  const activePhase = hasOutput ? revisionPhase : runPhase;
  const activePhaseStartedAt = hasOutput ? revisionPhaseStartedAt : runPhaseStartedAt;

  // True whenever ANY real Architecture Agent request is in flight for this feature -- the
  // streaming run/revise (activeStream) OR the "deep exploration mode" form's plain, non-
  // streaming run (plainRunMutation, only ever relevant pre-hasOutput). Gating every trigger
  // surface on this combined flag, not just activeStream.isPending, is what actually prevents the
  // double-fire bug this file's plainRunMutation comment describes -- activeStream.isPending alone
  // was blind to the form's own separate request.
  const anyRunPending = activeStream.isPending || (!hasOutput && plainRunMutation.isPending);

  // Shared by the composer's Send and a chat bubble's inline "Save & Send" -- both ultimately
  // fire the same stream (run vs. revise) with whatever text the human settled on. The human's
  // message appears in the chat feed immediately via pendingHumanReply -- the real "ask" bubble
  // only lands once the invalidated events query refetches (see useArchitectureAgentFlow.js's own
  // comment on why that refetch MUST be awaited).
  function submitArchitectureMessage(text) {
    if (anyRunPending) return;
    const trimmed = text.trim();

    setPendingHumanReply(trimmed);

    const call = hasOutput
      ? handleReviseStream({ revision_comment: trimmed, revised_by: user?.name || user?.email || "human_user" })
      : handleRunStream({ use_enhanced_srs_if_available: true, architecture_notes: null, human_comment: trimmed });

    call.finally(() => setPendingHumanReply(null));
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (anyRunPending) return;
    const trimmed = comment.trim();
    if (!trimmed) return;

    setComment("");
    submitArchitectureMessage(trimmed);
  }

  // The primary way Architecture Agent's first run actually starts is the auto-continue flow
  // from approving an Enhanced SRS (ResultTab.jsx), which calls handleRunStream directly and
  // never touches this chat at all. This button exists for the secondary path -- a human who
  // navigates here directly (or wants to re-run without typing a note) -- since the composer
  // otherwise requires non-empty text to submit.
  function handleStartWithoutNotes() {
    if (anyRunPending) return;
    submitArchitectureMessage("");
  }

  const reactionText = extractStreamingJsonStringField(streamedText, "architecture_rationale");
  const isAgentRunning = runningStage === "architecture" || anyRunPending;
  // Real ticking timer, not a static render-time-only label -- same fix as CoderAgentChat's
  // identical pattern, for the same reason (a long, token-free phase otherwise reads as stuck).
  const elapsedLabel = useElapsedLabel(activePhaseStartedAt);

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-4">
      <ChatHeader feature={feature} runningStage={runningStage} />

      <div className="flex-1 min-h-0 overflow-y-auto py-3 flex flex-col gap-3">
        {isLoadingTimeline ? (
          <LoadingSpinner label="Loading activity..." />
        ) : timeline.length === 0 && pendingHumanReply === null && !activeStream.isPending ? (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">No activity yet. Say something below to get started.</p>
        ) : (
          timeline.map((item, i) => (
            <ChatBubble
              key={i}
              item={item}
              allArtifacts={allArtifacts}
              onViewArtifact={onViewArtifact}
              onEditSubmit={(text) => submitArchitectureMessage(text)}
              isEditPending={activeStream.isPending}
            />
          ))
        )}

        {pendingHumanReply !== null && (
          <div className="flex justify-end">
            <div className="max-w-[85%] bg-accent-600 dark:bg-accent-500 text-white rounded-lg rounded-tr-sm px-3 py-2 text-sm">
              <p className="text-xs text-accent-200 dark:text-accent-100/80 mb-0.5">You</p>
              <p className="whitespace-pre-wrap break-words">
                {pendingHumanReply || (
                  <span className="italic text-accent-200 dark:text-accent-100/80">(no comment provided)</span>
                )}
              </p>
            </div>
          </div>
        )}

        {activeStream.isPending && (
          <>
            <LiveReactionBubble reactionText={reactionText} hasStarted={streamStarted} agentLabel="Architecture Agent" />
            {streamStarted && (
              <div className="flex items-center justify-between gap-2 bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30 rounded-lg px-3 py-2.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="relative flex h-2 w-2 flex-shrink-0">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-600" />
                  </span>
                  <p className="text-sm text-accent-800 dark:text-accent-300 font-semibold truncate">
                    {activePhase
                      ? `${activePhase.label}${elapsedLabel ? ` · ${elapsedLabel}` : ""}`
                      : `${hasOutput ? "Applying your requested change" : "Drafting the architecture plan"} -- watch progress live in the Result panel →`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={stopActiveStream}
                  className="text-xs font-semibold text-accent-700 dark:text-accent-300 hover:text-accent-900 dark:hover:text-accent-100 underline flex-shrink-0"
                >
                  Stop
                </button>
              </div>
            )}
          </>
        )}

        <ErrorBanner
          error={activeStream.error || (streamError && { message: streamError })}
          fallback="Architecture Agent request failed."
        />
      </div>

      <div className="flex-shrink-0 pt-1">
        {!hasOutput && (
          <div className="mb-2 flex flex-col gap-1.5">
            {/* Hidden once ANY run is in flight (streaming or the form's own plain request) --
                stops a human from firing a second, real request while one is already running.
                The form itself (below) deliberately stays visible even while pending, so its own
                in-progress state ("Generating Architecture Plan...") is still shown, not hidden. */}
            {!anyRunPending && (
              <>
                <button
                  type="button"
                  onClick={handleStartWithoutNotes}
                  className="self-start text-xs font-semibold bg-white dark:bg-white/10 hover:bg-accent-100 dark:hover:bg-white/20 text-accent-700 dark:text-accent-300 border border-accent-300 dark:border-accent-500/40 rounded-full px-3 py-1"
                >
                  Start Architecture Agent now
                </button>
                <button
                  type="button"
                  onClick={() => setShowExplorationForm((v) => !v)}
                  className="self-start text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold underline"
                >
                  {showExplorationForm
                    ? "Use the quick chat box instead"
                    : "Use deep exploration mode -- slower, reads previous features' approved plans first"}
                </button>
              </>
            )}
            {showExplorationForm && (
              <div className="mt-2">
                <ArchitectureRunForm />
              </div>
            )}
          </div>
        )}

        {!(!hasOutput && showExplorationForm) && (
          <form onSubmit={handleSubmit} className="flex flex-col gap-2">
            {SUGGESTION_CHIPS.architecture && (
              <div className="flex flex-wrap gap-1.5">
                {SUGGESTION_CHIPS.architecture.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => setComment(chip)}
                    className="text-xs bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20 text-gray-700 dark:text-gray-300 rounded-full px-2.5 py-1"
                  >
                    {chip}
                  </button>
                ))}
              </div>
            )}

            <ChatComposerBox
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              disabled={false}
              pending={anyRunPending}
              onStop={stopActiveStream}
              selectedAgent={selectedAgent}
              onSelectAgent={selectAgent}
              isAgentRunning={isAgentRunning}
              placeholder={
                hasOutput ? "Ask Architecture Agent for a change..." : "Tell Architecture Agent what to build (optional)..."
              }
            />
          </form>
        )}
      </div>
    </div>
  );
}
