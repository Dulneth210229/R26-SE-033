import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { reviseDomainStream, runDomainStream } from "../api/agents";

// Domain Agent's live, token-by-token run/revise (ChatGPT/Claude-style) -- mirrors
// useRequirementConversationFlow.js exactly (same NDJSON-over-fetch mechanism, same AbortController-
// per-call "stop generating" pattern). Direct user report: Domain Agent was the one agent chat
// left on the old blocking-wait experience (typed text stuck in the composer until the whole
// enrichment finished, no live output, no way to stop) after every one of those was already fixed
// for Requirement Agent. Shared via DomainAgentFlowContext the same way
// RequirementConversationFlowContext shares its flow hook -- ChatPanel's chat feed and ResultTab's
// live document view both need to observe the SAME in-flight stream.
export function useDomainAgentFlow(featureId) {
  const queryClient = useQueryClient();

  const [runStreamedText, setRunStreamedText] = useState("");
  const [runStreamStarted, setRunStreamStarted] = useState(false);
  const [runStreamError, setRunStreamError] = useState(null);
  const [revisionStreamedText, setRevisionStreamedText] = useState("");
  const [revisionStreamStarted, setRevisionStreamStarted] = useState(false);
  const [revisionStreamError, setRevisionStreamError] = useState(null);

  const runAbortRef = useRef(null);
  const reviseAbortRef = useRef(null);

  // Domain's stage_event is recorded synchronously by the backend route before the agent call
  // even starts (same as every other non-Requirement agent -- see useAgentMutations.js's own
  // comment), so unlike Requirement's streaming flows there's no "nothing was saved" case to
  // guard against -- always invalidate so a stopped-but-already-recorded "ask" bubble still shows
  // up, and so a genuinely completed run's new artifacts are picked up.
  //
  // MUST be awaited (and MUST be the mutation's onSuccess, not fired-and-forgotten inside it):
  // React Query's mutateAsync() only resolves once onSuccess itself resolves. DomainAgentChat's
  // submitDomainMessage clears the optimistic "You" bubble and the live streaming/reaction bubble
  // via that resolution (`call.finally(...)`, `activeStream.isPending` flipping to false) -- if
  // onSuccess returned before the invalidated queries had actually refetched, both live bubbles
  // would disappear a beat before the real persisted ones (from the freshly-refetched timeline)
  // existed to replace them, i.e. exactly the reported "the agent's reply disappears instantly"
  // bug. Real, reproduced bug, not a hypothetical -- invalidateQueries() alone only *schedules* a
  // refetch of active queries; its own returned promise is what actually waits for it to land.
  async function invalidateAfterCompletion() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] }),
      queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] }),
      queryClient.invalidateQueries({ queryKey: ["feature", featureId] }),
      queryClient.invalidateQueries({ queryKey: ["events", featureId] }),
    ]);
  }

  const runStream = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      runAbortRef.current = controller;
      return runDomainStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setRunStreamStarted(true);
            setRunStreamedText((current) => current + event.text);
          } else if (event.type === "error") {
            // The backend route always converts an uncaught exception into a real
            // {"type": "error"} NDJSON line before the stream ends -- but the streamed request's
            // own promise still resolves normally for it (only a genuine network/HTTP failure
            // rejects), so without this branch a real backend crash was completely invisible.
            setRunStreamError(event.message);
          }
        },
        controller.signal
      );
    },
    onSuccess: invalidateAfterCompletion,
  });

  function handleRunStream(payload) {
    setRunStreamedText("");
    setRunStreamStarted(false);
    setRunStreamError(null);
    return runStream.mutateAsync(payload);
  }

  function stopRunStream() {
    runAbortRef.current?.abort();
  }

  const reviseStream = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      reviseAbortRef.current = controller;
      return reviseDomainStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setRevisionStreamStarted(true);
            setRevisionStreamedText((current) => current + event.text);
          } else if (event.type === "error") {
            setRevisionStreamError(event.message);
          }
        },
        controller.signal
      );
    },
    onSuccess: invalidateAfterCompletion,
  });

  function handleReviseStream(payload) {
    setRevisionStreamedText("");
    setRevisionStreamStarted(false);
    setRevisionStreamError(null);
    return reviseStream.mutateAsync(payload);
  }

  function stopReviseStream() {
    reviseAbortRef.current?.abort();
  }

  return {
    runStream,
    handleRunStream,
    stopRunStream,
    runStreamedText,
    runStreamStarted,
    runStreamError,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
    revisionStreamError,
  };
}
