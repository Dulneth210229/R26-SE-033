import { useEffect, useRef, useState } from "react";
import { listGatingArtifactVersions, getOperativeGatingArtifact, hasNextStageStarted } from "../../lib/deriveStageStatus";
import {
  ARTIFACT_TYPE_STAGE,
  STAGE_GATING_ARTIFACT,
  ARTIFACT_TYPE_LABELS,
  dedupeArtifactVersions,
} from "../../lib/artifactTypeMeta";
import { STAGE_LABELS, CONSOLIDATED_APPROVAL_STAGES } from "../../lib/pipelineStages";
import { getEffectiveActiveArtifact } from "../../lib/activeArtifactSelection";
import {
  artifactDownloadUrl,
  artifactDownloadPdfUrl,
  featureCodeDownloadUrl,
  featureCodeWithQaReportDownloadUrl,
} from "../../api/client";
import { declutterJsonForDisplay } from "../../lib/streamingJsonDisplay";
import { looksLikeMongoUri } from "../../lib/mongoUri";
import ArtifactContentView from "../artifacts/ArtifactContentView";
import ArchitectureDiagramsGallery from "../pipeline/ArchitectureDiagramsGallery";
import UiuxPagePreviewsPanel from "../pipeline/UiuxPagePreviewsPanel";
import { LiveGenerationView, useRotatingLabel } from "../pipeline/RequirementConversationParts";
import GovernancePanel from "../pipeline/GovernancePanel";
import ApprovalPanel from "../pipeline/ApprovalPanel";
import GatingArtifactApprovalPanel from "../pipeline/GatingArtifactApprovalPanel";
import ArtifactList from "../pipeline/ArtifactList";
import UiuxVersionGroupList from "../pipeline/UiuxVersionGroupList";
import ErrorBanner from "../common/ErrorBanner";
import ConfirmDialog from "../common/ConfirmDialog";
import RequirementSrsOutputPanel from "./RequirementSrsOutputPanel";
import VersionSelect from "./VersionSelect";
import SecurityReportView from "../security/SecurityReportView";
import SecurityDecisionDialog from "../security/SecurityDecisionDialog";
import QaReportView from "../qa/QaReportView";
import { useWorkspaceSelection } from "../workspace/WorkspaceSelectionContext";
import { useRequirementConversationFlowContext } from "../workspace/RequirementConversationFlowContext";
import { useDomainAgentFlowContext } from "../workspace/DomainAgentFlowContext";
import { useArchitectureAgentFlowContext } from "../workspace/ArchitectureAgentFlowContext";
import { useUiuxAgentFlowContext } from "../workspace/UiuxAgentFlowContext";
import { useCoderAgentFlowContext } from "../workspace/CoderAgentFlowContext";
import { useSecurityAgentFlowContext } from "../workspace/SecurityAgentFlowContext";
import { useQaAgentFlowContext } from "../workspace/QaAgentFlowContext";
import { useFeature, useSetActiveArtifactSelection } from "../../hooks/useFeatures";
import { useApprovalMutation } from "../../hooks/useApprovalMutation";
import { useArtifactContent } from "../../hooks/useArtifacts";
import { buildSecurityRevisionComment } from "../../lib/securityReportToRevisionComment";
import { computeSecurityGateBlocksQa } from "../../lib/securityGate";

// Both Requirement->Domain and Domain->Architecture support pinning a specific approved version
// (direct user request for the latter, mirroring the former) -- extend this map (mirrors
// OutputPanel's own) if another stage's handoff gets the same treatment.
const ACTIVE_SELECTION_ARTIFACT_TYPE_BY_STAGE = {
  requirement: "srs",
  domain: "enhanced_srs",
};

// Drives the "Approve and continue" popup + orchestration for the three stage transitions that
// need it -- one config, one confirmingArtifactId state, one ConfirmDialog, instead of a separate
// parallel block per stage duplicating requirement's own. `autoRun: true` means confirming
// doesn't just switch the chat -- it also starts the next agent immediately, no separate manual
// click needed (a deliberate, different UX from Requirement -> Domain, where a human explicitly
// guides the very first run instead -- see ChatPanel's own proactive Domain Agent prompt).
// Domain -> Architecture's autoRun starts a real STREAM (handleRunArchitectureStream); Architecture
// -> UI/UX's autoRun instead fires a plain, non-streaming mutation (runUiux.mutate({})) -- UI/UX
// Agent has no streaming backend route today, see UiuxAgentFlowContext's own docstring.
const APPROVE_CONTINUATION_BY_STAGE = {
  requirement: {
    nextAgent: "domain",
    autoRun: false,
    title: "Approve this SRS and continue to Domain Agent?",
    message: (version) =>
      `Approving v${version} makes it the SRS this feature uses going forward (any other approved SRS version is superseded back to pending). Your chat will switch to Domain Agent, where you can tell it how to enrich this SRS -- using existing domain knowledge, something specific you provide, or both.`,
  },
  domain: {
    nextAgent: "architecture",
    autoRun: true,
    title: "Approve this Enhanced SRS and start Architecture Agent?",
    message: (version) =>
      `Approving v${version} makes it the Enhanced SRS this feature uses going forward (any other approved Enhanced SRS version is superseded back to pending). Architecture Agent will start automatically and generate the Architecture Plan plus Use Case, Sequence, and Class diagrams -- watch it live in the Result panel.`,
  },
  architecture: {
    nextAgent: "uiux",
    autoRun: true,
    title: "Approve this Architecture Plan and start UI/UX Agent?",
    message: (version) =>
      `Approving v${version} makes it the Architecture Plan this feature uses going forward (any other approved Architecture Plan version is superseded back to pending). UI/UX Agent will start automatically and generate page-level UI metadata, component code, and preview screenshots -- watch it live in the Result panel.`,
  },
  // UI/UX -> Coder is the fourth link in this chain, and the first one where approving also
  // LOCKS every other pending version's Approve button (direct user request, reversing the
  // immediately-prior session's own "free approval" choice for UI/UX specifically -- see
  // UiuxVersionGroupList's own comment) -- once Coder Agent starts consuming one version as its
  // visual reference, a stray approve on a different version mid-build would be confusing and
  // could re-trigger a second, conflicting run.
  uiux: {
    nextAgent: "coder",
    autoRun: true,
    title: "Approve this UI/UX version and start Coder Agent?",
    message: (version) =>
      `Approving v${version} locks it as the UI/UX design this feature builds from -- every other version is locked from approval until you reject this one. Coder Agent will start automatically and build the real frontend + backend to match this design as closely as possible -- watch it live in the Result panel.`,
  },
  // Coder -> Security is the fifth link, and the first that comes through this dialog at all --
  // previously the Coder Agent's own approve button skipped this popup entirely (no entry existed
  // here), so its real, serious warning was only ever visible in GovernancePanel's fine print, not
  // at the moment of actually clicking Approve. Direct user request: name the merge consequence
  // here too, then auto-start a real vulnerability scan.
  coder: {
    nextAgent: "security",
    autoRun: true,
    title: "Approve this Coder Agent output and start Security Agent?",
    message: (version) =>
      `Approving v${version} runs a real git merge --no-ff into main and permanently deletes the feature branch (see the warning below -- this part cannot be undone by re-running anything, only by explicitly revoking this approval afterward). Security Agent will then start automatically and scan the merged code for vulnerabilities -- watch it live in the Result panel.`,
  },
};

