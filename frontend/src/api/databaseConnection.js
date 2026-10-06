import { apiClient } from "./client";

const base = (projectId) => `/projects/${projectId}/database-connection`;

// Per-project MongoDB connection string -- the standalone way to set/view/clear it, independent
// of any specific Coder Agent run. Never returns the raw connection string, only whether one is
// configured and a credential-redacted display value (see the backend's mask_mongodb_uri).
export async function getDatabaseConnection(projectId) {
  const { data } = await apiClient.get(base(projectId));
  return data;
}

export async function saveDatabaseConnection(projectId, mongodbUri) {
  const { data } = await apiClient.put(base(projectId), { mongodb_uri: mongodbUri });
  return data;
}

export async function deleteDatabaseConnection(projectId) {
  await apiClient.delete(base(projectId));
}
