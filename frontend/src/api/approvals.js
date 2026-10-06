import { apiClient } from "./client";

export async function submitApproval(artifactId, { status, reviewer_comment, approved_by }) {
  const { data } = await apiClient.post(`/artifacts/${artifactId}/approval`, {
    status,
    reviewer_comment,
    approved_by,
  });
  return data;
}

export async function revokeApproval(artifactId, { reviewer_comment, revoked_by } = {}) {
  const { data } = await apiClient.post(`/artifacts/${artifactId}/approval/revoke`, {
    reviewer_comment,
    revoked_by,
  });
  return data;
}
