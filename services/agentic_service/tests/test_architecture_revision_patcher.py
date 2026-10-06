"""
Tests for the deterministic Architecture Plan revision patcher
(app/agents/architecture_agent/revision_patcher.py).

This locks in the fix for a real, confirmed bug: both real revision call sites
(_revise_architecture_plan_output/revise_stream) used to ask the LLM to retype the entire
architecture_plan_json object, which is unreliable for a large, deeply-nested document -- and on
failure the fallback rung silently cloned the existing plan unchanged, discarding the human's
requested edit with no visible error (a real, already-generated plan's own
revision_metadata.fallback_used=True proved this happened in practice). These tests exercise the
deterministic apply step in isolation -- no LLM, no fallback ladder -- since that step is what
must now reliably make a requested change actually happen once the (small, more-reliable) plan
names it.
"""

from app.agents.architecture_agent.revision_patcher import (
    _MISSING,
    _resolve_path,
    apply_architecture_revision_operations,
)


def _plan():
    return {
        "document_control": {"target_stack": "Next.js"},
        "feature_overview": {
            "scope": ["Search tasks by keyword"],
            "out_of_scope": ["Fuzzy matching"],
            "user_roles": ["Member"],
        },
        "requirement_interpretation": {},
        "architecture_approach": {},
        "design_views": {
            "context_view": {},
            "logical_view": {},
            "interface_view": {
                "api_endpoints": [
                    {"method": "GET", "endpoint": "/api/task-search", "description": "Search tasks"},
                ]
            },
            "data_view": {
                "data_entities": [
                    {"name": "TaskSearchResult", "purpose": "Represents a matched task", "fields": ["taskId", "title"]},
                ]
            },
            "behavior_view": {},
            "error_handling_view": {},
            "security_authorization_view": {},
            "quality_attributes_view": {},
        },
        "frontend_architecture_plan": {},
        "backend_architecture_plan": {},
        "implementation_plan": {
            "backend": {
                "endpoints": [
                    {"method": "GET", "path": "/api/task-search", "request_body": [], "response": "list of tasks"},
                ],
                "files": [
                    {"path": "app/api/task-search/route.ts", "purpose": "Search endpoint"},
                ],
                "models": [],
            },
            "frontend": {
                "pages": [{"path": "app/task-search/page.tsx", "purpose": "Search page"}],
                "services": [],
                "routing": {"new_routes": ["/task-search"]},
            },
            "implementation_order": ["Create backend endpoint", "Create frontend page"],
            "constraints": ["Must use Next.js App Router"],
        },
        "validation_plan": {},
        "coder_implementation_tasks": [
            {"task_id": "TASK-001", "task": "Implement search endpoint", "layer": "backend"},
        ],
        "traceability_matrix": [],
        "assumptions": ["Search is case-insensitive"],
        "constraints": ["Must respond within 500ms"],
        "risks": ["Large result sets may be slow"],
        "dependencies": ["MongoDB text index"],
        "human_approval_note": "",
    }


REQUIRED_ARCHITECTURE_PLAN_KEYS = [
    "document_control",
    "feature_overview",
    "requirement_interpretation",
    "architecture_approach",
    "design_views",
    "frontend_architecture_plan",
    "backend_architecture_plan",
    "validation_plan",
    "coder_implementation_tasks",
    "traceability_matrix",
    "assumptions",
    "constraints",
    "risks",
    "dependencies",
    "human_approval_note",
]

REQUIRED_DESIGN_VIEW_KEYS = [
    "context_view",
    "logical_view",
    "interface_view",
    "data_view",
    "behavior_view",
    "error_handling_view",
    "security_authorization_view",
    "quality_attributes_view",
]


def test_resolve_path_top_level():
    value, parent, key = _resolve_path(_plan(), "assumptions")
    assert value == ["Search is case-insensitive"]
    assert key == "assumptions"
    assert parent is not None


