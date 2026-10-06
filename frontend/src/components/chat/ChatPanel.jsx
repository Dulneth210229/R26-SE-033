import { useEffect, useRef, useState } from "react";
import { useFeature } from "../../hooks/useFeatures";
import { useFeatureApprovals, useFeatureEvents, useGraphStatus } from "../../hooks/usePipeline";
import { useFeatureArtifacts } from "../../hooks/useArtifacts";
import { deriveStageStatus, listGatingArtifactVersions, STATUS } from "../../lib/deriveStageStatus";
import { GATED_STAGES, STAGE_LABELS } from "../../lib/pipelineStages";
import { buildAgentTimeline } from "../../lib/buildAgentTimeline";
import { SUGGESTION_CHIPS } from "../../lib/suggestionChips";
import { useWorkspaceSelection } from "../workspace/WorkspaceSelectionContext";
import { useAuth } from "../../contexts/AuthContext";
import ChatBubble from "./ChatBubble";
import ChatComposerBox from "./ChatComposerBox";
import RequirementConversationChat from "./RequirementConversationChat";
import DomainAgentChat from "./DomainAgentChat";
import ArchitectureAgentChat from "./ArchitectureAgentChat";
import UiuxAgentChat from "./UiuxAgentChat";
import CoderAgentChat from "./CoderAgentChat";
import SecurityAgentChat from "./SecurityAgentChat";
import QaAgentChat from "./QaAgentChat";
import LoadingSpinner from "../common/LoadingSpinner";
import ErrorBanner from "../common/ErrorBanner";

function isProcessingNode(graphStatus, stage) {
  return Boolean(graphStatus?.next?.includes(`${stage}_node`));
}

// "System must render what agent is currently running" -- independent of which agent the user
// has selected to chat with, this surfaces whichever auto-run stage the LangGraph pipeline is
// actively executing right now (domain/uiux/coder are the only stages that ever run unattended).
function RunningBadge({ runningStage }) {
  if (!runningStage) return null;
  return (
    <div className="flex items-center gap-1.5 bg-accent-50 dark:bg-accent-500/10 text-accent-700 dark:text-accent-300 text-xs font-semibold rounded-full px-2.5 py-1 flex-shrink-0">
      <span className="relative flex h-1.5 w-1.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-accent-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-accent-500" />
      </span>
      {STAGE_LABELS[runningStage]} Agent running
    </div>
  );
}

function ChatHeader({ feature, runningStage }) {
  return (
    <div className="flex items-center justify-between gap-2 flex-shrink-0 pb-3 border-b border-gray-100 dark:border-gray-800">
      <div className="min-w-0">
        <h2 className="text-sm font-bold text-gray-900 dark:text-gray-100 truncate">{feature?.feature_name || "..."}</h2>
        <p className="text-xs text-gray-400 dark:text-gray-500 truncate">{feature?.feature_description}</p>
      </div>
      <RunningBadge runningStage={runningStage} />
    </div>
  );
}

