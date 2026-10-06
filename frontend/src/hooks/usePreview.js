import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getPreviewStatus, startPreview, stopPreview } from "../api/preview";

// Polls while a preview is running/stale so a stopped-from-elsewhere (or
// auto-stopped-by-a-new-Coder-Agent-run) container's state is picked up
// without a manual refresh -- same conditional-refetch idiom as
// useKnowledgeDocuments' processing-status poll.
function shouldKeepPolling(status) {
  return status?.status === "running" || status?.status === "stale";
}

export function usePreviewStatus(featureId) {
  return useQuery({
    queryKey: ["previewStatus", featureId],
    queryFn: () => getPreviewStatus(featureId),
    enabled: Boolean(featureId),
    refetchInterval: (query) => (shouldKeepPolling(query.state.data) ? 5_000 : false),
  });
}

export function useStartPreview(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => startPreview(featureId),
    onSuccess: (data) => {
      queryClient.setQueryData(["previewStatus", featureId], data);
    },
  });
}

export function useStopPreview(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => stopPreview(featureId),
    onSuccess: () => {
      queryClient.setQueryData(["previewStatus", featureId], {
        status: "stopped",
        preview_url: null,
        started_at: null,
      });
    },
  });
}
