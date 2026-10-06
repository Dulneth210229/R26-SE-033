"""
Real end-to-end verification of the MERN -> Next.js migration.

Creates a brand-new project + feature and drives the real pipeline
(Requirement -> Domain -> Architecture -> UI/UX -> Coder), approving each
gating artifact through the real approval_service (same code path as
POST /artifacts/{id}/approval), never by direct store manipulation -- per
this repo's standing convention. Prints the concrete evidence needed to
confirm the SRS, Architecture Plan, and generated code are genuinely
Next.js-shaped (not still MERN-shaped).

Model: pass --model-override <name> to temporarily override every
overridable agent (requirement_agent, domain_agent, architecture_agent,
coder_agent) to that model for this run, restoring each one's PRIOR override
(or clearing it if it had none) when the script exits, even on failure.
Omit --model-override to run with whatever is already configured live in
Mongo (this project's real settings already default coder/requirement/domain
to qwen3-coder-family models, per CLAUDE.md).

Run:
    ./.venv/Scripts/python.exe scripts/run_nextjs_migration_e2e.py --model-override llama3:latest
    ./.venv/Scripts/python.exe scripts/run_nextjs_migration_e2e.py   # real qwen3-coder confirmation run
"""

import argparse
import asyncio
import json
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.architecture_agent.agent import architecture_agent
from app.agents.coder_agent.agent import coder_agent
from app.agents.coder_agent.plan_validator import CodePlanValidationError
from app.agents.domain_agent.agent import domain_agent
from app.agents.requirement_agent.agent import requirement_agent
from app.agents.uiux_agent.agent import uiux_agent
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType, FeatureStatus
from app.schemas.approval_schema import ApprovalRequest
from app.schemas.architecture_schema import ArchitectureAgentRunRequest
from app.schemas.coder_schema import CoderAgentRunRequest
from app.schemas.domain_schema import DomainAgentRunRequest
from app.schemas.llm_schema import AgentLLMOverrideUpdateRequest
from app.schemas.project_schema import ProjectCreateRequest
from app.schemas.requirement_schema import RequirementAgentRunRequest, RequirementBAInput
from app.agents.uiux_agent.schemas import UIUXAgentInput  # noqa: F401 (documents the shape only)
from app.schemas.uiux_schema import UIUXAgentRunRequest
from app.services.approval_service import approval_service
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.services.llm_provider_service import llm_provider_service
from app.services.workspace_service import workspace_service
from app.utils.file_manager import read_json_file
from app.utils.id_generator import generate_id

OVERRIDABLE_AGENTS_FOR_THIS_RUN = [
    AgentName.REQUIREMENT.value,
    AgentName.DOMAIN.value,
    AgentName.ARCHITECTURE.value,
    AgentName.CODER.value,
]


@contextmanager
def temporary_model_override(model_name: str | None):
    """
    Temporarily override every agent in OVERRIDABLE_AGENTS_FOR_THIS_RUN to
    `model_name`, restoring each one's exact prior override (or clearing it
    if it had none) on exit -- even if the run raises. A no-op if
    model_name is None (use whatever is already configured live).
    """
    if not model_name:
        yield
        return

    document = store.llm_settings.get_document()
    prior_overrides = {
        agent_name: dict(document.get("agent_overrides", {}).get(agent_name, {}))
        for agent_name in OVERRIDABLE_AGENTS_FOR_THIS_RUN
    }
    had_override = {
        agent_name: agent_name in (document.get("agent_overrides", {}) or {})
        for agent_name in OVERRIDABLE_AGENTS_FOR_THIS_RUN
    }

    try:
        for agent_name in OVERRIDABLE_AGENTS_FOR_THIS_RUN:
            llm_provider_service.set_agent_override(
                agent_name, AgentLLMOverrideUpdateRequest(provider="ollama", model=model_name)
            )
        print(f"[model override] all agents temporarily set to {model_name}")
        yield
    finally:
        for agent_name in OVERRIDABLE_AGENTS_FOR_THIS_RUN:
            if had_override[agent_name]:
                prior = prior_overrides[agent_name]
                llm_provider_service.set_agent_override(
                    agent_name,
                    AgentLLMOverrideUpdateRequest(
                        provider=prior.get("provider"),
                        model=prior.get("model"),
                        temperature=prior.get("temperature"),
                        max_tokens=prior.get("max_tokens"),
                        timeout_seconds=prior.get("timeout_seconds"),
                    ),
                )
            else:
                llm_provider_service.clear_agent_override(agent_name)
        print("[model override] restored every agent's prior configuration")


def create_project() -> str:
    now = datetime.now(timezone.utc)
    project_id = generate_id("proj")

    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": "NextJS Migration Verify",
        "project_type": "E-commerce",
        "target_stack": "Next.js",
        "created_by": "human_user",
        "created_at": now,
        "updated_at": now,
    }

    print(f"project created: {project_id}")
    return project_id


