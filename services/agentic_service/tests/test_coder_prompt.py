"""
Trivial substring-presence tests locking in the Coder Agent system prompt's
hard rules (Next.js App Router + TypeScript). These only prove the rules are
present in the text sent to the model -- they cannot prove the model actually
follows them (that's what the real end-to-end run is for).
"""

from app.agents.coder_agent.prompt import (
    CODE_PLANNER_SYSTEM_PROMPT,
    CODER_AGENT_SYSTEM_PROMPT,
    MAX_IMPLEMENTATION_SPEC_CHARS,
    _match_implementation_plan_entries_for_file,
    _match_srs_requirements_for_file,
    build_implementation_spec_for_single_file,
    build_implementation_spec_section,
)


def test_prompt_forbids_hardcoded_fake_handlers():
    assert "hardcoded or fake logic" in CODER_AGENT_SYSTEM_PROMPT
    assert "lib/api/auth.ts" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_flagging_placeholder_stubs():
    assert "in a real app, you would" in CODER_AGENT_SYSTEM_PROMPT
    assert "final plain-text summary" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_request_body_validation():
    assert "validate that required fields are present" in CODER_AGENT_SYSTEM_PROMPT
    assert "status: 400" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_real_data_wiring_for_a_ui_ux_design_reference():
    # UI/UX output is now an HTML+Tailwind visual reference (not a literal component to import
    # with props to pass through) -- the prompt must still require real props/state/data-wiring
    # when the Coder Agent re-implements it as TSX.
    assert "props, state, and real data-wiring" in CODER_AGENT_SYSTEM_PROMPT
    assert "dangerouslySetInnerHTML" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_syntax_check_and_gap_check_tools():
    assert "check_syntax" in CODER_AGENT_SYSTEM_PROMPT
    assert "list_unimplemented_planned_files" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_blanket_use_client_rule():
    assert '"use client";' in CODER_AGENT_SYSTEM_PROMPT
    assert "no exceptions" in CODER_AGENT_SYSTEM_PROMPT
    assert "Route Handlers (`route.ts`) are server-only" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_named_import_for_connect_to_database():
    # Real, confirmed build failure: the coding loop wrote `import connectToDatabase from
    # "@/lib/mongodb"` (a default import) against a function that's actually a NAMED export --
    # `next build` failed with "does not contain a default export."
    assert 'import { connectToDatabase } from "@/lib/mongodb";' in CODER_AGENT_SYSTEM_PROMPT
    assert "does not contain a default export" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_installing_a_genuinely_needed_undeclared_dependency():
    # Real, confirmed bug: the coding loop imported `bcryptjs` in two Route Handlers without
    # ever installing it (package.json never declared it, new_dependencies was empty), and the
    # old prompt actively discouraged `run_shell` from installing anything not pre-declared by
    # planning -- `next build` correctly failed with "Module not found: Can't resolve 'bcryptjs'".
    assert "npm install <package>@<version> --save" in CODER_AGENT_SYSTEM_PROMPT
    assert "Module not found" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_pins_next_14_synchronous_params_contract():
    assert "PLAIN OBJECT" in CODER_AGENT_SYSTEM_PROMPT
    assert "do NOT `await` them" in CODER_AGENT_SYSTEM_PROMPT
    assert "Next.js 15" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_forbids_server_actions():
    assert "Server Actions" in CODER_AGENT_SYSTEM_PROMPT
    assert "FORBIDDEN" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_mongoose_model_guard():
    assert "mongoose.models.X || mongoose.model" in CODER_AGENT_SYSTEM_PROMPT
    assert "OverwriteModelError" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_forbids_build_error_suppression():
    assert "ignoreBuildErrors" in CODER_AGENT_SYSTEM_PROMPT
    assert "ignoreDuringBuilds" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_has_no_express_router_mount_step():
    # Next.js's file-based routing means there is no app.js-equivalent
    # "mount the router" step at all -- confirm the old MERN-era marker
    # doesn't leak back in.
    assert "FEATURE_ROUTES" not in CODER_AGENT_SYSTEM_PROMPT
    assert "FEATURE_ROUTES" not in CODE_PLANNER_SYSTEM_PROMPT
    assert "never needs a separate \"mount\" step" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_a_link_for_every_route():
    flattened = " ".join(CODER_AGENT_SYSTEM_PROMPT.split())
    assert "FEATURE_LINKS_END" in flattened
    assert "never rewrite `HomePage`'s JSX wholesale" in flattened
    assert "an unreachable page is exactly the" in flattened


def test_planner_prompt_requires_link_and_list_page_for_parameterized_routes():
    assert "FEATURE_LINKS_START" in CODE_PLANNER_SYSTEM_PROMPT
    assert "FEATURE_LINKS_END" in CODE_PLANNER_SYSTEM_PROMPT
    assert "do NOT link" in CODE_PLANNER_SYSTEM_PROMPT
    assert "list/index page" in CODE_PLANNER_SYSTEM_PROMPT