// domain_improvements is Domain Agent's own "what changed and why" side-record for the SAME
// version as its Enhanced SRS -- never independently meaningful and never what the pipeline gates
// on (STAGE_GATING_ARTIFACT only ever points at enhanced_srs for the domain stage; nothing in the
// backend ever reads domain_improvements' approval_status). It still gets saved with
// approval_status "pending" like every other artifact (artifact_service's generic default), which
// meant it showed up as its own row in "All Artifacts" with its own Approve/Reject/Request-
// Revision controls -- a real reported issue: the human was being asked to approve a document
// that was never a real decision point, on top of the Enhanced SRS itself. Excluded from the
// listed/approvable artifacts entirely; rendered instead as a read-only attachment directly under
// the Enhanced SRS document for the same version (see the domain-stage branch below).
//
// code_plan/code_diff/code_manifest/requirement_code_map are Coder Agent's own internal working
// documents -- real, useful to a human who wants to dig in, but not individually meaningful
// approval decisions the way the pipeline treats every other listed artifact. All four belong
// exclusively to the "coder" stage (per ARTIFACT_TYPE_STAGE), so excluding them by type alone,
// same mechanism as domain_improvements, needs no stage-conditional branching. The single real
// decision for this stage -- approving the generated code -- still happens exactly as before,
// through GovernancePanel's own Approve/Reject panel below (STAGE_GATING_ARTIFACT.coder points at
// code_diff/markdown, read from the unfiltered allArtifacts, independent of this list).
// use_case_diagram/sequence_diagram/class_diagram: per direct user request, diagrams no longer
// have an independent approval decision -- approving/rejecting/requesting revision on the
// Architecture Plan cascades the same decision to them automatically on the backend (see
// approval_service.py's _cascade_architecture_plan_decision). They're viewable only through
// ArchitectureDiagramsGallery now, not listed generically here.
// ui_metadata/ui_integration_manifest/ui_component_code/ui_page_html: per direct user request,
// the WHOLE UI/UX stage no longer requires any human approval decision at all -- every UI/UX
// artifact (including ui_preview_screenshot, STAGE_GATING_ARTIFACT.uiux) is saved already
// approved on the backend (see uiux_agent/agent.py's _save_artifacts). These four stay excluded
// from the listed rows for the same reason as always -- they're internal working documents, not
// individually meaningful decision points -- and ui_preview_screenshot itself still shows in
// GovernancePanel below as a plain "approved, nothing pending" status line. Raw metadata/
// manifest/component/page source is still viewable via the Preview tab and the "View" link on
// the Preview Screenshot itself where relevant -- just not as separate listed rows here.
const UNLISTED_ARTIFACT_TYPES = [
  "domain_improvements", "code_plan", "code_diff", "code_manifest", "requirement_code_map",
  "use_case_diagram", "sequence_diagram", "class_diagram",
  "ui_metadata", "ui_integration_manifest", "ui_component_code", "ui_page_html",
];

// setup_instructions is the one Coder Agent artifact still worth showing a human directly (real
// npm/build/run instructions for the generated project) -- but every past version is superseded
// the instant a newer one exists (there's nothing to compare/choose between, unlike the gating
// code_diff's own version history), so only the latest is kept.
const LATEST_VERSION_ONLY_ARTIFACT_TYPES = ["setup_instructions"];

// stage -> the real previous-stage artifact(s) it actually reads, for the "Using X vN for Y
// Agent" indicator -- generalized (direct user request, with a screenshot of the original
// Requirement->Domain-only version as the reference example) to every stage that has a real,
// approved-artifact input. Confirmed against each agent's own real run()/revise() code, not
// guessed:
// - domain reads the approved SRS.
// - architecture reads the approved Enhanced SRS when one exists, falling back to the plain SRS
//   only if it doesn't (srs_for_generation = enhanced_srs_json or srs_json, at every real call
//   site in architecture_agent/agent.py) -- resolved at render time below, never hardcoded to
//   just one.
// - uiux reads the approved Architecture Plan.
// - coder reads BOTH the Architecture Plan and the UI/UX Integration Manifest independently (at
//   every real call site in coder_agent/agent.py) -- the human-recognizable version to show for
//   the latter is ui_preview_screenshot's (its real gating/cascade-anchored type since item 64;
//   the manifest shares that exact version through the same approval cascade).
//
// Moved here from OutputPanel.jsx's own tab-bar header (direct user request: this indicator was
// cluttering the tab row next to Result/Files/Preview -- it now renders inline in the Result
// tab's own content instead, see the render block below).
const PREVIOUS_STAGE_INPUTS_BY_STAGE = {
  domain: [{ artifactType: "srs" }],
  architecture: [{ artifactType: "enhanced_srs", fallbackArtifactType: "srs" }],
  uiux: [{ artifactType: "architecture_plan" }],
  coder: [
    { artifactType: "architecture_plan" },
    { artifactType: "ui_preview_screenshot", artifactFormat: "png", label: "UI/UX Output" },
  ],
};

// Security and QA scan the live generated workspace directly off disk (confirmed: neither
// security_agent.py's nor qa_agent.py's run() ever calls a "find latest approved artifact"
// lookup for their main input) -- there is no formal, approved-artifact version behind "what
// they used" the way every other stage has one. An honest, plain, non-versioned label instead of
// a pill, so this indicator never implies a version number that doesn't actually exist.
const NO_ARTIFACT_VERSION_LABEL_BY_STAGE = {
  security: "Scanning the latest generated code",
  qa: "Testing the latest generated code",
};

// Shown in place of the generic "Planning the implementation..."/"Applying your requested
// change..." labels (and the generic phase tail) while a security-driven Coder Agent revision is
// in flight (direct user request: a themed spinner instead of a bare "Thinking"). Cycled by
// useRotatingLabel so it's visibly rotating, not stuck on one phrase.
const SECURITY_FIX_PHRASES = [
  "Patching vulnerabilities...",
  "Hardening the code...",
  "Re-checking security controls...",
  "Applying the suggested fix...",
];

// Requirement/Domain/Architecture's gating artifact is always the JSON half of a JSON+Markdown
// version pair (dedupeArtifactVersions keeps the JSON row as "the" displayed version for these
// three stages) -- so the plain "Download report" link always served raw JSON. These three
// stages instead get a document-specific label and a real, formatted PDF (rendered server-side
// from the same JSON via a dedicated pdf_builder template per agent, not a JSON dump). Security
// and QA have their own separate, earlier render branches (not this generic fallback) that each
// hardcode their own PDF download link directly -- this map never applies to them. Every other
// stage (uiux/coder) keeps the original raw-file "Download report" link.
const PDF_DOCUMENT_LABEL_BY_STAGE = {
  requirement: "Download SRS",
  domain: "Download Enhanced SRS",
  architecture: "Download Architecture Plan",
};

function keepLatestVersionOnly(artifacts, types) {
  const latestVersionByType = {};
  for (const artifact of artifacts) {
    if (!types.includes(artifact.artifact_type)) continue;
    latestVersionByType[artifact.artifact_type] = Math.max(
      latestVersionByType[artifact.artifact_type] ?? 0,
      artifact.version
    );
  }
  return artifacts.filter(
    (artifact) =>
      !types.includes(artifact.artifact_type) || artifact.version === latestVersionByType[artifact.artifact_type]
  );
}

