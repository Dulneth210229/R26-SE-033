import DocumentValue, { humanizeKey } from "./DocumentValue";
import EnrichedItemList from "./EnrichedItemList";
import EnrichedPlainList from "./EnrichedPlainList";

// These five sections carry Domain Agent enrichment markers (modified_by_domain_agent,
// original_description, origin, domain_citation) directly on their array items in a real
// Enhanced SRS -- rendered as color-coded cards (see EnrichedItemList) instead of a generic
// table, so an enrichment is visually obvious rather than buried as just another field.
// user_stories belongs here too (Domain Agent can add to it, same as FR/NFR/AC/VR -- see
// domain_agent/agent.py's SECTION_PREFIX_MAP) -- previously missing, so a domain-added user story
// silently rendered with no highlighting at all, unlike every other ID-tagged section.
const ENRICHABLE_SECTIONS = new Set([
  "functional_requirements",
  "non_functional_requirements",
  "acceptance_criteria",
  "validation_rules",
  "user_stories",
]);

// Plain list[str] sections a real Domain Agent enrichment can also target (see domain_validator.
// py's PLAIN_LIST_SECTIONS -- kept in sync manually, this is a display concern, not a source of
// truth). Unlike the sections above, a plain string carries no origin flag of its own -- a
// domain-added entry is identified by exact-text match against the sibling Domain Improvements
// artifact's own recorded additions (see buildHighlightedTextsBySection below).
const PLAIN_LIST_ENRICHABLE_SECTIONS = new Set([
  "data_requirements",
  "scope",
  "out_of_scope",
  "user_roles",
  "input_requirements",
  "output_requirements",
  "ui_expectations",
  "api_expectations",
  "constraints",
  "assumptions",
  "risks",
  "dependencies",
]);

// Groups the sibling Domain Improvements artifact's "additions" by target_section, keyed by the
// exact added text -- this is what lets a plain-list section (scope, constraints, risks, ...)
// show the same green "Added by Domain Agent" highlight an ID-tagged FR/NFR/AC/VR/US item already
// gets for free from its own origin field. Real, reported gap this closes: Domain Agent enrichment
// outside the 4 originally-enrichable sections was invisible in the document view -- a human had
// to separately read the "Domain Improvements" attachment below to know anything changed at all,
// defeating the whole point of inline highlighting.
function buildHighlightedTextsBySection(domainImprovements) {
  const bySection = new Map();
  for (const addition of domainImprovements?.additions || []) {
    if (!addition?.target_section || !addition?.description) continue;
    if (!bySection.has(addition.target_section)) bySection.set(addition.target_section, new Map());
    bySection.get(addition.target_section).set(addition.description, addition);
  }
  return bySection;
}

// SRS and Enhanced SRS share an identical shape (confirmed against real generated artifacts) --
// one renderer covers both. Section order follows how a human would actually read a
// requirements document: goal/scope first, requirements/stories/criteria next, technical
// expectations, then constraints/risks/traceability last.
const SECTION_ORDER = [
  ["business_goal", "Business Goal"],
  ["target_stack", "Target Stack"],
  ["architectural_style", "Architectural Style"],
  ["scope", "Scope"],
  ["out_of_scope", "Out of Scope"],
  ["user_roles", "User Roles"],
  ["user_stories", "User Stories"],
  ["functional_requirements", "Functional Requirements"],
  ["non_functional_requirements", "Non-Functional Requirements"],
  ["acceptance_criteria", "Acceptance Criteria"],
  ["input_requirements", "Input Requirements"],
  ["output_requirements", "Output Requirements"],
  ["ui_expectations", "UI Expectations"],
  ["api_expectations", "API Expectations"],
  ["data_requirements", "Data Requirements"],
  ["validation_rules", "Validation Rules"],
  ["domain_enrichment_metadata", "Domain Enrichment"],
  ["constraints", "Constraints"],
  ["assumptions", "Assumptions"],
  ["risks", "Risks"],
  ["dependencies", "Dependencies"],
  ["traceability", "Traceability"],
];

