import { useEffect, useState } from "react";
import { useUpdateProject } from "../../hooks/useProjects";
import Modal from "../common/Modal";
import ErrorBanner from "../common/ErrorBanner";

// Edit-in-a-modal, per direct user request: change project details, then an explicit "Save
// Changes" action persists them -- nothing is written until the user asks for it.
export default function EditProjectModal({ project, open, onClose }) {
  const [projectName, setProjectName] = useState("");
  const [projectType, setProjectType] = useState("");
  const [targetStack, setTargetStack] = useState("");
  const updateProject = useUpdateProject(project?.project_id);

  // Re-seed the form from the current project every time the modal opens, so a previous
  // edit/cancel never leaks into the next time it's opened.
  useEffect(() => {
    if (open && project) {
      setProjectName(project.project_name || "");
      setProjectType(project.project_type || "");
      setTargetStack(project.target_stack || "");
    }
  }, [open, project]);

  async function handleSubmit(event) {
    event.preventDefault();
    await updateProject.mutateAsync({
      project_name: projectName.trim(),
      project_type: projectType.trim(),
      target_stack: targetStack.trim(),
    });
    onClose();
  }

  return (
    <Modal open={open} onClose={onClose} title="Edit Project">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <ErrorBanner error={updateProject.error} fallback="Failed to save changes." />

        <div>
          <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Project Name</label>
          <input
            required
            value={projectName}
            onChange={(event) => setProjectName(event.target.value)}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
        </div>

        <div>
          <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Project Type</label>
          <input
            required
            value={projectType}
            onChange={(event) => setProjectType(event.target.value)}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
        </div>

        <div>
          <label className="block text-sm font-semibold mb-1 text-gray-900 dark:text-gray-200">Target Stack</label>
          <input
            value={targetStack}
            onChange={(event) => setTargetStack(event.target.value)}
            className="w-full p-2 text-sm border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
          />
        </div>

        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            className="bg-gray-200 hover:bg-gray-300 dark:bg-white/10 dark:hover:bg-white/20 text-gray-800 dark:text-gray-200 font-semibold py-2 px-4 rounded"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={updateProject.isPending}
            className="bg-accent-600 hover:bg-accent-700 disabled:opacity-50 text-white font-semibold py-2 px-4 rounded"
          >
            {updateProject.isPending ? "Saving..." : "Save Changes"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
