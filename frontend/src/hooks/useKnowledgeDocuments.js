import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteKnowledgeDocument, listKnowledgeDocuments, uploadKnowledgeDocument } from "../api/knowledge";

// Polls while any document is still "processing" (extraction/embedding just kicked off) so the
// panel picks up "ready"/"failed" without a manual refresh -- same conditional-refetch idiom as
// this app's other polling hooks (e.g. useFeatureArtifacts).
function isAnyDocumentProcessing(documents) {
  return Boolean(documents?.some((doc) => doc.status === "processing"));
}

export function useKnowledgeDocuments(projectId, options = {}) {
  return useQuery({
    queryKey: ["knowledgeDocuments", projectId],
    queryFn: () => listKnowledgeDocuments(projectId),
    enabled: Boolean(projectId),
    refetchInterval: (query) => (isAnyDocumentProcessing(query.state.data) ? 3_000 : false),
    ...options,
  });
}

export function useUploadKnowledgeDocument(projectId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (file) => uploadKnowledgeDocument(projectId, file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledgeDocuments", projectId] });
    },
  });
}

export function useDeleteKnowledgeDocument(projectId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (documentId) => deleteKnowledgeDocument(projectId, documentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["knowledgeDocuments", projectId] });
    },
  });
}
