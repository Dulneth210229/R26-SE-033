"""
Unit tests for executor._parse_jest_output -- parses Jest's real `--json` output shape
(testResults[].assertionResults[]) into the flat per-test-case result list agent.py matches
back to each planned QaTestCase. Uses a hand-built fixture matching Jest's real documented
--json shape (name/status/title/duration/failureMessages), not a live Jest run.
"""

from app.agents.qa_agent.executor import _parse_jest_output


def _jest_output(test_results):
    return {"testResults": test_results}


def test_parses_passed_and_failed_statuses_never_skipped():
    jest_output = _jest_output([
        {
            "name": "/repo/generated_tests/Item.unit.test.ts",
            "assertionResults": [
                {"title": "getItem returns an item", "status": "passed", "duration": 12, "failureMessages": []},
                {"title": "getItem throws on missing id", "status": "failed", "duration": 5,
                 "failureMessages": ["Expected function to throw"]},
                {"title": "getItem is pending", "status": "pending", "duration": None, "failureMessages": []},
            ],
        }
    ])

    result = _parse_jest_output(jest_output, exit_code=1)

    assert result["passed"] == 1
    assert result["failed"] == 2
    assert "skipped" not in result
    assert result["exit_code"] == 1
    assert len(result["results"]) == 3
    assert result["results"][2]["status"] == "failed"
    assert "pending" in result["results"][2]["failure_message"]


def test_test_file_is_normalized_to_basename_only():
    jest_output = _jest_output([
        {
            "name": "C:\\repo\\generated_tests\\Item.unit.test.ts",
            "assertionResults": [
                {"title": "x", "status": "passed", "duration": 1, "failureMessages": []},
            ],
        }
    ])

    result = _parse_jest_output(jest_output, exit_code=0)

    assert result["results"][0]["test_file"] == "Item.unit.test.ts"


def test_failure_message_joins_multiple_messages_and_truncates():
    long_message = "x" * 3000
    jest_output = _jest_output([
        {
            "name": "/repo/generated_tests/Item.unit.test.ts",
            "assertionResults": [
                {"title": "fails", "status": "failed", "duration": 1,
                 "failureMessages": ["first", long_message]},
            ],
        }
    ])

    result = _parse_jest_output(jest_output, exit_code=1)

    failure_message = result["results"][0]["failure_message"]
    assert failure_message.startswith("first\n")
    assert len(failure_message) <= 2000


def test_passing_result_has_no_failure_message():
    jest_output = _jest_output([
        {
            "name": "/repo/generated_tests/Item.unit.test.ts",
            "assertionResults": [
                {"title": "passes", "status": "passed", "duration": 3, "failureMessages": []},
            ],
        }
    ])

    result = _parse_jest_output(jest_output, exit_code=0)

    assert result["results"][0]["failure_message"] is None


def test_unknown_status_is_treated_as_failed_not_skipped():
    jest_output = _jest_output([
        {
            "name": "/repo/generated_tests/Item.unit.test.ts",
            "assertionResults": [
                {"title": "todo test", "status": "todo", "duration": None, "failureMessages": []},
            ],
        }
    ])

    result = _parse_jest_output(jest_output, exit_code=0)

    assert result["failed"] == 1
    assert result["results"][0]["status"] == "failed"
    assert "'todo'" in result["results"][0]["failure_message"]


def test_multiple_test_files_are_all_included():
    jest_output = _jest_output([
        {
            "name": "/repo/generated_tests/Item.unit.test.ts",
            "assertionResults": [{"title": "a", "status": "passed", "duration": 1, "failureMessages": []}],
        },
        {
            "name": "/repo/generated_tests/route.integration.test.ts",
            "assertionResults": [{"title": "b", "status": "failed", "duration": 2, "failureMessages": ["err"]}],
        },
    ])

    result = _parse_jest_output(jest_output, exit_code=1)

    test_files = {r["test_file"] for r in result["results"]}
    assert test_files == {"Item.unit.test.ts", "route.integration.test.ts"}


def test_empty_test_results_returns_zero_counts():
    result = _parse_jest_output({"testResults": []}, exit_code=0)

    assert result == {
        "results": [], "passed": 0, "failed": 0, "exit_code": 0, "raw_stderr": "",
    }


def test_missing_test_results_key_does_not_raise():
    result = _parse_jest_output({}, exit_code=None)

    assert result["results"] == []
    assert result["exit_code"] is None
