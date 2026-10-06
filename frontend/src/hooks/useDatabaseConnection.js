import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteDatabaseConnection, getDatabaseConnection, saveDatabaseConnection } from "../api/databaseConnection";

// Mirrors useKnowledgeDocuments.js's shape, minus its processing-state refetchInterval polling --
// a connection-string save/clear is instant, there's no async state to poll for here.
export function useDatabaseConnection(projectId, options = {}) {
  return useQuery({
    queryKey: ["databaseConnection", projectId],
    queryFn: () => getDatabaseConnection(projectId),
    enabled: Boolean(projectId),
    ...options,
  });
}

export function useSaveDatabaseConnection(projectId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (mongodbUri) => saveDatabaseConnection(projectId, mongodbUri),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["databaseConnection", projectId] });
    },
  });
}

export function useDeleteDatabaseConnection(projectId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => deleteDatabaseConnection(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["databaseConnection", projectId] });
    },
  });
}
