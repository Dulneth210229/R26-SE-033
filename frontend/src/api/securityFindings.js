import { apiClient } from "./client";

export async function setFindingSkipped(artifactId, { finding_id, skipped }) {
  const { data } = await apiClient.put(`/artifacts/${artifactId}/skipped-findings`, {
    finding_id,
    skipped,
  });
  return data;
}
