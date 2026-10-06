import { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { useDomainAgentFlowContext } from "../workspace/DomainAgentFlowContext";
import { useKnowledgeDocuments } from "../../hooks/useKnowledgeDocuments";
import { listGatingArtifactVersions } from "../../lib/deriveStageStatus";
import { SUGGESTION_CHIPS } from "../../lib/suggestionChips";
import { LiveReactionBubble } from "../pipeline/RequirementConversationParts";
import { extractStreamingJsonStringField } from "../../lib/streamingJsonDisplay";
import ChatBubble from "./ChatBubble";
import ChatComposerBox from "./ChatComposerBox";
import DocumentMentionPicker from "./DocumentMentionPicker";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

// Matches a trailing "/word" token (same pattern ChatPanel used before Domain got its own
// dedicated component).
const MENTION_TRIGGER_PATTERN = /(?:^|\s)\/(\w*)$/;

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

// Domain Agent's own dedicated chat, mirroring RequirementRevisionChat.jsx -- pulled out of
// ChatPanel's generic composer path per direct, multi-part user report: Domain Agent was the one
// agent chat left on the old experience every other agent already moved past --
//   1. the typed message sat inert in the composer until the WHOLE enrichment finished (fixed:
//      the composer clears and an optimistic bubble appears in the chat feed IMMEDIATELY, before
//      the agent even starts, exactly like every other agent's chat now does);
//   2. no live output at all, just a spinner then a sudden reveal (fixed: the enrichment plan's
//      "summary" streams live into a chat bubble via useDomainAgentFlowContext, and the Result
//      panel -- see ResultTab.jsx -- streams the same raw plan live too, both using the identical
//      mechanism Requirement Agent's revise chat already established);
//   3. no way to stop it (fixed: the composer's Send button becomes a Stop button while a stream
//      is in flight, same AbortController mechanism as every other agent).
// The actual "did the human's explicit content (e.g. a database schema) really get incorporated"
// bug was a backend problem (Domain Agent's validator rejected anything not traceable to a
// retrieved knowledge chunk, silently dropping literal human-provided content) -- fixed in
// domain_validator.py/agent.py/prompt.py, not here; this component only fixes how the chat LOOKS
// and BEHAVES while that fixed backend does its work.
export default function DomainAgentChat({
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
    runStreamError,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
    revisionStreamError,
  } = useDomainAgentFlowContext();

  const [comment, setComment] = useState("");
  const [pendingHumanReply, setPendingHumanReply] = useState(null);
  const [referencedDocuments, setReferencedDocuments] = useState([]);
  const [mentionQuery, setMentionQuery] = useState(null);

  const versions = listGatingArtifactVersions("domain", allArtifacts);
  const hasOutput = versions.length > 0;

  const activeStream = hasOutput ? reviseStream : runStream;
  const streamedText = hasOutput ? revisionStreamedText : runStreamedText;
  const streamStarted = hasOutput ? revisionStreamStarted : runStreamStarted;
  const stopActiveStream = hasOutput ? stopReviseStream : stopRunStream;
  // Set from a real {"type": "error"} NDJSON line -- unlike activeStream.error (only set on a
  // genuine promise rejection), this is the only signal available when the stream completed
  // "successfully" from fetch's point of view but the agent itself crashed mid-attempt.
  const streamError = hasOutput ? revisionStreamError : runStreamError;

  const projectId = feature?.project_id;
  const { data: knowledgeDocuments } = useKnowledgeDocuments(projectId, { enabled: Boolean(projectId) });

  function handleCommentChange(event) {
    const value = event.target.value;
    setComment(value);
    const match = value.slice(0, event.target.selectionStart ?? value.length).match(MENTION_TRIGGER_PATTERN);
    setMentionQuery(match ? match[1] : null);
  }

  function handleMentionSelect(doc) {
    setComment((current) => current.replace(MENTION_TRIGGER_PATTERN, (full) => (full.startsWith(" ") ? " " : "")));
    setReferencedDocuments((current) =>
      current.some((d) => d.document_id === doc.document_id) ? current : [...current, doc]
    );
    setMentionQuery(null);
  }

  function removeReferencedDocument(documentId) {
    setReferencedDocuments((current) => current.filter((d) => d.document_id !== documentId));
  }

  // Shared by the composer's Send, the "Just use domain knowledge" quick action, and a chat
  // bubble's inline "Save & Send" (see ChatBubble's own docstring on why editing resubmits rather
  // than rewriting history). The human's message appears in the chat feed immediately via
  // pendingHumanReply -- the real "ask" bubble only lands once the invalidated events query
  // refetches, same optimistic-then-reconciled pattern RequirementRevisionChat already uses.
  function submitDomainMessage(text, documentIds = []) {
    if (activeStream.isPending) return;
    const trimmed = text.trim();

    setPendingHumanReply(trimmed);

    const call = hasOutput
      ? handleReviseStream({
          revision_comment: trimmed,
          revised_by: user?.name || user?.email || "human_user",
          referenced_document_ids: documentIds,
        })
      : handleRunStream({ human_comment: trimmed, referenced_document_ids: documentIds });

    call.finally(() => setPendingHumanReply(null));
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (activeStream.isPending) return;
    const trimmed = comment.trim();
    if (!trimmed) return;

    const documentIds = referencedDocuments.map((doc) => doc.document_id);
    setComment("");
    setReferencedDocuments([]);
    setMentionQuery(null);
    submitDomainMessage(trimmed, documentIds);
  }

  function handleJustUseDomainKnowledge() {
    if (activeStream.isPending) return;
    submitDomainMessage("", []);
  }

  const reactionText = extractStreamingJsonStringField(streamedText, "summary");
  const isAgentRunning = runningStage === "domain" || activeStream.isPending;

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
              onEditSubmit={(text) => submitDomainMessage(text, [])}
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
            <LiveReactionBubble reactionText={reactionText} hasStarted={streamStarted} agentLabel="Domain Agent" />
            {streamStarted && (
              <div className="flex items-center justify-between gap-2 bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30 rounded-lg px-3 py-2.5">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="relative flex h-2 w-2 flex-shrink-0">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-accent-600" />
                  </span>
                  <p className="text-sm text-accent-800 dark:text-accent-300 font-semibold truncate">
                    {hasOutput ? "Applying your requested change" : "Enriching the SRS"} -- watch
                    progress live in the Result panel &rarr;
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
          fallback="Domain Agent request failed."
        />
      </div>

      <div className="flex-shrink-0 pt-1">
        {!hasOutput && !activeStream.isPending && (
          <div className="bg-accent-50 dark:bg-accent-500/10 border border-accent-200 dark:border-accent-500/30 rounded-md px-3 py-2.5 mb-2">
            <p className="text-sm font-semibold text-accent-900 dark:text-accent-200">
              Should Domain Agent enrich this SRS using its existing domain knowledge, or do you
              have something specific to add -- like a database schema, a compliance rule, or a
              business constraint?
            </p>
            <p className="text-xs text-accent-700 dark:text-accent-400 mt-1">
              Describe it below, or type <code>/</code> to reference an uploaded document. If you
              don't have anything specific, just click through and it'll use domain knowledge
              alone.
            </p>
            <button
              type="button"
              onClick={handleJustUseDomainKnowledge}
              className="mt-2 text-xs font-semibold bg-white dark:bg-white/10 hover:bg-accent-100 dark:hover:bg-white/20 disabled:opacity-50 text-accent-700 dark:text-accent-300 border border-accent-300 dark:border-accent-500/40 rounded-full px-3 py-1"
            >
              Just use domain knowledge
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          {SUGGESTION_CHIPS.domain && (
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTION_CHIPS.domain.map((chip) => (
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
            onChange={handleCommentChange}
            disabled={false}
            pending={activeStream.isPending}
            onStop={stopActiveStream}
            selectedAgent={selectedAgent}
            onSelectAgent={selectAgent}
            isAgentRunning={isAgentRunning}
            placeholder={
              hasOutput
                ? "Ask Domain Agent for a change..."
                : "e.g. Here's our database schema: ... (or leave blank and use the button above)"
            }
          >
            {mentionQuery !== null && (
              <DocumentMentionPicker documents={knowledgeDocuments} query={mentionQuery} onSelect={handleMentionSelect} />
            )}

            {referencedDocuments.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {referencedDocuments.map((doc) => (
                  <span
                    key={doc.document_id}
                    className="inline-flex items-center gap-1 text-xs bg-accent-50 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300 rounded-full px-2 py-1"
                  >
                    {doc.original_filename}
                    <button
                      type="button"
                      onClick={() => removeReferencedDocument(doc.document_id)}
                      className="text-accent-500 hover:text-accent-800 dark:hover:text-accent-100"
                      aria-label={`Remove ${doc.original_filename}`}
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}
          </ChatComposerBox>
        </form>
      </div>
    </div>
  );
}
