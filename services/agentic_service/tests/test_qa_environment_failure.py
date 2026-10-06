"""
Unit tests for QAAgent._finalize_report's environment_failure signal -- a genuine "Jest produced
no results at all despite tests being planned" case is surfaced as ONE top-level honest signal
(never N individually "failed" test cases misread as real defects), and gates OFF
_apply_root_cause_analysis so a real LLM call never fabricates plausible-sounding root causes for
tests that never actually ran. No real LLM/Jest/Docker -- generator/artifact_service are mocked at
their import site inside qa_agent/agent.py, matching test_qa_run_stream.py's own established
mocking convention.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.qa_agent.agent import QAAgent
from app.agents.qa_agent.schemas import QaTestCase


def _fake_project_and_feature():
    return (
        {"project_id": "project_1", "project_name": "P"},
        {"project_id": "project_1", "feature_id": "feature_1", "feature_name": "F"},
    )


@pytest.fixture
def finalize_report_mocks():
    saved_json = SimpleNamespace(artifact_id="artifact_json_1", version=1)
    saved_md = SimpleNamespace(artifact_id="artifact_md_1", version=1)

    with (
        patch("app.agents.qa_agent.agent.generator") as mock_generator,
        patch("app.agents.qa_agent.agent.artifact_service") as mock_artifact_service,
    ):
        mock_generator.analyze_failures = AsyncMock(return_value={})
        mock_artifact_service.save_json_artifact.return_value = saved_json
        mock_artifact_service.save_text_artifact.return_value = saved_md
        yield mock_generator


@pytest.mark.asyncio
async def test_environment_failure_set_when_jest_produces_zero_results_for_planned_cases(finalize_report_mocks):
    project, feature = _fake_project_and_feature()
    test_cases = [QaTestCase(name="a test", category="unit", test_file="a.unit.test.ts")]
    run_result = {"results": [], "passed": 0, "failed": 0, "exit_code": 1, "raw_stderr": "FATAL: jest crashed"}

    output = await QAAgent()._finalize_report(
        feature_id="feature_1", feature=feature, project=project, all_test_cases=test_cases,
        run_result=run_result, unit_targets=[], integration_targets=[], out_of_scope=[],
    )

    report = output.qa_report_json
    assert report["environment_failure"] == {"reason": "FATAL: jest crashed"}
    # Every individual test case still resolves to "failed" -- never a third status.
    assert report["test_cases"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_environment_failure_reason_falls_back_to_an_honest_default_when_stderr_is_empty(finalize_report_mocks):
    project, feature = _fake_project_and_feature()
    test_cases = [QaTestCase(name="a test", category="unit", test_file="a.unit.test.ts")]
    run_result = {"results": [], "passed": 0, "failed": 0, "exit_code": None, "raw_stderr": ""}

    output = await QAAgent()._finalize_report(
        feature_id="feature_1", feature=feature, project=project, all_test_cases=test_cases,
        run_result=run_result, unit_targets=[], integration_targets=[], out_of_scope=[],
    )

    assert output.qa_report_json["environment_failure"]["reason"] == (
        "The test runner produced no results and no error output."
    )


@pytest.mark.asyncio
async def test_environment_failure_skips_root_cause_analysis_entirely(finalize_report_mocks):
    project, feature = _fake_project_and_feature()
    test_cases = [QaTestCase(name="a test", category="unit", test_file="a.unit.test.ts")]
    run_result = {"results": [], "passed": 0, "failed": 0, "exit_code": 1, "raw_stderr": "boom"}

    await QAAgent()._finalize_report(
        feature_id="feature_1", feature=feature, project=project, all_test_cases=test_cases,
        run_result=run_result, unit_targets=[], integration_targets=[], out_of_scope=[],
    )

    finalize_report_mocks.analyze_failures.assert_not_called()


@pytest.mark.asyncio
async def test_no_environment_failure_when_no_test_cases_were_planned_at_all(finalize_report_mocks):
    project, feature = _fake_project_and_feature()
    run_result = {"results": [], "passed": 0, "failed": 0, "exit_code": 0, "raw_stderr": ""}

    output = await QAAgent()._finalize_report(
        feature_id="feature_1", feature=feature, project=project, all_test_cases=[],
        run_result=run_result, unit_targets=[], integration_targets=[], out_of_scope=[],
    )

    # Nothing was ever planned -- not an infrastructure failure, just an honest empty report.
    assert output.qa_report_json["environment_failure"] is None


@pytest.mark.asyncio
async def test_no_environment_failure_and_root_cause_analysis_runs_for_a_genuine_failure(finalize_report_mocks):
    project, feature = _fake_project_and_feature()
    test_cases = [QaTestCase(name="a test", category="unit", test_file="a.unit.test.ts")]
    run_result = {
        "results": [{"name": "a test", "test_file": "a.unit.test.ts", "status": "failed",
                      "duration_ms": 5, "failure_message": "expected 1 to equal 2"}],
        "passed": 0, "failed": 1, "exit_code": 1, "raw_stderr": "",
    }

    output = await QAAgent()._finalize_report(
        feature_id="feature_1", feature=feature, project=project, all_test_cases=test_cases,
        run_result=run_result, unit_targets=[], integration_targets=[], out_of_scope=[],
    )

    assert output.qa_report_json["environment_failure"] is None
    finalize_report_mocks.analyze_failures.assert_called_once()
