// Up-arrow send button, circular, matching the reference composer's send affordance. Shared by
// every composer in the app (ChatPanel's normal composer and ChatComposerBox, which the
// Requirement Agent's conversational reply box also uses) so "send" always looks and behaves
// identically regardless of which agent/flow is active.
//
// While `pending`, this renders as a ChatGPT/Claude-style "Stop generating" button instead of a
// disabled spinner (direct user request: every agent's chat should be pausable) -- clicking it
// calls `onStop`, which the caller wires to whichever mutation/stream is currently in flight. Omit
// `onStop` (or leave it undefined) to fall back to the old disabled-spinner look for a caller that
// hasn't wired stop support yet.
export default function SendButton({ disabled, pending, onStop }) {
  if (pending) {
    return (
      <button
        type="button"
        onClick={onStop}
        disabled={!onStop}
        className="w-8 h-8 rounded-full bg-gray-900 hover:bg-black dark:bg-white dark:hover:bg-gray-200 disabled:opacity-30 disabled:cursor-not-allowed text-white dark:text-gray-900 flex items-center justify-center flex-shrink-0 transition-colors"
        title={onStop ? "Stop generating" : "Working..."}
      >
        <svg viewBox="0 0 20 20" fill="currentColor" className="w-3.5 h-3.5">
          <rect x="5" y="5" width="10" height="10" rx="1.5" />
        </svg>
      </button>
    );
  }

  return (
    <button
      type="submit"
      disabled={disabled}
      className="w-8 h-8 rounded-full bg-accent-600 hover:bg-accent-700 disabled:opacity-30 disabled:cursor-not-allowed text-white flex items-center justify-center flex-shrink-0 transition-colors"
      title="Send"
    >
      <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
        <path
          fillRule="evenodd"
          d="M10 17a.75.75 0 01-.75-.75V5.612L5.29 9.77a.75.75 0 01-1.08-1.04l5.25-5.5a.75.75 0 011.08 0l5.25 5.5a.75.75 0 11-1.08 1.04l-3.96-4.158V16.25A.75.75 0 0110 17z"
          clipRule="evenodd"
        />
      </svg>
    </button>
  );
}
