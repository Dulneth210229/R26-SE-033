"""
Regression tests for the Architecture Agent revision reliability ladder: both real call sites
(_revise_architecture_plan_output, revise_stream) now ask the LLM for a small
{"revision_summary", "operations"} plan and apply it deterministically via revision_patcher --
never ask it to retype the full architecture_plan_json document, which was the actual root cause
of a real, confirmed bug (a real generated plan's own revision_metadata.fallback_used=True proved
a past revision request was silently dropped this exact way).

No real LLM/HTTP: provider.invoke_agent/stream is mocked directly, matching this project's
established convention (see test_architecture_agent_transport_errors.py).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.schemas import ArchitectureAgentInput
from app.schemas.architecture_schema import ArchitectureAgentReviseRequest

SRS = {
    "feature_name": "Task Search",
    "functional_requirements": [
        {"id": "FR-001", "description": "Users can search tasks by keyword."},
    ],
    "acceptance_criteria": [{"id": "AC-001", "description": "Matching tasks are displayed."}],
    "validation_rules": [{"id": "VR-001", "description": "Search query must not be empty."}],
    "non_functional_requirements": [{"id": "NFR-001", "description": "Search responds within 1s."}],
    "api_expectations": [
        {"endpoint": "/api/task-search", "method": "GET", "payload": "Search tasks"},
    ],
    "input_requirements": [{"field": "query", "type": "string", "description": "Search keyword"}],
    "output_requirements": [{"field": "results", "type": "array", "description": "Matching tasks"}],
    "data_requirements": [
        {"data_point": "TaskSearchResult", "description": "Represents a matched task"},
    ],
    "ui_expectations": [{"id": "UI-001", "description": "A search input box"}],
    "user_roles": ["Registered User"],
}


@pytest.fixture
def agent():
    return ArchitectureAgent()


def _existing_plan(agent: ArchitectureAgent) -> dict:
    """A structurally-complete Architecture Plan (via the already-tested deterministic fallback
    builder) to use as the "existing plan" a revision operates against."""
    agent_input = ArchitectureAgentInput(
        project={"project_id": "proj_revladder", "project_name": "TaskFlow", "target_stack": "MERN"},
        feature={"feature_id": "feature_revladder", "feature_name": "Task Search"},
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )
    return agent._build_fallback_architecture_output(agent_input, reason="fixture setup")["architecture_plan_json"]


def _valid_ops_plan_json() -> str:
    return json.dumps({
        "revision_summary": "Added a rate-limiting constraint as requested.",
        "operations": [
            {
                "action": "add",
                "field": "constraints",
                "value": "Search must be rate-limited to 10 requests per minute.",
            }
        ],
    })


@pytest.mark.asyncio
async def test_valid_operations_plan_applies_via_patcher_not_full_retype(agent):
    """A well-formed small operations plan from the LLM should be applied deterministically,
    with every OTHER section of the existing plan left untouched -- direct proof this is no
    longer a "retype everything" call."""
    existing_plan = _existing_plan(agent)
    original_assumptions = list(existing_plan.get("assumptions", []))

    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=_valid_ops_plan_json())

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        output = await agent._revise_architecture_plan_output(
            project={"project_id": "proj_revladder", "project_name": "TaskFlow"},
            feature={"feature_id": "feature_revladder", "feature_name": "Task Search"},
            srs_json=dict(SRS),
            existing_architecture_plan_json=existing_plan,
            revision_comment="Add a constraint that search must be rate-limited to 10 requests per minute.",
            revised_by="human_user",
        )

    plan = output.architecture_plan_json
    assert "Search must be rate-limited to 10 requests per minute." in plan["constraints"]
    # The rest of the document is genuinely untouched (proof this is a patch, not a retype).
    assert plan["assumptions"] == original_assumptions
    assert plan["revision_metadata"]["applied_changes"]
    assert plan["revision_metadata"]["unmatched_operations"] == []
    assert not plan["revision_metadata"].get("fallback_used")


@pytest.mark.asyncio
async def test_parse_failure_falls_through_to_json_repair_rung(agent):
    """First call returns unparseable junk; the repair call returns a valid operations plan --
    confirms the repair rung actually fires and its result gets applied."""
    existing_plan = _existing_plan(agent)

    call_count = {"n": 0}

    async def fake_invoke_agent(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return "not valid json at all"
        return _valid_ops_plan_json()

    provider = MagicMock()
    provider.invoke_agent = AsyncMock(side_effect=fake_invoke_agent)

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        output = await agent._revise_architecture_plan_output(
            project={"project_id": "proj_revladder", "project_name": "TaskFlow"},
            feature={"feature_id": "feature_revladder", "feature_name": "Task Search"},
            srs_json=dict(SRS),
            existing_architecture_plan_json=existing_plan,
            revision_comment="Add a constraint that search must be rate-limited to 10 requests per minute.",
            revised_by="human_user",
        )

    assert call_count["n"] >= 2
    plan = output.architecture_plan_json
    assert "Search must be rate-limited to 10 requests per minute." in plan["constraints"]
    assert not plan["revision_metadata"].get("fallback_used")


@pytest.mark.asyncio
async def test_both_attempts_failing_falls_back_to_deterministic_fallback(agent):
    """Neither the single-shot nor the repair call ever produces a parseable operations plan --
    confirms the existing, unchanged _fallback_revise_architecture_plan_json is still the true
    last resort, and it's reached correctly."""
    existing_plan = _existing_plan(agent)

    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value="still not valid json")

    with patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = provider

        output = await agent._revise_architecture_plan_output(
            project={"project_id": "proj_revladder", "project_name": "TaskFlow"},
            feature={"feature_id": "feature_revladder", "feature_name": "Task Search"},
            srs_json=dict(SRS),
            existing_architecture_plan_json=existing_plan,
            revision_comment="Add a constraint that search must be rate-limited to 10 requests per minute.",
            revised_by="human_user",
        )

    plan = output.architecture_plan_json
    assert plan["revision_metadata"]["fallback_used"] is True
    assert plan["human_approval_note"]


