"""
M4 manual verification script: run the Coder Agent's agentic loop against a
validated code plan and inspect the resulting git diff by hand.

This is deliberately NOT a pytest test -- this milestone's own success
criterion is "run it manually... and inspect the resulting diff by hand
before trusting any automation around it" (verify/build/test automation is
M5's job). Run with:

    PYTHONPATH=. .venv/Scripts/python.exe scripts/run_coder_loop_manual.py
"""

import asyncio
import json

from app.agents.coder_agent.coding_loop import build_coder_react_agent, build_task_message
from app.agents.coder_agent.plan_validator import CodePlanValidationError, code_plan_validator
from app.services.workspace_service import workspace_service
from app.utils.file_manager import read_json_file

PROJECT_ID = "proj_a2e3d529"
FEATURE_ID = "feature_a44033b8"

# Hand-completed plan from M3's final sanity check -- already proven to pass
# CodePlanValidator on its own (the real planner's own output kept omitting
# backend files across 3 attempts; see CLAUDE.md). M4 proves the loop
# correctly executes an already-validated plan, not the planner's reliability.
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
    "new_dependencies": ["axios", "jwt-decode", "bcrypt"],
    "env_vars_needed": ["JWT_SECRET"],
    "summary": "Full-stack login implementation: frontend page/component/service wiring the "
    "approved LoginForm, backend auth routes, and the User Credentials model.",
}


def print_message_trace(messages) -> None:
    print("\n=== MESSAGE TRACE ===")
    for message in messages:
        kind = type(message).__name__
        tool_calls = getattr(message, "tool_calls", None)
        content = getattr(message, "content", "")

        if tool_calls:
            print(f"[{kind}] tool_calls={tool_calls}")
        else:
            preview = content if len(content) <= 500 else content[:500] + "... (truncated)"
            print(f"[{kind}] {preview}")


async def run_once():
    agent = build_coder_react_agent(PROJECT_ID, FEATURE_ID)
    task_message = build_task_message(VALIDATED_CODE_PLAN)

    result = await agent.ainvoke(
        {"messages": [{"role": "user", "content": task_message}]},
        config={"recursion_limit": 50},
    )

    return result["messages"]


async def main():
    # Sanity-check the plan really is valid before spending an LLM run on it.
    srs_json = read_json_file(
        "outputs/e-commerce-platform/feature-login/01_requirements/SRS_v3.json"
    )
    architecture_plan_json = read_json_file(
        "outputs/e-commerce-platform/feature-login/03_architecture/login_sds_v5.json"
    )
    try:
        code_plan_validator.validate(srs_json, architecture_plan_json, VALIDATED_CODE_PLAN)
        print("Plan validation: PASSED")
    except CodePlanValidationError as error:
        print("Plan validation: FAILED -- aborting.")
        print(error)
        return

    branch_name = workspace_service.start_feature_branch(PROJECT_ID, FEATURE_ID)
    print(f"Workspace branch: {branch_name}")

    messages = await run_once()
    print_message_trace(messages)

    committed = workspace_service.commit_changes(
        PROJECT_ID, FEATURE_ID, message="Coder Agent: implement Login feature"
    )
    print(f"\nCommitted changes: {committed}")

    diff = workspace_service.diff_against_main(PROJECT_ID, FEATURE_ID)
    print("\n=== DIFF AGAINST MAIN ===")
    print(json.dumps({"added": diff["added"], "modified": diff["modified"], "deleted": diff["deleted"]}, indent=2))
    print("\n--- diff_text ---")
    print(diff["diff_text"])


if __name__ == "__main__":
    asyncio.run(main())
