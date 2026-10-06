import { createContext, useContext } from "react";
import { useArchitectureAgentFlow } from "../../hooks/useArchitectureAgentFlow";

const ArchitectureAgentFlowContext = createContext(null);

// Mirrors DomainAgentFlowContext.jsx exactly, for the same reason: ArchitectureAgentChat (the
// chat feed) and ResultTab (the live Architecture Plan document view) both need to observe the
// SAME in-flight stream -- two independent useArchitectureAgentFlow() calls would each hold their
// own separate mutation state, so the Result panel would never see a stream the chat panel
// started, or vice versa for the auto-continue flow that starts a run from ResultTab itself.
export function ArchitectureAgentFlowProvider({ featureId, children }) {
  const flow = useArchitectureAgentFlow(featureId);
  return <ArchitectureAgentFlowContext.Provider value={flow}>{children}</ArchitectureAgentFlowContext.Provider>;
}

export function useArchitectureAgentFlowContext() {
  const ctx = useContext(ArchitectureAgentFlowContext);
  if (!ctx) {
    throw new Error("useArchitectureAgentFlowContext must be used within an ArchitectureAgentFlowProvider");
  }
  return ctx;
}
