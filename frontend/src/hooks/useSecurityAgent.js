import { useMutation, useQueryClient } from "@tanstack/react-query";
import { runSecurity, runSecurityDeepScan } from "../api/agents";

const SECURITY_INVALIDATION_KEYS = (featureId) => [
  ["artifacts", featureId],
  ["feature", featureId],
  ["events", featureId],
  ["graphStatus", featureId],
];

// Security Agent has no revision flow (see REVISABLE_STAGES in pipelineStages.js -- re-running
// IS the whole operation) -- just a direct re-run trigger, so a plain useMutation is enough here,
// unlike the streaming useXAgentFlow hooks the other agents use for a real run/revise. Its real
// chat (a genuinely different, separate concern -- discussing an already-generated report, not
// producing one) has its own dedicated streaming hook, useSecurityChatFlow.js.
export function useRunSecurityAgent(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload) => runSecurity(featureId, payload),
    // Awaited, not fire-and-forget -- mutateAsync()/isPending only resolve once onSuccess itself
    // resolves, so an unawaited Promise.all here would let the mutation settle (and any
    // "generating" view built on isPending disappear) before the freshly invalidated queries have
    // actually refetched, producing a real empty-frame gap. Same bug class already found and
    // fixed for Domain/Requirement/QA chat elsewhere in this codebase.
    onSuccess: async () => {
      await Promise.all(
        SECURITY_INVALIDATION_KEYS(featureId).map((queryKey) => queryClient.invalidateQueries({ queryKey }))
      );
    },
  });
}

// A separate mutation from useRunSecurityAgent above -- triggers the AI-model deep-code-read scan
// (a genuinely new source-reading layer, distinct from the standard scan's summary-only LLM
// review) instead of a standard scan. Same awaited-invalidation shape for the same reason.
export function useRunSecurityAgentDeepScan(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload) => runSecurityDeepScan(featureId, payload),
    onSuccess: async () => {
      await Promise.all(
        SECURITY_INVALIDATION_KEYS(featureId).map((queryKey) => queryClient.invalidateQueries({ queryKey }))
      );
    },
  });
}
