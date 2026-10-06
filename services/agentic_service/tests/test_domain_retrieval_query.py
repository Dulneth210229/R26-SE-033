"""
Unit tests for DomainAgent._build_retrieval_query.

Pure Python, no embedding calls. Proves the query is built from dense,
domain-relevant prose fields only (feature name, business goal, scope,
FR/AC descriptions) and excludes low-signal fields (NFRs, constraints).
"""

from app.agents.domain_agent.agent import RETRIEVAL_QUERY_MAX_CHARS, DomainAgent

SRS_JSON = {
    "feature_name": "Checkout",
    "business_goal": "Allow users to complete a purchase.",
    "scope": ["Cart and payment flow"],
    "functional_requirements": [{"id": "FR-001", "description": "FR_MARKER user pays with a card."}],
    "acceptance_criteria": [{"id": "AC-001", "description": "AC_MARKER order is confirmed."}],
    "non_functional_requirements": [{"id": "NFR-001", "description": "NFR_MARKER_SHOULD_NOT_APPEAR"}],
    "constraints": ["CONSTRAINT_MARKER_SHOULD_NOT_APPEAR"],
}


def test_query_includes_dense_prose_fields():
    agent = DomainAgent()

    query = agent._build_retrieval_query(SRS_JSON)

    assert "Checkout" in query
    assert "Allow users to complete a purchase." in query
    assert "Cart and payment flow" in query
    assert "FR_MARKER" in query
    assert "AC_MARKER" in query


def test_query_excludes_nfrs_and_constraints():
    agent = DomainAgent()

    query = agent._build_retrieval_query(SRS_JSON)

    assert "NFR_MARKER_SHOULD_NOT_APPEAR" not in query
    assert "CONSTRAINT_MARKER_SHOULD_NOT_APPEAR" not in query


def test_query_appends_extra_text_for_revision():
    agent = DomainAgent()

    query = agent._build_retrieval_query(SRS_JSON, extra_text="REVISION_MARKER add mfa")

    assert "REVISION_MARKER" in query


def test_query_is_capped_to_max_chars():
    agent = DomainAgent()
    huge_srs = {
        "feature_name": "x" * 5000,
        "business_goal": "",
        "scope": [],
        "functional_requirements": [],
        "acceptance_criteria": [],
    }

    query = agent._build_retrieval_query(huge_srs)

    assert len(query) <= RETRIEVAL_QUERY_MAX_CHARS
