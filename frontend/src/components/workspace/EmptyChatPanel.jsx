import { useState } from "react";
import Modal from "../common/Modal";
import CreateFeatureForm from "../features/CreateFeatureForm";
import { useWorkspaceSelection } from "./WorkspaceSelectionContext";

// Shown in the middle (chat) panel only for a genuinely brand-new project with zero features --
// the plain "Select or create a feature to start." text this replaced looked broken/unfinished
// (a real user report: "the UI is almost empty"), especially next to a completely blank right
// panel. This keeps the same rounded-panel chrome every other panel uses, but with a real,
// friendly onboarding CTA that opens the exact same create-feature flow as the left panel's
// "+ New" link -- a second, independent trigger for the same Modal/CreateFeatureForm combo, not a
// new creation path.
export default function EmptyChatPanel({ projectId }) {
  const [showCreate, setShowCreate] = useState(false);
  const { selectFeature } = useWorkspaceSelection();

  return (
    <div className="h-full flex flex-col items-center justify-center gap-3 bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-6 text-center">
      <div className="w-12 h-12 rounded-full bg-accent-50 dark:bg-accent-500/10 flex items-center justify-center flex-shrink-0">
        <svg viewBox="0 0 24 24" fill="none" className="w-6 h-6 text-accent-500">
          <path
            d="M4 5.5A2.5 2.5 0 016.5 3h11A2.5 2.5 0 0120 5.5v8a2.5 2.5 0 01-2.5 2.5H10l-4.5 4v-4H6.5A2.5 2.5 0 014 13.5v-8z"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinejoin="round"
          />
        </svg>
      </div>

      <div>
        <p className="text-sm font-semibold text-gray-900 dark:text-gray-100">No feature yet</p>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-1 max-w-xs">
          Create your first feature to start talking to the Requirement Agent and building out this
          project.
        </p>
      </div>

      <button
        onClick={() => setShowCreate(true)}
        className="bg-accent-600 hover:bg-accent-700 text-white text-sm font-semibold px-4 py-2 rounded-md"
      >
        + Create your first feature
      </button>

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
    </div>
  );
}
