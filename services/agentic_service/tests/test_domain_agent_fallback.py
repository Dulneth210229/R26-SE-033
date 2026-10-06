"""
Unit tests for DomainAgent's deterministic plan-merge and fallback path.

Pure Python -- exercises _apply_enrichment_plan, _build_fallback_plan,
_next_dom_id, and _finalize_enhanced_srs_metadata directly, with no
LLM/embedding calls. Proves that:
- a real enrichment plan gets merged correctly (new "-DOM-" IDs assigned,
  original items enriched in place with original_description preserved),
- the fallback path (empty plan) never fabricates domain content and always
  produces validator-passing output,
- revision-style merges (base_srs_json already containing prior "-DOM-"
  items) continue ID numbering correctly instead of colliding/restarting.
"""

import copy

from app.agents.domain_agent.agent import DomainAgent
from app.agents.domain_agent.domain_validator import DomainEnhancementValidator

SRS_JSON = {
    "project_id": "proj_1",
    "feature_id": "feature_1",
    "functional_requirements": [{"id": "FR-001", "description": "Users can log in."}],
    "non_functional_requirements": [],
    "acceptance_criteria": [{"id": "AC-001", "description": "Given valid credentials, login succeeds."}],
    "validation_rules": [],
    "user_stories": [],
    "assumptions": [],
    "risks": [],
}

RETRIEVED_CHUNKS = [
    {"chunk_id": "auth.txt#0", "source_document": "auth.txt", "text": "Lock the account after 5 failed attempts."},
]


def test_fallback_plan_with_empty_retrieval_explains_why():
    agent = DomainAgent()

    plan = agent._build_fallback_plan(retrieved_chunks=[], reason="parse failed")

    assert plan["additions"] == []
    assert plan["modifications"] == []
    assert plan["no_changes_note"] == "No relevant domain knowledge was retrieved for this feature."


def test_fallback_plan_with_nonempty_retrieval_reports_the_failure_reason():
    agent = DomainAgent()

    plan = agent._build_fallback_plan(RETRIEVED_CHUNKS, reason="LLM timeout")

    assert "LLM timeout" in plan["no_changes_note"]
    assert plan["additions"] == []
    assert plan["modifications"] == []


def test_apply_empty_plan_preserves_srs_unchanged():
    agent = DomainAgent()
    plan = agent._build_fallback_plan(retrieved_chunks=[], reason="parse failed")

    enhanced, improvements = agent._apply_enrichment_plan(SRS_JSON, plan, retrieved_chunks=[])

    # Every original item survives, byte-for-byte, no fabricated additions.
    assert enhanced["functional_requirements"] == SRS_JSON["functional_requirements"]
    assert enhanced["acceptance_criteria"] == SRS_JSON["acceptance_criteria"]
    assert improvements["additions"] == []
    assert improvements["modifications"] == []
    assert improvements["no_changes_note"] == "No relevant domain knowledge was retrieved for this feature."


def test_apply_plan_with_addition_assigns_dom_id_and_flags_origin():
    agent = DomainAgent()
    plan = {
        "summary": "Added account lockout requirement.",
        "additions": [{
            "target_section": "functional_requirements",
            "description": "Lock the account after 5 consecutive failed login attempts.",
            "priority": "Should Have",
            "rationale": "Prevent brute-force attacks.",
            "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
        }],
        "modifications": [],
        "no_changes_note": None,
    }

    enhanced, improvements = agent._apply_enrichment_plan(SRS_JSON, plan, RETRIEVED_CHUNKS)

    new_items = [item for item in enhanced["functional_requirements"] if item["id"] != "FR-001"]
    assert len(new_items) == 1
    assert new_items[0]["id"] == "FR-DOM-001"
    assert new_items[0]["origin"] == "domain_agent"
    assert new_items[0]["domain_citation"]["source_document"] == "auth.txt"

    # Original item must survive untouched.
    original = next(item for item in enhanced["functional_requirements"] if item["id"] == "FR-001")
    assert original == SRS_JSON["functional_requirements"][0]

    assert improvements["additions"][0]["new_id"] == "FR-DOM-001"
    assert improvements["knowledge_sources_used"] == [{"source_document": "auth.txt", "chunks_used": 1}]
    assert improvements["no_changes_note"] is None


