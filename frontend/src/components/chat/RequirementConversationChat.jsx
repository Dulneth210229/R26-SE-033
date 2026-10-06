import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { useRequirementConversationFlowContext } from "../workspace/RequirementConversationFlowContext";
import { AgentTurnBubble, HumanBubble, LiveReactionBubble, QualityGateBanner } from "../pipeline/RequirementConversationParts";
import RequirementRunForm from "../pipeline/RequirementRunForm";
import ChatBubble from "./ChatBubble";
import ChatComposerBox from "./ChatComposerBox";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";
import { extractStreamingJsonStringField } from "../../lib/streamingJsonDisplay";

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

// The Requirement Agent's ENTIRE chat, pre-SRS gap-filling AND post-SRS revision, as ONE
// continuous conversation -- previously two separate components (RequirementConversationChat +
// RequirementRevisionChat) that ChatPanel hard-swapped between the instant an SRS artifact
// existed, which (even after an earlier fix that added a collapsed "show old conversation"
// toggle inside the post-SRS component) still read as "the chat disappeared and a different,
// sparser one took its place" -- direct, repeated user feedback: this must feel like ONE
// ChatGPT/Claude-style conversation, never a swap. `conversation.turn_history` (the pre-SRS Q&A)
// is now ALWAYS rendered in full, followed immediately by `timeline` (the post-SRS revision
// activity) once it exists -- one continuous scroll, no collapsing, no separate card chrome.
// `hasOutput` (artifact-existence-based, the same mode-switch signal every other agent's chat
// already uses) decides which composer/banners are active, not `conversation.status` -- there's a
// real, narrow desync window between the two right after confirm succeeds.
export default function RequirementConversationChat({
  featureId,
  feature,
  runningStage,
  selectedAgent,
  selectAgent,
  hasOutput,
  timeline,
  allArtifacts,
  onViewArtifact,
  isLoadingTimeline,
}) {
  const { user } = useAuth();
  const {
    conversation,
    isLoading,
    start,
    respondStream,
    handleReplyStream,
    stopReplyStream,
    replyStreamedText,
    replyStreamStarted,
    editTurnStream,
    handleEditTurnStream,
    stopEditTurnStream,
    editStreamedText,
    editStreamStarted,
    reset,
    confirmStream,
    handleConfirm,
    stopConfirmStream,
    isGenerating,
    isConfirmed,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
  } = useRequirementConversationFlowContext();

  // Pre-SRS composer state.
  const [replyText, setReplyText] = useState("");
  const [showManualForm, setShowManualForm] = useState(false);
  // The reply is optimistically shown as a real chat bubble the instant it's sent -- the actual
  // turn (with the agent's reaction+questions) only lands in conversation.turn_history once the
  // whole stream finishes, and without this the human's own message would appear to vanish for
  // however long generation takes.
  const [pendingHumanReply, setPendingHumanReply] = useState(null);
  // Same idea for an edited-and-resent turn: { turnIndex, pendingReply } while a streamed
  // regeneration from that turn is in flight, else null. Editing discards this turn and every
  // turn after it (see editTurnStream's own docstring), so while this is set, later turns are
  // hidden entirely rather than briefly shown then yanked away once the stream finishes.
  const [editingContext, setEditingContext] = useState(null);

  // Post-SRS composer state.
  const [revisionComment, setRevisionComment] = useState("");
  const [pendingRevisionReply, setPendingRevisionReply] = useState(null);

  function handleEditTurn(turnIndex, newReply) {
    setEditingContext({ turnIndex, pendingReply: newReply });
    handleEditTurnStream({ turnIndex, reply: newReply }).finally(() => setEditingContext(null));
  }

  const isReplying = respondStream.isPending;

  function handleReplySubmit(event) {
    event.preventDefault();
    if (isReplying || !conversation) return;
    const trimmed = replyText.trim();
    if (!trimmed) return;

    setReplyText("");

    // Live, token-by-token reply (ChatGPT/Claude-style) -- the agent's reaction+questions "type"
    // in as they're generated instead of appearing all at once after a blocking wait.
    setPendingHumanReply(trimmed);
    handleReplyStream({ reply: trimmed })
      .then((result) => {
        // The whole turn (human_reply + the agent's reaction/questions) is only ever persisted
        // atomically by the stream's "done" event -- stopping partway through means NOTHING was
        // saved server-side, unlike ChatGPT/Claude where the human's own message is durable the
        // instant it's sent. Give the typed text back to the composer instead of silently losing
        // it, so stopping never costs the human their own words.
        if (result?.aborted) setReplyText(trimmed);
      })
      .finally(() => setPendingHumanReply(null));
  }

  // Shared by the post-SRS composer's Send and a ChatBubble's inline "Save & Send" (see
  // ChatBubble's own docstring for why editing an old ask bubble resubmits rather than rewriting
  // history).
  function submitRevision(text) {
    if (reviseStream.isPending) return;
    const trimmed = text.trim();
    if (!trimmed) return;

    setPendingRevisionReply(trimmed);
    handleReviseStream({ revision_comment: trimmed, revised_by: user?.name || user?.email || "human_user" }).finally(() =>
      setPendingRevisionReply(null)
    );
  }

  function handleRevisionSubmit(event) {
    event.preventDefault();
    const trimmed = revisionComment.trim();
    if (!trimmed) return;
    setRevisionComment("");
    submitRevision(trimmed);
  }

  const isAgentRunning =
    runningStage === "requirement" || isReplying || editTurnStream.isPending || reviseStream.isPending;
  const showPreSrsComposer = !hasOutput && conversation && !isConfirmed && !isGenerating && !showManualForm;
  // Editing a past reply discards it and everything after it, then regenerates -- only safe while
  // the conversation is still in the gathering phase, same as replying normally, and NOT while an
  // SRS confirm-generation is already in flight (that would discard the very state it's generating
  // from). Kept gated on !isGenerating, unlike the composer below.
  const canEditTurns = showPreSrsComposer;
  // A real, reported bug: the composer used to share showPreSrsComposer's own !isGenerating term,
  // which UNMOUNTED the entire input box the instant SRS confirm-generation started (LiveGenerationView
  // in the separate Result panel is not what did this -- see RequirementSrsOutputPanel.jsx). Fixed by
  // dropping that one term here -- the composer now stays mounted and merely disables itself + offers
  // a Stop control during generation, exactly mirroring how the reply-stream phase (isReplying) has
  // always behaved.
  //
  // Direct user request: the composer must be visible ALONGSIDE the "Start Conversation" button
  // too, not appear only once a conversation already exists -- previously gated on `conversation`
  // being truthy, which meant nothing but the button rendered at all beforehand. Now mounted the
  // whole time this stage is in its pre-SRS phase (including the initial loading/not-yet-started
  // state); ChatComposerBox's own `disabled` prop (set below) is what actually keeps it inert
  // until start.mutate() succeeds and `conversation` exists.
  const canShowPreSrsComposer = !hasOutput && !isConfirmed && !showManualForm;
  const revisionReactionText = extractStreamingJsonStringField(revisionStreamedText, "revision_summary");

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-4">
      <ChatHeader feature={feature} runningStage={runningStage} />

      <div className="flex-1 min-h-0 overflow-y-auto py-3 flex flex-col gap-3">
        {isLoading ? (
          <LoadingSpinner label="Loading conversation..." />
        ) : !conversation ? (
          <div className="flex flex-col gap-3 max-w-xl">
            <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100">Talk to the Requirement Agent</h3>
            <p className="text-xs text-gray-400 dark:text-gray-500 -mt-2">
              Start from your rough description -- the agent will ask what's missing, prioritizing
              what matters most for a correct architecture and design. Click "Start Conversation"
              below to begin.
            </p>
          </div>
        ) : showManualForm && !hasOutput ? (
          <RequirementRunForm featureId={featureId} feature={feature} />
        ) : (
          <>
            {conversation.turn_history.map((turn) => {
              // Once a turn is being edited, every turn after it is about to be discarded (see
              // handleEditTurn) -- hide them immediately rather than showing them for a moment
              // and then having them vanish once the regeneration actually lands.
              if (editingContext && turn.turn_index > editingContext.turnIndex) return null;

              const isBeingEdited = editingContext?.turnIndex === turn.turn_index;

              return (
                <div key={turn.turn_index} className="flex flex-col gap-3">
                  {isBeingEdited ? (
                    <>
                      <HumanBubble text={editingContext.pendingReply} />
                      <LiveReactionBubble
                        reactionText={extractStreamingJsonStringField(editStreamedText, "reaction")}
                        hasStarted={editStreamStarted}
                      />
                      <button
                        type="button"
                        onClick={stopEditTurnStream}
                        className="self-start text-xs font-semibold text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 underline"
                      >
                        Stop
                      </button>
                    </>
                  ) : (
                    <>
                      {turn.human_reply && (
                        <HumanBubble
                          text={turn.human_reply}
                          onEdit={canEditTurns ? (newReply) => handleEditTurn(turn.turn_index, newReply) : null}
                          isEditPending={editTurnStream.isPending}
                        />
                      )}
                      <AgentTurnBubble turn={turn} />
                    </>
                  )}
                </div>
              );
            })}

            {!hasOutput && pendingHumanReply && <HumanBubble text={pendingHumanReply} />}
            {!hasOutput && respondStream.isPending && (
              <LiveReactionBubble
                reactionText={extractStreamingJsonStringField(replyStreamedText, "reaction")}
                hasStarted={replyStreamStarted}
              />
            )}

            <ErrorBanner error={editTurnStream.error} fallback="Failed to save your edit." />

            {!hasOutput && isConfirmed ? (
              <div className="bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 rounded-lg px-3 py-2.5">
                <p className="text-sm text-green-800 dark:text-green-300 font-semibold">
                  Confirmed -- the final SRS has been generated and is awaiting approval in the Result panel.
                </p>
              </div>
            ) : !hasOutput && isGenerating ? (
              <div className="flex items-center justify-between gap-2 bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30 rounded-lg px-3 py-2.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="relative flex h-2 w-2 flex-shrink-0">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-600" />
                  </span>
                  <p className="text-sm text-accent-800 dark:text-accent-300 font-semibold truncate">
                    Generating the final SRS -- watch it stream live in the Result panel &rarr;
                  </p>
                </div>
                {confirmStream.isPending && (
                  <button
                    type="button"
                    onClick={stopConfirmStream}
                    className="text-xs font-semibold text-accent-700 dark:text-accent-300 hover:text-accent-900 dark:hover:text-accent-100 underline flex-shrink-0"
                  >
                    Stop
                  </button>
                )}
              </div>
            ) : !hasOutput ? (
              <>
                <ErrorBanner error={respondStream.error} fallback="Failed to send your reply." />
                <ErrorBanner error={confirmStream.error} fallback="Failed to generate the SRS." />
                <QualityGateBanner
                  qualityGate={conversation.quality_gate}
                  onConfirm={handleConfirm}
                  isConfirming={isGenerating}
                  disabled={isReplying}
                />
              </>
            ) : null}

            {/* Post-SRS revision activity continues the SAME scroll immediately below the
                original conversation -- one continuous thread, never a separate block. */}
            {hasOutput && (
              <>
                {isLoadingTimeline ? (
                  <LoadingSpinner label="Loading activity..." />
                ) : timeline.length === 0 && !pendingRevisionReply ? (
                  <p className="text-sm text-gray-400 dark:text-gray-500 italic">
                    No revision activity yet. Ask for a change below.
                  </p>
                ) : (
                  timeline.map((item, i) => (
                    <ChatBubble
                      key={i}
                      item={item}
                      allArtifacts={allArtifacts}
                      onViewArtifact={onViewArtifact}
                      onEditSubmit={submitRevision}
                      isEditPending={reviseStream.isPending}
                    />
                  ))
                )}

                {pendingRevisionReply && (
                  <div className="flex justify-end">
                    <div className="max-w-[85%] bg-accent-600 dark:bg-accent-500 text-white rounded-lg rounded-tr-sm px-3 py-2 text-sm">
                      <p className="text-xs text-accent-200 dark:text-accent-100/80 mb-0.5">You</p>
                      <p className="whitespace-pre-wrap break-words">{pendingRevisionReply}</p>
                    </div>
                  </div>
                )}

                {reviseStream.isPending && (
                  <>
                    <LiveReactionBubble reactionText={revisionReactionText} hasStarted={revisionStreamStarted} />
                    {revisionStreamStarted && (
                      <div className="flex items-center justify-between gap-2 bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30 rounded-lg px-3 py-2.5">
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="relative flex h-2 w-2 flex-shrink-0">
                            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
                            <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-600" />
                          </span>
                          <p className="text-sm text-accent-800 dark:text-accent-300 font-semibold truncate">
                            Applying your requested change -- watch progress live in the Result panel &rarr;
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={stopReviseStream}
                          className="text-xs font-semibold text-accent-700 dark:text-accent-300 hover:text-accent-900 dark:hover:text-accent-100 underline flex-shrink-0"
                        >
                          Stop
                        </button>
                      </div>
                    )}
                  </>
                )}

                <ErrorBanner error={reviseStream.error} fallback="Failed to revise the SRS." />
              </>
            )}
          </>
        )}
      </div>

      {!hasOutput && conversation && !isConfirmed && !isGenerating && (
        <div className="flex-shrink-0 flex items-center justify-between pb-2">
          <button
            onClick={() => setShowManualForm((v) => !v)}
            className="text-xs text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold underline"
          >
            {showManualForm ? "Use the conversation instead" : "Prefer a detailed form instead?"}
          </button>
          <button
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            className="text-xs text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 underline"
          >
            Start over
          </button>
        </div>
      )}

      {/* Direct user request: the "Start Conversation" button must sit right next to the chat
          input, not up in the (mostly empty, pre-conversation) scroll area far above it -- and
          the composer itself must stay the same shared ChatComposerBox every other agent's chat
          uses, just disabled until the conversation actually exists. */}
      {!isLoading && !conversation && (
        <div className="flex-shrink-0 pb-2">
          <ErrorBanner error={start.error} fallback="Failed to start the conversation." />
          <button
            onClick={() => start.mutate()}
            disabled={start.isPending}
            className="w-full bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white text-sm font-semibold py-2 px-4 rounded-md"
          >
            {start.isPending ? "Starting..." : "Start Conversation"}
          </button>
          {start.isPending && <LoadingSpinner label="Reading the feature description..." />}
        </div>
      )}

      {canShowPreSrsComposer && (
        <form onSubmit={handleReplySubmit} className="flex-shrink-0">
          <ChatComposerBox
            value={replyText}
            onChange={(event) => setReplyText(event.target.value)}
            placeholder={
              !conversation
                ? 'Click "Start Conversation" above to begin...'
                : isGenerating
                  ? "Generating the final SRS -- please wait..."
                  : "Answer the question(s) above, or add anything else..."
            }
            disabled={!conversation || isReplying || editTurnStream.isPending || isGenerating}
            pending={isReplying || isGenerating}
            onStop={
              respondStream.isPending
                ? stopReplyStream
                : confirmStream.isPending
                  ? stopConfirmStream
                  : undefined
            }
            selectedAgent={selectedAgent}
            onSelectAgent={selectAgent}
            isAgentRunning={isAgentRunning}
          />
        </form>
      )}

      {hasOutput && (
        <div className="flex-shrink-0 pt-1">
          <form onSubmit={handleRevisionSubmit}>
            <ChatComposerBox
              value={revisionComment}
              onChange={(event) => setRevisionComment(event.target.value)}
              disabled={reviseStream.isPending}
              pending={reviseStream.isPending}
              onStop={stopReviseStream}
              selectedAgent={selectedAgent}
              onSelectAgent={selectAgent}
              isAgentRunning={isAgentRunning}
              placeholder="Ask Requirement Agent for a change..."
            />
          </form>
        </div>
      )}
    </div>
  );
}
