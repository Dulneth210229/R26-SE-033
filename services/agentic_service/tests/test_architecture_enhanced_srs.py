"""
Unit tests for Milestone 4 of the Architecture Agent upgrade.

Input side: when the Domain Agent's Enhanced SRS exists it must be the SOLE
requirements source shown to the model -- the plain SRS body must be absent
from the prompt entirely (previously both were sent). Output side: the Coder
Agent's planner prompt must render the architecture plan's
implementation_plan section when present, and omit it gracefully for legacy
plans that predate it. No LLM involved.
"""

from app.agents.architecture_agent.prompt import (
    build_agentic_architecture_user_prompt,
    build_architecture_user_prompt,
)
from app.agents.coder_agent.prompt import build_code_planner_user_prompt

PLAIN_SRS = {
    "functional_requirements": [
        {"id": "FR-001", "description": "PLAIN_SRS_ONLY_MARKER users can log in"},
    ],
}

ENHANCED_SRS = {
    "functional_requirements": [
        {"id": "FR-001", "description": "ENHANCED_SRS_MARKER users can log in with domain rules"},
    ],
}


def test_enhanced_srs_supersedes_plain_srs_in_the_prompt():
    prompt = build_architecture_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Login"},
        srs_json=PLAIN_SRS,
        enhanced_srs_json=ENHANCED_SRS,
    )

    assert "ENHANCED_SRS_MARKER" in prompt
    assert "PLAIN_SRS_ONLY_MARKER" not in prompt
    assert "SUPERSEDES" in prompt


def test_plain_srs_is_used_when_no_enhanced_srs_exists():
    prompt = build_architecture_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Login"},
        srs_json=PLAIN_SRS,
        enhanced_srs_json=None,
    )

    assert "PLAIN_SRS_ONLY_MARKER" in prompt
    assert "No approved Enhanced SRS is available." in prompt


def test_agentic_prompt_inherits_the_same_exclusivity():
    prompt = build_agentic_architecture_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Login"},
        srs_json=PLAIN_SRS,
        enhanced_srs_json=ENHANCED_SRS,
    )

    assert "ENHANCED_SRS_MARKER" in prompt
    assert "PLAIN_SRS_ONLY_MARKER" not in prompt


ARCHITECTURE_PLAN_WITH_IMPLEMENTATION = {
    "design_views": {
        "interface_view": {"api_endpoints": [{"endpoint": "/api/task-comments"}]},
        "data_view": {"data_entities": [{"name": "Comment"}]},
    },
    "implementation_plan": {
        "backend": {"files": [{"path": "server/src/routes/task-comments.routes.js"}]},
        "frontend": {"pages": [{"path": "client/src/pages/TaskCommentsPage.jsx"}]},
        "implementation_order": ["IMPLEMENTATION_ORDER_MARKER step one"],
        "constraints": ["c"],
    },
}

LEGACY_PLAN_WITHOUT_IMPLEMENTATION = {
    "design_views": {
        "interface_view": {"api_endpoints": [{"endpoint": "/api/auth/login"}]},
        "data_view": {"data_entities": [{"name": "UserCredentials"}]},
    },
}


def _coder_prompt(architecture_plan_json):
    return build_code_planner_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Task Comments"},
        srs_json={"functional_requirements": []},
        architecture_plan_json=architecture_plan_json,
        ui_integration_manifest_json=None,
        project_manifest_json={},
        human_comment=None,
    )


def test_coder_planner_prompt_renders_the_implementation_plan():
    prompt = _coder_prompt(ARCHITECTURE_PLAN_WITH_IMPLEMENTATION)

    assert "Architecture implementation plan" in prompt
    assert "IMPLEMENTATION_ORDER_MARKER" in prompt
    assert "blueprint your code plan must realize" in prompt


def test_coder_planner_prompt_omits_the_section_for_legacy_plans():
    prompt = _coder_prompt(LEGACY_PLAN_WITHOUT_IMPLEMENTATION)

    assert "Architecture implementation plan" not in prompt
