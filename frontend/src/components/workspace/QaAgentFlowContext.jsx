import { createContext, useContext } from "react";
import { useRunQaAgent } from "../../hooks/useQaAgent";
import { useQaRunStream } from "../../hooks/useQaRunStream";

const QaAgentFlowContext = createContext(null);

// Mirrors SecurityAgentFlowContext.jsx's own reasoning, at the smallest scale that reasoning
// needs: QaReportView (the stage's own Run/Re-run QA Scan button), QaAgentChat (its own
// empty-state "Run QA Scan" action), and ResultTab's "Continue to QA Agent" button (on the
// Security stage) all need to observe the SAME run flow -- three independent instances would each
// hold their own separate pending/progress state, so a run started from one surface would show no
// visible progress once the human switches over to another. `/qa/run` now has a real streaming
// sibling (direct user request, mirrors Security Agent's own live-progress deep-scan UX) --
// `qaRunFlow` (useQaRunStream) is the ONE surface all three consumers use to actually trigger and
// observe a run; `runQa` (the plain mutation) is kept here too only for completeness/back-compat,
// not used by any of the three UI trigger points anymore.
export function QaAgentFlowProvider({ featureId, children }) {
  const runQa = useRunQaAgent(featureId);
  const qaRunFlow = useQaRunStream(featureId);
  return <QaAgentFlowContext.Provider value={{ runQa, qaRunFlow }}>{children}</QaAgentFlowContext.Provider>;
}

export function useQaAgentFlowContext() {
  const ctx = useContext(QaAgentFlowContext);
  if (!ctx) {
    throw new Error("useQaAgentFlowContext must be used within a QaAgentFlowProvider");
  }
  return ctx;
}