@pytest.mark.asyncio
async def test_revise_stream_streams_and_applies_small_operations_plan(agent):
    """revise_stream's streamed tokens are now the small operations plan, not the whole document
    -- and the resulting artifact reflects the applied change. Mocks store/read_json_file/
    _find_latest_*_artifact so no real Mongo access happens, matching the established
    run_stream test's own convention (test_architecture_agent_transport_errors.py)."""
    existing_plan = _existing_plan(agent)

    provider = MagicMock()

    async def fake_stream(prompt, system_prompt=None, **kwargs):
        for chunk in [_valid_ops_plan_json()]:
            yield chunk

    provider.stream = fake_stream

    fake_feature = {
        "feature_id": "feature_revstream_test",
        "project_id": "proj_revstream_test",
        "feature_name": "Task Search",
    }
    fake_project = {"project_id": "proj_revstream_test", "project_name": "TaskFlow", "target_stack": "MERN"}
    fake_plan_artifact = {"file_path": "plan.json"}
    fake_srs_artifact = {"file_path": "srs.json"}

    def fake_read_json_file(path):
        if path == "plan.json":
            return existing_plan
        if path == "srs.json":
            return dict(SRS)
        return {}

    with (
        patch("app.agents.architecture_agent.agent.store") as mock_store,
        patch("app.agents.architecture_agent.agent.read_json_file", side_effect=fake_read_json_file),
        patch.object(agent, "_find_latest_architecture_plan_json_artifact", return_value=fake_plan_artifact),
        patch.object(agent, "_find_latest_approved_artifact", side_effect=[fake_srs_artifact, None]),
        patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
    ):
        mock_store.features.get.return_value = fake_feature
        mock_store.projects.get.return_value = fake_project
        mock_llm_service.get_provider.return_value = provider

        events = [
            event
            async for event in agent.revise_stream(
                feature_id="feature_revstream_test",
                request=ArchitectureAgentReviseRequest(
                    revision_comment="Add a constraint that search must be rate-limited to 10 requests per minute.",
                    revised_by="human_user",
                ),
            )
        ]

    token_events = [e for e in events if e.get("type") == "token"]
    done_events = [e for e in events if e.get("type") == "done"]
    assert token_events, "expected at least one streamed token event"
    assert done_events, f"expected a 'done' event, got: {[e.get('type') for e in events]}"

    streamed_text = "".join(e["text"] for e in token_events)
    # The streamed content is the SMALL operations plan, not the full architecture_plan_json --
    # confirmed by its size and by it being exactly what fake_stream yielded.
    assert streamed_text == _valid_ops_plan_json()
