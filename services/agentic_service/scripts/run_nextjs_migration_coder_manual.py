"""
Manual verification/completion script for the Coder Agent's coding/verify/diff/save
pipeline against the real NextJS Migration Verify project / Item Notes feature
(proj_3b717019 / feature_66e1362f).

Same rationale and pattern as scripts/run_quickcart_coder_pipeline_manual.py /
run_taskflow_coder_pipeline_manual.py: the real, automatic planner reliably failed
plan_validator for this feature (4/4 attempts) because the Architecture Agent's
deterministic fallback plan has crude data (a single literal endpoint string
"/api/item-notes" duplicated across 2 identical GET entries with no method
differentiation, and each requested field split into its own oddly-named "entity"
Item NotesDataEntity1..4) -- this is the SAME pre-existing, already-documented
planner-reliability gap this project's history has hit repeatedly (CLAUDE.md items
18/24), not a bug introduced by the Next.js migration. This bypasses
_plan_with_retries with a hand-validated plan that still covers every literal
string plan_validator requires (that endpoint string + all 4 entity names + FR-001),
but designs the actual Route Handler/model sensibly, matching the SRS's real
api_expectations (one ItemNote model, list+create Route Handler) rather than the
fallback's literal (crude) shape.

Run with:
    ./.venv/Scripts/python.exe scripts/run_nextjs_migration_coder_manual.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.coder_agent.agent import coder_agent
from app.agents.coder_agent.diff_builder import (
    build_code_manifest,
    build_file_tree,
    build_merge_report_markdown,
    build_requirement_code_map,
    build_setup_instructions_markdown,
)
from app.agents.coder_agent.plan_validator import code_plan_validator
from app.agents.coder_agent.schemas import CoderAgentOutput
from app.services.workspace_service import workspace_service
from app.services.in_memory_store import store
from app.utils.file_manager import read_json_file

PROJECT_ID = "proj_3b717019"
FEATURE_ID = "feature_66e1362f"

VALIDATED_CODE_PLAN = {
    "files": [
        {
            "path": "models/ItemNote.ts",
            "action": "create",
            "rationale": "Mongoose model for a note on a catalog item: itemId, content (max 500 "
            "chars per VR-001), authorId, createdAt. Uses the mongoose.models.ItemNote || "
            "mongoose.model(...) guard. Covers all four crude per-field entities the "
            "Architecture Plan's deterministic fallback split out separately (they are all "
            "fields of the same real ItemNote record).",
            "maps_to": [
                "Item NotesDataEntity1",
                "Item NotesDataEntity2",
                "Item NotesDataEntity3",
                "Item NotesDataEntity4",
                "FR-001",
            ],
        },
        {
            "path": "app/api/item-notes/route.ts",
            "action": "create",
            "rationale": "Route Handler implementing GET (list notes for an item via a "
            "?itemId= query param, newest first per AC-002) and POST (create a note, "
            "validating required fields and the 500-character limit per VR-001, and that the "
            "request comes from a registered user per VR-002). export const dynamic = "
            "'force-dynamic' since this touches the database.",
            "maps_to": ["/api/item-notes", "FR-001", "VR-001", "VR-002", "AC-001", "AC-002", "AC-003"],
        },
        {
            "path": "lib/api/itemNotes.ts",
            "action": "create",
            "rationale": "Client-side fetch wrapper functions (listItemNotes, createItemNote) "
            "that app/item-notes/page.tsx calls -- the real API-calling layer, not "
            "fake/hardcoded logic.",
            "maps_to": ["FR-001"],
        },
        {
            "path": "components/ItemNotesList.jsx",
            "action": "create",
            "rationale": "Integrate the approved ItemNotesList UI/UX component verbatim via "
            "read_ui_component -- do not re-author its markup.",
            "maps_to": ["FR-001", "US-002", "AC-002"],
        },
        {
            "path": "components/NoteInputField.jsx",
            "action": "create",
            "rationale": "Integrate the approved NoteInputField UI/UX component via "
            "read_ui_component, but it has a real, confirmed gap: it tracks its own input "
            "text in internal state but has no way to actually submit it (no button, no "
            "Enter-key handler, no onSubmit prop call). Add a real submit affordance (Enter "
            "key and/or a button) that calls a new onSubmit(text) prop, keeping its existing "
            "markup/styling/state machine intact.",
            "maps_to": ["FR-001", "AC-001", "VR-001"],
        },
        {
            "path": "app/item-notes/page.tsx",
            "action": "create",
            "rationale": "Host page (Client Component, \"use client\" first line): fetch real "
            "notes for the item on mount via lib/api/itemNotes, render them with the "
            "integrated ItemNotesList component, wire NoteInputField's onSubmit to a real "
            "create-note API call, refresh the list afterward.",
            "maps_to": ["FR-001", "US-001", "US-002", "AC-001", "AC-002"],
        },
        {
            "path": "app/page.tsx",
            "action": "modify",
            "rationale": "Register a real <Link href=\"/item-notes\"> in HomePage at the "
            "FEATURE_LINKS markers -- a page with no link to it is not complete.",
            "maps_to": [],
        },
    ],
    "new_dependencies": [],
    "env_vars_needed": [],
    "summary": "Full-stack Item Notes implementation for Next.js: one ItemNote Mongoose model "
    "(with the mongoose.models guard), a Route Handler implementing list/create with "
    "VR-001/VR-002/AC-001/AC-002/AC-003 validation, a real lib/api client module, and real "
    "wiring of the approved ItemNotesList/NoteInputField UI/UX components (fixing "
    "NoteInputField's missing submit affordance) via a new app/item-notes/page.tsx, linked "
    "from the home page.",
}


async def main():
    feature = store.features.get(FEATURE_ID)
    project = store.projects.get(PROJECT_ID)

    srs_json = read_json_file(
        "outputs/nextjs-migration-verify/feature-item-notes/02_domain/item_notes_enhanced_srs_v1.json"
    )
    architecture_plan_json = read_json_file(
        "outputs/nextjs-migration-verify/feature-item-notes/03_architecture/item_notes_architecture_plan_v1.json"
    )

    code_plan_validator.validate(srs_json, architecture_plan_json, VALIDATED_CODE_PLAN)
    print("Plan validation: PASSED")

    branch_name = workspace_service.start_feature_branch(PROJECT_ID, FEATURE_ID)
    print(f"Workspace branch: {branch_name}")

    verify_result, coding_attempts = await coder_agent._code_with_retries(
        PROJECT_ID, FEATURE_ID, VALIDATED_CODE_PLAN
    )
    print(f"\nverification_passed={verify_result['passed']} attempts={coding_attempts}")
    for step in verify_result["steps"]:
        print(f"  - {step['name']}: {step['status']}")

    diff = workspace_service.diff_against_main(PROJECT_ID, FEATURE_ID)
    print("\n=== DIFF (file lists only) ===")
    print(json.dumps({k: diff[k] for k in ("added", "modified", "deleted")}, indent=2))

    output = CoderAgentOutput(
        code_plan_json=VALIDATED_CODE_PLAN,
        verification_passed=verify_result["passed"],
        file_tree_json=build_file_tree(diff),
        code_manifest_json=build_code_manifest(VALIDATED_CODE_PLAN, diff),
        requirement_code_map_json=build_requirement_code_map(VALIDATED_CODE_PLAN, diff),
        setup_instructions_markdown=build_setup_instructions_markdown(VALIDATED_CODE_PLAN),
        merge_report_markdown=build_merge_report_markdown(
            feature["feature_name"], diff, verify_result, coding_attempts
        ),
    )

    output.artifact_ids = coder_agent._save_artifacts(dict(project), dict(feature), output)
    print("\n=== ARTIFACT IDS ===")
    print(output.artifact_ids)

    print("\n=== MERGE REPORT ===")
    print(output.merge_report_markdown)


if __name__ == "__main__":
    asyncio.run(main())
