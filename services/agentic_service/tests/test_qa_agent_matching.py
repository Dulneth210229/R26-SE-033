"""
Unit tests for QAAgent's own deterministic matching/aggregation logic -- _merge_results (pairs a
planned QaTestCase back to its real Jest execution result by (test_file, name), the same
convention prompt.py instructs the LLM to preserve), _count_by_category, and
_build_markdown_report. No LLM/Jest/Docker involved -- pure Python given hand-built inputs.
"""

from app.agents.qa_agent.agent import QAAgent, _build_markdown_report
from app.agents.qa_agent.schemas import QaTestCase

qa_agent = QAAgent()


def _tc(name, test_file, category="unit", **kwargs):
    return QaTestCase(name=name, test_file=test_file, category=category, **kwargs)


def test_merge_results_matches_by_test_file_and_name():
    test_cases = [_tc("adds two numbers", "math.unit.test.ts")]
    results = [
        {"name": "adds two numbers", "test_file": "math.unit.test.ts", "status": "passed",
         "duration_ms": 5, "failure_message": None},
    ]

    merged = qa_agent._merge_results(test_cases, results)

    assert len(merged) == 1
    assert merged[0]["status"] == "passed"
    assert merged[0]["duration_ms"] == 5


def test_merge_results_unmatched_case_is_marked_failed_with_explicit_note():
    test_cases = [_tc("a test that never ran", "broken.unit.test.ts")]

    merged = qa_agent._merge_results(test_cases, [])

    assert merged[0]["status"] == "failed"
    assert "did not produce a matching result" in merged[0]["failure_message"]


def test_merge_results_does_not_cross_match_same_name_different_file():
    test_cases = [_tc("returns null", "a.unit.test.ts")]
    results = [
        {"name": "returns null", "test_file": "b.unit.test.ts", "status": "passed",
         "duration_ms": 1, "failure_message": None},
    ]

    merged = qa_agent._merge_results(test_cases, results)

    assert merged[0]["status"] == "failed"


def test_merge_results_falls_back_to_positional_match_within_same_file_on_name_drift():
    test_cases = [_tc("adds two numbers correctly", "math.unit.test.ts")]
    results = [
        {"name": "should add two numbers", "test_file": "math.unit.test.ts", "status": "passed",
         "duration_ms": 3, "failure_message": None},
    ]

    merged = qa_agent._merge_results(test_cases, results)

    assert merged[0]["status"] == "passed"
    assert merged[0]["duration_ms"] == 3


def test_merge_results_leaves_genuine_execution_gap_as_failed():
    test_cases = [
        _tc("case one", "math.unit.test.ts"),
        _tc("case two", "math.unit.test.ts"),
    ]
    results = [
        {"name": "case one", "test_file": "math.unit.test.ts", "status": "passed",
         "duration_ms": 2, "failure_message": None},
    ]

    merged = qa_agent._merge_results(test_cases, results)

    assert merged[0]["status"] == "passed"
    assert merged[1]["status"] == "failed"
    assert "did not produce a matching result" in merged[1]["failure_message"]


def test_merge_results_preserves_planning_metadata_alongside_real_result():
    test_cases = [_tc(
        "getItem returns an item", "Item.unit.test.ts", category="unit",
        target_file="lib/api/item.ts", target_function="getItem",
        inputs="a valid id", expected_behavior="returns the matching item",
        method="llm",
    )]
    results = [
        {"name": "getItem returns an item", "test_file": "Item.unit.test.ts", "status": "failed",
         "duration_ms": 12, "failure_message": "Expected {id: 1} to equal {id: 2}"},
    ]

    merged = qa_agent._merge_results(test_cases, results)

    tc = merged[0]
    assert tc["target_file"] == "lib/api/item.ts"
    assert tc["target_function"] == "getItem"
    assert tc["inputs"] == "a valid id"
    assert tc["expected_behavior"] == "returns the matching item"
    assert tc["method"] == "llm"
    assert tc["status"] == "failed"
    assert tc["failure_message"] == "Expected {id: 1} to equal {id: 2}"


def test_count_by_category_totals_and_per_status_counts():
    merged = [
        {"category": "unit", "status": "passed"},
        {"category": "unit", "status": "failed"},
        {"category": "integration", "status": "passed"},
        {"category": "regression", "status": "failed"},
    ]

    counts = qa_agent._count_by_category(merged)

    assert counts["unit"] == {"total": 2, "passed": 1, "failed": 1}
    assert counts["integration"] == {"total": 1, "passed": 1, "failed": 0}
    assert counts["regression"] == {"total": 1, "passed": 0, "failed": 1}


def test_count_by_category_always_includes_all_three_categories_even_when_empty():
    counts = qa_agent._count_by_category([])

    assert set(counts.keys()) == {"unit", "integration", "regression"}
    assert counts["unit"]["total"] == 0


def _sample_report(test_cases=None, out_of_scope=None, raw_stderr=""):
    return {
        "project_name": "Sample Project",
        "feature_name": "Item Listing",
        "generated_at": "2026-08-18T00:00:00+00:00",
        "framework_used": "jest",
        "tests_generated": len(test_cases or []),
        "tests_passed": sum(1 for tc in (test_cases or []) if tc["status"] == "passed"),
        "tests_failed": sum(1 for tc in (test_cases or []) if tc["status"] == "failed"),
        "tests_by_category": qa_agent._count_by_category(test_cases or []),
        "test_cases": test_cases or [],
        "out_of_scope_modules": out_of_scope or [],
        "raw_stderr": raw_stderr,
    }


def test_build_markdown_report_lists_each_test_case_with_status_and_target():
    report = _sample_report(test_cases=[
        {"name": "getItem returns an item", "category": "unit", "target_file": "lib/api/item.ts",
         "target_function": "getItem", "status": "passed", "failure_message": None},
    ])

    markdown = _build_markdown_report(report)

    assert "getItem returns an item" in markdown
    assert "lib/api/item.ts::getItem" in markdown
    assert "[PASSED]" in markdown


def test_build_markdown_report_includes_failure_message_first_line_only():
    report = _sample_report(test_cases=[
        {"name": "fails", "category": "unit", "target_file": "lib/x.ts", "target_function": "",
         "status": "failed", "failure_message": "line one\nline two\nline three"},
    ])

    markdown = _build_markdown_report(report)

    assert "line one" in markdown
    assert "line two" not in markdown


def test_build_markdown_report_handles_zero_test_cases():
    report = _sample_report(test_cases=[])

    markdown = _build_markdown_report(report)

    assert "No test cases were generated." in markdown


def test_build_markdown_report_lists_out_of_scope_modules():
    report = _sample_report(out_of_scope=["app/page.tsx", "components/Widget.tsx"])

    markdown = _build_markdown_report(report)

    assert "app/page.tsx" in markdown
    assert "components/Widget.tsx" in markdown


def test_build_markdown_report_omits_stderr_section_when_empty():
    report = _sample_report(raw_stderr="")

    markdown = _build_markdown_report(report)

    assert "Test runner stderr" not in markdown


def test_build_markdown_report_includes_stderr_tail_when_present():
    report = _sample_report(raw_stderr="a real jest crash trace")

    markdown = _build_markdown_report(report)

    assert "Test runner stderr" in markdown
    assert "a real jest crash trace" in markdown
