"""
Real end-to-end verification of the upgraded Architecture Agent (Milestone 5
of the Architecture Agent upgrade) against the live TaskFlow project.

Creates a NEW feature ("Task Search") on proj_53284a63 -- a project that
already has an approved Architecture Plan (Task Comments) and a real
workspace -- so this genuinely exercises:
- the agentic, tool-using generation rung (reading the previous plan, the
  project manifest, and real workspace code),
- the new implementation_plan schema end-to-end,
- diagram artifacts still rendering unchanged,
- the reliability ladder if the agentic rung fails.

Approval of the intermediate SRS goes through the real approval_service
(the same code path as POST /artifacts/{id}/approval), never by direct
store manipulation -- per this repo's standing convention.

Run:
    ./.venv/Scripts/python.exe scripts/run_taskflow_architecture_e2e.py
"""

import asyncio
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, r"c:\Users\ASUS\Documents\GitHub\Auto-Forge-MAS\services\agentic_service")

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.requirement_agent.agent import RequirementAgent
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType, FeatureStatus
from app.schemas.approval_schema import ApprovalRequest
from app.schemas.architecture_schema import ArchitectureAgentRunRequest
from app.schemas.requirement_schema import RequirementAgentRunRequest, RequirementBAInput
from app.services.approval_service import approval_service
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id
from app.utils.file_manager import read_json_file

PROJECT_ID = "proj_53284a63"  # TaskFlow


def create_feature() -> str:
    project = store.projects[PROJECT_ID]
    now = datetime.now(timezone.utc)
    feature_id = generate_id("feature")

    store.features[feature_id] = {
        "feature_id": feature_id,
        "project_id": PROJECT_ID,
        "feature_name": "Task Search",
        "feature_description": (
            "Search tasks by keyword in their title or description, showing "
            "matching tasks as a list with links to each task's detail page."
        ),
        "feature_status": FeatureStatus.CREATED,
        "current_agent": AgentName.REQUIREMENT,
        "created_at": now,
        "updated_at": now,
    }

    artifact_service.create_feature_artifact_root(
        project_name=project["project_name"],
        feature_name="Task Search",
    )

    print(f"feature created: {feature_id}")
    return feature_id


def approve(artifact_id: str) -> None:
    response = approval_service.submit_approval(
        artifact_id,
        ApprovalRequest(
            status=ApprovalStatus.APPROVED,
            reviewer_comment="Approved for Architecture Agent E2E verification.",
            approved_by="human_user",
        ),
    )
    print(f"approved: {artifact_id} -> {response.status if response else 'FAILED'}")


def find_artifact(artifact_ids, artifact_type, artifact_format):
    for artifact_id in artifact_ids:
        artifact = store.artifacts.get(artifact_id)
        if not artifact:
            continue
        if artifact.get("artifact_type") in (artifact_type, artifact_type.value) and \
           artifact.get("artifact_format") in (artifact_format, artifact_format.value):
            return artifact_id, artifact
    return None, None


async def main() -> None:
    feature_id = create_feature()

    print("\n=== Step 1: real Requirement Agent ===")
    requirement_response = await RequirementAgent().run(
        feature_id,
        RequirementAgentRunRequest(
            ba_input=RequirementBAInput(
                project_type="SaaS",
                feature_name="Task Search",
                target_stack="MERN",
                architectural_style="modular",
                user_roles=["Registered User"],
                feature_description=(
                    "Users can search their tasks by keyword. Matching is against task "
                    "title and description. Results show as a list of matching tasks, "
                    "each linking to that task's detail page. An empty query shows a "
                    "prompt to type a search term; no matches shows a clear empty state."
                ),
            )
        ),
    )
    print("requirement status:", requirement_response.status)

    srs_artifact_id, _ = find_artifact(
        requirement_response.artifact_ids, ArtifactType.SRS, ArtifactFormat.JSON
    )
    if not srs_artifact_id:
        raise SystemExit("No SRS JSON artifact produced -- aborting.")
    approve(srs_artifact_id)

    print("\n=== Step 2: real Architecture Agent (upgraded) ===")
    architecture_response = await ArchitectureAgent().run(
        feature_id, ArchitectureAgentRunRequest()
    )
    print("architecture status:", architecture_response.status)
    print("artifact_ids:", architecture_response.artifact_ids)

    plan_artifact_id, plan_artifact = find_artifact(
        architecture_response.artifact_ids, ArtifactType.ARCHITECTURE_PLAN, ArtifactFormat.JSON
    )
    plan = read_json_file(plan_artifact["file_path"])

    print("\n=== Verification summary ===")
    implementation_plan = plan.get("implementation_plan", {})
    print("implementation_plan present:", bool(implementation_plan))
    backend = implementation_plan.get("backend", {})
    print("backend files:", [f.get("path") for f in backend.get("files", [])])
    print("endpoints:", [f"{e.get('method')} {e.get('path')}" for e in backend.get("endpoints", [])])
    print("models:", [m.get("name") for m in backend.get("models", [])])
    frontend = implementation_plan.get("frontend", {})
    print("pages:", [p.get("path") for p in frontend.get("pages", [])])
    print("implementation_order steps:", len(implementation_plan.get("implementation_order", [])))
    print("human_approval_note:", plan.get("human_approval_note", "")[:300])

    print("\ndiagram artifacts saved:")
    for artifact_id in architecture_response.artifact_ids:
        artifact = store.artifacts.get(artifact_id, {})
        print(f"  {artifact.get('artifact_type')} ({artifact.get('artifact_format')}): {artifact.get('file_path')}")

    print(f"\nfeature_id for follow-up: {feature_id}")
    print(f"plan artifact for review/approval: {plan_artifact_id}")


if __name__ == "__main__":
    asyncio.run(main())
