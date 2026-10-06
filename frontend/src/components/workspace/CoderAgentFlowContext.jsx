import { createContext, useContext } from "react";
import { useCoderAgentFlow } from "../../hooks/useCoderAgentFlow";

const CoderAgentFlowContext = createContext(null);

// Mirrors DomainAgentFlowContext.jsx/ArchitectureAgentFlowContext.jsx exactly, for the same
// reason: CoderAgentChat (the chat feed) and ResultTab (the live code-plan document view) both
// need to observe the SAME in-flight stream -- two independent useCoderAgentFlow() calls would
// each hold their own separate mutation state, so the Result panel would never see a stream the
// chat panel started.
export function CoderAgentFlowProvider({ featureId, children }) {
  const flow = useCoderAgentFlow(featureId);
  return <CoderAgentFlowContext.Provider value={flow}>{children}</CoderAgentFlowContext.Provider>;
}

export function useCoderAgentFlowContext() {
  const ctx = useContext(CoderAgentFlowContext);
  if (!ctx) {
    throw new Error("useCoderAgentFlowContext must be used within a CoderAgentFlowProvider");
  }
  return ctx;
}
