// domain_improvements is Domain Agent's own "what changed and why" record -- separate from the
// Enhanced SRS itself (which already gets SrsDocumentViewer). Real shape confirmed against
// generated artifacts: { summary, knowledge_sources_used[], additions[], modifications[] },
// each addition/modification carrying a domain_citation back to the source knowledge document.
function Citation({ citation }) {
  if (!citation?.source_document) return null;
  return (
    <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
      Source: <span className="font-mono">{citation.source_document}</span>
      {citation.chunk_id ? ` (${citation.chunk_id})` : ""}
    </p>
  );
}

export default function DomainImprovementsViewer({ data }) {
  if (!data) return null;

  const additions = data.additions || [];
  const modifications = data.modifications || [];

  return (
    <div className="max-w-3xl">
      <div className="mb-5 pb-3 border-b border-gray-200 dark:border-gray-800">
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">Domain Improvements</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">What the Domain Agent added or changed, and why.</p>
      </div>

      {data.fallback_used && (
        <div className="bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-200 dark:border-yellow-500/30 rounded-lg p-3 mb-5 text-sm text-yellow-900 dark:text-yellow-200">
          {data.fallback_reason || "This run used a safe fallback -- no domain enrichment was applied."}
        </div>
      )}

      {data.summary && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
            Summary
          </h3>
          <p className="text-sm text-gray-700 dark:text-gray-300">{data.summary}</p>
        </section>
      )}

      {data.knowledge_sources_used?.length > 0 && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
            Knowledge Sources Used
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {data.knowledge_sources_used.map((s) => (
              <span key={s.source_document} className="bg-blue-50 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300 text-xs px-2 py-1 rounded-full font-mono">
                {s.source_document} {s.chunks_used ? `(${s.chunks_used})` : ""}
              </span>
            ))}
          </div>
        </section>
      )}

      {additions.length > 0 && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-2 pb-1 border-b border-gray-100 dark:border-gray-800">
            Additions ({additions.length})
          </h3>
          <div className="flex flex-col gap-3">
            {additions.map((a, i) => (
              <div key={i} className="border border-green-200 dark:border-green-500/30 bg-green-50 dark:bg-green-500/10 rounded-lg p-3">
                <p className="text-xs font-semibold text-green-800 dark:text-green-300 uppercase tracking-wide">
                  New in {a.target_section?.replace(/_/g, " ")} {a.new_id && `· ${a.new_id}`}
                </p>
                <p className="text-sm text-gray-800 dark:text-gray-200 mt-1">{a.description}</p>
                {a.rationale && <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 italic">Why: {a.rationale}</p>}
                <Citation citation={a.domain_citation} />
              </div>
            ))}
          </div>
        </section>
      )}

      {modifications.length > 0 && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-2 pb-1 border-b border-gray-100 dark:border-gray-800">
            Modifications ({modifications.length})
          </h3>
          <div className="flex flex-col gap-3">
            {modifications.map((m, i) => (
              <div key={i} className="border border-blue-200 dark:border-blue-500/30 bg-blue-50 dark:bg-blue-500/10 rounded-lg p-3">
                <p className="text-xs font-semibold text-blue-800 dark:text-blue-300 uppercase tracking-wide">
                  {m.target_section?.replace(/_/g, " ")} {m.id && `· ${m.id}`}
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400 line-through mt-1">{m.original_description}</p>
                <p className="text-sm text-gray-800 dark:text-gray-200 mt-1">{m.enhanced_description}</p>
                {m.rationale && <p className="text-xs text-gray-500 dark:text-gray-400 mt-1 italic">Why: {m.rationale}</p>}
                <Citation citation={m.domain_citation} />
              </div>
            ))}
          </div>
        </section>
      )}

      {additions.length === 0 && modifications.length === 0 && !data.fallback_used && (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">No additions or modifications were recorded for this run.</p>
      )}
    </div>
  );
}
