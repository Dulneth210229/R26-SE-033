import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFeature, deleteFeature, getFeature, listFeatures, setActiveArtifactSelection } from "../api/features";

export function useFeatures(projectId) {
  return useQuery({
    queryKey: ["features", projectId],
    queryFn: () => listFeatures(projectId),
    enabled: Boolean(projectId),
  });
}

export function useFeature(featureId) {
  return useQuery({
    queryKey: ["feature", featureId],
    queryFn: () => getFeature(featureId),
    enabled: Boolean(featureId),
  });
}

export function useCreateFeature(projectId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload) => createFeature(projectId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["features", projectId] });
    },
  });
}

export function useDeleteFeature(projectId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (featureId) => deleteFeature(featureId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["features", projectId] });
    },
  });
}

export function useSetActiveArtifactSelection(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload) => setActiveArtifactSelection(featureId, payload),
    onSuccess: (updatedFeature) => {
      queryClient.setQueryData(["feature", featureId], updatedFeature);
    },
  });
}