def test_planner_prompt_requires_separate_files_for_collection_and_item_endpoints():
    assert "ALWAYS two different" in CODE_PLANNER_SYSTEM_PROMPT
    assert "app/api/<resource>/[id]/route.ts" in CODE_PLANNER_SYSTEM_PROMPT


def test_planner_prompt_distinguishes_remove_from_restore():
    assert "OPPOSITE actions" in CODE_PLANNER_SYSTEM_PROMPT
    assert "the footer has been removed" in CODE_PLANNER_SYSTEM_PROMPT
    assert "RESTORE" in CODE_PLANNER_SYSTEM_PROMPT


def test_coder_prompt_trusts_original_request_over_plan_rationale():
    assert "Original human request" in CODER_AGENT_SYSTEM_PROMPT
    assert "TRUST THE ORIGINAL REQUEST" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_forbids_rendering_raw_id_as_a_visible_column():
    assert "never render" in CODER_AGENT_SYSTEM_PROMPT
    assert "visible table column" in CODER_AGENT_SYSTEM_PROMPT
    assert "6a85cde40dc527b081a49e90" in CODER_AGENT_SYSTEM_PROMPT


def test_prompt_requires_mirroring_the_designs_exact_field_set():
    flattened = " ".join(CODER_AGENT_SYSTEM_PROMPT.split())
    assert "Mirror the design's exact visible field/column set" in flattened
    assert "superset of what the design displays" in flattened


def test_prompt_requires_responsive_design():
    assert "Responsive by default, no exceptions" in CODER_AGENT_SYSTEM_PROMPT
    assert "overflow-x-auto" in CODER_AGENT_SYSTEM_PROMPT


def test_batch_prompt_inherits_the_new_rules_via_shared_hard_rules():
    # BATCH_CODE_GENERATOR_SYSTEM_PROMPT is built from CODER_AGENT_SYSTEM_PROMPT.split("Tool
    # usage:")[0] -- confirm the new rules (all added before that split point) survive intact.
    from app.agents.coder_agent.prompt import BATCH_CODE_GENERATOR_SYSTEM_PROMPT

    assert "visible table column" in BATCH_CODE_GENERATOR_SYSTEM_PROMPT
    assert "Responsive by default, no exceptions" in BATCH_CODE_GENERATOR_SYSTEM_PROMPT


def test_prompt_requires_security_remediation_handling_without_weakening_existing_controls():
    # Format-triggered (not gated on revised_by, which coder_agent/agent.py never reads) so it
    # reaches every coding path -- confirm it's present in both the agentic and batch prompts.
    from app.agents.coder_agent.prompt import BATCH_CODE_GENERATOR_SYSTEM_PROMPT

    for prompt in (CODER_AGENT_SYSTEM_PROMPT, BATCH_CODE_GENERATOR_SYSTEM_PROMPT):
        assert "security remediation task from the Security Agent" in prompt
        assert "Never weaken or remove an EXISTING security control" in prompt


# --- build_implementation_spec_section / _for_single_file (thread the real SRS + Architecture
# Plan implementation_plan into the actual coding step, not just planning) ---

ARCHITECTURE_PLAN = {
    "implementation_plan": {
        "backend": {
            "files": [
                {
                    "path": "app/api/items/route.ts",
                    "action": "create",
                    "purpose": "CRUD for items",
                    "implements_endpoints": ["/api/items"],
                },
            ],
            "endpoints": [
                {
                    "method": "POST",
                    "path": "/api/items",
                    "request_body": [{"field": "name", "type": "string", "required": True}],
                    "response": "Item",
                    "error_cases": ["400 if name missing"],
                },
                {"method": "GET", "path": "/api/unrelated", "request_body": [], "response": "X"},
            ],
            "models": [
                {"name": "Item", "file": "models/Item.ts", "fields": [{"name": "name", "type": "string"}]},
                {"name": "Unrelated", "file": "models/Unrelated.ts", "fields": []},
            ],
        },
        "frontend": {
            "pages": [
                {"path": "app/items/page.tsx", "route": "/items", "purpose": "List items", "uses_components": []},
            ],
            "services": [
                {"path": "lib/api/items.ts", "functions": [{"name": "createItem", "calls_endpoint": "/api/items"}]},
            ],
        },
    }
}

SRS_WITH_REQUIREMENTS = {
    "ui_expectations": ["A main page showing all items in a list"],
    "functional_requirements": [
        {"id": "FR-001", "description": "User can create an item"},
        {"id": "FR-002", "description": "User can delete an item"},
        {"id": "FR-003", "description": "User can search items"},
        {"id": "FR-004", "description": "User can view an item"},
    ],
    "acceptance_criteria": [{"id": "AC-001", "description": "Given valid data, item is created"}],
}


