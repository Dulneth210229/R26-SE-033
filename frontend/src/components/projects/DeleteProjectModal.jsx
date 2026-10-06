import { useDeleteProject } from "../../hooks/useProjects";
import Modal from "../common/Modal";
import ErrorBanner from "../common/ErrorBanner";

// Delete-in-a-modal, per direct user request: a real "are you sure" confirmation before an
// irreversible, cascading delete (features, artifacts, knowledge documents, and generated code
// all go with it).
export default function DeleteProjectModal({ project, open, onClose, onDeleted }) {
  const deleteProject = useDeleteProject();

  async function handleConfirm() {
    await deleteProject.mutateAsync(project.project_id);
    onDeleted?.();
    onClose();
  }

  return (
    <Modal open={open} onClose={onClose} title="Delete Project">
      <div className="flex flex-col gap-4">
        <ErrorBanner error={deleteProject.error} fallback="Failed to delete project." />

        <p className="text-sm text-gray-700 dark:text-gray-300">
          Are you sure you want to delete <strong>{project?.project_name}</strong>? This will
          permanently delete every feature, artifact, and uploaded domain knowledge document, and
          all generated code for this project.
        </p>
        <p className="text-sm font-semibold text-red-600 dark:text-red-400">This cannot be undone.</p>

        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={deleteProject.isPending}
            className="bg-gray-200 hover:bg-gray-300 dark:bg-white/10 dark:hover:bg-white/20 disabled:opacity-50 text-gray-800 dark:text-gray-200 font-semibold py-2 px-4 rounded"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={deleteProject.isPending}
            className="bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
          >
            {deleteProject.isPending ? "Deleting..." : "Delete Project"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
