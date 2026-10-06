import { useState } from "react";
import { Link } from "react-router-dom";
import { timeAgo } from "../../lib/format";
import EditProjectModal from "./EditProjectModal";
import DeleteProjectModal from "./DeleteProjectModal";
import { iconForProjectType, gradientForProjectType } from "./projectVisuals";

// List-view counterpart to ProjectCard -- same data, one row per project instead of a card, for
// the grid/list view toggle on the Projects page.
export default function ProjectListRow({ project }) {
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const icon = iconForProjectType(project.project_type);
  const gradient = gradientForProjectType(project.project_type);

  return (
    <>
      <Link
        to={`/projects/${project.project_id}`}
        className="group flex items-center gap-4 bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 px-4 py-3 hover:border-transparent hover:shadow-md transition-all"
      >
        <div
          className={`w-10 h-10 rounded-lg bg-gradient-to-br ${gradient} flex items-center justify-center text-lg shadow-sm flex-shrink-0`}
        >
          {icon}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate group-hover:text-accent-700 dark:group-hover:text-accent-400 transition-colors">
            {project.project_name}
          </h3>
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
            Created by {project.created_by} &middot; {timeAgo(project.created_at)}
          </p>
        </div>

        <div className="hidden sm:flex flex-wrap gap-1.5 flex-shrink-0">
          {project.project_type && (
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300">
              {project.project_type}
            </span>
          )}
          {project.target_stack && (
            <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-accent-50 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300">
              {project.target_stack}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setShowEdit(true);
            }}
            title="Edit project"
            className="w-7 h-7 flex items-center justify-center rounded-full text-gray-400 dark:text-gray-500 hover:text-accent-600 dark:hover:text-accent-400 hover:bg-gray-100 dark:hover:bg-white/10"
          >
            ✎
          </button>
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setShowDelete(true);
            }}
            title="Delete project"
            className="w-7 h-7 flex items-center justify-center rounded-full text-gray-400 dark:text-gray-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-gray-100 dark:hover:bg-white/10"
          >
            &times;
          </button>
        </div>
      </Link>

      <EditProjectModal project={project} open={showEdit} onClose={() => setShowEdit(false)} />
      <DeleteProjectModal project={project} open={showDelete} onClose={() => setShowDelete(false)} />
    </>
  );
}
