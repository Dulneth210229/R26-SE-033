"""
Unit tests for DomainEnhancedSRSMarkdownBuilder.

Pure Python, no LLM calls. Proves the human-visible "what changed" contract:
domain-added items are tagged [DOMAIN ADDED], domain-enriched items are
tagged [DOMAIN ENHANCED] and show their original wording, and a trailing
enrichment summary section is always present.
"""

from app.agents.domain_agent.markdown_builder import DomainEnhancedSRSMarkdownBuilder

BASE_ENHANCED_SRS = {
    "feature_name": "Login",
    "project_id": "proj_1",
    "project_name": "TaskFlow",
    "project_type": "E-commerce",
    "feature_id": "feature_1",
    "target_stack": "MERN",
    "architectural_style": "modular",
    "business_goal": "Allow users to log in securely.",
}


def _builder():
    return DomainEnhancedSRSMarkdownBuilder()


def test_domain_added_item_is_tagged_and_cited():
    enhanced = dict(BASE_ENHANCED_SRS)
    enhanced["functional_requirements"] = [
        {
            "id": "FR-DOM-001",
            "description": "Lock the account after 5 failed attempts.",
            "origin": "domain_agent",
            "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
        }
    ]

    improvements = {"summary": "", "additions": [], "modifications": [], "knowledge_sources_used": [], "no_changes_note": None}

    markdown = _builder().build(enhanced, improvements)

    assert "[DOMAIN ADDED]" in markdown
    assert "FR-DOM-001" in markdown
    assert "auth.txt" in markdown


def test_domain_enhanced_item_shows_original_wording():
    enhanced = dict(BASE_ENHANCED_SRS)
    enhanced["acceptance_criteria"] = [
        {
            "id": "AC-001",
            "description": "Enriched wording with domain detail.",
            "modified_by_domain_agent": True,
            "original_description": "Original plain wording.",
            "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
        }
    ]

    improvements = {"summary": "", "additions": [], "modifications": [], "knowledge_sources_used": [], "no_changes_note": None}

    markdown = _builder().build(enhanced, improvements)

    assert "[DOMAIN ENHANCED]" in markdown
    assert "Original plain wording." in markdown
    assert "Enriched wording with domain detail." in markdown


def test_untouched_item_has_no_domain_tag():
    enhanced = dict(BASE_ENHANCED_SRS)
    enhanced["functional_requirements"] = [{"id": "FR-001", "description": "Users can log in."}]

    improvements = {"summary": "", "additions": [], "modifications": [], "knowledge_sources_used": [], "no_changes_note": None}

    markdown = _builder().build(enhanced, improvements)

    # The intro paragraph always explains the tag convention in prose, so check the
    # requirement line itself rather than a bare substring search over the whole doc.
    assert "- **FR-001**: Users can log in." in markdown
    assert "- **FR-001** **[DOMAIN ADDED]**" not in markdown
    assert "- **FR-001** **[DOMAIN ENHANCED]**" not in markdown


def test_enrichment_summary_section_is_always_present():
    enhanced = dict(BASE_ENHANCED_SRS)
    improvements = {"summary": "", "additions": [], "modifications": [], "knowledge_sources_used": [], "no_changes_note": None}

    markdown = _builder().build(enhanced, improvements)

    assert "Domain Agent Enrichment Summary" in markdown


def test_no_changes_note_is_rendered():
    enhanced = dict(BASE_ENHANCED_SRS)
    improvements = {
        "summary": "",
        "additions": [],
        "modifications": [],
        "knowledge_sources_used": [],
        "no_changes_note": "No relevant domain knowledge was retrieved for this feature.",
    }

    markdown = _builder().build(enhanced, improvements)

    assert "No relevant domain knowledge was retrieved for this feature." in markdown
