import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef } from "react";
import {
  reviseArchitecture,
  reviseCoder,
  reviseDomain,
  runArchitecture,
  runCoder,
  runDomain,
  runRequirement,
  runUiux,
} from "../api/agents";

// A fresh AbortController per call, stashed in a ref so a "Stop" button (rendered by whatever
// composer triggered this mutation) can reach back and cancel the in-flight request -- direct
// user request for a ChatGPT/Claude-style "pause" control, applied uniformly to every agent (see
// this hook's docstring in the calling components for the honest caveat: these four agents run as
// one plain awaited call, not a token stream, so "stop" here means "stop waiting on it," not a
// guaranteed mid-generation halt the way it is for Requirement Agent's real streaming endpoints).
function useAgentMutation(featureId, mutationFn) {
  const queryClient = useQueryClient();
  const abortRef = useRef(null);

  const mutation = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      abortRef.current = controller;
      return mutationFn(payload, controller.signal);
    },
    // Unlike Requirement Agent's streaming conversation (where the whole turn is only persisted
    // atomically by a final "done" event -- see useRequirementConversationFlow.js), these four
    // agents' routes record the human's comment as a stage_event SYNCHRONOUSLY, before the agent
    // call even starts (confirmed by reading agents.py's run/revise handlers) -- so even a stopped
    // request has almost always already durably saved it server-side by the time a human can
    // click Stop. Always invalidate (not skipped on abort) so that real "ask" bubble reliably
    // shows up in the chat feed either way.
    //
    // Awaited: mutateAsync/mutate only settles (isPending -> false) once onSuccess resolves --
    // if this returned before the invalidated queries actually refetched, the pending
    // spinner/bubble would disappear a beat before the real persisted response existed in the
    // freshly-refetched timeline to replace it. Same real, reported race as
    // DomainAgentFlow's own invalidateAfterCompletion (see its comment for the full story).
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["feature", featureId] }),
        queryClient.invalidateQueries({ queryKey: ["events", featureId] }),
      ]);
    },
  });

  return { ...mutation, stop: () => abortRef.current?.abort() };
}

export function useRunRequirement(featureId) {
  return useAgentMutation(featureId, (payload, signal) => runRequirement(featureId, payload, signal));
}

export function useRunDomain(featureId) {
  return useAgentMutation(featureId, (payload, signal) => runDomain(featureId, payload, signal));
}

export function useReviseDomain(featureId) {
  return useAgentMutation(featureId, (payload, signal) => reviseDomain(featureId, payload, signal));
}

export function useRunArchitecture(featureId) {
  return useAgentMutation(featureId, (payload, signal) => runArchitecture(featureId, payload, signal));
}

export function useReviseArchitecture(featureId) {
  return useAgentMutation(featureId, (payload, signal) => reviseArchitecture(featureId, payload, signal));
}

export function useRunUiux(featureId) {
  return useAgentMutation(featureId, (payload, signal) => runUiux(featureId, payload, signal));
}

export function useRunCoder(featureId) {
  return useAgentMutation(featureId, (payload, signal) => runCoder(featureId, payload, signal));
}

export function useReviseCoder(featureId) {
  return useAgentMutation(featureId, (payload, signal) => reviseCoder(featureId, payload, signal));
}
