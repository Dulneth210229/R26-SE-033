import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { runQaStream } from "../api/agents";

// Live, streamed QA run -- mirrors useSecurityDeepScanFlow.js exactly (same NDJSON-over-fetch
// mechanism, same AbortController-per-call "stop" pattern, same awaited-onSuccess fix for the
// "reply disappears instantly" race), except test generation is SEQUENTIAL (one real LLM call per
// discovered target, writing real files + sharing one Jest setup before execution) rather than
// concurrent batches, so there's no `inFlightBatches` here -- just `progress`
// ({completedCount, total, percent}) and `phaseLabel`, with the current target's own name already
// baked into the label text by the backend (see agent.py's run_stream `generation_progress`
// events).
//
// Direct user decision (Plan-agent-caught integration risk): this is the ONE run-triggering
// surface all 3 real consumers (QaReportView's Run/Re-run buttons, ResultTab's Security-approval
// auto-continue-to-QA, QaAgentChat's empty-state trigger + its isAgentRunning gate) now share via
// QaAgentFlowContext -- building this standalone and wiring it into only one consumer would have
// silently split the UX (some surfaces showing live progress, others still blank-waiting).
export function useQaRunStream(featureId) {
  const queryClient = useQueryClient();

  const [progress, setProgress] = useState(null);
  const [phaseLabel, setPhaseLabel] = useState(null);
  const [runError, setRunError] = useState(null);

  const abortRef = useRef(null);

  async function invalidateAfterCompletion() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["artifacts", featureId] }),
      queryClient.invalidateQueries({ queryKey: ["feature", featureId] }),
      queryClient.invalidateQueries({ queryKey: ["events", featureId] }),
      queryClient.invalidateQueries({ queryKey: ["graphStatus", featureId] }),
    ]);
  }

  const runStream = useMutation({
    mutationFn: (payload) => {
      const controller = new AbortController();
      abortRef.current = controller;
      return runQaStream(
        featureId,
        payload,
        (event) => {
          if (event.type === "phase") {
            setPhaseLabel(event.label);
          } else if (event.type === "generation_progress") {
            setPhaseLabel(event.label);
            setProgress({
              completedCount: event.index,
              total: event.total,
              percent: event.total > 0 ? Math.round((event.index / event.total) * 100) : 0,
            });
          } else if (event.type === "error") {
            // The backend route always converts an uncaught exception into a real
            // {"type": "error"} NDJSON line before the stream ends -- but the streamed request's
            // own promise still resolves normally for it (only a genuine network/HTTP failure
            // rejects), so without this branch a real backend crash was completely invisible.
            setRunError(event.message);
          }
        },
        controller.signal
      );
    },
    onSuccess: invalidateAfterCompletion,
  });

  function handleRunStream(payload = {}) {
    setProgress(null);
    setPhaseLabel(null);
    setRunError(null);
    return runStream.mutateAsync(payload);
  }

  function stopRunStream() {
    abortRef.current?.abort();
  }

  return {
    runStream,
    handleRunStream,
    stopRunStream,
    progress,
    phaseLabel,
    runError,
  };
}
