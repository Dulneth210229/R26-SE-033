import DocumentValue, { humanizeKey } from "./DocumentValue";

// Every design_views sub-view label -- context_view/logical_view/behavior_view don't get a
// dedicated top-level Markdown section of their own (per markdown_builder.py), so they're kept
// reachable in a "Design Views (Additional)" catch-all instead of being silently dropped.
const DESIGN_VIEW_LABELS = {
  context_view: "Context View",
  logical_view: "Logical View",
  interface_view: "Interface View",
  data_view: "Data View",
  behavior_view: "Behavior View",
  error_handling_view: "Error Handling View",
  security_authorization_view: "Security & Authorization View",
  quality_attributes_view: "Quality Attributes View",
};
const DESIGN_VIEW_CATCHALL_KEYS = ["context_view", "logical_view", "behavior_view"];

function Section({ title, value }) {
  if (value === null || value === undefined) return null;
  if (Array.isArray(value) && value.length === 0) return null;
  if (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0) return null;

  return (
    <section className="mb-5">
      <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
        {title}
      </h3>
      <DocumentValue value={value} />
    </section>
  );
}

// Renders every key of an object as its own labeled sub-block -- reused for
// requirement_interpretation, validation_plan, and the design_views catch-all so each is robust
// to whatever real sub-keys the LLM/fallback actually produced, instead of hardcoding a fixed
// sub-field list that would silently drop anything unexpected.
function SubSectionList({ data, labels = {} }) {
  if (!data || typeof data !== "object") return null;
  const entries = Object.entries(data).filter(
    ([, v]) => v !== null && v !== undefined && !(Array.isArray(v) && v.length === 0)
  );
  if (entries.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      {entries.map(([key, value]) => (
        <div key={key}>
          <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">{labels[key] || humanizeKey(key)}</p>
          <DocumentValue value={value} />
        </div>
      ))}
    </div>
  );
}

// Compact 2-column metadata grid for document_control -- mostly scalar fields, reads better as a
// header-style grid than DocumentValue's default vertical labeled-stack (which is built for
// deeper, more varied content). Falls back to DocumentValue for any field whose value isn't a
// simple scalar/string-array, so nothing unexpected is silently dropped.
function MetadataGrid({ data }) {
  if (!data || typeof data !== "object") return null;
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (entries.length === 0) return null;

  const simple = entries.filter(([, v]) => typeof v !== "object");
  const complex = entries.filter(([, v]) => typeof v === "object");

  return (
    <div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm mb-2">
        {simple.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="text-gray-500 dark:text-gray-400">{humanizeKey(key)}</dt>
            <dd className="text-gray-800 dark:text-gray-200">{String(value)}</dd>
          </div>
        ))}
      </dl>
      {complex.map(([key, value]) => (
        <div key={key} className="mt-2">
          <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">{humanizeKey(key)}</p>
          <DocumentValue value={value} />
        </div>
      ))}
    </div>
  );
}

const KNOWN_TOP_KEYS = [
  "document_control",
  "feature_overview",
  "requirement_interpretation",
  "architecture_approach",
  "design_views",
  "frontend_architecture_plan",
  "backend_architecture_plan",
  "implementation_plan",
  "validation_plan",
  "coder_implementation_tasks",
  "traceability_matrix",
  "assumptions",
  "constraints",
  "risks",
  "dependencies",
  "revision_metadata",
  "human_approval_note",
];

