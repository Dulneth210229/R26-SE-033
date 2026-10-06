import { createContext, useContext } from "react";
import { useDomainAgentFlow } from "../../hooks/useDomainAgentFlow";

const DomainAgentFlowContext = createContext(null);

// Mirrors RequirementConversationFlowContext.jsx exactly, for the same reason: DomainAgentChat
// (the chat feed) and ResultTab (the live Enhanced SRS document view) both need to observe the
// SAME in-flight stream -- two independent useDomainAgentFlow() calls would each hold their own
// separate mutation state, so the Result panel would never see a stream the chat panel started.
export function DomainAgentFlowProvider({ featureId, children }) {
  const flow = useDomainAgentFlow(featureId);
  return <DomainAgentFlowContext.Provider value={flow}>{children}</DomainAgentFlowContext.Provider>;
}

export function useDomainAgentFlowContext() {
  const ctx = useContext(DomainAgentFlowContext);
  if (!ctx) {
    throw new Error("useDomainAgentFlowContext must be used within a DomainAgentFlowProvider");
  }
  return ctx;
}
