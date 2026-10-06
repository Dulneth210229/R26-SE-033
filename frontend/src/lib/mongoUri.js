// Lightweight client-side check mirroring the backend's own MONGODB_URI_PATTERN
// (app/agents/coder_agent/env_uri.py) -- the backend's 400 is the real guard, this is just
// instant feedback so a typo'd/malformed value doesn't get silently swallowed (e.g. as ordinary
// human_comment planning text in the UI/UX-approval popup) with zero indication anything went
// wrong.
export function looksLikeMongoUri(value) {
  return /^mongodb(\+srv)?:\/\/\S+/i.test(value.trim());
}
