"""
Regression tests for a real, reported bug: a transport/timeout failure from
provider.invoke_agent() itself (not just bad/unparseable content it returns) used to propagate
UNCAUGHT out of the single-shot and JSON-repair rungs, crashing the whole Architecture Agent
request. httpx.ReadTimeout (and several other httpx transport exceptions) are frequently raised
with an EMPTY str() -- which is exactly what a real user saw: a chat banner reading
"Architecture Agent failed: " with nothing after the colon, after the model had already been
generating for close to the configured timeout window.

No real LLM/HTTP: provider.invoke_agent is mocked to raise directly, standing in for a timeout
whose message happens to be empty (the worst case for this bug -- a non-empty message would have
at least been readable, just attributed to the wrong place).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.schemas import ArchitectureAgentInput

SRS = {
    "feature_name": "Task Comments",
    "functional_requirements": [
        {"id": "FR-001", "description": "Users can add a comment to a task."},
    ],
    "acceptance_criteria": [{"id": "AC-001", "description": "A new comment is displayed."}],
    "validation_rules": [{"id": "VR-001", "description": "Comment text must not be empty."}],
    "non_functional_requirements": [{"id": "NFR-001", "description": "Comments load fast."}],
    "api_expectations": [
        {"endpoint": "/api/task-comments", "method": "POST", "payload": "Create a comment"},
    ],
    "input_requirements": [{"field": "text", "type": "string", "description": "Comment body"}],
    "output_requirements": [{"field": "comment", "type": "object", "description": "Saved comment"}],
    "data_requirements": [
        {"data_point": "Comment", "description": "Stores comment text, author, task id"},
    ],
    "ui_expectations": [{"id": "UI-001", "description": "A comment input box"}],
    "user_roles": ["Registered User"],
}


@pytest.fixture
def agent():
    return ArchitectureAgent()


@pytest.fixture
def agent_input():
    return ArchitectureAgentInput(
        project={"project_id": "proj_transport_test", "project_name": "TaskFlow", "target_stack": "MERN"},
        feature={"feature_id": "feature_transport_test", "feature_name": "Task Comments"},
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )


def _mock_exploration_agent():
    """Exploration rung 'succeeds' (no exception) but never calls submit_*, so
    _generate_raw_output_via_exploration raises and the ladder falls through to single-shot --
    isolating the single-shot/repair behavior this test suite actually targets."""
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value={})
    return fake_agent


@pytest.mark.asyncio
async def test_single_shot_call_exception_falls_through_to_repair_then_fallback(agent, agent_input):
    """The FIRST invoke_agent call (single-shot generation) throwing -- not just returning bad
    content -- must not crash the request. Previously uncaught entirely."""
    captured: dict = {}
    provider = MagicMock()
    # Every call raises an exception with an EMPTY message, exactly matching a real
    # httpx.ReadTimeout's usual str() -- the worst case for this bug.
    provider.invoke_agent = AsyncMock(side_effect=Exception(""))

    with (
        patch("app.agents.architecture_agent.agent.build_architecture_planning_tools", return_value=([], captured)),
        patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
        patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
    ):
        mock_llm_service.get_provider.return_value = provider

        output = await agent._generate_architecture_output(agent_input)

    # Both the single-shot call and the repair call were attempted (and both raised) --
    # the deterministic fallback rung is what actually produced this output.
    assert provider.invoke_agent.await_count >= 2
    assert output.architecture_plan_json["implementation_plan"]
    assert output.usecase_json["actors"]


@pytest.mark.asyncio
async def test_repair_call_exception_falls_through_to_fallback(agent, agent_input):
    """The single-shot call returns unparseable junk (triggering repair) and the REPAIR call
    itself then throws -- previously uncaught, since only the repair call's OUTPUT was ever
    validated, never a failure of the call itself."""
    captured: dict = {}
    provider = MagicMock()
    call_count = {"n": 0}

    async def fake_invoke_agent(*args, **kwargs):
        call_count["n"] += 1
        # 1st call (plan single-shot) -> junk, triggers repair. 2nd call (plan repair) -> raises,
        # the exact call this test targets. Any further calls (e.g. diagram generation's own
        # focused single-shot tier, sharing this same mocked provider) get junk too, so they hit
        # their own already-tested "bad output" resilience instead of an unrelated StopIteration.
        if call_count["n"] == 2:
            raise Exception("")
        return "not valid json at all"

    provider.invoke_agent = AsyncMock(side_effect=fake_invoke_agent)

    with (
        patch("app.agents.architecture_agent.agent.build_architecture_planning_tools", return_value=([], captured)),
        patch("app.agents.architecture_agent.agent.create_agent", return_value=_mock_exploration_agent()),
        patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
    ):
        mock_llm_service.get_provider.return_value = provider

        output = await agent._generate_architecture_output(agent_input)

    # await_count is >= 2, not necessarily exactly 2 -- _complete_diagram_models' own focused
    # single-shot tier shares this same mocked provider and may make further calls; what matters
    # here is that the plan-level single-shot + repair calls both ran (and both were survived).
    assert provider.invoke_agent.await_count >= 2
    assert output.architecture_plan_json["implementation_plan"]


@pytest.mark.asyncio
async def test_revise_single_shot_call_exception_falls_back_to_revision_fallback(agent):
    """_revise_architecture_plan_output's one LLM call throwing must fall through to
    _fallback_revise_architecture_plan_json (which just carries the existing plan forward with an
    honest note), not crash the whole revision."""
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=Exception(""))

    existing_plan = agent._build_fallback_architecture_output(
        ArchitectureAgentInput(
            project={"project_id": "proj_transport_test", "project_name": "TaskFlow", "target_stack": "MERN"},
            feature={"feature_id": "feature_transport_test", "feature_name": "Task Comments"},
            srs_json=dict(SRS),
            enhanced_srs_json=None,
            architecture_notes=None,
            human_comment=None,
        ),
        reason="fixture setup",
    )["architecture_plan_json"]

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        output = await agent._revise_architecture_plan_output(
            project={"project_id": "proj_transport_test", "project_name": "TaskFlow"},
            feature={"feature_id": "feature_transport_test", "feature_name": "Task Comments"},
            srs_json=dict(SRS),
            existing_architecture_plan_json=existing_plan,
            revision_comment="Add a delete confirmation dialog.",
            revised_by="human_user",
        )

    # await_count is >= 1, not necessarily exactly 1 -- diagram regeneration (also part of a
    # revision) shares this same mocked provider and may make further calls of its own; what
    # matters here is that the revision's own single-shot call ran (and was survived).
    assert provider.invoke_agent.await_count >= 1
    assert output.architecture_plan_json["implementation_plan"]
    # The fallback honestly records that the LLM revision didn't happen, per this project's own
    # established convention (never silently discard a human's requested change).
    assert "revision_metadata" in output.architecture_plan_json or output.architecture_plan_json.get(
        "human_approval_note"
    )


@pytest.mark.asyncio
async def test_run_stream_repair_call_exception_yields_done_not_a_crash(agent):
    """run_stream is the exact code path the reported bug came through (a real streamed request
    that eventually reaches the repair rung and times out). Mocks store/read_json_file/
    project_memory_service so no real Mongo access happens; the streaming call itself succeeds
    (yields a couple tokens of unparseable text), then the repair invoke_agent call throws --
    previously uncaught, propagating out of the async generator as a bare exception the route's
    try/except then rendered as a blank "Architecture Agent failed: " message."""
    from app.schemas.architecture_schema import ArchitectureAgentRunRequest

    provider = MagicMock()

    async def fake_stream(prompt, system_prompt=None, **kwargs):
        yield "not valid json"

    provider.stream = fake_stream
    provider.invoke_agent = AsyncMock(side_effect=Exception(""))

    fake_feature = {"feature_id": "feature_run_stream_test", "project_id": "proj_run_stream_test",
                     "feature_name": "Task Comments"}
    fake_project = {"project_id": "proj_run_stream_test", "project_name": "TaskFlow", "target_stack": "MERN"}
    fake_srs_artifact = {"file_path": "unused.json"}

    with (
        patch("app.agents.architecture_agent.agent.store") as mock_store,
        patch("app.agents.architecture_agent.agent.read_json_file", return_value=dict(SRS)),
        patch("app.agents.architecture_agent.agent.project_memory_service") as mock_pm,
        patch.object(agent, "_find_latest_approved_artifact", return_value=fake_srs_artifact),
        patch.object(agent, "_load_previous_architecture_plans", return_value=[]),
        patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
    ):
        mock_store.features.get.return_value = fake_feature
        mock_store.projects.get.return_value = fake_project
        mock_pm.load_project_manifest.return_value = {}
        mock_llm_service.get_provider.return_value = provider

        events = [
            event
            async for event in agent.run_stream(
                feature_id="feature_run_stream_test", request=ArchitectureAgentRunRequest()
            )
        ]

    # The generator ran to completion (a "done" event landed) instead of raising uncaught --
    # confirming the fix at the exact real code path the reported bug went through.
    done_events = [e for e in events if e.get("type") == "done"]
    assert done_events, f"expected a 'done' event, got: {[e.get('type') for e in events]}"
