// Human-readable labels for ArtifactType values (see app/core/enums.py).
export const ARTIFACT_TYPE_LABELS = {
  srs: "SRS",
  enhanced_srs: "Enhanced SRS",
  domain_improvements: "Domain Improvements",
  architecture_plan: "Architecture Plan",
  sds: "SDS (legacy)",
  use_case_diagram: "Use Case Diagram",
  sequence_diagram: "Sequence Diagram",
  class_diagram: "Class Diagram",
  architecture_traceability: "Architecture Traceability",
  ui_metadata: "UI Metadata",
  ui_integration_manifest: "UI Integration Manifest",
  ui_component_code: "Component Design",
  ui_page_html: "Page Design",
  ui_preview_screenshot: "Preview Screenshot",
  design_system: "Design System",
  code_plan: "Code Plan",
  code_diff: "Code Diff",
  code_manifest: "Code Manifest",
  requirement_code_map: "Requirement Code Map",
  setup_instructions: "Setup Instructions",
  project_manifest: "Project Manifest",
  security_report: "Security Report",
  qa_report: "QA Report",
};

// Which stage each artifact_type belongs to, for grouping in ArtifactList.
export const ARTIFACT_TYPE_STAGE = {
  srs: "requirement",
  enhanced_srs: "domain",
  domain_improvements: "domain",
  architecture_plan: "architecture",
  sds: "architecture",
  use_case_diagram: "architecture",
  sequence_diagram: "architecture",
  class_diagram: "architecture",
  architecture_traceability: "architecture",
  ui_metadata: "uiux",
  ui_integration_manifest: "uiux",
  ui_component_code: "uiux",
  ui_page_html: "uiux",
  ui_preview_screenshot: "uiux",
  code_plan: "coder",
  code_diff: "coder",
  code_manifest: "coder",
  requirement_code_map: "coder",
  setup_instructions: "coder",
  security_report: "security",
  qa_report: "qa",
};

// The single (artifact_type, artifact_format) pair that gates each stage's approval --
// approving/rejecting THIS specific artifact is what the graph actually reacts to (see
// approval_service.py's resume()). Format matters: every agent saves a JSON+Markdown pair at
// the same version, and the JSON copy is always the one the pipeline keys off of -- EXCEPT
// Coder Agent's code_diff, which only ever exists as Markdown (there is no JSON code_diff).
export const STAGE_GATING_ARTIFACT = {
  requirement: { type: "srs", format: "json" },
  domain: { type: "enhanced_srs", format: "json" },
  architecture: { type: "architecture_plan", format: "json" },
  // Per direct user request, the Preview Screenshot is the ONE artifact a human directly
  // approves for this stage -- ui_metadata/ui_integration_manifest/ui_component_code/
  // ui_page_html are no longer independently listed or approvable (see ResultTab.jsx's
  // UNLISTED_ARTIFACT_TYPES); approving the screenshot cascades the same decision to all of them
  // (approval_service.py's _cascade_uiux_screenshot_decision).
  uiux: { type: "ui_preview_screenshot", format: "png" },
  coder: { type: "code_diff", format: "markdown" },
  // Auto-approved (soft-gate) stage, like every security_report artifact itself -- registered
  // here purely so deriveStageStatus.js can tell "has run at least once" (shows Approved, since
  // it's never anything but auto-approved) from "never run yet" (shows Action Required, from
  // MANUAL_RUN_STAGES), not because a human ever makes a real approve/reject decision on it.
  security: { type: "security_report", format: "json" },
  // Same reasoning as security above -- auto-approved, registered purely so deriveStageStatus.js
  // can distinguish "has run at least once" from "never run yet."
  qa: { type: "qa_report", format: "json" },
};

// Back-compat plain type map, still useful for "which stage does this artifact_type belong
// to" checks that don't care about the gating nuance above.
export const STAGE_GATING_ARTIFACT_TYPE = Object.fromEntries(
  Object.entries(STAGE_GATING_ARTIFACT).map(([stage, { type }]) => [stage, type])
);

// A display-only artifact type (shown so a human can read/download it) that is never itself a
// real approval decision -- setup_instructions is generated alongside the Coder Agent's real
// gating artifact (code_diff) but isn't what a human is actually accepting; that's the generated
// code itself, gated via STAGE_GATING_ARTIFACT.coder. ArtifactRow checks this before offering
// inline Approve/Request-Revision/Reject on a row.
export const NON_APPROVABLE_ARTIFACT_TYPES = ["setup_instructions"];

