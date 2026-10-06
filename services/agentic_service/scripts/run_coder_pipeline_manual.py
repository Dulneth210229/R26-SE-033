"""
M5 manual verification script: exercise CoderAgent's coding/verify/diff/save
pipeline using the same hand-validated plan from M3/M4 (the real planner
still reliably omits backend files even with the M5 validation-retry loop --
see CLAUDE.md -- so this bypasses _plan_with_retries specifically to prove
everything downstream of a valid plan works correctly).

Run with:
    PYTHONPATH=. .venv/Scripts/python.exe scripts/run_coder_pipeline_manual.py
"""

import asyncio
import json

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

PROJECT_ID = "proj_a2e3d529"
FEATURE_ID = "feature_a44033b8"

VALIDATED_CODE_PLAN = {
    "files": [
        {
            "path": "client/src/pages/LoginPage.jsx",
            "action": "create",
            "rationale": "Host the approved LoginForm component and route /login to it.",
            "maps_to": ["login-page"],
        },
        {
            "path": "client/src/components/LoginForm.jsx",
            "action": "create",
            "rationale": "The approved UI/UX component for the login form -- integrate the "
            "exact approved file via read_ui_component, do not rewrite its markup.",
            "maps_to": ["LoginForm"],
        },
        {
            "path": "client/src/services/authService.js",
            "action": "create",
            "rationale": "Frontend API calls to the login/forgot-password endpoints.",
            "maps_to": ["FR-001", "FR-002", "FR-003", "FR-004"],
        },
        {
            "path": "server/src/routes/auth.routes.js",
            "action": "create",
            "rationale": "Backend routes implementing /api/auth/login and /api/auth/forgot-password.",
            "maps_to": ["/api/auth/login", "/api/auth/forgot-password"],
        },
        {
            "path": "server/src/models/UserCredentials.js",
            "action": "create",
            "rationale": "Mongoose model for the User Credentials data entity.",
            "maps_to": ["User Credentials"],
        },
    ],
    "new_dependencies": ["axios", "jwt-decode", "bcrypt", "jsonwebtoken"],
    "env_vars_needed": ["JWT_SECRET"],
    "summary": "Full-stack login implementation: frontend page/component/service wiring the "
    "approved LoginForm, backend auth routes, and the User Credentials model.",
}


async def main():
    feature = store.features.get(FEATURE_ID)
    project = store.projects.get(PROJECT_ID)

    srs_json = read_json_file(
        "outputs/e-commerce-platform/feature-login/01_requirements/SRS_v3.json"
    )
    architecture_plan_json = read_json_file(
        "outputs/e-commerce-platform/feature-login/03_architecture/login_sds_v5.json"
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
    print("\n=== DIFF ===")
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
