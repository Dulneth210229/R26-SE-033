import { apiClient } from "./client";

const base = (featureId) => `/features/${featureId}/preview`;

// Live, Cursor-style preview of the Coder Agent's generated Next.js app --
// explicit Start/Stop, never automatic. Status is polled (see
// useAgentMutations.js's usePreviewStatus) so a page refresh recovers
// "already running" state, since the backend's registry is in-memory only.
export async function startPreview(featureId) {
  const { data } = await apiClient.post(`${base(featureId)}/start`);
  return data;
}

export async function getPreviewStatus(featureId) {
  const { data } = await apiClient.get(`${base(featureId)}/status`);
  return data;
}

export async function stopPreview(featureId) {
  const { data } = await apiClient.post(`${base(featureId)}/stop`);
  return data;
}
