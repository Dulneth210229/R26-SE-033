"""
Unit tests for generator.analyze_failures / QAAgent._apply_root_cause_analysis -- the batched
root-cause + recommendation synthesis for failed tests (direct user request: explain WHY a test
actually failed, not just show Jest's raw assertion text). No real LLM/network calls --
llm_provider_service is mocked at its import site inside generator.analyze_failures.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.qa_agent import generator
from app.agents.qa_agent.agent import QAAgent


def _mock_provider(raw_output: str):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=raw_output)
    return provider


@pytest.mark.asyncio
async def test_analyze_failures_returns_empty_dict_for_no_failures():
    result = await generator.analyze_failures([], {})

    assert result == {}


@pytest.mark.asyncio
async def test_analyze_failures_returns_a_real_lookup_on_well_formed_response():
    raw = json.dumps({
        "root_causes": [
            {
                "test_file": "item.unit.test.ts",
                "name": "getItem returns an item",
                "root_cause": "getItem queries by _id but the test passes a string id.",
                "recommendation": "Cast the id to an ObjectId before querying.",
            }
        ]
    })
    failures = [{"name": "getItem returns an item", "test_file": "item.unit.test.ts",
                 "target_file": "lib/api/item.ts", "target_function": "getItem",
                 "failure_message": "Expected item, got null"}]
    provider = _mock_provider(raw)
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator.analyze_failures(failures, {"lib/api/item.ts": "export function getItem() {}"})

    key = ("item.unit.test.ts", "getItem returns an item")
    assert key in result
    assert result[key]["root_cause"] == "getItem queries by _id but the test passes a string id."
    assert result[key]["recommendation"] == "Cast the id to an ObjectId before querying."


@pytest.mark.asyncio
async def test_analyze_failures_returns_empty_dict_on_malformed_response():
    failures = [{"name": "a test", "test_file": "a.test.ts", "target_file": "lib/a.ts",
                 "target_function": "a", "failure_message": "boom"}]
    provider = _mock_provider("not json at all")
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator.analyze_failures(failures, {})

    assert result == {}


@pytest.mark.asyncio
async def test_analyze_failures_returns_empty_dict_when_provider_unreachable():
    failures = [{"name": "a test", "test_file": "a.test.ts", "target_file": "lib/a.ts",
                 "target_function": "a", "failure_message": "boom"}]
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=TimeoutError())
    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await generator.analyze_failures(failures, {})

    assert result == {}


@pytest.mark.asyncio
async def test_apply_root_cause_analysis_merges_into_the_matching_failed_case():
    merged = [
        {"name": "getItem returns an item", "test_file": "item.unit.test.ts", "target_file": "lib/api/item.ts",
         "target_function": "getItem", "status": "failed", "failure_message": "boom",
         "root_cause": None, "recommendation": None},
        {"name": "getItem is idempotent", "test_file": "item.unit.test.ts", "target_file": "lib/api/item.ts",
         "target_function": "getItem", "status": "passed", "failure_message": None,
         "root_cause": None, "recommendation": None},
    ]
    raw = json.dumps({
        "root_causes": [
            {"test_file": "item.unit.test.ts", "name": "getItem returns an item",
             "root_cause": "real root cause", "recommendation": "real recommendation"},
        ]
    })
    provider = _mock_provider(raw)
    unit_targets = [{"rel": "lib/api/item.ts", "source": "export function getItem() {}"}]

    with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=provider):
        result = await QAAgent()._apply_root_cause_analysis(merged, unit_targets, [])

    failed = next(tc for tc in result if tc["name"] == "getItem returns an item")
    passed = next(tc for tc in result if tc["name"] == "getItem is idempotent")
    assert failed["root_cause"] == "real root cause"
    assert failed["recommendation"] == "real recommendation"
    # A passed test was never sent for analysis at all -- stays None, not just unmatched.
    assert passed["root_cause"] is None


@pytest.mark.asyncio
async def test_apply_root_cause_analysis_is_a_no_op_with_no_failures():
    merged = [
        {"name": "a", "test_file": "a.test.ts", "target_file": "lib/a.ts", "target_function": "a",
         "status": "passed", "failure_message": None, "root_cause": None, "recommendation": None},
    ]

    with patch("app.services.llm_provider_service.llm_provider_service.get_provider") as mock_get_provider:
        result = await QAAgent()._apply_root_cause_analysis(merged, [], [])

    mock_get_provider.assert_not_called()
    assert result == merged
