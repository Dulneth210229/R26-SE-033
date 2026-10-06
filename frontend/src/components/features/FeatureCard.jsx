import { Link } from "react-router-dom";
import StatusBadge from "../common/StatusBadge";

const STATUS_ACCENT = {
  created: "border-l-slate-300",
  in_progress: "border-l-blue-400",
  completed: "border-l-green-400",
  failed: "border-l-red-400",
};

const STATUS_ICON = {
  created: "🆕",
  in_progress: "⚙️",
  completed: "✅",
  failed: "⚠️",
};

export default function FeatureCard({ projectId, feature }) {
  return (
    <Link
      to={`/projects/${projectId}/features/${feature.feature_id}`}
      className={`group block bg-white rounded-lg shadow-sm border border-gray-200 border-l-4 ${
        STATUS_ACCENT[feature.feature_status] || "border-l-gray-300"
      } p-5 hover:shadow-lg hover:-translate-y-0.5 transition-all`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-lg flex-shrink-0">{STATUS_ICON[feature.feature_status] || "📄"}</span>
          <h3 className="text-lg font-semibold text-gray-900 truncate">{feature.feature_name}</h3>
        </div>
        <span className="text-gray-300 group-hover:text-accent-500 transition-colors text-lg flex-shrink-0">&rarr;</span>
      </div>
      <p className="text-sm text-gray-500 mt-1 line-clamp-2">{feature.feature_description}</p>
      <div className="mt-3">
        <StatusBadge status={feature.feature_status} />
      </div>
    </Link>
  );
}