export default function ChatPanel({ featureId }) {
  const { selectedAgent, selectAgent, viewArtifact } = useWorkspaceSelection();
  const { user } = useAuth();
  const { data: feature } = useFeature(featureId);
  const { data: graphStatus, isLoading: graphLoading } = useGraphStatus(featureId);

  const runningStage = ["domain", "uiux", "coder"].find((stage) => isProcessingNode(graphStatus, stage));
  const anyProcessing = Boolean(runningStage);
  const { data: artifacts, isLoading: artifactsLoading, error: artifactsError } = useFeatureArtifacts(featureId, {
    isProcessing: anyProcessing,
  });
  const { data: approvals } = useFeatureApprovals(featureId);
  const { data: events, isLoading: eventsLoading } = useFeatureEvents(featureId);

  // Same stuck-detection idiom the old FeatureDetailPage used -- tracks how long each auto-run
  // stage has been "processing" so a genuinely stuck run can be distinguished from a normal wait.
  const processingSinceRef = useRef({});
  useEffect(() => {
    if (!graphStatus) return;
    for (const stage of ["domain", "uiux", "coder"]) {
      if (isProcessingNode(graphStatus, stage)) {
        if (!processingSinceRef.current[stage]) processingSinceRef.current[stage] = Date.now();
      } else {
        processingSinceRef.current[stage] = null;
      }
    }
  }, [graphStatus]);

  const allArtifacts = artifacts || [];
  const allApprovals = approvals || [];
  const allEvents = events || [];

  const stageStatuses = {};
  for (const stage of GATED_STAGES) {
    stageStatuses[stage] = deriveStageStatus({
      stage,
      graphStatus,
      artifacts: allArtifacts,
      processingSince: processingSinceRef.current[stage],
      now: Date.now(),
    });
  }

  // Not memoized: allArtifacts/allApprovals/allEvents are fresh `|| []` fallbacks each render
  // (see above), so a dependency array here would never actually skip recomputation anyway --
  // buildAgentTimeline itself is cheap (a handful of array scans + one sort). Scoped to
  // selectedAgent -- see buildAgentTimeline's own docstring for why each agent must hold only
  // its own chat, not a feed shared across every agent.
  const timeline = buildAgentTimeline(selectedAgent, allArtifacts, allApprovals, allEvents);

  const [comment, setComment] = useState("");

  const runMutationsByStage = {};
  const reviseMutationsByStage = {};

  const versions = listGatingArtifactVersions(selectedAgent, allArtifacts);
  const hasOutput = versions.length > 0;

  // Requirement Agent: ONE continuous chat covering both the pre-SRS gap-filling conversation and
  // post-SRS revision activity -- previously two separate components ChatPanel hard-swapped
  // between the instant hasOutput flipped true, which read as "the chat disappeared" even after
  // an earlier fix (a collapsed history toggle) -- direct, repeated user feedback that this must
  // feel like one ChatGPT/Claude-style conversation, never a swap. `hasOutput` now only decides
  // which composer/banners are active INSIDE the single component, not which component renders.
  if (selectedAgent === "requirement") {
    return (
      <RequirementConversationChat
        featureId={featureId}
        feature={feature}
        runningStage={runningStage}
        selectedAgent={selectedAgent}
        selectAgent={selectAgent}
        hasOutput={hasOutput}
        timeline={timeline}
        allArtifacts={allArtifacts}
        onViewArtifact={viewArtifact}
        isLoadingTimeline={graphLoading || artifactsLoading || eventsLoading}
      />
    );
  }

  // Domain Agent: its own dedicated chat (both the pre-output "run" and post-output "revise"
  // sub-flows), live-streamed the same way Requirement Agent's chats are -- see
  // DomainAgentChat.jsx's own docstring for the direct user report this replaced.
  if (selectedAgent === "domain") {
    return (
      <DomainAgentChat
        featureId={featureId}
        feature={feature}
        runningStage={runningStage}
        selectedAgent={selectedAgent}
        selectAgent={selectAgent}
        timeline={timeline}
        allArtifacts={allArtifacts}
        onViewArtifact={viewArtifact}
        isLoadingTimeline={graphLoading || artifactsLoading || eventsLoading}
      />
    );
  }

  // Architecture Agent: its own dedicated chat (live plan-token streaming + a phase/elapsed-time
  // banner for the non-streamable diagram-generation tail, plus the "deep exploration mode"
  // escape hatch) -- see ArchitectureAgentChat.jsx's own docstring.
  if (selectedAgent === "architecture") {
    return (
      <ArchitectureAgentChat
        featureId={featureId}
        feature={feature}
        runningStage={runningStage}
        selectedAgent={selectedAgent}
        selectAgent={selectAgent}
        timeline={timeline}
        allArtifacts={allArtifacts}
        onViewArtifact={viewArtifact}
        isLoadingTimeline={graphLoading || artifactsLoading || eventsLoading}
      />
    );
  }

  // UI/UX Agent: its own dedicated chat (live ui_metadata_json streaming + a phase/elapsed-time
  // banner for the non-streamable tail -- component generation, page assembly/rendering), no
  // human approval required for any of its output anymore, and a real revise() capability where
  // there previously was none at all -- see UiuxAgentChat.jsx's own docstring for the full,
  // direct user request this replaces.
  if (selectedAgent === "uiux") {
    return (
      <UiuxAgentChat
        featureId={featureId}
        feature={feature}
        runningStage={runningStage}
        selectedAgent={selectedAgent}
        selectAgent={selectAgent}
        timeline={timeline}
        allArtifacts={allArtifacts}
        onViewArtifact={viewArtifact}
        isLoadingTimeline={graphLoading || artifactsLoading || eventsLoading}
      />
    );
  }

  // Coder Agent: its own dedicated chat (live streaming + phase/elapsed-time banner for the
  // non-streamable coding/verify tail, plus a verification-result banner and Stop-safety-net
  // caveat neither Domain nor Architecture need) -- see CoderAgentChat.jsx's own docstring.
  if (selectedAgent === "coder") {
    return (
      <CoderAgentChat
        featureId={featureId}
        feature={feature}
        runningStage={runningStage}
        selectedAgent={selectedAgent}
        selectAgent={selectAgent}
        timeline={timeline}
        allArtifacts={allArtifacts}
        onViewArtifact={viewArtifact}
        isLoadingTimeline={graphLoading || artifactsLoading || eventsLoading}
      />
    );
  }

  // Security Agent: its own dedicated chat -- direct user request, mirrors QA Agent's own chat
  // shape exactly (see SecurityAgentChat.jsx's own docstring). Runs a scan itself (via the SAME
  // shared useSecurityAgentFlowContext() mutation the Result panel's Run/Re-run button and the
  // Coder-approval auto-trigger already observe) rather than through runMutationsByStage/
  // reviseMutationsByStage (neither is registered for "security" -- there's no revise() shape,
  // just run() and chat()).
  if (selectedAgent === "security") {
    return (
      <SecurityAgentChat
        featureId={featureId}
        feature={feature}
        runningStage={runningStage}
        selectedAgent={selectedAgent}
        selectAgent={selectAgent}
        allArtifacts={allArtifacts}
      />
    );
  }

  // QA Agent: its own dedicated chat -- same shape as Security Agent's above, see
  // QaAgentChat.jsx's own docstring. Runs a QA scan itself (via its own empty-state button)
  // rather than through runMutationsByStage/reviseMutationsByStage (neither is registered for
  // "qa" -- there's no revise() shape, just run() and chat()).
  if (selectedAgent === "qa") {
    return (
      <QaAgentChat
        featureId={featureId}
        feature={feature}
        runningStage={runningStage}
        selectedAgent={selectedAgent}
        selectAgent={selectAgent}
        allArtifacts={allArtifacts}
      />
    );
  }

  const runMutation = runMutationsByStage[selectedAgent];
  const reviseMutation = reviseMutationsByStage[selectedAgent];
  const activeMutation = hasOutput ? reviseMutation : runMutation;
  const isAgentRunning = runningStage === selectedAgent || Boolean(activeMutation?.isPending);

  // Shared by the composer's Send and a chat bubble's inline "Save & Send" (see ChatBubble's own
  // docstring for why editing an old message resubmits rather than rewriting history) -- both
  // ultimately do the same thing: fire whichever mutation (run vs. revise) currently applies, with
  // whatever text the human settled on.
  async function submitAgentMessage(text) {
    const trimmed = text.trim();
    if (!trimmed || !activeMutation) return;

    if (hasOutput) {
      await activeMutation.mutateAsync({ revision_comment: trimmed, revised_by: user?.name || user?.email || "human_user" });
    } else {
      await activeMutation.mutateAsync({ human_comment: trimmed });
    }
  }

  async function handleSubmit(event) {
    event.preventDefault();
    if (!comment.trim()) return;
    await submitAgentMessage(comment);
    setComment("");
  }

  const status = stageStatuses[selectedAgent];
  const canCompose = hasOutput ? Boolean(reviseMutation) : Boolean(runMutation);

  return (
    <div className="h-full flex flex-col bg-white dark:bg-gray-900 rounded-lg shadow border border-gray-300 dark:border-gray-800 p-4">
      <ChatHeader feature={feature} runningStage={runningStage} />

      <ErrorBanner error={artifactsError} fallback="Failed to load artifacts." />

      <div className="flex-1 min-h-0 overflow-y-auto py-3 flex flex-col gap-3">
        {graphLoading || artifactsLoading || eventsLoading ? (
          <LoadingSpinner label="Loading activity..." />
        ) : timeline.length === 0 ? (
          <p className="text-sm text-gray-400 dark:text-gray-500 italic">No activity yet. Say something below to get started.</p>
        ) : (
          timeline.map((item, i) => (
            <ChatBubble
              key={i}
              item={item}
              allArtifacts={allArtifacts}
              onViewArtifact={viewArtifact}
              onEditSubmit={submitAgentMessage}
              isEditPending={Boolean(activeMutation?.isPending)}
            />
          ))
        )}

        {status === STATUS.PROCESSING && (
          <LoadingSpinner label={`${STAGE_LABELS[selectedAgent]} Agent is working...`} />
        )}

        {status === STATUS.POSSIBLY_STUCK && (
          <div className="bg-red-50 dark:bg-red-500/10 border border-red-200 dark:border-red-500/30 rounded-lg p-3">
            <p className="text-sm font-semibold text-red-800 dark:text-red-300">Taking longer than expected.</p>
            <p className="text-xs text-red-700 dark:text-red-400 mt-1">
              Still polling automatically -- if the underlying issue resolves, this will pick up the
              result without a refresh.
            </p>
          </div>
        )}
      </div>

      <div className="flex-shrink-0 pt-1">
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <ErrorBanner error={activeMutation?.error} fallback="Request failed." />

          {canCompose && SUGGESTION_CHIPS[selectedAgent] && (
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTION_CHIPS[selectedAgent].map((chip) => (
                <button
                  key={chip}
                  type="button"
                  onClick={() => setComment(chip)}
                  className="text-xs bg-gray-100 dark:bg-white/10 hover:bg-gray-200 dark:hover:bg-white/20 text-gray-700 dark:text-gray-300 rounded-full px-2.5 py-1"
                >
                  {chip}
                </button>
              ))}
            </div>
          )}

          <ChatComposerBox
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            disabled={!canCompose}
            pending={activeMutation?.isPending}
            onStop={() => activeMutation?.stop?.()}
            selectedAgent={selectedAgent}
            onSelectAgent={selectAgent}
            isAgentRunning={isAgentRunning}
            placeholder={
              !canCompose
                ? `${STAGE_LABELS[selectedAgent]} Agent can't be messaged directly right now`
                : hasOutput
                ? `Ask ${STAGE_LABELS[selectedAgent]} Agent for a change...`
                : `Tell ${STAGE_LABELS[selectedAgent]} Agent what to build...`
            }
          />
        </form>
      </div>
    </div>
  );
}
