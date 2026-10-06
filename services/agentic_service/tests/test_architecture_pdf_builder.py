"""
Tests for app.agents.architecture_agent.pdf_builder.build_architecture_plan_html
-- string-presence assertions against a hand-built fixture Architecture Plan,
confirming Implementation Plan/Coder Implementation Tasks/Traceability tables
render with real content, not a JSON dump.
"""

from app.agents.architecture_agent.pdf_builder import build_architecture_plan_html

ARCHITECTURE_PLAN_FIXTURE = {
    "document_control": {
        "document_title": "Login Architecture Plan",
        "feature_name": "Login",
        "project_name": "Sample Project",
        "target_stack": "Next.js",
        "version": "v1",
        "approval_status": "pending",
    },
    "feature_overview": {
        "business_goal": "Let users log in securely.",
        "scope": ["Email/password login"],
        "out_of_scope": ["Social login"],
        "user_roles": ["Customer"],
        "feature_boundary": "Login only, not registration.",
    },
    "requirement_interpretation": {
        "functional_requirements": ["FR-001 interpreted as a login endpoint."],
        "acceptance_criteria": [],
        "validation_rules": [],
        "non_functional_requirements": [],
    },
    "architecture_approach": {
        "architecture_style": "layered",
        "architecture_rationale": "Simple and testable.",
        "frontend_overview": "A login page.",
        "backend_overview": "One auth route.",
        "data_overview": "One users collection.",
        "integration_overview": "None.",
        "design_tradeoffs": [],
    },
    "frontend_architecture_plan": {},
    "backend_architecture_plan": {},
    "implementation_plan": {
        "backend": {
            "files": [
                {"path": "app/api/auth/login/route.ts", "action": "create", "purpose": "Login endpoint"},
            ],
            "endpoints": [
                {
                    "method": "POST",
                    "path": "/api/auth/login",
                    "request_body": [{"field": "email", "type": "string", "required": True}],
                    "response": "{ token: string }",
                    "error_cases": ["401 invalid credentials"],
                },
            ],
            "models": [
                {"name": "User", "file": "models/User.ts", "fields": [{"name": "email", "type": "string"}]},
            ],
        },
        "frontend": {
            "pages": [{"path": "app/login/page.tsx", "route": "/login", "purpose": "Login page"}],
            "components_to_reuse": [],
            "services": [],
            "routing": {"new_routes": [], "nav_links": []},
        },
        "implementation_order": ["Create User model", "Create login route", "Create login page"],
        "constraints": ["Use bcrypt for password hashing"],
    },
    "design_views": {
        "interface_view": {
            "api_endpoints": [
                {
                    "method": "POST",
                    "endpoint": "/api/auth/login",
                    "purpose": "Authenticate a user",
                    "request_model": "LoginRequest",
                    "success_response_model": "LoginResponse",
                    "related_requirements": ["FR-001"],
                },
            ],
            "request_models": [],
            "response_models": [],
        },
        "data_view": {
            "data_entities": [
                {"name": "User", "purpose": "A registered user", "fields": ["email", "password_hash"]},
            ],
            "storage_rules": [],
            "data_validation_rules": [],
        },
    },
    "validation_plan": {"input_validation": [], "processing_validation": []},
    "coder_implementation_tasks": [
        {
            "task_id": "TASK-001",
            "task": "Implement login route",
            "layer": "backend",
            "suggested_files": ["app/api/auth/login/route.ts"],
        },
    ],
    "traceability_matrix": [
        {
            "source_id": "FR-001",
            "source_type": "functional_requirement",
            "architecture_plan_section": "Implementation Plan",
            "design_element": "login route",
            "coverage_status": "covered",
        },
    ],
    "assumptions": ["Users already have accounts"],
    "constraints": ["Must use Next.js"],
    "risks": [],
    "dependencies": [],
    "human_approval_note": "Review before proceeding.",
}


def test_build_architecture_plan_html_contains_every_expected_section_heading():
    html = build_architecture_plan_html(ARCHITECTURE_PLAN_FIXTURE)

    for heading in [
        "Document Control", "Feature Overview", "Requirement Interpretation",
        "Architecture Approach", "Frontend Architecture Plan", "Backend Architecture Plan",
        "End-to-End Implementation Plan", "API and Interface Plan", "Data Model Plan",
        "Validation Plan", "Error Handling Plan", "Security Plan", "Quality / NFR Plan",
        "Coder Implementation Tasks", "Requirement-to-Architecture Traceability",
        "Assumptions, Constraints, Risks, and Dependencies", "Human Approval Note",
    ]:
        assert heading in html


