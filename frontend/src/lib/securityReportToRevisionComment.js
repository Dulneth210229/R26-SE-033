import { DISPLAY_TIERS, groupFindingsByTier } from "./severityTiers";

// Formats a Security Agent report (the JSON artifact shape saved by security_agent/agent.py's
// run()) into a Coder Agent revision_comment. One line per finding as "[TIER] file:line --
// message", grouped critical-first -- deliberately carries a real `file:line` token per line so
// the Coder Agent's existing _find_well_specified_target_files (_REVISION_FILE_TOKEN_RE,
// coder_agent/agent.py:96) can target the right files with zero Coder-side changes.
//
// Each finding also carries its own root_cause/recommendation sub-lines when present (the
// backend's SecurityFinding schema populates both on every scan layer) -- this is what makes the
// plan the Coder Agent receives "coder-friendly" rather than just a bare list of complaints: it
// tells the model WHY the code is vulnerable and WHAT to change, not just where.
//
// skippedFindingIds (a human's explicit "accept the risk" choices for THIS report version, see
// securityGate.js) are filtered out before grouping -- a skipped finding must never be sent to
// the Coder Agent to "fix," since the whole point of skipping it was to proceed without fixing it.
export function buildSecurityRevisionComment(report, skippedFindingIds = []) {
  const skipped = new Set(skippedFindingIds || []);
  const findings = (report?.findings || []).filter((finding) => !skipped.has(finding.id));
  const groups = groupFindingsByTier(findings);

  const lines = ["Fix the following security findings reported by the Security Agent:", ""];

  for (const tier of DISPLAY_TIERS) {
    const findings = groups[tier];
    if (findings.length === 0) continue;

    for (const finding of findings) {
      const loc = finding.line ? `${finding.file}:${finding.line}` : finding.file;
      lines.push(`[${tier.toUpperCase()}] ${loc} -- ${finding.message} (${finding.cwe})`);
      if (finding.root_cause) {
        lines.push(`  Root cause: ${finding.root_cause}`);
      }
      if (finding.recommendation) {
        lines.push(`  Suggested fix: ${finding.recommendation}`);
      }
    }
  }

  return lines.join("\n");
}
