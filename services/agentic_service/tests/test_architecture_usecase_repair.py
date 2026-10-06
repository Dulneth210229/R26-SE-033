"""
Unit tests for the Architecture Agent's targeted use-case repair-retry loop
(app/agents/architecture_agent/agent.py: _complete_usecase_model /
_repair_usecase_specification). No real LLM: llm_provider_service is mocked
inside the agent's namespace (mirroring test_architecture_agent_exploration.py),
while the real usecase_modeler/usecase_validator run for real so validation
failures are genuine, not stubbed.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent, MAX_USECASE_REPAIR_ATTEMPTS
from app.agents.architecture_agent.schemas import ArchitectureAgentInput

SRS = {
    "feature_name": "Login",
    "functional_requirements": [
        {"id": "FR-001", "description": "The system must authenticate a user."},
        {"id": "FR-002", "description": "The system must validate the user email."},
        {"id": "FR-003", "description": "The system must validate the user password."},
        {"id": "FR-004", "description": "The system must validate the user credentials."},
    ],
    "user_roles": ["Registered User"],
}

# Real confirmed CRUD/step over-fragmentation: three parallel "Validate X"
# included use cases under one main use case -- must fail quality validation.
FRAGMENTED_SPECIFICATION = {
    "system_boundary": "Login",
    "diagram_title": "Login Use Case Diagram",
    "actors": [{"name": "Registered User", "type": "primary"}],
    "use_cases": [
        {"name": "Login", "type": "main", "related_requirements": ["FR-001"]},
        {"name": "Validate Email", "type": "included", "related_requirements": ["FR-002"]},
        {"name": "Validate Password", "type": "included", "related_requirements": ["FR-003"]},
        {"name": "Validate Credentials", "type": "included", "related_requirements": ["FR-004"]},
    ],
}

# A corrected specification that merges the three fragmented steps into one
# genuine, non-fragmented included use case -- what a successful repair call
# should return.
REPAIRED_SPECIFICATION = {
    "system_boundary": "Login",
    "diagram_title": "Login Use Case Diagram",
    "actors": [{"name": "Registered User", "type": "primary"}],
    "use_cases": [
        {"name": "Login", "type": "main", "related_requirements": ["FR-001"]},
        {
            "name": "Authenticate Credentials",
            "type": "included",
            "related_requirements": ["FR-002", "FR-003", "FR-004"],
        },
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
        "usecase_specification_json": specification,
    }


@pytest.mark.asyncio
async def test_repair_fixes_fragmentation_on_first_attempt(agent, agent_input):
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=json.dumps(REPAIRED_SPECIFICATION))

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_usecase_model(
            agent_input, _parsed_with_specification(dict(FRAGMENTED_SPECIFICATION))
        )

    # Exactly one repair call -- the repaired specification passed validation
    # immediately, no need for a second attempt.
    assert provider.invoke_agent.await_count == 1

    names = [uc["name"] for uc in parsed["usecase_json"]["use_cases"]]
    assert "Authenticate Credentials" in names
    assert "Validate Email" not in names
    assert "Validate Password" not in names

    # Final model must pass the real validator with no errors.
    agent.usecase_validator.validate(
        SRS, parsed["architecture_plan_json"], parsed["usecase_analysis_json"], parsed["usecase_json"]
    )


@pytest.mark.asyncio
async def test_repair_never_succeeds_falls_through_without_raising(agent, agent_input):
    provider = MagicMock()
    # Every repair call returns unparseable output -- _repair_usecase_specification
    # returns None on the very first attempt, so the loop breaks immediately.
    provider.invoke_agent = AsyncMock(return_value="not json at all")

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_usecase_model(
            agent_input, _parsed_with_specification(dict(FRAGMENTED_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == 1
    # Still returns the (still-fragmented) best-effort model -- never raises
    # for a quality failure; the outer _validate_full_output ladder is the
    # one that decides what happens next.
    assert parsed["usecase_json"]["use_cases"]


@pytest.mark.asyncio
async def test_repair_keeps_retrying_up_to_max_attempts_when_still_invalid(agent, agent_input):
    provider = MagicMock()
    # Parses fine every time, but never actually fixes the fragmentation --
    # the loop should retry up to MAX_USECASE_REPAIR_ATTEMPTS times, then
    # give up gracefully rather than looping forever.
    provider.invoke_agent = AsyncMock(return_value=json.dumps(FRAGMENTED_SPECIFICATION))

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_usecase_model(
            agent_input, _parsed_with_specification(dict(FRAGMENTED_SPECIFICATION))
        )

    assert provider.invoke_agent.await_count == MAX_USECASE_REPAIR_ATTEMPTS
    assert parsed["usecase_json"]["use_cases"]


@pytest.mark.asyncio
async def test_repair_loop_is_skipped_entirely_for_the_true_fallback_rung(agent, agent_input):
    """
    When the specification is genuinely empty (every generation rung
    including repair already failed), _complete_usecase_model must not make
    any new LLM call -- that rung's whole purpose is "the LLM already
    failed", so a repair call there would defeat the point.
    """
    provider = MagicMock()
    provider.invoke_agent = AsyncMock()

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        parsed = await agent._complete_usecase_model(agent_input, _parsed_with_specification({}))

    provider.invoke_agent.assert_not_awaited()
    assert parsed["usecase_json"]["use_cases"]
