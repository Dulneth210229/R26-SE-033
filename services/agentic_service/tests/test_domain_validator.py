"""
Unit tests for DomainEnhancementValidator.

Pure Python, no embedding/LLM calls. These tests are the enforcement proof
that Domain Agent behaves as a real RAG system: every proposed
addition/modification must cite a source among the retrieved chunks, no
enrichment may be claimed at all when retrieval returned nothing, and a
modification must reference a real, existing item ID.

Validation now happens on the LLM's small PROPOSED PLAN, before the
deterministic Python merge (see agent.py's _apply_enrichment_plan) --
earlier versions of this validator checked the already-merged output, which
became unnecessary once the merge itself started guaranteeing correctness
by construction.
"""

import pytest

from app.agents.domain_agent.domain_validator import (
    DomainEnhancementValidationError,
    DomainEnhancementValidator,
)

BASE_SRS_JSON = {
    "functional_requirements": [
        {"id": "FR-001", "description": "Users can log in with email and password."},
    ],
    "non_functional_requirements": [],
    "acceptance_criteria": [
        {"id": "AC-001", "description": "Given valid credentials, the user is logged in."},
    ],
    "validation_rules": [],
    "user_stories": [],
}

RETRIEVED_CHUNKS = [
    {"chunk_id": "auth.txt#0", "source_document": "auth.txt", "text": "Lock the account after 5 failed attempts."},
]


def _valid_addition():
    return {
        "target_section": "functional_requirements",
        "description": "Lock the account after 5 consecutive failed login attempts.",
        "priority": "Should Have",
        "rationale": "Prevent brute-force attacks.",
        "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
    }


def _valid_modification():
    return {
        "target_section": "acceptance_criteria",
        "id": "AC-001",
        "enhanced_description": "Given valid credentials and an unlocked account, the user is logged in.",
        "rationale": "Reflect the new lockout rule.",
        "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
    }


def test_valid_plan_passes():
    plan = {"additions": [_valid_addition()], "modifications": [_valid_modification()]}

    DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)


def test_invalid_target_section_on_addition_is_rejected():
    plan = {"additions": [{**_valid_addition(), "target_section": "not_a_real_section"}], "modifications": []}

    with pytest.raises(DomainEnhancementValidationError, match="invalid target_section"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)


def test_addition_missing_description_is_rejected():
    addition = _valid_addition()
    addition["description"] = "   "
    plan = {"additions": [addition], "modifications": []}

    with pytest.raises(DomainEnhancementValidationError, match="missing a non-empty description"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)


def test_modification_referencing_nonexistent_id_is_rejected():
    modification = _valid_modification()
    modification["id"] = "AC-999"
    plan = {"additions": [], "modifications": [modification]}

    with pytest.raises(DomainEnhancementValidationError, match="does not exist"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)


def test_modification_missing_enhanced_description_is_rejected():
    modification = _valid_modification()
    modification["enhanced_description"] = ""
    plan = {"additions": [], "modifications": [modification]}

    with pytest.raises(DomainEnhancementValidationError, match="missing a non-empty enhanced_description"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)


def test_citation_to_a_source_not_actually_retrieved_is_rejected():
    addition = _valid_addition()
    addition["domain_citation"]["source_document"] = "never_retrieved.txt"
    plan = {"additions": [addition], "modifications": []}

    with pytest.raises(DomainEnhancementValidationError, match="was not among the retrieved chunks"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)


def test_addition_without_citation_is_rejected():
    addition = _valid_addition()
    addition["domain_citation"] = {}
    plan = {"additions": [addition], "modifications": []}

    with pytest.raises(DomainEnhancementValidationError, match="no domain_citation.source_document"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)


def test_honesty_check_rejects_additions_claimed_with_empty_retrieval():
    plan = {"additions": [_valid_addition()], "modifications": []}

    with pytest.raises(DomainEnhancementValidationError, match="No domain knowledge chunks were retrieved"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, retrieved_chunks=[])


def test_honesty_check_allows_no_changes_with_empty_retrieval():
    plan = {"additions": [], "modifications": [], "no_changes_note": "No relevant domain knowledge was retrieved."}

    DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, retrieved_chunks=[])


def test_additions_and_modifications_must_be_lists():
    plan = {"additions": "not-a-list", "modifications": []}

    with pytest.raises(DomainEnhancementValidationError, match="must both be lists"):
        DomainEnhancementValidator().validate_plan(BASE_SRS_JSON, plan, RETRIEVED_CHUNKS)
