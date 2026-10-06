import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { useCoderAgentFlowContext } from "../workspace/CoderAgentFlowContext";
import { listGatingArtifactVersions } from "../../lib/deriveStageStatus";
import { SUGGESTION_CHIPS } from "../../lib/suggestionChips";
import { LiveReactionBubble, useElapsedLabel } from "../pipeline/RequirementConversationParts";
import { extractStreamingJsonStringField } from "../../lib/streamingJsonDisplay";
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

// Coder Agent's own dedicated chat, mirroring DomainAgentChat.jsx/ArchitectureAgentChat.jsx --
// live streaming, composer clears and an optimistic bubble appears immediately on submit, a Stop
// button while a stream is in flight. Two differences from Architecture's chat, both deliberate:
//   1. No exploration-mode toggle -- unlike Architecture's run_stream (which deliberately skips
//      its slower agentic tier for speed), Coder's revise_stream keeps the SAME agentic
//      exploration planner revise() always used, unconditionally. There is no reliability
//      trade-down to escape from here, so nothing to toggle.
//   2. A verification-result banner and a Stop-safety-net caveat, neither of which Domain/
//      Architecture need: a Coder Agent run can finish with real verification failures (unlike
//      Domain/Architecture's uniform "done, success" framing), and stopping mid coding-attempt
//      has a real, honest consequence worth stating plainly (see CoderAgent._code_with_retries_
//      stream's own docstring) rather than implying Stop always leaves zero trace.
export default function CoderAgentChat({
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
    runVerificationResult,
    runStreamError,
    runToolActivity,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
    revisionPhase,
    revisionPhaseStartedAt,
    revisionVerificationResult,
    revisionStreamError,
    revisionToolActivity,
  } = useCoderAgentFlowContext();

  const [comment, setComment] = useState("");
  const [pendingHumanReply, setPendingHumanReply] = useState(null);

  const versions = listGatingArtifactVersions("coder", allArtifacts);
  const hasOutput = versions.length > 0;

  const activeStream = hasOutput ? reviseStream : runStream;
  const streamedText = hasOutput ? revisionStreamedText : runStreamedText;
  const streamStarted = hasOutput ? revisionStreamStarted : runStreamStarted;
  const stopActiveStream = hasOutput ? stopReviseStream : stopRunStream;
  const activePhase = hasOutput ? revisionPhase : runPhase;
  const activePhaseStartedAt = hasOutput ? revisionPhaseStartedAt : runPhaseStartedAt;
  const verificationResult = hasOutput ? revisionVerificationResult : runVerificationResult;
  // Set from a real {"type": "error"} NDJSON line the backend sent -- unlike activeStream.error
  // (only ever set on a genuine promise rejection), this is the ONLY signal available when the
  // stream completed "successfully" from fetch's point of view but the agent itself crashed
  // mid-attempt. Without surfacing this, a real backend failure looked exactly like "the agent
  // did nothing" -- no error, no result, silence.
  const streamError = hasOutput ? revisionStreamError : runStreamError;
  // Real, live tool-call activity from the coding loop (list_dir/read_file/write_file/etc.), the
  // direct answer to "the agent must dynamically interact... in live" -- coding_loop.py has no
  // token-level output of its own, so this rolling log is the only real-time signal available
  // during the coding phase.
  const toolActivity = hasOutput ? revisionToolActivity : runToolActivity;

  // Shared by the composer's Send and a chat bubble's inline "Save & Send" -- both ultimately
  // fire the same stream (run vs. revise) with whatever text the human settled on. The human's
  // message appears in the chat feed immediately via pendingHumanReply -- the real "ask" bubble
  // only lands once the invalidated events query refetches (see useCoderAgentFlow.js's own
  // comment on why that refetch MUST be awaited).
  function submitCoderMessage(text) {
    if (activeStream.isPending) return;
    const trimmed = text.trim();

    setPendingHumanReply(trimmed);

    const call = hasOutput
      ? handleReviseStream({ revision_comment: trimmed, revised_by: user?.name || user?.email || "human_user" })
      : handleRunStream({ use_enhanced_srs_if_available: true, human_comment: trimmed });

    call.finally(() => setPendingHumanReply(null));
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (activeStream.isPending) return;
    const trimmed = comment.trim();
    if (!trimmed) return;

    setComment("");
    submitCoderMessage(trimmed);
  }

  // The composer otherwise requires non-empty text to submit -- this covers a human who wants
  // to kick off the first run without typing a note.
  function handleStartWithoutNotes() {
    if (activeStream.isPending) return;
    submitCoderMessage("");
  }

  const reactionText = extractStreamingJsonStringField(streamedText, "summary");
  const isAgentRunning = runningStage === "coder" || activeStream.isPending;
  // A real ticking timer (not a static, render-time-only label) -- revise_stream's planning phase
  // ("Exploring the codebase and planning your revision...") streams zero tokens by design (see
  // this component's file docstring) and can genuinely run for many minutes; without a visibly
  // ticking counter this reads as a hung UI, which is exactly what was reported.
  const elapsedLabel = useElapsedLabel(activePhaseStartedAt);
  const isStoppableCodingPhase = Boolean(activePhase?.phase?.startsWith("coding_attempt"));

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
              onEditSubmit={(text) => submitCoderMessage(text)}
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
            <LiveReactionBubble reactionText={reactionText} hasStarted={streamStarted} agentLabel="Coder Agent" />
            {(streamStarted || activePhase) && (
              <div className="flex items-center justify-between gap-2 bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30 rounded-lg px-3 py-2.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="relative flex h-2 w-2 flex-shrink-0">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-600" />
                  </span>
                  <p className="text-sm text-accent-800 dark:text-accent-300 font-semibold truncate">
                    {activePhase
                      ? `${activePhase.label}${elapsedLabel ? ` · ${elapsedLabel}` : ""}`
                      : `${hasOutput ? "Applying your requested change" : "Planning the implementation"} -- watch progress live in the Result panel →`}
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
            {toolActivity.length > 0 && (
              <div className="flex flex-col gap-0.5 px-1">
                {toolActivity.map((label, index) => (
                  <p
                    key={index}
                    className={`text-xs text-gray-500 dark:text-gray-400 truncate ${
                      index === toolActivity.length - 1 ? "font-medium text-gray-600 dark:text-gray-300" : ""
                    }`}
                  >
                    {label}
                  </p>
                ))}
              </div>
            )}
            {isStoppableCodingPhase && (
              <p className="text-xs text-gray-400 dark:text-gray-500 italic px-1">
                Stopping now commits whatever code has been written so far to the feature branch --
                safe (nothing merges or gets approved automatically), but unverified. Stopping during
                planning or verification never changes the workspace at all.
              </p>
            )}
          </>
        )}

        {!activeStream.isPending && verificationResult && (
          // "database_connection_saved" is a short-circuit result (see CoderAgent.revise_stream's
          // own docstring) -- nothing about the code changed, so it gets a neutral confirmation,
          // never the pass/fail coloring a real verification result gets.
          <div
            className={`rounded-lg px-3 py-2.5 text-sm font-semibold ${
              verificationResult.status === "database_connection_saved"
                ? "bg-accent-50 dark:bg-accent-500/10 text-accent-700 dark:text-accent-300 border border-accent-200 dark:border-accent-500/30"
                : verificationResult.verificationPassed
                ? "bg-green-50 dark:bg-green-500/10 text-green-700 dark:text-green-300 border border-green-200 dark:border-green-500/30"
                : "bg-amber-50 dark:bg-amber-500/10 text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-500/30"
            }`}
          >
            {verificationResult.status === "database_connection_saved"
              ? verificationResult.message
              : verificationResult.verificationPassed
              ? "Verification passed."
              : "Verification failed -- review before approving."}
          </div>
        )}

        <ErrorBanner
          error={activeStream.error || (streamError && { message: streamError })}
          fallback="Coder Agent request failed."
        />
      </div>

      <div className="flex-shrink-0 pt-1">
        {!hasOutput && !activeStream.isPending && (
          <div className="mb-2 flex flex-col gap-1.5">
            <button
              type="button"
              onClick={handleStartWithoutNotes}
              className="self-start text-xs font-semibold bg-white dark:bg-white/10 hover:bg-accent-100 dark:hover:bg-white/20 text-accent-700 dark:text-accent-300 border border-accent-300 dark:border-accent-500/40 rounded-full px-3 py-1"
            >
              Start Coder Agent now
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          {SUGGESTION_CHIPS.coder && (
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTION_CHIPS.coder.map((chip) => (
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
            pending={activeStream.isPending}
            onStop={stopActiveStream}
            selectedAgent={selectedAgent}
            onSelectAgent={selectAgent}
            isAgentRunning={isAgentRunning}
            placeholder={
              hasOutput ? "Ask Coder Agent for a change..." : "Tell Coder Agent what to build (optional)..."
            }
          />
        </form>
      </div>
    </div>
  );
}
