"""
Unit tests for the Architecture Agent's targeted class diagram repair-retry
loop (app/agents/architecture_agent/agent.py: _complete_class_model /
_repair_class_specification). No real LLM: llm_provider_service is mocked
inside the agent's namespace (mirroring test_architecture_usecase_repair.py),
while the real class_modeler/class_validator run for real so validation
failures are genuine, not stubbed.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent, MAX_CLASS_REPAIR_ATTEMPTS
from app.agents.architecture_agent.schemas import ArchitectureAgentInput

SRS = {
    "feature_name": "Task Search",
    "functional_requirements": [
        {"id": "FR-001", "description": "Search tasks by keyword."},
    ],
}

# A specification with an anemic, placeholder-only entity -- must fail
# quality validation.
ANEMIC_SPECIFICATION = {
    "diagram_title": "Task Search Class Diagram",
    "classes": [
        {"name": "TaskSearchController", "stereotype": "control",
         "operations": [{"name": "searchTasks", "parameters": ["request"], "return_type": "Response", "visibility": "+"}],
         "related_requirements": ["FR-001"]},
        {"name": "Task", "stereotype": "entity",
         "attributes": [{"name": "id", "type": "String", "visibility": "+"}],
         "related_requirements": ["FR-001"]},
    ],
    "relationships": [
        {"from": "TaskSearchController", "to": "Task", "type": "association", "label": "reads",
         "source_multiplicity": "1", "target_multiplicity": "0..*"},
    ],
}

# A corrected specification with real, feature-specific attributes.
REPAIRED_SPECIFICATION = {
    "diagram_title": "Task Search Class Diagram",
    "classes": [
        {"name": "TaskSearchController", "stereotype": "control",
         "operations": [{"name": "searchTasks", "parameters": ["request"], "return_type": "Response", "visibility": "+"}],
         "related_requirements": ["FR-001"]},
        {"name": "Task", "stereotype": "entity",
         "attributes": [
             {"name": "title", "type": "String", "visibility": "-"},
             {"name": "description", "type": "String", "visibility": "-"},
         ],
         "related_requirements": ["FR-001"]},
    ],
    "relationships": [
        {"from": "TaskSearchController", "to": "Task", "type": "association", "label": "reads",
         "source_multiplicity": "1", "target_multiplicity": "0..*"},
    ],
}


@pytest.fixture
def agent():
    return ArchitectureAgent()


@pytest.fixture
def agent_input():
    return ArchitectureAgentInput(
        project={"project_id": "proj_repair_test", "project_name": "TaskFlow", "target_stack": "MERN"},
        feature={"feature_id": "feature_repair_test", "feature_name": "Task Search"},
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )


def _parsed_with_specification(specification: dict) -> dict:
    return {
        "architecture_plan_json": {"design_views": {}},
        "class_specification_json": specification,
    }


@pytest.mark.asyncio
async def test_repair_fixes_anemic_entity_on_first_attempt(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=json.dumps(REPAIRED_SPECIFICATION))

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_class_model(
            agent_input, _parsed_with_specification(dict(ANEMIC_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == 1

    task_class = next(c for c in parsed["class_diagram_json"]["classes"] if c["name"] == "Task")
    attribute_names = {a["name"] for a in task_class["attributes"]}
    assert attribute_names == {"title", "description"}

    agent.class_validator.validate(SRS, parsed["class_diagram_json"])


@pytest.mark.asyncio
async def test_repair_never_succeeds_falls_through_without_raising(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value="not json at all")

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_class_model(
            agent_input, _parsed_with_specification(dict(ANEMIC_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == 1
    assert parsed["class_diagram_json"]["classes"]


@pytest.mark.asyncio
async def test_repair_keeps_retrying_up_to_max_attempts_when_still_invalid(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=json.dumps(ANEMIC_SPECIFICATION))

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_class_model(
            agent_input, _parsed_with_specification(dict(ANEMIC_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == MAX_CLASS_REPAIR_ATTEMPTS
    assert parsed["class_diagram_json"]["classes"]


@pytest.mark.asyncio
async def test_repair_loop_is_skipped_entirely_for_the_true_fallback_rung(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock()

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_class_model(agent_input, _parsed_with_specification({}))

    provider.invoke_agent.assert_not_awaited()
    assert parsed["class_diagram_json"]["classes"]