def create_feature(project_id: str) -> str:
    project = store.projects[project_id]
    now = datetime.now(timezone.utc)
    feature_id = generate_id("feature")

    store.features[feature_id] = {
        "feature_id": feature_id,
        "project_id": project_id,
        "feature_name": "Item Notes",
        "feature_description": (
            "Users can add a short text note to a catalog item and view every note "
            "left on that item, newest first."
        ),
        "feature_status": FeatureStatus.CREATED,
        "current_agent": AgentName.REQUIREMENT,
        "created_at": now,
        "updated_at": now,
    }

    artifact_service.create_feature_artifact_root(
        project_name=project["project_name"],
        feature_name="Item Notes",
    )

    print(f"feature created: {feature_id}")
    return feature_id


def approve(artifact_id: str) -> None:
    response = approval_service.submit_approval(
        artifact_id,
        ApprovalRequest(
            status=ApprovalStatus.APPROVED,
            reviewer_comment="Approved for Next.js migration E2E verification.",
            approved_by="human_user",
        ),
    )
    print(f"  approved: {artifact_id} -> {response.status if response else 'FAILED'}")


def find_artifact(artifact_ids, artifact_type, artifact_format):
    for artifact_id in artifact_ids:
        artifact = store.artifacts.get(artifact_id)
        if not artifact:
            continue
        if artifact.get("artifact_type") in (artifact_type, artifact_type.value) and \
           artifact.get("artifact_format") in (artifact_format, artifact_format.value):
            return artifact_id, artifact
    return None, None


def find_all_artifacts(artifact_ids, artifact_type, artifact_format):
    results = []
    for artifact_id in artifact_ids:
        artifact = store.artifacts.get(artifact_id)
        if not artifact:
            continue
        if artifact.get("artifact_type") in (artifact_type, artifact_type.value) and \
           artifact.get("artifact_format") in (artifact_format, artifact_format.value):
            results.append((artifact_id, artifact))
    return results


async def main(model_override: str | None, resume_project_id: str | None, resume_feature_id: str | None) -> None:
    with temporary_model_override(model_override):
        if resume_project_id and resume_feature_id:
            project_id = resume_project_id
            feature_id = resume_feature_id
            print(f"resuming existing project_id={project_id} feature_id={feature_id} "
                  "(skipping Requirement/Domain/Architecture/UI-UX -- already completed)")
            await run_coder_step(project_id, feature_id)
            return

        project_id = create_project()
        feature_id = create_feature(project_id)

        print("\n=== Step 1: Requirement Agent ===")
        requirement_response = await requirement_agent.run(
            feature_id,
            RequirementAgentRunRequest(
                ba_input=RequirementBAInput(
                    project_type="E-commerce",
                    feature_name="Item Notes",
                    target_stack="Next.js",
                    architectural_style="modular",
                    user_roles=["Registered User"],
                    feature_description=(
                        "Users can add a short text note to a catalog item (max 500 "
                        "characters) and view every note left on that item, newest first. "
                        "Each note shows its author and timestamp. An item with no notes "
                        "shows a clear empty state."
                    ),
                )
            ),
        )
        print("requirement status:", requirement_response.status)
        srs_artifact_id, srs_artifact = find_artifact(
            requirement_response.artifact_ids, ArtifactType.SRS, ArtifactFormat.JSON
        )
        if not srs_artifact_id:
            raise SystemExit("No SRS JSON artifact produced -- aborting.")
        srs_json = read_json_file(srs_artifact["file_path"])
        print("  target_stack:", srs_json.get("target_stack"))
        print("  api_expectations:", srs_json.get("api_expectations"))
        approve(srs_artifact_id)

        print("\n=== Step 2: Domain Agent ===")
        domain_response = await domain_agent.run(feature_id, DomainAgentRunRequest())
        print("domain status:", domain_response.status)
        enhanced_srs_artifact_id, enhanced_srs_artifact = find_artifact(
            domain_response.artifact_ids, ArtifactType.ENHANCED_SRS, ArtifactFormat.JSON
        )
        if not enhanced_srs_artifact_id:
            raise SystemExit("No Enhanced SRS JSON artifact produced -- aborting.")
        enhanced_srs_json = read_json_file(enhanced_srs_artifact["file_path"])
        print("  target_stack:", enhanced_srs_json.get("target_stack"))
        approve(enhanced_srs_artifact_id)

        print("\n=== Step 3: Architecture Agent ===")
        architecture_response = await architecture_agent.run(feature_id, ArchitectureAgentRunRequest())
        print("architecture status:", architecture_response.status)
        plan_artifact_id, plan_artifact = find_artifact(
            architecture_response.artifact_ids, ArtifactType.ARCHITECTURE_PLAN, ArtifactFormat.JSON
        )
        if not plan_artifact_id:
            plan_artifact_id, plan_artifact = find_artifact(
                architecture_response.artifact_ids, ArtifactType.SDS, ArtifactFormat.JSON
            )
        if not plan_artifact_id:
            raise SystemExit("No Architecture Plan JSON artifact produced -- aborting.")
        plan = read_json_file(plan_artifact["file_path"])
        implementation_plan = plan.get("implementation_plan", {})
        backend = implementation_plan.get("backend", {})
        frontend = implementation_plan.get("frontend", {})
        print("  backend files:", [f.get("path") for f in backend.get("files", [])])
        print("  endpoints:", [f"{e.get('method')} {e.get('path')}" for e in backend.get("endpoints", [])])
        print("  models:", [(m.get("name"), m.get("file")) for m in backend.get("models", [])])
        print("  pages:", [p.get("path") for p in frontend.get("pages", [])])
        print("  implementation_order:")
        for step in implementation_plan.get("implementation_order", []):
            print("   -", step)
        mount_step_present = any(
            "mount" in step.lower() and "router" in step.lower()
            for step in implementation_plan.get("implementation_order", [])
        )
        print("  [check] no 'mount the router' step present:", not mount_step_present)
        approve(plan_artifact_id)

        print("\n=== Step 4: UI/UX Agent ===")
        uiux_response = await uiux_agent.run(feature_id, UIUXAgentRunRequest())
        print("uiux artifact_ids:", uiux_response.artifact_ids)
        await approve_uiux_and_run_coder(project_id, feature_id, uiux_response.artifact_ids)


