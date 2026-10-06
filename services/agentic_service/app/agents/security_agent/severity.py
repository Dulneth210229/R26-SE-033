"""
Security Agent severity taxonomy.

Findings arrive with two DIFFERENT raw severity vocabularies depending on which layer produced
them: the pattern/secret scanners and the LLM reviewer use "critical"/"high"/"medium"/"low", while
`scan_dependencies` passes through npm audit's own raw severity string verbatim
("info"/"low"/"moderate"/"high"/"critical" -- note "moderate", not "medium"). Rather than
normalizing every producer to one vocabulary, this module is the single place that maps EITHER
raw vocabulary onto the three user-facing display tiers (Critical/Moderate/Warning) requested for
the report and the frontend's colour-coded badges -- every other piece of code (the report
builder, the API response counts, the frontend badge) reads that tier through this function
instead of re-deriving it.
"""

from __future__ import annotations

from typing import Any

DISPLAY_TIERS = ("critical", "moderate", "warning")

_TIER_BY_RAW_SEVERITY: dict[str, str] = {
    "critical": "critical",
    "high": "moderate",
    "medium": "moderate",
    "moderate": "moderate",  # npm audit's own vocabulary
    "low": "warning",
    "info": "warning",  # npm audit's own vocabulary
    "unknown": "warning",
}


def to_display_tier(severity: str) -> str:
    """Maps a finding's raw severity string onto critical/moderate/warning. Never raises --
    an unrecognized/malformed severity (e.g. a hallucinated LLM value) degrades to the least
    alarming tier rather than crashing report generation over it."""
    return _TIER_BY_RAW_SEVERITY.get(str(severity).lower().strip(), "warning")


def count_by_tier(findings: list[dict[str, Any]]) -> dict[str, int]:
    counts = {tier: 0 for tier in DISPLAY_TIERS}
    for finding in findings:
        counts[to_display_tier(finding.get("severity", "unknown"))] += 1
    return counts


def gate_decision(findings: list[dict[str, Any]]) -> str:
    """Informational only -- the "security" pipeline stage is deliberately a soft, auto-approved
    gate (see graph_orchestrator_service.AUTO_APPROVED_STAGES); this decision is surfaced to the
    human for them to act on, never consulted to block pipeline advancement.

    - "fail": at least one Critical-tier finding.
    - "review": no Critical, but at least one Moderate-tier finding.
    - "pass": nothing above Warning tier.
    """
    counts = count_by_tier(findings)
    if counts["critical"] > 0:
        return "fail"
    if counts["moderate"] > 0:
        return "review"
    return "pass"
