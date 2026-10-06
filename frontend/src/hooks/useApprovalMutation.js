import { useMutation, useQueryClient } from "@tanstack/react-query";
import { revokeApproval, submitApproval } from "../api/approvals";

export function useApprovalMutation(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ artifactId, status, reviewer_comment, approved_by }) =>
      submitApproval(artifactId, { status, reviewer_comment, approved_by }),
    // Awaited, not fire-and-forget -- mutateAsync()/isPending only resolve once onSuccess itself
    // resolves, so an unawaited Promise.all here could let the mutation settle before the freshly
    // invalidated queries have actually refetched. Same bug class already found and fixed for
    // Domain/Requirement/QA/Security Agent elsewhere in this codebase.
    onSuccess: async () => {
      // Approval is what advances the graph -- all queries must be invalidated so the UI
      // reflects the (possibly automatic, e.g. Domain/UI-UX/Coder) next stage as soon as
      // it's observable, rather than waiting for the next poll tick. approvals feeds the
      // activity timeline (M4).
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["approvals", featureId] }),
      ]);
    },
  });
}

// Separate from useApprovalMutation -- a revoke's payload/endpoint shape differs (no `status`,
// just an optional comment) and it's a deliberately less-common action, not worth overloading the
// same mutationFn's branching logic for.
export function useRevokeApprovalMutation(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ artifactId, reviewer_comment, revoked_by }) =>
      revokeApproval(artifactId, { reviewer_comment, revoked_by }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["approvals", featureId] }),
      ]);
    },
  });
}
