// Shared icon/gradient-per-project-type lookup -- used by both ProjectCard (grid view) and
// ProjectListRow (list view) so a project's visual identity stays the same regardless of which
// view is currently selected.
export const TYPE_ICONS = {
  "e-commerce": "🛒",
  saas: "☁️",
  social: "💬",
  fintech: "💳",
  healthcare: "🏥",
  education: "🎓",
};

export const TYPE_GRADIENTS = {
  "e-commerce": "from-orange-400 to-pink-500",
  saas: "from-sky-400 to-indigo-500",
  social: "from-fuchsia-400 to-purple-500",
  fintech: "from-emerald-400 to-teal-500",
  healthcare: "from-rose-400 to-red-500",
  education: "from-amber-400 to-orange-500",
};

export function iconForProjectType(projectType) {
  return TYPE_ICONS[(projectType || "").toLowerCase()] || "📦";
}

export function gradientForProjectType(projectType) {
  return TYPE_GRADIENTS[(projectType || "").toLowerCase()] || "from-accent-400 to-accent-600";
}
