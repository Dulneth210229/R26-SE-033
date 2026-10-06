import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  confirmRequirementConversation,
  getRequirementConversation,
  replyToRequirementConversationWithDocument,
  resetRequirementConversation,
  startRequirementConversation,
} from "../api/agents";

export function useRequirementConversation(featureId, options = {}) {
  return useQuery({
    queryKey: ["requirementConversation", featureId],
    queryFn: () => getRequirementConversation(featureId),
    enabled: Boolean(featureId),
    ...options,
  });
}

function useConversationMutation(featureId, mutationFn) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requirementConversation", featureId] });
    },
  });
}

export function useStartRequirementConversation(featureId) {
  return useConversationMutation(featureId, () => startRequirementConversation(featureId));
}

// Reply with an attached text/PDF/DOCX/MD document instead of (or alongside) typed text.
export function useReplyToRequirementConversationWithDocument(featureId) {
  return useConversationMutation(featureId, (payload) =>
    replyToRequirementConversationWithDocument(featureId, payload)
  );
}

export function useResetRequirementConversation(featureId) {
  return useConversationMutation(featureId, () => resetRequirementConversation(featureId));
}

// Confirming produces a real SRS artifact -- invalidate the same broader set of queries the
// existing run/revise mutations do (graph status, artifacts, feature, events), not just the
// conversation query, since this is the point where a normal Requirement Agent artifact appears.
export function useConfirmRequirementConversation(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload) => confirmRequirementConversation(featureId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["requirementConversation", featureId] });
      queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] });
      queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] });
      queryClient.invalidateQueries({ queryKey: ["feature", featureId] });
      queryClient.invalidateQueries({ queryKey: ["events", featureId] });
    },
  });
}
