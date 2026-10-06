"""
Unit tests for the dedicated diagram-generation agentic steps in
app/agents/architecture_agent/agent.py:
_generate_sequence_diagram_via_exploration, _generate_class_diagram_via_exploration,
and _complete_diagram_models's full rung matrix (agentic -> focused
single-shot -> deterministic fallback, with per-run memoization and
attempt_agentic gating).

No real LLM: create_agent / build_sequence_diagram_tools /
build_class_diagram_tools / llm_provider_service are mocked inside the
agent's namespace (mirroring test_architecture_agent_exploration.py), while
the real sequence_modeler/class_modeler/sequence_validator/class_validator
run for real so the resulting diagrams are genuine, not stubbed.
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

VALID_SEQUENCE_SUBMISSION = json.dumps({
    "participants": [
        {"name": "Registered User", "type": "actor"},
        {"name": "TaskSearchBoundary", "type": "boundary"},
        {"name": "TaskSearchController", "type": "control"},
    ],
    "interactions": [
        {"kind": "message", "from": "Registered User", "to": "TaskSearchBoundary", "message": "Type keyword", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "TaskSearchBoundary", "to": "TaskSearchController", "message": "Search tasks", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "TaskSearchController", "to": "TaskSearchBoundary", "message": "Return results", "message_type": "return", "related_requirements": ["AC-001"]},
    ],
})

VALID_CLASS_SUBMISSION = json.dumps({
    "classes": [
        {"name": "TaskSearchController", "stereotype": "control",
         "operations": [{"name": "searchTasks", "parameters": ["request"], "return_type": "Response", "visibility": "+"}],
         "related_requirements": ["FR-001"]},
        {"name": "Task", "stereotype": "entity",
         "attributes": [{"name": "title", "type": "String", "visibility": "-"}],
         "related_requirements": ["FR-001"]},
    ],
    "relationships": [],
})

BOTH_FOCUSED_SUBMISSION = json.dumps({
    "sequence_specification_json": json.loads(VALID_SEQUENCE_SUBMISSION),
    "class_specification_json": json.loads(VALID_CLASS_SUBMISSION),
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
        project={"project_id": "proj_diagram_test", "project_name": "TaskFlow", "target_stack": "MERN"},
        feature={"feature_id": "feature_diagram_test", "feature_name": "Task Search"},
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )


class TestSequenceDiagramExploration:
    @pytest.mark.asyncio
    async def test_returns_parsed_specification_on_submission(self, agent, agent_input):
        captured = {"sequence_json": VALID_SEQUENCE_SUBMISSION}
        with (
            patch("app.agents.architecture_agent.agent.build_sequence_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            result = await agent._generate_sequence_diagram_via_exploration(
                agent_input, ARCHITECTURE_PLAN, "Task Search"
            )

        assert result["participants"]

    @pytest.mark.asyncio
    async def test_raises_when_never_submitted(self, agent, agent_input):
        captured: dict = {}
        with (
            patch("app.agents.architecture_agent.agent.build_sequence_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError, match="submit_sequence_specification"):
                await agent._generate_sequence_diagram_via_exploration(agent_input, ARCHITECTURE_PLAN, "Task Search")

    @pytest.mark.asyncio
    async def test_recursion_limit_is_treated_as_no_submission(self, agent, agent_input):
        captured: dict = {}
        with (
            patch("app.agents.architecture_agent.agent.build_sequence_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent",
                  return_value=_mock_exploration_agent(side_effect=GraphRecursionError("too long"))),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError):
                await agent._generate_sequence_diagram_via_exploration(agent_input, ARCHITECTURE_PLAN, "Task Search")


class TestClassDiagramExploration:
    @pytest.mark.asyncio
    async def test_returns_parsed_specification_on_submission(self, agent, agent_input):
        captured = {"class_json": VALID_CLASS_SUBMISSION}
        with (
            patch("app.agents.architecture_agent.agent.build_class_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            result = await agent._generate_class_diagram_via_exploration(
                agent_input, ARCHITECTURE_PLAN, "Task Search", json.loads(VALID_SEQUENCE_SUBMISSION)
            )

        assert result["classes"]

    @pytest.mark.asyncio
    async def test_raises_when_never_submitted(self, agent, agent_input):
        captured: dict = {}
        with (
            patch("app.agents.architecture_agent.agent.build_class_diagram_tools", return_value=([], captured)),
            patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
            patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        ):
            with pytest.raises(ValueError, match="submit_class_specification"):
                await agent._generate_class_diagram_via_exploration(
                    agent_input, ARCHITECTURE_PLAN, "Task Search", json.loads(VALID_SEQUENCE_SUBMISSION)
                )


def _parsed(architecture_plan_json=None) -> dict:
    return {"architecture_plan_json": architecture_plan_json or dict(ARCHITECTURE_PLAN)}


class TestCompleteDiagramModelsRungMatrix:
    @pytest.mark.asyncio
    async def test_both_agentic_steps_succeed(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_sequence_diagram_via_exploration",
                         AsyncMock(return_value=json.loads(VALID_SEQUENCE_SUBMISSION))),
            patch.object(agent, "_generate_class_diagram_via_exploration",
                         AsyncMock(return_value=json.loads(VALID_CLASS_SUBMISSION))),
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock()
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_diagram_models(agent_input, _parsed())

            provider.invoke_agent.assert_not_awaited()  # neither focused-single-shot tier was needed

        assert parsed["sequence_diagram_json"]["participants"]
        assert parsed["class_diagram_json"]["classes"]

    @pytest.mark.asyncio
    async def test_sequence_succeeds_class_fails_uses_class_only_focused_single_shot(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_sequence_diagram_via_exploration",
                         AsyncMock(return_value=json.loads(VALID_SEQUENCE_SUBMISSION))),
            patch.object(agent, "_generate_class_diagram_via_exploration",
                         AsyncMock(side_effect=ValueError("class exploration failed"))),
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock(return_value=VALID_CLASS_SUBMISSION)
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_diagram_models(agent_input, _parsed())

            # Exactly one focused single-shot call, for class only.
            assert provider.invoke_agent.await_count == 1

        # The successful agentic sequence result is preserved, not discarded.
        assert any(p["name"] == "TaskSearchBoundary" for p in parsed["sequence_diagram_json"]["participants"])
        assert parsed["class_diagram_json"]["classes"]

    @pytest.mark.asyncio
    async def test_sequence_agentic_fails_uses_combined_focused_single_shot(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_sequence_diagram_via_exploration",
                         AsyncMock(side_effect=ValueError("sequence exploration failed"))),
            patch.object(agent, "_generate_class_diagram_via_exploration", AsyncMock()) as class_exploration,
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock(return_value=BOTH_FOCUSED_SUBMISSION)
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_diagram_models(agent_input, _parsed())

            class_exploration.assert_not_awaited()  # skipped entirely, nothing to stay consistent with
            assert provider.invoke_agent.await_count == 1

        assert parsed["sequence_diagram_json"]["participants"]
        assert parsed["class_diagram_json"]["classes"]

    @pytest.mark.asyncio
    async def test_both_tiers_fail_falls_through_to_deterministic_fallback(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_sequence_diagram_via_exploration",
                         AsyncMock(side_effect=ValueError("sequence exploration failed"))),
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock(return_value="not json at all")
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_diagram_models(agent_input, _parsed())

        # Deterministic fallback still produces a complete, valid model.
        assert parsed["sequence_diagram_json"]["participants"]
        assert parsed["class_diagram_json"]["classes"]

    @pytest.mark.asyncio
    async def test_attempt_agentic_false_skips_agentic_tier_entirely(self, agent, agent_input):
        with (
            patch.object(agent, "_generate_sequence_diagram_via_exploration", AsyncMock()) as seq_exploration,
            patch.object(agent, "_generate_class_diagram_via_exploration", AsyncMock()) as cls_exploration,
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock(return_value=BOTH_FOCUSED_SUBMISSION)
            mock_llm_service.get_provider.return_value = provider

            parsed = await agent._complete_diagram_models(agent_input, _parsed(), attempt_agentic=False)

            seq_exploration.assert_not_awaited()
            cls_exploration.assert_not_awaited()
            assert provider.invoke_agent.await_count == 1  # still gets real content via focused single-shot

        assert parsed["sequence_diagram_json"]["participants"]
        assert parsed["class_diagram_json"]["classes"]

    @pytest.mark.asyncio
    async def test_memoization_prevents_a_second_agentic_attempt_across_cascading_rungs(self, agent, agent_input):
        """
        Simulates the outer ladder cascading through _complete_diagram_models
        twice within one run() call (e.g. a plan-validation failure on the
        first rung triggering a second rung) -- the SAME diagram_generation_state
        dict is threaded through both calls, exactly like _generate_architecture_output
        does, so the second call must not re-attempt the expensive agentic tier.
        """
        with (
            patch.object(agent, "_generate_sequence_diagram_via_exploration",
                         AsyncMock(return_value=json.loads(VALID_SEQUENCE_SUBMISSION))) as seq_exploration,
            patch.object(agent, "_generate_class_diagram_via_exploration",
                         AsyncMock(return_value=json.loads(VALID_CLASS_SUBMISSION))) as cls_exploration,
            patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
        ):
            provider = MagicMock()
            provider.invoke_agent = AsyncMock()
            mock_llm_service.get_provider.return_value = provider

            diagram_generation_state: dict = {}
            await agent._complete_diagram_models(agent_input, _parsed(), diagram_generation_state)
            await agent._complete_diagram_models(agent_input, _parsed(), diagram_generation_state)

            assert seq_exploration.await_count == 1
            assert cls_exploration.await_count == 1
            provider.invoke_agent.assert_not_awaited()  # second call reused the cached result, no new calls at all
