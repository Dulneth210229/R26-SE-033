import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useProjects } from "../hooks/useProjects";
import PageHeader from "../components/layout/PageHeader";
import ProjectCard from "../components/projects/ProjectCard";
import ProjectListRow from "../components/projects/ProjectListRow";
import CreateProjectForm from "../components/projects/CreateProjectForm";
import Modal from "../components/common/Modal";
import LoadingSpinner from "../components/common/LoadingSpinner";
import ErrorBanner from "../components/common/ErrorBanner";

const THIRTY_DAYS_MS = 30 * 24 * 60 * 60 * 1000;

const SORT_OPTIONS = [
  { value: "recent", label: "Recently Updated" },
  { value: "name", label: "Name (A-Z)" },
  { value: "oldest", label: "Oldest First" },
];

function FolderIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
      <path d="M2 6a2 2 0 012-2h4.5l1.5 1.5H16a2 2 0 012 2V14a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}

function CodeIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-5 h-5">
      <path strokeLinecap="round" strokeLinejoin="round" d="M7 5L2.5 10 7 15M13 5l4.5 5-4.5 5" />
    </svg>
  );
}

function StackIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-5 h-5">
      <path d="M10 2l8 4-8 4-8-4 8-4z" />
      <path d="M2 10l8 4 8-4v2l-8 4-8-4v-2z" />
      <path d="M2 14l8 4 8-4v2l-8 4-8-4v-2z" />
    </svg>
  );
}

function ClockIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" className="w-5 h-5">
      <circle cx="10" cy="10" r="7.5" />
      <path strokeLinecap="round" d="M10 5.5V10l3 2" />
    </svg>
  );
}

function GridIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <rect x="2" y="2" width="7" height="7" rx="1.5" />
      <rect x="11" y="2" width="7" height="7" rx="1.5" />
      <rect x="2" y="11" width="7" height="7" rx="1.5" />
      <rect x="11" y="11" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function ListIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="currentColor" className="w-4 h-4">
      <rect x="2" y="3" width="16" height="3" rx="1" />
      <rect x="2" y="8.5" width="16" height="3" rx="1" />
      <rect x="2" y="14" width="16" height="3" rx="1" />
    </svg>
  );
}

