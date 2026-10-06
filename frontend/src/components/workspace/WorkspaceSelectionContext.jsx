import { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SELECTABLE_AGENT_STAGES } from "../../lib/pipelineStages";
import { useGraphStatus } from "../../hooks/usePipeline";
import { useFeatureArtifacts, useArtifactContent } from "../../hooks/useArtifacts";
import { deriveStageStatus, listGatingArtifactVersions } from "../../lib/deriveStageStatus";
import { deriveCurrentStage } from "../../lib/deriveCurrentStage";
import { computeSecurityGateBlocksQa } from "../../lib/securityGate";

const WorkspaceSelectionContext = createContext(null);

// The left/middle/right panels are siblings, not parent/child -- picking a feature in the left
// panel must simultaneously retarget the middle chat (which agent's conversation is shown) and
// the right panel (which agent's output is shown), and picking an agent in the middle panel must
// retarget the right panel too. A small shared context is the lightest mechanism that lets three
// siblings agree on "what are we looking at right now" without prop-drilling through the page
// component on every change -- no new state library needed, matching this app's existing total
// absence of one.
//
// selectedAgent is seeded from (and kept in sync with) the `agent` URL query param -- direct user
// report: refreshing the browser always reset the visible chat back to Requirement Agent, which
// read as "the other agent's chat history disappeared" even though every agent's chat data was
// always persisted server-side (stage_events/artifacts/approvals, or the requirement_conversations
// record) -- only the CLIENT-side "which agent's chat is currently on screen" state was ever lost.
// A plain useState default has no way to survive a full page reload; the URL does, and it's
// already the mechanism this page uses for featureId (see ProjectWorkspacePage), so a fresh load
// of the exact same URL now reopens the exact same agent's chat instead of silently jumping back
// to Requirement.
//
// When there's NO `?agent=` to seed from at all (a fresh project open, or a manual feature
// switch in the sidebar) -- direct user request, see the auto-select effect below -- the initial
// "requirement" default here is only ever a brief transient value; that effect corrects it to
// the feature's real last-executed agent (via currentStage) the moment its data resolves.
export function WorkspaceSelectionProvider({ featureId, onSelectFeature, children }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const urlAgent = searchParams.get("agent");
  const [selectedAgent, setSelectedAgentState] = useState(
    SELECTABLE_AGENT_STAGES.includes(urlAgent) ? urlAgent : "requirement"
  );
  const [selectedModel, setSelectedModel] = useState(null);
  const [activeOutputTab, setActiveOutputTab] = useState("result");
  const [viewingArtifact, setViewingArtifact] = useState(null);
  // Cursor-style fullscreen toggle for the live preview iframe -- UI-only, no server round trip,
  // so it lives here alongside activeOutputTab/viewingArtifact rather than in preview-specific
  // state. Reset whenever the feature changes (selectFeature below), same as the other UI-only
  // fields, so switching features never leaves a stale fullscreen preview covering the new one.
  const [isPreviewExpanded, setIsPreviewExpanded] = useState(false);

  // "How far can the human currently navigate in the agent picker" -- computed once here (not
  // per-leaf-component) since this context is already the shared home for "what are the three
  // sibling panels looking at right now." React Query dedupes these against whatever ResultTab/
  // OutputPanel/FeatureListItem already fetch for the same featureId, so this is a cache read,
  // not an extra network request. Mirrors FeatureListItem.jsx's own established
  // graphStatus+artifacts -> stageStatuses -> deriveCurrentStage pipeline exactly.
  const { data: graphStatus, isLoading: isGraphStatusLoading } = useGraphStatus(featureId);
  const { data: artifacts, isLoading: isArtifactsLoading } = useFeatureArtifacts(featureId);
  const stageStatuses = {};
  for (const stage of SELECTABLE_AGENT_STAGES) {
    stageStatuses[stage] = deriveStageStatus({ stage, graphStatus, artifacts: artifacts || [] });
  }
  // deriveCurrentStage returns undefined once every stage is APPROVED (a fully-completed
  // feature) -- fall back to the LAST stage, not the first, so a finished pipeline never gates
  // anything (the naive `|| "requirement"` fallback would incorrectly re-lock everything down).
  const currentStage =
    deriveCurrentStage(graphStatus, stageStatuses) ?? SELECTABLE_AGENT_STAGES[SELECTABLE_AGENT_STAGES.length - 1];

  // Security is a soft/auto-approved gate (its report is "approved"-equivalent the moment it
  // exists, regardless of findings), so currentStage above already treats QA as reachable the
  // instant ANY security report exists -- with no awareness of content. This is a genuine,
  // separate exception layered on top, not folded into deriveStageStatus/deriveCurrentStage
  // (which are shared with FeatureListItem.jsx and stay purely approval-status-based): direct
  // user request that QA must not be reachable while the LATEST security scan still has Critical
  // findings. Keyed on the latest version by number specifically (listGatingArtifactVersions
  // sorts descending) -- NOT "approved"/"operative" -- so an old, approved-but-stale clean
  // version can never mask a newer, still-pending Critical-bearing one.
  const securityVersions = listGatingArtifactVersions("security", artifacts || []);
  const latestSecurityArtifactId = securityVersions[0]?.artifact_id ?? null;
  const { data: latestSecurityReportData } = useArtifactContent(latestSecurityArtifactId);
  // Skip-aware (direct user request): a Critical finding a human has explicitly marked Skipped no
  // longer blocks -- see securityGate.js's own docstring. securityVersions[0] already carries
  // skipped_finding_ids as artifact-record metadata (no new fetch needed).
  const securityGateBlocksQa = computeSecurityGateBlocksQa(
    latestSecurityReportData?.content_json?.findings,
    securityVersions[0]?.skipped_finding_ids
  );

  // Direct user request: opening a project (or switching to a different feature) should land on
  // whichever agent that feature was LAST worked on, not always reset to Requirement -- reuses
  // currentStage above, which already answers exactly this ("how far has this feature's real
  // pipeline progress gotten"). Tracks which featureId an agent has already been auto-resolved
  // for, so this only ever fires once per feature (never fights a human's own later manual pick).
  const autoSelectedFeatureRef = useRef(null);

  useEffect(() => {
    if (autoSelectedFeatureRef.current !== featureId) {
      autoSelectedFeatureRef.current = null;
    }
  }, [featureId]);

  useEffect(() => {
    if (!featureId) return;
    if (autoSelectedFeatureRef.current === featureId) return;

    const urlAgentNow = searchParams.get("agent");
    if (SELECTABLE_AGENT_STAGES.includes(urlAgentNow)) {
      // An explicit agent is already specified (a deep link, or a page reload -- see this
      // component's own top-of-file comment) -- respect it, nothing to auto-select.
      autoSelectedFeatureRef.current = featureId;
      return;
    }
    // Real bug found live: currentStage is NEVER actually undefined/falsy while data is still
    // loading -- deriveStageStatus treats a not-yet-arrived `artifacts` array the same as a
    // genuinely empty one (both fall back to `artifacts || []`), so deriveCurrentStage happily
    // (and wrongly) returns "requirement" immediately, before the real data arrives, and the ref
    // guard above then locks that wrong answer in forever for this feature. The query's own
    // isLoading is the only reliable "not ready yet" signal -- wait on that instead.
    if (isGraphStatusLoading || isArtifactsLoading) return;

    autoSelectedFeatureRef.current = featureId;
    setSelectedAgentState(currentStage);
    setAgentQueryParam(currentStage);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setAgentQueryParam is a plain
    // function recreated every render (see its own definition below); including it would defeat
    // the point of this effect's guard.
  }, [featureId, currentStage, isGraphStatusLoading, isArtifactsLoading, searchParams]);

  function setAgentQueryParam(stage) {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (stage) {
          next.set("agent", stage);
        } else {
          next.delete("agent");
        }
        return next;
      },
      { replace: true }
    );
  }

  const value = useMemo(
    () => ({
      selectedFeatureId: featureId,
      selectFeature: (id) => {
        // Deliberately only ONE router call here (onSelectFeature -> navigate to the bare
        // `/features/{id}` path, no query string) -- a real, live-found bug: a second,
        // synchronous setSearchParams(...) call right after (as this used to do, to clear
        // `?agent=`) resolves against a STALE captured `location.pathname` from before the
        // navigate's change commits, and silently reverts the whole URL back to wherever it was
        // BEFORE this click -- reproducible any time the starting URL has no explicit featureId
        // segment (exactly the state a fresh project-open leaves you in, see
        // ProjectWorkspacePage's own effectiveFeatureId fallback). navigate() to a plain path
        // with no `?query` already fully replaces the location (clears any prior search string)
        // as a normal side effect, so the separate clear call was both redundant AND the actual
        // cause of the bug.
        onSelectFeature(id);
        setSelectedAgentState("requirement");
        setActiveOutputTab("result");
        setIsPreviewExpanded(false);
      },
      selectedAgent,
      selectAgent: (stage) => {
        setSelectedAgentState(stage);
        setActiveOutputTab("result");
        setAgentQueryParam(stage);
      },
      selectedModel,
      setSelectedModel,
      activeOutputTab,
      setActiveOutputTab,
      viewingArtifact,
      viewArtifact: setViewingArtifact,
      isPreviewExpanded,
      togglePreviewExpanded: () => setIsPreviewExpanded((v) => !v),
      currentStage,
      securityGateBlocksQa,
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- setAgentQueryParam/onSelectFeature
    // are recreated every render (setSearchParams identity, prop from parent); including them
    // would invalidate this memo every render and defeats its purpose. featureId/selectedAgent/etc
    // are the only values that actually need to trigger a new value object.
    [
      featureId,
      selectedAgent,
      selectedModel,
      activeOutputTab,
      viewingArtifact,
      isPreviewExpanded,
      currentStage,
      securityGateBlocksQa,
    ]
  );

  return <WorkspaceSelectionContext.Provider value={value}>{children}</WorkspaceSelectionContext.Provider>;
}

export function useWorkspaceSelection() {
  const ctx = useContext(WorkspaceSelectionContext);
  if (!ctx) {
    throw new Error("useWorkspaceSelection must be used within a WorkspaceSelectionProvider");
  }
  return ctx;
}
