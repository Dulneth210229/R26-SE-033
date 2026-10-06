import { useState } from "react";

function EyeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-4 h-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M2.5 12S6 5 12 5s9.5 7 9.5 7-3.5 7-9.5 7-9.5-7-9.5-7Z" />
      <circle cx="12" cy="12" r="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-4 h-4">
      <path strokeLinecap="round" strokeLinejoin="round" d="M3 3l18 18M10.6 10.6a2.5 2.5 0 0 0 3.5 3.5M6.7 6.7C4.5 8.1 2.5 12 2.5 12s3.5 7 9.5 7c1.8 0 3.3-.6 4.6-1.4M9.9 5.2A9.3 9.3 0 0 1 12 5c6 0 9.5 7 9.5 7-.5.9-1.3 2.1-2.4 3.2" />
    </svg>
  );
}

// Drop-in replacement for <input type="password">: same controlled-input props, plus a
// show/hide toggle (eye/eye-slash icon) inside the field's right edge. Direct user request,
// scoped to Login/Signup -- built as a shared component so any other password field (e.g.
// Profile's Change Password form) can adopt it later with a one-line change.
export default function PasswordInput({ className, ...inputProps }) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="relative">
      <input
        {...inputProps}
        type={visible ? "text" : "password"}
        className={className ? `${className} pr-9` : "pr-9"}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        tabIndex={-1}
        title={visible ? "Hide password" : "Show password"}
        className="absolute inset-y-0 right-0 w-9 flex items-center justify-center text-gray-400 hover:text-gray-600 dark:text-gray-500 dark:hover:text-gray-300"
      >
        {visible ? <EyeOffIcon /> : <EyeIcon />}
      </button>
    </div>
  );
}
