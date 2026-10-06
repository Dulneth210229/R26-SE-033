"""
QA Agent QA Report PDF Builder.

Purpose:
Convert a qa_report_json artifact into a real, well-structured HTML document (test cases grouped
by category, each with target/inputs/expected behavior/real execution status/failure message and
the synthesized root cause + recommendation for failures), rendered to PDF by
app.services.pdf_service. Mirrors the established 3-agent pattern (requirement/domain/architecture/
security_agent's own pdf_builder.py modules): reuses the genuinely generic helpers from
requirement_agent's own builder rather than reimplementing them.
"""

from __future__ import annotations

from typing import Any

from app.agents._shared.pdf_style import html_document_shell, signature_block_html
from app.agents.qa_agent.schemas import TEST_CATEGORIES
from app.agents.requirement_agent.pdf_builder import _esc, _meta_table, _plain_list, _section

_CATEGORY_HEADING = {"unit": "Unit", "integration": "Integration", "regression": "Regression"}
# Every test case resolves to "passed" or "failed" only -- never "skipped" (direct user
# requirement, see qa_agent/agent.py's own module docstring). An unrecognized status string
# (should never happen once the backend never emits one) deliberately does NOT fall back to a
# quiet gray -- it renders in the same red as "failed" so a future regression is loud in the
# exported PDF, not a silent reappearance of the status this fix removed.
_STATUS_BADGE_BACKGROUND = {"passed": "#16a34a", "failed": "#dc2626"}


def _status_badge(status: str) -> str:
    background = _STATUS_BADGE_BACKGROUND.get(status, "#dc2626")
    return f'<span class="badge" style="background:{background};">{_esc(status.upper())}</span>'


def _test_case_card(test_case: dict[str, Any]) -> str:
    target_file = test_case.get("target_file") or "N/A"
    target_function = test_case.get("target_function")
    target = f"{target_file}::{target_function}" if target_function else target_file
    inputs = test_case.get("inputs") or "Not specified."
    expected_behavior = test_case.get("expected_behavior") or "Not specified."
    failure_message = test_case.get("failure_message")
    root_cause = test_case.get("root_cause")
    recommendation = test_case.get("recommendation")

    parts = [
        '<div class="card">',
        f'<div class="card-title">{_esc(test_case.get("name", ""))} {_status_badge(test_case.get("status", "failed"))}</div>',
        f'<p style="font-size:9.5px;color:#6b7280;">Targets: {_esc(target)}</p>',
        f"<p><strong>Inputs:</strong> {_esc(inputs)}</p>",
        f"<p><strong>Expected behavior:</strong> {_esc(expected_behavior)}</p>",
    ]
    if failure_message:
        parts.append(f"<p><strong>Failure:</strong> {_esc(failure_message)}</p>")
    if root_cause:
        parts.append(f"<p><strong>Root cause:</strong> {_esc(root_cause)}</p>")
    if recommendation:
        parts.append(f"<p><strong>Recommendation:</strong> {_esc(recommendation)}</p>")
    parts.append("</div>")
    return "".join(parts)


def _test_cases_by_category_html(test_cases: list[dict[str, Any]]) -> str:
    if not test_cases:
        return '<p class="empty-note">No test cases were generated.</p>'

    groups: dict[str, list[dict[str, Any]]] = {category: [] for category in TEST_CATEGORIES}
    for test_case in test_cases:
        groups.setdefault(test_case.get("category", "unit"), []).append(test_case)

    parts = []
    for category in TEST_CATEGORIES:
        items = groups.get(category, [])
        if not items:
            continue
        cards = "".join(_test_case_card(tc) for tc in items)
        heading = _CATEGORY_HEADING.get(category, category.title())
        parts.append(f'<h3 class="subsection-title">{heading} ({len(items)})</h3>{cards}')
    return "".join(parts)


def build_qa_report_html(qa_report_json: dict[str, Any]) -> str:
    """
    Build a complete, self-contained QA Report HTML document from qa_report_json (the exact
    artifact shape qa_agent/agent.py's run()/run_stream() save).
    """
    feature_name = qa_report_json.get("feature_name", "Untitled Feature")
    test_cases = qa_report_json.get("test_cases", []) or []
    tests_by_category = qa_report_json.get("tests_by_category") or {}

    meta_rows = [
        ("Project", qa_report_json.get("project_name", "N/A")),
        ("Feature", qa_report_json.get("feature_name", "N/A")),
        ("Framework", qa_report_json.get("framework_used", "N/A")),
        ("Tests Generated", qa_report_json.get("tests_generated", len(test_cases))),
        ("Passed", qa_report_json.get("tests_passed", 0)),
        ("Failed", qa_report_json.get("tests_failed", 0)),
        ("Generated At", qa_report_json.get("generated_at", "N/A")),
    ]
    if qa_report_json.get("environment_failure"):
        meta_rows.append(("Environment Failure", qa_report_json["environment_failure"].get("reason", "N/A")))
    for category in TEST_CATEGORIES:
        counts = tests_by_category.get(category) or {"total": 0, "passed": 0, "failed": 0}
        heading = _CATEGORY_HEADING.get(category, category.title())
        meta_rows.append((
            f"{heading} Tests",
            f"{counts.get('total', 0)} total -- {counts.get('passed', 0)} passed, "
            f"{counts.get('failed', 0)} failed",
        ))

    sections = [
        _section(1, "Scan Summary", _meta_table(meta_rows)),
        _section(2, "Test Cases", _test_cases_by_category_html(test_cases)),
        _section(
            3, "Out of Scope for This Pass",
            _plain_list(qa_report_json.get("out_of_scope_modules", []))
            if qa_report_json.get("out_of_scope_modules") else '<p class="empty-note">Nothing out of scope.</p>',
        ),
    ]

    raw_stderr = qa_report_json.get("raw_stderr")
    if raw_stderr:
        sections.append(_section(
            4, "Test Runner Output (tail)",
            f'<pre style="white-space:pre-wrap;font-size:9.5px;">{_esc(raw_stderr[-2000:])}</pre>',
        ))

    sections.append(_section(len(sections) + 1, "Document Sign-Off", signature_block_html()))

    body_html = "".join(sections)
    body_html += (
        '<div class="doc-footer">Generated by AutoForge -- QA Agent. '
        "This document is a formatted export of the underlying qa_report artifact.</div>"
    )

    return html_document_shell(
        title=f"QA Report: {feature_name}",
        subtitle="QA Agent -- Test Generation & Execution Report",
        body_html=body_html,
    )
