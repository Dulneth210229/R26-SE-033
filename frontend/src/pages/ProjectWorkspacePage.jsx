import { useNavigate, useParams } from "react-router-dom";
import { useFeatures } from "../hooks/useFeatures";
import {
  WorkspaceSelectionProvider,
  useWorkspaceSelection,
} from "../components/workspace/WorkspaceSelectionContext";
import ResizableWorkspace from "../components/workspace/ResizableWorkspace";
import FeatureListPanel from "../components/workspace/FeatureListPanel";
import EmptyChatPanel from "../components/workspace/EmptyChatPanel";
import EmptyOutputPanel from "../components/workspace/EmptyOutputPanel";
import { RequirementConversationFlowProvider } from "../components/workspace/RequirementConversationFlowContext";
import { DomainAgentFlowProvider } from "../components/workspace/DomainAgentFlowContext";
import { ArchitectureAgentFlowProvider } from "../components/workspace/ArchitectureAgentFlowContext";
import { UiuxAgentFlowProvider } from "../components/workspace/UiuxAgentFlowContext";
import { CoderAgentFlowProvider } from "../components/workspace/CoderAgentFlowContext";
import { SecurityAgentFlowProvider } from "../components/workspace/SecurityAgentFlowContext";
import { QaAgentFlowProvider } from "../components/workspace/QaAgentFlowContext";
import ChatPanel from "../components/chat/ChatPanel";
import OutputPanel from "../components/output/OutputPanel";
import ArtifactViewerModal from "../components/artifacts/ArtifactViewerModal";
import LoadingSpinner from "../components/common/LoadingSpinner";

function WorkspaceBody({ projectId }) {
  const { selectedFeatureId, viewingArtifact, viewArtifact } = useWorkspaceSelection();

  return (
    // Wraps both the chat and output panels (regardless of which agent is currently selected) so
    // the Requirement Agent's conversation/generation state is shared between them -- see
    // RequirementConversationFlowContext for why this can't just be two separate hook calls.
    // Cheap when irrelevant: the underlying query is a single disabled-when-no-feature GET.
    <RequirementConversationFlowProvider featureId={selectedFeatureId}>
      <DomainAgentFlowProvider featureId={selectedFeatureId}>
        <ArchitectureAgentFlowProvider featureId={selectedFeatureId}>
          <UiuxAgentFlowProvider featureId={selectedFeatureId}>
            <CoderAgentFlowProvider featureId={selectedFeatureId}>
              <SecurityAgentFlowProvider featureId={selectedFeatureId}>
                <QaAgentFlowProvider featureId={selectedFeatureId}>
                  <div className="h-full">
                    <ResizableWorkspace
                      left={<FeatureListPanel projectId={projectId} />}
                      middle={
                        selectedFeatureId ? (
                          <ChatPanel featureId={selectedFeatureId} />
                        ) : (
                          <EmptyChatPanel projectId={projectId} />
                        )
                      }
                      right={selectedFeatureId ? <OutputPanel featureId={selectedFeatureId} /> : <EmptyOutputPanel />}
                    />
                    <ArtifactViewerModal artifact={viewingArtifact} onClose={() => viewArtifact(null)} />
                  </div>
                </QaAgentFlowProvider>
              </SecurityAgentFlowProvider>
            </CoderAgentFlowProvider>
          </UiuxAgentFlowProvider>
        </ArchitectureAgentFlowProvider>
      </DomainAgentFlowProvider>
    </RequirementConversationFlowProvider>
  );
}

// Replaces the old ProjectDetailPage -> FeatureDetailPage drill-down with one Cursor-style
// workspace: pick a feature in the left panel, talk to its agents in the middle panel, see their
// output in the right panel -- all without a page navigation. featureId in the URL just seeds
// which feature is initially selected (and keeps the URL bookmarkable/shareable); switching
// features afterward updates the URL via `replace` without unmounting this page.
export default function ProjectWorkspacePage() {
  const { projectId, featureId } = useParams();
  const navigate = useNavigate();
  const { data: features, isLoading } = useFeatures(projectId);

  function handleSelectFeature(id) {
    navigate(`/projects/${projectId}/features/${id}`, { replace: true });
  }

  if (isLoading) {
    return <LoadingSpinner label="Loading project..." />;
  }

  // No featureId in the URL yet (a fresh project open, e.g. clicking a project card, which
  // always navigates to the bare /projects/:projectId) -- default to whichever feature was most
  // recently worked on (highest updated_at, now a real, reliably-bumped signal -- see
  // stage_event_service.record()/approval_service.py's own updated_at writes), not just array
  // index 0. Direct user request. A plain reduce, not a new query -- `features` is already
  // fetched; ties (e.g. an all-fresh project where nothing has ever been touched) resolve to
  // whichever comes first, matching the previous behavior for that case exactly.
  const mostRecentlyActiveFeature =
    features && features.length > 0
      ? features.reduce((latest, current) =>
          new Date(current.updated_at) > new Date(latest.updated_at) ? current : latest
        )
      : null;
  const effectiveFeatureId = featureId || mostRecentlyActiveFeature?.feature_id || null;

  return (
    <WorkspaceSelectionProvider featureId={effectiveFeatureId} onSelectFeature={handleSelectFeature}>
      <WorkspaceBody projectId={projectId} />
    </WorkspaceSelectionProvider>
  );
}
