"""
Unit tests for RequirementAgent's SRS-completeness guarantee -- a real, confirmed bug: the real
LLM path for initial SRS generation had no "must not be empty" instruction for user_stories (or
several other fields), and REQUIRED_KEYS/_validate_stable_ids never enforced it either, so a
freshly-generated SRS could -- and did -- ship with "user_stories": []. Fixed with a deterministic,
no-LLM backstop (conversation_engine.ensure_srs_completeness) that runs unconditionally on the
final srs_json regardless of how it was produced.

Pure Python, no LLM/Mongo.
"""

from app.agents.requirement_agent.conversation_engine import ensure_srs_completeness

BASE_SRS = {
    "feature_name": "Item Listing",
    "target_stack": "Next.js",
    "architectural_style": "modular",
    "functional_requirements": [{"id": "FR-001", "description": "Admin can create an item.", "priority": "Must Have"}],
    "data_requirements": ["name (string, required)", "price (number, required)"],
    "assumptions": [],
}


def test_empty_user_stories_gets_one_entry_per_role():
    srs = dict(BASE_SRS)
    srs["user_stories"] = []
    srs["user_roles"] = ["Admin", "Guest"]

    patched, notes = ensure_srs_completeness(srs)

    assert len(patched["user_stories"]) == 2
    assert {s["role"] for s in patched["user_stories"]} == {"Admin", "Guest"}
    assert any("user_stories" in n for n in notes)


def test_empty_user_stories_and_empty_user_roles_defaults_to_one_generic_role():
    srs = dict(BASE_SRS)
    srs["user_stories"] = []
    srs["user_roles"] = []

    patched, notes = ensure_srs_completeness(srs)

    assert len(patched["user_stories"]) == 1
    assert patched["user_stories"][0]["role"] == "User"


def test_already_populated_user_stories_is_left_untouched():
    srs = dict(BASE_SRS)
    srs["user_stories"] = [{"id": "US-001", "role": "Admin", "goal": "manage items", "benefit": "stay organized"}]
    srs["user_roles"] = ["Admin"]

    patched, notes = ensure_srs_completeness(srs)

    assert patched["user_stories"] == srs["user_stories"]
    assert not any("user_stories" in n for n in notes)


def test_empty_user_roles_is_inferred_from_populated_user_stories():
    srs = dict(BASE_SRS)
    srs["user_roles"] = []
    srs["user_stories"] = [
        {"id": "US-001", "role": "Admin", "goal": "manage items", "benefit": "stay organized"},
        {"id": "US-002", "role": "Guest", "goal": "browse items", "benefit": "decide what to buy"},
    ]

    patched, notes = ensure_srs_completeness(srs)

    assert patched["user_roles"] == ["Admin", "Guest"]


def test_empty_constraints_derived_from_stack_and_architecture():
    srs = dict(BASE_SRS)
    srs["constraints"] = []
    srs["user_stories"] = [{"id": "US-001", "role": "User", "goal": "x", "benefit": "y"}]
    srs["user_roles"] = ["User"]

    patched, notes = ensure_srs_completeness(srs)

    assert any("Next.js" in c for c in patched["constraints"])
    assert any("modular" in c for c in patched["constraints"])


def test_empty_api_and_ui_expectations_get_hedged_placeholders_not_fake_precision():
    srs = dict(BASE_SRS)
    srs["user_stories"] = [{"id": "US-001", "role": "User", "goal": "x", "benefit": "y"}]
    srs["user_roles"] = ["User"]
    srs["api_expectations"] = []
    srs["ui_expectations"] = []

    patched, notes = ensure_srs_completeness(srs)

    assert len(patched["api_expectations"]) == 1
    assert len(patched["ui_expectations"]) == 1
    # Honest hedging, never a fabricated specific route/UI element.
    assert "inferred" in patched["api_expectations"][0].lower()
    assert "inferred" in patched["ui_expectations"][0].lower()


def test_empty_input_requirements_aliases_data_requirements_when_present():
    srs = dict(BASE_SRS)
    srs["user_stories"] = [{"id": "US-001", "role": "User", "goal": "x", "benefit": "y"}]
    srs["user_roles"] = ["User"]
    srs["input_requirements"] = []

    patched, notes = ensure_srs_completeness(srs)

    assert patched["input_requirements"] == srs["data_requirements"]


def test_empty_input_requirements_falls_back_to_placeholder_when_data_requirements_also_empty():
    srs = dict(BASE_SRS)
    srs["user_stories"] = [{"id": "US-001", "role": "User", "goal": "x", "benefit": "y"}]
    srs["user_roles"] = ["User"]
    srs["input_requirements"] = []
    srs["data_requirements"] = []

    patched, notes = ensure_srs_completeness(srs)

    assert len(patched["input_requirements"]) == 1


def test_empty_risks_and_dependencies_get_honest_not_evaluated_placeholders():
    """Real honesty requirement: an empty risks/dependencies list can legitimately be correct for
    a trivial feature -- the backstop must never claim "no risks" as a genuine finding, only
    "not evaluated"."""
    srs = dict(BASE_SRS)
    srs["user_stories"] = [{"id": "US-001", "role": "User", "goal": "x", "benefit": "y"}]
    srs["user_roles"] = ["User"]
    srs["risks"] = []
    srs["dependencies"] = []

    patched, notes = ensure_srs_completeness(srs)

    assert "not" in patched["risks"][0].lower()
    assert "not" in patched["dependencies"][0].lower()
    assert "no risks" not in patched["risks"][0].lower() or "not" in patched["risks"][0].lower()


def test_no_backstop_notes_when_nothing_was_empty():
    srs = dict(BASE_SRS)
    srs["user_stories"] = [{"id": "US-001", "role": "Admin", "goal": "manage items", "benefit": "stay organized"}]
    srs["user_roles"] = ["Admin"]
    srs["constraints"] = ["Must use Next.js."]
    srs["api_expectations"] = ["POST /api/items"]
    srs["ui_expectations"] = ["A list view"]
    srs["input_requirements"] = ["name"]
    srs["risks"] = ["Data loss on concurrent edits."]
    srs["dependencies"] = ["Image storage service."]

    patched, notes = ensure_srs_completeness(srs)

    assert notes == []


def test_missing_keys_entirely_are_treated_the_same_as_empty_lists():
    """A field can be genuinely ABSENT from the LLM's JSON (not just an empty list) -- the
    backstop must catch both shapes the same way."""
    srs = {
        "feature_name": "Item Listing",
        "target_stack": "Next.js",
        "architectural_style": "modular",
        "assumptions": [],
        # user_stories, user_roles, constraints, etc. are all absent, not just empty.
    }

    patched, notes = ensure_srs_completeness(srs)

    assert len(patched["user_stories"]) >= 1
    assert len(patched["constraints"]) >= 1
