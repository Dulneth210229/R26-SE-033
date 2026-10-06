import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { timeAgo } from "../../lib/format";
import EditProjectModal from "./EditProjectModal";
import DeleteProjectModal from "./DeleteProjectModal";
import { iconForProjectType, gradientForProjectType } from "./projectVisuals";

function CardMenu({ onEdit, onDelete }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    function handleClickOutside(event) {
      if (ref.current && !ref.current.contains(event.target)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  return (
    <div className="relative z-10" ref={ref}>
      <button
        type="button"
        onClick={(event) => {
          event.preventDefault();
          event.stopPropagation();
          setOpen((v) => !v);
        }}
        title="Project actions"
        className="w-7 h-7 flex items-center justify-center rounded-full bg-white/90 dark:bg-gray-800/90 text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 shadow-sm"
      >
        <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
          <path d="M10 5.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM10 11.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3zM10 17.5a1.5 1.5 0 100-3 1.5 1.5 0 000 3z" />
        </svg>
      </button>
      {open && (
        <div className="absolute right-0 mt-1 w-32 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg overflow-hidden">
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setOpen(false);
              onEdit();
            }}
            className="w-full text-left px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/5"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setOpen(false);
              onDelete();
            }}
            className="w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-500/10"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

export default function ProjectCard({ project }) {
  const gradient = gradientForProjectType(project.project_type);
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  return (
    <>
    <Link
      to={`/projects/${project.project_id}`}
      className="group relative block bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 overflow-hidden shadow-sm hover:shadow-xl hover:-translate-y-1 hover:border-transparent transition-all duration-200"
    >
      <div className={`h-1.5 bg-gradient-to-r ${gradient}`} />

      <div className="absolute top-2 right-2">
        <CardMenu onEdit={() => setShowEdit(true)} onDelete={() => setShowDelete(true)} />
      </div>

      <div className="p-5">
        <div
          className={`w-12 h-12 rounded-xl bg-gradient-to-br ${gradient} flex items-center justify-center text-xl shadow-sm flex-shrink-0`}
        >
          {iconForProjectType(project.project_type)}
        </div>

        <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100 mt-3 group-hover:text-accent-700 dark:group-hover:text-accent-400 transition-colors">
          {project.project_name}
        </h3>

        <div className="flex flex-wrap gap-1.5 mt-2.5">
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

        <div className="flex items-center justify-between mt-4 pt-3 border-t border-gray-100 dark:border-gray-800">
          <p className="text-xs text-gray-400 dark:text-gray-500">Created by {project.created_by}</p>
          <p className="text-xs text-gray-400 dark:text-gray-500">{timeAgo(project.created_at)}</p>
        </div>
      </div>
    </Link>

    <EditProjectModal project={project} open={showEdit} onClose={() => setShowEdit(false)} />
    <DeleteProjectModal project={project} open={showDelete} onClose={() => setShowDelete(false)} />
    </>
  );
}