const HEADER_FIELDS = ["feature_name", "project_name", "target_stack", "architectural_style", "project_type"];

function Section({ sectionKey, title, value, highlightedBySection }) {
  if (value === null || value === undefined || (Array.isArray(value) && value.length === 0)) {
    return null;
  }

  let body;
  if (ENRICHABLE_SECTIONS.has(sectionKey)) {
    body = <EnrichedItemList items={value} field={sectionKey} />;
  } else if (PLAIN_LIST_ENRICHABLE_SECTIONS.has(sectionKey)) {
    body = <EnrichedPlainList items={value} highlighted={highlightedBySection?.get(sectionKey)} />;
  } else {
    body = <DocumentValue value={value} />;
  }

  return (
    <section className="mb-5">
      <h3 className="text-sm font-bold text-gray-900 dark:text-gray-100 uppercase tracking-wide mb-1.5 pb-1 border-b border-gray-100 dark:border-gray-800">
        {title}
      </h3>
      {body}
    </section>
  );
}

const DOCUMENT_TYPE_LABELS = {
  srs: "Software Requirements Specification (SRS)",
  enhanced_srs: "Enhanced Software Requirements Specification (Enhanced SRS)",
  srs_preview: "SRS Preview (In Progress)",
};

// domainImprovements (optional): the sibling Domain Improvements JSON for the SAME version, when
// viewing an Enhanced SRS -- see ArtifactContentView's domainImprovementsArtifact prop. Absent for
// a plain SRS (Requirement Agent's own output, never domain-enriched) or when the caller doesn't
// have it in scope (e.g. the artifact-viewer popup, which doesn't currently look up siblings) --
// every section then just renders its plain, unhighlighted form exactly as before this feature.
//
// Permanently read-only -- per direct user request, the SRS may only be changed by explicitly
// chatting with the Requirement Agent (RequirementConversationChat.jsx). This component
// previously also supported field-by-field inline editing (a pencil icon on any section,
// edit-in-place like a Word document); that capability, and the backend /requirement/edit route
// it depended on, were both removed entirely -- chatting with the agent is now the only way to
// change anything.
export default function SrsDocumentViewer({ data, artifactType, domainImprovements }) {
  if (!data) return null;

  const knownKeys = new Set([...SECTION_ORDER.map(([k]) => k), ...HEADER_FIELDS, "project_id", "feature_id"]);
  const extraKeys = Object.keys(data).filter((k) => !knownKeys.has(k));
  const highlightedBySection = buildHighlightedTextsBySection(domainImprovements);

  return (
    <div className="max-w-3xl">
      <div className="mb-5 pb-3 border-b border-gray-200 dark:border-gray-800">
        <p className="text-xs font-bold text-accent-600 dark:text-accent-400 uppercase tracking-wide mb-1">
          {DOCUMENT_TYPE_LABELS[artifactType] || "Software Requirements Specification (SRS)"}
        </p>
        <h2 className="text-lg font-bold text-gray-900 dark:text-gray-100">{data.feature_name || "Untitled Feature"}</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          {[data.project_name, data.project_type, data.target_stack, data.architectural_style].filter(Boolean).join(" · ")}
        </p>
      </div>

      {SECTION_ORDER.map(([key, title]) => (
        <Section key={key} sectionKey={key} title={title} value={data[key]} highlightedBySection={highlightedBySection} />
      ))}

      {/* Nothing generated by the agent is ever silently hidden: any field this component
          doesn't explicitly know about still renders, generically, at the end. */}
      {extraKeys.map((key) => (
        <Section
          key={key}
          sectionKey={key}
          title={humanizeKey(key)}
          value={data[key]}
          highlightedBySection={highlightedBySection}
        />
      ))}
    </div>
  );
}
