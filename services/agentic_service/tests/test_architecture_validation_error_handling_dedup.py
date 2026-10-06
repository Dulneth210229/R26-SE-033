"""
Unit tests for a real, reported bug: the deterministic Architecture Plan
fallback's Validation Plan and Error Handling Plan sections rendered as
near-duplicates -- the same rule text repeated as both the "rule" and the
"condition," and one hardcoded "handling" sentence identical for every row.
No LLM involved: these are pure functions over hand-built fixtures.
"""

import pytest

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.schemas import ArchitectureAgentInput

SRS = {
    "feature_name": "Login and Signup",
    "functional_requirements": [
        {"id": "FR-001", "description": "Users can sign up with an email and password."},
    ],
    "acceptance_criteria": [
        {"id": "AC-001", "description": "A confirmation is shown after signup."},
    ],
    "validation_rules": [
        {"id": "VR-001", "description": "Email must be in a valid format."},
        {"id": "VR-002", "description": "Password must meet minimum strength requirements."},
    ],
    "non_functional_requirements": [],
    "api_expectations": [
        {"endpoint": "/api/signup", "method": "POST", "payload": "Create an account"},
    ],
    "input_requirements": [
        {"field": "email", "type": "string", "description": "User email"},
    ],
    "output_requirements": [
        {"field": "user", "type": "object", "description": "The created user"},
    ],
    "data_requirements": [
        {"data_point": "User", "description": "Stores email, password hash, created date"},
    ],
    "ui_expectations": [],
    "user_roles": ["Visitor"],
}

PROJECT = {"project_id": "proj_test", "project_name": "Finodil", "target_stack": "Next.js"}
FEATURE = {"feature_id": "feature_test", "feature_name": "Login and Signup"}


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


def test_error_handling_condition_does_not_repeat_the_validation_rule_text(fallback_plan):
    design_views = fallback_plan["design_views"]
    data_rules = {
        item["rule_id"]: item["rule"]
        for item in design_views["data_view"]["data_validation_rules"]
    }
    validation_errors = {
        item["source_id"]: item for item in design_views["error_handling_view"]["validation_errors"]
    }

    assert data_rules["VR-001"] == "Email must be in a valid format."
    assert validation_errors["VR-001"]["condition"] != data_rules["VR-001"]
    assert "Email must be in a valid format" not in validation_errors["VR-001"]["condition"]


def test_error_handling_handling_is_not_identical_across_different_rules(fallback_plan):
    validation_errors = fallback_plan["design_views"]["error_handling_view"]["validation_errors"]
    assert len(validation_errors) == 2

    handling_texts = [item["handling"] for item in validation_errors]
    assert handling_texts[0] != handling_texts[1]
    for item in validation_errors:
        assert item["source_id"] in item["handling"]


def test_error_handling_describes_response_behavior_not_a_restated_rule(fallback_plan):
    validation_errors = fallback_plan["design_views"]["error_handling_view"]["validation_errors"]
    for item in validation_errors:
        assert "400" in item["handling"]
        assert "reject" in item["handling"].lower() or "do not process" in item["handling"].lower()


def test_validation_plan_no_longer_duplicates_error_handling_view(fallback_plan):
    validation_plan = fallback_plan["validation_plan"]
    error_handling_view = fallback_plan["design_views"]["error_handling_view"]

    assert validation_plan["processing_validation"] != error_handling_view["validation_errors"]
    assert validation_plan["processing_validation"] == validation_plan["input_validation"]
