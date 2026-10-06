// Mirrors app/agents/security_agent/severity.py's to_display_tier exactly -- the backend report
// already includes each finding's raw severity string (critical/high/medium/moderate/low/info/
// unknown, see that module's docstring for why two vocabularies exist), so the frontend only
// needs to reproduce the SAME small mapping, not re-derive it independently.
const TIER_BY_RAW_SEVERITY = {
  critical: "critical",
  high: "moderate",
  medium: "moderate",
  moderate: "moderate",
  low: "warning",
  info: "warning",
  unknown: "warning",
};

export const DISPLAY_TIERS = ["critical", "moderate", "warning"];

export function toDisplayTier(severity) {
  return TIER_BY_RAW_SEVERITY[String(severity || "unknown").toLowerCase().trim()] || "warning";
}

// Groups a flat findings array (report.findings) into {critical: [...], moderate: [...], warning: [...]},
// each already in the fixed DISPLAY_TIERS order.
export function groupFindingsByTier(findings) {
  const groups = { critical: [], moderate: [], warning: [] };
  for (const finding of findings || []) {
    groups[toDisplayTier(finding.severity)].push(finding);
  }
  return groups;
}