function StatCard({ icon, iconClass, value, label, sublabel }) {
  return (
    <div className="flex-1 min-w-[180px] bg-white dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-gray-800 p-4 flex items-start gap-3">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${iconClass}`}>{icon}</div>
      <div className="min-w-0">
        <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 leading-tight">{value}</p>
        <p className="text-xs font-semibold text-gray-600 dark:text-gray-300">{label}</p>
        {sublabel && <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">{sublabel}</p>}
      </div>
    </div>
  );
}

function FilterSelect({ value, onChange, options, ariaLabel }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-label={ariaLabel}
        className="appearance-none text-sm border border-gray-300 dark:border-gray-700 rounded-lg pl-3 pr-8 py-2 bg-white dark:bg-gray-900 text-gray-700 dark:text-gray-200 focus:outline-none focus:border-accent-500 focus:ring-1 focus:ring-accent-500"
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>
      <svg
        viewBox="0 0 20 20"
        fill="currentColor"
        className="w-4 h-4 absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 dark:text-gray-500 pointer-events-none"
      >
        <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
      </svg>
    </div>
  );
}

export default function ProjectListPage() {
  const { data: projects, isLoading, error } = useProjects();
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [sortBy, setSortBy] = useState("recent");
  const [viewMode, setViewMode] = useState("grid");
  const navigate = useNavigate();

  const stats = useMemo(() => {
    if (!projects?.length) return null;
    const recentlyUpdated = projects.filter((p) => {
      const stamp = p.updated_at || p.created_at;
      return stamp && Date.now() - new Date(stamp).getTime() <= THIRTY_DAYS_MS;
    }).length;
    return {
      total: projects.length,
      types: new Set(projects.map((p) => p.project_type).filter(Boolean)).size,
      recentlyUpdated,
    };
  }, [projects]);

  const typeOptions = useMemo(() => {
    const values = [...new Set((projects || []).map((p) => p.project_type).filter(Boolean))].sort();
    return [{ value: "all", label: "All Types" }, ...values.map((v) => ({ value: v, label: v }))];
  }, [projects]);

  const filtered = useMemo(() => {
    if (!projects) return [];
    const q = search.trim().toLowerCase();

    let result = projects.filter((p) => {
      if (typeFilter !== "all" && p.project_type !== typeFilter) return false;
      if (!q) return true;
      return [p.project_name, p.project_type, p.target_stack].filter(Boolean).some((v) => v.toLowerCase().includes(q));
    });

    result = [...result].sort((a, b) => {
      if (sortBy === "name") return (a.project_name || "").localeCompare(b.project_name || "");
      if (sortBy === "oldest") return new Date(a.created_at || 0) - new Date(b.created_at || 0);
      return new Date(b.updated_at || b.created_at || 0) - new Date(a.updated_at || a.created_at || 0);
    });

    return result;
  }, [projects, search, typeFilter, sortBy]);

  return (
    <div className="h-full overflow-y-auto pr-1.5 flex flex-col gap-6">
      {/* Overview section -- the "at a glance" dashboard summary. */}
      <section>
        <PageHeader
          title="Projects"
          subtitle={
            projects?.length
              ? `${projects.length} application${projects.length === 1 ? "" : "s"} AutoForge is building.`
              : "The applications AutoForge is building."
          }
          actions={
            <button
              onClick={() => setShowCreate(true)}
              className="bg-gradient-to-r from-accent-600 to-accent-500 hover:from-accent-700 hover:to-accent-600 text-white font-semibold py-2 px-4 rounded-lg shadow-sm hover:shadow-md transition-all"
            >
              + New Project
            </button>
          }
        />

        <ErrorBanner error={error} fallback="Failed to load projects." />

        {stats && (
          <div className="flex flex-wrap gap-3">
            <StatCard
              icon={<FolderIcon />}
              iconClass="bg-violet-500/15 text-violet-500 dark:bg-violet-500/20"
              value={stats.total}
              label="Total Projects"
              sublabel="Active applications"
            />
            <StatCard
              icon={<CodeIcon />}
              iconClass="bg-fuchsia-500/15 text-fuchsia-500 dark:bg-fuchsia-500/20"
              value={stats.types}
              label="Project Types"
              sublabel={[...new Set(projects.map((p) => p.project_type).filter(Boolean))].join(", ") || "--"}
            />
            <StatCard
              icon={<StackIcon />}
              iconClass="bg-blue-500/15 text-blue-500 dark:bg-blue-500/20"
              value="Next.js"
              label="Tech Stack"
              sublabel="The only stack AutoForge builds"
            />
            <StatCard
              icon={<ClockIcon />}
              iconClass="bg-emerald-500/15 text-emerald-500 dark:bg-emerald-500/20"
              value={stats.recentlyUpdated}
              label="Recently Updated"
              sublabel="In the last 30 days"
            />
          </div>
        )}
      </section>

      {/* Browse section -- search/filter/sort/view-mode toolbar, then the actual project list. */}
      <section className="flex-1 min-h-0">
        {isLoading ? (
          <LoadingSpinner label="Loading projects..." />
        ) : projects.length === 0 ? (
          <div className="bg-white dark:bg-gray-900 rounded-xl border border-dashed border-gray-300 dark:border-gray-700 p-12 text-center">
            <p className="text-4xl mb-3">🚀</p>
            <p className="text-gray-700 dark:text-gray-200 font-semibold">No projects yet</p>
            <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">Create your first project to start the pipeline.</p>
            <button
              onClick={() => setShowCreate(true)}
              className="mt-4 bg-accent-600 hover:bg-accent-700 text-white font-semibold py-2 px-4 rounded"
            >
              + New Project
            </button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-3 mb-4">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search projects..."
                className="flex-1 min-w-[200px] text-sm border border-gray-300 dark:border-gray-700 rounded-lg px-4 py-2 focus:outline-none focus:border-accent-500 focus:ring-1 focus:ring-accent-500 bg-white dark:bg-gray-900 dark:text-gray-100"
              />
              <FilterSelect value={typeFilter} onChange={setTypeFilter} options={typeOptions} ariaLabel="Filter by project type" />
              <FilterSelect value={sortBy} onChange={setSortBy} options={SORT_OPTIONS} ariaLabel="Sort projects" />

              <div className="flex items-center border border-gray-300 dark:border-gray-700 rounded-lg overflow-hidden flex-shrink-0">
                <button
                  type="button"
                  onClick={() => setViewMode("grid")}
                  title="Grid view"
                  className={`w-8 h-8 flex items-center justify-center ${
                    viewMode === "grid"
                      ? "bg-accent-600 text-white"
                      : "bg-white dark:bg-gray-900 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
                  }`}
                >
                  <GridIcon />
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("list")}
                  title="List view"
                  className={`w-8 h-8 flex items-center justify-center border-l border-gray-300 dark:border-gray-700 ${
                    viewMode === "list"
                      ? "bg-accent-600 text-white"
                      : "bg-white dark:bg-gray-900 text-gray-400 dark:text-gray-500 hover:text-gray-600 dark:hover:text-gray-300"
                  }`}
                >
                  <ListIcon />
                </button>
              </div>
            </div>

            {filtered.length === 0 ? (
              <p className="text-sm text-gray-400 dark:text-gray-500 italic">No projects match your filters.</p>
            ) : viewMode === "grid" ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {filtered.map((project, index) => (
                  <div
                    key={project.project_id}
                    className="animate-[fadeInUp_0.35s_ease-out_backwards]"
                    style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
                  >
                    <ProjectCard project={project} />
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex flex-col gap-2">
                {filtered.map((project, index) => (
                  <div
                    key={project.project_id}
                    className="animate-[fadeInUp_0.35s_ease-out_backwards]"
                    style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
                  >
                    <ProjectListRow project={project} />
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </section>

      <Modal open={showCreate} onClose={() => setShowCreate(false)} title="Create Project">
        <CreateProjectForm
          onCancel={() => setShowCreate(false)}
          onCreated={(project) => {
            setShowCreate(false);
            navigate(`/projects/${project.project_id}`);
          }}
        />
      </Modal>

      <style>{`
        @keyframes fadeInUp {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
