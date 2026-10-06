import { apiClient, API_BASE_URL } from "./client";

const base = (projectId) => `/projects/${projectId}/knowledge/documents`;

// Per-project domain knowledge documents (PDF/DOCX/TXT/MD), uploaded so Domain Agent can
// retrieve them via similarity search or have a specific one pinned by document_id when
// referenced with "/" in the chat composer.
export async function listKnowledgeDocuments(projectId) {
  const { data } = await apiClient.get(base(projectId));
  return data;
}

export async function uploadKnowledgeDocument(projectId, file) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await apiClient.post(base(projectId), formData);
  return data;
}

export async function deleteKnowledgeDocument(projectId, documentId) {
  await apiClient.delete(`${base(projectId)}/${documentId}`);
}

export function knowledgeDocumentDownloadUrl(projectId, documentId) {
  return `${API_BASE_URL}${base(projectId)}/${documentId}/download`;
}
