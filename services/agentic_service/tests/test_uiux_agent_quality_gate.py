"""
Agent-level tests for UIUXAgent._generate_component_with_quality_gate -- the bounded, targeted
repair loop that sits between component_generator.generate() and a component being accepted as
done. Mocks UIUXAgent.component_generator directly (no real LLM/HTTP) so these run fast and
deterministically, matching this project's established mock-provider convention for agent-level
tests (see e.g. test_architecture_agent_revision_ladder.py).
"""

from unittest.mock import AsyncMock

import pytest

from app.agents.uiux_agent.agent import UIUXAgent
from app.agents.uiux_agent.component_generator import ComponentGenerationError
from app.agents.uiux_agent.schemas import UIUXAgentInput

PAGE_METADATA = {"page_id": "item-listing-page", "name": "Item Listing Page", "states": ["idle", "loading", "error", "success"]}
COMPONENT_METADATA = {"name": "ItemListingTable", "content_elements": ["item name", "item price"]}


@pytest.fixture
def agent():
    return UIUXAgent()


@pytest.fixture
def agent_input():
    return UIUXAgentInput(
        project={"project_id": "proj_qgtest", "project_name": "QualityGateTest"},
        feature={"feature_id": "feature_qgtest", "feature_name": "Item Listing"},
        srs_json={},
        architecture_plan_json={"design_views": {"data_view": {"data_entities": []}}},
        design_system_json={},
    )


@pytest.mark.asyncio
async def test_component_passing_gate_on_first_try_needs_no_repair(agent, agent_input):
    agent.component_generator.generate = AsyncMock(
        return_value=({"html_code": "<table><tr><td>Wireless Mouse</td></tr></table>"}, "raw")
    )
    agent.component_generator.repair = AsyncMock()

    html = await agent._generate_component_with_quality_gate(agent_input, PAGE_METADATA, COMPONENT_METADATA, [])

    assert html == "<table><tr><td>Wireless Mouse</td></tr></table>"
    agent.component_generator.repair.assert_not_awaited()


@pytest.mark.asyncio
async def test_component_failing_once_then_passing_gets_repaired(agent, agent_input):
    agent.component_generator.generate = AsyncMock(
        return_value=({"html_code": "<p>No data available</p>"}, "raw")
    )
    agent.component_generator.repair = AsyncMock(
        return_value=({"html_code": "<table><tr><td>Wireless Mouse</td></tr></table>"}, "repaired")
    )

    html = await agent._generate_component_with_quality_gate(agent_input, PAGE_METADATA, COMPONENT_METADATA, [])

    assert html == "<table><tr><td>Wireless Mouse</td></tr></table>"
    assert agent.component_generator.repair.await_count == 1


@pytest.mark.asyncio
async def test_component_failing_every_repair_attempt_raises(agent, agent_input):
    agent.component_generator.generate = AsyncMock(
        return_value=({"html_code": "<p>Unknown state.</p>"}, "raw")
    )
    agent.component_generator.repair = AsyncMock(
        return_value=({"html_code": "<p>No data available</p>"}, "still broken")
    )

    with pytest.raises(ComponentGenerationError):
        await agent._generate_component_with_quality_gate(agent_input, PAGE_METADATA, COMPONENT_METADATA, [])

    assert agent.component_generator.repair.await_count == agent.MAX_CONTENT_QUALITY_REPAIR_ATTEMPTS