// artifact_type -> dedicated document viewer key, for JSON content that should render as a real
// formatted document rather than a raw tree. SrsDocumentViewer covers both srs and enhanced_srs
// (they share one shape); sds is Architecture Plan's legacy type name (same shape as
// architecture_plan).
const DOCUMENT_VIEWER_TYPES = {
  srs: "srs-document",
  enhanced_srs: "srs-document",
  architecture_plan: "architecture-document",
  sds: "architecture-document",
  domain_improvements: "domain-improvements-document",
  ui_metadata: "ui-metadata-document",
};

// Artifact types where MULTIPLE genuinely distinct files can legitimately share one version --
// currently only ui_preview_screenshot (a feature with more than one page/UI gets one screenshot
// PER PAGE, all sharing the run's one version number). dedupeArtifactVersions' own type::version
// key assumes at most one meaningful artifact per (type, version) -- correct for the JSON+
// Markdown-pair case it was built for, but would silently collapse N genuinely different pages
// down to just one if applied here too. Types listed here are never collapsed by it.
const MULTI_ITEM_PER_VERSION_ARTIFACT_TYPES = ["ui_preview_screenshot"];

// Every gating artifact_type saves a JSON+Markdown pair sharing one version (see
// STAGE_GATING_ARTIFACT's own docstring) -- both are real, valid artifact records, but showing
// both as separate rows in a version list reads as the same version being duplicated. Keeps only
// the format each type's stage actually gates off of (falling back to whichever one shows up
// first if a type has no gating format registered, or only ever has one format to begin with --
// e.g. ui_component_code, diagram PNGs).
export function dedupeArtifactVersions(artifacts) {
  const kept = new Map();

  for (const artifact of artifacts) {
    const key = MULTI_ITEM_PER_VERSION_ARTIFACT_TYPES.includes(artifact.artifact_type)
      ? `${artifact.artifact_type}::${artifact.version}::${artifact.artifact_id}`
      : `${artifact.artifact_type}::${artifact.version}`;
    const existing = kept.get(key);

    if (!existing) {
      kept.set(key, artifact);
      continue;
    }

    const stage = ARTIFACT_TYPE_STAGE[artifact.artifact_type];
    const preferredFormat = STAGE_GATING_ARTIFACT[stage]?.format;

    if (preferredFormat && artifact.artifact_format === preferredFormat && existing.artifact_format !== preferredFormat) {
      kept.set(key, artifact);
    }
  }

  return Array.from(kept.values());
}

export function pickViewer(artifact) {
  if (artifact.artifact_format === "png") return "image";
  // code_diff exists in BOTH formats: the markdown one is the real merge report DiffViewer
  // parses (prose + a fenced diff block); the json one is just a {added, modified, deleted}
  // file-tree summary with no diff text at all -- routing it through DiffViewer showed the raw
  // JSON as if it were prose, with a permanent "No diff content found" underneath. Format still
  // decides the viewer for that one; only markdown code_diff gets the dedicated DiffViewer.
  if (artifact.artifact_type === "code_diff" && artifact.artifact_format === "markdown") return "diff";
  if (artifact.artifact_format === "json" && DOCUMENT_VIEWER_TYPES[artifact.artifact_type]) {
    return DOCUMENT_VIEWER_TYPES[artifact.artifact_type];
  }
  if (artifact.artifact_format === "markdown") return "markdown";
  if (artifact.artifact_format === "json") return "json";
  if (artifact.artifact_format === "html") return "html";
  if (artifact.artifact_format === "code") return "code";
  return "raw";
}

// A feature with more than one page/UI gets one Preview Screenshot per page, all sharing the
// SAME version number (see artifact_service.save_binary_artifact's version_override fix) -- with
// nothing to tell them apart, every row/thumbnail read as an identical "Preview Screenshot vN"
// duplicate. Best-effort filename-derived label (no dedicated backend field for this -- the
// filename is already the only place the real page identity survives). Shared by ArtifactRow.jsx
// (per-row label) and UiuxVersionGroupList.jsx (per-thumbnail label) so both use the same logic.
export function screenshotPageLabel(artifact) {
  if (!artifact.file_path) return null;
  const base = artifact.file_path
    .split(/[\\/]/)
    .pop()
    .replace(/\.png$/i, "")
    .replace(/_v\d+$/, "");
  if (!base) return null;
  return base.split("_").map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}
