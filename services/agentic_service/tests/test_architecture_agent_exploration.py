"""
Unit tests for Milestone 3 of the Architecture Agent upgrade: the agentic,
tool-using generation rung. No real LLM: create_agent /
build_architecture_planning_tools / llm_provider_service are mocked inside
the agent's namespace (mirroring test_coder_planner_exploration.py), while
the deterministic diagram modelers, validators, markdown builder, and
fallback ladder all run for real.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.errors import GraphRecursionError

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.schemas import ArchitectureAgentInput
from app.agents.architecture_agent.tools import build_architecture_planning_tools

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
        project={"project_id": "proj_explore_test", "project_name": "TaskFlow", "target_stack": "MERN"},
        feature={"feature_id": "feature_explore_test", "feature_name": "Task Comments"},
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )


def _valid_submission(agent, agent_input) -> str:
    """A structurally-valid full submission -- the real fallback builder's plan."""
    fallback = agent._build_fallback_architecture_output(agent_input, reason="fixture")
    return json.dumps({
        "architecture_plan_json": fallback["architecture_plan_json"],
        "usecase_specification_json": {},
    }, default=str)


def _valid_sequence_submission() -> str:
    """A structurally-valid sequence_specification_json for the dedicated diagram exploration step."""
    return json.dumps({
        "diagram_title": "Task Comments Sequence Diagram",
        "participants": [
            {"name": "Registered User", "type": "actor"},
            {"name": "TaskCommentsBoundary", "type": "boundary"},
            {"name": "TaskCommentsController", "type": "control"},
        ],
        "interactions": [
            {"kind": "message", "from": "Registered User", "to": "TaskCommentsBoundary",
             "message": "Submit comment", "message_type": "sync", "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "TaskCommentsBoundary", "to": "TaskCommentsController",
             "message": "POST /api/task-comments", "message_type": "sync", "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "TaskCommentsController", "to": "TaskCommentsBoundary",
             "message": "Return saved comment", "message_type": "return", "related_requirements": ["AC-001"]},
        ],
    })


def _valid_class_submission() -> str:
    """A structurally-valid class_specification_json for the dedicated diagram exploration step."""
    return json.dumps({
        "diagram_title": "Task Comments Class Diagram",
        "classes": [
            {"name": "TaskCommentsController", "stereotype": "control",
             "operations": [{"name": "createComment", "parameters": ["request"], "return_type": "Response", "visibility": "+"}],
             "related_requirements": ["FR-001"]},
            {"name": "Comment", "stereotype": "entity",
             "attributes": [{"name": "text", "type": "String", "visibility": "-"}],
             "related_requirements": ["FR-001"]},
        ],
        "relationships": [],
    })


def _mock_exploration_agent(side_effect=None):
    fake_agent = MagicMock()
    fake_agent.ainvoke = AsyncMock(return_value={}, side_effect=side_effect)
    return fake_agent


@pytest.mark.asyncio
async def test_exploration_submission_is_used_without_any_single_shot_call(agent, agent_input):
    """
    When all three dedicated exploration steps (architecture plan, sequence
    diagram, class diagram) succeed, no single-shot LLM call of any kind is
    needed -- diagram generation is decoupled from the plan's own success
    (agent.py's _complete_diagram_models always attempts its own agentic
    tier), so this test seeds all three captured dicts to simulate all
    three exploration steps succeeding independently.
    """
    plan_captured = {"plan_json": _valid_submission(agent, agent_input)}
    sequence_captured = {"sequence_json": _valid_sequence_submission()}
    class_captured = {"class_json": _valid_class_submission()}
    single_shot_provider = MagicMock()
    single_shot_provider.invoke_agent = AsyncMock()

    with (
        patch("app.agents.architecture_agent.agent.build_architecture_planning_tools",
              return_value=([], plan_captured)),
        patch("app.agents.architecture_agent.agent.build_sequence_diagram_tools",
              return_value=([], sequence_captured)),
        patch("app.agents.architecture_agent.agent.build_class_diagram_tools",
              return_value=([], class_captured)),
        patch("app.agents.architecture_agent.agent.create_agent",
              return_value=_mock_exploration_agent()),
        patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
    ):
        mock_llm_service.get_provider.return_value = single_shot_provider

        output = await agent._generate_architecture_output(agent_input)

    assert output.architecture_plan_json["implementation_plan"]
    assert output.usecase_json["actors"]  # use case still built deterministically
    assert output.sequence_puml and output.class_puml
    single_shot_provider.invoke_agent.assert_not_awaited()  # all three exploration steps sufficed


