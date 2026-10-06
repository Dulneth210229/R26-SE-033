import ArtifactRow from "./ArtifactRow";

export default function ArtifactList({
  artifacts,
  onView,
  gatingArtifactType,
  reviseMutation,
  featureId,
  activeArtifactType,
  activeArtifactId,
  onSetActive,
  onApproveClick,
}) {
  if (artifacts.length === 0) {
    return null;
  }

  const sorted = [...artifacts].sort((a, b) => {
    if (a.artifact_type !== b.artifact_type) {
      return a.artifact_type.localeCompare(b.artifact_type);
    }
    return b.version - a.version;
  });

  return (
    <div className="flex flex-col gap-2 mt-3">
      {sorted.map((artifact) => {
        const isGatingType = artifact.artifact_type === gatingArtifactType;
        // Every pending/rejected version gets its own inline Approve/Reject/Request-Revision --
        // no row is ever suppressed in favor of "the" gating artifact anymore. A real reported
        // bug (twice): first, only the single highest-version row had any controls at all
        // (fixed by making status/gating resolution version-AND-status-aware); then, even after
        // that fix, only ONE row (whichever the resolver called "operative") ever showed inline
        // buttons, so a human looking at [v1: pending, v2: rejected, v3: pending] still saw only
        // v1 as approvable and concluded v3 couldn't be selected at all. Every row now shows its
        // own controls, full stop -- consistent regardless of version number.
        //
        // Once ANY version of this artifact_type is approved, every OTHER version's Approve
        // button is disabled (not removed -- Reject/Request Revision stay available, e.g. to
        // formally clear out an old unused version) rather than silently still being clickable,
        // per direct user request: switching which version is approved is still possible, just
        // requires explicitly rejecting the current approval first, not a stray click on a
        // different row's Approve button.
        const approvedSibling = artifacts.find(
          (a) => a.artifact_type === artifact.artifact_type && a.approval_status === "approved" && a.artifact_id !== artifact.artifact_id
        );

        return (
          <ArtifactRow
            key={artifact.artifact_id}
            artifact={artifact}
            onView={onView}
            reviseMutation={isGatingType ? reviseMutation : null}
            featureId={featureId}
            onApproveClick={onApproveClick}
            approveLocked={Boolean(approvedSibling)}
            isActiveSelection={Boolean(activeArtifactType) && artifact.artifact_type === activeArtifactType && artifact.artifact_id === activeArtifactId}
            showActiveSelector={Boolean(activeArtifactType) && artifact.artifact_type === activeArtifactType}
            onSetActive={onSetActive}
          />
        );
      })}
    </div>
  );
}
