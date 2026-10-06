"""
Unit tests for the Architecture Agent's targeted sequence diagram repair-
retry loop (app/agents/architecture_agent/agent.py: _complete_sequence_model
/ _repair_sequence_specification). No real LLM: llm_provider_service is
mocked inside the agent's namespace (mirroring
test_architecture_usecase_repair.py), while the real sequence_modeler/
sequence_validator run for real so validation failures are genuine, not
stubbed.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent, MAX_SEQUENCE_REPAIR_ATTEMPTS
from app.agents.architecture_agent.schemas import ArchitectureAgentInput

SRS = {
    "feature_name": "Login",
    "functional_requirements": [
        {"id": "FR-001", "description": "The system must authenticate a user."},
    ],
    "user_roles": ["Registered User"],
}

# A specification with a duplicate message outside a loop -- must fail
# quality validation.
DUPLICATE_SPECIFICATION = {
    "diagram_title": "Login Sequence Diagram",
    "participants": [
        {"name": "Registered User", "type": "actor"},
        {"name": "LoginBoundary", "type": "boundary"},
        {"name": "LoginController", "type": "control"},
    ],
    "interactions": [
        {"kind": "message", "from": "Registered User", "to": "LoginBoundary", "message": "Submit credentials", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "LoginBoundary", "to": "LoginController", "message": "Authenticate user", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "LoginBoundary", "to": "LoginController", "message": "authenticate user", "message_type": "sync", "related_requirements": ["FR-001"]},
    ],
}

# A corrected specification with the duplicate removed.
REPAIRED_SPECIFICATION = {
    "diagram_title": "Login Sequence Diagram",
    "participants": [
        {"name": "Registered User", "type": "actor"},
        {"name": "LoginBoundary", "type": "boundary"},
        {"name": "LoginController", "type": "control"},
    ],
    "interactions": [
        {"kind": "message", "from": "Registered User", "to": "LoginBoundary", "message": "Submit credentials", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "LoginBoundary", "to": "LoginController", "message": "Authenticate user", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "LoginController", "to": "LoginBoundary", "message": "Return login result", "message_type": "return", "related_requirements": ["FR-001"]},
    ],
}


@pytest.fixture
def agent():
    return ArchitectureAgent()


@pytest.fixture
def agent_input():
    return ArchitectureAgentInput(
        project={"project_id": "proj_repair_test", "project_name": "TaskFlow", "target_stack": "MERN"},
        feature={"feature_id": "feature_repair_test", "feature_name": "Login"},
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )


def _parsed_with_specification(specification: dict) -> dict:
    return {
        "architecture_plan_json": {"design_views": {}},
        "sequence_specification_json": specification,
    }


@pytest.mark.asyncio
async def test_repair_fixes_duplicate_message_on_first_attempt(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=json.dumps(REPAIRED_SPECIFICATION))

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_sequence_model(
            agent_input, _parsed_with_specification(dict(DUPLICATE_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == 1

    messages = [i["message"] for i in parsed["sequence_diagram_json"]["interactions"] if i["kind"] == "message"]
    assert messages.count("Authenticate user") == 1

    agent.sequence_validator.validate(SRS, parsed["sequence_diagram_json"])


@pytest.mark.asyncio
async def test_repair_never_succeeds_falls_through_without_raising(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value="not json at all")

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_sequence_model(
            agent_input, _parsed_with_specification(dict(DUPLICATE_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == 1
    assert parsed["sequence_diagram_json"]["interactions"]


@pytest.mark.asyncio
async def test_repair_keeps_retrying_up_to_max_attempts_when_still_invalid(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=json.dumps(DUPLICATE_SPECIFICATION))

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_sequence_model(
            agent_input, _parsed_with_specification(dict(DUPLICATE_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == MAX_SEQUENCE_REPAIR_ATTEMPTS
    assert parsed["sequence_diagram_json"]["interactions"]


@pytest.mark.asyncio
async def test_repair_loop_is_skipped_entirely_for_the_true_fallback_rung(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock()

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_sequence_model(agent_input, _parsed_with_specification({}))

    provider.invoke_agent.assert_not_awaited()
    assert parsed["sequence_diagram_json"]["interactions"]