@pytest.mark.asyncio
async def test_no_submission_falls_back_to_single_shot_ladder(agent, agent_input):
    captured: dict = {}  # exploration never calls submit_architecture_plan
    single_shot_provider = MagicMock()
    # Single-shot + repair both return junk -> deterministic fallback rung.
    single_shot_provider.invoke_agent = AsyncMock(return_value="not json at all")

    with (
        patch("app.agents.architecture_agent.agent.build_architecture_planning_tools",
              return_value=([], captured)),
        patch("app.agents.architecture_agent.agent.create_agent",
              return_value=_mock_exploration_agent()),
        patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
    ):
        mock_llm_service.get_provider.return_value = single_shot_provider

        output = await agent._generate_architecture_output(agent_input)

    # The run did NOT crash: single-shot rung was attempted, and the
    # deterministic fallback produced a complete, valid plan.
    assert single_shot_provider.invoke_agent.await_count >= 1
    assert output.architecture_plan_json["implementation_plan"]


@pytest.mark.asyncio
async def test_recursion_limit_is_a_clean_fallback_not_a_crash(agent, agent_input):
    captured: dict = {}
    single_shot_provider = MagicMock()
    single_shot_provider.invoke_agent = AsyncMock(return_value="not json at all")

    with (
        patch("app.agents.architecture_agent.agent.build_architecture_planning_tools",
              return_value=([], captured)),
        patch("app.agents.architecture_agent.agent.create_agent",
              return_value=_mock_exploration_agent(side_effect=GraphRecursionError("too long"))),
        patch("app.agents.architecture_agent.agent.get_agentic_chat_model", return_value=MagicMock()),
        patch("app.agents.architecture_agent.agent.llm_provider_service") as mock_llm_service,
    ):
        mock_llm_service.get_provider.return_value = single_shot_provider

        output = await agent._generate_architecture_output(agent_input)

    assert output.architecture_plan_json["implementation_plan"]


def test_tool_set_is_read_only_plus_submit():
    tools, captured = build_architecture_planning_tools("proj_does_not_exist", [])
    names = {t.name for t in tools}

    assert names == {
        "list_workspace_dir",
        "read_workspace_file",
        "search_workspace_code",
        "read_project_manifest",
        "read_previous_architecture_plan",
        "submit_architecture_plan",
    }
    assert "write_file" not in names and "apply_patch" not in names and "run_shell" not in names


def test_workspace_tools_degrade_gracefully_when_no_workspace_exists():
    # A project that does not exist in the store has no resolvable workspace --
    # normal for a project's first feature; must inform, never raise.
    tools, _ = build_architecture_planning_tools("proj_does_not_exist", [])
    by_name = {t.name: t for t in tools}

    assert "No workspace exists" in by_name["list_workspace_dir"].invoke({"path": "."})
    assert "No workspace exists" in by_name["read_workspace_file"].invoke({"path": "a.js"})
    assert "No workspace exists" in by_name["search_workspace_code"].invoke({"query": "express"})


def test_read_previous_architecture_plan_by_name_and_not_found():
    previous = [{
        "feature_id": "feature_x",
        "feature_name": "Login",
        "architecture_plan_json": {"design_views": {"interface_view": {"api_endpoints": []}}},
    }]
    tools, _ = build_architecture_planning_tools("proj_does_not_exist", previous)
    by_name = {t.name: t for t in tools}

    found = by_name["read_previous_architecture_plan"].invoke({"feature_name": "login"})
    assert "design_views" in found

    missing = by_name["read_previous_architecture_plan"].invoke({"feature_name": "Checkout"})
    assert "Available previous features: Login" in missing


def test_submit_architecture_plan_captures_its_argument():
    tools, captured = build_architecture_planning_tools("proj_does_not_exist", [])
    by_name = {t.name: t for t in tools}

    result = by_name["submit_architecture_plan"].invoke({"plan_json": '{"architecture_plan_json": {}}'})

    assert "submitted" in result.lower()
    assert captured["plan_json"] == '{"architecture_plan_json": {}}'
