"""
Tests for the deterministic SRS revision patcher (app/agents/requirement_agent/revision_patcher.py).

This locks in the fix for a real reported bug: asking the LLM to retype the entire SRS for a
revision was unreliable, and a genuine "remove this specific non-functional requirement" comment
was silently dropped. These tests exercise the deterministic apply step in isolation -- no LLM,
no fallback ladder -- since that step is what must now reliably make a requested change actually
happen once the (small, more-reliable) plan names it.
"""

from app.agents.requirement_agent.revision_patcher import apply_revision_operations


def _srs():
    return {
        "functional_requirements": [
            {"id": "FR-001", "description": "Admin can create a task", "priority": "Must Have"},
        ],
        "non_functional_requirements": [
            {"id": "NFR-001", "description": "System should be secure", "category": "Security"},
            {
                "id": "NFR-002",
                "description": "Listing page must load within 2 seconds for up to 10,000 items",
                "category": "Performance",
            },
        ],
        "acceptance_criteria": [
            {"id": "AC-001", "description": "Admin can see a list of tasks."},
        ],
        "user_stories": [
            {"id": "US-001", "role": "Admin", "goal": "manage tasks", "benefit": "stay organized"},
        ],
        "scope": ["Implement task management."],
        "assumptions": [],
    }


def test_remove_id_description_item_by_exact_text():
    srs = _srs()
    operations = [
        {
            "action": "remove",
            "field": "non_functional_requirements",
            "target": "Listing page must load within 2 seconds for up to 10,000 items",
        }
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["non_functional_requirements"]) == 1
    assert patched["non_functional_requirements"][0]["id"] == "NFR-001"
    assert not unmatched
    assert len(applied) == 1


def test_remove_id_description_item_by_id():
    srs = _srs()
    operations = [{"action": "remove", "field": "non_functional_requirements", "target": "NFR-002"}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["non_functional_requirements"]) == 1
    assert not unmatched


def test_remove_by_partial_distinctive_substring():
    srs = _srs()
    operations = [{"action": "remove", "field": "non_functional_requirements", "target": "10,000 items"}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["non_functional_requirements"]) == 1
    assert patched["non_functional_requirements"][0]["id"] == "NFR-001"
    assert not unmatched


def test_unmatched_removal_is_reported_not_silently_dropped():
    srs = _srs()
    operations = [{"action": "remove", "field": "non_functional_requirements", "target": "Something not in the SRS"}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["non_functional_requirements"]) == 2
    assert not applied
    assert len(unmatched) == 1
    assert "Something not in the SRS" in unmatched[0]


def test_add_functional_requirement_gets_next_stable_id():
    srs = _srs()
    operations = [
        {"action": "add", "field": "functional_requirements", "value": "Admin can archive a task", "priority": "Should Have"}
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["functional_requirements"]) == 2
    assert patched["functional_requirements"][1]["id"] == "FR-002"
    assert patched["functional_requirements"][1]["priority"] == "Should Have"
    assert not unmatched


