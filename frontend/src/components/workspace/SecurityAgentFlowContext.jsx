import { createContext, useContext } from "react";
import { useRunSecurityAgent, useRunSecurityAgentDeepScan } from "../../hooks/useSecurityAgent";
import { useSecurityDeepScanFlow } from "../../hooks/useSecurityDeepScanFlow";

const SecurityAgentFlowContext = createContext(null);

// Mirrors UiuxAgentFlowContext.jsx's own reasoning, at the smallest scale that reasoning needs:
// SecurityReportView (the stage's own Run/Re-run Scan button), SecurityAgentChat (its own
// empty-state "Run Security Scan" action), and ResultTab (the Coder-Agent-approval popup's
// auto-triggered first scan) all need to observe the SAME useRunSecurityAgent mutation -- three
// independent instances would each hold their own separate `isPending`, so a scan started from
// one surface would show no visible progress on the others. Running a scan itself has no
// streaming route (one plain POST, see useSecurityAgent.js's own docstring), so this context
// wraps just that one mutation, not a bigger flow hook the way Domain/Architecture/UI-UX Agent's
// own contexts do -- Security Agent's chat is a genuinely separate concern with its own separate
// streaming hook, useSecurityChatFlow.js, not part of this context at all.
//
// Also wraps `securityDeepScanFlow` -- the AI-model deep-code-read scan's LIVE, streamed variant
// (real per-batch progress + a genuine stop, see useSecurityDeepScanFlow.js), which is what the UI
// actually uses now. The plain, non-streaming `runSecurityDeepScan` mutation (useSecurityAgent.js)
// is kept alongside, wired but unused by the UI -- matching this project's own established
// precedent for a superseded-but-still-valid hook (e.g. useRunDomain/useReviseDomain after Domain
// Agent got its own streaming chat).
export function SecurityAgentFlowProvider({ featureId, children }) {
  const runSecurity = useRunSecurityAgent(featureId);
  const runSecurityDeepScan = useRunSecurityAgentDeepScan(featureId);
  const securityDeepScanFlow = useSecurityDeepScanFlow(featureId);
  return (
    <SecurityAgentFlowContext.Provider value={{ runSecurity, runSecurityDeepScan, securityDeepScanFlow }}>
      {children}
    </SecurityAgentFlowContext.Provider>
  );
}

export function useSecurityAgentFlowContext() {
  const ctx = useContext(SecurityAgentFlowContext);
  if (!ctx) {
    throw new Error("useSecurityAgentFlowContext must be used within a SecurityAgentFlowProvider");
  }
  return ctx;
}
