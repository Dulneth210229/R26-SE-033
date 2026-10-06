import { apiClient, artifactContentUrl, artifactDownloadUrl } from "./client";

export async function listFeatureArtifacts(featureId) {
  const { data } = await apiClient.get(`/features/${featureId}/artifacts`);
  return data;
}

export async function getArtifactContent(artifactId) {
  const { data } = await apiClient.get(`/artifacts/${artifactId}/content`);
  return data;
}

// Only unapproved (pending/rejected/revision_requested) artifacts can be deleted -- the backend
// rejects (400) an attempt to delete an approved one.
export async function deleteArtifact(artifactId) {
  await apiClient.delete(`/artifacts/${artifactId}`);
}

export { artifactContentUrl, artifactDownloadUrl };
