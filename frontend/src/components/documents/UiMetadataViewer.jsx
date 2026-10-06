// ui_metadata is the UI/UX Agent's page/component plan -- real shape confirmed against generated
// artifacts: { pages: [{page_id, name, route, actors[], covers_requirements[], layout_regions[],
// components[{name, reused_from_design_system, new_component_justification, covers_ui_expectations[],
// content_elements[]}], states[]}], notes }. Rendered as real page cards instead of a raw JSON tree.
function Chip({ children, tone = "gray" }) {
  const tones = {
    gray: "bg-gray-100 dark:bg-white/10 text-gray-600 dark:text-gray-300",
    accent: "bg-accent-50 dark:bg-accent-500/15 text-accent-700 dark:text-accent-300",
    blue: "bg-blue-50 dark:bg-blue-500/15 text-blue-700 dark:text-blue-300",
  };
  return <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${tones[tone]}`}>{children}</span>;
}

function ChipGroup({ label, items, tone }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="mb-3">
      <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <Chip key={item} tone={tone}>
            {item}
          </Chip>
        ))}
      </div>
    </div>
  );
}

function ComponentRow({ component }) {
  const reused = Boolean(component.reused_from_design_system);
  const contentElements = Array.isArray(component.content_elements) ? component.content_elements : [];

  return (
    <div
      className={`rounded-lg border p-3 ${
        reused
          ? "border-accent-200 dark:border-accent-500/30 bg-accent-50 dark:bg-accent-500/10"
          : "border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900"
      }`}
    >
      <div className="flex items-center justify-between flex-wrap gap-2">
        <p className="text-sm font-bold text-gray-900 dark:text-gray-100 min-w-0">{component.name}</p>
        <span
          className={`text-[10px] font-bold px-1.5 py-0.5 rounded uppercase tracking-wide flex-shrink-0 ${
            reused ? "bg-accent-600 text-white" : "bg-gray-200 dark:bg-white/10 text-gray-600 dark:text-gray-300"
          }`}
        >
          {reused ? "Reused" : "New"}
        </span>
      </div>

      {!reused && component.new_component_justification && (
        <p className="text-xs text-gray-500 dark:text-gray-400 italic mt-1">{component.new_component_justification}</p>
      )}

      {component.covers_ui_expectations?.length > 0 && (
        <ul className="list-disc list-inside text-xs text-gray-600 dark:text-gray-400 mt-1.5 space-y-0.5">
          {component.covers_ui_expectations.map((expectation, i) => (
            <li key={i}>{expectation}</li>
          ))}
        </ul>
      )}

      {contentElements.length > 0 && (
        <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <div className="flex flex-wrap gap-1.5">
            {contentElements.map((element, i) => (
              <Chip key={i} tone="gray">
                {String(element)}
              </Chip>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function PageCard({ page }) {
  const components = page.components || [];

  return (
    <div className="mb-5 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
      <div className="bg-gray-50 dark:bg-white/5 px-4 py-3 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 min-w-0">{page.name}</h3>
          {page.route && (
            <code className="text-xs text-accent-700 dark:text-accent-300 bg-accent-50 dark:bg-accent-500/15 px-2 py-0.5 rounded flex-shrink-0">{page.route}</code>
          )}
        </div>
      </div>

      <div className="p-4">
        <div className="flex flex-wrap gap-4">
          <ChipGroup label="Actors" items={page.actors} tone="blue" />
          <ChipGroup label="Layout Regions" items={page.layout_regions} tone="gray" />
          <ChipGroup label="States" items={page.states} tone="gray" />
        </div>
        <ChipGroup label="Covers Requirements" items={page.covers_requirements} tone="accent" />

        {components.length > 0 && (
          <>
            <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2 mt-1">
              Components ({components.length})
            </p>
            <div className="flex flex-col gap-2">
              {components.map((component, i) => (
                <ComponentRow key={component.name || i} component={component} />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function UiMetadataViewer({ data }) {
  if (!data) return null;

  const pages = data.pages || [];

  return (
    <div className="max-w-3xl">
      <div className="mb-5 pb-3 border-b border-gray-200 dark:border-gray-800">
        <p className="text-xs font-bold text-accent-600 dark:text-accent-400 uppercase tracking-wide mb-1">UI Metadata</p>
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
          {pages.length} Page{pages.length === 1 ? "" : "s"} Defined
        </h2>
      </div>

      {pages.map((page, i) => (
        <PageCard key={page.page_id || i} page={page} />
      ))}

      {data.notes && (
        <div className="bg-gray-50 dark:bg-white/5 border border-gray-200 dark:border-gray-700 rounded-lg p-3">
          <p className="text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">Notes</p>
          <p className="text-sm text-gray-700 dark:text-gray-300 whitespace-pre-wrap">{data.notes}</p>
        </div>
      )}
    </div>
  );
}