def test_resolve_path_nested():
    plan = _plan()
    value, parent, key = _resolve_path(plan, "implementation_plan.backend.endpoints")
    assert value == plan["implementation_plan"]["backend"]["endpoints"]
    assert key == "endpoints"


def test_resolve_path_missing_segment_returns_missing():
    value, parent, key = _resolve_path(_plan(), "implementation_plan.backend.nonexistent")
    assert value is _MISSING
    assert parent is None
    assert key is None


def test_resolve_path_missing_top_level_returns_missing():
    value, parent, key = _resolve_path(_plan(), "not_a_real_field")
    assert value is _MISSING


def test_string_list_add():
    plan = _plan()
    operations = [{"action": "add", "field": "constraints", "value": "Must be rate-limited to 10 req/min"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert "Must be rate-limited to 10 req/min" in patched["constraints"]
    assert not unmatched
    assert len(applied) == 1


def test_string_list_remove_by_exact_text():
    plan = _plan()
    operations = [{"action": "remove", "field": "risks", "target": "Large result sets may be slow"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["risks"] == []
    assert not unmatched


def test_string_list_remove_by_substring():
    plan = _plan()
    operations = [{"action": "remove", "field": "dependencies", "target": "text index"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["dependencies"] == []
    assert not unmatched


def test_string_list_modify():
    plan = _plan()
    operations = [
        {
            "action": "modify",
            "field": "assumptions",
            "target": "case-insensitive",
            "value": "Search is case-insensitive and trims whitespace",
        }
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["assumptions"] == ["Search is case-insensitive and trims whitespace"]
    assert not unmatched


def test_string_list_unmatched_is_reported_not_silently_dropped():
    plan = _plan()
    operations = [{"action": "remove", "field": "risks", "target": "Something never mentioned anywhere"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["risks"] == ["Large result sets may be slow"]
    assert len(unmatched) == 1
    assert not applied


def test_object_list_add_with_full_dict_value():
    plan = _plan()
    operations = [
        {
            "action": "add",
            "field": "implementation_plan.backend.endpoints",
            "value": {
                "method": "POST",
                "path": "/api/task-search/save",
                "request_body": ["query"],
                "response": "saved search id",
            },
        }
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    endpoints = patched["implementation_plan"]["backend"]["endpoints"]
    assert len(endpoints) == 2
    assert endpoints[1]["path"] == "/api/task-search/save"
    assert not unmatched


def test_object_list_add_with_bare_string_value_infers_wrap_key():
    plan = _plan()
    operations = [
        {
            "action": "add",
            "field": "coder_implementation_tasks",
            "value": "Implement rate limiting middleware",
        }
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    tasks = patched["coder_implementation_tasks"]
    assert len(tasks) == 2
    # Existing sibling items use "task_id" as their first-priority key -- the wrapper should
    # follow that convention, not default blindly to "description".
    assert tasks[1] == {"task_id": "Implement rate limiting middleware"}
    assert not unmatched


def test_object_list_remove_by_name():
    plan = _plan()
    operations = [{"action": "remove", "field": "design_views.data_view.data_entities", "target": "TaskSearchResult"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["design_views"]["data_view"]["data_entities"] == []
    assert not unmatched


def test_object_list_remove_by_substring_of_purpose():
    plan = _plan()
    operations = [
        {"action": "remove", "field": "implementation_plan.backend.files", "target": "Search endpoint"}
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["implementation_plan"]["backend"]["files"] == []
    assert not unmatched


def test_object_list_modify_only_overwrites_given_fields():
    plan = _plan()
    operations = [
        {
            "action": "modify",
            "field": "implementation_plan.backend.endpoints",
            "target": "/api/task-search",
            "value": {"response": "paginated list of tasks"},
        }
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    endpoint = patched["implementation_plan"]["backend"]["endpoints"][0]
    assert endpoint["response"] == "paginated list of tasks"
    # Untouched fields on the same item survive the partial merge.
    assert endpoint["method"] == "GET"
    assert endpoint["path"] == "/api/task-search"
    assert not unmatched


def test_object_list_modify_by_method_and_path_text():
    plan = _plan()
    operations = [
        {
            "action": "modify",
            "field": "design_views.interface_view.api_endpoints",
            "target": "GET /api/task-search",
            "value": {"description": "Search tasks by keyword, case-insensitive"},
        }
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    endpoint = patched["design_views"]["interface_view"]["api_endpoints"][0]
    assert endpoint["description"] == "Search tasks by keyword, case-insensitive"
    assert not unmatched


def test_scalar_set():
    plan = _plan()
    operations = [{"action": "set", "field": "document_control.target_stack", "value": "Next.js 14 (App Router)"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["document_control"]["target_stack"] == "Next.js 14 (App Router)"
    assert not unmatched


def test_scalar_modify_is_equivalent_to_set():
    plan = _plan()
    operations = [{"action": "modify", "field": "document_control.target_stack", "value": "Next.js 15"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["document_control"]["target_stack"] == "Next.js 15"
    assert not unmatched


def test_dict_leaf_set_merges_partial_value():
    plan = _plan()
    operations = [
        {
            "action": "set",
            "field": "implementation_plan.frontend.routing",
            "value": {"new_routes": ["/task-search", "/task-search/saved"]},
        }
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert patched["implementation_plan"]["frontend"]["routing"]["new_routes"] == [
        "/task-search",
        "/task-search/saved",
    ]
    assert not unmatched


def test_dict_leaf_add_is_rejected_with_steering_message():
    plan = _plan()
    operations = [
        {"action": "add", "field": "implementation_plan.frontend.routing", "value": "/task-search/saved"}
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert not applied
    assert len(unmatched) == 1
    assert "nested section" in unmatched[0]


def test_dict_leaf_remove_is_rejected():
    plan = _plan()
    operations = [{"action": "remove", "field": "implementation_plan.frontend.routing", "target": "new_routes"}]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert not applied
    assert len(unmatched) == 1


def test_malformed_operations_are_skipped_not_raised():
    plan = _plan()
    operations = [
        "not a dict",
        {"action": "remove", "field": "path.that.does.not.exist", "target": "x"},
        {"action": "add", "field": "constraints", "value": "Real, valid operation"},
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert "Real, valid operation" in patched["constraints"]
    assert len(applied) == 1
    assert len(unmatched) == 2


def test_full_plan_smoke_test_required_keys_survive_patching():
    plan = _plan()
    operations = [
        {"action": "add", "field": "constraints", "value": "Must be rate-limited"},
        {"action": "remove", "field": "risks", "target": "Large result sets"},
        {
            "action": "add",
            "field": "implementation_plan.backend.endpoints",
            "value": {"method": "DELETE", "path": "/api/task-search/{id}", "response": "204"},
        },
        {"action": "set", "field": "document_control.target_stack", "value": "Next.js 14"},
        {
            "action": "modify",
            "field": "implementation_plan.frontend.routing",
            "value": {"new_routes": ["/task-search", "/task-search/history"]},
        },
    ]

    patched, applied, unmatched = apply_architecture_revision_operations(plan, operations)

    assert len(applied) == 5
    assert not unmatched

    for key in REQUIRED_ARCHITECTURE_PLAN_KEYS:
        assert key in patched, f"required top-level key {key!r} missing after patching"

    for key in REQUIRED_DESIGN_VIEW_KEYS:
        assert key in patched["design_views"], f"required design_views key {key!r} missing after patching"


def test_original_plan_is_not_mutated():
    plan = _plan()
    original_constraints = list(plan["constraints"])
    operations = [{"action": "add", "field": "constraints", "value": "New constraint"}]

    apply_architecture_revision_operations(plan, operations)

    assert plan["constraints"] == original_constraints
