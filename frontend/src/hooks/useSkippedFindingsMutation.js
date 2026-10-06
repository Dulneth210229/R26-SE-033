import { useMutation, useQueryClient } from "@tanstack/react-query";
import { setFindingSkipped } from "../api/securityFindings";

// Mirrors useApprovalMutation's exact shape (async onSuccess + awaited invalidateQueries -- see
// that hook's own comment for why an unawaited Promise.all is a real, repeatedly-reintroduced bug
// class in this codebase). Only invalidates ["artifacts", featureId] -- NOT artifactContent --
// since skipped_finding_ids lives on the artifact record's metadata, never inside content_json
// (see artifact_service.set_finding_skipped's own docstring).
export function useSetFindingSkippedMutation(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ artifactId, finding_id, skipped }) => setFindingSkipped(artifactId, { finding_id, skipped }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] });
    },
  });
}
