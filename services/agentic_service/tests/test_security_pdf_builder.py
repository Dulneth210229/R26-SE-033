"""
Tests for app.agents.security_agent.pdf_builder.build_security_report_html -- string-presence
assertions against a hand-built fixture report, confirming real severity-tier grouping (via the
real severity.to_display_tier, not a re-derived mapping), and defensive rendering of the real,
confirmed-nullable fields (root_cause/recommendation/line can be None -- line is always None for
every dependency-scan finding).
"""

from app.agents.security_agent.pdf_builder import build_security_report_html

REPORT_FIXTURE = {
    "project_name": "Finodil",
    "feature_name": "Login and Signup",
    "generated_at": "2026-08-25T10:00:00Z",
    "scan_type": "ai_model_deep_scan",
    "gate_decision": "fail",
    "findings_count": 3,
    "critical_count": 1,
    "moderate_count": 1,
    "warning_count": 1,
    "findings": [
        {
            "id": "SEC-AI-DEEPSCAN:1",
            "rule_id": "SEC-AI-DEEPSCAN",
            "layer": "ai_model_deep_scan",
            "severity": "critical",
            "cwe": "CWE-943",
            "file": "app/api/auth/login/route.ts",
            "line": 27,
            "message": "NoSQL Injection via Query Parameters",
            "root_cause": "const user = await LoginAndSignupData.findOne({ email, ...filter });",
            "recommendation": "Sanitize or validate the `filter` object to prevent injection attacks.",
        },
        {
            "id": "SEC-JS-005:app/page.tsx:10",
            "rule_id": "SEC-JS-005",
            "layer": "pattern",
            "severity": "high",
            "cwe": "CWE-79",
            "file": "app/page.tsx",
            "line": 10,
            "message": "dangerouslySetInnerHTML bypasses React's default escaping",
            # Confirmed real: findings shaped before this field existed carry None here.
            "root_cause": None,
            "recommendation": None,
        },
        {
            "id": "SEC-DEP-NPM-AUDIT:lodash",
            "rule_id": "SEC-DEP-NPM-AUDIT",
            "layer": "dependency",
            "severity": "low",
            "cwe": "CWE-1104",
            "file": "package-lock.json",
            # Confirmed real: every dependency-scan finding always has line=None.
            "line": None,
            "message": "npm audit flagged 'lodash'",
            "root_cause": "A known vulnerability exists in this dependency version.",
            "recommendation": "Upgrade lodash to a patched version.",
        },
    ],
    "dependency_scan": {
        "audit_exit_code": 0,
        "audit_ran_offline": True,
        "dependency_summary": {"info": 0, "low": 1, "moderate": 0, "high": 0, "critical": 0, "total": 1},
    },
    "llm_review_status": "AI model deep scan ran over 3 batch(es) of real source code (3 succeeded, 0 failed): 3 finding(s).",
}


def test_build_security_report_html_contains_every_expected_section_heading():
    html = build_security_report_html(REPORT_FIXTURE)

    for heading in ["Scan Summary", "Findings", "Dependency Scan", "LLM Review Status", "Document Sign-Off"]:
        assert heading in html


def test_findings_are_grouped_by_the_real_severity_tier_not_a_reinvented_mapping():
    html = build_security_report_html(REPORT_FIXTURE)

    # "critical" (raw) -> Critical tier; "high" (raw) -> Moderate tier; "low" (raw) -> Warning tier
    # -- exactly severity.to_display_tier's real mapping, confirmed by these headings appearing
    # with the correct counts.
    assert "Critical (1)" in html
    assert "Moderate (1)" in html
    assert "Warning (1)" in html


def test_every_real_finding_field_renders():
    html = build_security_report_html(REPORT_FIXTURE)

    assert "app/api/auth/login/route.ts:27" in html
    assert "NoSQL Injection via Query Parameters" in html
    assert "CWE-943" in html
    assert "Sanitize or validate the" in html


def test_null_root_cause_and_recommendation_render_a_fallback_not_none_or_a_crash():
    html = build_security_report_html(REPORT_FIXTURE)

    assert "Not specified." in html
    assert "None" not in html.split("Findings")[1].split("Dependency Scan")[0]


def test_null_line_renders_n_a_not_a_crash():
    html = build_security_report_html(REPORT_FIXTURE)

    assert "package-lock.json (N/A)" in html


def test_dependency_summary_dict_renders_as_a_table_not_a_python_repr():
    html = build_security_report_html(REPORT_FIXTURE)

    assert "Total" in html
    assert "{'info'" not in html  # would indicate a raw Python dict repr leaked through


def test_gate_decision_and_counts_render():
    html = build_security_report_html(REPORT_FIXTURE)

    assert "FAIL" in html
    assert "Finodil" in html
    assert "Login and Signup" in html


def test_html_escaping_of_finding_message():
    fixture = {
        **REPORT_FIXTURE,
        "findings": [
            {
                "id": "x", "rule_id": "SEC-X", "layer": "pattern", "severity": "critical",
                "cwe": "CWE-79", "file": "a.ts", "line": 1,
                "message": "<script>alert(1)</script>", "root_cause": None, "recommendation": None,
            }
        ],
    }
    html = build_security_report_html(fixture)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_findings_renders_an_empty_note_not_a_crash():
    fixture = {**REPORT_FIXTURE, "findings": [], "findings_count": 0}
    html = build_security_report_html(fixture)

    assert "No findings from any scan layer." in html


def test_result_is_a_complete_self_contained_html_document():
    html = build_security_report_html(REPORT_FIXTURE)

    assert html.startswith("<!DOCTYPE html>")
    assert "<title>Security Report: Login and Signup</title>" in html