def test_match_implementation_plan_entries_matches_by_path_and_maps_to():
    file_entry = {"path": "app/api/items/route.ts", "action": "create", "maps_to": ["/api/items", "Item"]}
    matched = _match_implementation_plan_entries_for_file(file_entry, ARCHITECTURE_PLAN["implementation_plan"])

    assert len(matched["backend_file"]) == 1
    assert matched["backend_file"][0]["path"] == "app/api/items/route.ts"
    assert len(matched["endpoints"]) == 1
    assert matched["endpoints"][0]["path"] == "/api/items"
    assert len(matched["models"]) == 1
    assert matched["models"][0]["name"] == "Item"
    # The unrelated endpoint/model must never leak in.
    assert all(e["path"] != "/api/unrelated" for e in matched["endpoints"])
    assert all(m["name"] != "Unrelated" for m in matched["models"])


def test_match_implementation_plan_entries_matches_frontend_pages_and_services():
    page_entry = {"path": "app/items/page.tsx", "action": "create", "maps_to": []}
    matched = _match_implementation_plan_entries_for_file(page_entry, ARCHITECTURE_PLAN["implementation_plan"])
    assert len(matched["pages"]) == 1
    assert matched["pages"][0]["route"] == "/items"

    service_entry = {"path": "lib/api/items.ts", "action": "create", "maps_to": []}
    matched_service = _match_implementation_plan_entries_for_file(service_entry, ARCHITECTURE_PLAN["implementation_plan"])
    assert len(matched_service["services"]) == 1


def test_match_implementation_plan_entries_returns_empty_dict_when_nothing_matches():
    file_entry = {"path": "lib/mongodb.ts", "action": "modify", "maps_to": []}
    matched = _match_implementation_plan_entries_for_file(file_entry, ARCHITECTURE_PLAN["implementation_plan"])
    assert matched == {}


def test_match_srs_requirements_matches_by_id_in_maps_to():
    file_entry = {"path": "app/api/items/route.ts", "maps_to": ["FR-001", "AC-001"]}
    matched = _match_srs_requirements_for_file(file_entry, SRS_WITH_REQUIREMENTS)
    matched_ids = {item["id"] for item in matched}
    assert matched_ids == {"FR-001", "AC-001"}


def test_match_srs_requirements_falls_back_to_first_few_when_no_id_in_maps_to():
    file_entry = {"path": "models/Item.ts", "maps_to": ["Item"]}
    matched = _match_srs_requirements_for_file(file_entry, SRS_WITH_REQUIREMENTS)
    assert len(matched) == 3
    assert matched[0]["id"] == "FR-001"


def test_build_implementation_spec_for_single_file_includes_ui_expectations_and_matched_slice():
    file_entry = {"path": "app/api/items/route.ts", "action": "create", "maps_to": ["/api/items", "FR-001"]}
    spec = build_implementation_spec_for_single_file(file_entry, SRS_WITH_REQUIREMENTS, ARCHITECTURE_PLAN)

    assert "A main page showing all items in a list" in spec
    assert "/api/items" in spec
    assert "FR-001" in spec


def test_build_implementation_spec_for_single_file_empty_inputs_return_empty_string():
    file_entry = {"path": "lib/mongodb.ts", "action": "modify", "maps_to": []}
    spec = build_implementation_spec_for_single_file(file_entry, {}, {})
    assert spec == ""


def test_build_implementation_spec_for_single_file_truncates_at_char_cap():
    huge_plan = {
        "implementation_plan": {
            "backend": {
                "files": [{"path": "app/api/big/route.ts", "purpose": "x" * (MAX_IMPLEMENTATION_SPEC_CHARS * 2)}],
            },
            "frontend": {},
        }
    }
    file_entry = {"path": "app/api/big/route.ts", "maps_to": []}
    spec = build_implementation_spec_for_single_file(file_entry, {}, huge_plan)
    assert len(spec) <= MAX_IMPLEMENTATION_SPEC_CHARS + len("\n... (truncated)")
    assert spec.endswith("... (truncated)")


def test_build_implementation_spec_section_covers_every_planned_file():
    code_plan_json = {
        "files": [
            {"path": "app/api/items/route.ts", "action": "create", "maps_to": ["/api/items", "FR-001"]},
            {"path": "app/items/page.tsx", "action": "create", "maps_to": []},
        ]
    }
    section = build_implementation_spec_section(code_plan_json, SRS_WITH_REQUIREMENTS, ARCHITECTURE_PLAN)

    assert "app/api/items/route.ts" in section
    assert "app/items/page.tsx" in section
    assert "/api/items" in section
    # ui_expectations appears once, cross-cutting, not per-file.
    assert section.count("A main page showing all items in a list") == 1


def test_build_implementation_spec_section_empty_when_nothing_available():
    section = build_implementation_spec_section({"files": []}, {}, {})
    assert section == ""
