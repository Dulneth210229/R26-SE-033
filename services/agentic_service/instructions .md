# Auto-Forge MAS — Build Instructions

**Audience:** Claude Code, working directly in this repository.
**Purpose:** This document is the implementation plan for extending the existing Auto-Forge MAS backend (`services/agentic_service`) with a real LangGraph orchestration layer, a working UI/UX Agent, and a working Coder Agent built as a LangGraph tool-using subgraph. Security and QA agents are stubbed for now and wired into the graph as no-op pass-through nodes so the pipeline is end-to-end runnable today and swappable later.

Read this whole document before writing code. Sections are ordered as build milestones — implement them in order. Do not skip the "Foundation" milestone; both new agents depend on it.

---

## 0. Ground truth: what already exists

Before changing anything, this is the actual current state of the repo (verified by inspection, not assumed):

| Component | State | Notes |
|---|---|---|
| `requirement_agent` | **Implemented** | LLM → `srs_json` + `srs_markdown`, saved as versioned artifacts |
| `domain_agent` | **Stub** (`raise NotImplementedError`) | Config for RAG (ChromaDB + `sentence-transformers`) already exists in `core/config.py` but agent body is not written |
| `architecture_agent` | **Implemented** | Produces SDS JSON/MD + use case, sequence, and class diagrams (PlantUML → PNG). Uses a `modeler → validator → builder → renderer` pattern split across separate files |
| `uiux_agent` | **Stub** | Schema already sketched: outputs `ui_design_markdown`, `ui_metadata_json`, `html_tailwind`, optional `react_component` |
| `coder_agent` | **Stub** | Schema already sketched: outputs `file_tree_json`, `code_manifest_json`, `requirement_code_map_json`, `setup_instructions_markdown`, `merge_report_markdown`. Prompt already says **MERN stack**, patch-based, preserve previous features |
| `deployment_agent` | **Stub** | Out of scope for this document |
| `security_agent`, `qa_agent` | **Do not exist yet** | We will create empty placeholder modules only |
| Persistence | **MongoDB**, already wired | `services/in_memory_store.py` is MongoDB-backed despite its filename (kept for import compatibility). Collections: `projects`, `features`, `artifacts`, `approvals`, `llm_settings` |
| Orchestration | **Manual FastAPI**, no LangGraph | `requirements.txt` has no `langgraph`/`langchain`. Each agent is a REST endpoint under `/features/{feature_id}/agents/...`; approval is a flag on an artifact (`approval_status`), checked via `artifact_service.get_latest_approved_artifact()` |
| Artifact storage | `outputs/{project_slug}/feature-{feature_slug}/{stage_folder}/` | `ArtifactService.STAGE_FOLDER_MAP` maps `AgentName` → folder (`01_requirements`, `02_domain`, `03_architecture`, `04_uiux`, `05_code`, `06_deployment`) |
| LLM providers | `BaseLLMProvider` (Ollama, OpenAI) | **One-shot only** — `generate()`/`stream()`/`invoke_agent()`. No tool-calling loop anywhere in the codebase yet |

**Two decisions this document makes, stated up front:**

