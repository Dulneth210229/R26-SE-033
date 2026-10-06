const STYLES = {
  pending: "bg-yellow-100 text-yellow-800 dark:bg-yellow-500/15 dark:text-yellow-300",
  approved: "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-300",
  rejected: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  revision_requested: "bg-orange-100 text-orange-800 dark:bg-orange-500/15 dark:text-orange-300",
  not_started: "bg-gray-100 text-gray-500 dark:bg-white/10 dark:text-gray-400",
  action_required: "bg-blue-100 text-blue-800 dark:bg-blue-500/15 dark:text-blue-300",
  awaiting_review: "bg-yellow-100 text-yellow-800 dark:bg-yellow-500/15 dark:text-yellow-300",
  processing: "bg-accent-100 text-accent-800 dark:bg-accent-500/15 dark:text-accent-300",
  possibly_stuck: "bg-red-100 text-red-800 dark:bg-red-500/15 dark:text-red-300",
  // Feature-level status (feature_status, see app/core/enums.py's FeatureStatus) -- a distinct
  // namespace from the artifact/stage statuses above, each given its own clearly different color
  // so a feature card's status is visually distinguishable at a glance from a stage's own status.
  created: "bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-300",
  in_progress: "bg-blue-100 text-blue-700 dark:bg-blue-500/15 dark:text-blue-300",
  completed: "bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300",
  failed: "bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300",
};

const LABELS = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  revision_requested: "Revision requested",
  not_started: "Not started",
  action_required: "Action required",
  awaiting_review: "Awaiting review",
  processing: "Processing...",
  possibly_stuck: "Possibly stuck",
  created: "Created",
  in_progress: "In Progress",
  completed: "Completed",
  failed: "Failed",
};

export default function StatusBadge({ status, label: labelOverride }) {
  const style = STYLES[status] || "bg-gray-100 text-gray-600 dark:bg-white/10 dark:text-gray-300";
  const label = labelOverride || LABELS[status] || status;

  return (
    <span className={`inline-block whitespace-nowrap px-2 py-1 text-xs font-semibold rounded-full ${style}`}>
      {label}
    </span>
  );
}
