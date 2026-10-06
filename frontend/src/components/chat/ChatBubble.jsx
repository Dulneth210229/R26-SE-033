import { useState } from "react";
import { STAGE_LABELS } from "../../lib/pipelineStages";
import { ARTIFACT_TYPE_LABELS } from "../../lib/artifactTypeMeta";
import { PencilIcon } from "../pipeline/RequirementConversationParts";
import CopyButton from "../common/CopyButton";

const STATUS_LABELS = {
  approved: "Approved",
  rejected: "Rejected",
  revision_requested: "Revision requested",
};

// Ask-bubble labels by stage_event event_type -- a plain map instead of a ternary so a new
// event_type never silently falls through to the wrong label.
const ASK_EVENT_LABELS = {
  run: "Started",
  revise: "Revision requested",
  edit: "Manual edit",
  clarify_start: "Conversation started",
  clarify: "Answered questions",
  confirm: "Confirmed SRS",
};

// Extracted from StageInteractionPanel's old TimelineItem. `item.stage` always equals whichever
// agent's chat is currently open (buildAgentTimeline scopes the whole feed to one agent, per
// direct user report -- see its own docstring), so the stage tag rendered below is redundant
// today; kept because a future multi-agent-in-one-view layout could reuse this bubble as-is.
//
// `onEditSubmit`, when provided, enables ChatGPT/Claude-style "edit this message" on "ask"
// bubbles -- hovering reveals a pencil affordance; clicking it swaps the bubble in place for an
// editable textarea seeded with the original text (same pattern as HumanBubble in
// RequirementConversationParts.jsx). Direct user report on an earlier version of this: clicking
// Edit loaded the text back into the composer below instead, so "editing" meant leaving the
// message, retyping in a totally different box, and hitting Send again -- not what "edit the
// message" means in any reference chat product. Saving calls onEditSubmit(newText), which the
// caller wires to the SAME run/revise mutation the composer's Send already uses -- the artifact
// an old ask already produced is still immutable history (this app has no backend "rewind" for
// run/revise, unlike the Requirement Agent's pre-SRS conversation), so "edit" here means
// resubmitting the edited text as the next message, just triggered from the message itself
// instead of a round-trip through the composer.
export default function ChatBubble({ item, allArtifacts, onViewArtifact, onEditSubmit, isEditPending }) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(item.comment || "");
  const stageTag = STAGE_LABELS[item.stage] || item.stage;

  if (item.kind === "ask") {
    if (isEditing) {
      return (
        <div className="flex justify-end">
          <div className="max-w-[85%] w-full flex flex-col gap-1.5">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              autoFocus
              rows={Math.min(8, Math.max(2, draft.split("\n").length))}
              className="w-full text-sm bg-white dark:bg-gray-900 border border-accent-400 dark:border-accent-500 rounded-lg p-2.5 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-accent-500 resize-none"
            />
            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setDraft(item.comment || "");
                  setIsEditing(false);
                }}
                disabled={isEditPending}
                className="text-xs text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 disabled:opacity-50 font-semibold px-2 py-1"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  const trimmed = draft.trim();
                  setIsEditing(false);
                  if (!trimmed || trimmed === (item.comment || "").trim()) return;
                  onEditSubmit(trimmed);
                }}
                disabled={isEditPending || !draft.trim()}
                className="text-xs bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold px-3 py-1 rounded-md"
              >
                Save &amp; Send
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="flex justify-end group">
        <div className="max-w-[85%] flex flex-col items-end gap-1">
          <div className="bg-accent-600 dark:bg-accent-500 text-white rounded-lg rounded-tr-sm px-3 py-2 text-sm">
            <p className="text-xs text-accent-200 dark:text-accent-100/80 mb-0.5">
              {ASK_EVENT_LABELS[item.eventType] || "Revision requested"} &middot; {stageTag}
            </p>
            <p className="whitespace-pre-wrap break-words">{item.comment || <span className="italic text-accent-200 dark:text-accent-100/80">(no comment provided)</span>}</p>
          </div>
          <div className="flex items-center gap-2">
            {onEditSubmit && item.comment && (
              <button
                type="button"
                onClick={() => setIsEditing(true)}
                disabled={isEditPending}
                title="Edit this message"
                className="opacity-0 group-hover:opacity-100 focus:opacity-100 disabled:opacity-30 transition-opacity text-xs text-gray-400 dark:text-gray-500 hover:text-accent-600 dark:hover:text-accent-400 flex items-center gap-1 px-1"
              >
                <PencilIcon />
                Edit
              </button>
            )}
            <CopyButton text={item.comment} />
          </div>
        </div>
      </div>
    );
  }

  if (item.kind === "response") {
    const label = item.types.map((t) => ARTIFACT_TYPE_LABELS[t] || t).join(", ");
    const representative = allArtifacts.find(
      (a) => a.version === item.version && item.types.includes(a.artifact_type)
    );
    const messageText = `Produced ${label} (v${item.version})`;
    const copyText = item.summary ? `${messageText}\n${item.summary}` : messageText;

    return (
      <div className="flex justify-start group">
        <div className="max-w-[85%] flex flex-col items-start gap-1">
          <div className="bg-gray-200 dark:bg-white/10 text-gray-800 dark:text-gray-200 rounded-lg rounded-tl-sm px-3 py-2 text-sm">
            <p className="text-xs text-gray-500 dark:text-gray-400 mb-0.5">{stageTag} Agent</p>
            <p>
              {messageText}
              {representative && (
                <>
                  {" -- "}
                  <button
                    onClick={() => onViewArtifact(representative)}
                    className="text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold"
                  >
                    View
                  </button>
                </>
              )}
            </p>
            {item.summary && (
              <p className="mt-1 text-gray-600 dark:text-gray-300 whitespace-pre-wrap break-words">
                {item.summary}
              </p>
            )}
          </div>
          <CopyButton text={copyText} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-center">
      <p className="text-xs text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-white/5 border border-gray-300 dark:border-gray-700 rounded-full px-3 py-1">
        {stageTag}: {STATUS_LABELS[item.status] || item.status}
        {item.comment ? ` -- "${item.comment}"` : ""}
      </p>
    </div>
  );
}
