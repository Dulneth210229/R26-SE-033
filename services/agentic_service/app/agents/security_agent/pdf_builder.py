"""
Security Agent Security Report PDF Builder.

Purpose:
Convert a security_report_json artifact into a real, well-structured HTML document (findings
grouped by severity tier, each with file/line, CWE, root cause, and recommended fix -- the exact
fields the user asked for), rendered to PDF by app.services.pdf_service. Mirrors the established
3-agent pattern (requirement/domain/architecture_agent's own pdf_builder.py modules): reuses the
genuinely generic helpers from requirement_agent's own builder rather than reimplementing them,
and reuses severity.py's own to_display_tier/DISPLAY_TIERS for grouping -- the saved report only
carries each finding's raw producer-vocabulary severity string, never a precomputed tier, so
re-deriving that mapping here instead of importing it would risk silently drifting from the real
gate_decision/*_count fields and the frontend's own SecurityReportView.jsx.
"""

from __future__ import annotations

from typing import Any

from app.agents._shared.pdf_style import html_document_shell, signature_block_html
from app.agents.requirement_agent.pdf_builder import _esc, _meta_table, _section, _text_block
from app.agents.security_agent.severity import DISPLAY_TIERS, to_display_tier

_TIER_HEADING = {"critical": "Critical", "moderate": "Moderate", "warning": "Warning"}

# Inline overrides on the shared .badge class (a single green pill by default, see
# _shared/pdf_style.py) -- severity coloring is specific to this one document, not worth adding
# three new classes to the shared stylesheet every other agent's PDF would also load.
_TIER_BADGE_BACKGROUND = {"critical": "#dc2626", "moderate": "#ea580c", "warning": "#ca8a04"}


def _severity_badge(tier: str) -> str:
    background = _TIER_BADGE_BACKGROUND.get(tier, "#6b7280")
    return f'<span class="badge" style="background:{background};">{_esc(_TIER_HEADING.get(tier, tier))}</span>'


def _finding_card(finding: dict[str, Any]) -> str:
    tier = to_display_tier(finding.get("severity", "unknown"))
    file = finding.get("file") or "N/A"
    line = finding.get("line")
    location = f"{file}:{line}" if line is not None else f"{file} (N/A)"
    message = finding.get("message") or "No description provided."
    cwe = finding.get("cwe") or "N/A"
    root_cause = finding.get("root_cause") or "Not specified."
    recommendation = finding.get("recommendation") or "Not specified."

    return (
        '<div class="card">'
        f'<div class="card-title">{_esc(location)} {_severity_badge(tier)}</div>'
        f"<p>{_esc(message)}</p>"
        f'<p style="font-size:9.5px;color:#6b7280;">Rule: {_esc(finding.get("rule_id", "N/A"))} '
        f"-- CWE: {_esc(cwe)}</p>"
        f"<p><strong>Root cause:</strong> {_esc(root_cause)}</p>"
        f"<p><strong>Suggested fix:</strong> {_esc(recommendation)}</p>"
        "</div>"
    )


def _findings_by_tier_html(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return '<p class="empty-note">No findings from any scan layer.</p>'

    groups: dict[str, list[dict[str, Any]]] = {tier: [] for tier in DISPLAY_TIERS}
    for finding in findings:
        groups[to_display_tier(finding.get("severity", "unknown"))].append(finding)

    parts = []
    for tier in DISPLAY_TIERS:
        items = groups[tier]
        if not items:
            continue
        cards = "".join(_finding_card(finding) for finding in items)
        parts.append(
            f'<h3 class="subsection-title">{_TIER_HEADING[tier]} ({len(items)})</h3>{cards}'
        )
    return "".join(parts)


def _dependency_scan_html(dependency_scan: dict[str, Any] | None) -> str:
    dependency_scan = dependency_scan or {}
    summary = dependency_scan.get("dependency_summary")
    # npm audit's own metadata shape -- a dict of counts by severity, not a list of records.
    if isinstance(summary, dict) and summary:
        rows = [(str(key).replace("_", " ").title(), value) for key, value in summary.items()]
    else:
        rows = [("Summary", "Not available.")]

    meta_rows = [
        ("Audit Exit Code", dependency_scan.get("audit_exit_code", "N/A")),
        ("Ran Offline", "Yes" if dependency_scan.get("audit_ran_offline") else "No"),
    ]
    return _meta_table(meta_rows) + _meta_table(rows)


def build_security_report_html(security_report_json: dict[str, Any]) -> str:
    """
    Build a complete, self-contained Security Report HTML document from security_report_json
    (the exact artifact shape security_agent/agent.py's run()/run_ai_model_scan() save).
    """
    feature_name = security_report_json.get("feature_name", "Untitled Feature")
    findings = security_report_json.get("findings", []) or []

    meta_rows = [
        ("Project", security_report_json.get("project_name", "N/A")),
        ("Feature", security_report_json.get("feature_name", "N/A")),
        ("Scan Type", security_report_json.get("scan_type", "standard")),
        ("Gate Decision", (security_report_json.get("gate_decision") or "N/A").upper()),
        ("Total Findings", security_report_json.get("findings_count", len(findings))),
        ("Critical", security_report_json.get("critical_count", 0)),
        ("Moderate", security_report_json.get("moderate_count", 0)),
        ("Warning", security_report_json.get("warning_count", 0)),
        ("Scan Generated At", security_report_json.get("generated_at", "N/A")),
    ]

    sections = [
        _section(1, "Scan Summary", _meta_table(meta_rows)),
        _section(2, "Findings", _findings_by_tier_html(findings)),
        _section(3, "Dependency Scan", _dependency_scan_html(security_report_json.get("dependency_scan"))),
        _section(4, "LLM Review Status", _text_block(security_report_json.get("llm_review_status"))),
        _section(5, "Document Sign-Off", signature_block_html()),
    ]

    body_html = "".join(sections)
    body_html += (
        '<div class="doc-footer">Generated by AutoForge -- Security Agent. '
        "This document is a formatted export of the underlying security_report artifact.</div>"
    )

    return html_document_shell(
        title=f"Security Report: {feature_name}",
        subtitle="Security Agent -- Security Scan Report",
        body_html=body_html,
    )
