import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { reviseCoderStream, runCoderStream } from "../api/agents";

// Coder Agent's live, token-by-token run/revise (ChatGPT/Claude-style) -- mirrors
// useArchitectureAgentFlow.js exactly (same NDJSON-over-fetch mechanism, same
// AbortController-per-call "stop generating" pattern, same awaited-onSuccess fix for the "reply
// disappears instantly" race -- see that hook's own comment for the full story, not repeated
// here), plus run/revisionPhase (+ a start timestamp for an elapsed-time display) for the
// non-streamable coding/verify tail. One addition Domain/Architecture's hooks don't have:
// run/revisionVerificationResult, set from the "done" event's verification_passed/status/message
// -- unlike Domain/Architecture's uniform "done, success" framing, a Coder Agent run can finish
// with verification failures, and the chat needs to show that honestly rather than a blanket
// success banner.
// Rolling activity log cap -- enough to feel "live" without the list growing unbounded during a
// long coding attempt (a real revision can call dozens of tools).
const MAX_TOOL_ACTIVITY_ENTRIES = 8;

export function useCoderAgentFlow(featureId) {
  const queryClient = useQueryClient();

  const [runStreamedText, setRunStreamedText] = useState("");
  const [runStreamStarted, setRunStreamStarted] = useState(false);
  const [runPhase, setRunPhase] = useState(null);
  const [runPhaseStartedAt, setRunPhaseStartedAt] = useState(null);
  const [runVerificationResult, setRunVerificationResult] = useState(null);
  const [runStreamError, setRunStreamError] = useState(null);
  const [runToolActivity, setRunToolActivity] = useState([]);

  const [revisionStreamedText, setRevisionStreamedText] = useState("");
  const [revisionStreamStarted, setRevisionStreamStarted] = useState(false);
  const [revisionPhase, setRevisionPhase] = useState(null);
  const [revisionPhaseStartedAt, setRevisionPhaseStartedAt] = useState(null);
  const [revisionVerificationResult, setRevisionVerificationResult] = useState(null);
  const [revisionStreamError, setRevisionStreamError] = useState(null);
  const [revisionToolActivity, setRevisionToolActivity] = useState([]);

  const runAbortRef = useRef(null);
  const reviseAbortRef = useRef(null);

  // Awaited, same reasoning as Domain/ArchitectureAgentFlow's own invalidateAfterCompletion --
  // MUST be awaited or the live bubble/view disappears a beat before the freshly-refetched
  // persisted one exists to replace it.
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
      return runCoderStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setRunStreamStarted(true);
            setRunStreamedText((current) => current + event.text);
          } else if (event.type === "phase") {
            setRunPhase({ phase: event.phase, label: event.label });
            setRunPhaseStartedAt(Date.now());
          } else if (event.type === "done") {
            setRunVerificationResult({
              verificationPassed: event.verification_passed,
              status: event.status,
              message: event.message,
            });
          } else if (event.type === "error") {
            // The backend route always converts an uncaught exception into a real
            // {"type": "error"} NDJSON line before the stream ends -- but streamNdjsonPost's own
            // promise still resolves normally for it (only a genuine network/HTTP failure rejects),
            // so without this branch a real backend crash was previously completely invisible: no
            // rejection for ErrorBanner's `activeStream.error` to catch, no result, nothing -- the
            // exact "the agent did nothing" symptom a real user reported.
            setRunStreamError(event.message);
          } else if (event.type === "tool_activity") {
            // Real, incremental "I can see it working" progress during the coding loop, which
            // (unlike token streaming) has no LLM output of its own to show -- one line per real
            // tool call/result as it happens, instead of a single static phase label sitting
            // unchanged for however long the whole attempt takes.
            setRunToolActivity((current) => [...current, event.label].slice(-MAX_TOOL_ACTIVITY_ENTRIES));
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
    setRunVerificationResult(null);
    setRunStreamError(null);
    setRunToolActivity([]);
    return runStream.mutateAsync(payload);
  }

  function stopRunStream() {
    runAbortRef.current?.abort();
  }

  const reviseStream = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      reviseAbortRef.current = controller;
      return reviseCoderStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "token") {
            setRevisionStreamStarted(true);
            setRevisionStreamedText((current) => current + event.text);
          } else if (event.type === "phase") {
            setRevisionPhase({ phase: event.phase, label: event.label });
            setRevisionPhaseStartedAt(Date.now());
          } else if (event.type === "done") {
            setRevisionVerificationResult({
              verificationPassed: event.verification_passed,
              status: event.status,
              message: event.message,
            });
          } else if (event.type === "error") {
            setRevisionStreamError(event.message);
          } else if (event.type === "tool_activity") {
            setRevisionToolActivity((current) =>
              [...current, event.label].slice(-MAX_TOOL_ACTIVITY_ENTRIES)
            );
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
    setRevisionVerificationResult(null);
    setRevisionStreamError(null);
    setRevisionToolActivity([]);
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
    runVerificationResult,
    runStreamError,
    runToolActivity,
    reviseStream,
    handleReviseStream,
    stopReviseStream,
    revisionStreamedText,
    revisionStreamStarted,
    revisionPhase,
    revisionPhaseStartedAt,
    revisionVerificationResult,
    revisionStreamError,
    revisionToolActivity,
  };
}