def test_build_architecture_plan_html_renders_implementation_plan_tables():
    html = build_architecture_plan_html(ARCHITECTURE_PLAN_FIXTURE)

    assert "<table" in html
    assert "app/api/auth/login/route.ts" in html
    assert "POST /api/auth/login" in html
    assert "Create User model" in html


def test_build_architecture_plan_html_renders_coder_tasks_and_traceability_tables():
    html = build_architecture_plan_html(ARCHITECTURE_PLAN_FIXTURE)

    assert "TASK-001" in html
    assert "Implement login route" in html
    assert "FR-001" in html
    assert "covered" in html


def test_build_architecture_plan_html_renders_data_entities_table():
    html = build_architecture_plan_html(ARCHITECTURE_PLAN_FIXTURE)

    assert "User" in html
    assert "A registered user" in html


def test_build_architecture_plan_html_never_renders_a_raw_python_dict_repr():
    # Real, live-found bug: a dict-shaped error_case/field entry (e.g. {"source_id": "VR-001",
    # "condition": ..., "handling": ...}) rendered as Python's own repr ("{'source_id': ...}")
    # instead of readable text, via a plain str(item) call on a value that can be a dict.
    fixture = {
        **ARCHITECTURE_PLAN_FIXTURE,
        "implementation_plan": {
            **ARCHITECTURE_PLAN_FIXTURE["implementation_plan"],
            "backend": {
                **ARCHITECTURE_PLAN_FIXTURE["implementation_plan"]["backend"],
                "endpoints": [
                    {
                        "method": "POST",
                        "path": "/api/auth/login",
                        "request_body": [],
                        "response": "ok",
                        "error_cases": [
                            {"source_id": "VR-001", "condition": "Email must be valid.", "handling": "Return 400."},
                        ],
                    },
                ],
            },
        },
        "design_views": {
            **ARCHITECTURE_PLAN_FIXTURE["design_views"],
            "interface_view": {
                "api_endpoints": [],
                "request_models": [
                    {
                        "name": "LoginRequest",
                        "fields": [{"name": "email", "type": "string", "required": True}],
                        "related_requirements": [],
                    },
                ],
                "response_models": [],
            },
        },
    }

    html = build_architecture_plan_html(fixture)

    assert "{'" not in html
    assert "source_id: VR-001" in html
    assert "name: email" in html


def test_build_architecture_plan_html_is_a_complete_self_contained_document():
    html = build_architecture_plan_html(ARCHITECTURE_PLAN_FIXTURE)

    assert html.startswith("<!DOCTYPE html>")
    assert "<style>" in html
    assert "Login" in html


def test_build_architecture_plan_html_includes_downloaded_date_and_sign_off_section():
    html = build_architecture_plan_html(ARCHITECTURE_PLAN_FIXTURE)

    assert "Downloaded On:" in html
    assert "Document Sign-Off" in html


def test_build_architecture_plan_html_keeps_a_single_sentence_business_goal_as_a_plain_paragraph():
    html = build_architecture_plan_html(ARCHITECTURE_PLAN_FIXTURE)

    assert '<p class="section-body">Let users log in securely.</p>' in html


def test_build_architecture_plan_html_keeps_architecture_style_as_a_plain_paragraph_even_when_multi_sentence():
    # Architecture Style is a short label field, deliberately never smart-bulleted.
    fixture = {
        **ARCHITECTURE_PLAN_FIXTURE,
        "architecture_approach": {
            **ARCHITECTURE_PLAN_FIXTURE["architecture_approach"],
            "architecture_style": "Layered. Modular. Testable.",
        },
    }

    html = build_architecture_plan_html(fixture)

    assert '<p class="section-body">Layered. Modular. Testable.</p>' in html


def test_build_architecture_plan_html_bullets_a_multi_sentence_architecture_rationale():
    fixture = {
        **ARCHITECTURE_PLAN_FIXTURE,
        "architecture_approach": {
            **ARCHITECTURE_PLAN_FIXTURE["architecture_approach"],
            "architecture_rationale": "Keeps concerns separated. Easier to test each layer. Scales well for this team.",
        },
    }

    html = build_architecture_plan_html(fixture)

    assert "<li>Keeps concerns separated.</li>" in html
    assert "<li>Easier to test each layer.</li>" in html
    assert "<li>Scales well for this team.</li>" in html
