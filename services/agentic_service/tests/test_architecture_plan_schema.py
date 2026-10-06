"""
Unit tests for the Architecture Plan's implementation_plan section (Milestone 1
of the Architecture Agent upgrade): the plan must always carry a concrete,
coder-executable implementation_plan -- authored by the LLM when it complies,
mechanically synthesized from design_views/SRS when it doesn't (and for every
legacy/fallback plan). No LLM involved: the deterministic fallback builder,
the synthesis helper, the validator, and the markdown builder are all pure
functions over hand-built fixtures.
"""

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.markdown_builder import ArchitecturePlanMarkdownBuilder
from app.agents.architecture_agent.schemas import ArchitectureAgentInput
from app.agents.architecture_agent.sds_validator import (
    ArchitecturePlanValidationError,
    ArchitecturePlanValidator,
)

SRS = {
    "feature_name": "Task Comments",
    "functional_requirements": [
        {"id": "FR-001", "description": "Users can add a comment to a task."},
        {"id": "FR-002", "description": "Users can view comments for a task."},
    ],
    "acceptance_criteria": [
        {"id": "AC-001", "description": "A new comment is displayed after posting."},
    ],
    "validation_rules": [
        {"id": "VR-001", "description": "Comment text must not be empty."},
    ],
    "non_functional_requirements": [
        {"id": "NFR-001", "description": "Comments load within 2 seconds."},
    ],
    "api_expectations": [
        {"endpoint": "/api/task-comments", "method": "POST", "payload": "Create a comment"},
        {"endpoint": "/api/task-comments", "method": "GET", "payload": "List comments"},
    ],
    "input_requirements": [
        {"field": "text", "type": "string", "description": "Comment body"},
    ],
    "output_requirements": [
        {"field": "comment", "type": "object", "description": "The saved comment"},
        {"field": "error_message", "type": "string", "description": "Error text"},
    ],
    "data_requirements": [
        {"data_point": "Comment", "description": "Stores comment text, author, task id, created date"},
    ],
    "ui_expectations": [
        {"id": "UI-001", "description": "A comment input box below the task details"},
    ],
    "user_roles": ["Registered User"],
}

PROJECT = {"project_id": "proj_test", "project_name": "TaskFlow", "target_stack": "Next.js"}
FEATURE = {"feature_id": "feature_test", "feature_name": "Task Comments"}


@pytest.fixture
def agent():
    return ArchitectureAgent()


@pytest.fixture
def agent_input():
    return ArchitectureAgentInput(
        project=dict(PROJECT),
        feature=dict(FEATURE),
        srs_json=dict(SRS),
        enhanced_srs_json=None,
        architecture_notes=None,
        human_comment=None,
    )


@pytest.fixture
def fallback_plan(agent, agent_input):
    parsed = agent._build_fallback_architecture_output(agent_input, reason="test")
    return parsed["architecture_plan_json"]


def test_fallback_plan_contains_a_complete_implementation_plan(fallback_plan):
    implementation_plan = fallback_plan.get("implementation_plan")

    assert isinstance(implementation_plan, dict)
    for key in ["backend", "frontend", "implementation_order", "constraints"]:
        assert key in implementation_plan, f"missing {key}"

    backend = implementation_plan["backend"]
    file_paths = [item["path"] for item in backend["files"]]
    # POST and GET /api/task-comments share the same (collection) route file --
    # no separate "mount the router" file/step exists under Next.js's
    # file-based routing.
    assert "app/api/task-comments/route.ts" in file_paths
    assert any(path.startswith("models/") for path in file_paths)

    endpoint_paths = {(item["method"], item["path"]) for item in backend["endpoints"]}
    assert ("POST", "/api/task-comments") in endpoint_paths
    assert ("GET", "/api/task-comments") in endpoint_paths

    assert backend["models"], "SRS has data requirements -- models must be planned"
    assert backend["models"][0]["file"].startswith("models/")

    frontend = implementation_plan["frontend"]
    assert frontend["pages"][0]["path"] == "app/task-comments/page.tsx"
    assert frontend["pages"][0]["route"] == "/task-comments"
    assert frontend["services"], "endpoints exist -- a service module must be planned"
    assert frontend["routing"]["new_routes"] and frontend["routing"]["nav_links"]

    assert implementation_plan["implementation_order"]
    assert not any(
        "mount" in step.lower() and "router" in step.lower()
        for step in implementation_plan["implementation_order"]
    )
    assert any("FEATURE_LINKS" in step for step in implementation_plan["implementation_order"])
    assert implementation_plan["constraints"]


