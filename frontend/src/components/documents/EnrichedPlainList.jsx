// Highlight version of a plain bullet list (see DocumentValue's own string-array rendering) for
// SRS sections that have no per-item id/object to hang a domain-agent origin flag on (scope,
// out_of_scope, constraints, risks, dependencies, data_requirements, etc.) -- unlike
// EnrichedItemList's FR/NFR/AC/VR items, a plain string can't carry its own "origin" field, so a
// domain-added entry is identified by exact-text match against the sibling Domain Improvements
// artifact's own recorded additions (see SrsDocumentViewer's buildHighlightedTextsBySection).
// Same green "Added by Domain Agent" color convention as EnrichedItemList/DomainImprovementsViewer
// so the same meaning reads the same way everywhere in the app -- plain-list sections never get a
// "modified" state (there's no original text to diff against once a string is edited in place).
//
// Permanently read-only -- the SRS may only be changed by explicitly chatting with the
// Requirement Agent (RequirementConversationChat.jsx), never by editing this view directly. This
// component previously also rendered an inline edit/remove/add UI (per-item pencil, textarea,
// Save/Cancel); that was removed by direct user request. Only the highlighting rendering below
// survives.
function Citation({ citation }) {
  if (!citation) return null;
  return (
    <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-1 italic">
      Source: {citation.source_document}
      {citation.chunk_id ? ` (${citation.chunk_id})` : ""}
    </p>
  );
}

// This field is documented as list[str], but a real, confirmed LLM generation mimicked the
// ID-tagged {id, description} shape FR/NFR/AC/VR items use (schema drift, not a display-layer
// bug) -- rendering the raw object as a JSX child crashes the whole page ("Objects are not
// valid as a React child"). Extracts a displayable string regardless of which shape actually
// arrived, so a schema violation degrades to "shows the text" instead of a hard crash.
function itemText(item) {
  if (typeof item === "string") return item;
  if (item && typeof item === "object") {
    if (typeof item.description === "string") return item.description;
    if (typeof item.text === "string") return item.text;
    if (typeof item.value === "string") return item.value;
    try {
      return JSON.stringify(item);
    } catch {
      return String(item);
    }
  }
  return String(item ?? "");
}

export default function EnrichedPlainList({ items, highlighted }) {
  if (!Array.isArray(items) || items.length === 0) {
    return <p className="text-sm text-gray-400 dark:text-gray-500 italic">None</p>;
  }

  return (
    <div className="flex flex-col gap-1.5">
      {items.map((item, index) => {
        const text = itemText(item);
        const match = highlighted?.get(text);

        if (!match) {
          return (
            <div key={index} className="pl-3 relative before:content-['\2022'] before:absolute before:left-0 before:text-gray-400">
              <p className="text-sm text-gray-700 dark:text-gray-300">{text}</p>
            </div>
          );
        }

        return (
          <div
            key={index}
            className="rounded-lg border border-green-200 dark:border-green-500/30 bg-green-50 dark:bg-green-500/10 p-2.5"
          >
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm text-gray-800 dark:text-gray-200">{text}</p>
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-green-600 text-white uppercase tracking-wide whitespace-nowrap flex-shrink-0">
                Added by Domain Agent
              </span>
            </div>
            <Citation citation={match.domain_citation} />
          </div>
        );
      })}
    </div>
  );
}
