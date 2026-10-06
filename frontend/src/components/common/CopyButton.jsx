import { useState } from "react";

function CopyIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-3 h-3">
      <path d="M7 3.5A1.5 1.5 0 018.5 2h3.879a1.5 1.5 0 011.06.44l3.122 3.12A1.5 1.5 0 0117 6.622V12.5a1.5 1.5 0 01-1.5 1.5h-1v-3.379a3 3 0 00-.879-2.121L10.5 5.379A3 3 0 008.379 4.5H7v-1z" />
      <path d="M4.5 6A1.5 1.5 0 003 7.5v9A1.5 1.5 0 004.5 18h7a1.5 1.5 0 001.5-1.5v-6.879a1.5 1.5 0 00-.44-1.06L9.44 5.44A1.5 1.5 0 008.378 5H4.5z" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-3 h-3">
      <path
        fillRule="evenodd"
        d="M16.704 4.153a.75.75 0 01.143 1.052l-8 10.5a.75.75 0 01-1.127.075l-4.5-4.5a.75.75 0 011.06-1.06l3.894 3.893 7.48-9.817a.75.75 0 011.05-.143z"
        clipRule="evenodd"
      />
    </svg>
  );
}

// Hover-reveal "copy this message" affordance -- every user and agent chat bubble gets one
// (direct user request, matching ChatGPT/Claude's copy-to-clipboard icon). Relies on a `group`
// class somewhere on an ancestor element to reveal on hover, same convention as the pre-existing
// Edit affordance this sits next to. Swaps to a checkmark for a moment after a successful copy so
// the click has visible confirmation, then reverts -- silently does nothing on failure (clipboard
// permission denied/unavailable) since there's nothing more meaningful to show.
export default function CopyButton({ text, label = "Copy" }) {
  const [copied, setCopied] = useState(false);

  if (!text) return null;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Nothing meaningful to recover into.
    }
  }

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? "Copied!" : label}
      className="opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity text-xs text-gray-400 dark:text-gray-500 hover:text-accent-600 dark:hover:text-accent-400 flex items-center gap-1 px-1"
    >
      {copied ? <CheckIcon /> : <CopyIcon />}
      {copied ? "Copied" : "Copy"}
    </button>
  );
}
