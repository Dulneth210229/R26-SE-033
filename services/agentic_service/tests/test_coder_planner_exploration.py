"""
Unit tests for CodePlanner.generate_via_exploration (app/agents/coder_agent/planner.py)
-- the agentic, tool-exploring counterpart to generate(), used only by
CoderAgent.revise(). No real LLM: create_agent and build_revision_planning_tools
are both mocked, since this test is about the orchestration logic (reading
the captured plan after the loop ends, recursion-limit/no-submission
handling, JSON repair fallback), not about real tool-calling behavior --
that's proven separately by the real end-to-end revise() run against a live
feature.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.errors import GraphRecursionError

from app.agents.coder_agent.planner import CodePlanGenerationError, CodePlanner, REVISION_PLANNING_RECURSION_LIMIT

VALID_PLAN_JSON_STR = (
    '{"files": [{"path": "client/src/pages/TaskDetailPage.jsx", "action": "modify", '
    '"rationale": "Add tailwind styling", "maps_to": []}], '
    '"new_dependencies": [], "env_vars_needed": [], "summary": "Add tailwind styling."}'
)


def _call_kwargs(**overrides):
    kwargs = dict(
        project_id="proj_x",
        feature_id="feature_x",
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Task Comments"},
        srs_json={"functional_requirements": []},
        architecture_plan_json={"design_views": {}},
        ui_integration_manifest_json=None,
        project_manifest_json={},
        human_comment="Styles are missing, add tailwind css",
        previous_plan_json=None,
        validation_feedback=None,
        coverage_baseline_files=[],
    )
    kwargs.update(overrides)
    return kwargs


def _mock_agent(ainvoke_result=None, ainvoke_side_effect=None):
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value=ainvoke_result, side_effect=ainvoke_side_effect)
    return fake_agent


@pytest.mark.asyncio
async def test_parses_the_plan_submitted_via_submit_code_plan():
    planner = CodePlanner()
    captured = {"plan_json": VALID_PLAN_JSON_STR}
    fake_agent = _mock_agent(ainvoke_result={})

    with (
        patch("app.agents.coder_agent.planner.build_revision_planning_tools", return_value=([], captured)),
        patch("app.agents.coder_agent.planner.create_agent", return_value=fake_agent),
    ):
        code_plan_json, raw = await planner.generate_via_exploration(**_call_kwargs())

    assert code_plan_json["files"][0]["path"] == "client/src/pages/TaskDetailPage.jsx"
    assert raw == VALID_PLAN_JSON_STR
    fake_agent.ainvoke.assert_awaited_once()
    _, call_kwargs = fake_agent.ainvoke.await_args
    assert call_kwargs["config"]["recursion_limit"] == REVISION_PLANNING_RECURSION_LIMIT


@pytest.mark.asyncio
async def test_raises_when_submit_code_plan_is_never_called():
    planner = CodePlanner()
    captured: dict = {}
    fake_agent = _mock_agent(ainvoke_result={})

    with (
        patch("app.agents.coder_agent.planner.build_revision_planning_tools", return_value=([], captured)),
        patch("app.agents.coder_agent.planner.create_agent", return_value=fake_agent),
    ):
        with pytest.raises(CodePlanGenerationError, match="submit_code_plan"):
            await planner.generate_via_exploration(**_call_kwargs())


@pytest.mark.asyncio
async def test_recursion_limit_is_treated_as_a_clean_failure_not_a_crash():
    planner = CodePlanner()
    captured: dict = {}
    fake_agent = _mock_agent(ainvoke_side_effect=GraphRecursionError("exploration ran too long"))

    with (
        patch("app.agents.coder_agent.planner.build_revision_planning_tools", return_value=([], captured)),
        patch("app.agents.coder_agent.planner.create_agent", return_value=fake_agent),
    ):
        with pytest.raises(CodePlanGenerationError, match="submit_code_plan"):
            await planner.generate_via_exploration(**_call_kwargs())


@pytest.mark.asyncio
async def test_unexpected_exception_is_treated_as_a_clean_failure_not_a_crash():
    """A real, confirmed gap: previously only GraphRecursionError was caught around
    agent.ainvoke(...) -- any other exception (a transient Ollama/langchain-ollama transport
    error, already documented elsewhere in this project's history as a real occurrence)
    propagated straight out uncaught. Confirms it now falls through to the same
    "plan_json not in captured" -> CodePlanGenerationError path as a turn-limit timeout,
    letting _plan_with_retries retry it like any other incomplete attempt."""
    planner = CodePlanner()
    captured: dict = {}
    fake_agent = _mock_agent(ainvoke_side_effect=RuntimeError("Ollama connection reset"))

    with (
        patch("app.agents.coder_agent.planner.build_revision_planning_tools", return_value=([], captured)),
        patch("app.agents.coder_agent.planner.create_agent", return_value=fake_agent),
    ):
        with pytest.raises(CodePlanGenerationError, match="submit_code_plan"):
            await planner.generate_via_exploration(**_call_kwargs())


@pytest.mark.asyncio
async def test_malformed_submitted_json_goes_through_the_existing_repair_path():
    planner = CodePlanner()
    captured = {"plan_json": "not valid json at all"}
    fake_agent = _mock_agent(ainvoke_result={})

    repaired_provider = MagicMock()
    repaired_provider.invoke_agent = AsyncMock(return_value=VALID_PLAN_JSON_STR)
    mock_llm_provider_service = MagicMock()
    mock_llm_provider_service.get_provider.return_value = repaired_provider

    with (
        patch("app.agents.coder_agent.planner.build_revision_planning_tools", return_value=([], captured)),
        patch("app.agents.coder_agent.planner.create_agent", return_value=fake_agent),
        patch("app.agents.coder_agent.planner.llm_provider_service", mock_llm_provider_service),
    ):
        code_plan_json, raw = await planner.generate_via_exploration(**_call_kwargs())

    assert code_plan_json["files"][0]["path"] == "client/src/pages/TaskDetailPage.jsx"
    repaired_provider.invoke_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_keyword_hint_files_is_threaded_into_the_user_prompt():
    """
    Tier 1b (CoderAgent._find_keyword_hint_files) -- confirms generate_via_exploration
    actually forwards keyword_hint_files into build_agentic_revision_planner_user_prompt,
    not just accepts it as a dead parameter.
    """
    planner = CodePlanner()
    captured = {"plan_json": VALID_PLAN_JSON_STR}
    fake_agent = _mock_agent(ainvoke_result={})
    hint_files = ["app/login/LoginForm.tsx", "components/Footer.tsx"]

    with (
        patch("app.agents.coder_agent.planner.build_revision_planning_tools", return_value=([], captured)),
        patch("app.agents.coder_agent.planner.create_agent", return_value=fake_agent),
        patch(
            "app.agents.coder_agent.planner.build_agentic_revision_planner_user_prompt",
            wraps=None,
            return_value="prompt text",
        ) as mock_build_prompt,
    ):
        await planner.generate_via_exploration(**_call_kwargs(keyword_hint_files=hint_files))

    _, call_kwargs = mock_build_prompt.call_args
    assert call_kwargs["keyword_hint_files"] == hint_files