// The Result tab: whichever agent is selected in the chat, this shows what it produced (version
// picker + document/diagram/screenshot view), plus governance (approve/reject, trace links) and
// the full versioned artifact list -- everything that used to live in StageOutputPanel +
// StageSidebar's Governance/Artifacts tabs, now scoped to the agent picked in the chat panel
// instead of a separate pipeline nav.
export default function ResultTab({ featureId, stage, allArtifacts }) {
  const { viewArtifact, selectAgent } = useWorkspaceSelection();
  const versions = listGatingArtifactVersions(stage, allArtifacts);
  // For CONSOLIDATED_APPROVAL_STAGES (requirement/domain/architecture -- direct user decision),
  // the DEFAULT selection is "the newest version that still needs a decision" (approved wins,
  // else highest pending/revision-requested, else highest overall -- getOperativeGatingArtifact's
  // existing precedence, already used by GovernancePanel), not just the newest version NUMBER --
  // e.g. [v1: pending, v2: rejected] defaults to v1, the one actually actionable. Every other
  // stage keeps the original "always the newest number" default unchanged.
  function defaultSelectedVersion() {
    if (CONSOLIDATED_APPROVAL_STAGES.includes(stage)) {
      return getOperativeGatingArtifact(stage, allArtifacts)?.version ?? versions[0]?.version ?? null;
    }
    return versions[0]?.version ?? null;
  }
  const [selectedVersion, setSelectedVersion] = useState(defaultSelectedVersion());

  // Switching stages (e.g. auto-switching to Domain Agent right after approving the SRS) must
  // always jump to the NEW stage's default version, unconditionally -- without this, a version
  // number that happens to exist for both stages (e.g. "v4" of both srs and enhanced_srs) would
  // pass the "does this version still exist" check below and silently keep showing the PREVIOUS
  // stage's document under the new stage's header, a real bug found live: the panel kept showing
  // an old SRS revision after switching to Domain Agent, simply because that version number
  // coincidentally also existed among Domain's own artifacts.
  useEffect(() => {
    setSelectedVersion(defaultSelectedVersion());
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally NOT keyed on `versions`
    // here; that case (a new version arriving for the SAME stage) is handled by the effect below.
  }, [stage]);

  // Real, confirmed bug found while building field-by-field SRS editing: this effect's own
  // comment above always claimed a new version arriving for the SAME stage would jump the
  // selector to it, but the check only ever covered "the previously-selected version vanished."
  // A freshly-created version (from a revision OR a direct field edit) never invalidates the
  // OLD version -- v2 stays a real, selectable version after v3 is created -- so `versions.some
  // (...)` still found the old selection and the effect silently did nothing, leaving a human
  // staring at their pre-edit document with no visible sign anything happened. Fixed by also
  // jumping when the latest version NUMBER has genuinely increased since the last render
  // (tracked via a ref, not `versions` itself, so an unrelated re-render -- e.g. an existing
  // version's own approval_status changing -- doesn't yank a human away from a version they're
  // deliberately reviewing). Deliberately jumps to the raw new version NUMBER here, never through
  // defaultSelectedVersion's operative resolver -- a fresh revision created after an OLDER version
  // was already approved must still surface immediately, not stay hidden behind the still-approved
  // one just because the resolver prefers "approved" over "newest".
  const previousLatestVersionRef = useRef(versions[0]?.version ?? null);
  useEffect(() => {
    const latestVersion = versions[0]?.version ?? null;
    const previousLatestVersion = previousLatestVersionRef.current;

    if (versions.length > 0 && !versions.some((v) => v.version === selectedVersion)) {
      setSelectedVersion(defaultSelectedVersion());
    } else if (
      latestVersion !== null &&
      previousLatestVersion !== null &&
      latestVersion > previousLatestVersion
    ) {
      setSelectedVersion(latestVersion);
    }

    previousLatestVersionRef.current = latestVersion;
  }, [versions, selectedVersion]);

  // While the Requirement Agent conversation is still in progress (no SRS artifact saved yet),
  // this is where its output belongs -- the same place every other stage's real output shows up,
  // instead of a second copy squeezed into the narrow chat column. RequirementSrsOutputPanel
  // deliberately shows nothing SRS-shaped (no template/draft preview) until real generation
  // starts -- see its own docstring.
  const isRequirementStage = stage === "requirement";

  // Always mounted regardless of stage (see RequirementConversationFlowProvider) -- cheap to read
  // unconditionally, only acted on when isRequirementStage. A revision streams the SAME way the
  // initial generation does: live in this panel, not a blocking wait then a static reveal (a real
  // reported issue), regardless of whether an approved SRS already exists.
  const { reviseStream, revisionStreamedText, revisionStreamStarted } = useRequirementConversationFlowContext();
  const isRevising = isRequirementStage && reviseStream.isPending;

  // Same idea for Domain Agent -- direct user report: Domain Agent had no live output at all
  // (blocking spinner, then a sudden reveal), the one agent left behind after every other
  // streamed flow already got this treatment. Domain's stream is the small enrichment PLAN (not
  // the final Enhanced SRS), decluttered for display -- same pragmatic choice
  // RequirementRevisionChat's own live view already makes (see LiveGenerationView's docstring):
  // shows something real and readable "typing" live, even though the actual merge into the
  // Enhanced SRS happens deterministically once the plan finishes, not token-by-token.
  const isDomainStage = stage === "domain";
  const {
    runStream: domainRunStream,
    runStreamedText: domainRunStreamedText,
    runStreamStarted: domainRunStreamStarted,
    reviseStream: domainReviseStream,
    revisionStreamedText: domainRevisionStreamedText,
    revisionStreamStarted: domainRevisionStreamStarted,
  } = useDomainAgentFlowContext();
  const isDomainRevising = isDomainStage && domainReviseStream.isPending;
  const isDomainRunning = isDomainStage && domainRunStream.isPending;
  const isDomainGenerating = isDomainRevising || isDomainRunning;
  const domainStreamedText = isDomainRevising ? domainRevisionStreamedText : domainRunStreamedText;
  const domainStreamStarted = isDomainRevising ? domainRevisionStreamStarted : domainRunStreamStarted;

  // Same idea, Architecture Agent -- the plan text streams live, then a "phase" tail (use case
  // model, diagram generation, PlantUML rendering) that isn't itself streamable prose, shown via
  // LiveGenerationView's isFinalizing mode instead of a bare spinner (see that component's own
  // docstring for why). Read unconditionally regardless of stage -- cheap, and this is also what
  // handleConfirmedApprove below needs to auto-start a run from the requirement/domain branch.
  const {
    handleRunStream: handleRunArchitectureStream,
    runStream: architectureRunStream,
    runStreamedText: architectureRunStreamedText,
    runStreamStarted: architectureRunStreamStarted,
    runPhase: architectureRunPhase,
    runPhaseStartedAt: architectureRunPhaseStartedAt,
    reviseStream: architectureReviseStream,
    revisionStreamedText: architectureRevisionStreamedText,
    revisionStreamStarted: architectureRevisionStreamStarted,
    revisionPhase: architectureRevisionPhase,
    revisionPhaseStartedAt: architectureRevisionPhaseStartedAt,
    plainRunMutation: architecturePlainRunMutation,
  } = useArchitectureAgentFlowContext();
  const isArchitectureStage = stage === "architecture";
  const isArchitectureRevising = isArchitectureStage && architectureReviseStream.isPending;
  const isArchitectureRunning =
    isArchitectureStage && (architectureRunStream.isPending || architecturePlainRunMutation.isPending);
  const isArchitectureGenerating = isArchitectureRevising || isArchitectureRunning;
  // Guards every auto-triggered Architecture Agent run below (Enhanced-SRS approval and the
  // "use raw SRS instead" skip) against firing a SECOND real request on top of one already in
  // flight -- the exact double-fire that used to produce two artifact versions with identical
  // content when a human had ArchitectureRunForm's "deep exploration mode" open (or had already
  // submitted it) at the moment an auto-continue fired. See useArchitectureAgentFlow.js's own
  // comment on plainRunMutation for the full story.
  const architectureRunAlreadyInFlight =
    architectureRunStream.isPending || architectureReviseStream.isPending || architecturePlainRunMutation.isPending;
  const architectureStreamedText = isArchitectureRevising ? architectureRevisionStreamedText : architectureRunStreamedText;
  const architectureStreamStarted = isArchitectureRevising ? architectureRevisionStreamStarted : architectureRunStreamStarted;
  const architecturePhase = isArchitectureRevising ? architectureRevisionPhase : architectureRunPhase;
  const architecturePhaseStartedAt = isArchitectureRevising ? architectureRevisionPhaseStartedAt : architectureRunPhaseStartedAt;

  // Same idea, Coder Agent -- the code plan text streams live during run()'s planning (revise()'s
  // planning uses the agentic exploration planner instead, which has no tokens at all -- see
  // CoderAgent.revise_stream's own docstring), then a "phase" tail (preparing the workspace,
  // coding attempts, verification, diffing) covers the rest, shown the same isFinalizing way
  // Architecture's diagram-generation tail already is.
  const {
    handleRunStream: handleRunCoderStream,
    runStream: coderRunStream,
    runStreamedText: coderRunStreamedText,
    runStreamStarted: coderRunStreamStarted,
    runPhase: coderRunPhase,
    runPhaseStartedAt: coderRunPhaseStartedAt,
    handleReviseStream: handleCoderReviseStream,
    reviseStream: coderReviseStream,
    revisionStreamedText: coderRevisionStreamedText,
    revisionStreamStarted: coderRevisionStreamStarted,
    revisionPhase: coderRevisionPhase,
    revisionPhaseStartedAt: coderRevisionPhaseStartedAt,
  } = useCoderAgentFlowContext();
  const isCoderStage = stage === "coder";
  const isCoderRevising = isCoderStage && coderReviseStream.isPending;
  const isCoderRunning = isCoderStage && coderRunStream.isPending;
  const isCoderGenerating = isCoderRevising || isCoderRunning;
  const coderStreamedText = isCoderRevising ? coderRevisionStreamedText : coderRunStreamedText;
  const coderStreamStarted = isCoderRevising ? coderRevisionStreamStarted : coderRunStreamStarted;
  const coderPhase = isCoderRevising ? coderRevisionPhase : coderRunPhase;
  const coderPhaseStartedAt = isCoderRevising ? coderRevisionPhaseStartedAt : coderRunPhaseStartedAt;

  // Same idea, UI/UX Agent -- ui_metadata_json streams live, then a "phase" tail (component
  // generation, page assembly/rendering) covers the rest, shown the same isFinalizing way
  // Architecture/Coder's own non-streamable tails already are. Read unconditionally regardless of
  // stage -- cheap, and this is also what handleConfirmedApprove below needs to auto-start a run
  // from the architecture-approval branch.
  const {
    handleRunStream: handleRunUiuxStream,
    runStream: uiuxRunStream,
    runStreamedText: uiuxRunStreamedText,
    runStreamStarted: uiuxRunStreamStarted,
    runPhase: uiuxRunPhase,
    runPhaseStartedAt: uiuxRunPhaseStartedAt,
    reviseStream: uiuxReviseStream,
    revisionStreamedText: uiuxRevisionStreamedText,
    revisionStreamStarted: uiuxRevisionStreamStarted,
    revisionPhase: uiuxRevisionPhase,
    revisionPhaseStartedAt: uiuxRevisionPhaseStartedAt,
  } = useUiuxAgentFlowContext();
  const isUiuxStage = stage === "uiux";
  const isUiuxRevising = isUiuxStage && uiuxReviseStream.isPending;
  const isUiuxRunning = isUiuxStage && uiuxRunStream.isPending;
  const isUiuxGenerating = isUiuxRevising || isUiuxRunning;
  const uiuxStreamedText = isUiuxRevising ? uiuxRevisionStreamedText : uiuxRunStreamedText;
  const uiuxStreamStarted = isUiuxRevising ? uiuxRevisionStreamStarted : uiuxRunStreamStarted;
  const uiuxPhase = isUiuxRevising ? uiuxRevisionPhase : uiuxRunPhase;
  const uiuxPhaseStartedAt = isUiuxRevising ? uiuxRevisionPhaseStartedAt : uiuxRunPhaseStartedAt;

  // Deduped for display: every gating artifact_type saves a JSON+Markdown pair sharing one
  // version, and listing both as separate rows read as the same version being duplicated (a real
  // reported issue) -- see dedupeArtifactVersions's own docstring.
  const stageArtifacts = keepLatestVersionOnly(
    dedupeArtifactVersions(
      allArtifacts.filter(
        (a) => ARTIFACT_TYPE_STAGE[a.artifact_type] === stage && !UNLISTED_ARTIFACT_TYPES.includes(a.artifact_type)
      )
    ),
    LATEST_VERSION_ONLY_ARTIFACT_TYPES
  );

  // Security/QA already replaced the stacked "All Artifacts" list + separate "Governance" panel
  // with one compact version dropdown + inline approval control (see the security branch below) --
  // CONSOLIDATED_APPROVAL_STAGES (requirement/domain/architecture, direct user request) now gets
  // the exact same treatment via GatingArtifactApprovalPanel. uiux/coder keep the original,
  // unchanged surfaces. One shared boolean, not two independently-maintained conditions, so the
  // two render guards below can never drift out of sync with each other.
  const showLegacyArtifactSurfaces = stage !== "security" && stage !== "qa" && !CONSOLIDATED_APPROVAL_STAGES.includes(stage);

  // Lets a human pin which APPROVED version feeds the next agent (e.g. which SRS version Domain
  // Agent reads) instead of always the latest approved one -- see ArtifactRow's radio button and
  // OutputPanel's "Using SRS vN for Domain Agent" indicator, which reads the same effective value.
  const { data: feature } = useFeature(featureId);
  const setActiveSelection = useSetActiveArtifactSelection(featureId);
  const activeArtifactType = ACTIVE_SELECTION_ARTIFACT_TYPE_BY_STAGE[stage];
  const effectiveActiveArtifact = activeArtifactType
    ? getEffectiveActiveArtifact(allArtifacts, feature?.active_artifact_selection, activeArtifactType)
    : null;

  // Approving the Requirement Agent's SRS (or Domain Agent's Enhanced SRS) is where approving
  // genuinely switches the human's chat over to a different agent -- worth an explicit
  // confirmation, not just an immediate click. Owned HERE (not inside GovernancePanel or
  // ArtifactRow) because BOTH of those can offer an Approve button for a pending version now (a
  // real reported bug: only the single "operative"/highest-version artifact ever had approval
  // controls at all) -- this is their shared ancestor, and it never unmounts across the
  // approve -> switch-chat (-> auto-run) transition the way either child can (see this
  // component's own git history for the exact unmount bug this already caused once).
  //
  // Requirement -> Domain deliberately does NOT auto-run Domain Agent (it used to, immediately,
  // with an empty human_comment) -- a real, direct user report: Domain Agent already running
  // blind, before the human ever got a chance to say "use existing domain knowledge" vs. "here's
  // a database schema I want incorporated," meant their only option once they arrived at its chat
  // was to REVISE already-generated output instead of guiding the ORIGINAL generation. Approving
  // only switches the chat to Domain Agent; ChatPanel's own empty-state prompt is what invites the
  // human to guide the actual first run.
  //
  // Domain -> Architecture is the opposite, deliberately: Architecture Agent needs no comparable
  // human-guidance step (there's nothing analogous to "here's a database schema" to wait for), so
  // approving auto-starts it immediately -- see APPROVE_CONTINUATION_BY_STAGE's own `autoRun`.
  //
  // UI/UX -> Coder is the fourth link, also auto-run -- and the first stage where approving ALSO
  // locks every other pending version from being approved (UiuxVersionGroupList's own
  // `approveLocked`, computed here indirectly since this same `requestApproveConfirmation` is
  // what it calls) -- direct user request, so a stray approve on a different UI/UX version can't
  // re-trigger a second, conflicting Coder Agent run once one is already building.
  const approveContinuation = APPROVE_CONTINUATION_BY_STAGE[stage];
  const [confirmingArtifactId, setConfirmingArtifactId] = useState(null);
  // Direct user request: a domain-only alternate path -- reject this Enhanced SRS version and
  // start Architecture Agent using the feature's original SRS instead, for a human who doesn't
  // want Domain Agent's proposed enrichment. A separate id/dialog from confirmingArtifactId above
  // since this is a different action (reject, not approve) with different consequences to state.
  const [skippingEnhancementArtifactId, setSkippingEnhancementArtifactId] = useState(null);
  // Security is a parallel special case, not another APPROVE_CONTINUATION_BY_STAGE entry -- every
  // other entry's shape is "approve -> auto-run the next agent," but approving a security report
  // needs to ask the human what to do next (proceed anyway, or send it to the Coder Agent to fix)
  // rather than silently continuing -- see SecurityDecisionDialog.jsx's own docstring for why no
  // further loop-tracking state is needed beyond this one id.
  const [securityDecisionArtifactId, setSecurityDecisionArtifactId] = useState(null);
  // Optional MongoDB URI a human can supply right in the UI/UX-approval popup (one of two new
  // entry points for this, alongside the standalone Database Connection panel reachable from
  // FeatureListPanel -- see DatabaseConnectionPanel.jsx) -- only ever read/reset for the uiux
  // stage's own dialog instance, every other stage's dialog never renders the field at all.
  const [mongoUriDraft, setMongoUriDraft] = useState("");
  const mongoUriIsValid = looksLikeMongoUri(mongoUriDraft);
  const srsApproval = useApprovalMutation(featureId);
  // Shared with SecurityReportView.jsx (see SecurityAgentFlowContext's own docstring) -- read
  // unconditionally regardless of stage, same as every other agent's flow-context hook above, so
  // handleConfirmedApprove can auto-start a scan from the coder-approval branch below.
  const { runSecurity } = useSecurityAgentFlowContext();
  const isSecurityGenerating = stage === "security" && runSecurity.isPending;

  function requestApproveConfirmation(artifactId) {
    setMongoUriDraft("");
    setConfirmingArtifactId(artifactId);
  }

  async function handleConfirmedApprove() {
    try {
      await srsApproval.mutateAsync({ artifactId: confirmingArtifactId, status: "approved" });
    } catch {
      // Keep the dialog open -- srsApproval.error is rendered inside it so the human can see why
      // and retry or cancel, instead of the dialog vanishing on a failed approval.
      return;
    }

    setConfirmingArtifactId(null);
    selectAgent(approveContinuation.nextAgent);

    if (approveContinuation.autoRun) {
      // Not awaited: the run's own state already lives in the always-mounted flow provider (an
      // ArchitectureAgentFlowContext stream, or a UiuxAgentFlowContext mutation), so nothing is
      // lost by not waiting here -- awaiting would instead hold this dialog's "Approving..."
      // spinner up for the entire run. No pin/selection call is needed first either -- the
      // approval above just reverted every other version of this artifact_type back to pending
      // (exclusivity), so the pin-aware lookup on the backend resolves to exactly the version
      // just approved.
      if (approveContinuation.nextAgent === "architecture") {
        if (!architectureRunAlreadyInFlight) {
          handleRunArchitectureStream({ use_enhanced_srs_if_available: true, architecture_notes: null, human_comment: null });
        }
      } else if (approveContinuation.nextAgent === "uiux") {
        handleRunUiuxStream({ use_enhanced_srs_if_available: true, human_comment: null });
      } else if (approveContinuation.nextAgent === "coder") {
        // Safe by construction: run()/run_stream() (always what this fires, since UI/UX -> Coder
        // is always a FIRST run, never a revision) never short-circuit on a URI-only comment the
        // way revise() does -- passing one here saves it via the existing extract_mongodb_uri
        // call in run_stream() AND still runs the full plan/code/verify cycle using the
        // URI-stripped remainder for planning.
        handleRunCoderStream({ use_enhanced_srs_if_available: true, human_comment: mongoUriDraft.trim() || null });
      } else if (approveContinuation.nextAgent === "security") {
        // Security Agent has no streaming route (a scan is one plain POST) -- runSecurity is the
        // shared SecurityAgentFlowContext instance, so SecurityReportView's own Run/Re-run button
        // and the isSecurityGenerating view below both observe this exact same pending state.
        runSecurity.mutate({});
      }
    }
  }

  function requestSkipEnhancementConfirmation(artifactId) {
    setSkippingEnhancementArtifactId(artifactId);
  }

  // Domain-only alternate to handleConfirmedApprove above: instead of approving the Enhanced SRS,
  // rejects it (so the Domain stage shows a real, resolved decision rather than "Action required"
  // forever) and starts Architecture Agent with use_enhanced_srs_if_available: false, which -- per
  // ArchitectureAgent.run()/run_stream()'s own real logic -- never even looks up an approved
  // Enhanced SRS, so it naturally falls back to the feature's already-approved plain SRS with no
  // special-casing needed. Confirmed rejecting an artifact has no side effects on sibling versions
  // (only approval's own exclusivity-revert touches siblings), so no other Enhanced SRS version is
  // affected by this.
  async function handleConfirmedSkipEnhancement() {
    try {
      await srsApproval.mutateAsync({ artifactId: skippingEnhancementArtifactId, status: "rejected" });
    } catch {
      // Keep the dialog open -- srsApproval.error is rendered inside it, same as handleConfirmedApprove.
      return;
    }

    setSkippingEnhancementArtifactId(null);
    selectAgent("architecture");
    // Not awaited -- same reasoning as handleConfirmedApprove's own autoRun calls: the run's state
    // already lives in the always-mounted ArchitectureAgentFlowContext. Guarded the same way too --
    // see architectureRunAlreadyInFlight's own comment.
    if (!architectureRunAlreadyInFlight) {
      handleRunArchitectureStream({ use_enhanced_srs_if_available: false, architecture_notes: null, human_comment: null });
    }
  }

  // Security's own approve handler -- no confirmation dialog first (unlike every other gated
  // stage, there's nothing to warn about before approving; the real decision point is the popup
  // AFTER approval, not before it), just the real approval call, then open the decision popup.
  async function handleSecurityApprove(artifactId, comment) {
    await srsApproval.mutateAsync({ artifactId, status: "approved", reviewer_comment: comment ?? null });
    setSecurityDecisionArtifactId(artifactId);
  }

  // Shared by every approve-trigger surface for this stage (the "All Artifacts" list's own
  // per-row Approve button AND GovernancePanel's "Stage Actions" one) so approving from either
  // place opens the same decision popup, not just one of them.
  const onApproveClickForStage =
    stage === "security" ? handleSecurityApprove : approveContinuation ? requestApproveConfirmation : undefined;

  // Two direct-action buttons next to the security version dropdown (direct user request) --
  // an ADDITIONAL, always-visible path alongside SecurityDecisionDialog above (which still opens,
  // unchanged, right after clicking Approve). Hoisted here (not just inside the render IIFE below)
  // so both the handlers and the render block share one computation.
  const selectedSecurityArtifact =
    stage === "security" ? versions.find((v) => v.version === selectedVersion) || versions[0] || null : null;
  const securityReportQuery = useArtifactContent(selectedSecurityArtifact?.artifact_id ?? null);
  const securityReport = securityReportQuery.data?.content_json;
  const securityHasFindings = (securityReport?.findings || []).length > 0;
  // For SecurityReportView's "Compared to vN" section -- the version immediately before whatever
  // is selected, by version number (never "operative"/approved, just the prior one), so switching
  // the dropdown to any historical version still shows a meaningful comparison against what came
  // right before it. null when there's no prior version (the very first scan ever).
  const previousSecurityArtifact = selectedSecurityArtifact
    ? versions.find((v) => v.version === selectedSecurityArtifact.version - 1) ?? null
    : null;

  // Independent of selectedSecurityArtifact (whatever the version DROPDOWN happens to have
  // selected) -- the QA gate below must key off the truly latest scan by version number, not an
  // older approved-but-stale one a human could park the dropdown on. `versions` is already sorted
  // descending (listGatingArtifactVersions), so versions[0] is that latest version.
  const latestSecurityArtifact = stage === "security" ? versions[0] || null : null;
  const latestSecurityReportQuery = useArtifactContent(latestSecurityArtifact?.artifact_id ?? null);
  // Skip-aware (direct user request): a Critical finding a human has explicitly marked Skipped no
  // longer blocks -- see securityGate.js's own docstring. latestSecurityArtifact already carries
  // skipped_finding_ids as artifact-record metadata (no new fetch needed).
  const securityGateBlocksQa = computeSecurityGateBlocksQa(
    latestSecurityReportQuery.data?.content_json?.findings,
    latestSecurityArtifact?.skipped_finding_ids
  );

  const { qaRunFlow } = useQaAgentFlowContext();
  const [fixVulnerabilitiesArtifactId, setFixVulnerabilitiesArtifactId] = useState(null);
  const [isSendingFix, setIsSendingFix] = useState(false);
  const [isContinuingToQa, setIsContinuingToQa] = useState(false);
  // Distinguishes "the Coder Agent is revising because of a security fix" from any other,
  // unrelated in-flight Coder revision -- so the themed spinner below never mislabels a normal
  // Coder-chat revision, and only fires for the two real trigger surfaces (this button and
  // SecurityDecisionDialog's own "Send to Coder Agent to Fix").
  const [isSecurityFixInFlight, setIsSecurityFixInFlight] = useState(false);
  const securityFixLabel = useRotatingLabel(isSecurityFixInFlight ? SECURITY_FIX_PHRASES : null);

  // Reuses the exact same two calls SecurityDecisionDialog.handleSendToCoder already makes --
  // small enough to duplicate directly here rather than extracting a shared cross-component
  // helper. Deliberately does NOT change the report's own approval status; it's about to be
  // superseded by a new scan either way.
  async function handleConfirmedFixVulnerabilities() {
    setIsSendingFix(true);
    setIsSecurityFixInFlight(true);
    // Switch BEFORE awaiting the (multi-minute) revision, not after -- otherwise the human sees
    // nothing but a disabled button for the whole duration, since the Coder Agent's own live view
    // only renders while this stage is selected (a real, confirmed gap, not just cosmetic). Closing
    // the dialog here too, before the await, mirrors SecurityDecisionDialog's own already-fixed
    // ordering -- a real, reported bug: this one stayed open showing "Sending..." for the entire
    // revision because it used to only close in the try block, after the await resolved.
    selectAgent("coder");
    setFixVulnerabilitiesArtifactId(null);
    try {
      await handleCoderReviseStream({
        revision_comment: buildSecurityRevisionComment(securityReport, selectedSecurityArtifact?.skipped_finding_ids),
        revised_by: "security_agent_report",
      });
      runSecurity.mutate({ human_comment: "Re-scan after the Coder Agent's security-driven revision." });
    } finally {
      setIsSendingFix(false);
      setIsSecurityFixInFlight(false);
    }
  }

  // Deliberately a PLAIN approve call, not handleSecurityApprove -- that handler's whole job is
  // opening SecurityDecisionDialog afterward, which this direct button is explicitly meant to
  // skip (per the user's own explicit choice: also approve, but don't reopen the popup).
  async function handleContinueToQa() {
    if (!selectedSecurityArtifact || securityGateBlocksQa) return;
    setIsContinuingToQa(true);
    try {
      if (selectedSecurityArtifact.approval_status !== "approved") {
        await srsApproval.mutateAsync({ artifactId: selectedSecurityArtifact.artifact_id, status: "approved" });
      }
      selectAgent("qa");
      // Not awaited: QA's own pending state now lives in the shared QaAgentFlowContext's
      // qaRunFlow (the streaming run, direct user request for live progress here too), so
      // QaReportView (once the chat switches over) shows real, live progress -- matching every
      // other "fire the next agent, don't block this button on it" transition in this file.
      qaRunFlow.handleRunStream({ human_comment: "Continuing from Security Agent." });
    } finally {
      setIsContinuingToQa(false);
    }
  }

  // allArtifacts, not stageArtifacts -- a real bug found live: code_diff (the Coder stage's own
  // gating type) is deliberately excluded from stageArtifacts (see UNLISTED_ARTIFACT_TYPES), so
  // looking it up there resolved to undefined and the popup read "Approving vundefined...".
  // allArtifacts is the unfiltered list and always has whatever's being confirmed, regardless of
  // whether that type happens to be hidden from the "All Artifacts" listing.
  const confirmingArtifact = confirmingArtifactId
    ? allArtifacts.find((a) => a.artifact_id === confirmingArtifactId)
    : null;

  // Direct user correction: a UI/UX run/revision producing several pages at once must be
  // presented (and approved) as ONE version, not as N independent-looking per-page rows -- the
  // backend already treats it that way (shared version number + approval cascade, see
  // approval_service.py's UI/UX cascade); UiuxVersionGroupList makes that true on screen too.
  // Every other stage keeps the generic ArtifactList exactly as before.
  const uiuxVersionCount = stage === "uiux" ? new Set(stageArtifacts.map((a) => a.version)).size : null;

  return (
    <div className="flex flex-col gap-5">
      {(() => {
        const noArtifactLabel = NO_ARTIFACT_VERSION_LABEL_BY_STAGE[stage];
        if (noArtifactLabel) {
          return (
            <span className="self-start text-xs font-semibold text-gray-500 dark:text-gray-400 bg-gray-100 dark:bg-white/5 rounded-full px-3 py-1 whitespace-nowrap truncate">
              {noArtifactLabel}
            </span>
          );
        }

        const descriptors = PREVIOUS_STAGE_INPUTS_BY_STAGE[stage];
        if (!descriptors) return null;

        const agentLabel = `${STAGE_LABELS[stage] || stage} Agent`;

        const pills = descriptors
          .map((descriptor) => {
            const format = descriptor.artifactFormat || "json";
            let effective = getEffectiveActiveArtifact(
              allArtifacts, feature?.active_artifact_selection, descriptor.artifactType, format
            );
            let resolvedType = descriptor.artifactType;
            if (!effective && descriptor.fallbackArtifactType) {
              effective = getEffectiveActiveArtifact(
                allArtifacts, feature?.active_artifact_selection, descriptor.fallbackArtifactType, format
              );
              resolvedType = descriptor.fallbackArtifactType;
            }
            if (!effective) return null;

            const label = descriptor.label || ARTIFACT_TYPE_LABELS[resolvedType] || resolvedType;
            return { key: resolvedType, label, version: effective.version };
          })
          .filter(Boolean);

        if (pills.length === 0) return null;

        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            {pills.map((pill) => (
              <span
                key={pill.key}
                title={`${agentLabel} will use ${pill.label} v${pill.version} -- pin a different approved version from its row's radio button below.`}
                className="text-xs font-semibold text-accent-700 dark:text-accent-400 bg-accent-50 dark:bg-accent-500/10 rounded-full px-3 py-1 whitespace-nowrap truncate"
              >
                Using {pill.label} v{pill.version} for {agentLabel}
              </span>
            ))}
          </div>
        );
      })()}

      {showLegacyArtifactSurfaces && (
      <div>
        <h3 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">
          All Artifacts ({stage === "uiux" ? uiuxVersionCount : stageArtifacts.length})
        </h3>
        <ErrorBanner error={setActiveSelection.error} fallback="Failed to change which version is in use." />
        {stage === "uiux" ? (
          <UiuxVersionGroupList
            artifacts={stageArtifacts}
            featureId={featureId}
            onView={viewArtifact}
            onApproveClick={approveContinuation ? requestApproveConfirmation : undefined}
          />
        ) : (
          <ArtifactList
            artifacts={stageArtifacts}
            onView={viewArtifact}
            // Only used to gate the (separate, revise-only) Revise button -- approval controls are
            // no longer suppressed for any row of the gating type (see ArtifactList's docstring).
            gatingArtifactType={STAGE_GATING_ARTIFACT[stage]?.type ?? null}
            featureId={featureId}
            onApproveClick={onApproveClickForStage}
            activeArtifactType={activeArtifactType}
            activeArtifactId={effectiveActiveArtifact?.artifact_id}
            settingActive={setActiveSelection.isPending}
            onSetActive={(artifactId) =>
              setActiveSelection.mutate({ artifact_type: activeArtifactType, artifact_id: artifactId })
            }
          />
        )}
      </div>
      )}

      {isRevising ? (
        <LiveGenerationView
          displayText={declutterJsonForDisplay(revisionStreamedText)}
          hasStarted={revisionStreamStarted}
          connectingLabel="Connecting to Requirement Agent..."
          generatingLabel="Reviewing your requested change..."
        />
      ) : isDomainGenerating ? (
        <LiveGenerationView
          displayText={declutterJsonForDisplay(domainStreamedText)}
          hasStarted={domainStreamStarted}
          connectingLabel="Connecting to Domain Agent..."
          generatingLabel={isDomainRevising ? "Applying your requested change..." : "Enriching the SRS with domain knowledge..."}
        />
      ) : isArchitectureGenerating ? (
        <LiveGenerationView
          displayText={declutterJsonForDisplay(architectureStreamedText)}
          hasStarted={architectureStreamStarted}
          connectingLabel="Connecting to Architecture Agent..."
          generatingLabel={isArchitectureRevising ? "Applying your requested change..." : "Drafting the architecture plan..."}
          isFinalizing={Boolean(architecturePhase)}
          finalizingLabel={architecturePhase?.label}
          phaseStartedAt={architecturePhaseStartedAt}
        />
      ) : isCoderGenerating ? (
        <LiveGenerationView
          displayText={declutterJsonForDisplay(coderStreamedText)}
          hasStarted={coderStreamStarted}
          connectingLabel={isSecurityFixInFlight ? securityFixLabel : "Connecting to Coder Agent..."}
          generatingLabel={
            isSecurityFixInFlight ? securityFixLabel : isCoderRevising ? "Applying your requested change..." : "Planning the implementation..."
          }
          isFinalizing={isSecurityFixInFlight || Boolean(coderPhase)}
          finalizingLabel={isSecurityFixInFlight ? securityFixLabel : coderPhase?.label}
          phaseStartedAt={coderPhaseStartedAt}
        />
      ) : isUiuxGenerating ? (
        <LiveGenerationView
          displayText={declutterJsonForDisplay(uiuxStreamedText)}
          hasStarted={uiuxStreamStarted}
          connectingLabel="Connecting to UI/UX Agent..."
          generatingLabel={isUiuxRevising ? "Applying your requested change..." : "Generating ui_metadata..."}
          isFinalizing={Boolean(uiuxPhase)}
          finalizingLabel={uiuxPhase?.label}
          phaseStartedAt={uiuxPhaseStartedAt}
        />
      ) : isSecurityGenerating ? (
        // No streamed text -- a scan is one plain, non-streaming POST -- so this is isFinalizing
        // mode from the start (spinner + elapsed timer only), matching Architecture/Coder/UI-UX's
        // own non-streamable tails. Otherwise switching to the Security stage mid-scan (from the
        // Coder-approval auto-trigger) would show SecurityReportView's bare "No security scan has
        // been run yet" empty state instead of any visible progress.
        <LiveGenerationView
          displayText=""
          hasStarted={false}
          isFinalizing
          finalizingLabel="Scanning the merged code for vulnerabilities..."
          phaseStartedAt={runSecurity.submittedAt || null}
        />
      ) : versions.length === 0 && isRequirementStage ? (
        <RequirementSrsOutputPanel />
      ) : stage === "security" ? (
        // Unlike every other stage, Security Agent has no revise() flow to trigger a first run
        // from (see pipelineStages.js's REVISABLE_STAGES -- a re-run IS the whole operation) --
        // SecurityReportView itself renders the "Run Security Scan" empty-state action when
        // `artifact` is null, so this branch (unlike the generic ones below) fires regardless of
        // versions.length. (SecurityAgentChat, the Result tab's chat-panel counterpart, has its
        // own separate empty-state trigger for the same underlying action.)
        //
        // Deliberately skips the generic "All Artifacts" full-list AND GovernancePanel further
        // down (both suppressed for this stage, see their own render guards) -- a compact version
        // dropdown plus one inline approval control replaces both, so picking a version and
        // approving/rejecting it happen in the same place instead of two differently-resolved
        // surfaces (direct user request). "Awaiting your review" now renders BELOW the report
        // (direct user request), and the two new "next step" buttons sit next to the version
        // dropdown -- selectedSecurityArtifact/securityReport/securityHasFindings are all hoisted
        // above (shared with handleConfirmedFixVulnerabilities/handleContinueToQa).
        (() => {
          const securityApproveLocked = selectedSecurityArtifact
            ? Boolean(
                stageArtifacts.find(
                  (a) =>
                    a.artifact_type === "security_report" &&
                    a.approval_status === "approved" &&
                    a.artifact_id !== selectedSecurityArtifact.artifact_id
                )
              )
            : false;

          return (
            <div className="flex flex-col gap-4">
              {versions.length > 0 && (
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <VersionSelect versions={versions} selectedVersion={selectedVersion} onChange={setSelectedVersion} />
                  <div className="flex items-center gap-3 flex-wrap">
                    {selectedSecurityArtifact && (
                      <a
                        href={artifactDownloadPdfUrl(selectedSecurityArtifact.artifact_id)}
                        className="text-sm text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold"
                      >
                        Download Security Report
                      </a>
                    )}
                    <button
                      type="button"
                      onClick={() => setFixVulnerabilitiesArtifactId(selectedSecurityArtifact?.artifact_id ?? null)}
                      disabled={!selectedSecurityArtifact || !securityHasFindings || coderReviseStream.isPending}
                      title="Send this report to the Coder Agent to fix the findings, then re-scan"
                      className="text-sm bg-red-600 hover:bg-red-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
                    >
                      Fix Vulnerabilities
                    </button>
                    <button
                      type="button"
                      onClick={handleContinueToQa}
                      disabled={!selectedSecurityArtifact || isContinuingToQa || srsApproval.isPending || securityGateBlocksQa}
                      title={
                        securityGateBlocksQa
                          ? "The latest security scan still has Critical findings -- fix or mark them Skipped before continuing to QA Agent"
                          : "Approve this report and move on to QA Agent"
                      }
                      className="text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
                    >
                      {isContinuingToQa ? "Continuing..." : "Continue to QA Agent"}
                    </button>
                  </div>
                </div>
              )}

              <SecurityReportView artifact={selectedSecurityArtifact} previousArtifact={previousSecurityArtifact} />

              {selectedSecurityArtifact &&
                (selectedSecurityArtifact.approval_status === "pending" ? (
                  <ApprovalPanel
                    featureId={featureId}
                    artifact={selectedSecurityArtifact}
                    approveLocked={securityApproveLocked}
                    onApproveClick={(comment) => handleSecurityApprove(selectedSecurityArtifact.artifact_id, comment)}
                  />
                ) : (
                  <p className="text-xs text-gray-400 dark:text-gray-500">
                    v{selectedSecurityArtifact.version} is {selectedSecurityArtifact.approval_status}.
                  </p>
                ))}
            </div>
          );
        })()
      ) : stage === "qa" ? (
        // Same reasoning as the security branch above, minus the approval popup entirely -- QA
        // stays auto-approved (see pipelineStages.js's AUTO_APPROVED_STAGES), so there's no
        // pending/approved distinction to render here, just the version dropdown plus
        // QaReportView (which owns its own "Re-run" / "Send Failing Tests to Coder Agent" actions).
        // Also fires the "Run QA Scan" empty state itself when `artifact` is null, same as
        // SecurityReportView, so this branch fires regardless of versions.length too.
        (() => {
          const selectedQaArtifact = versions.find((v) => v.version === selectedVersion) || versions[0] || null;
          return (
            <div className="flex flex-col gap-4">
              {versions.length > 0 && (
                <div className="flex items-center justify-between flex-wrap gap-2">
                  <VersionSelect versions={versions} selectedVersion={selectedVersion} onChange={setSelectedVersion} />
                  {selectedQaArtifact && (
                    <div className="flex items-center gap-3 flex-wrap">
                      <a
                        href={artifactDownloadPdfUrl(selectedQaArtifact.artifact_id)}
                        className="text-sm text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold"
                      >
                        Download QA Report
                      </a>
                      <a
                        href={featureCodeWithQaReportDownloadUrl(featureId)}
                        className="text-sm bg-accent-600 hover:bg-accent-700 text-white font-semibold px-3 py-1.5 rounded-md"
                      >
                        Download Project + QA Report (.zip)
                      </a>
                    </div>
                  )}
                </div>
              )}

              <QaReportView artifact={selectedQaArtifact} />
            </div>
          );
        })()
      ) : versions.length === 0 ? (
        <p className="text-sm text-gray-400 dark:text-gray-500 italic">No output yet for this stage.</p>
      ) : (
        <div>
          {(() => {
            // Hoisted once and reused everywhere this section needs "the artifact behind the
            // currently-selected version" -- previously computed separately (identically) in two
            // different inline IIFEs; also now backs the new Approve & Move to Security button AND
            // (for CONSOLIDATED_APPROVAL_STAGES) GatingArtifactApprovalPanel below.
            const selectedVersionArtifact = versions.find((v) => v.version === selectedVersion) || versions[0];
            const pdfDocumentLabel = PDF_DOCUMENT_LABEL_BY_STAGE[stage];
            // Domain Improvements attaches to whichever Enhanced SRS version is being viewed --
            // same version number (both saved together, see domain_agent's _save_domain_artifacts),
            // never its own listed/approvable row (see UNLISTED_ARTIFACT_TYPES above).
            const domainImprovements =
              stage === "domain"
                ? allArtifacts.find(
                    (a) => a.artifact_type === "domain_improvements" && a.version === selectedVersionArtifact.version
                  )
                : null;
            // Same computation GovernancePanel.jsx/Security's own securityApproveLocked already
            // use: some OTHER version of the same artifact_type is already approved.
            const approveLocked =
              CONSOLIDATED_APPROVAL_STAGES.includes(stage) &&
              stageArtifacts.some(
                (a) =>
                  a.artifact_type === selectedVersionArtifact.artifact_type &&
                  a.approval_status === "approved" &&
                  a.artifact_id !== selectedVersionArtifact.artifact_id
              );
            // Direct user request: once approved AND the pipeline has moved on to the next agent,
            // revoke becomes permanently unavailable -- hasNextStageStarted is the artifact-
            // existence check also enforced server-side (approval_service.py's revoke_approval);
            // nextStageInFlight is a frontend-only extra safeguard for the narrow window where the
            // next stage is already generating but hasn't saved its first artifact yet.
            const nextStageInFlight =
              (stage === "requirement" && isDomainGenerating) ||
              (stage === "domain" && isArchitectureGenerating) ||
              (stage === "architecture" && isUiuxGenerating);
            const canRevoke = !hasNextStageStarted(stage, allArtifacts) && !nextStageInFlight;
            return (
          <>
          <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
            <VersionSelect versions={versions} selectedVersion={selectedVersion} onChange={setSelectedVersion} />
            <div className="flex items-center gap-3 flex-wrap">
              <a
                href={
                  pdfDocumentLabel
                    ? artifactDownloadPdfUrl(selectedVersionArtifact.artifact_id)
                    : artifactDownloadUrl(selectedVersionArtifact.artifact_id)
                }
                className="text-sm text-accent-600 dark:text-accent-400 hover:text-accent-800 dark:hover:text-accent-300 font-semibold"
              >
                {pdfDocumentLabel || "Download report"}
              </a>
              {stage === "coder" && selectedVersionArtifact.approval_status === "pending" && (
                <button
                  type="button"
                  onClick={() => requestApproveConfirmation(selectedVersionArtifact.artifact_id)}
                  className="text-sm bg-green-600 hover:bg-green-700 text-white font-semibold px-3 py-1.5 rounded-md"
                >
                  Approve & Move to Security
                </button>
              )}
              {/* Direct user request: a quick Approve button right next to the version dropdown,
                  so approving doesn't require scrolling past the whole rendered document first --
                  mirrors the Coder stage's own "Approve & Move to Security" button above, reusing
                  the exact same requestApproveConfirmation/handleConfirmedApprove flow. Purely
                  additive: GatingArtifactApprovalPanel further down (Reject/Request Revision/
                  Revoke/Delete, plus its own Approve) is untouched. */}
              {CONSOLIDATED_APPROVAL_STAGES.includes(stage) && selectedVersionArtifact.approval_status === "pending" && (
                <button
                  type="button"
                  onClick={() => requestApproveConfirmation(selectedVersionArtifact.artifact_id)}
                  disabled={approveLocked}
                  title={
                    approveLocked
                      ? "Another version is already approved -- reject it first to approve a different one"
                      : undefined
                  }
                  className="text-sm bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white font-semibold px-3 py-1.5 rounded-md"
                >
                  Approve
                </button>
              )}
              {/* Direct user request: a domain-only alternate to Approve -- reject this Enhanced
                  SRS version and start Architecture Agent with the feature's original SRS instead,
                  for a human who doesn't want Domain Agent's proposed enrichment. */}
              {stage === "domain" && selectedVersionArtifact.approval_status === "pending" && (
                <button
                  type="button"
                  onClick={() => requestSkipEnhancementConfirmation(selectedVersionArtifact.artifact_id)}
                  className="text-sm bg-white dark:bg-white/10 border border-gray-300 dark:border-gray-600 hover:bg-gray-50 dark:hover:bg-white/20 text-gray-700 dark:text-gray-200 font-semibold px-3 py-1.5 rounded-md"
                >
                  Use Raw SRS Instead
                </button>
              )}
              {stage === "coder" && (
                <a
                  href={featureCodeDownloadUrl(featureId)}
                  className="text-sm bg-accent-600 hover:bg-accent-700 text-white font-semibold px-3 py-1.5 rounded-md"
                >
                  Download Project (.zip)
                </a>
              )}
            </div>
          </div>

          {stage === "uiux" ? (
            <UiuxPagePreviewsPanel allArtifacts={allArtifacts} />
          ) : (
            <div>
              <ArtifactContentView
                artifact={selectedVersionArtifact}
                domainImprovementsArtifact={domainImprovements}
              />
              {stage === "architecture" && (
                <ArchitectureDiagramsGallery allArtifacts={allArtifacts} version={selectedVersionArtifact.version} />
              )}
              {domainImprovements && (
                <div className="mt-5 pt-5 border-t border-gray-100 dark:border-gray-800">
                  <ArtifactContentView artifact={domainImprovements} />
                </div>
              )}
            </div>
          )}

          {CONSOLIDATED_APPROVAL_STAGES.includes(stage) && (
            <div className="mt-4 pt-4 border-t border-gray-100 dark:border-gray-800">
              <GatingArtifactApprovalPanel
                featureId={featureId}
                artifact={selectedVersionArtifact}
                approveLocked={approveLocked}
                canRevoke={canRevoke}
                onApproveClick={onApproveClickForStage}
              />
            </div>
          )}
          </>
            );
          })()}
        </div>
      )}

      {showLegacyArtifactSurfaces && (
      <div className="pt-4 border-t border-gray-100 dark:border-gray-800">
        <h3 className="text-xs font-bold text-gray-400 dark:text-gray-500 uppercase tracking-wide mb-2">Governance</h3>
        <GovernancePanel
          stage={stage}
          featureId={featureId}
          allArtifacts={allArtifacts}
          stageArtifacts={stageArtifacts}
          onApproveClick={onApproveClickForStage}
        />
      </div>
      )}

      {approveContinuation && (
        <ConfirmDialog
          open={Boolean(confirmingArtifactId)}
          onClose={() => {
            if (!srsApproval.isPending) {
              setConfirmingArtifactId(null);
              setMongoUriDraft("");
            }
          }}
          onConfirm={handleConfirmedApprove}
          title={approveContinuation.title}
          message={approveContinuation.message(confirmingArtifact?.version)}
          confirmLabel="Approve & Continue"
          confirmingLabel="Approving..."
          tone="primary"
          confirming={srsApproval.isPending}
          confirmDisabled={stage === "uiux" && mongoUriDraft.trim().length > 0 && !mongoUriIsValid}
          error={srsApproval.error}
          errorFallback="Failed to submit approval decision."
        >
          {stage === "uiux" && (
            <div>
              <label className="block text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-1">
                MongoDB connection string (optional)
              </label>
              <input
                type="text"
                value={mongoUriDraft}
                onChange={(e) => setMongoUriDraft(e.target.value)}
                placeholder="mongodb+srv://user:password@cluster0.xxx.mongodb.net/mydb"
                className="w-full px-3 py-2 text-sm font-mono border border-gray-300 dark:border-gray-600 dark:bg-white/5 dark:text-gray-100 rounded-md focus:outline-none focus:border-accent-500"
              />
              {mongoUriDraft.trim().length > 0 && !mongoUriIsValid && (
                <p className="text-xs text-red-600 dark:text-red-400 mt-1">
                  Must start with mongodb:// or mongodb+srv://
                </p>
              )}
              <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
                Leave blank to keep serving seed data, or add/change it later from the Database
                Connection panel.
              </p>
            </div>
          )}
        </ConfirmDialog>
      )}

      <ConfirmDialog
        open={Boolean(skippingEnhancementArtifactId)}
        onClose={() => {
          if (!srsApproval.isPending) setSkippingEnhancementArtifactId(null);
        }}
        onConfirm={handleConfirmedSkipEnhancement}
        title="Skip this enhancement and continue with the raw SRS?"
        message="This marks this Enhanced SRS version as rejected and starts Architecture Agent using the feature's original SRS instead -- Domain Agent's proposed additions won't be included in the design."
        confirmLabel="Use Raw SRS & Continue"
        confirmingLabel="Working..."
        tone="primary"
        confirming={srsApproval.isPending}
        error={srsApproval.error}
        errorFallback="Failed to skip the enhancement."
      />

      <SecurityDecisionDialog
        artifactId={securityDecisionArtifactId}
        featureId={featureId}
        skippedFindingIds={
          versions.find((v) => v.artifact_id === securityDecisionArtifactId)?.skipped_finding_ids ?? []
        }
        onClose={() => setSecurityDecisionArtifactId(null)}
        onFixStart={() => {
          setIsSecurityFixInFlight(true);
          selectAgent("coder");
        }}
        onFixSettled={() => setIsSecurityFixInFlight(false)}
      />

      <ConfirmDialog
        open={Boolean(fixVulnerabilitiesArtifactId)}
        onClose={() => {
          if (!isSendingFix) setFixVulnerabilitiesArtifactId(null);
        }}
        onConfirm={handleConfirmedFixVulnerabilities}
        title="Send this report to the Coder Agent to fix?"
        message="This sends the report's findings to the Coder Agent, which revises the code to address them. Once that finishes, the Security Agent automatically re-scans the fixed code."
        confirmLabel="Send to Coder Agent"
        confirmingLabel="Sending..."
        tone="primary"
        confirming={isSendingFix}
        error={coderReviseStream.error || runSecurity.error}
        errorFallback="Failed to send the report to the Coder Agent."
      />
    </div>
  );
}
