import { useEffect, useRef, useState } from "react";
import LoadingSpinner from "../common/LoadingSpinner";
import LightHorseLoader from "../common/LightHorseLoader";
import CopyButton from "../common/CopyButton";

// Ticks once a second while `startedAt` is set -- used by LiveGenerationView's finalizing phase
// to show "2m 14s" instead of a static label, the cheapest possible signal that a long,
// non-streamable step (diagram generation, PlantUML rendering) is still actually progressing and
// not stuck. Returns null (render nothing) until at least 1s has elapsed, matching this file's
// existing "don't show a counter at 0" convention.
// Exported so other chat components (CoderAgentChat, ArchitectureAgentChat) can show a real
// ticking timer for their own long, token-free phases instead of each re-deriving a static,
// render-time-only label -- see those components' own comments for why a static label reads as a
// hung/broken UI during a genuinely long wait.
export function useElapsedLabel(startedAt) {
  const [, forceTick] = useState(0);

  useEffect(() => {
    if (!startedAt) return undefined;
    const interval = setInterval(() => forceTick((n) => n + 1), 1000);
    return () => clearInterval(interval);
  }, [startedAt]);

  if (!startedAt) return null;

  const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
  if (elapsedSeconds < 1) return null;

  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = elapsedSeconds % 60;
  return minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`;
}

// Cycles through `phrases` every `intervalMs`, restarting from the first phrase whenever the
// phrase list itself changes (so a caller can freely swap in a different theme without a stale
// index lingering). Returns the first phrase immediately (no "waiting for the first tick" gap)
// and null if the list is empty. Used by ResultTab.jsx's Coder Agent live view to show a real,
// visibly-rotating security-fix-themed message instead of a single static label during a
// security-driven revision -- deliberately new; no existing rotating-message mechanism exists
// anywhere else in this codebase (every other phase label is one static string).
export function useRotatingLabel(phrases, intervalMs = 2500) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    setIndex(0);
    if (!phrases || phrases.length < 2) return undefined;
    const interval = setInterval(() => setIndex((n) => (n + 1) % phrases.length), intervalMs);
    return () => clearInterval(interval);
  }, [phrases, intervalMs]);

  if (!phrases || phrases.length === 0) return null;
  return phrases[index % phrases.length];
}

export function PencilIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-3 h-3">
      <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z" />
    </svg>
  );
}

// Presentational pieces of the Requirement Agent's conversational gap-filling flow -- ChatPanel
// composes these around its own normal ChatComposerBox, so the actual input mechanism (single
// free-text box + agent/model pills + send button) is identical to every other agent's chat
// instead of a separate bespoke form. Bubble classes mirror ChatBubble's so a conversation turn
// looks the same as any other chat message in this app.
//
// `onEdit`, when provided, enables ChatGPT/Claude-style "edit this message" -- hovering reveals a
// pencil affordance; clicking it swaps the bubble for an editable textarea seeded with the
// original text. Saving calls onEdit(newText), which the caller wires to
// RequirementAgent.edit_turn_reply -- the backend discards this turn and everything after it, then
// regenerates from the edited text, exactly like the reference products' edit flow. Omit `onEdit`
// (e.g. while a stream is generating, or after confirm) to render a plain, non-editable bubble.
export function HumanBubble({ text, onEdit, isEditPending }) {
  const [isEditing, setIsEditing] = useState(false);
  const [draft, setDraft] = useState(text);

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
                setDraft(text);
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
                if (!trimmed || trimmed === text.trim()) return;
                onEdit(trimmed);
              }}
              disabled={isEditPending || !draft.trim()}
              className="text-xs bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold px-3 py-1 rounded-md"
            >
              Save &amp; Regenerate
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
          <p className="text-xs text-accent-200 dark:text-accent-100/80 mb-0.5">You</p>
          <p className="whitespace-pre-wrap break-words">{text}</p>
        </div>
        <div className="flex items-center gap-2">
          {onEdit && (
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
          <CopyButton text={text} />
        </div>
      </div>
    </div>
  );
}

export function AgentTurnBubble({ turn }) {
  const hasQuestions = turn.questions_asked && turn.questions_asked.length > 0;
  const hasAssumptions = turn.assumptions_flagged_this_turn && turn.assumptions_flagged_this_turn.length > 0;
  const hasReaction = Boolean(turn.agent_reaction && turn.agent_reaction.trim());

  if (!hasQuestions && !hasAssumptions && !hasReaction) return null;

  const copyText = [turn.agent_reaction, ...(turn.questions_asked || []).map((q) => q.question)]
    .filter(Boolean)
    .join("\n\n");

  return (
    <div className="flex flex-col items-start gap-1 group">
      <div className="max-w-[85%] bg-gray-100 dark:bg-white/10 text-gray-800 dark:text-gray-200 rounded-lg rounded-tl-sm px-3 py-2 text-sm flex flex-col gap-2">
        <p className="text-xs text-gray-500 dark:text-gray-400">Requirement Agent</p>

        {/* The agent's own dynamically-generated reaction to the human's last reply -- e.g.
            calling out that a reply was irrelevant or didn't answer the question, instead of the
            questions below just appearing as if nothing was wrong with it. */}
        {hasReaction && <p className="whitespace-pre-wrap break-words">{turn.agent_reaction}</p>}

        {hasQuestions && (
          <ul className="space-y-2">
            {turn.questions_asked.map((q, i) => (
              <li key={i}>
                <p>{q.question}</p>
                {/* Per-question example answers used to live as separate input placeholders (one
                    box per question) -- now that replies go through the single shared composer
                    like every other agent, the example is shown as inline guidance instead so it
                    isn't lost. */}
                {q.placeholder_example && (
                  <p className="text-xs text-gray-500 dark:text-gray-400 italic mt-0.5">
                    e.g. {q.placeholder_example}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        {hasAssumptions && (
          <div className="bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/30 rounded-md px-2.5 py-1.5">
            <p className="text-[11px] font-bold text-amber-800 dark:text-amber-300 uppercase tracking-wide mb-1">
              Assumed instead of asked
            </p>
            <ul className="list-disc list-inside text-xs text-amber-900 dark:text-amber-200 space-y-0.5">
              {turn.assumptions_flagged_this_turn.map((a, i) => (
                <li key={i}>{a}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
      <CopyButton text={copyText} />
    </div>
  );
}

export function QualityGateBanner({ qualityGate, onConfirm, isConfirming, disabled }) {
  const [showOverride, setShowOverride] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");

  if (!qualityGate) return null;

  if (qualityGate.ready) {
    return (
      <div className="flex items-center justify-between gap-3 bg-green-50 dark:bg-green-500/10 border border-green-200 dark:border-green-500/30 rounded-lg px-3 py-2.5">
        <p className="text-sm text-green-800 dark:text-green-300 font-semibold">Ready to generate the final SRS.</p>
        <button
          onClick={() => onConfirm({})}
          disabled={isConfirming || disabled}
          className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white text-sm font-semibold px-4 py-1.5 rounded-md flex-shrink-0"
        >
          Confirm & Generate Final SRS
        </button>
      </div>
    );
  }

  return (
    <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-lg px-3 py-2.5">
      <p className="text-sm font-semibold text-red-800 dark:text-red-300 mb-1">Not ready to confirm yet:</p>
      <ul className="list-disc list-inside text-xs text-red-700 dark:text-red-400 space-y-0.5 mb-2">
        {qualityGate.reasons.map((reason, i) => (
          <li key={i}>{reason}</li>
        ))}
      </ul>

      {disabled && (
        <p className="text-xs text-red-500 dark:text-red-400 italic mb-2">
          Waiting for your last answer to finish processing before this can be confirmed...
        </p>
      )}

      {!showOverride ? (
        <button
          onClick={() => setShowOverride(true)}
          disabled={disabled}
          className="text-xs text-red-700 dark:text-red-400 hover:text-red-900 dark:hover:text-red-300 disabled:opacity-50 font-semibold underline"
        >
          Confirm anyway
        </button>
      ) : (
        <div className="flex flex-col gap-2 mt-1">
          <input
            value={overrideReason}
            onChange={(e) => setOverrideReason(e.target.value)}
            placeholder="Why is it okay to proceed despite these gaps?"
            className="text-sm border border-red-300 dark:border-red-500/40 dark:bg-white/5 dark:text-gray-100 rounded-md p-1.5 focus:outline-none focus:border-red-500"
          />
          <button
            onClick={() =>
              onConfirm({ override_quality_gate: true, override_reason: overrideReason.trim() || null })
            }
            disabled={isConfirming || disabled || !overrideReason.trim()}
            className="self-start bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white text-sm font-semibold px-4 py-1.5 rounded-md"
          >
            Confirm Anyway & Generate SRS
          </button>
        </div>
      )}
    </div>
  );
}

// The live-updating "SRS is being generated" view -- shown from the moment Confirm is clicked
// until the real artifact takes over. A spinner alone covers the network/model-startup latency
// before the first token arrives; once tokens start streaming in, the text growing in place is
// itself the strongest possible signal that generation is genuinely live, not a fixed wait
// followed by a sudden reveal. Its only home is now the wide Result/Output panel (the chat column
// shows a compact pointer instead of duplicating this) -- sized accordingly, not for a narrow
// sidebar.
//
// `displayText` is whatever the caller wants shown -- NOT necessarily the raw streamed JSON.
// Showing raw JSON (braces, quotes, "known_answers":) live reads as debug output, not a document
// "generating directly" the way ChatGPT/Claude's responses do (a real, reported issue) -- callers
// should run the raw stream through declutterJsonForDisplay (or an equivalent transform) first.
// See RequirementSrsOutputPanel for the one remaining caller.
//
// `isFinalizing`/`finalizingLabel`/`phaseStartedAt` (all optional, every existing call site
// unaffected): for a generation whose token stream finishes but real work continues behind the
// scenes (Architecture Agent's use-case model + diagram generation + PlantUML rendering, which
// can be several sequential LLM calls plus subprocess renders -- see ArchitectureAgentChat.jsx).
// When set, the already-streamed text stays frozen on screen (still the most useful thing to
// show -- it's real, finished content) instead of being replaced by a bare spinner, and the
// header swaps the pulsing "connecting" dot for a cube spinner + the current phase label + an
// elapsed-time counter, so a multi-minute tail doesn't read as stuck.
export function LiveGenerationView({
  displayText,
  hasStarted,
  connectingLabel,
  generatingLabel = "Generating...",
  isFinalizing = false,
  finalizingLabel,
  phaseStartedAt = null,
}) {
  const elapsedLabel = useElapsedLabel(isFinalizing ? phaseStartedAt : null);
  // Direct, real reported bug: this box has overflow-y-auto but nothing ever moved its own
  // scrollTop as displayText grew, so a human had to keep manually scrolling down to see newly-
  // arriving content -- no auto-scroll-to-bottom precedent existed anywhere else in this codebase
  // to copy, so this is a first implementation, not a reused pattern.
  const previewRef = useRef(null);
  useEffect(() => {
    if (previewRef.current) previewRef.current.scrollTop = previewRef.current.scrollHeight;
  }, [displayText]);

  return (
    <div className="border border-accent-200 dark:border-accent-500/30 bg-accent-50 dark:bg-accent-500/10 rounded-lg p-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        {isFinalizing ? (
          <LoadingSpinner variant="cube" size={18} />
        ) : (
          <span className="relative flex h-2.5 w-2.5">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-accent-600" />
          </span>
        )}
        <p className="text-sm font-semibold text-accent-800 dark:text-accent-300">
          {isFinalizing ? finalizingLabel : hasStarted ? generatingLabel : connectingLabel}
          {isFinalizing && elapsedLabel && <span className="font-normal text-accent-600 dark:text-accent-400"> &middot; {elapsedLabel}</span>}
        </p>
      </div>

      {!hasStarted && !isFinalizing && (
        <div className="flex items-center gap-3 text-gray-500 dark:text-gray-400 py-2">
          <LightHorseLoader size={40} />
          <span className="text-sm">Waiting for the model to start responding...</span>
        </div>
      )}

      {hasStarted && (
        <pre
          ref={previewRef}
          className="text-sm text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-md p-4 max-h-[65vh] overflow-y-auto whitespace-pre-wrap break-words font-sans"
        >
          {displayText}
          {!isFinalizing && (
            <span className="inline-block w-2 h-4 bg-accent-600 align-text-bottom animate-pulse ml-0.5" />
          )}
        </pre>
      )}
    </div>
  );
}

// The live, in-chat counterpart for a normal reply's streaming response -- unlike SRS generation
// (a document, shown in LiveGenerationView above), a reply's agent_reaction IS meant to read as a
// single chat message, so this shows ONLY that field's text growing inside a normal
// AgentTurnBubble-styled bubble -- no JSON, no surrounding known_answers/questions noise -- and
// swaps seamlessly into a real AgentTurnBubble the instant the stream completes and the actual
// turn (with its questions) lands. Also reused by DomainAgentChat.jsx for its own streaming
// summary -- `agentLabel` defaults to "Requirement Agent" only for that original caller's sake;
// every other caller should pass its own agent's label explicitly.
export function LiveReactionBubble({ reactionText, hasStarted, agentLabel = "Requirement Agent" }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] bg-gray-100 dark:bg-white/10 text-gray-800 dark:text-gray-200 rounded-lg rounded-tl-sm px-3 py-2 text-sm flex flex-col gap-2">
        <p className="text-xs text-gray-500 dark:text-gray-400">{agentLabel}</p>
        {!hasStarted || !reactionText ? (
          <div className="flex items-center gap-2">
            <LightHorseLoader size={28} />
            <span className="text-sm text-gray-500 dark:text-gray-400">Thinking...</span>
          </div>
        ) : (
          <p className="whitespace-pre-wrap break-words">
            {reactionText}
            <span className="inline-block w-1.5 h-3.5 bg-accent-600 align-text-bottom animate-pulse ml-0.5" />
          </p>
        )}
      </div>
    </div>
  );
}
