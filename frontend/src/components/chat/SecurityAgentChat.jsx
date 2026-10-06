import { useState } from "react";
import { useSecurityChatFlow, useSecurityChatHistory } from "../../hooks/useSecurityChatFlow";
import { useSecurityAgentFlowContext } from "../workspace/SecurityAgentFlowContext";
import { HumanBubble } from "../pipeline/RequirementConversationParts";
import ChatComposerBox from "./ChatComposerBox";
import LoadingSpinner from "../common/LoadingSpinner";
import LightHorseLoader from "../common/LightHorseLoader";
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

// A user turn reuses HumanBubble (RequirementConversationParts.jsx) as-is -- it's already fully
// generic (text/onEdit/isEditPending props, no Requirement-specific logic), giving Security chat
// the exact same Copy + hover-to-edit affordance for free (direct user request) instead of a
// second, parallel implementation. `onEdit` is only passed for a real, already-persisted turn
// (a stable `turn_index` -- see security_agent/agent.py's own _append_chat_turns) and only while
// no stream is currently in flight.
function SecurityChatBubble({ turn, onEdit, isEditPending }) {
  if (turn.role === "user") {
    return <HumanBubble text={turn.content} onEdit={onEdit} isEditPending={isEditPending} />;
  }
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] bg-gray-200 dark:bg-white/10 text-gray-800 dark:text-gray-200 rounded-lg rounded-tl-sm px-3 py-2 text-sm whitespace-pre-wrap break-words">
        <p className="text-xs text-gray-400 dark:text-gray-500 mb-0.5">Security Agent</p>
        {turn.content || <span className="italic opacity-60">...</span>}
      </div>
    </div>
  );
}

// Security Agent's own dedicated chat -- mirrors QaAgentChat.jsx's exact structure/shape (pure
// Q&A about an already-generated report, backed by its own real, persisted turn history --
// store.security_conversations, see useSecurityChatFlow.js -- rather than derived from
// artifact/event history the way every other agent's chat is). Direct user request: live,
// streaming, history-preserving discussion of the vulnerabilities found. Reuses the SAME shared
// useSecurityAgentFlowContext() mutation the Result panel's "Run/Re-run Scan" button and the
// Coder-approval auto-trigger already observe (see SecurityAgentFlowContext.jsx) -- not a new,
// independent mutation -- so a scan started from here shows its real progress everywhere else
// too, and vice versa.
export default function SecurityAgentChat({ featureId, feature, runningStage, selectedAgent, selectAgent, allArtifacts }) {
  const { data: history, isLoading: isLoadingHistory } = useSecurityChatHistory(featureId);
  const {
    chatStream, handleSendMessage, stopStream,
    editTurnStream, handleEditTurn,
    streamedText, streamStarted, streamError, pendingHumanMessage,
  } = useSecurityChatFlow(featureId);
  const { runSecurity } = useSecurityAgentFlowContext();
  const [message, setMessage] = useState("");

  const hasReport = (allArtifacts || []).some((a) => a.artifact_type === "security_report");
  const allTurns = history?.turns || [];
  const anyStreamPending = chatStream.isPending || editTurnStream.isPending;
  // While an edit is in flight, hide the turn being edited and everything after it -- they're
  // about to be discarded server-side, so showing them would flash stale content that's already
  // wrong (same "editing rewinds the conversation" UX Requirement Agent's own edit flow uses).
  const editingTurnIndex = editTurnStream.isPending ? editTurnStream.variables?.turnIndex : null;
  const turns = editingTurnIndex != null ? allTurns.filter((t) => t.turn_index < editingTurnIndex) : allTurns;
  const isAgentRunning = runningStage === "security" || anyStreamPending || runSecurity.isPending;

  function handleSubmit(event) {
    event.preventDefault();
    if (anyStreamPending) return;
    const trimmed = message.trim();
    if (!trimmed) return;
    setMessage("");
    handleSendMessage(trimmed);
  }

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-4">
      <ChatHeader feature={feature} runningStage={runningStage} />

      <div className="flex-1 min-h-0 overflow-y-auto py-3 flex flex-col gap-3">
        {!hasReport && (
          <div className="bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30 rounded-md px-3 py-2.5">
            <p className="text-sm font-semibold text-accent-900 dark:text-accent-200">
              No security scan has been run yet for this feature.
            </p>
            <ErrorBanner error={runSecurity.error} fallback="Failed to run the security scan." />
            <button
              type="button"
              onClick={() => runSecurity.mutate({})}
              disabled={runSecurity.isPending}
              className="mt-2 text-xs font-semibold bg-white dark:bg-white/10 hover:bg-accent-100 dark:hover:bg-white/20 disabled:opacity-50 text-accent-700 dark:text-accent-300 border border-accent-300 dark:border-accent-500/40 rounded-full px-3 py-1"
            >
              {runSecurity.isPending ? "Scanning..." : "Run Security Scan"}
            </button>
          </div>
        )}

        {isLoadingHistory ? (
          <LoadingSpinner label="Loading chat history..." />
        ) : turns.length === 0 && !anyStreamPending ? (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">
            No messages yet. Ask about the security report below -- e.g. "why is this finding Critical?"
          </p>
        ) : (
          turns.map((turn, i) => (
            <SecurityChatBubble
              key={i}
              turn={turn}
              onEdit={
                turn.role === "user" && turn.turn_index != null && !anyStreamPending
                  ? (newText) => handleEditTurn(turn.turn_index, newText)
                  : null
              }
              isEditPending={editTurnStream.isPending}
            />
          ))
        )}

        {anyStreamPending && pendingHumanMessage && (
          <SecurityChatBubble turn={{ role: "user", content: pendingHumanMessage }} />
        )}
        {/* Direct user request: show the Light Horse loader only until the agent starts
            responding -- once the first token arrives, the real streamed reply bubble takes over. */}
        {anyStreamPending && !streamStarted && (
          <div className="flex items-center gap-2 pl-1">
            <LightHorseLoader size={40} />
            <span className="text-sm text-gray-500 dark:text-gray-400">Thinking...</span>
          </div>
        )}
        {anyStreamPending && streamStarted && (
          <SecurityChatBubble turn={{ role: "assistant", content: streamedText }} />
        )}

        <ErrorBanner error={chatStream.error || editTurnStream.error || (streamError && { message: streamError })} fallback="Security chat request failed." />
      </div>

      <div className="flex-shrink-0 pt-1">
        <form onSubmit={handleSubmit}>
          <ChatComposerBox
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            disabled={false}
            pending={anyStreamPending}
            onStop={stopStream}
            selectedAgent={selectedAgent}
            onSelectAgent={selectAgent}
            isAgentRunning={isAgentRunning}
            placeholder="Ask Security Agent about the vulnerabilities found..."
          />
        </form>
      </div>
    </div>
  );
}
