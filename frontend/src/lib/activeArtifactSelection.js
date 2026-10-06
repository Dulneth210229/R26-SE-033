// Mirrors artifact_service.get_selected_or_latest_approved_artifact's exact logic on the
// frontend, so both the "Using SRS vN" indicator (OutputPanel) and the per-row radio button
// (ArtifactList/ArtifactRow) agree on which version is currently effective without a second
// round trip to the backend -- `artifacts` is whatever's already loaded (useFeatureArtifacts),
// `activeSelection` is feature.active_artifact_selection ({artifact_type: artifact_id}).
export function getEffectiveActiveArtifact(artifacts, activeSelection, artifactType, artifactFormat = "json") {
  const approvedOfType = artifacts.filter(
    (a) => a.artifact_type === artifactType && a.artifact_format === artifactFormat && a.approval_status === "approved"
  );

  if (approvedOfType.length === 0) return null;

  const selectedId = activeSelection?.[artifactType];
  const selected = selectedId && approvedOfType.find((a) => a.artifact_id === selectedId);
  if (selected) return selected;

  return approvedOfType.reduce((latest, a) => (a.version > latest.version ? a : latest), approvedOfType[0]);
}
