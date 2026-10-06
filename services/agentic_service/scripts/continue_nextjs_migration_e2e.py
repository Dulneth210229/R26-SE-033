"""
Continuation of run_nextjs_migration_e2e.py for proj_3b717019 / feature_66e1362f:
Requirement + Domain Agent already completed and were approved for real
(target_stack: Next.js confirmed for both). Architecture Agent's real call
hit a confirmed, severe real hardware issue -- `qwen3-coder.max:latest` (this
project's live per-agent override for architecture_agent) took over 3.5
hours for a single call before timing out, matching this project's own
previously-documented GPU/VRAM-mismatch finding (CLAUDE.md item 29) for this
exact class of 30B model on a 6GB GPU.

Since the user's explicit request was that the CODER AGENT's output use
qwen3-coder specifically (not necessarily every agent), this continuation
temporarily overrides ONLY architecture_agent to llama3:latest (the same,
already-established fix from item 29) for this run, restoring its exact
prior override afterward. requirement_agent/domain_agent/coder_agent are
left on their already-configured live defaults (qwen3-coder-family).

Run:
    ./.venv/Scripts/python.exe scripts/continue_nextjs_migration_e2e.py
"""

import asyncio
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.architecture_agent.agent import architecture_agent
from app.agents.uiux_agent.agent import uiux_agent
from app.core.enums import ArtifactFormat, ArtifactType
from app.schemas.architecture_schema import ArchitectureAgentRunRequest
from app.schemas.llm_schema import AgentLLMOverrideUpdateRequest
from app.schemas.uiux_schema import UIUXAgentRunRequest
from app.services.in_memory_store import store
from app.services.llm_provider_service import llm_provider_service
from app.services.workspace_service import workspace_service
from app.utils.file_manager import read_json_file

from run_nextjs_migration_e2e import (  # noqa: E402
    approve,
    approve_uiux_and_run_coder,
    find_artifact,
    temporary_model_override,
)

PROJECT_ID = "proj_3b717019"
FEATURE_ID = "feature_66e1362f"


async def main() -> None:
    document = store.llm_settings.get_document()
    prior_architecture_override = dict(document.get("agent_overrides", {}).get("architecture_agent", {}))
    had_override = "architecture_agent" in (document.get("agent_overrides", {}) or {})

    try:
        llm_provider_service.set_agent_override(
            "architecture_agent", AgentLLMOverrideUpdateRequest(provider="ollama", model="llama3:latest")
        )
        print("[model override] architecture_agent temporarily set to llama3:latest")

        print("\n=== Step 3: Architecture Agent ===")
        architecture_response = await architecture_agent.run(FEATURE_ID, ArchitectureAgentRunRequest())
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
    finally:
        if had_override:
            llm_provider_service.set_agent_override(
                "architecture_agent",
                AgentLLMOverrideUpdateRequest(
                    provider=prior_architecture_override.get("provider"),
                    model=prior_architecture_override.get("model"),
                    temperature=prior_architecture_override.get("temperature"),
                    max_tokens=prior_architecture_override.get("max_tokens"),
                    timeout_seconds=prior_architecture_override.get("timeout_seconds"),
                ),
            )
        else:
            llm_provider_service.clear_agent_override("architecture_agent")
        print("[model override] restored architecture_agent's prior configuration")

    print("\n=== Step 4: UI/UX Agent ===")
    uiux_response = await uiux_agent.run(FEATURE_ID, UIUXAgentRunRequest())
    print("uiux artifact_ids:", uiux_response.artifact_ids)
    await approve_uiux_and_run_coder(PROJECT_ID, FEATURE_ID, uiux_response.artifact_ids)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        traceback.print_exc()
        raise
