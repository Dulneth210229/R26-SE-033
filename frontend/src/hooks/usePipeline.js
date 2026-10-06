import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { getGraphStatus, listFeatureApprovals, listFeatureEvents, startPipeline } from "../api/features";

const FAST_POLL_MS = 4_000;
const SLOW_POLL_MS = 15_000;

function isLikelyProcessing(graphStatus) {
  if (!graphStatus?.next?.length) {
    return false;
  }

  // Any *_node entry (as opposed to an approve_* gate) means the graph is actively running
  // an auto-triggered stage (domain/uiux/coder) rather than waiting on a human decision.
  return graphStatus.next.some((node) => node.endsWith("_node"));
}

export function useGraphStatus(featureId) {
  return useQuery({
    queryKey: ["graphStatus", featureId],
    queryFn: () => getGraphStatus(featureId),
    enabled: Boolean(featureId),
    staleTime: 5_000,
    refetchInterval: (query) => (isLikelyProcessing(query.state.data) ? FAST_POLL_MS : SLOW_POLL_MS),
    refetchOnWindowFocus: true,
  });
}

export function useFeatureApprovals(featureId) {
  return useQuery({
    queryKey: ["approvals", featureId],
    queryFn: () => listFeatureApprovals(featureId),
    enabled: Boolean(featureId),
  });
}

export function useFeatureEvents(featureId) {
  return useQuery({
    queryKey: ["events", featureId],
    queryFn: () => listFeatureEvents(featureId),
    enabled: Boolean(featureId),
  });
}

export function useStartPipeline(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => startPipeline(featureId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] });
      queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] });
    },
  });
}
