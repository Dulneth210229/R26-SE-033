"""
Tests for app.agents.qa_agent.pdf_builder.build_qa_report_html -- string-presence assertions
against a hand-built fixture report, confirming real category grouping, defensive rendering of
confirmed-nullable fields (root_cause/recommendation/failure_message can be None for a
passed/skipped test), and a complete self-contained document.
"""

from app.agents.qa_agent.pdf_builder import build_qa_report_html

REPORT_FIXTURE = {
    "project_name": "Finodil",
    "feature_name": "Login and Signup",
    "generated_at": "2026-08-26T10:00:00Z",
    "framework_used": "jest",
    "tests_generated": 3,
    "tests_passed": 1,
    "tests_failed": 2,
    "tests_by_category": {
        "unit": {"total": 2, "passed": 1, "failed": 1},
        "integration": {"total": 1, "passed": 0, "failed": 1},
        "regression": {"total": 0, "passed": 0, "failed": 0},
    },
    "test_cases": [
        {
            "name": "getItem returns an item", "category": "unit", "target_file": "lib/api/item.ts",
            "target_function": "getItem", "inputs": "a valid item id", "expected_behavior": "returns the item",
            "test_file": "item.unit.test.ts", "method": "llm", "status": "passed",
            "duration_ms": 12, "failure_message": None, "root_cause": None, "recommendation": None,
        },
        {
            "name": "getItem returns null for a missing id", "category": "unit", "target_file": "lib/api/item.ts",
            "target_function": "getItem", "inputs": "a nonexistent item id", "expected_behavior": "returns null",
            "test_file": "item.unit.test.ts", "method": "llm", "status": "failed",
            "duration_ms": 8, "failure_message": "Expected null, got undefined",
            "root_cause": "getItem does not guard against a missing document.",
            "recommendation": "Return null explicitly when the query result is falsy.",
        },
        {
            "name": "POST /api/items creates an item", "category": "integration", "target_file": "app/api/items/route.ts",
            "target_function": "POST", "inputs": "", "expected_behavior": "",
            "test_file": "items.integration.test.ts", "method": "llm", "status": "failed",
            "duration_ms": None, "failure_message": None, "root_cause": None, "recommendation": None,
        },
    ],
    "out_of_scope_modules": ["app/page.tsx", "components/ItemCard.tsx"],
    "raw_stderr": "",
}


def test_build_qa_report_html_contains_every_expected_section_heading():
    html = build_qa_report_html(REPORT_FIXTURE)

    for heading in ["Scan Summary", "Test Cases", "Out of Scope for This Pass", "Document Sign-Off"]:
        assert heading in html


def test_test_cases_are_grouped_by_the_real_category():
    html = build_qa_report_html(REPORT_FIXTURE)

    assert "Unit (2)" in html
    assert "Integration (1)" in html
    assert "Regression" not in html.split("Test Cases")[1].split("Out of Scope")[0]


def test_every_real_test_case_field_renders():
    html = build_qa_report_html(REPORT_FIXTURE)

    assert "getItem returns an item" in html
    assert "lib/api/item.ts::getItem" in html
    assert "a valid item id" in html
    assert "PASSED" in html
    assert "FAILED" in html
    assert "SKIPPED" not in html


def test_failure_message_root_cause_and_recommendation_render_for_the_failed_case():
    html = build_qa_report_html(REPORT_FIXTURE)

    assert "Expected null, got undefined" in html
    assert "getItem does not guard against a missing document." in html
    assert "Return null explicitly when the query result is falsy." in html


def test_null_fields_render_a_fallback_not_none_or_a_crash():
    html = build_qa_report_html(REPORT_FIXTURE)

    # The third (failed, unmatched) test case has no inputs/expected_behavior -- must fall back,
    # never show "None".
    assert "None" not in html.split("Test Cases")[1].split("Out of Scope")[0]


def test_out_of_scope_modules_render():
    html = build_qa_report_html(REPORT_FIXTURE)

    assert "app/page.tsx" in html
    assert "components/ItemCard.tsx" in html


def test_per_category_pass_fail_counts_render_from_tests_by_category():
    html = build_qa_report_html(REPORT_FIXTURE)

    assert "2 total -- 1 passed, 1 failed" in html


def test_raw_stderr_only_renders_when_non_empty():
    html_without = build_qa_report_html(REPORT_FIXTURE)
    assert "Test Runner Output" not in html_without

    with_stderr = {**REPORT_FIXTURE, "raw_stderr": "FATAL: jest crashed"}
    html_with = build_qa_report_html(with_stderr)
    assert "Test Runner Output" in html_with
    assert "FATAL: jest crashed" in html_with


def test_html_escaping_of_test_case_name():
    fixture = {
        **REPORT_FIXTURE,
        "test_cases": [
            {
                "name": "<script>alert(1)</script>", "category": "unit", "target_file": "a.ts",
                "target_function": "a", "inputs": "", "expected_behavior": "",
                "test_file": "a.test.ts", "method": "llm", "status": "passed",
                "duration_ms": 1, "failure_message": None, "root_cause": None, "recommendation": None,
            }
        ],
    }
    html = build_qa_report_html(fixture)

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_empty_test_cases_renders_an_empty_note_not_a_crash():
    fixture = {**REPORT_FIXTURE, "test_cases": [], "tests_generated": 0}
    html = build_qa_report_html(fixture)

    assert "No test cases were generated." in html


def test_result_is_a_complete_self_contained_html_document():
    html = build_qa_report_html(REPORT_FIXTURE)

    assert html.startswith("<!DOCTYPE html>")
    assert "<title>QA Report: Login and Signup</title>" in html
