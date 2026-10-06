import { MANUAL_RUN_STAGES, STAGE_SEQUENCE, STUCK_TIMEOUT_MS } from "./pipelineStages";
import { STAGE_GATING_ARTIFACT } from "./artifactTypeMeta";

// Best-effort, client-side reconstruction of "what stage is this feature at" -- the backend
// has no dedicated status API beyond graph-status's {next, values} shape, and feature_status/
// current_agent on the Feature resource are documented as unreliable past the Architecture
// stage. This heuristic mirrors exactly what the graph itself does (GATED_STAGES + approval
// gates), just reconstructed from artifact state + graph-status rather than true graph
// internals -- correct scope for a system with no real status endpoint, not a permanent gap.
export const STATUS = {
  NOT_STARTED: "not_started",
  ACTION_REQUIRED: "action_required",
  AWAITING_REVIEW: "awaiting_review",
  PROCESSING: "processing",
  POSSIBLY_STUCK: "possibly_stuck",
  APPROVED: "approved",
  REJECTED: "rejected",
};

// Resolves the single version of a gating artifact_type that best represents "what a human
// should act on / what's currently true for this stage" -- considering EVERY version's
// approval_status, not just the highest version number. A rejected/superseded newest version
// must never mask an older version that's still genuinely pending a decision: a real reported
// bug had rejecting the latest SRS revision show the whole feature as "Rejected" (and hid its
// Approve/Reject controls entirely) even though an earlier version was still sitting there,
// pending, fully approvable.
//
// Precedence: an APPROVED version always wins (the highest-versioned one, if more than one
// somehow exists) -- else the highest-versioned still-PENDING/REVISION_REQUESTED version (a real
// decision still waiting, regardless of whether some OTHER, newer version was rejected) -- else
// the highest-versioned version overall (every version has been decided on and rejected --
// nothing pending, correctly reported as rejected) -- else null (no artifact of this type exists
// yet). Deleting a rejected version (leaving only a pending one behind) naturally resolves
// correctly through this same precedence with no special-casing needed.
export function resolveGatingArtifact(artifacts, artifactType, artifactFormat = null) {
  const matches = artifacts.filter(
    (artifact) =>
      artifact.artifact_type === artifactType && (artifactFormat == null || artifact.artifact_format === artifactFormat)
  );

  if (matches.length === 0) {
    return null;
  }

  const byVersionDesc = [...matches].sort((a, b) => b.version - a.version);

  const approved = byVersionDesc.find((a) => a.approval_status === "approved");
  if (approved) return approved;

  const pending = byVersionDesc.find((a) => a.approval_status === "pending" || a.approval_status === "revision_requested");
  if (pending) return pending;

  return byVersionDesc[0];
}

/**
 * @param {object} params
 * @param {string} params.stage - one of GATED_STAGES
 * @param {{next: string[]}|null|undefined} params.graphStatus
 * @param {Array} params.artifacts - all artifacts for the feature (any stage)
 * @param {number|null} [params.processingSince] - ms timestamp when this stage was first
 *   observed as "processing" (tracked by the caller, e.g. a useRef in FeatureDetailPage)
 * @param {number} [params.now]
 */
export function deriveStageStatus({ stage, graphStatus, artifacts, processingSince = null, now = Date.now() }) {
  const gating = STAGE_GATING_ARTIFACT[stage];
  const latest = gating ? resolveGatingArtifact(artifacts, gating.type, gating.format) : null;
  const nextNodes = graphStatus?.next || [];
  const isGraphProcessingThisStage = nextNodes.includes(`${stage}_node`);

  if (!latest) {
    if (MANUAL_RUN_STAGES.includes(stage)) {
      return STATUS.ACTION_REQUIRED;
    }

    if (isGraphProcessingThisStage) {
      const timeout = STUCK_TIMEOUT_MS[stage] ?? Infinity;

      if (processingSince != null && now - processingSince > timeout) {
        return STATUS.POSSIBLY_STUCK;
      }

      return STATUS.PROCESSING;
    }

    return STATUS.NOT_STARTED;
  }

  if (latest.approval_status === "approved") {
    return STATUS.APPROVED;
  }

  if (latest.approval_status === "rejected") {
    return STATUS.REJECTED;
  }

  // "pending" or "revision_requested"
  return STATUS.AWAITING_REVIEW;
}

// The version of a stage's gating artifact a human should act on right now -- see
// resolveGatingArtifact's own docstring for the exact precedence. Named "operative", not
// "latest", because it deliberately is NOT always the highest version number.
export function getOperativeGatingArtifact(stage, artifacts) {
  const gating = STAGE_GATING_ARTIFACT[stage];
  return gating ? resolveGatingArtifact(artifacts, gating.type, gating.format) : null;
}

// Every version of a stage's gating artifact, newest first -- powers the Output tab's version
// picker (distinct from getOperativeGatingArtifact, which returns the one version that's
// currently actionable, not necessarily the newest one).
export function listGatingArtifactVersions(stage, artifacts) {
  const gating = STAGE_GATING_ARTIFACT[stage];
  if (!gating) return [];

  return artifacts
    .filter((a) => a.artifact_type === gating.type && a.artifact_format === gating.format)
    .sort((a, b) => b.version - a.version);
}

// True once the NEXT stage in the pipeline has produced any output at all (any artifact of its
// own gating type exists for this feature) -- direct user request: once an approval on this stage
// has been "acted on" by the pipeline moving forward, it should become permanently unrevokable,
// even navigating back later. Existence-based (not "has fully completed"), matching the backend's
// own equivalent check in approval_service.py -- both are intentionally a coarse, cheap signal,
// not a perfect one (see GatingArtifactApprovalPanel's own extra in-flight-generation safeguard on
// the frontend for the narrow gap between "next stage started generating" and "next stage saved
// its first artifact").
export function hasNextStageStarted(stage, artifacts) {
  const nextStage = STAGE_SEQUENCE[STAGE_SEQUENCE.indexOf(stage) + 1];
  const nextGating = nextStage ? STAGE_GATING_ARTIFACT[nextStage] : null;
  return nextGating ? artifacts.some((a) => a.artifact_type === nextGating.type) : false;
}
