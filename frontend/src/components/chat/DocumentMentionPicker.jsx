// "/" mention dropdown -- shown while typing a "/word" trailing token in the composer input,
// scoped to Domain Agent only. Lists this project's ready-to-use knowledge documents, filtered
// by whatever's typed after "/", so referencing one works like Claude/ChatGPT's file mentions.
export default function DocumentMentionPicker({ documents, query, onSelect }) {
  const readyDocuments = (documents || []).filter((doc) => doc.status === "ready");
  const filtered = query
    ? readyDocuments.filter((doc) => doc.original_filename.toLowerCase().includes(query.toLowerCase()))
    : readyDocuments;

  return (
    <div className="absolute bottom-full left-0 mb-1 w-72 max-h-56 overflow-y-auto bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg z-20">
      {readyDocuments.length === 0 ? (
        <p className="text-xs text-gray-400 dark:text-gray-500 italic px-3 py-2">
          No knowledge documents uploaded yet for this project.
        </p>
      ) : filtered.length === 0 ? (
        <p className="text-xs text-gray-400 dark:text-gray-500 italic px-3 py-2">No matching documents.</p>
      ) : (
        filtered.map((doc) => (
          <button
            key={doc.document_id}
            type="button"
            onMouseDown={(event) => {
              // mousedown (not click) fires before the input's blur, so the picker's selection
              // handler runs before anything closes it out from under the click.
              event.preventDefault();
              onSelect(doc);
            }}
            className="w-full text-left px-3 py-2 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-white/10 truncate"
            title={doc.original_filename}
          >
            {doc.original_filename}
          </button>
        ))
      )}
    </div>
  );
}
