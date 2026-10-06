import { createContext, useContext } from "react";
import { useRequirementConversationFlow } from "../../hooks/useRequirementConversationFlow";

const RequirementConversationFlowContext = createContext(null);

// Both the middle chat panel (RequirementConversationChat) and the right output panel
// (RequirementSrsOutputPanel) need to observe the SAME live-generation state -- whether a stream
// is currently running and what text has arrived so far. Two independent
// useRequirementConversationFlow() calls would each hold their own separate mutation state, so
// clicking Confirm in the chat panel would never be visible to the output panel next to it. This
// provider calls the flow hook exactly once per feature and shares the result via context, so
// both panels observe the identical, single in-flight stream.
export function RequirementConversationFlowProvider({ featureId, children }) {
  const flow = useRequirementConversationFlow(featureId);
  return (
    <RequirementConversationFlowContext.Provider value={flow}>{children}</RequirementConversationFlowContext.Provider>
  );
}

export function useRequirementConversationFlowContext() {
  const ctx = useContext(RequirementConversationFlowContext);
  if (!ctx) {
    throw new Error(
      "useRequirementConversationFlowContext must be used within a RequirementConversationFlowProvider"
    );
  }
  return ctx;
}
