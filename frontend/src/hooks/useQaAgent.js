import { useMutation, useQueryClient } from "@tanstack/react-query";
import { runQa } from "../api/agents";

// QA Agent has no chat/revision flow tied to running it (see MANUAL_RUN_STAGES in
// pipelineStages.js) -- just a direct re-run trigger, mirrors useSecurityAgent.js's
// useRunSecurityAgent exactly (plain useMutation, not a streaming flow -- run is several real
// LLM calls plus a real sandboxed test execution, not one continuous reply to watch live).
export function useRunQaAgent(featureId) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload) => runQa(featureId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] });
      queryClient.invalidateQueries({ queryKey: ["feature", featureId] });
      queryClient.invalidateQueries({ queryKey: ["events", featureId] });
      queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] });
    },
  });
}