def test_apply_plan_with_modification_preserves_original_description():
    agent = DomainAgent()
    plan = {
        "additions": [],
        "modifications": [{
            "target_section": "acceptance_criteria",
            "id": "AC-001",
            "enhanced_description": "Given valid credentials and an unlocked account, login succeeds.",
            "rationale": "Reflect the lockout rule.",
            "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
        }],
        "no_changes_note": None,
    }

    enhanced, improvements = agent._apply_enrichment_plan(SRS_JSON, plan, RETRIEVED_CHUNKS)

    modified = next(item for item in enhanced["acceptance_criteria"] if item["id"] == "AC-001")
    assert modified["description"] == "Given valid credentials and an unlocked account, login succeeds."
    assert modified["modified_by_domain_agent"] is True
    assert modified["original_description"] == "Given valid credentials, login succeeds."

    assert improvements["modifications"][0]["original_description"] == "Given valid credentials, login succeeds."
    assert improvements["modifications"][0]["enhanced_description"] == modified["description"]


def test_next_dom_id_continues_past_existing_dom_items():
    agent = DomainAgent()
    base_with_prior_dom_item = copy.deepcopy(SRS_JSON)
    base_with_prior_dom_item["functional_requirements"].append({
        "id": "FR-DOM-001",
        "description": "Existing domain addition.",
        "origin": "domain_agent",
        "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
    })

    plan = {
        "additions": [{
            "target_section": "functional_requirements",
            "description": "A second domain addition.",
            "priority": "Should Have",
            "rationale": "Another rule.",
            "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
        }],
        "modifications": [],
        "no_changes_note": None,
    }

    enhanced, _ = agent._apply_enrichment_plan(base_with_prior_dom_item, plan, RETRIEVED_CHUNKS)

    new_ids = sorted(item["id"] for item in enhanced["functional_requirements"] if "-DOM-" in item["id"])
    assert new_ids == ["FR-DOM-001", "FR-DOM-002"]


def test_finalize_metadata_sets_fallback_flag_and_reason():
    agent = DomainAgent()
    enhanced = copy.deepcopy(SRS_JSON)

    agent._finalize_enhanced_srs_metadata(
        enhanced, srs_version=3, retrieved_chunks=[], fallback_used=True, fallback_reason="boom"
    )

    metadata = enhanced["domain_enrichment_metadata"]
    assert metadata["based_on_srs_version"] == 3
    assert metadata["fallback_used"] is True
    assert metadata["fallback_reason"] == "boom"


def test_finalize_metadata_omits_reason_when_not_fallback():
    agent = DomainAgent()
    enhanced = copy.deepcopy(SRS_JSON)

    agent._finalize_enhanced_srs_metadata(
        enhanced, srs_version=1, retrieved_chunks=[], fallback_used=False, fallback_reason=None
    )

    metadata = enhanced["domain_enrichment_metadata"]
    assert metadata["fallback_used"] is False
    assert "fallback_reason" not in metadata


def test_fallback_plan_always_passes_the_validator():
    agent = DomainAgent()

    plan = agent._build_fallback_plan(retrieved_chunks=[], reason="parse failed")

    # Must not raise -- the fallback plan must always be validator-clean.
    DomainEnhancementValidator().validate_plan(SRS_JSON, plan, retrieved_chunks=[])


def test_real_plan_from_fallback_merge_round_trip_passes_the_validator():
    """
    Simulates the real pipeline shape: a plan that would come from a real LLM call, validated
    before merge, merged deterministically, and the *next* plan (e.g. a revision) validated
    against the already-merged state.
    """
    agent = DomainAgent()
    plan = {
        "additions": [{
            "target_section": "functional_requirements",
            "description": "Lock the account after 5 consecutive failed login attempts.",
            "priority": "Should Have",
            "rationale": "Prevent brute-force attacks.",
            "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
        }],
        "modifications": [],
        "no_changes_note": None,
    }

    DomainEnhancementValidator().validate_plan(SRS_JSON, plan, RETRIEVED_CHUNKS)
    enhanced, _ = agent._apply_enrichment_plan(SRS_JSON, plan, RETRIEVED_CHUNKS)

    # A follow-up revision plan should be able to validate against the now-enriched state,
    # referencing the previously-added FR-DOM-001 by id.
    revision_plan = {
        "additions": [],
        "modifications": [{
            "target_section": "functional_requirements",
            "id": "FR-DOM-001",
            "enhanced_description": "Lock the account after 5 failed attempts and notify the user by email.",
            "rationale": "Add notification per revision comment.",
            "domain_citation": {"source_document": "auth.txt", "chunk_id": "auth.txt#0"},
        }],
        "no_changes_note": None,
    }

    DomainEnhancementValidator().validate_plan(enhanced, revision_plan, RETRIEVED_CHUNKS)