def test_modify_replaces_description_in_place_keeping_id():
    srs = _srs()
    operations = [
        {"action": "modify", "field": "acceptance_criteria", "target": "AC-001", "value": "Admin can filter the task list by status."}
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["acceptance_criteria"][0]["id"] == "AC-001"
    assert patched["acceptance_criteria"][0]["description"] == "Admin can filter the task list by status."
    assert not unmatched


def test_string_list_field_add_and_remove():
    srs = _srs()
    operations = [
        {"action": "add", "field": "scope", "value": "Support recurring tasks."},
        {"action": "remove", "field": "scope", "target": "Implement task management."},
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["scope"] == ["Support recurring tasks."]
    assert not unmatched


def test_user_story_add():
    srs = _srs()
    operations = [
        {"action": "add", "field": "user_stories", "role": "Guest", "value": "browse public tasks", "benefit": "see what's available"}
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["user_stories"]) == 2
    assert patched["user_stories"][1]["id"] == "US-002"
    assert patched["user_stories"][1]["role"] == "Guest"
    assert not unmatched


def test_add_to_completely_empty_id_description_field():
    """Real gap this locks in: a plural/broad revision request ('add user stories') targeting a
    field that starts genuinely empty must work, not just adding to an already-populated one."""
    srs = _srs()
    srs["user_stories"] = []
    operations = [
        {"action": "add", "field": "user_stories", "role": "Guest", "value": "browse public tasks", "benefit": "see what's available"}
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["user_stories"]) == 1
    assert patched["user_stories"][0]["id"] == "US-001"
    assert not unmatched


def test_add_to_completely_empty_plain_string_field():
    srs = _srs()
    srs["constraints"] = []
    operations = [{"action": "add", "field": "constraints", "value": "Must use Next.js."}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["constraints"] == ["Must use Next.js."]
    assert not unmatched


def test_multiple_add_operations_against_the_same_id_description_field_in_one_call():
    """A broad request like 'add user stories' (plural) must produce several correctly-sequenced,
    collision-free ids in one operations list, not just one item."""
    srs = _srs()
    srs["user_stories"] = []
    operations = [
        {"action": "add", "field": "user_stories", "role": "Admin", "value": "create tasks", "benefit": "manage the backlog"},
        {"action": "add", "field": "user_stories", "role": "Customer", "value": "view tasks", "benefit": "track progress"},
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert [story["id"] for story in patched["user_stories"]] == ["US-001", "US-002"]
    assert patched["user_stories"][0]["role"] == "Admin"
    assert patched["user_stories"][1]["role"] == "Customer"
    assert len(applied) == 2
    assert not unmatched


def test_multiple_add_operations_against_the_same_plain_string_field_in_one_call():
    srs = _srs()
    srs["constraints"] = []
    operations = [
        {"action": "add", "field": "constraints", "value": "Must use Next.js."},
        {"action": "add", "field": "constraints", "value": "Must enforce JWT authentication on every endpoint."},
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["constraints"] == [
        "Must use Next.js.",
        "Must enforce JWT authentication on every endpoint.",
    ]
    assert not unmatched


def test_user_story_add_honors_explicit_benefit_not_the_generic_default():
    """Real, confirmed gap this closes: the operation schema never documented "benefit" even
    though _apply_user_story_operation reads it -- every prior revision-added user story silently
    got the same generic default benefit regardless of what was actually requested."""
    srs = _srs()
    operations = [
        {
            "action": "add",
            "field": "user_stories",
            "role": "Guest",
            "value": "browse public tasks",
            "benefit": "decide whether to sign up",
        }
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    new_story = patched["user_stories"][-1]
    assert new_story["benefit"] == "decide whether to sign up"
    assert new_story["benefit"] != "complete the intended business process"  # the generic default


def test_non_functional_requirement_add_honors_explicit_category():
    srs = _srs()
    operations = [
        {"action": "add", "field": "non_functional_requirements", "value": "Must support 1000 concurrent users.", "category": "Scalability"}
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    new_nfr = patched["non_functional_requirements"][-1]
    assert new_nfr["category"] == "Scalability"


def test_operations_against_two_different_fields_in_one_call():
    """Confirms the field-agnostic design: one broad revision comment covering several sections
    at once (e.g. 'add a user story and a constraint') works exactly like two separate,
    single-field revisions would."""
    srs = _srs()
    srs["user_stories"] = []
    srs["constraints"] = []
    operations = [
        {"action": "add", "field": "user_stories", "role": "Admin", "value": "archive old tasks", "benefit": "keep the list tidy"},
        {"action": "add", "field": "constraints", "value": "Must use Next.js."},
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert len(patched["user_stories"]) == 1
    assert patched["constraints"] == ["Must use Next.js."]
    assert len(applied) == 2
    assert not unmatched


def test_scalar_field_set_action_works():
    srs = _srs()
    srs["business_goal"] = "Original goal."
    operations = [{"action": "set", "field": "business_goal", "value": "Updated goal."}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["business_goal"] == "Updated goal."
    assert not unmatched


def test_scalar_field_modify_action_is_treated_as_set():
    """Real, confirmed bug found via live verification against the real model: a request to
    change an EXISTING scalar value ("update the business goal to also mention...") naturally
    produces action="modify", not "set" -- previously only "set" was accepted, so the change
    silently fell through to the unsupported-field catch-all and never happened."""
    srs = _srs()
    srs["business_goal"] = "Original goal."
    operations = [{"action": "modify", "field": "business_goal", "value": "Updated goal."}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["business_goal"] == "Updated goal."
    assert not unmatched
    assert applied


def test_traceability_is_rebuilt_after_functional_requirement_removal():
    srs = _srs()
    srs["functional_requirements"].append({"id": "FR-002", "description": "Admin can delete a task", "priority": "Must Have"})
    operations = [{"action": "remove", "field": "functional_requirements", "target": "FR-001"}]

    patched, _, _ = apply_revision_operations(srs, operations)

    assert [row["requirement_id"] for row in patched["traceability"]] == ["FR-002"]


def test_user_story_modify_goal_only_backward_compatible():
    """Every pre-existing caller only ever sends value/goal -- must behave identically after
    the role/benefit extension."""
    srs = _srs()
    operations = [{"action": "modify", "field": "user_stories", "target": "US-001", "value": "manage all tasks"}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["user_stories"][0]["goal"] == "manage all tasks"
    assert patched["user_stories"][0]["role"] == "Admin"
    assert patched["user_stories"][0]["benefit"] == "stay organized"
    assert not unmatched


def test_user_story_modify_role_and_benefit():
    """Real gap this closes: modify previously only ever touched goal, even when the operation
    carried role/benefit -- the field-by-field inline-edit UI needs to edit any part of a
    user story, not just its goal text."""
    srs = _srs()
    operations = [
        {"action": "modify", "field": "user_stories", "target": "US-001", "role": "Manager", "benefit": "keep the team on track"}
    ]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert patched["user_stories"][0]["role"] == "Manager"
    assert patched["user_stories"][0]["benefit"] == "keep the team on track"
    assert patched["user_stories"][0]["goal"] == "manage tasks"  # untouched
    assert not unmatched


def test_malformed_operation_is_skipped_not_raised():
    srs = _srs()
    operations = ["not a dict", {"action": "remove", "field": "unsupported_field", "target": "x"}]

    patched, applied, unmatched = apply_revision_operations(srs, operations)

    assert not applied
    assert len(unmatched) == 2
    # Existing content is untouched by the malformed/unsupported operations.
    assert patched["non_functional_requirements"] == srs["non_functional_requirements"]
