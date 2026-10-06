"""
Unit tests for QAAgent.run_stream -- the sequential, per-target progress-streaming sibling of
run() (direct user request, mirrors Architecture Agent's own run/run_stream split). Everything
below discovery/generation/execution is mocked at its module-level import site inside
qa_agent/agent.py, so these tests focus purely on the event sequence/shape run_stream itself
yields, not on real file I/O, real LLM calls, or a real Jest run (those are covered elsewhere --
test_qa_generator_fallback.py, test_qa_jest_parser.py, test_qa_root_cause_analysis.py).
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.qa_agent.agent import QAAgent
from app.agents.qa_agent.schemas import QaLLMGenerationResult, QaTestCase


def _fake_project_and_feature():
    return (
        {"project_id": "project_1", "project_name": "P"},
        {"project_id": "project_1", "feature_id": "feature_1", "feature_name": "F"},
    )


@pytest.fixture
def qa_run_stream_mocks(tmp_path):
    project, feature = _fake_project_and_feature()

    unit_target = {"rel": "lib/item.ts", "source": "export function getItem() {}", "exports": ["getItem"]}
    integration_target = {
        "route_rel": "app/api/items/route.ts", "route_source": "export async function GET() {}",
        "related_files": [],
    }

    unit_result = QaLLMGenerationResult(
        test_cases=[QaTestCase(name="getItem works", category="unit", target_file="lib/item.ts",
                                target_function="getItem")],
        test_code='test("getItem works", () => {});',
    )

    run_result = {
        "results": [{"name": "getItem works", "test_file": "item.unit.test.ts", "status": "failed",
                      "duration_ms": 5, "failure_message": "boom"}],
        "passed": 0, "failed": 1, "exit_code": 1, "raw_stderr": "",
    }

    saved_json = SimpleNamespace(artifact_id="artifact_json_1", version=1)
    saved_md = SimpleNamespace(artifact_id="artifact_md_1", version=1)

    with (
        patch("app.agents.qa_agent.agent.store") as mock_store,
        patch("app.agents.qa_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.qa_agent.agent.discovery") as mock_discovery,
        patch("app.agents.qa_agent.agent.generator") as mock_generator,
        patch("app.agents.qa_agent.agent.executor") as mock_executor,
        patch("app.agents.qa_agent.agent.artifact_service") as mock_artifact_service,
    ):
        mock_store.features.get.return_value = feature
        mock_store.projects.get.return_value = project
        mock_workspace.get_repo_path.return_value = tmp_path

        mock_discovery.discover_unit_test_targets.return_value = [unit_target]
        mock_discovery.discover_integration_test_targets.return_value = [integration_target]
        mock_discovery.discover_out_of_scope_modules.return_value = []

        mock_generator.generate_unit_tests = AsyncMock(return_value=unit_result)
        mock_generator.generate_integration_tests = AsyncMock(return_value=None)
        mock_generator.generate_regression_tests = AsyncMock(return_value=None)
        mock_generator.analyze_failures = AsyncMock(return_value={})

        mock_executor.run_tests.return_value = run_result

        mock_artifact_service.save_json_artifact.return_value = saved_json
        mock_artifact_service.save_text_artifact.return_value = saved_md

        with patch.object(QAAgent, "_load_approved_acceptance_criteria", return_value=[]):
            yield


@pytest.mark.asyncio
async def test_run_stream_yields_discovery_phase_first(qa_run_stream_mocks):
    events = [event async for event in QAAgent().run_stream(feature_id="feature_1")]

    assert events[0] == {"type": "phase", "phase": "discovery", "label": "Scanning the codebase for testable files..."}


@pytest.mark.asyncio
async def test_run_stream_yields_a_generation_progress_event_per_target(qa_run_stream_mocks):
    events = [event async for event in QAAgent().run_stream(feature_id="feature_1")]

    generation_events = [e for e in events if e["type"] == "generation_progress"]
    assert len(generation_events) == 2  # 1 unit target + 1 integration target, 0 regression (no acceptance criteria)
    assert generation_events[0]["category"] == "unit"
    assert generation_events[0]["target"] == "lib/item.ts"
    assert generation_events[0]["index"] == 1
    assert generation_events[0]["total"] == 2
    assert generation_events[1]["category"] == "integration"
    assert generation_events[1]["target"] == "app/api/items/route.ts"


@pytest.mark.asyncio
async def test_run_stream_yields_execution_phase_when_tests_were_generated(qa_run_stream_mocks):
    events = [event async for event in QAAgent().run_stream(feature_id="feature_1")]

    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert "execution" in phases


@pytest.mark.asyncio
async def test_run_stream_yields_root_cause_phase_only_when_there_are_failures(qa_run_stream_mocks):
    events = [event async for event in QAAgent().run_stream(feature_id="feature_1")]

    phases = [e["phase"] for e in events if e["type"] == "phase"]
    assert "root_cause" in phases
    # root_cause comes after execution, before saving -- the real order the frontend expects.
    assert phases.index("execution") < phases.index("root_cause") < phases.index("saving")


@pytest.mark.asyncio
async def test_run_stream_ends_with_a_real_done_event(qa_run_stream_mocks):
    events = [event async for event in QAAgent().run_stream(feature_id="feature_1")]

    done = events[-1]
    assert done["type"] == "done"
    assert done["artifact_ids"] == ["artifact_json_1", "artifact_md_1"]
    assert done["tests_generated"] == 1
    assert done["tests_failed"] == 1


@pytest.mark.asyncio
async def test_run_stream_yields_an_error_event_when_no_workspace_exists(tmp_path):
    project, feature = _fake_project_and_feature()
    missing_path = tmp_path / "does_not_exist"

    with (
        patch("app.agents.qa_agent.agent.store") as mock_store,
        patch("app.agents.qa_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_store.features.get.return_value = feature
        mock_store.projects.get.return_value = project
        mock_workspace.get_repo_path.return_value = missing_path

        events = [event async for event in QAAgent().run_stream(feature_id="feature_1")]

    assert len(events) == 1
    assert events[0]["type"] == "error"
