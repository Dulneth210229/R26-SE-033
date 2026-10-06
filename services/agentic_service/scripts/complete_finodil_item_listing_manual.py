"""
Manual completion script for the Coder Agent's verify/diff/save pipeline against the real
Finodil project / Item Listing feature (proj_2ba24bc0 / feature_5ff762e5).

Context: the Coder Agent's own coding loop was stopped mid-run by the human, and the feature
was then completed by hand (direct file edits on the already-existing feature/item-listing
branch, on top of the stopped attempt's own commit) rather than resuming the agent. This left
the AutoForge dashboard's Coder Agent "Result" panel empty for this feature (no CODE_DIFF
artifact was ever saved), even though the real code is complete, committed, and already
verified once manually via a real `next build` + `next start` + Playwright session.

This script does NOT re-run the coding loop (the code is already correct and committed) --
it only runs the same deterministic verify() -> diff -> save_artifacts tail `_code_with_retries`
would have run, against the code as it now stands on disk, so the dashboard shows a real,
accurate Coder Agent result exactly like every other feature. Mirrors the established
scripts/run_*_manual.py pattern in this same directory.

Run with:
    ./.venv/Scripts/python.exe scripts/complete_finodil_item_listing_manual.py
"""

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
from app.agents.coder_agent.schemas import CoderAgentOutput
from app.services.workspace_service import workspace_service
from app.services.in_memory_store import store
from app.utils.file_manager import read_json_file

PROJECT_ID = "proj_2ba24bc0"
FEATURE_ID = "feature_5ff762e5"

CODE_PLAN = {
    "files": [
        {
            "path": "models/ItemListingData.ts",
            "action": "modify",
            "rationale": "Removed junk auto-derived fields (itemsTable, a duplicate name, a "
            "field literally named 'string') inherited from the Architecture Plan's crude "
            "fallback field list, keeping only the real SRS-derived fields (name, description, "
            "price, quantity, category, createdAt).",
            "maps_to": ["FR-002", "FR-DOM-003", "AC-002"],
        },
        {
            "path": "lib/types/ItemListing.ts",
            "action": "create",
            "rationale": "Shared request/response type (ItemListingItem/ItemListingResponse) so "
            "the frontend no longer imports the server-only Mongoose Document interface.",
            "maps_to": ["FR-002"],
        },
        {
            "path": "lib/seedData.ts",
            "action": "modify",
            "rationale": "Rewrote the Item Listing seed block: same junk-field removal as the "
            "model, 8 items to satisfy the 8-10 pre-seeded item requirement, with the last item "
            "deliberately at quantity 0 for a real out-of-stock example.",
            "maps_to": ["FR-003", "AC-003"],
        },
        {
            "path": "app/api/items/route.ts",
            "action": "modify",
            "rationale": "GET handler serves seed data when connectToDatabase() returns null; "
            "when a real DB is connected and genuinely empty, auto-seeds it via insertMany "
            "before reading (FR-003 for a real connection too, not just the fallback path); "
            "maps Mongoose documents to the shared ItemListingItem shape with inStock computed "
            "from quantity > 0 (FR-DOM-003).",
            "maps_to": ["FR-002", "FR-003", "FR-DOM-003", "AC-002", "AC-003"],
        },
        {
            "path": "lib/mongodb.ts",
            "action": "modify",
            "rationale": "connectToDatabase() now catches a real connection failure (not just an "
            "unset MONGODB_URI) and fails fast via serverSelectionTimeoutMS, degrading to seed "
            "data instead of hanging or throwing a 500 -- a cross-feature fix shared with Login "
            "and Signup.",
            "maps_to": ["NFR-001"],
        },
        {
            "path": "lib/api/itemListing.ts",
            "action": "modify",
            "rationale": "Uses the shared ItemListingResponse type instead of importing the "
            "Mongoose interface directly.",
            "maps_to": ["FR-002"],
        },
        {
            "path": "lib/auth/session.ts",
            "action": "create",
            "rationale": "Minimal shared client-side session marker (localStorage-based), since "
            "Login and Signup's backend never issues a real cookie/JWT session -- this fills "
            "that real gap so FR-001/AC-001's auth gate has something real to check.",
            "maps_to": ["FR-001", "AC-001"],
        },
        {
            "path": "lib/api/loginAndSignup.ts",
            "action": "modify",
            "rationale": "Calls saveSession()/clearSession() on successful login/signup/logout "
            "so the new session marker is actually written.",
            "maps_to": ["FR-001", "AC-001"],
        },
        {
            "path": "app/login-and-signup/page.tsx",
            "action": "modify",
            "rationale": "Replaced a dead no-op useEffect with a real getSession() check so the "
            "Logout link reflects genuine login state.",
            "maps_to": ["FR-001"],
        },
        {
            "path": "app/item-listing/page.tsx",
            "action": "modify",
            "rationale": "Full auth gate via getSession() + redirect to /login-and-signup when "
            "absent (FR-001/AC-001); loading/error/empty/success states faithfully matching the "
            "approved UI/UX design (the approved LoadingIndicator asset was itself mismatched/"
            "off-topic, substituted with a new but design-consistent loading state); success "
            "grid includes a quantity + in-stock/out-of-stock badge row per FR-DOM-003.",
            "maps_to": [
                "FR-001",
                "FR-002",
                "FR-004",
                "FR-005",
                "FR-DOM-003",
                "AC-001",
                "AC-002",
                "AC-004",
                "AC-005",
            ],
        },
        {
            "path": "qa_results_debug.json",
            "action": "delete",
            "rationale": "Debris from an earlier QA run, unreferenced by any code.",
            "maps_to": [],
        },
        {
            "path": "qa_results_debug2.json",
            "action": "delete",
            "rationale": "Debris from an earlier QA run, unreferenced by any code.",
            "maps_to": [],
        },
    ],
    "new_dependencies": [],
    "env_vars_needed": ["MONGODB_URI"],
    "summary": "Completed the Item Listing feature by hand after the Coder Agent's own coding "
    "loop was stopped mid-run: removed junk auto-derived schema fields, added a shared "
    "response type and a shared client-side session marker (filling Login and Signup's real "
    "lack of a server-side session), hardened the DB connection helper to fail fast and "
    "degrade to seed data, and rebuilt the item-listing page with a real auth gate and "
    "loading/error/empty/success states matching the approved UI/UX design.",
}


