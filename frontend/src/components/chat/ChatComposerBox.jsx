import { useEffect, useRef } from "react";
import AgentSelect from "./AgentSelect";
import ModelSelect from "./ModelSelect";
import SendButton from "./SendButton";

const ATTACH_ACCEPT = ".txt,.md,.pdf,.docx";

// Caps how tall the composer can grow before it starts scrolling internally instead -- roughly
// 10 lines at this font size, matching ChatGPT/Claude's own composer ceiling. Past this, the rest
// of the workspace (chat history, output panel) stays visible instead of getting pushed off
// screen by one very long message.
const MAX_TEXTAREA_HEIGHT_PX = 240;

function PaperclipIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-4 h-4 flex-shrink-0">
      <path
        d="M8.5 12.5l4-4a2 2 0 10-2.83-2.83l-5 5a3.5 3.5 0 004.95 4.95l4.5-4.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// The rounded composer box shared by every agent's chat, including the Requirement Agent's
// conversational reply flow -- previously that flow had its own separate stack of per-question
// input boxes with a "Send Answers" button, visually inconsistent with every other agent. Pulling
// this out into one component is what actually guarantees "the chat window stays the same for
// every agent" going forward: there is only one place this markup exists, so it can't drift.
// `children` renders above the input (e.g. Domain Agent's "/" document-mention picker/chips) --
// only ChatPanel's normal composer uses that slot today.
//
// A multi-line `<textarea>` (not `<input>`) -- Shift+Enter inserts a newline, plain Enter sends,
// matching ChatGPT/Claude. `allowFileAttach` (only the Requirement Agent's conversation opts in
// today) adds a paperclip button for attaching a text/PDF/DOCX file directly to the message.
export default function ChatComposerBox({
  value,
  onChange,
  placeholder,
  disabled,
  pending,
  onStop,
  selectedAgent,
  onSelectAgent,
  isAgentRunning,
  children,
  allowFileAttach = false,
  attachedFile = null,
  onAttachFile,
  onRemoveAttachedFile,
}) {
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);

  // Real auto-resize (measure scrollHeight, not just count "\n"s) -- a long message with no
  // manual line breaks still wraps across many visual lines, and the box needs to grow with
  // THAT, not just explicit Shift+Enter presses. Resetting to "auto" first is what lets the
  // browser recompute scrollHeight correctly when text is removed/shortened, not just added.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_TEXTAREA_HEIGHT_PX)}px`;
  }, [value]);

  function handleKeyDown(event) {
    // requestSubmit() is the standard DOM equivalent of clicking the form's own submit button --
    // using it (instead of manually calling a submit handler) means every caller's existing
    // <form onSubmit={...}> wiring keeps working completely unchanged; this only needs to know
    // there IS a form, not what it does when submitted.
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className="relative rounded-2xl border border-gray-300 dark:border-gray-700 bg-gray-100 dark:bg-white/5 p-2.5 flex flex-col gap-2">
      {children}

      {attachedFile && (
        <div className="flex flex-wrap gap-1.5">
          <span className="inline-flex items-center gap-1.5 text-xs bg-accent-50 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300 rounded-full px-2.5 py-1">
            <PaperclipIcon />
            <span className="truncate max-w-[220px]">{attachedFile.name}</span>
            <button
              type="button"
              onClick={onRemoveAttachedFile}
              className="text-accent-500 hover:text-accent-800 dark:hover:text-accent-100"
              aria-label={`Remove ${attachedFile.name}`}
            >
              &times;
            </button>
          </span>
        </div>
      )}

      <textarea
        ref={textareaRef}
        value={value}
        onChange={onChange}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        rows={1}
        style={{ maxHeight: `${MAX_TEXTAREA_HEIGHT_PX}px` }}
        className="w-full bg-transparent text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none px-1 disabled:cursor-not-allowed resize-none overflow-y-auto"
      />
      <div className="flex items-end justify-between gap-2">
        <div className="flex items-end gap-3 min-w-0">
          {allowFileAttach && (
            <>
              <input
                ref={fileInputRef}
                type="file"
                accept={ATTACH_ACCEPT}
                className="hidden"
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) onAttachFile(file);
                  event.target.value = "";
                }}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={disabled}
                title="Attach a text, PDF, or Word document"
                className="flex items-center justify-center w-8 h-8 rounded-full text-gray-500 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed flex-shrink-0"
              >
                <PaperclipIcon />
              </button>
            </>
          )}
          {/* flex-auto (grow AND shrink, basis on the pill's own natural content width -- NOT
              flex-1's forced equal-halves basis-0%) so these two pills size to their own content
              at comfortable widths (e.g. "qwen2.5-coder:14b" shows in full whenever there's
              genuinely room for it) but still actually shrink once the row runs out of space --
              previously they only had an upper bound (PillDropdown's own max-w-[160px]), never
              anything letting them shrink below their intrinsic content width, so at narrow
              (laptop) column widths the row overflowed past the composer's own card border.
              fillWidth (below) is what lets the pill itself actually shrink to match instead of
              just this wrapper. */}
          <div className="flex flex-col gap-1 min-w-0 flex-auto">
            <span className="text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide px-1">
              Agent
            </span>
            <AgentSelect value={selectedAgent} onChange={onSelectAgent} isRunning={isAgentRunning} fillWidth />
          </div>
          <div className="flex flex-col gap-1 min-w-0 flex-auto">
            <span className="text-[10px] font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wide px-1">
              Model
            </span>
            <ModelSelect agentStage={selectedAgent} fillWidth />
          </div>
        </div>
        <SendButton
          disabled={disabled || (!value.trim() && !attachedFile)}
          pending={pending}
          onStop={onStop}
        />
      </div>
      {/* A passive notice, not content -- select-none keeps it out of a drag-select/copy, since
          it's never meant to be quoted or copied like a real message. Rendered here (inside the
          one shared composer every agent's chat renders, per this component's own docstring)
          so every stage gets it automatically with this one change. */}
      <p className="text-[11px] text-gray-500 dark:text-gray-400 text-center select-none">
        AI can make mistakes. Check important information.
      </p>
    </div>
  );
}