// Structured, section-by-section rendering matching the section order this project's own
// markdown_builder.py already established (17 sections, human-authored reading order) --
// read-only only, no inline editing (unlike SrsDocumentViewer, this component has no
// featureId/editable props and none should be added here).
export default function ArchitecturePlanDocumentViewer({ data }) {
  if (!data) return null;

  const docControl = data.document_control || {};
  const designViews = data.design_views || {};
  const implementationPlan = data.implementation_plan || {};
  const backendPlan = implementationPlan.backend || {};
  const frontendPlan = implementationPlan.frontend || {};
  const hasDesignViewCatchall = DESIGN_VIEW_CATCHALL_KEYS.some((k) => designViews[k]);
  const extraKeys = Object.keys(data).filter((k) => !KNOWN_TOP_KEYS.includes(k));

  return (
    <div className="max-w-3xl">
      <div className="mb-5 pb-3 border-b border-gray-200 dark:border-gray-800">
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">
          {docControl.document_title || data.feature_overview?.feature_name || "Architecture Plan"}
        </h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          {[docControl.target_stack, docControl.architecture_style, docControl.version && `v${docControl.version}`.replace("vv", "v")]
            .filter(Boolean)
            .join(" · ")}
        </p>
      </div>

      {data.human_approval_note && (
        <div className="bg-yellow-50 dark:bg-yellow-500/10 border border-yellow-200 dark:border-yellow-500/30 rounded-lg p-3 mb-5 text-sm text-yellow-900 dark:text-yellow-200 whitespace-pre-line">
          <p className="text-xs font-bold uppercase tracking-wide mb-1">Note for reviewer</p>
          {data.human_approval_note}
        </div>
      )}

      {/* 1. Document Control */}
      {Object.keys(docControl).length > 0 && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
            Document Control
          </h3>
          <MetadataGrid data={docControl} />
        </section>
      )}

      {/* 2. Feature Overview */}
      <Section title="Feature Overview" value={data.feature_overview} />

      {/* 3. Requirement Interpretation */}
      {data.requirement_interpretation && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
            Requirement Interpretation
          </h3>
          <SubSectionList data={data.requirement_interpretation} />
        </section>
      )}

      {/* 4. Architecture Approach */}
      <Section title="Architecture Approach" value={data.architecture_approach} />

      {/* 5. Frontend Architecture Plan */}
      <Section title="Frontend Architecture Plan" value={data.frontend_architecture_plan} />

      {/* 6. Backend Architecture Plan */}
      <Section title="Backend Architecture Plan" value={data.backend_architecture_plan} />

      {/* 7. End-to-End Implementation Plan (Coder Agent Blueprint) */}
      {Object.keys(implementationPlan).length > 0 && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
            Implementation Plan
          </h3>
          {backendPlan.files && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Backend Files</p>
              <DocumentValue value={backendPlan.files} />
            </div>
          )}
          {backendPlan.endpoints && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Backend Endpoints</p>
              <DocumentValue value={backendPlan.endpoints} />
            </div>
          )}
          {backendPlan.models && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Backend Data Models</p>
              <DocumentValue value={backendPlan.models} />
            </div>
          )}
          {frontendPlan.pages && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Frontend Pages</p>
              <DocumentValue value={frontendPlan.pages} />
            </div>
          )}
          {frontendPlan.components_to_reuse && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Frontend Components to Reuse</p>
              <DocumentValue value={frontendPlan.components_to_reuse} />
            </div>
          )}
          {frontendPlan.services && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Frontend Services</p>
              <DocumentValue value={frontendPlan.services} />
            </div>
          )}
          {frontendPlan.routing && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Frontend Routing</p>
              <DocumentValue value={frontendPlan.routing} />
            </div>
          )}
          {implementationPlan.implementation_order && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Implementation Order</p>
              <ol className="list-decimal list-inside text-sm text-gray-700 dark:text-gray-300 space-y-1">
                {implementationPlan.implementation_order.map((step, i) => (
                  <li key={i}>{step}</li>
                ))}
              </ol>
            </div>
          )}
          {implementationPlan.constraints && (
            <div className="mb-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-400 mb-1">Constraints</p>
              <DocumentValue value={implementationPlan.constraints} />
            </div>
          )}
        </section>
      )}

      {/* 8. API & Interface Plan */}
      <Section title="API & Interface Plan" value={designViews.interface_view} />

      {/* 9. Data Model Plan */}
      <Section title="Data Model Plan" value={designViews.data_view} />

      {/* 10. Validation Plan */}
      {data.validation_plan && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
            Validation Plan
          </h3>
          <SubSectionList data={data.validation_plan} />
        </section>
      )}

      {/* 11. Error Handling Plan */}
      <Section title="Error Handling Plan" value={designViews.error_handling_view} />

      {/* 12. Security Plan */}
      <Section title="Security Plan" value={designViews.security_authorization_view} />

      {/* 13. Quality / NFR Plan */}
      <Section title="Quality / NFR Plan" value={designViews.quality_attributes_view} />

      {/* Design Views not covered by a dedicated section above -- kept reachable, never hidden. */}
      {hasDesignViewCatchall && (
        <section className="mb-5">
          <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
            Design Views (Additional)
          </h3>
          <SubSectionList
            data={Object.fromEntries(DESIGN_VIEW_CATCHALL_KEYS.filter((k) => designViews[k]).map((k) => [k, designViews[k]]))}
            labels={DESIGN_VIEW_LABELS}
          />
        </section>
      )}

      {/* 14. Coder Implementation Tasks */}
      <Section title="Coder Implementation Tasks" value={data.coder_implementation_tasks} />

      {/* 15. Requirement-to-Architecture Traceability */}
      <Section title="Requirement-to-Architecture Traceability" value={data.traceability_matrix} />

      {/* 16. Assumptions / Constraints / Risks / Dependencies */}
      <Section title="Constraints" value={data.constraints} />
      <Section title="Assumptions" value={data.assumptions} />
      <Section title="Risks" value={data.risks} />
      <Section title="Dependencies" value={data.dependencies} />

      {data.revision_metadata && (
        <section className="mb-5 pt-2 border-t border-gray-100 dark:border-gray-800">
          <p className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-1">Revision</p>
          <DocumentValue value={data.revision_metadata} />
        </section>
      )}

      {/* Any key not explicitly claimed above still renders here, generically -- nothing from a
          real agent output is ever silently hidden. */}
      {extraKeys.map((key) => (
        <Section key={key} title={humanizeKey(key)} value={data[key]} />
      ))}
    </div>
  );
}