def main():
    feature = store.features.get(FEATURE_ID)
    project = store.projects.get(PROJECT_ID)
    if feature is None or project is None:
        raise SystemExit(f"Could not find feature={FEATURE_ID} / project={PROJECT_ID} in store")

    srs_json = read_json_file(
        "outputs/finodil/feature-item-listing/02_domain/item_listing_enhanced_srs_v1.json"
    )
    ui_expectations = srs_json.get("ui_expectations")

    branch = workspace_service.ensure_project_repo(PROJECT_ID)
    print(f"Current branch: {branch.active_branch.name}")

    print("Running real sandboxed verify() against the already-committed code...")
    verify_result = coder_agent.verifier.verify(
        PROJECT_ID,
        FEATURE_ID,
        CODE_PLAN,
        original_request=None,
        ui_expectations=ui_expectations,
    )
    print(f"\nverification_passed={verify_result['passed']}")
    for step in verify_result["steps"]:
        print(f"  - {step['name']}: {step['status']}")

    diff = workspace_service.diff_against_main(PROJECT_ID, FEATURE_ID)
    print("\n=== DIFF (file lists only) ===")
    print(json.dumps({k: diff[k] for k in ("added", "modified", "deleted")}, indent=2))

    output = CoderAgentOutput(
        code_plan_json=CODE_PLAN,
        verification_passed=verify_result["passed"],
        file_tree_json=build_file_tree(diff),
        code_manifest_json=build_code_manifest(CODE_PLAN, diff),
        requirement_code_map_json=build_requirement_code_map(CODE_PLAN, diff),
        setup_instructions_markdown=build_setup_instructions_markdown(CODE_PLAN),
        merge_report_markdown=build_merge_report_markdown(
            feature["feature_name"], diff, verify_result, 1
        ),
    )

    output.artifact_ids = coder_agent._save_artifacts(dict(project), dict(feature), output)
    print("\n=== ARTIFACT IDS ===")
    print(output.artifact_ids)


if __name__ == "__main__":
    main()