async def approve_uiux_and_run_coder(project_id: str, feature_id: str, uiux_artifact_ids: list[str]) -> None:
    metadata_artifact_id, _ = find_artifact(
        uiux_artifact_ids, ArtifactType.UI_METADATA, ArtifactFormat.JSON
    )
    if metadata_artifact_id:
        approve(metadata_artifact_id)
    component_artifacts = find_all_artifacts(
        uiux_artifact_ids, ArtifactType.UI_COMPONENT_CODE, ArtifactFormat.CODE
    )
    print(f"  approving {len(component_artifacts)} UI component artifact(s) individually:")
    for component_artifact_id, component_artifact in component_artifacts:
        print("   -", component_artifact.get("file_path"))
        approve(component_artifact_id)

    print("\n=== Step 5: Coder Agent ===")
    try:
        coder_response = await coder_agent.run(feature_id, CoderAgentRunRequest())
        print("verification_passed:", coder_response.verification_passed)
    except CodePlanValidationError as error:
        print("CODER AGENT PLANNING FAILED (real, pre-existing planner reliability gap, not a "
              "migration bug -- see CLAUDE.md):")
        print(" ", error)
        print(f"\nfeature_id for manual follow-up: {feature_id}")
        print(f"project_id for manual follow-up: {project_id}")
        return

    repo_path = workspace_service.get_repo_path(project_id)
    print("\n=== Generated file spot-checks ===")
    for candidate in [
        "package.json", "next.config.ts", "tsconfig.json",
        "app/layout.tsx", "app/page.tsx", "app/globals.css", "lib/mongodb.ts",
    ]:
        print(f"  {candidate}: {'present' if (repo_path / candidate).exists() else 'MISSING'}")

    app_page = (repo_path / "app" / "page.tsx")
    if app_page.exists():
        content = app_page.read_text(encoding="utf-8")
        print("  app/page.tsx has a real <Link href> inside FEATURE_LINKS markers:",
              "<Link href=" in content)

    print("\n  verify_result / merge report:")
    code_diff_artifact_id, code_diff_artifact = find_artifact(
        coder_response.artifact_ids, ArtifactType.CODE_DIFF, ArtifactFormat.MARKDOWN
    )
    if code_diff_artifact:
        print(Path(code_diff_artifact["file_path"]).read_text(encoding="utf-8")[:4000])

    print(f"\nfeature_id for manual follow-up: {feature_id}")
    print(f"project_id for manual follow-up: {project_id}")


async def run_coder_step(project_id: str, feature_id: str) -> None:
    """
    Resume path: UI/UX Agent already ran and saved its artifacts in a prior
    invocation -- look them up fresh from the store (still pending, since
    the prior run crashed before approving them) instead of re-running the
    agent and burning more real LLM time.
    """
    uiux_artifact_ids = [
        artifact["artifact_id"]
        for artifact in store.artifacts.values()
        if artifact.get("feature_id") == feature_id
        and artifact.get("agent_name") in (AgentName.UIUX, AgentName.UIUX.value)
    ]
    await approve_uiux_and_run_coder(project_id, feature_id, uiux_artifact_ids)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-override", default=None, help="e.g. llama3:latest")
    parser.add_argument("--resume-project-id", default=None)
    parser.add_argument("--resume-feature-id", default=None)
    args = parser.parse_args()

    try:
        asyncio.run(main(args.model_override, args.resume_project_id, args.resume_feature_id))
    except Exception:
        traceback.print_exc()
        raise
