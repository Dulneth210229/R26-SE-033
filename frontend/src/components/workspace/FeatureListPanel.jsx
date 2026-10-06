import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProject } from "../../hooks/useProjects";
import { useDeleteFeature, useFeatures } from "../../hooks/useFeatures";
import { useWorkspaceSelection } from "./WorkspaceSelectionContext";
import FeatureListItem from "./FeatureListItem";
import DomainKnowledgePanel from "./DomainKnowledgePanel";
import DatabaseConnectionPanel from "./DatabaseConnectionPanel";
import CreateFeatureForm from "../features/CreateFeatureForm";
import Modal from "../common/Modal";
import ConfirmDialog from "../common/ConfirmDialog";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

// Matches ThemeSwitcher.jsx's own established inline-icon convention (viewBox 24, stroke
// currentColor, w-4 h-4) so these two buttons read as a consistent part of the same design
// system rather than a one-off style.
function KnowledgeIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 flex-shrink-0">
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5" />
      <path strokeLinecap="round" strokeLinejoin="round" d="M4 5.5v15A2.5 2.5 0 0 0 6.5 23H20v-3" />
    </svg>
  );
}

function DatabaseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="w-3.5 h-3.5 flex-shrink-0">
      <ellipse cx="12" cy="5" rx="7" ry="3" />
      <path strokeLinecap="round" d="M5 5v6c0 1.66 3.13 3 7 3s7-1.34 7-3V5" />
      <path strokeLinecap="round" d="M5 11v6c0 1.66 3.13 3 7 3s7-1.34 7-3v-6" />
    </svg>
  );
}

// Left panel: this project's features/tasks, like Cursor's task list. Replaces the old
// ProjectDetailPage's feature grid -- clicking a row retargets the whole workspace (middle chat
// + right output) at that feature, rather than navigating to a separate page.
export default function FeatureListPanel({ projectId }) {
  const { data: project } = useProject(projectId);
  const { data: featuresData, isLoading, error } = useFeatures(projectId);
  const features = featuresData || [];
  const { selectedFeatureId, selectFeature } = useWorkspaceSelection();
  const navigate = useNavigate();
  const [showCreate, setShowCreate] = useState(false);
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [showDatabaseConnection, setShowDatabaseConnection] = useState(false);
  const [deletingFeature, setDeletingFeature] = useState(null);
  const deleteFeature = useDeleteFeature(projectId);

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800">
      <div className="flex-shrink-0 p-3 border-b border-gray-100 dark:border-gray-800">
        <h2 className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate" title={project?.project_name}>
          {project?.project_name || "..."}
        </h2>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">{project?.target_stack}</p>
        <div className="flex items-center gap-2 mt-2">
          <button
            onClick={() => setShowKnowledge(true)}
            title="Domain Knowledge"
            className="flex-1 min-w-0 text-xs font-semibold bg-white dark:bg-white/10 hover:bg-gray-50 dark:hover:bg-white/20 active:bg-gray-100 dark:active:bg-white/25 border border-gray-300 dark:border-gray-600 hover:border-accent-400 dark:hover:border-accent-500/50 text-gray-700 dark:text-gray-200 hover:text-accent-700 dark:hover:text-accent-300 transition-all hover:shadow-sm px-2.5 py-1.5 rounded-md inline-flex items-center justify-center gap-1.5"
          >
            <KnowledgeIcon />
            <span className="truncate">Domain Knowledge</span>
          </button>
          <button
            onClick={() => setShowDatabaseConnection(true)}
            title="Database Connection"
            className="flex-1 min-w-0 text-xs font-semibold bg-white dark:bg-white/10 hover:bg-gray-50 dark:hover:bg-white/20 active:bg-gray-100 dark:active:bg-white/25 border border-gray-300 dark:border-gray-600 hover:border-accent-400 dark:hover:border-accent-500/50 text-gray-700 dark:text-gray-200 hover:text-accent-700 dark:hover:text-accent-300 transition-all hover:shadow-sm px-2.5 py-1.5 rounded-md inline-flex items-center justify-center gap-1.5"
          >
            <DatabaseIcon />
            <span className="truncate">Database Connection</span>
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2">
        <div className="flex items-center justify-between px-1 pb-2">
          <h3 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide">Features</h3>
          <button
            onClick={() => setShowCreate(true)}
            className="text-xs font-semibold text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300"
          >
            + New
          </button>
        </div>

        <ErrorBanner error={error} fallback="Failed to load features." />

        {isLoading ? (
          <LoadingSpinner label="Loading features..." />
        ) : features.length === 0 ? (
          <p className="text-xs text-gray-400 dark:text-gray-500 italic px-1">No features yet. Create one to get started.</p>
        ) : (
          <div className="flex flex-col gap-1">
            {features.map((feature) => (
              <FeatureListItem
                key={feature.feature_id}
                feature={feature}
                isSelected={feature.feature_id === selectedFeatureId}
                onSelect={() => selectFeature(feature.feature_id)}
                onDeleteClick={setDeletingFeature}
              />
            ))}
          </div>
        )}
      </div>

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Feature">
        <CreateFeatureForm
          projectId={projectId}
          onCancel={() => setShowCreate(false)}
          onCreated={(feature) => {
            setShowCreate(false);
            selectFeature(feature.feature_id);
          }}
        />
      </Modal>

      <Modal open={showKnowledge} onClose={() => setShowKnowledge(false)} title="Domain Knowledge" size="wide">
        <DomainKnowledgePanel projectId={projectId} />
      </Modal>

      <Modal
        open={showDatabaseConnection}
        onClose={() => setShowDatabaseConnection(false)}
        title="Database Connection"
        size="wide"
      >
        <DatabaseConnectionPanel projectId={projectId} />
      </Modal>

      <ConfirmDialog
        open={Boolean(deletingFeature)}
        onClose={() => {
          if (!deleteFeature.isPending) setDeletingFeature(null);
        }}
        onConfirm={async () => {
          await deleteFeature.mutateAsync(deletingFeature.feature_id);
          if (deletingFeature.feature_id === selectedFeatureId) {
            navigate(`/projects/${projectId}`);
          }
          setDeletingFeature(null);
        }}
        title="Delete this feature?"
        message={`This permanently deletes "${deletingFeature?.feature_name}" and everything scoped to it -- every artifact, approval, and conversation. This cannot be undone.`}
        confirmLabel="Delete Feature"
        confirmingLabel="Deleting..."
        confirming={deleteFeature.isPending}
        error={deleteFeature.error}
        errorFallback="Failed to delete feature."
      />
    </div>
  );
}
