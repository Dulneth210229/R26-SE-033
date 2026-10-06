import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteArtifact, getArtifactContent, listFeatureArtifacts } from "../api/artifacts";

const FAST_POLL_MS = 4_000;
const SLOW_POLL_MS = 15_000;

export function useFeatureArtifacts(featureId, { isProcessing = false } = {}) {
  return useQuery({
    queryKey: ["artifacts", featureId],
    queryFn: () => listFeatureArtifacts(featureId),
    enabled: Boolean(featureId),
    staleTime: 5_000,
    refetchInterval: isProcessing ? FAST_POLL_MS : SLOW_POLL_MS,
    refetchOnWindowFocus: true,
  });
}

export function useDeleteArtifact(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (artifactId) => deleteArtifact(artifactId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] });
    },
  });
}

export function useArtifactContent(artifactId) {
  return useQuery({
    queryKey: ["artifactContent", artifactId],
    queryFn: () => getArtifactContent(artifactId),
    enabled: Boolean(artifactId),
    // An artifact's file content never changes once created -- new versions get new IDs.
    staleTime: Infinity,
  });
}
