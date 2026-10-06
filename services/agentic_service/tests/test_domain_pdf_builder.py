"""
Tests for app.agents.domain_agent.pdf_builder.build_enhanced_srs_html --
confirms the shared SRS-shaped sections render, plus the Domain Agent-specific
highlighting (a domain-added plain-list entry gets a visible badge) and the
trailing Domain Improvements section.
"""

from app.agents.domain_agent.pdf_builder import build_enhanced_srs_html

ENHANCED_SRS_FIXTURE = {
    "feature_name": "Login",
    "project_id": "proj_1",
    "project_name": "Sample Project",
    "project_type": "SaaS",
    "feature_id": "feature_1",
    "target_stack": "Next.js",
    "architectural_style": "modular",
    "business_goal": "Let users log in securely.",
    "scope": ["Email/password login"],
    "out_of_scope": [],
    "user_roles": ["Customer"],
    "functional_requirements": [
        {"id": "FR-001", "description": "User can log in with email and password", "priority": "high"},
        {
            "id": "FR-DOM-001",
            "description": "Account locks after 5 failed login attempts",
            "priority": "high",
            "origin": "domain_agent",
        },
    ],
    "non_functional_requirements": [],
    "user_stories": [],
    "acceptance_criteria": [],
    "input_requirements": [],
    "output_requirements": [],
    "ui_expectations": [],
    "api_expectations": [],
    "data_requirements": ["items table: id, name, price, stock, quantity"],
    "validation_rules": [],
    "constraints": [],
    "assumptions": [],
    "risks": [],
    "dependencies": [],
    "traceability": [],
}

DOMAIN_IMPROVEMENTS_FIXTURE = {
    "summary": "Added account lockout and a data schema based on domain knowledge.",
    "additions": [
        {
            "new_id": "FR-DOM-001",
            "target_section": "functional_requirements",
            "description": "Account locks after 5 failed login attempts",
            "rationale": "Prevents brute-force attacks.",
        },
        {
            "new_id": "DR-DOM-001",
            "target_section": "data_requirements",
            "description": "items table: id, name, price, stock, quantity",
            "rationale": "Human-provided schema.",
        },
    ],
    "modifications": [],
    "knowledge_sources_used": [{"source_document": "auth_security.txt", "chunks_used": 2}],
}


def test_build_enhanced_srs_html_contains_shared_srs_sections():
    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, DOMAIN_IMPROVEMENTS_FIXTURE)

    for heading in [
        "Project Information", "Business Goal", "Scope", "Functional Requirements",
        "Data Requirements", "Requirement Traceability Summary",
        "Domain Agent Enrichment Summary", "Human Approval Note",
    ]:
        assert heading in html


def test_build_enhanced_srs_html_highlights_domain_added_plain_list_entry():
    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, DOMAIN_IMPROVEMENTS_FIXTURE)

    assert "items table: id, name, price, stock, quantity" in html
    assert "Domain Added" in html


def test_build_enhanced_srs_html_tags_domain_added_functional_requirement():
    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, DOMAIN_IMPROVEMENTS_FIXTURE)

    assert "FR-DOM-001" in html
    assert "Account locks after 5 failed login attempts" in html


def test_build_enhanced_srs_html_renders_enrichment_summary_content():
    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, DOMAIN_IMPROVEMENTS_FIXTURE)

    assert "Added account lockout and a data schema based on domain knowledge." in html
    assert "auth_security.txt" in html
    assert "Prevents brute-force attacks." in html


def test_build_enhanced_srs_html_handles_missing_domain_improvements():
    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, None)

    assert "No domain enrichment was applied to this SRS." in html
    assert html.startswith("<!DOCTYPE html>")


def test_build_enhanced_srs_html_includes_downloaded_date_and_sign_off_section():
    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, DOMAIN_IMPROVEMENTS_FIXTURE)

    assert "Downloaded On:" in html
    assert "Document Sign-Off" in html


def test_build_enhanced_srs_html_keeps_a_single_sentence_business_goal_as_a_plain_paragraph():
    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, DOMAIN_IMPROVEMENTS_FIXTURE)

    assert '<p class="section-body">Let users log in securely.</p>' in html


def test_build_enhanced_srs_html_bullets_a_multi_sentence_enrichment_summary():
    improvements = {
        **DOMAIN_IMPROVEMENTS_FIXTURE,
        "summary": "Added account lockout for security. Added a real data schema. Both come from domain knowledge.",
    }

    html = build_enhanced_srs_html(ENHANCED_SRS_FIXTURE, improvements)

    assert "<li>Added account lockout for security.</li>" in html
    assert "<li>Added a real data schema.</li>" in html
    assert "<li>Both come from domain knowledge.</li>" in html
