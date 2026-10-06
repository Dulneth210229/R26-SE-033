// Reuses StatusBadge.jsx's exact existing Tailwind class strings (red/orange/yellow), not new
// colors -- critical/moderate/warning is a distinct namespace from that component's
// approval-status vocabulary, so this stays a separate small component rather than overloading
// StatusBadge's STYLES/LABELS with severity keys that would collide in meaning ("pending" reads
// very differently for an approval than it would for a vulnerability).
const STYLES = {
  critical: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  moderate: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  warning: "bg-yellow-100 text-yellow-800 dark:bg-yellow-500/15 dark:text-yellow-300",
};

const LABELS = {
  critical: "Critical",
  moderate: "Moderate",
  warning: "Warning",
};

export default function SeverityBadge({ tier }) {
  const style = STYLES[tier] || "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300";
  const label = LABELS[tier] || tier;

  return (
    <span className={`inline-block px-2 py-1 text-xs font-semibold rounded-full ${style}`}>{label}</span>
  );
}
