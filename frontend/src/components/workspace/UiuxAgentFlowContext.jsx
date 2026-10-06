import { createContext, useContext } from "react";
import { useUiuxAgentFlow } from "../../hooks/useUiuxAgentFlow";

const UiuxAgentFlowContext = createContext(null);

// Mirrors DomainAgentFlowContext.jsx/ArchitectureAgentFlowContext.jsx exactly: UiuxAgentChat (the
// chat feed) and ResultTab (the live ui_metadata document view, plus the auto-continue trigger
// right after Architecture Plan approval) both need to observe the SAME in-flight stream -- two
// independent useUiuxAgentFlow() calls would each hold their own separate mutation state, so the
// Result panel would never see a stream the chat panel started, or vice versa for the
// auto-continue flow that starts a run from ResultTab itself.
export function UiuxAgentFlowProvider({ featureId, children }) {
  const flow = useUiuxAgentFlow(featureId);
  return <UiuxAgentFlowContext.Provider value={flow}>{children}</UiuxAgentFlowContext.Provider>;
}

export function useUiuxAgentFlowContext() {
  const ctx = useContext(UiuxAgentFlowContext);
  if (!ctx) {
    throw new Error("useUiuxAgentFlowContext must be used within a UiuxAgentFlowProvider");
  }
  return ctx;
}
