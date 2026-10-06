"""
Unit tests for the dedicated use case diagram agentic generation step
(app/agents/architecture_agent/agent.py:_generate_usecase_diagram_via_exploration) and
_complete_usecase_model's full rung matrix (agentic -> focused single-shot -> deterministic
fallback, gated by attempt_agentic/attempt_focused_fallback, with diagram_generation_state
memoization). Mirrors test_architecture_diagram_exploration.py's existing coverage pattern for
the sequence/class equivalents.

No real LLM: create_agent / build_usecase_diagram_tools / llm_provider_service are mocked inside
the agent's namespace, while the real usecase_modeler/usecase_validator run for real so the
resulting use case diagrams (including the deterministic fallback path) are genuine, not stubbed.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.errors import GraphRecursionError

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.schemas import ArchitectureAgentInput

SRS = {
    "feature_name": "Task Search",
    "functional_requirements": [{"id": "FR-001", "description": "Search tasks by keyword."}],
    "acceptance_criteria": [{"id": "AC-001", "description": "Matching tasks are displayed."}],
    "user_roles": ["Registered User"],
}

VALID_USECASE_SUBMISSION = json.dumps({
    "system_boundary": "Task Search",
    "diagram_title": "Task Search Use Case Diagram",
    "actors": [{"name": "Registered User", "type": "primary"}],
    "use_cases": [
        {
            "name": "Search Tasks",
            "type": "main",
            "description": "A registered user searches for tasks by keyword.",
            "related_requirements": ["FR-001", "AC-001"],
        },
    ],
})

ARCHITECTURE_PLAN = {"design_views": {"interface_view": {}, "data_view": {}}}


def _mock_exploration_agent(side_effect=None):
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value={}, side_effect=side_effect)
    return fake_agent


@pytest.fixture
def agent():
    return ArchitectureAgent()


@pytest.fixture
def agent_input():
    return ArchitectureAgentInput(
        project={"project_id": "proj_usecase_test", "project_name": "TaskFlow", "target_stack": "MERN"},
        feature={"feature_id": "feature_usecase_test", "feature_name": "Task Search"},
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )


class TestUseCaseDiagramExploration:
    @pytest.mark.asyncio
    async def test_returns_parsed_specification_on_submission(self, agent, agent_input):
        captured = {"usecase_json": VALID_USECASE_SUBMISSION}
        with (
            patch("app.agents.architecture_agent.agent.build_usecase_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            result = await agent._generate_usecase_diagram_via_exploration(
                agent_input, ARCHITECTURE_PLAN, "Task Search"
            )

        assert result["use_cases"]

    @pytest.mark.asyncio
    async def test_raises_when_never_submitted(self, agent, agent_input):
        captured: dict = {}
        with (
            patch("app.agents.architecture_agent.agent.build_usecase_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError, match="submit_usecase_specification"):
                await agent._generate_usecase_diagram_via_exploration(agent_input, ARCHITECTURE_PLAN, "Task Search")

    @pytest.mark.asyncio
    async def test_recursion_limit_is_treated_as_no_submission(self, agent, agent_input):
        captured: dict = {}
        with (
            patch("app.agents.architecture_agent.agent.build_usecase_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent",
                  return_value=_mock_exploration_agent(side_effect=GraphRecursionError("too long"))),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError):
                await agent._generate_usecase_diagram_via_exploration(agent_input, ARCHITECTURE_PLAN, "Task Search")


def _parsed(usecase_specification_json=None) -> dict:
    parsed = {"architecture_plan_json": dict(ARCHITECTURE_PLAN)}
    if usecase_specification_json is not None:
        parsed["usecase_specification_json"] = usecase_specification_json
    return parsed


class TestCompleteUseCaseModelRungMatrix:
    @pytest.mark.asyncio
    async def test_agentic_step_succeeds_focused_fallback_never_needed(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_usecase_diagram_via_exploration",
                         AsyncMock(return_value=json.loads(VALID_USECASE_SUBMISSION))),
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock()
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_usecase_model(agent_input, _parsed())

            provider.invoke_agent.assert_not_awaited()  # focused single-shot tier never needed

        assert parsed["usecase_json"]["use_cases"]

    @pytest.mark.asyncio
    async def test_agentic_fails_focused_fallback_disabled_uses_deterministic_fallback(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_usecase_diagram_via_exploration",
                         AsyncMock(side_effect=ValueError("usecase exploration failed"))),
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock()
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_usecase_model(agent_input, _parsed())

            provider.invoke_agent.assert_not_awaited()  # attempt_focused_fallback defaults False

        # Deterministic fallback still produces a complete, valid model.
        assert parsed["usecase_json"]["use_cases"]

    @pytest.mark.asyncio
    async def test_agentic_fails_focused_fallback_enabled_uses_focused_single_shot(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_usecase_diagram_via_exploration",
                         AsyncMock(side_effect=ValueError("usecase exploration failed"))),
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock(return_value=VALID_USECASE_SUBMISSION)
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_usecase_model(
                agent_input, _parsed(), attempt_focused_fallback=True,
            )

            assert provider.invoke_agent.await_count == 1

        assert any(uc["name"] == "Search Tasks" for uc in parsed["usecase_json"]["use_cases"])

    @pytest.mark.asyncio
    async def test_attempt_agentic_false_skips_agentic_tier_entirely(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_usecase_diagram_via_exploration", AsyncMock()) as exploration,
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock(return_value=VALID_USECASE_SUBMISSION)
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_usecase_model(
                agent_input, _parsed(), attempt_agentic=False, attempt_focused_fallback=True,
            )

            exploration.assert_not_awaited()
            assert provider.invoke_agent.await_count == 1  # still gets real content via focused single-shot

        assert parsed["usecase_json"]["use_cases"]

    @pytest.mark.asyncio
    async def test_attempt_agentic_false_and_focused_fallback_false_never_calls_the_llm(self, agent, agent_input):
        """
        Mirrors _generate_architecture_output's true last-resort deterministic-
        fallback rung: the plan text itself already needed the deterministic
        fallback, so this rung must not make any new LLM call for the use case
        model either -- it just falls straight to the modeler's own
        deterministic template.
        """
        with (
            patch.object(agent, "_generate_usecase_diagram_via_exploration", AsyncMock()) as exploration,
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock()
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_usecase_model(agent_input, _parsed(), attempt_agentic=False)

            exploration.assert_not_awaited()
            provider.invoke_agent.assert_not_awaited()

        assert parsed["usecase_json"]["use_cases"]

    @pytest.mark.asyncio
    async def test_existing_specification_in_parsed_is_used_when_agentic_not_yet_attempted(self, agent, agent_input):
        """
        A rung whose main LLM call already embedded a real
        usecase_specification_json into `parsed` (e.g. _generate_raw_output_
        via_exploration's own submission) must not be discarded just because
        this specific call didn't itself attempt the agentic tier -- it's
        only regenerated from scratch if the agentic tier is attempted AND
        the existing specification is genuinely empty.
        """
        with (
            patch.object(agent, "_generate_usecase_diagram_via_exploration", AsyncMock()) as exploration,
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock()
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_usecase_model(
                agent_input,
                _parsed(usecase_specification_json=json.loads(VALID_USECASE_SUBMISSION)),
                attempt_agentic=False,
            )

            exploration.assert_not_awaited()
            provider.invoke_agent.assert_not_awaited()

        assert any(uc["name"] == "Search Tasks" for uc in parsed["usecase_json"]["use_cases"])

    @pytest.mark.asyncio
    async def test_memoization_prevents_a_second_agentic_attempt_across_cascading_rungs(self, agent, agent_input):
        """
        Simulates the outer ladder cascading through _complete_usecase_model
        twice within one run() call (e.g. a plan-validation failure on the
        first rung triggering a second rung) -- the SAME diagram_generation_state
        dict is threaded through both calls, exactly like _generate_architecture_output
        does, so the second call must not re-attempt the expensive agentic tier,
        and must reuse the cached successful result instead.
        """
        with (
            patch.object(agent, "_generate_usecase_diagram_via_exploration",
                         AsyncMock(return_value=json.loads(VALID_USECASE_SUBMISSION))) as exploration,
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock()
            mock_llm_service.get_provider.return_value = provider

            diagram_generation_state: dict = {}
            await agent._complete_usecase_model(agent_input, _parsed(), diagram_generation_state)
            second_parsed = await agent._complete_usecase_model(agent_input, _parsed(), diagram_generation_state)

            assert exploration.await_count == 1
            provider.invoke_agent.assert_not_awaited()

        assert second_parsed["usecase_json"]["use_cases"]