def test_fallback_plan_passes_the_full_validator(agent, fallback_plan):
    ArchitecturePlanValidator().validate(SRS, fallback_plan)  # must not raise


def test_validator_rejects_a_plan_missing_the_implementation_plan(fallback_plan):
    plan = dict(fallback_plan)
    plan.pop("implementation_plan")

    with pytest.raises(ArchitecturePlanValidationError, match="implementation_plan"):
        ArchitecturePlanValidator().validate(SRS, plan)


def test_validator_rejects_empty_backend_files_when_srs_has_api_expectations(fallback_plan):
    plan = dict(fallback_plan)
    plan["implementation_plan"] = dict(plan["implementation_plan"])
    plan["implementation_plan"]["backend"] = {"files": [], "endpoints": [], "models": []}

    with pytest.raises(ArchitecturePlanValidationError, match="backend.files is empty"):
        ArchitecturePlanValidator().validate(SRS, plan)


def test_ensure_implementation_plan_synthesizes_when_llm_omitted_it(agent, fallback_plan):
    # Simulates an otherwise-valid LLM plan that skipped the new section --
    # it must be backfilled from the plan's own design_views, not rejected.
    plan = dict(fallback_plan)
    plan.pop("implementation_plan")

    agent._ensure_implementation_plan(plan, srs_json=SRS, feature_name="Task Comments")

    assert isinstance(plan["implementation_plan"], dict)
    ArchitecturePlanValidator().validate(SRS, plan)


def test_ensure_implementation_plan_keeps_a_valid_llm_authored_one(agent, fallback_plan):
    marker_plan = {
        "backend": {"files": [{"path": "custom.js"}], "endpoints": [], "models": []},
        "frontend": {"pages": [{"path": "p.jsx"}]},
        "implementation_order": ["step 1"],
        "constraints": ["c1"],
    }
    plan = dict(fallback_plan)
    plan["implementation_plan"] = marker_plan

    agent._ensure_implementation_plan(plan, srs_json=SRS, feature_name="Task Comments")

    assert plan["implementation_plan"] is marker_plan  # untouched


def test_legacy_sds_conversion_synthesizes_an_implementation_plan(agent, agent_input):
    # The live e-commerce project's plan is stored under the legacy sds type --
    # conversion must produce a plan that carries an implementation_plan too.
    base_sds = agent._build_base_design_from_srs(
        srs=SRS,
        project_id="proj_test",
        project_name="TaskFlow",
        project_type="SaaS",
        feature_id="feature_test",
        feature_name="Task Comments",
        target_stack="MERN",
        architecture_style="mvc",
        reason="test",
    )

    converted = agent._convert_sds_to_architecture_plan(sds_json=base_sds, srs_json=SRS)

    assert isinstance(converted.get("implementation_plan"), dict)
    ArchitecturePlanValidator().validate(SRS, converted)


def test_markdown_renders_the_implementation_plan_sections(fallback_plan):
    markdown = ArchitecturePlanMarkdownBuilder().build(fallback_plan)

    assert "End-to-End Implementation Plan (Coder Agent Blueprint)" in markdown
    assert "app/api/task-comments/route.ts" in markdown
    assert "Implementation Order" in markdown
    assert "POST /api/task-comments" in markdown or "/api/task-comments" in markdown
