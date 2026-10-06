import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { reviseUiuxStream, runUiuxStream } from "../api/agents";

// UI/UX Agent's live, token-by-token run/revise (ChatGPT/Claude-style) -- mirrors
// useArchitectureAgentFlow.js exactly (same NDJSON-over-fetch mechanism, same
// AbortController-per-call "stop generating" pattern, same awaited-onSuccess fix for the "reply
// disappears instantly" race -- see that hook's own comment for the full story, not repeated
// here). Like Architecture Agent, UI/UX Agent's stream also emits {"type": "phase", phase, label}
// events for the non-streamable tail (component generation, page assembly/rendering) that follows
// ui_metadata_json itself -- tracked here as run/revisionPhase (+ a start timestamp for an
// elapsed-time display) so the UI can show real progress instead of a bare spinner once tokens
// stop arriving.
export function useUiuxAgentFlow(featureId) {
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

  // Awaited, same reasoning as ArchitectureAgentFlow/DomainAgentFlow's own
  // invalidateAfterCompletion -- MUST be awaited or the live bubble/view disappears a beat before
  // the freshly-refetched persisted one exists to replace it.
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
      return runUiuxStream(
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
      return reviseUiuxStream(
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
  };
}
