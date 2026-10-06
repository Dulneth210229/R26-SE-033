import { apiClient } from "./client";

export async function listFeatures(projectId) {
  const { data } = await apiClient.get(`/projects/${projectId}/features`);
  return data;
}

export async function getFeature(featureId) {
  const { data } = await apiClient.get(`/features/${featureId}`);
  return data;
}

export async function createFeature(projectId, { feature_name, feature_description }) {
  const { data } = await apiClient.post(`/projects/${projectId}/features`, {
    feature_name,
    feature_description,
  });
  return data;
}

// Permanently deletes this feature and everything scoped to it (artifacts, approvals, stage
// events, requirement conversation, and its own git branch if one exists) -- never touches
// sibling features or the project itself.
export async function deleteFeature(featureId) {
  await apiClient.delete(`/features/${featureId}`);
}

export async function startPipeline(featureId) {
  const { data } = await apiClient.post(`/features/${featureId}/start`);
  return data;
}

export async function getGraphStatus(featureId) {
  const { data } = await apiClient.get(`/features/${featureId}/graph-status`);
  return data;
}

export async function listFeatureApprovals(featureId) {
  const { data } = await apiClient.get(`/features/${featureId}/approvals`);
  return data;
}

export async function listFeatureEvents(featureId) {
  const { data } = await apiClient.get(`/features/${featureId}/events`);
  return data;
}

// Pins which APPROVED version of one artifact_type (e.g. "srs") feeds the next pipeline stage --
// used when more than one version has been approved and the latest one isn't the one a human
// wants the next agent to use. Returns the updated feature (including the new
// active_artifact_selection map).
export async function setActiveArtifactSelection(featureId, { artifact_type, artifact_id }) {
  const { data } = await apiClient.put(`/features/${featureId}/artifacts/active-selection`, {
    artifact_type,
    artifact_id,
  });
  return data;
}
