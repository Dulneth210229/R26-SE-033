import clsx from "clsx";
import { useGraphStatus } from "../../hooks/usePipeline";
import { useFeatureArtifacts } from "../../hooks/useArtifacts";
import { deriveStageStatus, STATUS } from "../../lib/deriveStageStatus";
import { deriveCurrentStage } from "../../lib/deriveCurrentStage";
import { SELECTABLE_AGENT_STAGES, STAGE_LABELS } from "../../lib/pipelineStages";
import StatusBadge from "../common/StatusBadge";

const DOT_STYLES = {
  approved: "bg-green-500",
  awaiting_review: "bg-yellow-500",
  action_required: "bg-blue-500",
  processing: "bg-accent-500 animate-pulse",
  possibly_stuck: "bg-red-500",
  rejected: "bg-red-500",
  not_started: "bg-gray-300",
};

// Compact task-list row, like Cursor's left task rail -- one line for the name, a status dot +
// current-stage label instead of a full pipeline nav (that's the middle/right panels' job now).
// Independently fetches graph-status/artifacts for THIS feature only, same hooks the old
// FeatureDetailPage used -- acceptable per-row cost for the feature counts this app deals with.
export default function FeatureListItem({ feature, isSelected, onSelect, onDeleteClick }) {
  const { data: graphStatus } = useGraphStatus(feature.feature_id);
  const { data: artifacts } = useFeatureArtifacts(feature.feature_id);

  const allArtifacts = artifacts || [];
  const stageStatuses = {};
  for (const stage of SELECTABLE_AGENT_STAGES) {
    stageStatuses[stage] = deriveStageStatus({ stage, graphStatus, artifacts: allArtifacts });
  }
  // deriveCurrentStage returns undefined once every stage is APPROVED (a fully-completed
  // feature) -- fall back to the LAST stage, not the first, so a finished feature's row doesn't
  // misreport its current stage as "Requirement" (the same fix applied to
  // WorkspaceSelectionContext's own identical computation).
  const currentStage =
    deriveCurrentStage(graphStatus, stageStatuses) ?? SELECTABLE_AGENT_STAGES[SELECTABLE_AGENT_STAGES.length - 1];
  const currentStatus = stageStatuses[currentStage] || STATUS.NOT_STARTED;

  return (
    <div
      className={clsx(
        "relative group w-full rounded-md transition-colors border",
        isSelected
          ? "bg-accent-50 dark:bg-accent-500/10 border-accent-200 dark:border-accent-500/30"
          : "border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-white/5"
      )}
    >
      <button type="button" onClick={onSelect} className="w-full text-left px-3 py-2.5">
        <div className="flex items-center gap-2 min-w-0 pr-6">
          <span className={clsx("w-2 h-2 rounded-full flex-shrink-0", DOT_STYLES[currentStatus] || "bg-gray-300")} />
          <span
            className={clsx(
              "text-sm font-semibold truncate",
              isSelected ? "text-accent-900 dark:text-accent-200" : "text-gray-800 dark:text-gray-200"
            )}
          >
            {feature.feature_name}
          </span>
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5 pl-4 truncate">{feature.feature_description}</p>
        <div className="pl-4 mt-1.5 flex items-center gap-1.5 min-w-0">
          <span className="text-[11px] text-gray-400 dark:text-gray-500 truncate min-w-0">
            {STAGE_LABELS[currentStage]}
          </span>
          <span className="flex-shrink-0">
            <StatusBadge status={currentStatus} />
          </span>
        </div>
      </button>
      {onDeleteClick && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onDeleteClick(feature);
          }}
          title="Delete feature"
          className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 focus:opacity-100 transition-opacity text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 text-xs font-semibold px-1"
        >
          &times;
        </button>
      )}
    </div>
  );
}
