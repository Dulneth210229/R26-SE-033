// Small shared formatting helpers -- kept dependency-free (no date library) since the app only
// ever needs a handful of simple, human-readable formats.
export function timeAgo(iso) {
  if (!iso) return "";

  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 60) return "just now";

  const units = [
    ["year", 31536000],
    ["month", 2592000],
    ["week", 604800],
    ["day", 86400],
    ["hour", 3600],
    ["minute", 60],
  ];

  for (const [label, seconds] of units) {
    const value = Math.floor(diffSec / seconds);
    if (value >= 1) return `${value} ${label}${value === 1 ? "" : "s"} ago`;
  }

  return "just now";
}
