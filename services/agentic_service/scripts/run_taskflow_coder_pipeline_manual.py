"""
Manual verification script for the Coder Agent's coding/verify/diff/save
pipeline against the real TaskFlow project / Task Comments feature.

Same rationale and pattern as scripts/run_coder_pipeline_manual.py: the real
planner reliably fails plan_validator for this feature (confirmed twice,
identically -- see CLAUDE.md item 19) because the Architecture Agent's
deterministic fallback plan has crude data (a single literal endpoint string
duplicated across 3 near-identical GET entries, and each requested field
split into its own oddly-named "entity"). This bypasses _plan_with_retries
with a hand-validated plan that still covers every literal string
plan_validator requires, but designs the actual routes/model sensibly
(matching the SRS's real api_expectations: POST/GET/DELETE, one Comment
model) rather than the fallback's literal (nonsensical) shape.

Run with:
    PYTHONPATH=. .venv/Scripts/python.exe scripts/run_taskflow_coder_pipeline_manual.py
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

PROJECT_ID = "proj_53284a63"
FEATURE_ID = "feature_5521adbd"

VALIDATED_CODE_PLAN = {
    "files": [
        {
            "path": "server/src/models/Comment.js",
            "action": "create",
            "rationale": "Mongoose model for a task comment: text, author, task reference, "
            "created timestamp -- covers all four data entities the Architecture Plan split "
            "out separately (they are all fields of the same real-world Comment record).",
            "maps_to": [
                "Task CommentsDataEntity1",
                "Task CommentsDataEntity2",
                "Task CommentsDataEntity3",
                "Task CommentsDataEntity4",
                "FR-001",
                "FR-004",
            ],
        },
        {
            "path": "server/src/routes/task-comments.routes.js",
            "action": "create",
            "rationale": "Real REST routes for task comments: POST to create, GET to list "
            "chronologically, DELETE to remove a comment the requester authored. The "
            "Architecture Plan's fallback only ever wrote a single duplicated GET endpoint "
            "string ('/api/task-comments') with no method differentiation -- this plans the "
            "SRS's actual api_expectations (POST/GET/DELETE) while still covering that literal "
            "endpoint string for traceability.",
            "maps_to": ["/api/task-comments", "FR-001", "FR-002", "FR-003", "FR-004"],
        },
        {
            "path": "server/src/app.js",
            "action": "modify",
            "rationale": "Mount the new task-comments router at the FEATURE_ROUTES_END marker.",
            "maps_to": [],
        },
        {
            "path": "client/src/components/CommentInput.jsx",
            "action": "modify",
            "rationale": "The approved UI/UX component's submit handler currently hardcodes a "
            "fake setTimeout-based 'mock submission' with a comment saying 'in real app this "
            "would be an API call' -- integrate it for real: accept an onSubmit(taskId, text) "
            "prop and call it instead of the mock, keeping the existing markup/styling intact.",
            "maps_to": ["FR-001"],
        },
        {
            "path": "client/src/components/CommentList.jsx",
            "action": "modify",
            "rationale": "The approved UI/UX component's delete button has no onClick handler "
            "at all -- add an onDelete(commentId) prop and wire the existing delete button to "
            "call it, keeping the existing markup/styling intact.",
            "maps_to": ["FR-003"],
        },
        {
            "path": "client/src/services/taskCommentsService.js",
            "action": "create",
            "rationale": "Real frontend API calls to the task-comments endpoints (list, add, "
            "delete) -- the functions TaskDetailPage/CommentInput/CommentList actually call.",
            "maps_to": ["FR-001", "FR-002", "FR-003"],
        },
        {
            "path": "client/src/pages/TaskDetailPage.jsx",
            "action": "create",
            "rationale": "Host CommentList and CommentInput for a given task: fetch real "
            "comments on mount via taskCommentsService, pass real props (comments, "
            "currentUser, state) to CommentList, wire CommentInput's onSubmit and "
            "CommentList's onDelete to the real service calls and refresh state afterward.",
            "maps_to": ["FR-001", "FR-002", "FR-003", "FR-004"],
        },
        {
            "path": "client/src/App.jsx",
            "action": "modify",
            "rationale": "Add a /tasks/:taskId route to TaskDetailPage.",
            "maps_to": [],
        },
    ],
    "new_dependencies": [],
    "env_vars_needed": [],
    "summary": "Full-stack Task Comments implementation: a Comment model, real REST routes "
    "(create/list/delete), and real wiring of the approved CommentInput/CommentList UI/UX "
    "components (replacing their placeholder fake/no-op logic with real service calls) via "
    "a new TaskDetailPage.",
}


async def main():
    feature = store.features.get(FEATURE_ID)
    project = store.projects.get(PROJECT_ID)

    srs_json = read_json_file(
        "outputs/taskflow/feature-task-comments/01_requirements/task_comments_srs_v2.json"
    )
    architecture_plan_json = read_json_file(
        "outputs/taskflow/feature-task-comments/03_architecture/task_comments_architecture_plan_v1.json"
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
