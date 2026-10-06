"""
Tests for app.agents.requirement_agent.pdf_builder.build_srs_html -- string-
presence assertions against a hand-built fixture SRS, confirming the expected
section headings/table headers/content render, and that this is a real table
(not a JSON dump).
"""

from app.agents.requirement_agent.pdf_builder import build_srs_html

SRS_FIXTURE = {
    "feature_name": "Login",
    "project_id": "proj_1",
    "project_name": "Sample Project",
    "project_type": "SaaS",
    "feature_id": "feature_1",
    "target_stack": "Next.js",
    "architectural_style": "modular",
    "business_goal": "Let users log in securely.",
    "scope": ["Email/password login"],
    "out_of_scope": ["Social login"],
    "user_roles": ["Customer"],
    "functional_requirements": [
        {"id": "FR-001", "description": "User can log in with email and password", "priority": "high"},
    ],
    "non_functional_requirements": [
        {"id": "NFR-001", "description": "Login must respond within 1 second", "priority": "medium"},
    ],
    "user_stories": [
        {"id": "US-001", "role": "customer", "goal": "log in", "benefit": "access my account"},
    ],
    "acceptance_criteria": [
        {"id": "AC-001", "description": "Given valid credentials, login succeeds"},
    ],
    "input_requirements": ["Email address", "Password"],
    "output_requirements": ["JWT token"],
    "ui_expectations": ["A login form with email and password fields"],
    "api_expectations": ["POST /api/auth/login"],
    "data_requirements": ["users table: id, email, password_hash"],
    "validation_rules": [
        {"id": "VR-001", "description": "Email must be a valid email address"},
    ],
    "constraints": ["Must use bcrypt for password hashing"],
    "assumptions": ["Users already have an account"],
    "risks": ["Brute-force login attempts"],
    "dependencies": ["Email service"],
    "traceability": [
        {"requirement_id": "FR-001", "related_acceptance_criteria": ["AC-001"]},
    ],
}


def test_build_srs_html_contains_every_expected_section_heading():
    html = build_srs_html(SRS_FIXTURE)

    for heading in [
        "Project Information", "Business Goal", "Scope", "Out of Scope", "User Roles",
        "Functional Requirements", "Non-Functional Requirements", "User Stories",
        "Acceptance Criteria", "Input Requirements", "Output Requirements",
        "UI Expectations", "API Expectations", "Data Requirements", "Validation Rules",
        "Constraints", "Assumptions", "Risks", "Dependencies",
        "Requirement Traceability Summary", "Human Approval Note",
    ]:
        assert heading in html


def test_build_srs_html_renders_requirements_as_a_real_table_not_json():
    html = build_srs_html(SRS_FIXTURE)

    assert "<table" in html
    assert "FR-001" in html
    assert "User can log in with email and password" in html
    assert '"id"' not in html
    assert '"description"' not in html


def test_build_srs_html_renders_user_stories_and_traceability():
    html = build_srs_html(SRS_FIXTURE)

    assert "customer" in html
    assert "log in" in html
    assert "access my account" in html
    assert "AC-001" in html


def test_build_srs_html_is_a_complete_self_contained_document():
    html = build_srs_html(SRS_FIXTURE)

    assert html.startswith("<!DOCTYPE html>")
    assert "<style>" in html
    assert "Login" in html


def test_build_srs_html_includes_downloaded_date_and_sign_off_section():
    html = build_srs_html(SRS_FIXTURE)

    assert "Downloaded On:" in html
    assert "Document Sign-Off" in html
    assert "Prepared By" in html


def test_build_srs_html_keeps_a_single_sentence_business_goal_as_a_plain_paragraph():
    html = build_srs_html(SRS_FIXTURE)

    assert '<p class="section-body">Let users log in securely.</p>' in html


def test_build_srs_html_bullets_a_multi_sentence_business_goal():
    fixture = {**SRS_FIXTURE, "business_goal": "Let users log in securely. Support email and password. Lock the account after failures."}

    html = build_srs_html(fixture)

    assert html.count("<li>Let users log in securely.</li>") == 1
    assert html.count("<li>Support email and password.</li>") == 1
    assert html.count("<li>Lock the account after failures.</li>") == 1


def test_build_srs_html_does_not_false_split_on_an_abbreviation():
    fixture = {**SRS_FIXTURE, "business_goal": "Support social login, e.g. Google login, for convenience."}

    html = build_srs_html(fixture)

    assert '<p class="section-body">Support social login, e.g. Google login, for convenience.</p>' in html