1. **We introduce LangGraph as a real orchestrator now**, not just for the Coder Agent. A top-level `StateGraph` will run the whole per-feature pipeline (Requirement → Domain → Architecture → UI/UX → Coder → Security → QA), using `interrupt()` for every human approval gate, checkpointed in the MongoDB instance you already run. This replaces the current "call each endpoint manually" flow with a graph the FastAPI layer drives. Your existing per-agent logic (the modeler/validator/builder functions) is **reused**, not thrown away — it becomes the body of a graph node.
2. **The one-shot `BaseLLMProvider` stays** for Requirement/Domain/Architecture (they don't need tool calling). A **new**, separate model factory using LangChain's `init_chat_model` is added specifically for agentic (tool-calling) nodes — currently only the Coder Agent. This keeps your Ollama/OpenAI/Anthropic provider-agnostic design intact for both code paths.

---

## 1. Tech stack additions

Add to `requirements.txt`:

```
langgraph>=0.6
langgraph-checkpoint-mongodb
langchain>=0.3
langchain-core
langchain-anthropic
langchain-openai
langchain-ollama
gitpython
playwright
ripgrepy          # or shell out to system `rg` directly — see §5.4
docker             # python docker SDK, for sandboxed run_shell
```

Run `playwright install chromium` once during setup (used for UI preview screenshots).

**Model/provider policy for this build:**
- Requirement / Domain / Architecture agents → keep using `llm_provider_service` (`BaseLLMProvider`), unchanged.
- UI/UX Agent → one-shot structured-JSON calls (no tools needed) → also use `llm_provider_service`, same as Architecture Agent.
- Coder Agent → **tool-calling required** → use `langchain.chat_models.init_chat_model`, configured from the same `store.llm_settings` document so switching provider in one place still works. `init_chat_model` supports Anthropic, OpenAI, and Ollama by model string, so this does not fork your provider abstraction into two unrelated systems — it's one more consumer of the same settings.

---

## 2. Why the two remaining agents need a different shape

Your Requirement/Domain/Architecture pattern is: **LLM emits JSON → validator checks coverage → deterministic builder renders Markdown/PlantUML → done.** That works because a spec doesn't need to execute. Code does. A single LLM call that emits an entire feature's file contents as one JSON blob cannot see whether imports resolve, whether a previous feature already defined that route, or whether the result even runs — and it has no way to correct itself.

So the Coder Agent needs an **agentic loop**: act (write/edit a file) → observe (lint/build/test result or file content) → correct → repeat, with a hard stop condition. That loop, wired with real tools, is what "build it like Claude Code" actually means architecturally — it is not a different model, it's a different control structure.

The UI/UX Agent doesn't need a full agentic loop, but it does need to stop being a single free-form generation, for a different reason: **fidelity**. If the UI/UX Agent just writes HTML/Tailwind text and the Coder Agent later "reinterprets" it into React, you get drift between what the human approved and what ships. The fix is structural: make the thing the human approves the same file that ships.

---

## 3. Foundation work (build this first — Milestone 0)

Everything below is shared infrastructure both new agents depend on. Do not start the UI/UX or Coder agent implementation until this milestone is done and tested in isolation.

### 3.1 New enums

Edit `app/core/enums.py`:

```python
class AgentName(str, Enum):
    REQUIREMENT = "requirement_agent"
    DOMAIN = "domain_agent"
    ARCHITECTURE = "architecture_agent"
    UIUX = "uiux_agent"
    CODER = "coder_agent"
    SECURITY = "security_agent"      # NEW
    QA = "qa_agent"                  # NEW
    DEPLOYMENT = "deployment_agent"

class ArtifactType(str, Enum):
    SRS = "srs"
    ENHANCED_SRS = "enhanced_srs"
    ARCHITECTURE_PLAN = "architecture_plan"
    SDS = "sds"
    USE_CASE_DIAGRAM = "use_case_diagram"
    SEQUENCE_DIAGRAM = "sequence_diagram"
    CLASS_DIAGRAM = "class_diagram"
    ARCHITECTURE_TRACEABILITY = "architecture_traceability"

    # UI/UX Agent — NEW
    UI_METADATA = "ui_metadata"            # design tokens + component tree JSON
    UI_COMPONENT_CODE = "ui_component_code"  # actual .jsx/.tsx files
    UI_PREVIEW_SCREENSHOT = "ui_preview_screenshot"
    DESIGN_SYSTEM = "design_system"        # project-level, cross-feature

    # Coder Agent — NEW
    CODE_PLAN = "code_plan"
    CODE_DIFF = "code_diff"
    CODE_MANIFEST = "code_manifest"
    REQUIREMENT_CODE_MAP = "requirement_code_map"
    SETUP_INSTRUCTIONS = "setup_instructions"
    PROJECT_MANIFEST = "project_manifest"  # project-level, cross-feature

    # Security / QA — NEW (placeholders for now)
    SECURITY_REPORT = "security_report"
    QA_REPORT = "qa_report"

    UI_DESIGN = "ui_design"
    CODE = "code"
    DEPLOYMENT = "deployment"
```

Edit `app/services/artifact_service.py` → `STAGE_FOLDER_MAP`:

```python
STAGE_FOLDER_MAP = {
    AgentName.REQUIREMENT: "01_requirements",
    AgentName.DOMAIN: "02_domain",
    AgentName.ARCHITECTURE: "03_architecture",
    AgentName.UIUX: "04_uiux",
    AgentName.CODER: "05_code",
    AgentName.SECURITY: "06_security",   # NEW
    AgentName.QA: "07_qa",               # NEW
    AgentName.DEPLOYMENT: "08_deployment",
}
```

### 3.2 Project-level artifacts (cross-feature memory)

Your current artifact model is **feature-scoped** (`outputs/{project}/feature-{name}/...`). Both new agents need something **project-scoped** that persists across features, or every feature will reinvent colors, components, routes, and models from zero, and "preserve previous features" stays a hope instead of a mechanism.

Add two project-level, singleton-per-project JSON documents, stored the same way as other artifacts but keyed by `project_id` with no `feature_id`, or as plain JSON files at `outputs/{project_slug}/_project/`:

- **`design_system.json`** (owned by UI/UX Agent) — color palette, typography scale, spacing scale, and the registry of shared base components already built (`Button`, `Input`, `Card`, `Navbar`, etc.) with their file paths and prop signatures.
- **`project_manifest.json`** (owned by Coder Agent) — registry of what already exists in the codebase: routes, API endpoints, Mongoose/Express models, shared components consumed, feature → files-touched map. This is your **repo map**: cheap, structured, and always accurate because it is written deterministically after each successful merge, not inferred by an LLM.

Both files are read (never blindly overwritten) at the start of every feature run and updated only after human approval of that feature's output. Add a small `ProjectMemoryService` in `app/services/project_memory_service.py` with `load_design_system(project_id)`, `save_design_system(...)`, `load_project_manifest(project_id)`, `update_project_manifest(...)`.

### 3.3 Workspace & Git service

New file: `app/services/workspace_service.py`.

Each **project** gets one persistent Git repository on disk (not per-feature, per-project — this is your actual growing MERN codebase):

```
workspaces/{project_slug}/repo/          # the real MERN app, one git repo
```

Responsibilities:
- `ensure_project_repo(project_id)` — clone/init the repo if it doesn't exist yet (first feature initializes a scaffold: `client/` React app via Vite, `server/` Express app, root `package.json`, `.gitignore`, base folder structure).
- `start_feature_branch(project_id, feature_id)` — `git checkout -b feature/{feature_slug}` from `main`.
- `diff_against_main(project_id, feature_id)` — returns a structured diff (files added/modified/deleted + unified diff text) used to build `file_tree_json` and `merge_report_markdown` **deterministically**, never by asking the LLM to self-report what it changed.
- `merge_feature_branch(project_id, feature_id)` — called only after human approval; merges into `main`, deletes the feature branch.
- `discard_feature_branch(project_id, feature_id)` — called on rejection; resets so the next attempt starts clean or from the human-annotated state.

Use `gitpython` for all of this. This gives you rollback, real diffs for human review, and a clean unit of work per feature almost for free — don't reinvent version tracking on top of your artifact versioning system; Git already does this better for source code specifically.

### 3.4 Sandbox / shell execution service

New file: `app/services/sandbox_service.py`.

The Coder Agent will run `npm install`, `npm run build`, `npm test`, etc. This must **never** run directly on the host. Run it in a disposable Docker container with the project workspace bind-mounted:

- Base image: `node:20-slim` (matches MERN).
- Mount `workspaces/{project_slug}/repo` read-write at `/workspace`.
- No network egress except the npm registry (or run an offline/verdaccio mirror later — not needed for v1).
- Hard timeout per command (e.g. 120s) and a total wall-clock budget per feature run (e.g. 10 minutes) to stop runaway loops.
- Return `{exit_code, stdout, stderr}` — never raise raw exceptions back into the agent loop; the agent needs the failure text to self-correct.

This same service will be reused, unchanged, by the Security Agent (`npm audit`, SAST tools) and QA Agent (running the generated test suite) later — build it generically now.

### 3.5 Agentic (tool-calling) model factory

New file: `app/providers/agentic_model_factory.py`.

```python
from langchain.chat_models import init_chat_model
from app.services.in_memory_store import store  # Mongo-backed despite the name

def get_agentic_chat_model():
    settings = store.llm_settings
    provider = settings["provider"]          # "ollama" | "openai" | "anthropic"
    model = settings["model"]

    model_string = f"{provider}:{model}"
    return init_chat_model(
        model_string,
        temperature=settings.get("temperature", 0.1),
        timeout=settings.get("timeout_seconds", 320),
    )
```

Notes:
- You'll need to add `"anthropic"` to `LLMProviderService.SUPPORTED_PROVIDERS` and an `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` setting in `core/config.py`, mirroring the existing OpenAI settings. Anthropic models are the strongest current option specifically for agentic code editing; keep Ollama/OpenAI available for cost control and local dev.
- `init_chat_model` is intentionally used here instead of hand-writing three separate LangChain client wrappers — it already dispatches to `langchain-anthropic` / `langchain-openai` / `langchain-ollama` based on the string prefix. This is the one piece of this system that should **not** be built from scratch.
- Verify the exact `init_chat_model` signature and supported provider prefixes against the LangChain version actually installed (`pip show langchain`) before finalizing — this API has moved fast; don't trust a remembered signature over what's on disk.

### 3.6 Graph orchestrator service + Mongo checkpointer

New file: `app/services/graph_orchestrator_service.py`.

This is the piece that turns "several FastAPI endpoints called in sequence" into "one LangGraph state machine with human-in-the-loop pauses." Build this in Milestone 0 as a **skeleton with pass-through nodes**, then fill in each real node body as you finish that agent (Milestone 3+, Milestone 6+). Don't wait until every agent is done to wire the graph — wire it early with no-ops so you can test the interrupt/resume mechanics independently of agent quality.

```python
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.mongodb import MongoDBSaver
from typing_extensions import TypedDict

class FeaturePipelineState(TypedDict, total=False):
    project_id: str
    feature_id: str
    human_comment: str | None
    last_agent: str
    last_artifact_ids: list[str]
    approval_decision: str | None   # "approved" | "rejected" | "revision_requested"

def make_approval_gate(agent_name: str):
    def _gate(state: FeaturePipelineState):
        decision = interrupt({
            "feature_id": state["feature_id"],
            "agent_name": agent_name,
            "artifact_ids": state["last_artifact_ids"],
            "message": f"Review {agent_name} output before continuing.",
        })
        return {"approval_decision": decision}
    return _gate

def route_after_approval(agent_name: str):
    def _route(state: FeaturePipelineState):
        if state["approval_decision"] == "approved":
            return "next"
        return "retry"   # loops back into the same agent node with human_comment set
    return _route
```

Build the graph with nodes: `requirement_node → approve_requirement → [route] → domain_node → approve_domain → ... → uiux_node → approve_uiux → ... → coder_node → approve_coder → ... → security_node (stub) → qa_node (stub) → END`. Each `*_node` function calls the **existing** agent's `run()`-equivalent logic (Requirement/Architecture agents already have this; UI/UX and Coder will get theirs in later milestones) and writes `last_artifact_ids` into state.

Compile with a MongoDB checkpointer, reusing your existing Mongo connection settings:

```python
from langgraph.checkpoint.mongodb import MongoDBSaver
checkpointer = MongoDBSaver.from_conn_string(settings.MONGODB_URI, settings.MONGODB_DATABASE)
graph = builder.compile(checkpointer=checkpointer)
```

Use `thread_id = feature_id` in the `configurable` config for every invoke/resume call — this is what lets a human approve a stage hours or days later and the graph pick up exactly where it paused, even across backend restarts.

**How this connects to your existing FastAPI approval endpoint:** `POST /artifacts/{artifact_id}/approval` currently just flips `artifact["approval_status"]` in Mongo. Extend `approval_service.submit_approval(...)` so that, after recording the approval as it does today, it also calls:

```python
graph_orchestrator_service.resume(
    feature_id=feature_id,
    resume_value=request.status,   # "approved" / "rejected" / "revision_requested"
)
```

which does `graph.invoke(Command(resume=resume_value), config={"configurable": {"thread_id": feature_id}})`. This means your frontend and existing approval UX **do not need to change at all** — only the plumbing behind that one endpoint changes. This is the cleanest integration point and the reason the rest of your API surface (projects, features, artifacts routes) needs no changes.

**Starting a feature run:** add one new endpoint, `POST /features/{feature_id}/start`, that does `graph.invoke({"project_id": ..., "feature_id": ...}, config=...)` to kick off the graph for the first time. Everything after that first call is driven by approvals hitting the resume path above.

---

## 4. UI/UX Agent — implementation plan

### 4.1 Scope for this milestone

Produce, per feature: a validated `ui_metadata_json` (design tokens + component/page tree, coverage-checked against the approved SRS/SDS), real React (`.jsx`) components with Tailwind classes (using **mock data**, no backend calls yet), a rendered screenshot per page for human review, and an integration manifest describing how these components should be wired into the app (route path, nav entry, expected props) — consumed later by the Coder Agent, not by the human.

### 4.2 File layout (mirrors `architecture_agent`'s split-by-concern convention)

```
app/agents/uiux_agent/
    agent.py                # orchestrates the steps below, same shape as architecture_agent/agent.py
    prompt.py                # UIUX_AGENT_SYSTEM_PROMPT + builders for user prompts
    schemas.py                # UIUXAgentInput / UIUXAgentOutput (extend what's already there)
    metadata_modeler.py       # LLM call #1: SRS/SDS -> ui_metadata_json
    metadata_validator.py     # coverage check: every actor-facing use case has a page/action
    component_generator.py    # LLM call #2: ui_metadata_json -> .jsx + Tailwind files, per component
    design_system_service.py  # load/merge project-level design_system.json (uses ProjectMemoryService)
    preview_renderer.py       # Playwright: render component(s) to static HTML, screenshot to PNG
    integration_manifest_builder.py  # deterministic: builds the manifest the Coder Agent consumes
```

### 4.3 Step-by-step pipeline (this is the body of `UIUXAgent.run()`)

1. **Load context.** Approved `srs_json`, approved `enhanced_srs_json` (if Domain Agent has run), approved `sds_json`. Load the project's `design_system.json` via `ProjectMemoryService` — if this is the project's first feature, it doesn't exist yet and this step *creates* the initial one instead of loading it.
2. **Generate `ui_metadata_json`** (`metadata_modeler.py`, one LLM call, JSON-mode/structured output). This should describe, per page: layout regions, components used (reusing named components from `design_system.json` wherever a fit exists — the prompt must be explicit about this), states (loading/empty/error/success), and the design tokens it needs that don't already exist in the design system (new tokens must be justified, not invented casually).
3. **Validate coverage** (`metadata_validator.py`): every actor + use case in the approved SRS that implies a screen or interaction must map to at least one page/component in `ui_metadata_json`. Mirror the pattern already used in `architecture_agent/sds_validator.py` — same idea, new target document. Fail loudly (raise a typed validation error) rather than silently proceeding on an incomplete mapping; this is a cheap, deterministic check that catches an entire class of "the login page forgot the forgot-password link" bugs before a human even looks at it.
4. **Generate component code** (`component_generator.py`): for each page/component in the validated metadata, generate the actual `.jsx` file with Tailwind classes and mock/sample data props. Keep this call scoped per-component (or per-page) rather than one giant call for the whole feature — smaller, more reliable generations, and it lets you retry a single broken component without regenerating everything.
5. **Render + screenshot** (`preview_renderer.py`): use Playwright to load each generated component in an isolated preview harness (a minimal Vite dev server or a static HTML shell that mounts the component with `ReactDOM.createRoot` and the mock props) and capture a PNG. This mirrors your existing `plantuml_service` pattern (render an artifact to an image so a human can review it visually) — same idiom, new content type.
6. **Save artifacts**: `ui_metadata_json`, one `.jsx` file per component (as text artifacts), one PNG per page (as binary artifacts, via `artifact_service.save_binary_artifact`, same as diagram PNGs today), `ui_design_markdown` (human-readable summary), and the integration manifest.
7. **Update `design_system.json`** with any new tokens/components introduced — but only after human approval (do this in the approval-gate resume path, not before, so a rejected run doesn't pollute the shared design system).
8. **Human approval gate**: the human reviews the PNG screenshots (not raw JSX) plus the metadata summary. This is the fidelity guarantee: what's approved here is a screenshot of the literal component that ships — there is no later "regenerate the UI from a mockup" step for the Coder Agent to introduce drift in.

### 4.4 My specific suggestions for this agent

- **Do not let the LLM invent new base components per feature.** The single biggest cause of "every page looks slightly different" in generated UIs is a fresh `Button` implementation every run. Force reuse: pass the existing `design_system.json` component registry into the prompt and instruct the model to import from it; only allow new component creation when the validator confirms no existing component fits, and even then require it to register the new component back into the shared system.
- **Keep the frontend as one persistent app (`client/`), not one throwaway project per feature.** The UI/UX Agent should never regenerate `App.jsx`/router config itself — it produces new, self-contained component files plus a manifest saying "this goes at route `/login`, needs a nav entry called 'Login'". The **Coder Agent** performs the actual integration (routing, imports, wiring to state/auth). This keeps "produce approved visuals" and "wire it into a growing app" cleanly separated, and it avoids the UI/UX agent needing write access to files it didn't create.
- **Mock data must be realistic and consistent**, ideally derived from the SDS entity definitions (e.g. a `Product` mock object should have the same fields the SDS class diagram says a `Product` has) — this reduces rework when the Coder Agent later swaps mock data for real API calls, because the shape doesn't change, only the data source.
- Treat `html_tailwind`/`react_component` fields already in your stub schema as superseded by this plan — replace them with the richer output described above rather than keeping both; having two representations of the same UI invites exactly the drift problem this whole redesign is meant to avoid.

---

## 5. Coder Agent — implementation plan (the core of this build)

### 5.1 Scope for this milestone

Given an approved SRS + Architecture SDS + UI/UX component files + the project's `project_manifest.json`, produce a working, tested, patch-based change to the persistent MERN codebase for exactly one feature, plus a deterministic diff/manifest for human review, using a LangGraph ReAct-style tool-using subgraph — not a single LLM call.

### 5.2 High-level flow

```
[plan_node]  (one-shot LLM call, NOT agentic)
     |
     v
[plan_validator]  (deterministic coverage check vs SDS)
     |
     v
[prepare_workspace]  (git branch, deterministic)
     |
     v
[coding_loop_node]  <-------------------+   (agentic: create_react_agent + tools)
     |                                  |
     v                                  |
[verify_node]  (npm build/lint/test, deterministic, sandboxed)
     |                                  |
   pass? --- no, retries left ----------+   (loop back with failure text appended)
     |
   yes / retries exhausted
     v
[diff_node]  (git diff -> file_tree_json + merge_report_markdown, deterministic)
     |
     v
[human approval interrupt]
     |
   approved? --- no -----> [discard branch, loop back to coding_loop_node with human_comment]
     |
   yes
     v
[merge_node]  (git merge to main, update project_manifest.json, deterministic)
```

The pattern to notice: **only `coding_loop_node` is a non-deterministic agentic step.** Everything around it — planning validation, workspace prep, build/test verification, diff computation, manifest updates — is deterministic code, exactly like your existing validator/builder split in `architecture_agent`. This is intentional: keep the blast radius of "the LLM might do something unexpected" as small and as checkable as possible.

### 5.3 `plan_node` — scoped planning before any code is touched

New file: `app/agents/coder_agent/planner.py`. One-shot LLM call (use `llm_provider_service`, not the agentic model — this step doesn't need tools) that reads the approved SRS, SDS, UI/UX integration manifest, and `project_manifest.json`, and produces `code_plan_json`:

```python
class CodePlanFile(BaseModel):
    path: str                 # e.g. "server/src/routes/auth.routes.js"
    action: Literal["create", "modify", "delete"]
    rationale: str
    maps_to: list[str]        # SDS class/endpoint IDs or SRS requirement IDs

class CodePlan(BaseModel):
    files: list[CodePlanFile]
    new_dependencies: list[str]        # npm packages to add, if any
    env_vars_needed: list[str]
    summary: str
```

`app/agents/coder_agent/plan_validator.py`: deterministic check that every SDS endpoint/class relevant to this feature is referenced by at least one planned file, mirroring `ArchitecturePlanValidator`'s coverage-check pattern. Reject and retry the plan call (not the whole coding loop) if coverage is incomplete — this is a much cheaper place to catch a missing endpoint than after the agent has already written code.

This plan becomes the **task description** handed to the agentic loop — the agent is told what to build and why, not left to improvise architecture from scratch. This is the load-bearing design choice that keeps an open-ended tool-using agent from wandering: it edits within a pre-validated scope instead of deciding scope itself.

### 5.4 Tools — `app/agents/coder_agent/tools.py`

Define these as LangChain `@tool`-decorated functions, all hard-scoped to `workspaces/{project_slug}/repo` (reject any path that resolves outside the workspace root — path traversal guard is not optional):

- **`list_dir(path: str) -> str`** — list files/folders relative to the workspace root.
- **`read_file(path: str) -> str`** — return file contents; return a clear "file not found" string rather than raising, so the agent can react to it instead of crashing the tool call.
- **`write_file(path: str, content: str) -> str`** — create a new file or fully overwrite one. Reserve this primarily for **new** files.
- **`apply_patch(path: str, find: str, replace: str) -> str`** — for editing existing files, prefer a find-exact-block/replace-with-block tool over line-numbered unified diffs. LLMs are noticeably more reliable at "replace this exact snippet with this one" than at producing correct line offsets for a patch format (this mirrors the edit style used by Aider and similar tools for exactly this reliability reason). Fail clearly if `find` doesn't match exactly once in the file, and tell the agent so it can re-read the file and retry.
- **`run_shell(command: str, cwd: str = ".", timeout: int = 120) -> str`** — routed through `sandbox_service`, allowlisted to `npm`, `npx`, `node`, `git status`, `git diff` only. Returns combined stdout/stderr and exit code as text.
- **`search_code(query: str) -> str`** — shell out to `ripgrep` (`rg --line-number`) over the workspace. Simple text search is enough for a codebase this system builds incrementally itself; don't build an embeddings-based retriever for v1 — it's real engineering cost for a problem ripgrep already solves at this scale.
- **`read_project_manifest() -> str`** — returns the relevant slice of `project_manifest.json` (existing routes, models, shared components) so the agent doesn't collide with or duplicate prior features. This is the tool that makes "preserve previous features" an actual mechanism instead of a prompt instruction.
- **`read_ui_component(component_name: str) -> str`** — reads the approved `.jsx` file produced by the UI/UX Agent for this feature, so the coder agent integrates the exact approved file rather than regenerating UI from a text description of it.

### 5.5 `coding_loop_node` — the agentic subgraph

```python
from langgraph.prebuilt import create_react_agent
from app.providers.agentic_model_factory import get_agentic_chat_model
from app.agents.coder_agent.tools import (
    list_dir, read_file, write_file, apply_patch,
    run_shell, search_code, read_project_manifest, read_ui_component,
)

coder_react_agent = create_react_agent(
    model=get_agentic_chat_model(),
    tools=[list_dir, read_file, write_file, apply_patch,
           run_shell, search_code, read_project_manifest, read_ui_component],
    prompt=CODER_AGENT_SYSTEM_PROMPT,
)
```

Invoke it inside the LangGraph node with the `code_plan_json` plus any prior failure output (on retries) as the initial human message, and a `recursion_limit` set in the invoke config to bound how many tool-call round-trips a single attempt can take (start around 40–60; tune once you see real traces). **Verify the exact `create_react_agent` import path and signature against the installed `langgraph` version** — check `pip show langgraph` and its docs before wiring this, since prebuilt agent APIs in this ecosystem change between minor versions faster than most libraries. If it's been renamed or superseded (e.g. by `langchain.agents.create_agent` with middleware) by the time you build this, use whichever is current and adjust the import — the graph/node structure around it doesn't change.

### 5.6 `verify_node` — deterministic, sandboxed, hard gate

After the agentic loop believes it's done, **do not trust its self-report.** Run, via `sandbox_service`:
1. `npm install` (only if `new_dependencies` is non-empty or `package.json` changed)
2. `npm run build` (or `tsc --noEmit` if applicable)
3. `npm run lint`
4. `npm test` (whatever test suite already exists — the QA Agent will add feature-specific tests later; for now this at minimum guards against regressions in previously merged features)

If any step fails: route back to `coding_loop_node` with the failure output appended as a new message, up to a fixed retry budget (e.g. 3 attempts). If retries are exhausted, route to a `needs_human_help` state that surfaces the failure directly to the human instead of silently merging broken code — never let a failing verify step be overridden automatically.

### 5.7 `diff_node` — deterministic diff, not agent self-report

Use `workspace_service.diff_against_main(...)` (git-based) to build:
- `file_tree_json` — actual files added/modified/deleted, computed from `git diff --name-status`.
- `merge_report_markdown` — human-readable diff summary (can embed real `git diff` hunks per file, or a summarized version for large diffs).
- `code_manifest_json` — files with short descriptions, reconciled against `code_plan_json`'s `maps_to` field.
- `requirement_code_map_json` — built by joining `code_plan_json.files[].maps_to` with the actual files that ended up touched (from the git diff), not from the plan alone — a file the agent added that wasn't in the original plan should still show up here, flagged as "unplanned," rather than silently disappearing.

This node is why the earlier "the plan tags every file with the SDS/SRS IDs it maps to" design decision pays off: traceability from requirement → SDS element → actual file is assembled from data you already have, not asked of the LLM after the fact.

### 5.8 `merge_node` — after human approval

`workspace_service.merge_feature_branch(...)`, then `ProjectMemoryService.update_project_manifest(...)` with the newly added routes/models/components so the **next** feature's `plan_node` sees them. On rejection, `workspace_service.discard_feature_branch(...)` and loop back into `coding_loop_node` with the human's comment as additional context.

### 5.9 File layout

```
app/agents/coder_agent/
    agent.py                 # assembles the LangGraph subgraph described above
    prompt.py                 # CODER_AGENT_SYSTEM_PROMPT (extend what's already there)
    schemas.py                 # extend existing CoderAgentInput/Output + CodePlan, etc.
    planner.py                 # plan_node body
    plan_validator.py          # deterministic coverage check
    tools.py                   # the @tool-decorated functions from §5.4
    verify.py                  # verify_node body (build/lint/test via sandbox_service)
    diff_builder.py             # diff_node body
```

### 5.10 My specific suggestions and risks to plan for

- **Cost and latency are real.** An agentic loop with 10–40 tool round-trips per feature, on top of Playwright screenshots and Docker builds, is meaningfully slower and more expensive than your current one-shot agents. Set expectations with yourself now, not after the first end-to-end run surprises you. Consider a cheaper/faster model for `plan_node` (structured, low-creativity) and a stronger model for `coding_loop_node`.
- **Context growth.** As the codebase grows past a handful of features, do not feed the whole repo into context. The `project_manifest.json` + `search_code`/`read_file` tools are your scoping mechanism — the agent should be pulling in only what it asks for, not receiving a full repo dump up front. Revisit this once you have 8–10 features merged; if the manifest itself grows unwieldy, summarize older features' entries rather than dropping them.
- **Non-determinism is a feature here, not a bug to eliminate** — but it means you need the deterministic guardrails (`plan_validator`, `verify_node`, git-based diffing) more than a traditional pipeline would, precisely because the generation step itself isn't reproducible run to run.
- **Sandbox discipline is not optional.** You are giving a model real `run_shell` and file-write access. Container isolation, command allowlisting, and timeouts in `sandbox_service` are your actual security boundary right now — the Security Agent reviewing the *output* later is a second layer, not a substitute for this one.
- **Resist the urge to let the agent decide architecture.** The `plan_node` + validator exist specifically so the open-ended agentic loop is executing a pre-approved, SDS-traceable plan rather than improvising. If you notice the agent frequently deviating from the plan in ways that turn out fine, that's a signal to revisit the plan step's prompt — not a reason to remove the constraint.

---

## 6. Wiring both agents into the top-level graph

Once §4 and §5 exist as callable functions, replace the pass-through `uiux_node` and `coder_node` stubs from Milestone 0 (§3.6) with real calls into `UIUXAgent.run(...)` and the compiled Coder Agent subgraph respectively. The approval-gate nodes and routing logic around them do not change — this is the payoff of building the graph skeleton early with no-ops: the orchestration plumbing was already tested before either agent's internals existed.

---

## 7. Security & QA Agents — placeholders for this phase

Create these now, matching the existing stub convention exactly, so the graph has real node targets to route to instead of `None`:

```
app/agents/security_agent/agent.py
app/agents/security_agent/prompt.py
app/agents/security_agent/schemas.py

app/agents/qa_agent/agent.py
app/agents/qa_agent/prompt.py
app/agents/qa_agent/schemas.py
```

```python
# security_agent/agent.py
"""
Security Agent.

Purpose (future):
- Run npm audit / SAST tooling against the merged feature branch via sandbox_service.
- Flag vulnerabilities mapped to specific files/lines.
- Produce a security_report artifact for human review.

Placeholder for this phase: passes through without blocking the pipeline.
"""

class SecurityAgent:
    async def run(self, **kwargs):
        return {"status": "skipped", "message": "Security Agent not yet implemented."}
```

Same shape for `QAAgent`. In the top-level graph (§3.6), wire `security_node`/`qa_node` to call these and **auto-approve** (skip the human interrupt) for now, so the pipeline runs end-to-end without stalling on a gate nobody can act on yet. Flip this to a real `interrupt()` gate the moment these agents produce real output — don't leave an auto-approved gate in place silently once there's something worth reviewing behind it.

Reuse `sandbox_service` (§3.4) for both when you build them for real — Security Agent for `npm audit`/dependency scanning, QA Agent for running (and possibly writing) the test suite. This is exactly why that service was built generically rather than coder-agent-specific.

---

## 8. Build roadmap — do it in this order

- **M0 — Foundation** (§3): enums, `ProjectMemoryService`, `workspace_service`, `sandbox_service`, `agentic_model_factory`, `graph_orchestrator_service` with all-stub nodes wired end to end. **Test:** run a fake feature through the whole graph with pass-through nodes and confirm `interrupt()`/`Command(resume=...)` actually pauses and resumes correctly using the Mongo checkpointer, including after a backend restart.
- **M1 — UI/UX Agent, steps 1–3** (§4.3): metadata modeling + coverage validation only. **Test:** run against your existing approved login feature SRS/SDS; inspect `ui_metadata_json` by hand.
- **M2 — UI/UX Agent, steps 4–8**: component generation, Playwright rendering, artifact saving, design system persistence. **Test:** full UI/UX run on the login feature, human approves via screenshots.
- **M3 — Coder Agent planning** (§5.3–5.4): `plan_node` + `plan_validator` + tool functions written and unit-tested in isolation (call each tool directly against a scratch git repo, no LLM involved yet).
- **M4 — Coder Agent loop** (§5.5): wire `create_react_agent` with the tools; run it manually (outside the graph) against the login feature's plan and inspect the resulting diff by hand before trusting any automation around it.
- **M5 — Coder Agent verification + diff** (§5.6–5.8): sandboxed build/test gate, retry routing, deterministic diff/manifest generation, merge-on-approval.
- **M6 — Full wiring** (§6): replace stub nodes with real UI/UX and Coder calls in the top-level graph; run the entire pipeline for the login feature from Requirement through Coder, end to end, with a human approving each stage.
- **M7 — Security/QA placeholders** (§7): stub modules + auto-approved pass-through nodes so the graph has a real terminal shape.
- **M8 — Second feature.** Deliberately pick a feature that reuses UI (e.g. signup, which shares form components with login) and touches shared backend code (e.g. the same `User` model). This is the real test of `design_system.json` and `project_manifest.json` doing their job — don't consider this system validated until a second feature builds cleanly on top of the first without regenerating what already exists.

---

## 9. Testing strategy

- **Unit-test tools in isolation** (`read_file`, `apply_patch`, `run_shell`, path-traversal rejection) against a throwaway git repo fixture — these are plain deterministic functions and should be tested like any other, without ever invoking an LLM.
- **Unit-test validators** (`metadata_validator`, `plan_validator`) with hand-crafted incomplete inputs to confirm they actually reject what they're supposed to, mirroring however `usecase_validator.py`/`sds_validator.py` are already tested in this repo, if at all — add tests for those too if missing, since the new validators follow the same pattern.
- **Golden-file test the deterministic builders** (`diff_builder`, `integration_manifest_builder`): given a fixed git diff, assert the exact `file_tree_json`/`merge_report_markdown` produced — these have no LLM involved and should be fully reproducible.
- **One real integration test**: the login feature, end to end, through the actual graph, with a scripted "always approve" human responder. Run this whenever either agent's prompt or tool set changes — it's your regression signal against silent quality drift, which is otherwise invisible in a system with this much non-determinism.

---

## 10. Open items intentionally deferred

- `domain_agent` is still a stub; this document doesn't change that. If Domain Agent isn't finished before UI/UX and Coder are wired in, both should treat `enhanced_srs_json` as optional (the Architecture Agent already does this) and fall back to plain `srs_json`.
- `deployment_agent` is untouched here.
- Cross-feature UI consistency is enforced via `design_system.json`; there is no automated visual-regression diffing (e.g. comparing a later feature's screenshot against the design system's reference screenshots) in this plan. Worth adding once you have 3+ features and can tell whether drift is actually happening in practice.
- Embedding-based code search is deliberately excluded in favor of `ripgrep` + the project manifest. Revisit only if the codebase grows large enough that manifest + grep genuinely stops being sufficient — don't build it preemptively.
