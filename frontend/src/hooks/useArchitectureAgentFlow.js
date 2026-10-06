import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { reviseArchitectureStream, runArchitecture, runArchitectureStream } from "../api/agents";

// Architecture Agent's live, token-by-token run/revise (ChatGPT/Claude-style) -- mirrors
// useDomainAgentFlow.js exactly (same NDJSON-over-fetch mechanism, same AbortController-per-call
// "stop generating" pattern, same awaited-onSuccess fix for the "reply disappears instantly"
// race -- see that hook's own comment for the full story, not repeated here). One addition:
// Architecture Agent's stream also emits {"type": "phase", phase, label} events for the
// non-streamable tail (use case model, diagram generation, PlantUML rendering) that follows the
// plan text -- tracked here as run/revisionPhase (+ a start timestamp for an elapsed-time
// display) so the UI can show real progress instead of a bare spinner once tokens stop arriving.
export function useArchitectureAgentFlow(featureId) {
  const queryClient = useQueryClient();

  const [runStreamedText, setRunStreamedText] = useState("");
  const [runStreamStarted, setRunStreamStarted] = useState(false);
  const [runPhase, setRunPhase] = useState(null);
  const [runPhaseStartedAt, setRunPhaseStartedAt] = useState(null);
  const [runStreamError, setRunStreamError] = useState(null);

  const [revisionStreamedText, setRevisionStreamedText] = useState("");
  const [revisionStreamStarted, setRevisionStreamStarted] = useState(false);
  const [revisionPhase, setRevisionPhase] = useState(null);
  const [revisionPhaseStartedAt, setRevisionPhaseStartedAt] = useState(null);
  const [revisionStreamError, setRevisionStreamError] = useState(null);

  const runAbortRef = useRef(null);
  const reviseAbortRef = useRef(null);

  // Awaited, same reasoning as DomainAgentFlow's own invalidateAfterCompletion -- MUST be awaited
  // or the live bubble/view disappears a beat before the freshly-refetched persisted one exists
  // to replace it.
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
      return runArchitectureStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setRunStreamStarted(true);
            setRunStreamedText((current) => current + event.text);
          } else if (event.type === "phase") {
            setRunPhase({ phase: event.phase, label: event.label });
            setRunPhaseStartedAt(Date.now());
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
    setRunPhase(null);
    setRunPhaseStartedAt(null);
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
      return reviseArchitectureStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setRevisionStreamStarted(true);
            setRevisionStreamedText((current) => current + event.text);
          } else if (event.type === "phase") {
            setRevisionPhase({ phase: event.phase, label: event.label });
            setRevisionPhaseStartedAt(Date.now());
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
    setRevisionPhase(null);
    setRevisionPhaseStartedAt(null);
    setRevisionStreamError(null);
    return reviseStream.mutateAsync(payload);
  }

  function stopReviseStream() {
    reviseAbortRef.current?.abort();
  }

  // The non-streaming "deep exploration mode" path (ArchitectureRunForm), a real, separate
  // backend call (POST /architecture/run, the full agentic tool-calling exploration tier) from
  // the streaming runStream above (POST /architecture/run/stream, which deliberately skips that
  // tier for speed -- see ArchitectureAgent.run_stream's own docstring). Kept here, not
  // instantiated inside ArchitectureRunForm itself, for the exact reason UI/UX Agent's own
  // duplicate-mutation-instance bug was fixed (see UiuxAgentFlowContext.jsx): two independent
  // useMutation() instances for the same real action can't see each other's pending state, which
  // is precisely what let a human fire both this plain run AND the streaming run for one feature's
  // very first Architecture Agent run, producing two artifact versions with identical content.
  // Sharing one instance here means every trigger surface (this form, the chat's own quick-action
  // button/composer, and ResultTab's approve-and-auto-continue) can all check the SAME isPending.
  const plainRunAbortRef = useRef(null);
  const plainRunMutation = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      plainRunAbortRef.current = controller;
      return runArchitecture(featureId, payload, controller.signal);
    },
    onSuccess: invalidateAfterCompletion,
  });

  function handlePlainRun(payload) {
    return plainRunMutation.mutateAsync(payload);
  }

  function stopPlainRun() {
    plainRunAbortRef.current?.abort();
  }

  return {
    runStream,
    handleRunStream,
    stopRunStream,
    runStreamedText,
    runStreamStarted,
    runPhase,
    runPhaseStartedAt,
    runStreamError,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
    revisionPhase,
    revisionPhaseStartedAt,
    revisionStreamError,
    plainRunMutation,
    handlePlainRun,
    stopPlainRun,
  };
}
