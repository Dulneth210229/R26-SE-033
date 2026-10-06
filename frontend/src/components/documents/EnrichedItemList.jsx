// Renders SRS requirement-like arrays (functional_requirements, non_functional_requirements,
// acceptance_criteria, validation_rules, user_stories) as cards instead of a generic table --
// specifically so Domain Agent enrichment is visually obvious, not buried in a raw field.
// user_stories is the one shape that differs ({id, role, goal, benefit}, no "description") --
// see primaryText() below. Real Enhanced SRS data
// marks its own changes: an item with modified_by_domain_agent=true carries the pre-enrichment
// original_description alongside the enriched one; an item with origin="domain_agent" is a whole
// new item the Domain Agent added that never existed in the plain SRS. Color convention matches
// DomainImprovementsViewer (green=addition, blue=modification) so the same meaning reads the same
// way everywhere in the app.
//
// Permanently read-only -- the SRS may only be changed by explicitly chatting with the
// Requirement Agent (RequirementConversationChat.jsx), never by editing this view directly. This
// component previously also rendered an inline edit/remove/add UI (per-item pencil, textarea,
// Save/Cancel); that was removed by direct user request. Only the highlighting/card rendering
// below survives.
function Citation({ citation }) {
  if (!citation) return null;
  return (
    <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1.5 italic">
      Source: {citation.source_document}
      {citation.chunk_id ? ` (${citation.chunk_id})` : ""}
    </p>
  );
}

function ItemCard({ item, field }) {
  const isNew = item.origin === "domain_agent";
  const isModified = Boolean(item.modified_by_domain_agent);
  const isUserStory = field === "user_stories";

  const colorClasses = isNew
    ? "border-green-200 dark:border-green-500/30 bg-green-50 dark:bg-green-500/10"
    : isModified
      ? "border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-500/10"
      : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900";

  const tags = [item.priority, item.category].filter(Boolean);

  return (
    <div className={`rounded-lg border p-3 ${colorClasses}`}>
      <div className="flex items-center justify-between gap-2 mb-1">
        <div className="flex items-center gap-2">
          {item.id && <span className="text-xs font-bold text-gray-500 dark:text-gray-400">{item.id}</span>}
          {tags.map((tag) => (
            <span key={tag} className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300">
              {tag}
            </span>
          ))}
        </div>
        {isNew && (
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-green-600 text-white uppercase tracking-wide">
            Added by Domain Agent
          </span>
        )}
        {isModified && (
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-600 text-white uppercase tracking-wide">
            Enhanced by Domain Agent
          </span>
        )}
      </div>

      {isModified && item.original_description && (
        <p className="text-xs text-gray-400 dark:text-gray-500 line-through mb-0.5">{item.original_description}</p>
      )}
      {isUserStory ? (
        <p className="text-sm text-gray-800 dark:text-gray-200">
          As a <span className="font-semibold">{item.role || "user"}</span>, I want to{" "}
          <span className="font-semibold">{item.goal || "use the feature"}</span>, so that{" "}
          {item.benefit || "achieve the business goal"}.
        </p>
      ) : (
        <p className="text-sm text-gray-800 dark:text-gray-200">{item.description}</p>
      )}

      <Citation citation={item.domain_citation} />
    </div>
  );
}

export default function EnrichedItemList({ items, field }) {
  if (!Array.isArray(items) || items.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {items.map((item, index) => (
        <ItemCard key={item.id || index} item={item} field={field} />
      ))}
    </div>
  );
}
