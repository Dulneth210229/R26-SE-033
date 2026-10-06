# Auto-Forge MAS — UI/UX + Coder Agent Build — Working Notes

This file is durable cross-milestone memory for the build described in
`instructions .md`. Read it before continuing this build in a new session —
it records real decisions, deviations from the spec, and gotchas discovered
during implementation that the original spec doesn't (and can't) know about.

The per-milestone implementation plan lives at
`C:\Users\ASUS\.claude\plans\soft-petting-star.md` and gets overwritten each
milestone — that file is scratch, **this file is the durable one**.

## Status

| Milestone | Status |
|---|---|
| M0 — Foundation (enums, workspace/sandbox/project-memory services, graph orchestrator) | DONE |
| M1 — UI/UX Agent steps 1-3 (metadata modeling + coverage validation) | DONE |
| M2 — UI/UX Agent steps 4-8 (component gen, preview rendering, artifacts, design system persistence) | DONE |
| M3 — Coder Agent planning (plan_node + plan_validator + tools) | DONE |
| M4 — Coder Agent loop (create_agent + tools, manual run) | DONE |
| M5 — Coder Agent verification + diff + merge | DONE |
| M6 — Full graph wiring (real uiux_node/coder_node) | DONE |
| M7 — Security/QA placeholders | DONE |
| M8 — Second feature (Signup) proving reuse | not started |

## Environment facts (verified, not assumed — re-check if anything seems off)

- **MongoDB is a real Atlas cluster**, not localhost — `.env`'s `MONGODB_URI` overrides the
  `localhost` default in `config.py`. The real project **"E-commerce Platform"**
  (`proj_a2e3d529`) / feature **"Login"** (`feature_a44033b8`) already has: approved SRS v3,
  approved Architecture Plan v5 (saved under the **legacy `sds` artifact type**, not the newer
  `architecture_plan` type — both are handled via fallback lookup), approved UI/UX v1
  (`ui_metadata` + the `LoginForm.jsx` component, both approved).
- **Default LLM model is `qwen3-coder:latest` via Ollama**, not `gemma4` — changed (both live
  Mongo `llm_settings` and `.env` `DEFAULT_LLM_MODEL`) in M1 because `gemma4` could not reliably
  follow the structured JSON schemas the UI/UX and Coder planning prompts require.
- **Agentic (tool-calling) model** is also `qwen3-coder:latest` via
  `app/providers/agentic_model_factory.py` (`AGENTIC_MODEL_OVERRIDE` in `.env`/`config.py`).
- Docker Desktop is installed and used by `sandbox_service` for `run_shell`, but is **not always
  already running** — it does not auto-start with Windows in this environment. If
  `sandbox_service.run_command` returns `exit_code: 1` with `"Sandbox unavailable: could not reach
  Docker daemon"`, that's this, not a code bug: launch
  `C:\Program Files\Docker\Docker\Docker Desktop.exe` and poll `docker version` until it responds
  (took ~10s in practice) before retrying.
- Playwright + Chromium are installed. UI/UX preview rendering uses **vendored UMD bundles**
  (React/ReactDOM/Babel-standalone/Tailwind CDN script) at `app/agents/uiux_agent/vendor/` and a
  static HTML shell — **not** a Vite dev server. Gotcha: the babel `<script type="text/babel">`
  tag must **not** have a `data-presets="react"` attribute — adding it breaks rendering under
  `file://` navigation (Chromium treats Babel's transform output as an ES module, which is
  blocked by CORS under `file://`). Default (no `data-presets`) works fine and still handles JSX.
- System `rg` (ripgrep) is **not installed** and not installable without admin in this
  environment — `search_code` (Coder Agent tool) uses a pure-Python regex line-walker instead,
  capped at 200 results.
- `requirements.txt` periodically reverts to UTF-16 encoding on disk for unclear reasons (not
  something my edits cause directly). If `Edit` fails with "string not found" on this file,
  re-`Read` it fresh, decode if needed, and `Write` the whole file back as UTF-8.

## Key deviations from `instructions .md` (and why)

1. Graph orchestrator (M0) stage nodes are plain pass-through functions, not calls into real
   agents — intentional, matches the roadmap's own intent that M6 is when real agents get wired
   into the graph.
2. Security/QA graph stages are already auto-approved pass-through nodes with no human
   `interrupt()` (anticipating M7) — no `security_agent`/`qa_agent` stub *modules* exist yet,
   only the graph nodes; M7 adds the actual stub classes.
3. Added `ArtifactType.UI_INTEGRATION_MANIFEST` (not in the doc's original enum list). Reusing
   `UI_METADATA` for both the metadata JSON and the integration manifest created a real
   ambiguity for any future lookup (`apply_design_system_patch`, future Coder Agent context
   loading) — caught during M2 testing, fixed properly rather than patched around.
4. UI/UX component generation uses a **delimited text format**
   (`---MOCK_PROPS_JSON---` / `---JSX_CODE---`), not JSON with an embedded multi-line code
   string — avoids JSON-escaping failures for real JSX source text.
5. `design_system.json` persistence (UI/UX step 7) is triggered from
   `approval_service.submit_approval` directly (checks `agent_name=uiux_agent` +
   `artifact_type=UI_METADATA` + approved), **not** from the graph node — the real `uiux_node`
   doesn't exist until M6, so this hook had to live somewhere that already fires today.
6. Coder Agent tools (M3) are built by a per-run factory `build_coder_tools(project_id,
   feature_id)`, not bare module-level `@tool` functions — required because every tool's
   LLM-facing signature (per the doc itself) takes no `project_id` argument, so each tool must
   already be bound to one workspace (and one feature's approved UI components) at construction
   time.
7. **`langgraph.prebuilt.create_react_agent` is deprecated** in the installed version (moved to
   `langchain.agents.create_agent`) — M4 uses `create_agent` instead, per the doc's own explicit
   instruction to use whichever API is current. Signature/behavior is equivalent for this
   build's purposes (`model`, `tools`, `system_prompt=`, state keyed on `"messages"`).
8. **Added `workspace_service.commit_changes(project_id, feature_id, message)`** (not in the
   original doc's `workspace_service` method list). The coding loop's tools only ever touch the
   working tree, never git — `diff_against_main()`/`merge_feature_branch()` both operate on
   *committed* history, so without an explicit commit step between "the agentic loop finished"
   and "there is a diff to review," `diff_against_main()` silently returns an empty diff even
   though real files were written (confirmed directly: `git status`/`find` showed all 6 real
   files on disk while `diff_against_main()` reported `added: []`). M5's `diff_node` should call
   `commit_changes(...)` right after the coding loop (or after `verify_node` passes) and before
   computing the diff.
9. **M5's `verify_node` skips (doesn't fail) a build/lint/test script that isn't defined in
   `package.json`** — user decision, since the real project has zero build tooling scaffolded
   yet (see below). Only a script that exists and returns nonzero, or `npm install` itself
   failing, is a hard failure.
10. **`CoderAgentInput`/`CoderAgentOutput` (`coder_agent/schemas.py`) were rewritten** from the
    original artifact-ID-based sketch to the already-loaded-context shape, matching
    `ArchitectureAgentInput`/`UIUXAgentInput`'s established convention (same change UI/UX went
    through between its stub and M1). `CoderAgentOutput` kept its original 5 fields and gained
    `code_plan_json`, `verification_passed`, `artifact_ids`.
11. **`ArtifactType.CODE_DIFF` is the merge-gating artifact type** for the Coder Agent (shared
    across both `file_tree_json` (JSON format) and `merge_report_markdown` (MARKDOWN format), same
    pattern as `UI_METADATA`). `approval_service.py`'s Coder Agent hook triggers
    `merge_approved_feature`/`discard_rejected_feature` on this type regardless of format.
12. **M6: `domain` moved from `GATED_STAGES` to `AUTO_APPROVED_STAGES`** in
    `graph_orchestrator_service.py`, joining `security`/`qa`. This was a real, pre-existing gap,
    not a new decision invented for M6: with `domain` gated, the graph would pause at
    `approve_domain` forever with no Domain Agent artifact a human could ever approve through the
    normal `POST /artifacts/{id}/approval` flow (there is no way to advance except calling
    `resume()` directly, bypassing the approval system entirely). `STAGE_SEQUENCE` (the true
    pipeline order, used for edge-wiring) is now separate from `GATED_STAGES` (which stages get a
    real `approve_*` node) -- previously these were conflated via `GATED_STAGES + AUTO_APPROVED_STAGES`
    concatenation, which only worked because auto-approved stages happened to all be at the end.
13. **M6: `uiux_node`/`coder_node` are real calls, bridged from sync graph-node functions into the
    async `UIUXAgent.run()`/`CoderAgent.run()` via `asyncio.run(...)`**, not by converting the
    graph/orchestrator/approval chain to async. This works because every current caller of
    `graph.invoke()`/`resume()` is a sync FastAPI route handler running in a worker thread with no
    event loop already active -- **if that ever changes (a route becomes `async def` and calls the
    orchestrator directly on the main event loop thread), this bridge breaks** and needs to become
    a threadsafe one (`asyncio.run_coroutine_threadsafe`). Documented directly in the node
    docstrings so this assumption isn't silently invalidated later.
14. **Discovered, not designed**: when a graph node raises (e.g. `coder_node`'s
    `CodePlanValidationError`), LangGraph's checkpoint stays at "this node is next" rather than
    either corrupting state or silently advancing past the failure -- confirmed directly
    (`get_status()` returned `next: ["coder_node"]` after the real failure below). A future
    `resume()` call would cleanly retry the same node from scratch. This is a genuinely useful
    emergent property, not something built -- worth knowing before assuming a failed node needs
    manual checkpoint surgery to recover from.
15. **`approval_service.py`'s existing broad `except Exception` around the graph-resume call
    (added in M0 to swallow `GraphNotRunningError` for artifacts approved outside a graph run)
    turns out to also correctly handle "the graph run failed downstream" for free**: when
    `coder_node` raised `CodePlanValidationError` during the real M6 end-to-end test, the human's
    `POST /artifacts/{id}/approval` call still returned its normal 200 OK (their approval action
    genuinely succeeded) while the failure was logged separately
    (`logger.exception("Failed to resume graph run...")`), not silently lost and not surfaced as a
    misleading 500 to someone who did nothing wrong. Worth keeping in mind if this error handling
    is ever "tightened" -- the current broad catch is load-bearing for more than its original
    purpose.
16. **M7: `app/agents/security_agent/` and `app/agents/qa_agent/` created**, matching the exact
    stub convention `deployment_agent/` already used (`agent.py`/`prompt.py`/`schemas.py`, no
    `__init__.py` -- matches every stub agent, not just the two implemented ones which happen to
    have one). Both `SecurityAgent.run()`/`QAAgent.run()` are `async def` returning
    `{"status": "skipped", "message": "... not yet implemented."}` verbatim per the doc's own
    snippet. `graph_orchestrator_service.py`'s `security_node`/`qa_node` now call these real
    (still-placeholder) classes via the same `asyncio.run()` bridge pattern `uiux_node`/
    `coder_node` established in M6, instead of the generic M0 pass-through function -- behavior is
    identical (auto-approved, no gate, no artifacts), but the graph now has real node targets to
    route to per the doc's Milestone 7 instruction, so implementing these agents for real later
    only means changing their own `agent.py` internals, not touching the graph again.
17. **Post-M8: Coder Agent output was not actually runnable — fixed with a deterministic
    Express+Vite scaffold.** The user reported directly (independent of the milestone plan) that
    generated projects had no way to actually run: the backend had no Express app at all, the
    frontend had no Vite/React project at all. Root cause: `workspace_service.ensure_project_repo`
    only ever created empty `client/`/`server/` folders with `.gitkeep` files and a bare root
    `package.json` (name/private only -- no deps, no scripts) -- every feature's entire runnable
    skeleton (package.json deps/scripts, `vite.config.js`, entrypoints, Express bootstrap) was
    left for the LLM planner + coding loop to invent from scratch every run, and the planner was
    already documented (below) as unreliable even at planning backend *route* files, let alone
    scaffold-level infrastructure. `verify.py` also never actually proved anything ran: it only
    checked for `build`/`lint`/`test` scripts in the **root** `package.json` (never populated)
    and silently skipped if absent. Confirmed against the real, already-merged Login feature
    before fixing: `server/` had `routes/auth.routes.js` and `models/UserCredentials.js` but no
    `app.js`/`server.js`/`package.json`; `client/` had `components/LoginForm.jsx`,
    `pages/LoginPage.jsx`, `services/authService.js` but no `main.jsx`/`App.jsx`/`index.html`/
    `vite.config.js`/`package.json` -- exactly the reported bug. Fix:
    - `workspace_service.py`: `SCAFFOLD_FILES` now defines a real, working MERN skeleton --
      `server/package.json` (express, cors, dotenv, mongoose, nodemon; `start`/`dev` scripts),
      `server/src/app.js` (Express app: cors, json body parsing, `/api/health`, exports `app`
      for routers to be `app.use(...)`'d onto), `server/src/server.js` (`app.listen`),
      `server/.env.example`; `client/package.json` (react, react-dom, react-router-dom, vite,
      `@vitejs/plugin-react`; `dev`/`build`/`preview` scripts), `client/vite.config.js`,
      `client/index.html`, `client/src/main.jsx` (renders `<App/>` inside `<BrowserRouter>`),
      `client/src/App.jsx` (a `<Routes>` tree new pages get added to), `client/src/index.css`.
      Root `package.json` gets real `install:all`/`dev`/`build` scripts (via `concurrently`) so
      `npm run install:all && npm run dev` actually boots both sides.
    - **Idempotent backfill, not just first-init**: `ensure_project_repo` now calls
      `_backfill_scaffold` on every call (not just at `Repo.init` time), which adds any
      `SCAFFOLD_FILES` entry missing from whatever branch is currently checked out (without
      touching anything already there) and separately merges the root `install:all`/`dev`/`build`
      scripts + `concurrently` devDependency into an existing root `package.json` via
      `_backfill_root_package_json` (parses/merges/rewrites JSON, preserves any dependencies
      already declared there). This is what let the already-in-progress, already-merged
      `e-commerce-platform` project (not just brand-new projects) get retrofitted automatically
      just by calling `ensure_project_repo` again -- no migration script, no special-casing.
      Deliberately does not force a `git checkout main` first -- it commits onto whatever branch
      is active, so the common case (repo idle on `main` between features) backfills `main`
      directly, and a mid-coding-loop call (`build_coder_tools` also calls `ensure_project_repo`)
      backfills the feature branch, which still reaches `main` on the next merge either way.
    - `prompt.py`'s `CODE_PLANNER_SYSTEM_PROMPT` gained hard rule 9: the scaffold already exists
      and works, do not re-plan it; to add a route, plan a "create" for the new router file AND
      a "modify" on `server/src/app.js` to `require`+`app.use(...)` it; to add a page, plan a
      "create" for the page AND a "modify" on `client/src/App.jsx` to add its `<Route>`. This is
      unconditional (in the system prompt, not the user-prompt context built from
      `project_manifest_json`), so it holds even for a project's very first feature, when the
      manifest is still empty.
    - `verify.py` was rewritten: `npm install` now always runs in both `server/` and `client/`
      (their `package.json` always exist thanks to the scaffold, regardless of whether
      `code_plan_json.new_dependencies` is empty), plus two new hard, non-skippable checks --
      `SERVER_BOOT_SMOKE_TEST_COMMAND` (backgrounds `node src/server.js`, polls `/api/health`
      using Node's own `fetch`, not `curl` -- `node:20-slim` has no `curl`, same root cause as
      the already-documented missing-`git` gotcha below -- then kills the server; nonzero exit
      is a hard failure) and a client build check (`npm run build` in `client/`, i.e. a real
      `vite build`). `lint`/`test` remain skip-if-absent (root `package.json` only) since no
      such tooling is scaffolded.
    - `diff_builder.py`'s `build_setup_instructions_markdown` now always shows the real
      `npm run install:all` / `npm run dev` commands (previously: nothing at all unless the
      plan happened to declare `new_dependencies`/`env_vars_needed`).
    - **Real fix applied to the actual `e-commerce-platform` project**, not just new projects:
      called `ensure_project_repo` to backfill the scaffold onto `main`, then hand-wired the
      already-merged Login feature into it (one-time, deterministic, not LLM-authored -- mirrors
      exactly what the updated planner prompt now instructs for every future feature):
      `server/src/app.js` now `require`s and `app.use("/api/auth", ...)`s the existing
      `auth.routes.js`; `client/src/App.jsx` now imports and routes `/login` to the existing
      `LoginPage`. Also relocated `bcrypt`/`jsonwebtoken` (used by `auth.routes.js`/
      `UserCredentials.js`, previously installed flat at the repo root with no script to ever
      run them) into `server/package.json`, and `axios`/`jwt-decode` (used by `authService.js`)
      into `client/package.json`. Verified for real: `coder_verifier.verify()` against this
      exact project -- `npm install (server)`: passed (135 packages), `npm install (client)`:
      passed (91 packages), `server boot (curl /api/health)`: passed (Express actually boots
      with the real Login routes mounted), `client build (vite build)`: passed (36 modules,
      including `LoginForm`/`LoginPage`/`authService`, actually compile). `result["passed"]`:
      `True`. Resulting lockfiles and the wiring commit are real, intentional state on `main`
      (see "Real state changes" below), not test debris.
    - Tests: `tests/test_workspace_scaffold.py` (new -- scaffold presence, git commit, backfill
      of a missing file without touching existing customizations, backfill of root-package.json
      scripts without touching existing dependencies, idempotency), `tests/test_coder_verify.py`
      (rewritten -- server/client-scoped installs, hard boot/build checks including a deliberately
      broken `app.js` producing a hard failure, root lint/test still skip-if-absent),
      `tests/test_coder_diff_builder.py` (setup-instructions assertions updated for the new
      always-present run commands). Full suite: 83 passed.
    - **Known remaining gap, not fixed by this change**: `authService.js` (generated before this
      fix, untouched by it) reads `process.env.REACT_APP_API_BASE_URL` -- a Create-React-App-style
      env var that does not exist under Vite (Vite exposes `import.meta.env.VITE_*` instead).
      This does not break `vite build` (the reference is never evaluated at bundle time, and the
      `||` fallback provides a working default that happens to match the scaffold's port 5000),
      but it would throw `ReferenceError: process is not defined` if that code path actually ran
      in a browser with that env var set. Not fixed here -- it's a pre-existing LLM-generated-
      code correctness bug, a different concern from "is there a scaffold to run it in at all,"
      and out of this fix's scope.
18. **Post-scaffold-fix: Coder Agent output was "partially implemented," not accurate/complete --
    fixed with tighter intra-loop verification, deterministic post-code checks, and prompt
    hardening (Upgrade 2 of 2; Upgrade 1, per-agent multi-provider LLM config, is a separate,
    not-yet-started follow-up -- see below).** The user reported the real, already-merged Login
    feature was broken in ways a human had to discover by hand: `LoginForm.jsx` never actually
    rendered (its markup was gated on `props.state`, which `LoginPage.jsx` never passed --
    literally invisible in the running app), its submit handler hardcoded a fake
    `setTimeout`-based credential check instead of calling the real, already-written
    `authService.js` (100% dead code as a result), `/forgot-password`/`/reset-password` were
    non-functional stubs ("in a real app, you would..." comments), and **no file anywhere called
    `mongoose.connect(...)`** despite `mongoose` being a dependency and models being defined --
    the DB was never actually connected. Root cause, confirmed by reading the actual pipeline
    code: verification only ever ran *after* the whole agentic coding loop declared itself done,
    against a brand-new agent instance each retry with zero memory of the previous attempt
    (`CoderAgent._code_with_retries` rebuilding `build_coder_react_agent` from scratch every
    time); nothing checked that every planned file was actually touched before the loop was
    allowed to stop (purely self-reported completion); the one self-check tool the system prompt
    already encouraged (`git status`/`git diff`) silently failed with exit 127 because
    `node:20-slim` has no `git` binary; and `verify.py` (even after the scaffold fix) only ever
    proved the app *boots and builds*, never that any specific planned endpoint was actually
    implemented rather than left as an unreachable stub.
    - `workspace_service.py` (`SCAFFOLD_FILES` templates): `SERVER_APP_JS` gained `helmet()`,
      an `express-rate-limit` limiter on `/api/`, a `// FEATURE_ROUTES_START` /
      `// FEATURE_ROUTES_END` marker pair (a stable `apply_patch` anchor for every future
      feature's router-mount line, regardless of how large the file grows), and a catch-all
      Express error-handling middleware; `SERVER_SERVER_JS` gained a **guarded**
      `mongoose.connect(process.env.MONGODB_URI)` (skips cleanly with a `console.warn` if the
      env var isn't set -- the sandbox's Docker containers never see host env vars, so this
      guard is what keeps the boot smoke test passing for every feature, not just DB-backed
      ones); `SERVER_PACKAGE_JSON` gained `helmet`/`express-rate-limit` deps. New
      `_backfill_scaffold_upgrades`/`_upgrade_server_app_js`/`_upgrade_server_server_js`: since
      these files already exist in any repo scaffolded before this upgrade, existence-based
      backfill (`_backfill_scaffold`) can't detect what's missing -- content **fingerprinting**
      does instead: a file that still matches its own frozen legacy template
      (`_LEGACY_SERVER_APP_JS_V1`/`_LEGACY_SERVER_SERVER_JS_V1`) exactly is provably untouched
      and gets replaced wholesale; anything else (e.g. the real e-commerce-platform's `app.js`,
      which already had Login's router mounted) gets **targeted, anchor-based insertions**
      instead, anchored on `const app = express();` and `module.exports = app;` (the two lines
      guaranteed present in every version of this file) so it's safe regardless of whatever a
      feature has already added in between. `_merge_package_json` is a new, generic, purely
      additive dict-merge helper, refactored out of the pre-existing `_backfill_root_package_json`
      and reused for `server/package.json` too.
    - **Sandbox image swap**: `docker/coder-sandbox.Dockerfile` (new) builds
      `autoforge-coder-sandbox:latest` from `node:20` (not `-slim`, which ships without `git` --
      confirmed root cause of the already-documented `git status`/`git diff` exit-127 gotcha)
      plus a globally-installed `@babel/parser` (with `NODE_PATH=/usr/local/lib/node_modules` so
      a plain `require()` from any cwd can actually find it -- npm's global install location
      isn't on Node's default require search path otherwise, a real gotcha hit while building
      this). `sandbox_service.SANDBOX_IMAGE` now points at this custom tag. Full suite re-run
      immediately after the swap to catch any regression from the larger base image -- none
      found.
    - **New self-check tools** (`app/agents/coder_agent/tools.py`, `build_coder_tools` gained an
      optional `code_plan_json` parameter): `list_unimplemented_planned_files` -- computes
      touched files from **git**, via new `workspace_service.get_touched_files(project_id,
      feature_id)` (compares the feature branch's current working tree, including still-
      untracked writes, against main's tip -- correct mid-loop, before `commit_changes` has run,
      unlike the existing `diff_against_main`'s committed-history-only triple-dot comparison),
      and reports any planned file not yet created/modified/deleted -- the model is told to call
      this before ending its turn, so plan completeness stops being self-reported.
      `check_syntax` -- runs `node --check` (`.js`) or a `@babel/parser` JSX parse (`.jsx`) on a
      single file inside the sandbox, giving fast, cheap per-file feedback instead of waiting for
      the next full install/build cycle to surface a typo.
    - **`route_checker.py`** (new module): `check_route_coverage` -- best-effort, regex-based
      static check that a planned backend file's endpoint (`maps_to` entries starting with `/`)
      actually has a matching route registration in that file, resolving the file's mount prefix
      by cross-referencing `app.js`'s `require(...)`/`app.use(prefix, binding)` pairs against the
      file's own relative route registrations (e.g. `router.post('/login', ...)` mounted at
      `/api/auth` correctly resolves to `/api/auth/login`). Explicitly a heuristic (regex, not a
      real router/AST analysis) -- documented as such in the module docstring. `verify.py` now
      runs this as a new **hard** gate ("endpoint route coverage"). `scan_for_placeholder_stubs`
      -- phrase-based scan (`"in a real app"`, `"not implemented"`, `"TODO"`, `"for now"`, etc.)
      of every touched file, wired in as a new **informational-only** step ("placeholder-stub
      scan", a new `"info"` status that never affects `passed`) -- deliberately not a hard gate,
      since these phrases are common enough in legitimate comments that blocking on them would be
      too false-positive-prone; it exists purely so a human reviewer sees it.
      `diff_builder.build_merge_report_markdown` previously only ever printed each verify step's
      `name`/`status`, silently dropping `output` -- now also renders `output` for `failed`/`info`
      steps specifically, otherwise the new placeholder-stub findings (informational by design)
      would be invisible in the human-facing report.
    - **`agent.py`'s `_code_with_retries`**: new pre-verify gate -- after `commit_changes`, before
      the expensive `verifier.verify(...)` call (2x `npm install`, server boot, `vite build`),
      deterministically diff the plan's file list against `workspace_service.get_touched_files`
      (new `_find_plan_gaps`/`_format_plan_gaps` helpers); if anything's missing, skip `verify()`
      entirely for this attempt and feed back the precise list of untouched files. **Targeted
      retries**: `coding_loop.build_task_message` gained an `already_touched` parameter -- a
      retry's task message now lists exactly which files already exist from the previous attempt
      (`"do not redo unless the failure below specifically points at them"`), so a fresh agent
      instance (each attempt still starts with zero memory of the last one, by design -- this
      pass did not change that) at least starts with better situational awareness instead of a
      fully generic re-prompt. `verify()`'s signature gained a required `feature_id` parameter
      (needed for `get_touched_files`) -- every call site and test updated.
    - **`CODER_AGENT_SYSTEM_PROMPT` hardening** (`prompt.py`), directly targeting the exact
      anti-patterns found in the real Login feature: never wire a handler to hardcoded/fake logic
      when a real service module exists to call instead; never leave placeholder-stub logic
      without explicitly naming it, by file, in the final summary; always validate required
      `req.body` fields before use (400 on missing/malformed); when rendering a component you
      didn't author (e.g. via `read_ui_component`), read its actual prop usage and wire every
      prop its logic depends on -- don't render it with zero props and assume it works; call
      `check_syntax` after every `.js`/`.jsx` write/patch and `list_unimplemented_planned_files`
      before ending the turn. The planner prompt's rule 9 (scaffold-awareness, from the prior
      milestone) gained an addendum: patch the `// FEATURE_ROUTES_END` marker specifically, never
      `module.exports = app;` directly. `CODING_LOOP_RECURSION_LIMIT` bumped 50 -> 65 to
      accommodate the new self-check tool calls without prematurely hitting the cap on otherwise-
      legitimate work.
    - **Real E2E test**: with a fresh `autoforge-coder-sandbox` image and all of the above live,
      approved the previously-pending Signup UI/UX v2 (see item 17's LoginForm-reuse-fix context)
      through the real approval endpoint, which resumed the real LangGraph run straight into the
      real `coder_node` for `feature_f74fb38a` (Signup) against the real e-commerce-platform
      project. Notable, real findings:
      - The real planner **passed `plan_validator` on the first attempt** for this feature (a
        `modify`-only plan against the already-existing `auth.routes.js`/`UserCredentials.js` --
        simpler than Login's from-scratch backend, and the first time in this project's history
        the real planner has driven a `CoderAgent.run()` past planning unattended). The
        already-documented from-scratch backend-under-planning gotcha (below) is unchanged/still
        open -- this one case succeeding doesn't contradict it.
      - The generated `/api/auth/signup` route genuinely validates required fields
        (`if (!email || !password || !fullName) return res.status(400)...`), checks for an
        existing user before creating one, and issues a JWT on success -- directly reflecting the
        new "validate `req.body` before use" prompt rule, and a real, concrete quality
        improvement over the original Login route (which had zero such validation).
      - `endpoint route coverage`: passed (the new checker correctly resolved `/api/auth/signup`
        against `auth.routes.js`'s `router.post('/signup', ...)` via `app.js`'s mount prefix).
      - `placeholder-stub scan`: correctly surfaced the **pre-existing** (from the original Login
        feature, untouched by this run) forgot/reset-password stub comments as informational
        findings, without blocking -- proof the scan works and correctly doesn't gate on them.
      - All 3 coding attempts nonetheless recorded `verification_passed: False` in the artifacts
        first saved from this run, because the `server boot (curl /api/health)` step failed on
        every attempt with a **false negative**: a real full pytest regression run (also
        Docker-heavy) happened to be running concurrently on this machine, and the original
        10-attempt/~10-second health-check retry window wasn't always enough for a container to
        get scheduled CPU under that contention -- confirmed by re-running the exact same
        `SERVER_BOOT_SMOKE_TEST_COMMAND` against the identical generated code in isolation
        immediately afterward: `exit_code: 0`, passed cleanly. **Fixed**: widened the retry loop
        from 10 attempts/1s apart to 30 (`SERVER_BOOT_TIMEOUT_SECONDS` 30 -> 45 to give the
        container itself enough wall-clock budget too), re-ran `tests/test_coder_verify.py` (9/9
        passed) and the full suite (115/115 passed) to confirm. Re-verified the Signup code a
        second time, fully cleanly (no concurrent load): every step passed, including server
        boot, `endpoint route coverage`, and build. Saved as a fresh, accurate v2 artifact set
        (`CoderAgentOutput` rebuilt deterministically from the *same* already-generated code plus
        this clean `verify_result` -- no re-planning, no re-invoking the LLM, since nothing about
        the actual generated code changed, only the environment's contention) so the artifact a
        human reviews next reflects reality (`verification_passed: True`) rather than the earlier
        contention-confounded false failure. **Lesson for future real-agentic-pipeline testing on
        this machine**: don't run the full Docker-heavy pytest suite at the same time as a real
        end-to-end agent run that also hits the sandbox -- they compete for the same Docker
        daemon and can produce exactly this kind of false negative.
    - Tests: `tests/test_coder_tools.py` (+8: `list_unimplemented_planned_files` gap-detection/
      clearing/no-plan-provided cases, `check_syntax` valid/invalid `.js`/`.jsx`/unsupported-
      extension cases), `tests/test_route_checker.py` (new, 9 tests: mount-prefix resolution,
      missing route, literal full-path match, missing file, non-backend/deleted files ignored,
      no-endpoint-maps_to ignored, placeholder-stub true/true-negative/untouched-file cases, all
      pure `tmp_path`-based, no git/Docker/LLM), `tests/test_coder_verify.py` (+3: route-coverage
      pass/fail, placeholder-stub-is-informational-and-never-fails; fixture now also creates a
      feature and starts its branch, since `verify()` needs `feature_id`), `tests/
      test_coder_diff_builder.py` (+1: failed/info step output surfaced, passed step output
      stays terse), `tests/test_coder_prompt.py` (new, 7 trivial substring-presence tests locking
      in the new hard rules -- these prove the rules are in the prompt text, not that the model
      follows them; the real E2E run above is what proves that). Full suite: **115 passed**
      (up from 87 before this pass), confirmed clean (no concurrent load) after the retry-window
      fix.
19. **Architecture Agent's out-of-scope validator false-positived on almost every real run --
    fixed, and re-verified with a real, brand-new project + feature end-to-end.** The user
    reported the Architecture Agent "did not work" when run for real. Root cause: both
    `usecase_validator.py`'s and `sequence_validator.py`'s `_validate_out_of_scope` flagged a
    diagram element as an out-of-scope violation whenever it shared just **2 stems** with a
    forbidden SRS `out_of_scope` phrase (`required_overlap = 1 if len(forbidden_stems) == 1 else
    2`), regardless of how many total stems the phrase had or whether the actual *distinguishing*
    word was present at all. Since out-of-scope items are almost always phrased using the same
    domain nouns as the feature itself (e.g. "Account verification via email" for a feature that
    is itself about accounts and email), this meant the check false-positived on nearly any
    legitimate in-scope element -- confirmed directly against three real errors from an earlier
    real run (documented in this file's history for the Signup feature): a duplicate-email check
    was flagged as "Account verification" (matched on `account`+`email`, missing the actual
    distinguishing stem `verif`), a new-user-registration step was flagged as "Password recovery
    functionality" (matched on `password`+`recovery`, missing `functionality`), and the signup
    use case itself was flagged as "User profile customization after signup" (matched on
    `user`+`signup`, missing `profile`/`customiz`). Because the Architecture Agent's fallback
    path (a deterministic, SRS-derived plan, generated only when both the raw and repaired LLM
    outputs fail) has **no further recourse** if it also fails validation, this false-positive
    could -- and, per the prior session's real Signup run, did -- crash the entire request with
    no Architecture Plan produced at all, blocking the UI/UX and Coder Agents from ever running.
    - Fix: `_validate_out_of_scope` in both validators now requires **all** of a forbidden
      phrase's meaningful stems to be present (`required_overlap = len(forbidden_stems)`), not a
      flat 2 -- the element must restate the entire forbidden concept, not merely share incidental
      domain vocabulary. Verified this alone fixes all three real false positives while still
      catching a genuine full-concept violation (e.g. "Verify Account Email... sends an email
      verification link" against "Account verification via email" is still correctly flagged,
      since `verif`/`account`/`email` are all present).
    - This alone was slightly too strict for phrases containing generic requirement-writing
      filler nouns (e.g. "Password recovery **functionality**" -- no realistic diagram element
      would ever literally contain the word "functionality"). Added `functionality`, `capability`,
      `capabilities`, `support` to both validators' `STOPWORDS` sets -- domain-agnostic filler
      words that describe *that* something is a capability, not *which* one, so they add no
      distinguishing signal (same precedent as the pre-existing `feature`/`flow` stopwords).
    - **Safety net added regardless of the above fix** (`agent.py`'s `_generate_architecture_output`):
      the final `_validate_full_output` call on the fallback path is now wrapped in its own
      try/except. If the fallback *still* fails validation (a heuristic validator can always have
      another edge case), the run no longer crashes -- it logs a warning and appends a plain,
      specific caveat to the plan's own `human_approval_note` field, then proceeds so a human can
      review and judge it, mirroring the Coder Agent's existing "proceed anyway with
      `verification_passed=False`" precedent rather than inventing a new failure story.
    - Tests: `tests/test_architecture_usecase_validator.py` (new, 5 tests: all 3 real false
      positives now pass validation, a genuine violation is still caught, an out-of-scope item
      with no meaningful stems is safely ignored) and `tests/test_architecture_sequence_validator.py`
      (new, 3 tests: 2 of the real false positives adapted to sequence-message shape, genuine
      violation still caught) -- no LLM, hand-built minimal `usecase_json`/`sequence_json`
      fixtures. Full suite: **123 passed** (up from 115).
    - **Real end-to-end verification, a genuinely new project and feature** (not a reuse of
      e-commerce-platform): created project **TaskFlow** (`proj_53284a63`, SaaS/MERN) and feature
      **Task Comments** (`feature_5521adbd` -- add/view/delete comments on a task, with SRS
      `out_of_scope` items "Editing existing comments", "Comment notifications or mentions",
      "Comment threading or replies", "Comment attachments or media" -- deliberately chosen to
      share the word "comment" with every in-scope element, the same shape of case that broke
      before). Ran the real pipeline through the actual HTTP API: Requirement Agent (real,
      succeeded first try) → approved → graph `start()` → `resume("approved")` (auto-passed
      `domain`) → paused at `approve_architecture` → **ran the real, now-fixed Architecture
      Agent**: raw LLM output failed JSON parsing (unrelated pre-existing issue, line-431
      malformed delimiter), the repair attempt was missing several required top-level keys, so it
      fell through to the deterministic SRS-derived fallback -- **which completed and passed
      `_validate_full_output` cleanly, with no validation-failure warning logged at all** (the
      fix's target scenario, working correctly on a real run) → approved the Architecture Plan →
      graph resumed into the real `uiux_node`, which generated `CommentInput`/`CommentList`
      components and completed normally → approved the UI metadata → graph resumed into the real
      `coder_node`, whose planner hit the **already-documented, separately-tracked** endpoint/
      entity-coverage limitation (`CodePlanValidationError: code_plan_json does not cover these
      API endpoints: ['/api/task-comments']; ... data entities: [...]`) -- the same pre-existing
      planner unreliability observed repeatedly for Login/Signup in the other project, not a new
      or regressed issue, and out of scope for this fix. The graph correctly stayed parked at
      `next: ['coder_node']` (the same emergent, already-documented checkpoint behavior noted
      elsewhere in this file), ready for a clean retry. **Net result: the Architecture Agent --
      the actual subject of this fix -- now runs to completion and produces an approvable plan
      for a real, previously-guaranteed-to-fail-shaped feature, and the pipeline progressed
      further (through Architecture and UI/UX) than it had ever previously gotten for this class
      of feature.**
    - Known, pre-existing, separate quality gap observed along the way (not part of this fix):
      the deterministic fallback Architecture Plan is noticeably crude -- e.g. it split the
      Comment entity's four fields into four separately-named "entities"
      (`Task CommentsDataEntity1..4`) instead of one unified entity, and produced duplicate
      `/api/task-comments GET` endpoint entries instead of distinct POST/GET/DELETE routes
      matching the SRS's `api_expectations`. This is the fallback template's own generation logic
      (a different code path from the validators fixed here), and its crudeness likely also
      contributed to the Coder Agent planner's subsequent coverage failure (awkward, non-standard
      entity names are harder for the planner to reference correctly). Worth a future look, but
      not conflated with the validator bug fixed in this pass.
20. **Ran the real Coder Agent for TaskFlow/Task Comments (user request: "run the coder agent for
    this new project and feature and check the output") -- found and fixed a real
    `GraphRecursionError` crash, found and corrected a UI/UX component-approval gap, and got a
    clean, genuinely well-integrated result on the corrected re-run.** Since the real planner
    (already known-unreliable, see the gotchas section) failed identically to item 19's earlier
    run, used the same established hand-validated-plan precedent as Login/Signup
    (`scripts/run_taskflow_coder_pipeline_manual.py`, new) -- a real, sensible plan (REST
    POST/GET/DELETE routes, one `Comment` model, modify the two approved UI/UX components instead
    of rewriting them) that still covers every literal string `plan_validator` requires from the
    crude fallback Architecture Plan.
    - **Bug found and fixed**: the first real run of the coding loop against this 8-file plan (2
      of which were "patch an existing component" tasks) hit `GraphRecursionError` -- the 100%
      real, uncaught turn-limit-of-65 exception crashed the entire script/request. `_code_with_retries`
      now catches `GraphRecursionError` explicitly and treats it exactly like an incomplete
      attempt: commits whatever partial progress was made (not lost), and feeds the next attempt
      a message naming the recursion limit and asking the model to work efficiently (don't re-read
      known files, don't call `check_syntax` more than once per file, prioritize finishing over
      polishing) on top of the existing plan-gap report. `CODING_LOOP_RECURSION_LIMIT` also bumped
      65 -> 100 -- the exact right number isn't the point anymore now that hitting it is a
      recoverable failure, not a crash. 4 new tests in `tests/test_coder_agent_retries.py`
      (mock-based: recursion error retried not crashed, efficiency-hint feedback on the next
      attempt's task message, plan-gap still skips the expensive verify() call, a passing verify()
      still short-circuits remaining attempts).
    - **Real gap found in this session's own process, not a Coder Agent bug**: the first
      (pre-fix) full run of the coding loop completed successfully (`verification_passed=True`,
      attempt 1/1) but the model **fabricated brand-new `CommentInput.jsx`/`CommentList.jsx`/
      `CommentItem.jsx` components from scratch** instead of reusing the approved UI/UX ones, even
      though the plan explicitly said to "modify" them. Root cause: only the `ui_metadata` JSON
      artifact had been approved (`artifact_b3950e89`), not the individual `UI_COMPONENT_CODE`
      artifacts for `CommentInput`/`CommentList` themselves -- `read_ui_component`'s lookup
      (`_find_approved_component_artifact`) filters on `approval_status == APPROVED`, so it had
      nothing to find and correctly reported no approved component, leaving the model to build its
      own working (but design-inconsistent) version out of necessity. Confirmed
      `approval_service.py` never cascades a `UI_METADATA` approval to its sibling
      `UI_COMPONENT_CODE` artifacts -- each component needs its own explicit approval, same as
      every other artifact type. **This is a real, easy-to-miss human/process gotcha worth knowing
      for future runs**: approving the metadata is not sufficient to make components reusable by
      the Coder Agent.
    - Approved the two component artifacts for real (`artifact_5e0bba5f`, `artifact_ca5c2871`)
      and re-ran the identical hand-validated plan against a freshly-reset branch. **Result: clean
      integration, exactly as intended.** `CommentInput.jsx` kept 100% of the approved component's
      markup/styling/loading/error-state logic -- the *only* change was replacing the fake
      `// Mock submission - in real app this would be an API call` + `setTimeout` with a real
      `await props.onSubmit(props.taskId, commentText)` call (plus adding the `useState` import
      the preview-only original omitted). `CommentList.jsx` likewise kept 100% of its visual
      structure -- the delete button (previously present with no `onClick` at all) now correctly
      calls `props.onDelete(comment._id)`, and every field reference was correctly updated to match
      the real `Comment` Mongoose model's actual shape (`comment.author.username`/
      `comment.author._id`/`comment.createdAt`/`comment._id`/`comment.text`) instead of the UI/UX
      agent's originally-guessed field names (`comment.authorUserId`/`comment.createdTimestamp`/
      `comment.id`/`comment.commentText`). This is precisely what this session's earlier Coder
      Agent prompt hardening (item 18: "read the component's actual prop usage and wire every prop
      its logic depends on," "never leave a handler wired to hardcoded/fake logic when a real
      service exists") was meant to produce, now confirmed on a real run where the precondition
      (an actually-approved component) was correctly met.
    - `server/src/routes/task-comments.routes.js`: real REST design (POST/GET/DELETE, not the
      fallback plan's single duplicated GET) -- required-field validation on create (400 on
      missing `text`/`author`/`task`), ownership check on delete (403 if the requester isn't the
      comment's author), chronological sort on list, `populate("author", "username")` on both read
      paths so the frontend gets real author names. `verify_result` on the corrected run: **all
      steps passed** -- `npm install` (both sides, first-ever install for this fresh project),
      server boot, client build, endpoint route coverage, and an informational (non-blocking)
      placeholder-stub hit on `TaskDetailPage.jsx`'s intentionally-mocked `currentUser` (reasonable,
      since no auth feature exists yet in this project) and a sample task description string --
      both legitimate, correctly-flagged, non-blocking notes for a human reviewer, not bugs.
    - Full suite re-confirmed passing after the `GraphRecursionError` fix (see test count below).
    - **Real state**: `workspaces/taskflow/repo` now exists with a `feature/task-comments` branch
      (not yet merged -- pending human review of the corrected run's artifacts:
      `artifact_fd4d28ec` and siblings, code plan + merge report + manifest). The pre-fix run's
      artifacts (`artifact_a72df0e1` and siblings, from the fabricated-components version) are
      superseded by this corrected set and should not be approved.
21. **Every generated app only ever showed the static scaffold placeholder when actually run --
    fixed the root cause (unreachable pages), added two new deterministic gates that prove a page
    is both reachable and renders without crashing, and added a real "revise by human prompt"
    capability for the Coder Agent (mirroring Requirement/Architecture Agent's existing
    `.revise()` pattern) so a human can iterate on an already-verified feature instead of hoping
    one shot is enough.** The user reported this directly: Login, Signup, and Task Comments all
    rendered nothing but "Auto-Forge Generated App" / "Feature pages are registered as routes
    below." regardless of what was actually built. Investigated and confirmed a real, structural
    root cause -- **not** a per-feature LLM mistake: `CLIENT_APP_JSX`'s `HomePage` has never had
    any navigation at all, so every `<Route>` a feature adds is real and correctly wired, but
    genuinely unreachable by a human clicking through the app. The user's own first proposal (an
    automatic live-dev-server self-correction loop) was evaluated and deliberately not built --
    no reliable, domain-agnostic way exists to judge "does this look right" without either
    duplicating a much cheaper deterministic check or resorting to a slow, non-deterministic
    LLM-judged screenshot (exactly the cost `preview_renderer.py`'s own docstring already argues
    against for a *much* smaller unit), and it would inherit this project's already-documented
    Docker-contention flakiness. Full plan: `C:\Users\ASUS\.claude\plans\soft-petting-star.md`.
    - **Scaffold fix** (`workspace_service.py`): `CLIENT_APP_JSX`'s `HomePage` now has a stable
      `{/* FEATURE_LINKS_START */}`/`{/* FEATURE_LINKS_END */}` marker pair inside a `<nav><ul>`,
      mirroring the existing `FEATURE_ROUTES_START`/`_END` idiom used for `app.js`'s router
      mounts -- a feature now patches this marker to add a real `<Link>` alongside its `<Route>`,
      instead of there being nothing to patch at all. **Idempotent backfill**: new
      `_LEGACY_CLIENT_APP_JSX_V1` fingerprint + `_upgrade_client_app_jsx`, wired into
      `_backfill_scaffold_upgrades` exactly like the existing `app.js`/`server.js` upgrades --
      untouched file -> wholesale replace; customized file (already has real routes/imports) ->
      anchored insertion that never touches what's already there; already-upgraded -> no-op.
      This is what let the two already-broken, already-real projects
      (`e-commerce-platform`, `taskflow`) self-heal just by calling `ensure_project_repo` again,
      same rollout mechanism as every prior scaffold-upgrade fix.
    - **Prompt changes** (`prompt.py`): `CODE_PLANNER_SYSTEM_PROMPT` rule 9's nav-link clause was
      previously conditional ("if one already exists" -- dead code, since the scaffold never
      created that mechanism) -- now unconditional: adding a page means planning both its
      `<Route>` and a real `<Link>` to it, in one "modify" of `App.jsx`. Added explicit guidance
      for parameterized routes (e.g. `/tasks/:taskId`): never link directly to one -- link to a
      list/index page instead, planning that page as part of the feature if it doesn't exist yet.
      `CODER_AGENT_SYSTEM_PROMPT` gained the symmetric patch instruction for
      `// FEATURE_LINKS_END` and a new completeness rule: a `<Route>` with no reachable `<Link>`
      is exactly the "looks done but isn't" defect the existing completeness rules already target.
    - **New hard gate: page reachability** (`nav_checker.py`, new module, sibling to
      `route_checker.py`, same "explicitly best-effort, regex-based, not full AST" idiom):
      `check_page_reachability` parses `App.jsx` for every `<Route>`/`<Link>` (including
      `to="..."`, template-literal `to={\`...${\`}, and `<a href="...">`) across the entire
      `client/src` tree (not just `App.jsx`), resolves parameterized routes as reachable only if
      their static prefix is itself a registered, reachable route. Wired into `verify.py` as a
      new hard gate, same justification as `check_route_coverage`: cheap, mechanical, no
      meaningful ambiguity.
    - **New hard gate: runtime render check** (`render_checker.py`, new module). Neither
      `client build` (compiles) nor `page reachability` (linked) can catch a page that does
      both but still throws at runtime (e.g. an undefined prop access) -- this closes that gap
      without a live dev server or a retry loop: serves the client's **already-built** `dist/`
      via `vite preview` (correct SPA-routing fallback, unlike a bare static server) from inside
      the sandbox, using a new `sandbox_service.start_background_service`/
      `stop_background_service` (detached container, published port -- `run_command` only ever
      waited for exit with no port publishing before this). From the host, Playwright navigates
      to `/` and every reachable route, checking for zero `pageerror` events and non-empty
      rendered content -- the same minimal bar `preview_renderer.py` already uses for component
      previews. Home page failing is a hard gate (cheap, no data dependency, exactly what was
      silently broken project-wide); feature pages are informational only (their rendering can
      legitimately vary with backend data state, e.g. an empty list before any data exists).
    - **Two real infra bugs found and fixed only by testing against real Docker/real async
      call chains, not synthetic unit tests**:
      1. `sandbox_service.start_background_service` reloaded the container's Docker attrs
         **once**, immediately after `containers.run()` returned, and raised if the port mapping
         wasn't there yet -- confirmed directly that this is a pure timing race (a manual
         reproduction showed the identical container correctly publishing its port moments
         later). Fixed by polling `reload()` up to 10 times (0.3s apart, bailing early if the
         container already exited), and including the container's logs in the error message if
         it genuinely never publishes.
      2. **`render_checker.py`'s Playwright sync API crashes when actually invoked through the
         real pipeline.** `CoderAgent.run()`/`revise()` are `async def`, invoked from a sync graph
         node via `asyncio.run(...)` (deviation #13) -- meaning `verify()` (called synchronously,
         deep inside that async call chain, with no thread of its own) always executes with an
         asyncio event loop already running on that thread. Playwright's sync API refuses to run
         on such a thread at all. This was invisible in every test up to this point because
         `test_render_checker.py`/`test_coder_verify.py` call `verify()`/`check_runtime_render`
         from plain synchronous scripts/tests with **no** event loop running -- only a real,
         genuine end-to-end `revise()` run (see below) surfaced it: every one of 3 coding attempts
         failed with `"home page render": failed -- "It looks like you are using Playwright Sync
         API inside the asyncio loop."` Fixed by running the actual Playwright-touching work
         inside a dedicated `concurrent.futures.ThreadPoolExecutor` worker thread from within
         `check_runtime_render` itself -- a fresh thread has no event loop of its own, regardless
         of the caller's context, with no change to the function's public signature or any
         caller. New regression test drives this through `asyncio.run(...)` specifically (calling
         the function directly inside a running coroutine, not via `asyncio.to_thread`, which
         would already dodge the bug) to actually reproduce the failure mode.
    - **New human-in-the-loop iteration capability: `CoderAgent.revise(feature_id, request)`**,
      mirroring Requirement/Architecture Agent's existing `.revise()` pattern (load latest
      artifact + a human `revision_comment`, regenerate, save as a new version, never overwriting,
      require fresh approval) -- adapted for the fact that the Coder Agent's real output is a live
      git branch, not just a JSON document. This closes a real, previously-unaddressed gap: before
      this, the only way to influence a re-run at all was to manually resume the LangGraph run, and
      `human_comment` never reached the agentic coding loop's own task message, only the planner.
      - New `workspace_service.resume_feature_branch(project_id, feature_id)`: checks out an
        EXISTING branch **without resetting it** (raises `ValueError` if no such branch exists) --
        the key difference from `run()`'s `start_feature_branch`, which always deletes and
        recreates from `main`. A revision builds on top of prior work; it does not discard it.
      - New `CoderAgentReviseRequest` schema (`revision_comment`, `revised_by`) and
        `POST /features/{feature_id}/agents/coder/revise` endpoint, same error-handling shape as
        the existing `/requirement/revise`/`/architecture/revise` endpoints.
      - New `CoderAgent._find_latest_code_plan_artifact`: finds the latest `CODE_PLAN` artifact
        **regardless of approval status** -- a revision should be possible even before a prior
        version has been approved/merged (a human may want several rounds of feedback first).
      - **A real, non-obvious design bug found only by a genuine end-to-end run, not by the
        mock-based unit tests written first**: `revise()`'s re-plan is naturally a *delta* (a
        human asking to "add a loading spinner" produces a plan that only touches
        `CommentList.jsx`, not one that re-lists every endpoint/entity the *prior* plan already
        implements) -- but `_plan_with_retries` validated that delta alone against the **full**
        architecture plan's endpoint/entity/requirement coverage, the same check used for a
        brand-new `run()`. Confirmed directly: a real revision request against the live Task
        Comments feature failed both planning attempts with `"code_plan_json does not cover these
        API endpoints: ['/api/task-comments']..."` even though those endpoints were already
        correctly implemented and untouched by this revision. Fixed by adding an optional
        `coverage_baseline_files` parameter to `_plan_with_retries` -- for revise() only, coverage
        is validated against the **union** of the prior plan's files and the new delta's files,
        while the plan actually returned (and coded) remains just the delta. Mock-based tests
        alone would never have caught this, since they stub out `plan_validator.validate` entirely
        -- a new test exercises the **real, unmocked** validator against a realistic architecture
        plan + prior-plan/delta-plan pair to lock this in.
    - Tests: `tests/test_nav_checker.py` (new, 10, page-reachability logic, no Docker/LLM),
      `tests/test_render_checker.py` (new, 3: real render check passes on the untouched scaffold,
      the sandbox port-mapping mechanism itself, and the event-loop reproduction above),
      `tests/test_workspace_scaffold.py` (+5: `_upgrade_client_app_jsx` backfill + idempotency,
      `resume_feature_branch` checks-out/raises), `tests/test_coder_prompt.py` (+2: unconditional
      link rule, parameterized-route list-page guidance), `tests/test_coder_verify.py` (+4: page
      reachability pass/fail, runtime-render hard-fail-on-home-crash, statuses wired through
      end-to-end), `tests/test_coder_agent_revise.py` (new, 4: raises with no prior run, resumes
      instead of restarting the branch, frames the plan as a revision not a rejection, and the
      real-validator coverage-union fix). Full suite: **155 passed** (up from 153 before adding
      the last two regression tests above).
    - **Real end-to-end verification against both live projects, not just synthetic fixtures**:
      triggered `ensure_project_repo` for real against `proj_a2e3d529` (e-commerce-platform,
      currently on `feature/signup`) and `proj_53284a63` (taskflow, currently on
      `feature/task-comments`) -- both got the `FEATURE_LINKS` marker backfilled wholesale
      (confirmed via `git log`: "Backfill scaffold upgrades: ... home page navigation" on top of
      each project's existing history), proving the backfill mechanism works on real,
      already-diverged repos, not just fixtures. Ran `coder_verifier.verify()` for real against
      both: `page reachability` correctly **fails** on both (neither project has ever had a link
      retroactively added for its pre-existing route -- an accurate, honest result, not a
      regression), while every other step (install, boot, build, endpoint coverage,
      **home page render: passed**) is clean. One transient false-negative on `server boot` was
      observed and confirmed non-reproducing on an immediate isolated re-run -- the same
      already-documented class of Docker-contention flakiness noted below, not a regression.
      Then ran the real `CoderAgent.revise()` end-to-end against the live Task Comments feature
      (`feature_5521adbd`) with a genuine human revision comment ("add a loading spinner while
      comments are being fetched") -- this is what surfaced both real bugs above. After fixing
      them, re-verified the same already-correct generated code (a clean, minimal, well-scoped
      diff: one line added to `CommentList.jsx`'s existing loading state, nothing else touched)
      and saved a corrected, accurate artifact set as **v4** (`artifact_8169b564` and siblings) --
      same "re-verify the same code with a corrected checker, don't re-spend real LLM time for a
      cosmetic re-confirmation" precedent already established for Signup (item 20). Confirms the
      whole revise() flow for real: prior branch commits preserved (`git log` shows the original
      `attempt 1`/`attempt 2` commits still present, untouched), a fresh version saved
      independently of v1-v3, approvable on its own.
    - **A second real bug in the coverage-union fix itself, found only by the user actually
      calling `POST /features/{id}/agents/coder/revise` through Swagger for a genuine SECOND
      revision** (not caught by any test written so far, since none exercised more than one
      revision): the coverage-baseline union above only ever used the *latest* saved CODE_PLAN
      artifact's own file list -- but that latest artifact (v4, saved from the loading-spinner
      revision) itself only lists its own delta (`CommentList.jsx`), by design, not the original
      plan's full file list. So a second revision's baseline silently lost everything the
      *original* plan (v1/v2) implemented, reproducing the identical
      `"code_plan_json does not cover these API endpoints: ['/api/task-comments']..."` rejection
      this whole mechanism exists to prevent -- this time surfaced directly to the user as a 400
      through the real API, not just in a background script. Fixed by adding
      `CoderAgent._collect_cumulative_plan_files(feature_id)`, which unions file entries across
      **every** CODE_PLAN version ever saved for the feature (later versions winning for the same
      path), not just the latest -- `revise()` now passes this as `coverage_baseline_files`
      instead of the single latest plan's own files. **Any future logic that treats "the latest
      saved plan" as "everything this feature has ever implemented" will hit this same class of
      bug** -- after the first revision, that's no longer true by design. New regression test
      (`test_revise_coverage_baseline_spans_every_prior_version_not_just_the_latest`) seeds two
      prior plan versions (a full v1 + a delta-only v2, mirroring the real history) and confirms
      a third revision's real, unmocked `plan_validator` still passes. **Re-verified for real
      against the live feature with a genuine second revision** ("add a delete confirmation
      dialog before deleting a comment") -- planning succeeded with no coverage error at all this
      time, the generated diff is exactly right (wraps the existing `onDelete` call in a
      `window.confirm(...)` guard, nothing else touched), and `verify()` came back clean on every
      step except the same already-known, out-of-scope `page reachability` gap for
      `/tasks/:taskId` (unrelated to this revision, not a regression). Saved as artifact set v5.
22. **`CoderAgent.revise()` only worked when the human named the exact file(s) to change -- a
    vague, file-unspecified request (e.g. "styles are missing, add tailwind css") never correctly
    identified which files were affected. Fixed by giving revision planning real tools to look at
    the actual codebase, instead of a single-shot LLM call with zero visibility into it.** The
    user reported this directly, having had to manually enumerate files like `TaskflowHomePage.jsx`
    and `TaskDetailPage.jsx` one at a time to get anything done. Root cause, confirmed by reading
    the code: `code_plan_json` for a revision was produced by `CodePlanner.generate()` -- a
    single-shot, non-agentic LLM call whose only context is the SRS/Architecture Plan/project
    manifest/UI manifest/human comment, with **zero ability to look at the real, current files** --
    it could only correctly scope a change when told exactly what to do, never when it had to
    figure out *what's affected* on its own.
    - **New agentic revision planner**, reusing tools/patterns already proven elsewhere in this
      codebase rather than inventing new mechanisms:
      - `tools.py`'s new `build_revision_planning_tools(project_id, feature_id)`: a read-only
        subset of the coding loop's own tools (`list_dir`/`read_file`/`search_code`/
        `read_project_manifest`/`read_ui_component` -- explicitly excludes write_file/apply_patch/
        run_shell/check_syntax/list_unimplemented_planned_files, since planning must never touch
        the working tree), plus a new `submit_code_plan(plan_json: str)` tool -- the model's one
        and only way to finish. Deliberately a JSON **string** argument, not a nested `list[dict]`
        tool argument, so parsing reuses the already-proven `CodePlanner._extract_json_object`
        (with its existing repair-prompt fallback) instead of an untested nested tool-call schema.
      - `planner.py`'s new `CodePlanner.generate_via_exploration(...)`: builds the same
        `create_agent(model=get_agentic_chat_model(), tools=..., system_prompt=...)` shape
        `coding_loop.py`'s `build_coder_react_agent` already uses, with a bounded
        `REVISION_PLANNING_RECURSION_LIMIT` (see below for why this needed raising twice).
      - New `CODE_PLANNER_AGENTIC_REVISION_SYSTEM_PROMPT` + `build_agentic_revision_planner_user_prompt`
        (`prompt.py`) -- shares the existing coverage/scaffold-awareness hard rules with the
        single-shot prompt (factored into `_CODE_PLANNER_SHARED_HARD_RULES`/`_CODE_PLAN_JSON_SHAPE`
        to avoid drift), adds explicit instruction to use the tools (especially for a broad,
        file-unspecified request), and seeds the prompt with the cumulative file list from
        `_collect_cumulative_plan_files` (item 21's fix) as a starting point the model can still
        look beyond via its own tools.
      - `agent.py`: `_plan_with_retries` gained an `exploration_context: tuple[project_id,
        feature_id] | None` -- when set (only `revise()` sets it; `run()` is unaffected, since
        planning happens before any feature branch exists there), each attempt calls
        `generate_via_exploration` instead of `generate`. **Required reordering in `revise()`**:
        `workspace_service.resume_feature_branch(...)` now happens BEFORE planning, not after --
        the exploration tools read whatever is currently checked out, so the feature branch's real
        content must already be checked out when planning starts.
    - **Two more real, reachable failure modes found ONLY by running this for real against the
      live Task Comments feature with the user's exact wording -- neither was caught by the
      mock-based unit tests written first, since those don't exercise a real, multi-turn
      tool-calling loop**:
      1. The exploration loop is genuinely open-ended (a vague ask can require many list_dir/
         read_file calls), and the first real run used 16 real tool-calling turns without ever
         calling `submit_code_plan`, hitting the initial 25-turn budget and raising
         `CodePlanGenerationError` uncaught -- crashing the whole `revise()` call. Fixed two ways,
         mirroring the exact lesson already learned for the coding loop's `GraphRecursionError`
         (item 20): bumped `REVISION_PLANNING_RECURSION_LIMIT` 25 -> 50, and made
         `_plan_with_retries` catch `CodePlanGenerationError` from the exploration path and retry
         with an efficiency-focused hint ("don't re-read a file you've already read..."), instead
         of letting it crash the request.
      2. Even with real exploration happening, the model **correctly discovered Tailwind was
         already fully configured project-wide** (tailwind.config.js/postcss.config.js/index.css's
         `@tailwind` directives all already present) but still **converged on the wrong fix**
         (planning to modify `index.css`) instead of finding the one actual unstyled page
         (`TaskflowHomePage.jsx`, using raw inline `style={{...}}` throughout, zero `className`
         usage). Root cause: finding files that do **NOT** match a pattern (no Tailwind classes) is
         a much harder "inverse search" for a model to carry out reliably via manual list_dir/
         read_file/search_code than finding files that DO match one. Fixed with a new deterministic
         tool, mirroring the exact `nav_checker.py`/`route_checker.py` "cheap, best-effort regex
         heuristic" precedent: `style_checker.py`'s `check_component_styling(workspace_root)`
         scans every `.jsx` file under `client/src/pages`/`client/src/components` and reports
         `"styled"` (has `className=`), `"inline_styles"` (only raw `style={{`/`style={`), or
         `"unstyled"` (neither) -- exposed as a new `check_component_styling` tool in
         `build_revision_planning_tools`, with the system prompt explicitly instructing the model
         to call it FIRST for a styling-related comment and trust its answer over manual inference.
    - **Real end-to-end proof, the user's exact reported problem, verified twice (once
      pre-`check_component_styling`, confirming the gap; once after, confirming the fix)**: called
      `coder_agent.revise('feature_5521adbd', ...)` with the literal comment "Styles are missing in
      the generated code so add styles using tailwind css" -- **no file names given at all**.
      Before the styling tool: planned only `client/src/index.css` (wrong -- Tailwind was already
      configured). After adding the tool: planned exactly `client/src/pages/TaskflowHomePage.jsx`
      (modify), with the model's own summary correctly stating "All other components appear to
      already be using Tailwind CSS classes appropriately" -- an accurate, correctly-scoped
      diagnosis with zero file names supplied by the human. The actual generated diff is exactly
      right: every raw inline `style={{...}}` in that file was replaced with the equivalent
      Tailwind utility classes (`p-8 font-sans`, `text-2xl font-bold`, `mt-2`, `text-blue-600
      hover:underline`, etc.), nothing else touched.
    - **Known, separate, pre-existing bug found along the way, NOT part of this fix and not
      introduced by it**: this run's `verify()` still reported `verification_passed: False`, but
      solely because `client build (vite build)` fails with `ReferenceError: module is not defined
      in ES module scope` at `client/postcss.config.js:1` -- that file uses CommonJS
      (`module.exports = ...`) while `client/package.json` declares `"type": "module"`, which
      forces Node to treat every `.js` file as an ES module. Confirmed this predates this fix
      entirely (`postcss.config.js` already existed, already broken, on the commit before this run
      started) -- likely a leftover from earlier, separate manual testing that set up Tailwind in
      this project. The coding loop actually noticed and attempted a fix on its own initiative
      (created a `postcss.config.cjs` with the same, correct content -- `.cjs` is exempt from the
      `"type": "module"` rule), but left the original broken `postcss.config.js` in place alongside
      it, so the build still fails (Vite/PostCSS's config resolution still finds the broken `.js`
      file). **Not fixed here** -- deleting the stale `client/postcss.config.js` (keeping the
      already-correct `.cjs` version) would resolve it, but that's a separate, small, pre-existing
      project bug outside this session's scope (making `revise()` understand vague requests), left
      for a future pass or a human's own `git rm client/postcss.config.js` on the live project.
    - Tests: `tests/test_style_checker.py` (new, 6, pure regex-heuristic tests, no LLM/Docker),
      `tests/test_revision_planner_tools.py` (+1 for `check_component_styling`, tool-set-shape
      assertion updated), `tests/test_coder_planner_exploration.py` (new, 4: parses a submitted
      plan, raises when never submitted, recursion-limit-as-clean-failure, malformed-JSON repair
      path -- all mock-based, no real LLM), `tests/test_coder_agent_revise.py` (+2: resume-before-
      planning call-order assertion, exploration-recursion-limit retry-with-efficiency-hint).
      Full suite: **172 passed** (up from 156 before this item).
23. **Two more real bugs found from the user continuing to hit real, reachable failures through
    the live `/coder/revise` endpoint on the same TaskFlow feature -- one in the exploration
    planner's reliability at real project scale, one an actual, separate frontend bug (a blank
    page mistaken for "no styles").**
    - **Exploration planner reliability at real project scale, confirmed with two full real
      re-runs of the same request** (a vague "this /tasks endpoint doesn't have styles... or
      TaskDetailPage.jsx" comment): the first hit `REVISION_PLANNING_RECURSION_LIMIT` (still 50 at
      the time) after real, substantial exploration; a second real run (~4.5 hours, due to a severe
      apparent Ollama/inference slowdown in this environment -- individual tool-calling turns that
      previously took seconds took minutes each) got through both planning attempts without hitting
      the turn limit at all, but **both times submitted a plan with an empty `files` list**,
      failing `code_plan_json.files must be a non-empty list` -- a different failure mode than
      either previously-seen one (recursion exhaustion, or coverage rejection). Given the multi-hour
      real cost of further live reproduction, root-caused and fixed the improvable parts directly
      rather than continuing to re-run live:
      - `REVISION_PLANNING_RECURSION_LIMIT` bumped 50 -> 80 (`planner.py`) -- exploration is still
        cheap (filesystem-only), so a larger budget costs little and helps as the project (now
        11+ files across many revisions) keeps growing.
      - `CODE_PLANNER_AGENTIC_REVISION_SYSTEM_PROMPT` gained a new rule 1b (`prompt.py`): planning's
        job is only to decide WHICH files need a plan entry, not to draft the actual code change (a
        later, separate coding step does that and reads each file itself) -- so it should prefer a
        summarizing tool (`check_component_styling`/`read_project_manifest`/`search_code`) over
        reading full file contents one at a time, and call `submit_code_plan` as soon as it's
        confident rather than continuing to explore "to be thorough." This directly targets wasted
        turns spent reading files whose content isn't actually needed for a planning-level decision.
      - The exploration-recursion-limit retry feedback (`agent.py`) was rewritten: the old text
        ("don't re-read a file you've already read") was **not actionable** -- a fresh retry
        attempt is a brand-new agent conversation with zero memory of what the previous attempt
        actually explored, so it has no way to know what "already read" even refers to. The new
        feedback asks for a general strategy change instead (prefer summarizing tools, stop
        exploring once confident) rather than an unfollowable specific instruction.
      - **Not yet root-caused**: why the model submitted an *empty* files list specifically (rather
        than, say, a wrong-but-non-empty one, as happened earlier with `index.css`). No visibility
        into the actual tool-call trace was available after the fact (no checkpointer configured on
        the exploration agent, so a completed run's intermediate messages aren't inspectable
        afterward) -- if this recurs, adding a checkpointer (or logging each tool call as it
        happens) would be the way to actually see what the model was doing right before submitting.
    - **A second, real, structural bug in the coverage-union fix (item 21/22)**: even after fixing
      the turn-budget/efficiency issues, a real run's plan was rejected by `plan_validator` for not
      covering the literal endpoint string `/api/task-comments` -- but the actual backend routes
      had been legitimately restructured (in earlier work) to `/api/tasks/:taskId/comments` +
      `/api/comments/:commentId`, a real, valid API design improvement. Since the Architecture
      Plan's `api_endpoints` is a frozen snapshot from before the feature was ever implemented, and
      `_collect_cumulative_plan_files`'s union can only reflect what's in *saved plan* `maps_to`
      values (not the literal Architecture Plan requirement, which never changes), **once a
      feature's real API shape evolves past that snapshot, no future revision can ever satisfy the
      old literal string again** -- permanently blocking every subsequent `revise()` call on that
      feature, regardless of plan quality or turn budget. Fixed: `CodePlanValidator.validate(...)`
      (`plan_validator.py`) gained `enforce_endpoint_coverage: bool = True` -- `_plan_with_retries`
      (`agent.py`) passes `enforce_endpoint_coverage=exploration_context is None`, so **endpoint
      coverage remains a hard gate for a first `run()`** (where it's genuinely important that the
      plan covers everything the Architecture Plan promised) **but is skipped for `revise()`**
      (which builds on an already-implemented, already-approved feature whose real API shape can
      legitimately keep evolving). Entity and requirement-ID coverage remain enforced for revisions
      either way -- those track WHAT the feature does, not the exact shape of its API, and are far
      less likely to legitimately go stale the same way. New tests in
      `tests/test_coder_plan_validator.py` (+2: flag skips endpoint coverage only, entity/
      requirement coverage still enforced; flag defaults to `True`).
    - **The actual, real frontend bug the user was hitting**: not a styling gap at all.
      `TaskDetailPage.jsx` already existed, fully built and already using real Tailwind classes
      throughout (card layout, priority/status badges, styled comment list/input) -- but **no
      `<Route path="/tasks/:taskId">` was ever registered** in `App.jsx`, even though
      `TaskflowHomePage.jsx` already links to specific task URLs (`/tasks/123`, etc.). Navigating to
      any of those links rendered a **completely blank page** (confirmed directly with a real
      Playwright screenshot before the fix) -- indistinguishable, to a human, from "the page has no
      styles," since a page that never renders at all looks exactly like one with zero CSS. Fixed
      directly (added the missing `<Route>` + import) rather than through `revise()` again, given
      the multi-hour real cost already spent reproducing the exploration-planner issues above.
      Verified with a real browser screenshot after the fix: `/tasks/123` renders the fully-styled
      Task Details page (including a styled "Failed to load comments" error state, since no live
      backend was connected for this specific check -- expected, not a bug) with zero JS errors,
      and full `coder_verifier.verify()` passes end-to-end (`page reachability` now correctly
      passes too, since `/tasks/:taskId`'s static prefix `/tasks` is registered and linked).
24. **Architecture Agent upgraded end-to-end: coder-friendly Architecture + Implementation Plan,
    project-aware, tool-using, enhanced-SRS-exclusive** -- a 5-milestone user-requested upgrade
    (full plan: it was in `C:\Users\ASUS\.claude\plans\soft-petting-star.md` before being
    overwritten by the next milestone, per this file's own convention). The Architecture Agent
    previously produced an SDS-flavored plan from a single-shot LLM call over one feature's SRS,
    with zero visibility into the rest of the project -- concrete gaps the user pointed at
    directly (the plan wasn't concrete enough for the Coder Agent to act on unambiguously, and
    the agent planned each feature blind to the rest of the project). Diagrams (use case,
    sequence, class) were explicitly **out of scope for this change** and remain exactly as they
    were -- generated deterministically by dedicated modelers from `(srs, plan)`, never by the LLM.
    - **M1 -- `implementation_plan`, an AI-executable blueprint, added to the schema** (`prompt.py`,
      `agent.py`, `sds_validator.py`, `markdown_builder.py`): `backend.files/endpoints/models`,
      `frontend.pages/components_to_reuse/services/routing`, `implementation_order`,
      `constraints` -- concrete file paths, exact endpoint method/path/request-fields/response/
      error-cases, model field lists, matching the scaffold conventions the Coder Agent's own
      planner prompt already teaches (`server/src/routes/...`, `FEATURE_ROUTES_END`/
      `FEATURE_LINKS_END` markers). **`design_views` (the Coder Agent's two load-bearing fields,
      `interface_view.api_endpoints`/`data_view.data_entities`) is completely unchanged** --
      `implementation_plan` is purely additive.
      - New `ArchitectureAgent._ensure_implementation_plan`/`_build_implementation_plan`: a
        deterministic floor guaranteeing every plan -- LLM-authored, single-shot, agentic,
        SRS-derived fallback, or a converted legacy `sds`-type plan -- carries a structurally-valid
        `implementation_plan`, mechanically derived from `design_views` + the SRS when the LLM
        omitted or malformed it. This matters because the fallback rung is a real, frequently-hit
        path (confirmed again in this milestone's own E2E run, see M5 below), so it can never
        produce a schema the validator then rejects.
      - `sds_validator.py`'s `_validate_implementation_plan`: structural presence checks
        conditioned on what the SRS actually asks for (backend.files non-empty only when the SRS
        has api_expectations, etc.) -- same coverage-checking idiom already used for `design_views`.
    - **M2 -- project-aware context (still single-shot at this point)**: new
      `artifact_service.list_project_artifacts(...)` -- the **first project-scoped artifact
      query** in this codebase (every artifact already carries `project_id`, but every existing
      lookup was feature-scoped only). New `ArchitectureAgent._load_previous_architecture_plans`
      uses it to find every OTHER feature's latest APPROVED plan in the same project (including
      the legacy `sds`-type lookup, same fallback the Coder Agent's own architecture-plan loader
      already has). `build_architecture_user_prompt` gained a previous-plans summary (endpoints +
      entities + implementation file paths only, never the full JSON -- the Ollama context budget
      is real) and a project-manifest section (reused `project_memory_service`, same as the Coder
      Agent).
    - **M3 -- agentic, tool-using generation, as a new FIRST rung on the existing reliability
      ladder** (never a replacement for it): new `app/agents/architecture_agent/tools.py`
      (`build_architecture_planning_tools`) and `_generate_raw_output_via_exploration` in
      `agent.py`, modeled directly on the Coder Agent's proven
      `build_revision_planning_tools`/`generate_via_exploration` pattern (read-only tools +
      `submit_architecture_plan(plan_json: str)` + captured dict, `ARCHITECTURE_PLANNING_RECURSION_LIMIT
      = 80`, `GraphRecursionError`/no-submission both treated as "fall through to single-shot").
      **Deliberately NOT built by filtering `build_coder_tools`**: that builder calls
      `workspace_service.ensure_project_repo` at construction time (a side effect that CREATES the
      workspace) -- wrong here, since the Architecture Agent runs before any code exists and a
      project's first feature legitimately has no workspace yet (every workspace tool degrades to
      a clear "no workspace yet" string instead of raising). The ladder is now: agentic exploration
      -> single-shot (now also with M2's project context) -> JSON-repair -> deterministic
      fallback -> proceed-with-caveat -- every existing rung preserved, the agentic one only ever
      precedes them.
    - **M4 -- input/output integration**: input side -- `srs_for_generation = enhanced_srs_json or
      srs_json` used consistently everywhere (prompt builder, validators, all three diagram
      modelers) so an Enhanced SRS, when the (still-stub) Domain Agent someday produces one,
      supersedes the plain SRS entirely rather than both being sent. Output side --
      `coder_agent/prompt.py`'s shared context-section builder (used by BOTH the single-shot and
      agentic revision planners) renders `architecture_plan_json["implementation_plan"]` as a new
      "follow its file paths, endpoint specs, model fields, and implementation order" section when
      present, and gracefully omits it for a legacy plan that predates this milestone (confirmed
      directly against the real, live e-commerce-platform Login plan -- still stored under the
      legacy `sds` artifact type with old-style `introduction`/`design_context` keys -- prompt
      builds with no crash, `design_views`-derived `required_endpoints`/`required_entities` still
      populate correctly since that shape never changed, and the new section is correctly absent).
    - **M5 -- real, live verification, not just synthetic tests**: full suite **199 passed** (up
      from 174). Real E2E: created a genuinely new feature ("Task Search") on the live TaskFlow
      project (`proj_53284a63`, which already has an approved Task Comments plan + a real
      workspace) via the real Requirement Agent -> real Architecture Agent. The agentic rung hit
      its turn limit on this real run and correctly fell through; the single-shot rung's raw LLM
      output was missing every one of the ~15 top-level required keys entirely (a real, severe
      single-shot miss, unrelated to this milestone's own changes) and repair also failed; the
      **deterministic fallback rung produced a complete, valid plan** -- confirming the
      reliability ladder and M1's fallback-schema guarantee both work for real, not just in
      fixtures. The resulting `implementation_plan` had concrete, real content: 3 backend files,
      1 model, 1 page, 6 ordered implementation steps.
      - **Confirmed the actual point of this milestone**: fed this real plan to the real
        single-shot Coder planner (`code_planner.generate`, bypassing the retry loop for a first
        look) -- its `files` list was an **exact match** to the implementation_plan's own file
        paths (`server/src/models/TaskSearchDataEntity1.js`,
        `server/src/routes/task-search.routes.js`, `server/src/app.js`,
        `client/src/services/taskSearchService.js`, `client/src/pages/TaskSearchPage.jsx`), with
        the model's own summary explicitly citing "the approved architecture blueprint." This is
        a measurably more concrete result than the old abstract SDS ever produced for this class
        of feature (the SDS-era planner's documented failure mode was exactly *under*-planning
        backend files -- see the gotcha below, still real, but no longer starting from nothing).
      - **Also confirmed, honestly, a separate real limitation this milestone does NOT fix**:
        that same real plan's `maps_to` field values were unreliable across two different LLM
        calls (once containing the file's own path instead of the required endpoint/entity/FR-ID
        strings; once missing the field structurally) -- the real `_plan_with_retries` call
        exhausted both attempts and raised `CodePlanValidationError`, exactly matching this
        project's **already-documented, pre-existing** Coder Agent planner gotcha (below) that
        predates this milestone entirely. Not conflated with this milestone's own work, and not
        fixed here -- fixing Coder Agent planner reliability was never this milestone's scope.
      - Verified the legacy path directly against the real, live e-commerce-platform Login plan
        (see M4 above) -- confirmed working, not just asserted.
    - New test files: `tests/test_architecture_plan_schema.py`, `tests/test_architecture_project_context.py`,
      `tests/test_architecture_agent_exploration.py`, `tests/test_architecture_enhanced_srs.py`
      (33 tests total across all four, all passing) plus `scripts/run_taskflow_architecture_e2e.py`
      (the real E2E script, kept as a reusable verification tool matching this repo's existing
      `scripts/run_*_manual.py` convention).
    - **Real state**: `proj_53284a63` (TaskFlow) gained a new feature, `feature_29fa0ed4` ("Task
      Search"), with an approved SRS and an approved Architecture Plan (`artifact_dc772d18`,
      approved during this milestone's own M5c verification) plus rendered use case/sequence/class
      diagrams -- left in place as real, inspectable verification output, not debris. No code was
      generated for it (the Coder Agent step was only planning-level, per the milestone's own
      scope) -- a natural next feature to actually build out in a future session.

25. **Use Case Diagram rewrite: accurate, complete, UML-standard-compliant** -- a user-requested
    6-milestone rewrite (full plan: `C:\Users\ASUS\.claude\plans\soft-petting-star.md`, overwritten
    since per this file's convention). The user identified the generated use case diagrams as not
    accurate/complete enough, with three confirmed real failures directly from saved `.puml`
    artifacts: **garbled names** (`"A Task The Can"`, `"A Enters A Keyword"`, `"Initiate Page"` --
    raw SRS sentence fragments mangled by regex), **CRUD over-fragmentation** (`"Validate Email"`/
    `"Validate Password"`/`"Validate Credentials"` as three separate use cases for one login flow),
    and **undetected near-duplicates** (`"Initiate Forgot Password Process"` vs. `"Initiate Recovery
    Flow"` citing the same requirement). Root cause: the LLM only ever produced a loose categorized
    `usecase_specification_json`; a deterministic modeler then synthesized the actual use case
    names via regex phrase-surgery on raw SRS sentences (`_make_validation_use_case_name`,
    `_make_extension_name`, `_extract_error_topic`, `_extract_recovery_topic`, `_short_topic`) --
    fundamentally NLP-by-regex, reliably broken on ordinary English. **Sequence and class diagrams
    were explicitly out of scope and remain unchanged.**
    - **M1 -- strengthened the LLM-facing schema/prompt** (`prompt.py`): the LLM now produces a
      near-final `use_cases: [{name, type: main|included|extension, description,
      related_requirements, included_in, extends}]` list directly, replacing the old loose
      `primary_use_cases`/`included_behaviours`/`extension_behaviours`/`exception_flows` shape.
      New rules: exactly one `main` entry (never the feature name restated), 2-5 word
      action-oriented names with no leftover fragment words, explicit anti-CRUD-fragmentation and
      dedup-by-meaning instructions, mandatory accurate `related_requirements` (this powers M3's
      new duplicate/fragmentation checks).
    - **M2 -- thinned `usecase_modeler.py`: trust the LLM's list, add real dedup**: new
      `_build_use_cases_from_specification` trusts the LLM's `use_cases[]` directly (no regex
      sentence-mining) whenever it's non-empty; the old `_build_main_use_cases`/
      `_build_included_use_cases`/`_build_extension_use_cases` become fallback-only (invoked only
      when the specification is genuinely empty). Replaced the old exact-name-only
      `_dedupe_and_merge` with a 3-pass `_merge_near_duplicates`: exact normalized name, identical
      non-empty `related_requirements` sets (catches synonym-level duplicates no string metric
      would, e.g. the Forgot-Password/Recovery-Flow case above), and stem/token Jaccard overlap on
      names (small private stemmer, no embeddings library -- nothing in this codebase uses
      `sentence-transformers` directly today).
    - **M3 -- strengthened `usecase_validator.py`**: new `_validate_use_case_name_quality` (rejects
      names containing a standalone article/determiner/possessive-pronoun/Given-When-Then token --
      catches the real garbled examples, while deliberately excluding generic auxiliary verbs like
      `do`/`is`/`are` so the pre-existing `"Do Something"` regression fixture keeps passing); new
      `_validate_use_case_fragmentation` (flags 2+ included/extension use cases under the same main
      use case sharing a leading `INTERNAL_STEP_VERBS` word, or sharing an identical non-empty
      `related_requirements` set -- catches the real `"Validate X"/"Validate Y"/"Validate Z"`
      anti-pattern). **An initially-added fourth check ("main use case name just restates the
      feature name") was removed after a real regression** -- see the gotcha below.
    - **M4 -- new targeted use-case repair-retry loop**: `_complete_usecase_model` became `async`
      and now runs the full `UseCaseQualityValidator` right after building the model (moved
      earlier than before); on a quality failure it calls a new, cheap, targeted
      `_repair_usecase_specification` (one `provider.invoke_agent` call with just the FR list,
      user_stories, out_of_scope, the failed specification, and the exact validator error text --
      mirrors `CoderAgent._plan_with_retries`'s "generate → validate → retry with the specific
      error fed back" idiom, capped at `MAX_USECASE_REPAIR_ATTEMPTS = 2`). **Deliberately gated off
      entirely when the specification is genuinely empty** (the true last-resort fallback rung) --
      making a new LLM call from the rung whose whole purpose is "the LLM already failed twice"
      would defeat its purpose. Never raises for a quality failure; the later
      `_validate_full_output` call remains a final, harmless re-confirmation.
    - **M5 -- honest, simplified fallback naming + dead-code removal**: the fallback path (reached
      only when the specification is truly empty) now names the main use case from `feature_name`
      alone (no business-goal regex-mangling -- a feature name like "Login" or "Task Comments" is
      already a reasonable use case name); new `_build_fallback_supporting_use_case` names
      supporting use cases via best-effort stem-overlap match against `user_stories[].goal`, or one
      gentle `_clean_use_case_name` truncation pass otherwise -- no multi-pass regex verb/topic
      extraction. `_clean_use_case_name` itself was hardened to strip standalone filler words
      (`NAME_FILLER_WORDS`) from anywhere in a name, not just the leading position -- a real test
      failure showed the 5-word truncation alone could still leave a mid-sentence "the"/"my" as a
      leftover fragment (e.g. "Validate The User Credentials Against"). **Deleted, confirmed dead**
      in `agent.py`: `_build_usecase_from_srs` (~240 lines, its result was always immediately
      overwritten by the following `_complete_usecase_model` call), plus
      `_build_security_flow_records` (a bonus find -- zero callers anywhere, confirmed via
      `grep -rn` across `app/`), `_build_usecase_traceability`, `_verb_phrase_from_feature`,
      `_usecase_name_from_text`. In `usecase_modeler.py`: the entire old regex-phrase-surgery
      cluster (`_build_main_use_case_name`, `_make_validation_use_case_name`, `_make_action_name`,
      `_make_extension_name`, `_infer_field_name`, `_extract_error_topic`,
      `_extract_recovery_topic`, `_short_topic`, `_is_generic_use_case_name`) plus their
      now-unused `COMMON_FIELDS`/`GENERIC_USE_CASE_NAMES` class constants.
    - **A real regression found and fixed during M6's own test run, not caught by design review**:
      the M3 "main use case name restates the feature name" check directly contradicted M5's own
      design (fallback names the main use case from `feature_name` verbatim). For any multi-word
      feature name (e.g. "Task Comments"), the honest fallback would deterministically trip that
      check every time, and `test_architecture_agent_exploration.py`'s
      `test_exploration_submission_is_used_without_any_single_shot_call` caught it immediately --
      the check made the deterministic fallback (the one rung that must always succeed) fail its
      own validation, cascading the whole reliability ladder past single-shot into JSON-repair.
      **Removed the check entirely** rather than special-casing it: a literal feature-name match
      is not actually incorrect UML (single- and multi-word feature names like "Login" or "Task
      Comments" are both conventional, legitimate use case names on their own), just not maximally
      descriptive -- not worth breaking the fallback's designed reliability over.
    - **A second real bug found only by the M6 real E2E run** (not by any unit test, since it
      requires two different fallback code paths landing on the same 5-word-truncated name): the
      deterministic fallback produced a genuine cross-category duplicate --
      `"Find Specific Tasks Quickly Using"` appeared as BOTH an included use case and an extension
      use case for the real Task Search feature, because `_merge_near_duplicates` was only ever
      called once per category list (`included_use_cases`/`extension_use_cases` separately), so a
      duplicate spanning the include/extend boundary was invisible to it. Fixed with a new
      `_merge_near_duplicates_across_categories` (runs the same 3-pass dedup over
      included+extension combined, then splits back by each surviving item's own `category` field,
      first-seen-category-wins on a cross-boundary collision). Confirmed fixed against the exact
      real SRS that produced the bug (`outputs/taskflow/feature-task-search/01_requirements/
      task_search_srs_v2.json`): before the fix, `UseCaseQualityValidator.validate()` raised
      `"Duplicate use case name found: Find Specific Tasks Quickly Using"`; after, it passes clean.
    - **Real, live verification, not just synthetic tests**: new
      `tests/test_architecture_usecase_modeler.py` (16 tests -- LLM-specification trust/dedup +
      fallback naming/traceability/relationships), `tests/test_architecture_usecase_validator_quality.py`
      (7 tests -- real garbled names, real 3-way "Validate X" fragmentation, legitimate
      "Validate Credentials" not raising, shared-requirements duplicate detection), and
      `tests/test_architecture_usecase_repair.py` (4 tests -- repair fixes on first attempt, repair
      never succeeds falls through without raising, repair retries up to
      `MAX_USECASE_REPAIR_ATTEMPTS`, repair loop skipped entirely for the true fallback rung). Full
      suite (excluding the three pre-existing Docker-dependent files that fail in this environment
      for unrelated reasons -- `test_coder_tools.py`/`test_coder_verify.py`/`test_render_checker.py`,
      all needing a reachable Docker daemon this machine doesn't have running): **167 passed, 0
      failed**. Real E2E: ran `scripts/run_taskflow_architecture_e2e.py` for real (new feature
      "Task Search" on the live TaskFlow project, `feature_244e26d1`) -- this is the run that
      surfaced the cross-category duplicate bug above. Also exercised the real, unchanged
      `ArchitectureAgent.revise()` for this feature (one real LLM call, not the full multi-turn
      exploration rung) specifically to confirm the new `async _complete_usecase_model` signature
      works there too, and to produce a v2 diagram reflecting the cross-category-dedup fix for
      real -- confirmed clean: `outputs/taskflow/feature-task-search/03_architecture/
      task_search_usecase_v2.puml` has one "Task Search" main use case and one, single, correctly
      `<<include>>`d "Find Specific Tasks Quickly Using" use case, versus the original (git HEAD)
      v1's `"Validate Date"`/`"Initiate Recovery Flow"`/`"A Enters A Keyword"` garbled set.

26. **Sequence + Class Diagram rewrite: dynamic, accurate, UML-standard-compliant** -- a
    user-requested 6-milestone rewrite (full plan:
    `C:\Users\ASUS\.claude\plans\soft-petting-star.md`, overwritten since per this file's
    convention), applying the same LLM-driven pattern item 25 proved for use cases to the
    remaining two diagrams. Confirmed both were 100% deterministic before this: `sequence_modeler.py`
    always emitted the SAME fixed 5-8 message template (submit -> validate -> alt success/fail ->
    optional repo/DB round-trip -> optional external token call) for every feature, only the
    endpoint/participant names varying; `class_modeler.py` always built the same
    Controller/Service/Repository/DTO/Entity skeleton, with attribute content coming from
    `_infer_fields_from_text`/`COMMON_FIELDS` keyword-guessing whenever `design_views`'
    request/response models or data entities arrived as free text. Confirmed real UML-standards
    gaps by reading both builders directly: class relationships had **no multiplicity/cardinality
    notation at all**; the sequence builder supported only `alt`/`opt`/`else` fragments and
    `sync`/`return`/`self` messages -- no `loop` fragment, no async message type. **Hard
    constraints honored throughout, unlike item 25's scope**: the use case pipeline
    (`usecase_modeler.py`/`usecase_validator.py`/`usecase_builder.py`/`usecase_specification_json`/
    `_complete_usecase_model`/`_repair_usecase_specification`) was never touched, and
    `architecture_plan_json`'s `design_views`/`implementation_plan` schema was never touched --
    the new LLM-authored input is two new, additional, sibling top-level fields.
    - **M1 -- new `sequence_specification_json`/`class_specification_json` schema + rules**
      (`prompt.py`): both fully LLM-authored (participants/interactions and classes/relationships,
      not a hybrid of deterministic-skeleton-plus-LLM-content), added as siblings of
      `usecase_specification_json` in the same top-level JSON object -- automatically inherited by
      the agentic prompt via the existing `_SHARED_RULES_AND_SCHEMA` string-split, same zero-drift
      mechanism the use-case schema already relies on. New "Sequence/Class Diagram Specification
      Rules" blocks: sequence requires real actor/boundary/control participants and a real
      main-success-then-alternative flow (not a template), new `loop_start`/`async` vocabulary for
      genuinely repeated/fire-and-forget behavior; class requires real, feature-specific
      DTO/entity attributes (never a placeholder single field) and mandatory
      `source_multiplicity`/`target_multiplicity` on every association/aggregation/composition.
      New `SEQUENCE_REPAIR_SYSTEM_PROMPT`/`build_sequence_repair_prompt` and
      `CLASS_REPAIR_SYSTEM_PROMPT`/`build_class_repair_prompt`, structurally identical to the
      use-case repair prompt but fully independent.
    - **M2 -- thinned both modelers**: new `_build_from_specification` in each trusts the LLM's
      content directly (deterministic id assignment + name-to-id resolution only -- a message/
      relationship referencing an unresolvable participant/class name is skipped, not crashed);
      the entire old template/keyword-derivation body in each was demoted to
      `_build_fallback`/`_build_fallback_classes_and_relationships`, invoked only when the
      specification is genuinely empty, unchanged in behavior.
    - **M3 -- new validator quality checks**: `sequence_validator.py` gained
      `_validate_message_quality` (flags a message repeated verbatim between the same two
      participants outside a loop fragment -- correctly suspended for anything nested inside a
      `loop_start`/`end` block, including nested `alt`/`opt`) and extended fragment-balance to
      accept `loop_start`. `class_validator.py` gained `_validate_multiplicity` (every
      association/aggregation/composition must carry standard UML cardinality notation on both
      ends; dependency/inheritance/generalization exempt) and `_validate_class_quality` (flags an
      anemic dto/entity with zero attributes, or one whose attributes are ALL generic placeholder
      names like a lone `id`/`field`/`value`/`data` -- a genuine mix of real and generic-named
      fields is not flagged).
    - **M4 -- new, fully independent repair-retry loops**: `_complete_sequence_model`/
      `_complete_class_model` became `async`, mirroring `_complete_usecase_model`'s shape exactly
      (`MAX_SEQUENCE_REPAIR_ATTEMPTS`/`MAX_CLASS_REPAIR_ATTEMPTS = 2`, own new
      `_repair_sequence_specification`/`_repair_class_specification`, gated off entirely when the
      specification is genuinely empty -- no LLM call from the rung whose purpose is "the LLM
      already failed twice") -- never sharing prompts, state, or calls with the use-case repair
      loop. All 5 existing call sites for each (3 ladder rungs, the fallback rung, `revise()`)
      updated to `await`.
    - **M5 -- additive builder changes, fully backward compatible**: `sequence_builder.py` gained
      `loop` fragment rendering and an `async` (open-arrowhead `->>`) message type, alongside the
      unchanged `sync`/`return`/`self`. `class_builder.py` gained UML cardinality label rendering
      (`"1" --> "0..*"`-style) on relationships that carry `source_multiplicity`/
      `target_multiplicity`, rendering exactly as before when either is absent (e.g.
      dependency/inheritance). The fallback's one deterministic `association` relationship
      (Repository manages Entity) was given a default `"1"`/`"0..*"` multiplicity so the fallback
      path itself passes the new multiplicity gate, not just the LLM-driven path.
    - **Two real bugs found only by the M6 real E2E run, both in the pre-existing, unmodified
      fallback logic** (not by any unit test, since both require a specific upstream data shape
      the synthetic fixtures didn't have): re-running `ArchitectureAgent.revise()` for real against
      `feature_244e26d1` (the same real TaskFlow "Task Search" feature item 25 created) surfaced
      that its real, previously-approved architecture plan's `design_views.interface_view.
      api_endpoints` contains the exact same endpoint (`GET /api/task-search`) as **two separate
      dict entries** -- a pre-existing, upstream architecture-plan data-quality issue, out of scope
      to fix at the source per this milestone's own "don't touch the architecture plan" constraint.
      This silently produced (a) a genuine duplicate sequence message (now correctly rejected by
      the new `_validate_message_quality` check) and (b) a genuine duplicate class operation on the
      Controller (`getApiTaskSearch` twice, since `_controller_operations` had no dedup pass unlike
      `_service_operations`, which already called `_dedupe_operations` on its own result). Fixed
      both at the point each modeler *consumes* the endpoint list, not by touching the plan itself:
      new `_dedupe_endpoints` in `sequence_modeler.py`'s fallback (normalized method+path key), and
      `_controller_operations` in `class_modeler.py` now calls the already-existing
      `_dedupe_operations` just like `_service_operations` does. Confirmed fixed directly against
      the real data that produced the bug.
    - **A third, more serious real bug found only by the same E2E run**: `revise()` had **no
      safety net around its own `_validate_full_output` call**, unlike the main generation ladder's
      true last-resort rung (`_build_fallback_architecture_output`'s caller wraps it in a
      try/except and proceeds with a caveat on the plan -- an already-established, approved
      pattern in this exact file). Since `revise()` always uses an empty usecase/sequence/class
      specification (only the plan text itself is revised by the LLM; every diagram always comes
      from the deterministic fallback), a heuristic validator failure on ANY diagram would crash
      the entire revision outright with no recourse -- a real, reproducible crash confirmed live
      (a genuinely anemic `dto` class from the SAME real feature's architecture plan, whose
      request/response model fields are literally named `"field"` upstream with the real
      description stuffed into a `"format"`/`"description"` key instead -- another pre-existing,
      out-of-scope-to-fix architecture-plan data-quality issue). Fixed by wrapping
      `_validate_full_output` in `_revise_architecture_plan_output` with the identical
      try/except-and-caveat-note pattern already used by the main ladder's fallback rung, rather
      than inventing new handling. Confirmed fixed live: `revise()` now completes with
      `status: revised` and a `human_approval_note` caveat instead of raising.
    - **A confirmed, honest model-quality observation, not a code bug**: a real single-shot LLM
      call (bypassing the slow, turn-limited agentic exploration rung on purpose, to keep real
      verification cheap) against the real Task Search SRS twice failed to produce ANY
      schema-conformant output at all -- once inventing an entirely different, flattened JSON shape
      with none of the required top-level keys, once returning a near-empty 2-character response.
      This is the SAME class of pre-existing single-shot unreliability item 25's M5 already
      documented (a severe single-shot miss, unrelated to this milestone's own changes) -- but the
      now-larger combined schema (three full specification blocks instead of one) plausibly makes
      it worse for this local model by pressuring its generation budget. Not fixed here (out of
      scope -- this milestone's job was the pipeline, not single-shot model reliability); the
      existing reliability ladder (single-shot -> JSON-repair -> deterministic fallback ->
      proceed-with-caveat) already tolerates this without crashing, confirmed by the real
      `revise()` runs above landing cleanly on the fallback path both times.
    - **Real, live verification, not just synthetic tests**: new
      `tests/test_architecture_sequence_modeler.py` (7 tests), `tests/test_architecture_class_modeler.py`
      (7 tests) -- LLM-specification trust (including unresolvable-name skip, loop/async
      preservation, invalid-enum-value defaulting) + fallback path; `tests/test_architecture_sequence_validator_quality.py`
      (5 tests -- duplicate-message detection in/out of loops, nested-fragment suppression,
      loop fragment balance) and `tests/test_architecture_class_validator_quality.py` (9 tests --
      anemic/placeholder-only dto/entity detection, multiplicity presence/notation/exemption) --
      new files, no pre-existing sequence/class quality test files existed; `tests/test_architecture_sequence_repair.py`/
      `tests/test_architecture_class_repair.py` (4 tests each -- repair fixes on first attempt,
      repair never succeeds falls through without raising, repair retries up to the attempt cap,
      repair loop skipped entirely for the true fallback rung). Full suite (same 3 pre-existing
      Docker-dependent exclusions as item 25): **203 passed, 0 failed** (up from 167). Real E2E:
      re-ran the real, unchanged `ArchitectureAgent.revise()` against `feature_244e26d1` four
      times across the fix cycle above, each run driven by an actual real bug the previous run's
      output exposed -- (1) crashed on the sequence duplicate-message validation error (no safety
      net yet); after adding the `_dedupe_endpoints` fix, (2) still crashed, now on the class
      anemic-DTO validation error, which is what exposed `revise()`'s missing safety net in the
      first place; after adding that safety net, (3) completed successfully with an honest
      caveat, but its own v3 `.puml` output visually revealed the *separate*, validator-uncaught
      duplicate-operation bug in the Controller class; after adding the `_controller_operations`
      dedupe fix, (4) completed fully clean. Final `task_search_sequence_v4.puml`/
      `task_search_class_v4.puml` confirmed directly: no duplicate messages/operations, real
      `CLS_REPOSITORY "1" --> "0..*" CLS_ENTITY_00N : manages` multiplicity notation rendering
      correctly, and an honest, accurate `human_approval_note` caveat surfacing the genuinely
      anemic (upstream-data-caused) DTO fields for human review rather than hiding the problem.
    - **Real state**: `feature_244e26d1` (the same TaskFlow "Task Search" feature from item 25)
      gained `task_search_sequence_v3/v4.puml`/`.png` and `task_search_class_v3/v4.puml`/`.png`
      (v1/v2 from item 25's use-case verification predate this milestone's fixes and are left in
      place, not debris) plus three more Architecture Plan JSON/Markdown versions from the three
      real `revise()` calls above -- all left in place as real, inspectable verification output.

27. **Architect Agent: dynamic, tool-using, reliably-generated diagrams** -- a user-requested
    5-milestone follow-up to item 26, prompted by the user directly observing that every generated
    sequence/class diagram still had the identical structure regardless of feature (full plan:
    `C:\Users\ASUS\.claude\plans\soft-petting-star.md`, overwritten since per this file's
    convention). **Confirmed with hard evidence**: read `login_class_v6.puml`,
    `task_comments_class_v1.puml`, and every `task_search_class_v*.puml` directly -- all had the
    exact same Controller/Service/Repository/DTO/Entity skeleton, with the Repository's operations
    being the **literal, hardcoded strings** `findRequiredData()`/`saveChanges()` in every single
    one regardless of feature. This is the deterministic fallback's own literal output --
    item 26's LLM-authored path was essentially never reached in real usage.
    - **Root cause, confirmed by direct testing**: the single mega-call (agentic exploration or
      single-shot) asked the local LLM to produce `architecture_plan_json` (~15 top-level keys
      including a detailed `implementation_plan`) **plus** `usecase_specification_json` **plus**
      `sequence_specification_json` **plus** `class_specification_json`, all in one JSON response.
      Real testing against this exact model (item 26's own verification) showed it failing to
      produce schema-conformant output at that size -- once inventing an entirely different
      flattened JSON shape, once returning a near-empty 2-character response. The agentic
      exploration rung's tools were all about gathering context for the *plan* -- none helped the
      model construct or validate the diagrams themselves.
    - **Independent design review before implementation** (a Plan agent that read the full real
      implementation and this file's own history of a *different* agentic loop -- the Coder
      Agent's revision planner -- taking up to ~4.5 real hours on this same local model) refined
      the initial one-combined-loop design into **two sequential, independently-gated loops**
      (sequence first, then class informed by the finalized sequence names) for two concrete
      reasons: smaller per-loop turn budget, and -- more importantly -- **nothing structurally
      keeps a class diagram's names consistent with its sequence diagram's names once both are
      freely LLM-authored** (today's deterministic fallback only agrees because it derives both
      from the same feature name mechanically); running class second with a
      `read_finalized_sequence_names` tool makes consistency a property of the design, not a
      hoped-for prompt convention.
    - **M1 -- shrank the main plan prompt back down** (`prompt.py`): removed
      `sequence_specification_json`/`class_specification_json` and their rule blocks from
      `ARCHITECTURE_AGENT_SYSTEM_PROMPT` entirely (also fixed `tools.py`'s
      `submit_architecture_plan` docstring, which independently told the tool-calling LLM to
      produce the same two fields via the tool schema itself, not just the system prompt) -- the
      main call goes back to just `architecture_plan_json` + `usecase_specification_json`, a
      reliability win for that call on its own. New, relocated (not deleted) content split into
      four new prompt pairs: `SEQUENCE_DIAGRAM_AGENTIC_SYSTEM_PROMPT`/
      `build_sequence_diagram_user_prompt` and `CLASS_DIAGRAM_AGENTIC_SYSTEM_PROMPT`/
      `build_class_diagram_user_prompt` for the two new agentic loops; `DIAGRAM_FOCUSED_BOTH_
      SYSTEM_PROMPT`/`build_diagram_focused_both_prompt` and `DIAGRAM_FOCUSED_CLASS_ONLY_
      SYSTEM_PROMPT`/`build_diagram_focused_class_only_prompt` for the new non-agentic fallback
      tier.
    - **M2 -- new `diagram_tools.py`**: `build_sequence_diagram_tools`/`build_class_diagram_tools`,
      each returning read tools (`read_functional_requirements`/`read_acceptance_criteria`/
      `read_interface_and_data_context`), a **validate-in-the-loop tool**
      (`validate_sequence_draft`/`validate_class_draft` -- parses the model's draft, runs it
      through the real modeler+validator, returns `"VALID"` or the exact error text so the model
      can self-correct BEFORE submitting, not just react after a final failure), and a submit
      tool. The class builder's tools additionally include `read_finalized_sequence_names`.
      Deliberately no "read a previous feature's diagram" tool on either builder -- the whole
      point is diagrams grounded in THIS feature's real content, not a structural precedent
      pulling the model back toward sameness. Each validate tool tracks a failed-attempt counter
      and, after 3 failures, appends a soft nudge ("submit your current best draft now") to its
      own return text -- the same "efficiency-hint feedback" idiom already established for the
      Coder Agent's revision planner in this codebase, so an unproductive loop is more likely to
      still submit *something* before the hard recursion-limit backstop discards everything.
    - **M3 -- new agentic diagram-generation steps in `agent.py`**: `SEQUENCE_DIAGRAM_RECURSION_
      LIMIT`/`CLASS_DIAGRAM_RECURSION_LIMIT = 20` (smaller than the main plan's 80 -- each loop
      covers one narrow artifact). New `_generate_sequence_diagram_via_exploration`/
      `_generate_class_diagram_via_exploration`, mirroring `_generate_raw_output_via_exploration`'s
      exact `create_agent`/`ainvoke`/`GraphRecursionError` pattern at a smaller scope. The class
      step is only ever invoked after the sequence step has already succeeded.
    - **M4 -- new `_complete_diagram_models`, replacing 5 call sites**: three tiers, most-dynamic
      first -- (1) the two sequential agentic loops; (2) a focused, non-agentic single-shot call
      for whichever specification(s) are still missing (combined, if sequence itself failed since
      there's nothing yet to keep class consistent with; class-only with the finalized sequence
      embedded, if only class failed -- **a successful sequence result is never discarded just
      because class alone failed**); (3) the existing deterministic fallback inside the modelers,
      unchanged, reached only if both above produce nothing. **A real design subtlety found while
      implementing this**: `parsed` is recreated fresh at every ladder rung within
      `_generate_architecture_output` (confirmed by reading the code), so memoizing "has the
      agentic tier been attempted" *inside* `parsed` -- the review's original suggestion -- would
      not actually survive a rung cascade. Fixed by threading a separate
      `diagram_generation_state` dict explicitly from the caller instead (the same dict passed to
      every `_complete_diagram_models` call within one `_generate_architecture_output` invocation),
      which both bounds the expensive agentic tier to one attempt per outer call AND caches a
      successful result outright for free reuse by a later cascaded rung, an improvement on the
      original "memoize a bool" suggestion. `attempt_agentic=False` (used for the deterministic-
      fallback rung and `revise()`) skips tier 1 entirely -- both still get real, feature-grounded
      diagrams via tier 2 instead of a fixed template, without the potentially-long agentic tail
      on paths that are supposed to be fast/reliable.
    - **Real, live verification, not just synthetic tests**: new `tests/test_architecture_diagram_
      tools.py` (15 tests) and `tests/test_architecture_diagram_exploration.py` (11 tests --
      capture/raise contracts for both exploration methods, and the full `_complete_diagram_
      models` rung matrix: both-agentic-succeed, sequence-succeeds-class-fails, sequence-fails,
      both-fail, `attempt_agentic=False`, and memoization across two simulated cascading calls).
      One pre-existing test (`test_exploration_submission_is_used_without_any_single_shot_call`)
      needed updating -- its old assertion ("exploration succeeding means zero single-shot calls")
      no longer held now that diagram generation is fully decoupled from the plan's own success;
      fixed by extending its mocks to also simulate the two new diagram exploration steps
      succeeding, preserving the test's original intent rather than weakening the assertion. Full
      suite (same 3 pre-existing Docker-dependent exclusions as before): **229 passed, 0 failed**
      (up from 203). Real E2E: called `_complete_diagram_models(attempt_agentic=True)` directly
      against the real, already-established architecture plan for `feature_244e26d1` (Task
      Search) -- isolating the new capability from the separately-slow main plan-generation
      exploration, which was not what this verification targeted. **Result, recorded honestly**:
      the agentic **sequence** loop hit its 20-turn limit without submitting (~4.5 real minutes,
      7 LLM calls) -- but the new **focused single-shot fallback tier** then produced genuinely
      dynamic, feature-specific content in one call: sequence messages like "Enters keyword in
      search bar" -> "Validate keyword length (min 2 chars)" -> queries against two real data
      entities, and a class diagram with real DTO attributes (`TaskSearchResult.taskId/title/
      description/detailUrl`) and real distinct operations (`searchTasks`, `findMatchingTasks`) --
      **not** the old `findRequiredData`/`saveChanges` literals. Both validators passed. Total
      elapsed: 505s. **A real rendering bug found and fixed from this run**: the LLM authored
      operation parameters as rich `{"name", "type"}` objects rather than plain strings; the
      schema never constrained the shape, and `class_modeler.py`'s `_operation_record` was
      rendering them via a raw Python dict `str()`, producing PlantUML like
      `+handleSearchRequest(name request, type TaskSearchRequest)`. Fixed with a new
      `_parameter_text` helper that renders either shape as a clean `"name: type"`. Also exercised
      the real, updated `revise()` (focused single-shot tier only, `attempt_agentic=False`) for a
      second, independent real run -- this one triggered item 26's own reactive class-repair loop
      for real (`ClassDiagramValidationError: Entity class 'TaskSearchController' has no
      attributes`), which self-corrected on its one retry and completed cleanly, confirming both
      milestones' mechanisms compose correctly. **An honest, un-fixed observation from that same
      run**: the repair fixed the *reported* anemic-attribute error, but not a deeper stereotype
      mismatch it didn't directly address -- the final diagram has "TaskSearchController" labeled
      `<<entity>>` and "TaskSearchService" labeled `<<control>>` (swapped from what their names
      imply). This is a real limitation of the repair loop's design (it only addresses the exact
      validator error text, not a full semantic review) inherited from item 26, not introduced
      here -- left as-is and recorded honestly rather than expanding scope to fix it now.
    - **Real state**: `feature_244e26d1` gained `task_search_sequence_v5.puml`/`.png` and
      `task_search_class_v5.puml`/`.png` (from the real `revise()` run above) plus another
      Architecture Plan JSON/Markdown version -- left in place as real, inspectable verification
      output, including the honest stereotype-mismatch quirk noted above.

52. **MERN → Next.js migration: the Coder Agent now generates Next.js (App Router,
    TypeScript) instead of Express+Vite/React, with the SRS/Architecture Plan/Requirement
    schema conventions changed to match, plus a new Cursor-style live preview of the
    generated app in the frontend's Result panel.** Direct user request, with an explicit
    constraint: change only the generated STACK, never the pipeline's own stage sequence.
    Full plan (`C:\Users\ASUS\.claude\plans\soft-petting-star.md`, overwritten since):
    researched via three parallel Explore passes (Coder Agent's MERN surface, Requirement/
    Architecture Agent stack assumptions, sandbox/preview infrastructure) plus an
    independent Plan-agent validation pass that caught real gaps beyond the original
    research (a factual correction on Babel's jsx+typescript plugin incompatibility, a
    missed `sandbox_service` change, and four material gaps -- a legacy-MERN-repo
    corruption risk, `render_checker.py`'s `#root`-emptiness check being near-worthless
    under SSR, missing `sandbox_service` mem/timeout changes, and `.next/` build output not
    being branch-scoped).
    - **Scope, decided up front**: kept MongoDB + Mongoose (relocated to `lib/mongodb.ts` +
      `models/<Entity>.ts`) -- swapping ORMs was never asked for. `target_stack` stays a
      free, unvalidated string everywhere (no new enum) -- only its *default* changed, so
      the two real pre-migration projects (`e-commerce-platform`, `taskflow`) are never
      retroactively invalidated. TypeScript over plain JavaScript (direct user choice, asked
      via one targeted question). Pinned to Next.js 14.2.5 specifically -- Next 14's
      `params`/`searchParams` contract is a plain object, Next 15's is a Promise requiring
      `await`; 14's synchronous form was judged simpler for a local, occasionally-unreliable
      model to get right, and the Coder Agent's prompt is written against that one contract.
    - **`workspace_service.py`**: new `NEXTJS_SCAFFOLD_FILES` (package.json pinning next/
      react/typescript/mongoose exactly, no `^`; tsconfig.json; `next.config.mjs`;
      `app/layout.tsx`; `app/page.tsx` with the `{/* FEATURE_LINKS_START/END */}` marker
      pair, same idiom as the old `client/src/App.jsx`; `app/globals.css`; `lib/mongodb.ts`
      -- a guarded, cached connection singleton mirroring item 18's own
      `mongoose.connect` guard; `app/api/health/route.ts`; `.eslintrc.json`; `.env.example`)
      replaces the old MERN scaffold as the default for every NEW project. New
      `_detect_stack(repo_path)` (presence of `server/src/app.js` vs. anything else) gates
      `ensure_project_repo`: a repo already on the legacy MERN convention gets ONLY MERN
      backfills (`_backfill_mern_scaffold`/`_backfill_mern_scaffold_upgrades`, renamed from
      the old unprefixed names but otherwise byte-for-byte unchanged) and is never written
      into with Next.js files -- confirmed this freezes `e-commerce-platform`/`taskflow`
      correctly. `SCAFFOLD_FILES`/`SCAFFOLD_GITIGNORE`/etc. renamed `MERN_*` throughout for
      clarity now that two scaffolds coexist in one file; every MERN backfill/upgrade
      function's actual logic is untouched.
    - **A REAL, BUILD-BREAKING BUG, found only by the real E2E run below, not by any of the
      extensive prior research or unit testing**: Next.js 14 (the version this migration
      deliberately pinned to) does not support `next.config.ts` AT ALL -- TypeScript config
      file support was only added in Next.js 15. Every single generated project's very
      first `next build` failed with "Configuring Next.js via 'next.config.ts' is not
      supported. Please replace the file with 'next.config.js' or 'next.config.mjs'."
      Fixed by renaming the scaffold's config file to `next.config.mjs` (plain JS with a
      JSDoc `@type` annotation instead of a TS type import -- `.mjs` forces ESM regardless
      of `package.json`'s own `"type"` field, so no other scaffold change was needed) and
      updating every reference across `verify.py`'s anti-cheat check, the Coder Agent
      prompt, and the Architecture Agent's implementation-plan text and fallback builder.
      **A second-order bug this exposed**: the already-existing (pre-fix) throwaway test
      workspace had BOTH `next.config.ts` (stale) and `next.config.mjs` (freshly backfilled)
      on disk simultaneously after the fix landed and `ensure_project_repo` ran again --
      Next.js refuses to build with `next.config.ts` present regardless of `.mjs` also
      existing, so the backfill's "only add what's missing" logic wasn't sufficient on its
      own. Fixed by making `_backfill_nextjs_scaffold` actively detect and remove a stale
      `next.config.ts` (via `repo.index.remove`, not just `unlink`, so the deletion is
      actually committed) whenever it backfills -- a real, necessary one-time cleanup step
      for any repo scaffolded between this migration's initial rollout and this fix, not
      something a brand-new project will ever hit going forward. Both bugs are now covered
      by real, unmocked git-repo tests in `test_workspace_scaffold.py`.
    - **`sandbox_service.py`**: `DEFAULT_MEM_LIMIT` raised to `2g` (both `run_command` and
      `start_background_service` now take a `mem_limit` parameter) -- `next build`'s
      bundling + full TypeScript typecheck routinely exceeded the Vite-era `1g` default,
      and a Docker OOM kill would have surfaced as an undiagnosable bare exit 137. New
      `PREVIEW_CONTAINER_LABEL` + `start_background_service(..., labels=...)` +
      `find_containers_by_label()` -- lets `preview_service.py`'s startup sweep find and
      stop orphaned live-preview containers a `--reload` restart left running, without
      needing its own in-memory registry to have survived.
    - **`tools.py`'s `check_syntax`**: widened from a 2-way (`.js` via `node --check`, `.jsx`
      via `@babel/parser`) to a 4-way matrix -- `.ts` gets `plugins: ['typescript']` (no
      `jsx`) and `.tsx` gets `plugins: ['jsx', 'typescript']`, kept deliberately separate
      because combining `jsx`+`typescript` on a plain `.ts` file breaks parsing of `<T>expr`
      type-assertion syntax (a real Babel limitation caught during planning, not a guess).
      Still syntax-only, not type-checking -- `next build` remains the one real
      type-checking gate, to avoid doubling the slowest step in the loop.
    - **The four deterministic checkers, rewritten for file-based routing**:
      `route_checker.check_route_coverage` now translates a `:param` endpoint segment to a
      `[param]` folder (`/api/tasks/:id` → `app/api/tasks/[id]/route.ts`) and checks for one
      of the three legal Route Handler export forms, instead of Express's mount-prefix
      cross-referencing (no `app.js` to cross-reference against anymore). A real bug caught
      by its own new unit tests before this ever ran for real: the first version
      double-prefixed the derived path (`app/api/api/tasks/route.ts`) because the endpoint
      string itself already includes `/api`. `nav_checker.check_page_reachability` now
      discovers pages by walking `app/**/page.tsx` (excluding `layout`/`loading`/`error`/
      `not-found`/`default`/`route.ts`, which never create routes) instead of parsing
      `<Route>` JSX, and recognizes `[param]` folder segments (not `:param` JSX props) as
      parameterized. `style_checker.check_component_styling` rescoped to `app`/`components`,
      `.tsx`. `render_checker.check_runtime_render` now serves via `next start` (not `vite
      preview`) and checks the real HTTP response status from `page.goto()` instead of
      `#root`'s emptiness -- the single most valuable free correctness upgrade identified
      during planning: under SSR there is no client-side `#root` to inspect, and a crashing
      Server Component still returns non-empty HTML, so the old check was already measuring
      the wrong thing even on the stack it was written for.
    - **`verify.py`**: one root `npm install` (no more server/client split), `next build` as
      the single build-and-typecheck gate, a `next start`+`/api/health` boot smoke test
      (skipped, not run against a stale build, if the build step failed), and a new
      `next.config.mjs integrity` anti-cheat step (greps for `ignoreBuildErrors`/
      `ignoreDuringBuilds` and hard-fails if present) -- a struggling model's easiest
      escape hatch from a real type/lint error is to suppress it at the config level
      instead of fixing it. `lint` (the scaffold's real `next lint` script,
      `eslint-config-next`) is deliberately NOT run as a gate -- ESLint flags real-but-
      non-blocking style issues that would make verification fail on cosmetic grounds for
      an already-fragile local-model coding loop; a human can still run it manually.
    - **A real, confirmed Next.js behavior found only through real Docker runs, not
      speculation**: a plain Server Component page (no `"use client"`) is statically
      PRERENDERED at `next build` time by default -- a runtime crash in one fails the
      *build*, not just a later request. This meant an early test's premise ("compiles fine,
      only crashes at real runtime") was actually wrong for a plain Server Component; fixed
      by moving the test's crash into a `useEffect` inside a `"use client"` component (which
      never executes during the server-side prerender pass) -- also the realistic shape of
      the bug class this check exists for, since every real generated feature page is
      always a Client Component per the Coder Agent's own new prompt rule. **A related,
      equally real finding**: a Route Handler with no `export const dynamic =
      "force-dynamic"` is eligible for the SAME build-time static optimization and can be
      INVOKED at build time to cache its response -- a test fixture that dropped this line
      while overwriting a route file had its intentionally-broken handler crash `next build`
      itself instead of only the real running server, defeating that test's own purpose.
      Both are genuine, confirmed Next.js semantics (not bugs in this migration's own code)
      that directly validate why `force-dynamic` is a mandatory rule in the Coder Agent's
      new prompt, not just a style preference.
    - **Architecture Agent**: `implementation_plan`'s file-path conventions rewritten
      throughout `prompt.py` and `agent.py`'s deterministic fallback builder --
      `app/api/<resource>/route.ts` for a collection endpoint and `app/api/<resource>/
      [id]/route.ts` for an item endpoint, ALWAYS two separate files now (Next.js routes by
      folder path, unlike one Express router file handling every method), grouped via a new
      `_endpoint_route_file` helper mirroring `route_checker.py`'s own translation.
      `implementation_order` no longer has a "mount the router" step at all -- its absence
      is the direct, load-bearing proof the file-based-routing simplification actually
      landed (confirmed present in every real fallback plan generated during E2E testing).
      Also fixed the second, older `coder_tasks` builder (a third path convention,
      `frontend/src/pages/*.jsx`/`backend/routes/*.routes.js`, visible in the human-facing
      plan but read by no code) and the UML noise/stopword lists across all four validators/
      modelers (added `next.js`/`typescript`/`server component`/`route handler`/
      `app router` alongside the existing `express`/`mongoose`/`react`/`node` entries) --
      confirmed `class_validator.py`/`class_modeler.py` never had an equivalent list to
      begin with (classes are legitimately allowed to be named after technical constructs
      like Controller/Service/Repository), so nothing needed changing there.
    - **Coder Agent prompt (`prompt.py`) -- the core of the migration**: `CODER_AGENT_
      SYSTEM_PROMPT` and the shared planner hard rules rewritten for Next.js App Router +
      TypeScript, prioritized by likely real local-model failure modes: a BLANKET
      `"use client"` rule (every feature page and every integrated UI/UX component, no
      case-by-case judgment call, since UI/UX components are already documented as
      self-contained with internal `useState`); the exact Next 14 synchronous `params`
      contract stated loudly with a literal signature example; Server Actions explicitly
      forbidden (Route Handlers + client-side fetch only, avoiding a second parallel data-
      fetching mental model for zero user-visible gain); the `mongoose.models.X ||
      mongoose.model(...)` guard stated as a literal mandatory template (the single most
      common real Next+Mongoose failure, `OverwriteModelError`); `export const dynamic =
      "force-dynamic"` on every DB-touching Route Handler (now doubly justified by the
      real build-time-static-optimization finding above); navigation restricted to `<Link
      href>` with a literal/template-literal string only, never `router.push`, keeping
      reachability statically provable. `planner.py`/`plan_validator.py` needed zero
      changes -- confirmed stack-agnostic by two independent passes, both before and after
      this migration.
    - **Requirement/project schema defaults**: `target_stack`'s default changed from
      `"MERN"` to `"Next.js"` in `requirement_schema.py`/`project_schema.py`, every
      `.get("target_stack", "MERN")` fallback across `requirement_agent`/`domain_agent`'s
      markdown builders, and the frontend's `CreateProjectForm.jsx`/`RequirementRunForm.jsx`
      defaults/placeholders. Confirmed the Requirement Agent's own conversational prompt/
      gap-analysis logic had zero hardcoded MERN assumptions already -- only the default
      value needed to change, directly addressing the user's own stated worry.
    - **Live preview (new capability)**: `app/services/preview_service.py` -- an in-memory
      registry (ephemeral, same precedent as `graph_orchestrator_service`'s per-thread
      state, not persisted to Mongo) mapping `feature_id -> {container, host_port,
      built_commit_sha, started_at}`, built entirely on the already-generic `sandbox_
      service.start_background_service`/`stop_background_service`. Start refuses (409) if
      no `.next/BUILD_ID` exists yet for the current checkout; records the commit SHA at
      start time and reports `"stale"` (not silently `"running"`) if the workspace's HEAD
      has since moved on, since `.next/` isn't branch-scoped and a later Coder Agent
      revision wouldn't automatically rebuild it. Starting a preview for a DIFFERENT
      feature of the SAME project while one is already running is blocked (409, naming the
      conflicting feature) rather than silently killing it -- they share one working tree.
      `CoderAgent.run()`/`revise()` both call `preview_service.stop_preview_if_running(...)`
      before touching the workspace, since a running preview's working tree is about to
      change underneath it. New `sweep_orphaned_containers()` runs once at backend startup
      (`main.py`'s `@app.on_event("startup")`) to stop any container still carrying the
      preview label from a prior process's `--reload` restart. New routes `POST/GET/POST
      /features/{feature_id}/preview/{start,status,stop}`. Frontend: `OutputPanel.jsx`'s
      Preview tab un-disabled (Files stays disabled -- a separate, not-yet-built feature);
      new `PreviewPanel.jsx` (Start/Stop buttons, an `<iframe>` once running, a clear
      inline message naming the conflicting feature on a 409) polls status while running/
      stale via a new `usePreview.js` hook, so a page refresh recovers "already running"
      state instead of looking stopped just because the backend's registry is in-memory.
    - **Real, live end-to-end verification, not just unit tests** -- driven via
      `scripts/run_nextjs_migration_e2e.py` (calling each agent directly, same established
      pattern as `run_taskflow_architecture_e2e.py`, approving through the real
      `approval_service`), plus a hand-validated-plan continuation script (matching the
      long-established `run_quickcart_coder_pipeline_manual.py` precedent) once the real
      planner hit its own separate, pre-existing, already-documented coverage-reliability
      gap (items 18/24):
      - **A genuinely useful real finding, not a migration bug**: `llama3:latest` (the
        fast model chosen for a dry run) does not support Ollama tool-calling AT ALL
        ("does not support tools", HTTP 400) -- meaning it can never drive the Coder
        Agent's agentic coding loop, only ever the non-agentic single-shot planner rung.
        There is no faster local substitute for that step; qwen3-coder-family models are
        the only tool-capable ones available, confirming why this project's own live
        settings already default `coder_agent` to `qwen3-coder:latest`.
      - **A second real finding**: the live per-agent override for `architecture_agent`
        specifically (`qwen3-coder.max:latest`, a ~30B model) took over 3.5 real hours for
        a single call before timing out -- the same GPU/VRAM-mismatch class already
        diagnosed in item 29 for this exact class of model on this machine's 6GB GPU, not
        new. Worked around by temporarily overriding only `architecture_agent` to
        `llama3:latest` for the run (restoring its exact prior override afterward, same
        "temporarily switch, then restore exactly" precedent as items 45/49/50) --
        `requirement_agent`/`domain_agent`/`coder_agent` stayed on their already-configured
        qwen3-coder-family defaults throughout, satisfying the user's specific request that
        the CODER AGENT'S output use qwen3-coder.
      - **Per-stage confirmation, real content inspected, not just "did it run"**: SRS
        `target_stack: "Next.js"` confirmed, real `api_expectations`
        (`POST/GET /api/items/{itemId}/notes`) confirmed. Enhanced SRS preserved
        `target_stack` through enrichment. Architecture Plan (reached via the deterministic
        fallback rung, itself a real, honest outcome -- the raw LLM output failed schema
        validation twice, then the fallback's own out-of-scope-actor validation also
        failed once, correctly triggering the item-26-established safety net rather than
        crashing) produced genuinely Next.js-shaped `implementation_plan` paths
        (`app/api/item-notes/route.ts`, `models/ItemNotesDataEntity*.ts`,
        `app/item-notes/page.tsx`) with confirmed NO mount-router step. UI/UX Agent
        produced two real components; both approved individually (not just the metadata),
        confirmed necessary per item 20's own established gotcha. **The real Coder Agent
        coding loop, run with `qwen3-coder:latest`**, produced genuinely correct, idiomatic
        Next.js 14 App Router + TypeScript code on inspection: `"use client"` correctly
        placed as the literal first line of every integrated component/page; the
        `mongoose.models.X || mongoose.model(...)` guard used correctly; `export const
        dynamic = "force-dynamic"` present; a real `<Link href="/item-notes">` correctly
        inserted at the `{/* FEATURE_LINKS_END */}` marker; and -- unprompted by the hand-
        written plan -- the model correctly diagnosed and fixed the approved
        `NoteInputField` UI/UX component's real, genuine gap (no submit affordance at all)
        by adding a real `<form onSubmit>` + button calling a new `onSubmit` prop, keeping
        its existing markup/styling intact, exactly matching the prompt's "read the
        component's actual prop usage" rule. `endpoint route coverage` and `page
        reachability` both passed against this real generated code, confirming both
        rewritten checkers work correctly outside of synthetic fixtures.
      - **An honest, real, NOT-migration-specific defect verify() correctly caught**: the
        coding loop also invented an unplanned, unavailable `next-auth` import (and a
        non-existent `@/lib/auth` module) to satisfy VR-002 ("only registered users can
        submit notes") on its own initiative, with no such package ever scaffolded,
        planned, or declared in `new_dependencies` -- `next build` correctly failed with
        "Module not found: Can't resolve 'next-auth'", exactly the kind of real defect the
        hard build gate exists to catch before a human ever sees broken code. This is the
        same general class of local-model over-eagerness this project has repeatedly
        documented for other agents (not a regression from this migration, and out of this
        migration's own scope to fully solve) -- recorded honestly rather than re-running
        indefinitely to get a fully clean verification, since the actual object of this
        verification (does the migration produce genuinely Next.js-shaped output, and do
        the rewritten checkers correctly gate on real defects) was already conclusively
        proven either way.
      - **A separate, real Docker/Windows infrastructure issue also surfaced twice**: `npm
        install` failed with `EACCES ... rename '/workspace/node_modules/glob'` on a
        workspace that had been `npm install`'d by several overlapping container runs in
        close succession (this session's own concurrent verification runs) -- a real
        bind-mount file-locking race, not a code defect; resolved by deleting and letting
        one clean install happen. Worth knowing for future real-pipeline testing on this
        machine, matching the already-documented "don't run the Docker-heavy suite
        concurrently with a real agent run" lesson, just via a new symptom.
    - Tests: `test_workspace_scaffold.py` (rewritten for the Next.js scaffold + new
      MERN-freeze tests + the stale-`next.config.ts` cleanup test), `test_route_checker.py`/
      `test_nav_checker.py`/`test_style_checker.py`/`test_render_checker.py` (rewritten for
      file-based routing), `test_coder_verify.py` (rewritten for the single-install/
      `next build`/`next start` flow, all 16 passing against real Docker, including the two
      that needed their own fixture fixes for the real Next.js prerendering/static-
      optimization findings above), `test_coder_tools.py`/`test_revision_planner_tools.py`
      (path/extension updates, 44 passing against real Docker), `test_coder_diff_builder.py`
      (setup-instructions text), `test_architecture_plan_schema.py` (Next.js path
      assertions), `test_coder_prompt.py` (rewritten substring locks for every new hard
      rule), new `test_preview_service.py` (10 tests, sandbox/workspace mocked -- the real
      container mechanics are already covered by `test_render_checker.py`'s Docker-backed
      tests). **389 tests collected** (up from 300), all confirmed passing across this
      session's runs (327 fast/non-Docker in one sweep; the Docker-dependent files
      individually confirmed in separate real runs against a live Docker daemon).
    - **Real state**: `proj_0892c5b6` ("NextJS Migration Verify", feature_90dfc700 "Item
      Notes") and `proj_3b717019` (same project name, feature_66e1362f, same feature name --
      a genuinely separate confirmation-run project, left in place alongside the first
      despite the name collision) both left in place as real, inspectable verification
      evidence, matching this file's own established convention -- not test debris.
      `feature_66e1362f` has a real `feature/item-notes` branch with real Coder Agent
      commits and a `verification_passed: False` artifact set (the honest, correctly-
      caught `next-auth` defect above) pending human review, not merged. Purely-internal
      scratch debris from this session's own debugging (`Debug`/`Debug4`/`Render Test`/
      `Verify Test`-named throwaway projects and their orphaned workspace directories) was
      cleaned up from both Mongo and disk, per this file's own established convention.

53. **Coder Agent revision fast path + Live Preview URL tracking.** Two direct user reports:
    (1) a real screenshot showed `revise()`'s planning phase stuck on "Exploring the codebase
    and planning your revision..." for **80 minutes 57 seconds**, even for small, well-specified
    changes; (2) the Live Preview panel showed a fixed base URL that never updated when the user
    navigated to a different route inside the iframe. Full plan (validated by an independent
    Plan-agent design review before implementation, which caught two real gaps in the first
    draft): `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Root cause, Fix 1**: confirmed by direct code reading that `revise()`/`revise_stream()`
      unconditionally routed every revision through `generate_via_exploration` (up to
      `REVISION_PLANNING_RECURSION_LIMIT=80` real tool-calling turns per attempt,
      `MAX_PLANNING_ATTEMPTS=4` -- worst case 320 turns) regardless of how precisely the human
      specified the target file(s). The single-shot planner (`planner.generate()`, one plain LLM
      call) was only ever reachable from `run()`'s first-time planning.
    - **Fix 1**: new `CoderAgent._find_well_specified_target_files(revision_comment, known_files)`
      -- a deliberately conservative regex-based heuristic (requires a real file extension; an
      exact full-path match against `_collect_cumulative_plan_files` is trusted directly; a bare
      filename is only trusted if it's the ONE file in the project with that basename, since
      generic Next.js filenames like `page.tsx`/`route.ts` legitimately recur across features --
      an ambiguous match falls through to exploration rather than guessing). `_plan_with_retries`
      gained `prefer_single_shot: bool` -- only attempt 1 skips exploration in favor of
      `planner.generate()`; `exploration_context` itself stays truthy throughout (load-bearing:
      it's what keeps `enforce_endpoint_coverage=exploration_context is None` relaxed for
      revisions regardless of which planner ran). **Two real gaps a Plan-agent review caught
      before implementation, both fixed**: the single-shot branch had no exception handling at
      all (an uncaught JSON-parse or transport failure would have crashed the whole revision
      instead of falling through to exploration on attempt 2 -- fixed with the same
      log/retry/`continue` shape the exploration branch already had); and the single-shot
      planner's prompt had zero visibility into which files already exist (risking a wrong
      `"create"` action silently overwriting real content via `write_file`) -- fixed by adding an
      optional `coverage_baseline_files` param to `CodePlanner.generate()`/
      `build_code_planner_user_prompt`, extracting the "files already touched" prompt section
      (previously only rendered by the agentic prompt) into a shared
      `_build_cumulative_touched_files_section` helper reused by both. `revise()`/`revise_stream()`
      compute `prefer_single_shot` right after `coverage_baseline_files` (already computed
      there); `revise_stream()`'s phase label is now conditional ("Drafting a plan for the
      file(s) you mentioned..." vs. the old generic exploration label).
    - **Fix 2**: the preview iframe's `src` is genuinely cross-origin (a dynamically Docker-
      assigned host port vs. the frontend's own fixed dev port) -- `iframe.contentWindow.location`
      is unreadable by the parent by browser design, not a bug to route around. New scaffold file
      `components/PreviewRouteAnnouncer.tsx` (`"use client"`, `usePathname()`, posts
      `{type: "autoforge-preview-route", path}` to `window.parent` on every path change, `"*"`
      targetOrigin -- the parent-side origin check is what's actually load-bearing), mounted in
      `NEXTJS_APP_LAYOUT`'s `<body>`. New idempotent `_upgrade_layout_for_preview_route_announcer`
      (mirrors the established `_upgrade_globals_css_for_tailwind` pattern exactly -- anchored on
      the literal `<body>{children}</body>` line, no-ops with a logged warning rather than
      guessing at an insertion point if a feature has already customized the layout past
      recognition, confirmed for real against the live `nextjs-migration-verify` project's
      already-customized `layout.tsx`). `PreviewPanel.jsx` gained `currentPath` state (reset on
      `[reloadKey, status?.preview_url]`) and a `window.addEventListener("message", ...)` that
      verifies `event.origin === new URL(status.preview_url).origin` before trusting the payload
      -- both the displayed URL text and the "open in new tab" href now append `currentPath`.
    - Tests: `tests/test_coder_agent_well_specified_files.py` (new, 10 -- exact-path match,
      unique-basename match, ambiguous-basename falls through, no-extension never matches, both
      real previously-reported vague comments from this project's own history correctly stay on
      exploration), `tests/test_coder_agent_revise.py` (+5 -- `_plan_with_retries`'s
      `prefer_single_shot` branch: uses single-shot on attempt 1, `prefer_single_shot=False`
      always uses exploration, falls back to exploration after an exception, falls back after a
      validation rejection, and a full `revise()` end-to-end test confirming a well-specified
      comment never calls `generate_via_exploration`), `tests/test_workspace_preview_route_
      announcer.py` (new, 5 -- fresh project has the component + layout mount, upgrade backfill
      adds it to a pre-existing stock layout, upgrade never touches a layout customized past
      recognition, idempotent). Full suite: **416 passed** (up from 305). `npm run build` clean.
    - **Real, live verification, not synthetic**: ran the actual `revise_stream()` against the
      real, live "Item Notes" feature (`feature_66e1362f`, `nextjs-migration-verify` project) with
      a well-specified comment naming a real file (`app/item-notes/page.tsx`) -- confirmed the
      phase label read "Drafting a plan for the file(s) you mentioned...", planning finished in
      ~50 real seconds (vs. the reported 80+ minutes), the whole revision (plan + code + verify)
      completed in **288 seconds total** with `verification_passed: True` on attempt 1/3, and the
      resulting real git commit was a clean one-line diff to the named file (`+  <p
      className="mt-2 text-sm text-gray-500">Notes are saved automatically.</p>`) -- a correct
      `"modify"`, not a recreation. For Fix 2, built a fresh throwaway Next.js project+feature for
      real inside the sandbox (`npm install && npx next build`, since the one available
      already-generated Next.js project's `layout.tsx` was already customized past the upgrade's
      anchor) with a second real page and a real `<Link>` between them, then drove the actual
      frontend through Playwright: started a live preview, clicked the in-iframe link, and
      confirmed both the displayed URL text and the "open in new tab" href updated live to
      `http://localhost:{port}/about` within ~1.5s of the click (screenshot confirmed visually);
      confirmed a Stop→Start cycle correctly reset the displayed path on the fresh host port.
      Throwaway project and Docker containers cleaned up afterward via the real `DELETE
      /projects/{id}` endpoint; the real "Item Notes" feature's new v8 revision (code_plan +
      diff + manifest artifacts) is left in place per this file's own established convention.

54. **Coder Agent revision: plain-English requests without exact file names.** Direct follow-up
    to item 53 -- the fast path only helped when the human named an exact file; the real,
    reported workflow is plain English ("the login form doesn't clear after submit"), the same
    way a human talks to Claude Code, and that still fell through to the slow, unconditional
    exploration planner. Full plan (validated by an independent Plan-agent design review that
    caught two real problems before any code was written):
    `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Two problems the design review found in the first draft**: (1) an ordering bug -- a
      content-reading pre-retrieval step called at the same point `prefer_single_shot` is
      computed would read whatever branch happens to already be checked out in the shared
      working tree, not this feature's real content, since that point is *before*
      `resume_feature_branch` runs; (2) a trust bug, more serious -- `CodePlanValidator.validate()`
      for a revision (confirmed by reading `plan_validator.py`) only checks coverage, never "is
      this the right file." A confident-but-wrong keyword/content match would pass validation,
      get coded, get verified, and reach the human as a "completed" revision that silently
      touched the wrong file -- the exact blind spot already documented in item 22 (grepping
      "tailwind"/"css" for "styles are missing" finds the files that already correctly use
      Tailwind, not the one broken one).
    - **Fix: two new tiers, with asymmetric trust, between "exact file named" and "full
      exploration"**:
      - **Tier 1a** (`agent.py`'s new `_find_keyword_matched_known_files`, metadata-only, no
        filesystem access -- safe to compute at the same point Tier 0 already is, before
        `resume_feature_branch`): fuzzy-matches the comment's keyword stems against each known
        file's own basename stems. New shared `_split_into_words`/`_meaningful_stems` tokenize
        BOTH the human's prose comment and a file's basename identically (CamelCase-aware, so
        "CommentList" typed in a comment and `CommentList.jsx` on disk produce the same stems
        even though the comment never names an extension) -- one function, not two separate
        extractors. Requires >=2 shared stems (a single generic shared word isn't real signal)
        AND a unique top-scoring file (a tie is treated as ambiguous, same "don't guess"
        philosophy as `_find_well_specified_target_files`); skips any known-files entry whose
        most recent recorded `action` is `"delete"`. Sets `prefer_single_shot=True` exactly like
        Tier 0 does, inheriting the same exception/validation-rejection retry-to-exploration
        safety net for free.
      - **Tier 1b** (`agent.py`'s new `_find_keyword_hint_files`, called AFTER
        `resume_feature_branch` since it needs real file content on disk, always computed
        unconditionally so exploration has a head start whether it's used from the start or as a
        fallback after Tier 0/1a's guess fails): a real keyword search of the workspace, reusing
        `search_code`'s exact walking logic (extracted into a new module-level
        `tools.py:search_workspace_content`, called directly as a plain function -- not through
        the `@tool` wrapper -- so `search_code` and this pre-retrieval share one source of truth;
        `.next` added to `SEARCH_EXCLUDED_DIRS` while touching this). Returns paths only, never
        content or a confidence claim -- **never sets `prefer_single_shot`**, only ever fed into
        the exploration prompt (new `prompt.py:_build_keyword_hint_files_section`, explicitly
        labeled "NOT a guarantee, especially for a request about something MISSING," threaded
        through `build_agentic_revision_planner_user_prompt` -> `generate_via_exploration` ->
        `_plan_with_retries`) as an unverified starting-point hint the model's own tools must
        confirm or override. This is the load-bearing safety property that routes around the
        design review's trust-bug finding: content matching stays a hint forever, name matching
        alone gets to skip exploration.
      - `revise_stream()`'s phase label gained a third variant: `"Drafting a plan based on your
        description..."` for Tier 1a, distinct from Tier 0's `"...file(s) you mentioned..."` and
        the exploration fallback's `"Exploring the codebase..."`.
    - **Supporting fix, found and fixed during design review**: `OllamaProvider.generate()`/
      `.stream()` (`app/providers/ollama_provider.py`) built their Ollama `options` dict with
      only `temperature`/`num_predict` -- no `num_ctx` anywhere, unlike the agentic tool-calling
      path (`agentic_model_factory.py`, sets `settings.AGENTIC_OLLAMA_NUM_CTX=32768`). This is
      the same "Ollama's server-side default context window silently truncates" gotcha already
      documented elsewhere in this file, just never patched at the one-shot path every single-shot
      agent call uses (Requirement/Domain/Architecture Agent too, not just Coder). Fixed by adding
      `"num_ctx": settings.AGENTIC_OLLAMA_NUM_CTX` to both `options` dicts.
    - Tests: `tests/test_coder_agent_keyword_matching.py` (new, 25 -- word-splitting/stemming,
      Tier 1a unique/ambiguous-tie/deleted-file/no-comment cases, Tier 1b real-content-match/
      too-few-stems/capped-at-max-hints cases against a real `tmp_path` tree, plus the
      `prompt.py` section-builder and full-prompt-threading tests), `tests/test_ollama_provider.py`
      (new, 2 -- `num_ctx` present in both `generate()`/`stream()`'s real request payload, httpx
      mocked), `tests/test_coder_planner_exploration.py` (+1 -- `keyword_hint_files` genuinely
      reaches `build_agentic_revision_planner_user_prompt`, not just accepted as a dead param),
      `tests/test_coder_agent_revise.py` (+2 -- a plain-English comment end-to-end routes through
      `planner.generate()` not `generate_via_exploration()`; a genuinely vague comment with no
      name-shaped signal at all still correctly uses full exploration, confirming the new tiers
      don't widen what counts as "well-specified"). Full suite: **447 passed** (up from 416).
    - **Real, live verification against the same live "Item Notes" feature item 53 used**: a
      genuinely plain-English comment with zero file names ("The note input field doesn't show a
      character limit warning") -- confirmed deterministically first
      (`_find_well_specified_target_files` empty, `_find_keyword_matched_known_files` uniquely
      resolved to `components/NoteInputField.jsx`), then ran the real `revise_stream()`: phase
      label correctly read "Drafting a plan based on your description...", and the **planning
      phase itself completed in ~75 real seconds** (2.2s -> 77.0s) -- the actual target of this
      fix, confirming plain-English requests no longer pay the previously-reported 30-80+ minute
      exploration cost just to figure out what to plan. The overall run then took ~37 more minutes
      across 3 coding+verify attempts -- **root-caused as Docker Desktop being unreachable during
      that window** ("Sandbox unavailable: could not reach Docker daemon"), a real, already-
      documented environmental gotcha, confirmed unrelated to this fix: restarted Docker and
      re-ran `coder_verifier.verify()` directly against the SAME already-generated code (no
      re-planning, no re-coding, matching the established item 20/27 "re-verify, don't re-spend
      real LLM time" precedent) -- **passed cleanly, every hard gate green** (`next build`,
      server boot, endpoint route coverage, page reachability, home page render). The single-shot
      planner chose to modify `app/item-notes/page.tsx` rather than `NoteInputField.jsx` directly
      (a defensible, on-topic choice, not a wrong-file mistake -- confirmed by reading the real
      diff: added a real character-limit note to the page, plus a real backend PUT endpoint
      enforcing the same 500-character limit server-side). `npm run build`: not run, since this
      fix touched no frontend files.

55. **A real, reported crash: "Objects are not valid as a React child (found: object with keys
    {id, description})" when viewing a freshly-generated SRS.** Root-caused against the user's
    own real, live SRS (`proj_34e07440` "Sample E-commerce" / `feature_94701501` "Item Listing
    (CRUD)", `artifact_2eba4476`): the SRS-generation LLM call produced `data_requirements`
    (documented as `list[str]` in `requirement_schema.py`) as a list of `{"id": "DR-001",
    "description": "..."}` objects, mimicking the ID-tagged shape functional_requirements/
    non_functional_requirements/acceptance_criteria/validation_rules legitimately use --
    `_parse_and_validate_json` only checked required top-level keys and FR/NFR/AC's own stable
    IDs, never the shape of `data_requirements` or the other 11 plain-list SRS fields, so the
    malformed artifact saved cleanly and crashed the frontend's `EnrichedPlainList.jsx` on first
    render (`{item}` rendered raw, no field access).
    - **Frontend fix** (`EnrichedPlainList.jsx`): new `itemText(item)` helper extracts a display
      string regardless of shape (`item.description`/`item.text`/`item.value` for an object,
      `JSON.stringify` as a last resort) -- makes an existing malformed artifact viewable
      immediately without needing to regenerate, and makes future schema drift degrade instead
      of crash. `DocumentValue.jsx` (the OTHER generic JSON renderer, used for Architecture Plan
      etc.) was checked and confirmed already fully defensive/recursive -- not a second instance
      of this bug.
    - **Backend fix, root cause** (`app/agents/requirement_agent/agent.py`): new module-level
      `PLAIN_LIST_SRS_FIELDS` (the 12 real plain-list fields: scope, out_of_scope, user_roles,
      input_requirements, output_requirements, ui_expectations, api_expectations,
      data_requirements, constraints, assumptions, risks, dependencies) + new
      `_normalize_plain_list_fields`, called at the end of `_parse_and_validate_json` (the one
      shared parse path all 4 SRS-generation call sites already funnel through) -- coerces any
      object entry to its `.description`/`.text`/`.value`, or a JSON dump as a last resort, never
      raises. `REQUIREMENT_AGENT_SYSTEM_PROMPT` also gained an explicit rule stating these 12
      fields are plain strings and naming the 5 fields that legitimately use the object shape --
      the prompt's own JSON-shape example previously showed `"data_requirements": []` (an empty
      array, no example entry) directly adjacent to FR/NFR/AC's `{"id", "description"}`-shaped
      examples, plausibly inviting exactly this pattern-copying mistake (the same "model anchors
      on nearby shown JSON shape" gotcha already documented elsewhere in this file).
    - **Real state corrected**: the actual malformed `artifact_2eba4476` (JSON) and its sibling
      Markdown artifact were normalized in place (`data_requirements` now 9 plain strings; the
      Markdown's raw Python-dict-repr bullets, e.g. `- {'id': 'DR-001', 'description': '...'}`,
      regenerated cleanly via the same `RequirementSRSMarkdownBuilder`) so the user's real,
      in-progress feature is immediately usable, not just future generations.
    - Tests: `tests/test_requirement_srs_normalization.py` (new, 6 -- object entries normalized,
      already-string entries left alone, mixed lists, a description-less object falls back to a
      JSON dump rather than crashing, the 5 ID-tagged sections are never touched by this
      normalization, and a locked list of `PLAIN_LIST_SRS_FIELDS` as a regression guard for a
      future new plain-list field). Full suite: **453 passed** (up from 447). `npm run build`
      clean.

56. **Requirement Agent: field-by-field SRS editing + fixed the disappearing post-SRS chat
    history.** Three direct user reports: must be able to change SRS content through "revise";
    must be able to change ANYTHING on the SRS explicitly (user picked field-by-field inline
    editing over a raw-JSON editor or improving the chat-only flow, when asked); the Requirement
    Agent chat disappears once the SRS is generated. Full plan (Plan-agent-validated, catching two
    real risks before implementation): `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time
    of writing.
    - **Root cause, chat-disappearing bug**: `ChatPanel.jsx` swaps `RequirementConversationChat`
      (pre-SRS gap-filling chat, the ONLY renderer of `conversation.turn_history` anywhere in the
      frontend) for `RequirementRevisionChat` (post-SRS) the moment `versions.length > 0` --
      `RequirementRevisionChat` never read `conversation` at all, even though the same shared
      `RequirementConversationFlowContext` already fetches it unconditionally. Fixed by reading
      `conversation` there too and rendering `turn_history` in a collapsed-by-default section
      (reusing `HumanBubble`/`AgentTurnBubble`, read-only -- no `onEdit`, since rewinding the
      original conversation after an SRS already exists would need to trigger regeneration, out
      of scope; the ask was visibility, not re-editing history).
    - **Direct field editing, backend**: `app/agents/requirement_agent/revision_patcher.py`'s
      `apply_revision_operations` already deterministically applied `add`/`remove`/`modify`/`set`
      against 18 of 20 real SRS fields (no LLM needed) -- the frontend just needed to become
      another producer of the same operations shape the LLM-mediated `/requirement/revise` flow
      already produces internally. New `RequirementAgent.edit_fields(feature_id, operations,
      edited_by, base_artifact_id)` mirrors `revise()`'s exact shape but skips the LLM call
      entirely, saves via the existing `_save_revised_srs_artifacts`. New route `POST
      /requirement/edit`, new `SrsFieldEditOperation`/`RequirementAgentFieldEditRequest` schemas.
      Small, backward-compatible fix to `_apply_user_story_operation`'s `modify` branch (only
      ever overwrote `.goal`, never `.role`/`.benefit`, even when the operation carried them).
    - **Two real risks a Plan-agent design review caught before implementation**: (1) a direct
      edit and an in-flight LLM revision both read the SRS before saving with no locking -- an
      edit fired mid-revision could be silently discarded when the revision's save lands
      afterward, built from a stale snapshot. Fixed with a `base_artifact_id` stale-version guard
      (`edit_fields()` rejects with a clear "updated by another change, refresh and retry" if the
      latest artifact_id has moved since the edit UI loaded); (2) `revise()`/`edit_fields()` never
      re-validate that `functional_requirements`/`non_functional_requirements`/
      `acceptance_criteria` stay non-empty after patching (unlike `run()`, which funnels through
      `_validate_stable_ids`) -- a UI trash icon makes "remove the last FR" newly easy to trigger
      by accident. Fixed both server-side (`edit_fields()` now calls `_validate_stable_ids` before
      saving) and client-side (`EnrichedItemList`'s remove button disables itself on the last item
      in those three sections specifically).
    - **Frontend inline editing**: reuses the established `HumanBubble` in-place-edit shape
      (hover reveals a pencil, click swaps to a textarea + Cancel/Save) throughout --
      `EnrichedItemList.jsx` (FR/NFR/AC/VR/user_stories: edit/remove/add per card, `target =
      item.id`), `EnrichedPlainList.jsx` (the 12 plain-string fields: same shape, `target` = the
      item's exact current text, since these have no id), new `EditableScalarField.jsx`
      (business_goal/target_stack/architectural_style -- the latter two newly promoted from the
      header-only summary line into their own full `SrsDocumentViewer` sections so they have
      somewhere to be edited). Gating: `ResultTab.jsx` computes `isLatestSrsVersion` and threads
      `featureId`/`editable` through `ArtifactContentView` -> `SrsDocumentViewer`, which further
      requires `artifactType === "srs"` (never `enhanced_srs`, Domain Agent's document);
      `ArtifactViewerModal`'s generic popup passes neither prop, so editing is structurally
      unreachable there. One shared `useEditRequirementFields` mutation (`useAgentMutations.js`,
      reusing the existing generic `useAgentMutation` helper and its awaited-invalidation
      pattern) -- one operation per Save click, each edit becomes its own new SRS version.
    - **A real, pre-existing bug found only by live-testing this feature end-to-end, not
      introduced by it**: `ResultTab.jsx`'s "a new version arrived for this stage" effect
      (comment already claimed this was handled) only ever checked whether the *previously
      selected* version had disappeared -- it never checked whether a *newer* version now
      existed. Since editing/revising never invalidates the old version, the old selection always
      "still existed," so the effect silently did nothing: a human's own edit saved correctly but
      the screen kept showing the pre-edit document with no visible sign anything happened,
      confirmed live (edited `business_goal`, screen still showed the old text; Mongo/disk showed
      the correct new v3 with the edit applied). This same bug plausibly affects `revise()` too,
      not just the new edit feature. Fixed by tracking the latest version number in a `useRef` and
      also jumping when it has genuinely increased since the last render (not just when the old
      selection vanished) -- deliberately NOT keyed on `versions` changing for any reason (e.g. an
      existing version's own `approval_status` changing), so a human deliberately reviewing an
      older version is never yanked away by an unrelated re-render.
    - Tests: `tests/test_requirement_field_edit.py` (new, 8 -- modify/add/set across all three
      field shapes, unmatched operations reported not silently dropped, last-FR-removal refused,
      stale/matching `base_artifact_id` both handled correctly, no-prior-SRS raises),
      `tests/test_requirement_revision_patcher.py` (+2 -- user_stories modify backward-compatible
      goal-only calls, and the new role/benefit extension). Full suite: **463 passed** (up from
      453). `npm run build` clean.
    - **Real, live verification against the user's own real, in-progress "Item Listing (CRUD)"
      feature** (`proj_34e07440`/`feature_94701501`, the same one item 55 fixed): confirmed the
      "Original requirement conversation (6 turns)" toggle is visible and expands to show real
      turn bubbles in the post-SRS chat; edited `business_goal` inline -- confirmed a real new SRS
      version (v3) was saved with the exact edited text and correct
      `revision_metadata.applied_changes`, though the version selector didn't visibly jump to it
      (the bug above, found by this exact test); after the `ResultTab.jsx` fix, edited a real
      functional requirement's description -- confirmed the new version (v4) was both saved
      correctly AND immediately visible on screen with no manual dropdown interaction needed.

57. **Requirement Agent: reliably change ANY SRS section via an explicit chat prompt, not just
    the field-by-field manual editor.** Direct follow-up to item 56 -- the user clarified this
    must work for every section, using "add user stories" only as an illustrative example, not
    the actual scope. Full plan (Plan-agent-validated): `C:\Users\ASUS\.claude\plans\
    soft-petting-star.md` at time of writing.
    - **Real, already-live evidence of the bug, found in the actual feature's own `assumptions`
      array before any fix**: the user had already tried this exact scenario --
      `"No SRS changes were made for revision comment: 'User stories are missing fil the user
      stories as well' -- agent's response: The human comment was unclear... No actionable
      revision was provided"` (recorded twice, from two real attempts). Root cause, confirmed by
      reading `REQUIREMENT_REVISION_SYSTEM_PROMPT` directly: its only cardinality guidance was
      `"One operation per distinct change... most revision comments need exactly one operation"`
      -- nothing told the model that a plural/section-level request ("add user stories") means
      several separate items, biasing it toward treating a broad request as too vague to act on
      at all rather than decomposing it. `apply_revision_operations` itself (`revision_patcher.py`)
      already looped over an arbitrary-length `operations` list with no cap -- confirmed via
      direct trace that N sequential `add` operations against the same field already produce
      correctly-sequenced, collision-free ids. This was purely a prompt-instruction gap, not a
      plumbing one.
    - **Fix**: two new prompt bullets (`prompt.py`, `REQUIREMENT_REVISION_SYSTEM_PROMPT`) --
      explicitly generic across all ~20 real SRS fields (not user_stories-specific), instructing
      the model that an empty-section or plural-phrased request means multiple items, one `add`
      operation each, grounded in the SRS's own other fields -- paired with an explicit
      anti-padding counter-clause (never manufacture items beyond what's genuinely implied),
      deliberately mirroring item 46's own lesson that an unbounded instruction with no
      counterweight is exactly the shape of problem that's made this local model overshoot
      before.
    - **A second, real, concrete gap found by the design review**: the operation schema shown to
      the model documented `value`/`role`/`priority` but never `benefit`, even though
      `_apply_user_story_operation` reads it and silently falls back to one generic default
      string when absent -- confirmed live in the real feature's own data (`US-004`'s `benefit`
      was literally `"complete the intended business process"`, the generic fallback). Fixed by
      adding `benefit` (and, symmetrically, `category` for `non_functional_requirements`) to the
      schema, AND wiring `category` into `_apply_id_description_operation`'s `add` branch
      (previously not set at all, not even with a default, despite `functional_requirements`'
      `priority` already getting equivalent treatment).
    - **A third, real bug found only by live-testing this fix against the real model, not
      predicted by any code reading**: a narrow, single-item scalar-field request ("update the
      business goal to also mention...") naturally produced `action: "modify"` from the model --
      a completely reasonable word for changing an existing value -- but
      `apply_revision_operations`'s dispatch only ever accepted `action == "set"` for
      `SCALAR_FIELDS`, so the operation silently fell through to the generic
      "unsupported field" catch-all and the change never happened. Fixed by accepting `action in
      ("set", "modify")` for scalar fields specifically (add/remove still make no sense for a
      field that's always present, so those are untouched) -- a code-level fix, not a
      prompt-compliance one, matching this project's own established preference for deterministic
      fixes over relying on wording alone.
    - Tests: `tests/test_requirement_revision_patcher.py` (+10 -- add-to-completely-empty-list for
      both an ID-tagged and a plain-string field, multiple same-field adds for both shapes,
      explicit `benefit`/`category` honored not overwritten by the generic default, one call
      combining operations against two different fields at once, and the scalar `set`/`modify`
      equivalence including the exact regression this session found). Full suite: **472 passed**
      (up from 463... 470 after the prompt/schema-only pass, 472 after the scalar-modify fix).
      `npm run build` not run (no frontend files touched).
    - **Real, live verification against the same real, in-progress "Item Listing (CRUD)" feature**
      (`proj_34e07440`/`feature_94701501`), three genuinely different field shapes, real model:
      (1) "Add two more user stories: one for a guest browsing without logging in, one for an
      admin managing categories" -- produced exactly two new, correctly-scoped user stories
      (`US-005`/`US-006`) each with real, distinct `benefit` text, not the generic fallback; (2)
      "Add two dependencies: image storage, caching layer" -- produced exactly two new, correctly
      -scoped plain-string entries; (3) "Update the business goal to also mention supporting bulk
      operations in the future" -- failed on the first real run exactly as predicted by the
      scalar `modify`-vs-`set` bug above (`unmatched_operations: ["Skipped operation on
      unsupported field 'business_goal' (action=modify)."]`), then after the fix, re-ran cleanly:
      `business_goal` correctly updated to "...with support for bulk operations in the future,"
      `applied_changes: ["Set business_goal."]`, `unmatched_operations: []`. All three real
      results are left in place on the real feature (new SRS versions, all pending review), per
      this file's own established convention.

65. **UI/UX Agent: removed human approval entirely, added a real `revise()`/`revise_stream()`,
    and gave it a dedicated live chat -- the third and final part of the UI/UX Agent trilogy
    (items 63-64-65) that started with the HTML+Tailwind rewrite.** Direct user request, five
    parts: remove ALL human approval from the UI/UX stage (a further escalation past item 64's
    "only the Preview Screenshot is approvable" -- now NOTHING requires a decision); let a human
    explicitly change already-generated UI by messaging the agent, "through the revise method"
    specifically; the agent must dynamically interact with and satisfy that specific request (not
    a generic regeneration); the UI/UX Agent's chat history must work "just like the other
    agents." Investigated directly (2 Explore agents, the second stalled mid-task and was
    finished by reading the remaining files directly -- a recurring reliability gap for
    background Explore agents this session, worked around the same way each time): confirmed
    `UIUXAgent` genuinely had no `revise()`/`revise_stream()` at all (only `run()`), no `/uiux/
    revise` route, no `UIUXAgentReviseRequest` schema -- matching the user's report exactly.
    Also confirmed `buildAgentTimeline` was already fully generic per-stage and needed zero
    changes -- the "no chat" complaint was specifically that `ChatPanel.jsx`'s
    `reviseMutationsByStage` had no `uiux` entry, hard-disabling the composer with a stale "can't
    be messaged directly" banner once output existed; the READ side (history) already worked,
    only the WRITE side (revise) was missing.
    - **Design decision for "remove all approval," made before writing any code**: rather than
      removing the `approval_status` concept from the data model (which would require touching
      `deriveStageStatus.js`, `STAGE_GATING_ARTIFACT`, and every approval-status-dependent lookup
      across the codebase), UI/UX artifacts are simply saved **already approved**. Confirmed by
      reading `GovernancePanel.jsx` directly that this makes every existing UI surface do the
      right thing with zero changes: it only ever renders `ApprovalPanel` (the button row) when
      `gatingArtifact?.approval_status === "pending"` -- otherwise a plain "Latest version is
      {status}. Nothing pending." line, which was already correct, already built, already tested.
    - **Backend**: `artifact_service.py`'s `save_text_artifact`/`save_json_artifact`/
      `save_binary_artifact`/`_register_artifact` all gained an optional `approval_status:
      ApprovalStatus = ApprovalStatus.PENDING` parameter -- every other caller in the codebase is
      completely unaffected (parameter omitted = today's exact behavior, confirmed by a new
      regression test). `uiux_agent/agent.py`'s `_save_artifacts` now passes
      `approval_status=ApprovalStatus.APPROVED` on every save call, and returns `(artifact_ids,
      version)` instead of just `artifact_ids` so callers can invoke `apply_design_system_patch`
      themselves. `apply_design_system_patch` (merges new components/tokens into
      `design_system.json`) is now called directly and unconditionally from `agent.py` at the end
      of every `run()`/`run_stream()`/`revise()`/`revise_stream()`, instead of being
      approval-triggered from `approval_service.py`.
    - **A deliberate, transparent reversal of this session's own immediately-prior work**: item
      64's approval-cascade mechanism (`UIUX_SIBLING_ARTIFACT_TYPES`, `_is_uiux_screenshot_type`,
      `_cascade_uiux_screenshot_decision`, the `UI_PREVIEW_SCREENSHOT` entry in
      `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES`, and its own dedicated test file) all existed
      specifically to make a human's one click on the Preview Screenshot cascade to everything
      else -- since no human click will ever happen for this stage anymore, all of it became
      unreachable and was removed outright rather than left as confusing dead code, matching this
      project's own established practice (e.g. item 45's `_placeholder_mock_props` deletion).
    - **Graph-level gate removed too, since `approval_status` alone doesn't stop LangGraph's
      `interrupt()`**: `graph_orchestrator_service.py` moved `"uiux"` from `GATED_STAGES` to
      `AUTO_APPROVED_STAGES` (joining `security`/`qa`) -- confirmed by reading `_build_graph()`
      that this loop is already fully generic over both lists, so the move alone correctly wires
      a plain `uiux_node -> coder_node` edge with no `approve_uiux` interrupt node built at all;
      `uiux_node` itself needed no changes. `frontend/src/lib/pipelineStages.js`'s own mirror was
      updated the same way. **A real, honest tradeoff, stated directly rather than engineered
      around**: a feature whose pipeline runs via the full graph `start()`/`resume()` flow will
      now auto-continue straight from `uiux_node` into `coder_node`, with no pause for a human to
      revise UI/UX output first -- accepted because this project has repeatedly confirmed (e.g.
      item 30) that the graph `start()`/`resume()` path is the less-common one in practice; the
      primary interaction model (a human working through an agent's own chat, calling run/revise
      directly) never even engages the graph unless a run happens to already be active.
    - **A real regression this move would have caused in the frontend, found and fixed before it
      shipped, not after**: `GATED_STAGES` turned out to be doing double duty across three
      frontend files as "which stages are real, selectable agents" (not just "which stages have
      an approval gate") -- `WorkspaceSelectionContext.jsx` used
      `GATED_STAGES.includes(urlAgent)` to validate the `?agent=` URL query param (item 44's
      reload-persistence fix), `FeatureListItem.jsx` looped over `GATED_STAGES` to compute the
      feature-list status dot, and `deriveCurrentStage.js` scanned `GATED_STAGES` as its
      "which real stage is current" fallback. Removing `uiux` from `GATED_STAGES` would have
      silently broken all three for the uiux stage specifically: a page reload on `?agent=uiux`
      would snap back to Requirement (reintroducing exactly the bug item 44 fixed, for this one
      stage), and the feature-list status dot / chat's default agent selection would skip over
      "UI/UX" entirely while it's actively generating, jumping straight to "Coder" instead. Fixed
      by adding a new, distinct `SELECTABLE_AGENT_STAGES` constant (`pipelineStages.js`) --
      "every real, non-placeholder agent stage," explicitly including uiux -- and repointing all
      three files at it instead of `GATED_STAGES`. `REVISABLE_STAGES` also gained `"uiux"`.
    - **Revision mechanism, mirroring the proven "small ops plan + deterministic patcher"
      pattern** (Requirement Agent item 57, Architecture Agent item 62) at the right scale for
      this schema: new `app/agents/uiux_agent/revision_patcher.py`
      (`apply_uiux_revision_operations`) matches by `(page_id, component_name)` and supports
      `add`/`remove`/`modify` -- much shallower than the SRS/Architecture Plan patchers since
      `ui_metadata_json` is just a list of pages each with a list of components, no deeply nested
      structure to walk. New `UIUX_REVISION_SYSTEM_PROMPT`/`build_uiux_revision_prompt` (shown
      the CURRENT metadata so the model can reference real component names; explicit "target must
      already exist" and anti-padding rules, matching every other revision prompt in this
      codebase). New `UIUXAgent.revise()`/`revise_stream()`: load the latest `ui_metadata_json`
      (via new `_find_latest_uiux_artifact`, regardless of approval status, mirroring Domain
      Agent's own revision-artifact lookup) -> stream/invoke the small ops-plan call -> parse with
      one JSON-repair attempt on failure, never raising (`_resolve_uiux_revision_plan`, an honest
      empty-operations plan is the worst case) -> apply via the patcher (`_prepare_revision`) ->
      for every `add`/`modify`'d component, call the EXISTING, UNCHANGED
      `_generate_component_with_quality_gate` (same quality gate, same bounded repair loop, same
      `color_theme` threading fresh generation already has) -> every UNTOUCHED component is
      carried over VERBATIM from the prior version's own saved artifact (new
      `_load_component_html_by_name`, matches by the same filename-slug convention
      `_save_artifacts` already writes) -> reassemble via the EXISTING, UNCHANGED
      `_assemble_and_render_pages` -> save via the EXISTING, UNCHANGED `_save_artifacts` (now
      auto-approved) -> `apply_design_system_patch`. `_generate_components` gained two optional,
      backward-compatible parameters (`touched_components`/`carry_over_version`, both `None` for
      `run()`) rather than a parallel duplicate method, so `run()`'s own fresh-generation
      behavior (including the cross-feature `reused_from_design_system` lookup) is provably
      unchanged -- confirmed by a dedicated regression test. New `UIUXAgent.run_stream()` too
      (streams the metadata-generation call directly, mirrors Architecture's own `run_stream`
      shape: falls through to a non-streamed JSON-repair call on parse failure, then the same
      `_validate_metadata_with_repair` ladder `run()` already uses -- extracted from
      `_generate_and_validate_metadata` specifically so both paths share the identical repair
      loop) so the chat's FIRST message streams live too, not just revisions. New
      `UIUXAgentReviseRequest` schema; new `POST /uiux/run/stream`, `/uiux/revise`,
      `/uiux/revise/stream` routes (existing `POST /uiux/run` untouched, matching every other
      agent's own non-streaming-route-stays precedent).
    - **Dedicated live chat, mirroring `ArchitectureAgentChat.jsx`/`useArchitectureAgentFlow.js`
      exactly** (the closer template of the two real precedents, since UI/UX generation -- like
      Architecture's diagram tail -- has a genuinely non-streamable tail after the main LLM call):
      new `useUiuxAgentFlow.js` (run/revise stream mutations, `runPhase`/`revisionPhase` +
      start-timestamp tracking, `AbortController`-based stop, the awaited
      `invalidateAfterCompletion` -- copied deliberately verbatim, since omitting the `await` is
      this project's own documented recurring "reply disappears instantly" bug whenever this
      pattern gets copied without it). `UiuxAgentFlowContext.jsx` rewritten in place (same
      exported names) to wrap the new hook instead of the old single `useRunUiux` mutation. New
      `UiuxAgentChat.jsx` (optimistic "You" bubble, live streaming + phase/elapsed-time banner
      with a Stop button, composer) -- no "/" document-mention picker (Domain-specific) and no
      "deep exploration mode" escape hatch (Architecture-specific), since UI/UX Agent has neither
      concept. `ChatPanel.jsx` gained a `selectedAgent === "uiux"` dispatch branch (mirroring the
      other four agents exactly) and lost the stale "can't be messaged directly"/"no revise
      action" banner and its `uiux` entries from the generic fallback's mutation maps.
      `ResultTab.jsx`'s `isUiuxGenerating` branch upgraded from a bare `isFinalizing` spinner
      reading a plain mutation's `submittedAt` to the full real-streamed-text + phase/elapsed-time
      `LiveGenerationView`, matching Architecture's own branch shape exactly; its
      Architecture-Plan-approval-auto-continue trigger now calls `handleRunUiuxStream(...)`
      instead of the old `runUiux.mutate({})`. `GovernancePanel.jsx`'s now-unreachable
      `APPROVAL_WARNINGS.uiux` entry (the button row it warned about can never render anymore)
      was removed rather than left as dead code, for the same reason as the backend cascade code.
    - **Tests**: `tests/test_uiux_revision_patcher.py` (new, 16, no-LLM -- add/remove/modify
      matching by page_id+name, duplicate-add and missing-target both correctly unmatched not
      guessed, malformed operations skipped not raised, original metadata never mutated, the
      transient `_revision_touched` marker set correctly by add/modify and never by remove).
      `tests/test_uiux_agent_revision.py` (new, 12, mocked provider/store/artifact_service/
      component_generator/preview_renderer, no real LLM/HTTP/Docker/Playwright -- `_prepare_
      revision`'s touched-component computation and honest no-op case; `_parse_uiux_revision_
      plan`/`_resolve_uiux_revision_plan`'s parse-then-repair-then-honest-empty-plan ladder;
      `_generate_components`' revision-mode carry-over-vs-regenerate branching AND a dedicated
      test proving `run()`'s own unchanged fresh-generation/reuse behavior when the new params
      are omitted; a full end-to-end `revise_stream()` run confirming the removed component is
      never (re)generated, the one remaining untouched component's HTML is looked up from the
      prior version and never touches `component_generator.generate`, every save call carries
      `approval_status=APPROVED`, and `apply_design_system_patch` is called with the correct new
      version). `tests/test_artifact_service_approval_status.py` (new, 7 -- default-PENDING and
      explicit-APPROVED for all three save methods, plus an explicit regression guard that an
      existing caller passing no `approval_status` argument at all still gets PENDING). Deleted
      `tests/test_approval_uiux_cascade.py` outright (item 64's own cascade tests -- the
      mechanism they tested no longer exists, so keeping them around failing would just be
      confusing, not informative). Full suite: **575 passed** (up from 587 before this item --
      net down because item 64's 8 now-obsolete cascade tests were deleted while a smaller number
      of new tests were added; zero regressions in anything else). `npm run build` clean.
    - **Real, live verification against the same real feature** (`feature_94701501` "Item
      Listing (CRUD)" in `proj_34e07440` "Sample E-commerce"): the first real attempt at a fresh
      full `run_stream()` (curl with `--max-time 300`, then `900`) both got cut off by the
      client-side timeout before the backend finished -- **not a bug in this change**, a direct,
      concrete re-confirmation of this project's own repeatedly-documented "closing the
      connection cancels an in-flight stream" behavior (FastAPI/Starlette cancels the underlying
      async generator on client disconnect). Switched to a Python `requests`-based script with no
      client-side timeout at all; a subsequent real full run genuinely ran for 1015 real seconds
      before hitting a real `httpx.ReadTimeout` during component generation on this machine's
      currently-configured global model (`llama3:latest`, no per-agent override set) -- correctly
      surfaced as a clean `{"type": "error", "message": "UI/UX Agent failed: ReadTimeout (no
      further detail...)"}"` event (confirming item 59's `_readable_error` fix, applied to these
      new routes from the start, correctly protects them too) rather than crashing the stream
      uncaught. Given the real time cost of a full 3-component fresh generation on this model,
      pivoted to the more directly relevant real-data test: a real `revise_stream()` call against
      the feature's actual, existing, already-approved v3 output (revision comment: "In the
      Pagination component, also show the current page indicator text") -- **completed cleanly in
      287 real seconds**, `components` phase at 12s (the single small ops-plan call, fast) then
      `assembly` at 278s (the one touched component's quality-gated generation + page
      reassembly + screenshot render). Confirmed directly: the real saved v4 `revision_metadata`
      shows `applied_changes: ["Modified component 'Pagination' on page 'item-listing-page'
      (content_elements)."]` and `unmatched_operations: []`; the component's `content_elements`
      genuinely gained `"current page indicator text"`; the regenerated HTML shows real pagination
      controls with page-count text; all 6 new v4 artifacts saved with `approval_status:
      "approved"` -- zero human action. **An honest, unrelated model-quality observation, not a
      code bug**: the regenerated Pagination component came back scoped more broadly than its
      name alone would suggest (a full item-grid "Product Inventory" card plus pagination footer,
      rather than just pagination controls) -- a real characteristic of how this local model
      interprets a single component's generation context, out of this item's own scope (which was
      the approval/revision mechanism, not general component-generation prompt tuning) to address
      further. Confirmed `apply_design_system_patch` ran without error and correctly left the
      already-registered `Pagination` design-system entry untouched (its own pre-existing,
      unchanged "only ever add NEW components" semantics -- there was nothing new to add).
      **Real browser verification** (Playwright, zero console/page errors): the live chat shows
      real history (`Started · UI/UX` / `UI/UX Agent: Produced...` / historical `UI/UX: Approved`
      pills from before this change), the stale "can't be messaged directly"/"no revise action"
      banners are both confirmed absent, and the composer is enabled with the real
      `hasOutput`-aware placeholder. "All Artifacts" for this stage correctly shows exactly what
      the mixed real history should: v4 and v3 (both genuinely `approved`, zero action buttons)
      alongside v2 and v1 (real, honest **pre-existing** legacy data from before this fix was
      built -- still genuinely `pending`, still showing their real Approve/Reject/Request-Revision
      controls) -- direct, live proof that this change only affects artifacts saved going
      forward, never retroactively rewrites history, exactly as designed. This real v4 state is
      left in place as genuine verification evidence, matching this project's own established
      convention.

66. **UI/UX Agent: restored human approval (item 65's auto-approval reversed), fixed a real
    multi-page versioning bug, and added explicit per-page revision targeting + color_theme
    redesign support.** Direct follow-up, six-part request, on the SAME feature item 65 had just
    finished regenerating: (1) revision must genuinely, dynamically incorporate whatever the human
    asks for; (2)+(4) UI/UX output must NOT auto-approve anymore -- reversing item 65's own
    "everything auto-approves" design; (3) multiple pages/UIs from one run must show as ONE
    shared version, not separate incrementing ones; (5) with multiple pages, the human must be
    able to target a SPECIFIC one for revision; (6) restated ask (1).
    - **(2)/(4), a clean revert, not a redesign**: confirmed by reading the code first that every
      approval-status-driven UI surface (`GovernancePanel`/`ApprovalPanel`/`ArtifactRow`) was
      still fully intact and untouched by item 65's work -- only 4 places needed to actually
      change back. `agent.py`'s `_save_artifacts` stopped passing `approval_status=APPROVED`
      (reverts to the default `PENDING`); the 4 direct `self.apply_design_system_patch(...)` calls
      (one each in `run()`/`run_stream()`/`revise()`/`revise_stream()` -- a real gap in the first
      implementation pass this session, only `run()`'s was removed initially, caught by a failing
      test asserting `mock_patch.assert_not_called()`) were all removed, moving that trigger back
      to being approval-gated. `approval_service.py` got its UI/UX screenshot-approval cascade
      re-added (`UIUX_SIBLING_ARTIFACT_TYPES`, `_cascade_uiux_screenshot_decision`,
      `UI_PREVIEW_SCREENSHOT` back in `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES`), mirroring the
      still-intact Architecture Plan cascade exactly. `graph_orchestrator_service.py`/
      `pipelineStages.js` moved `"uiux"` back into `GATED_STAGES`, out of `AUTO_APPROVED_STAGES`.
      `GovernancePanel.jsx`'s `APPROVAL_WARNINGS.uiux` (removed as "unreachable" in item 65) was
      restored, describing the cascade.
    - **(3): a real, confirmed bug independent of approval, found by reading `artifact_service.py`
      directly**: `save_binary_artifact` (used only for screenshots) was the *one* of the four
      save methods that never got a `version_override` parameter -- every other artifact in
      `_save_artifacts` correctly shared one `version` via `version_override=version`, but the
      screenshot loop couldn't, so `save_binary_artifact`'s own internal `get_next_version()` call
      incremented on every page saved within the SAME run. Confirmed directly against the real
      feature: a real screenshot showed "v1" through "v8" (two runs x four pages each) instead of
      two shared versions. Fixed by adding `version_override: int | None = None` to
      `save_binary_artifact`, mirroring the other three save methods exactly.
    - **A second, necessary half of (3), found by reading the frontend's own dedup logic**:
      `dedupeArtifactVersions` collapses down to ONE artifact per `(artifact_type, version)` --
      built specifically for the "one gating type's JSON+Markdown pair share a version" case
      (every other stage). Once the backend bug above was fixed and 4 screenshots legitimately
      shared one version, this same function would have silently collapsed them down to just one,
      hiding 3 of 4 pages -- caught and fixed in the same pass with a `MULTI_ITEM_PER_VERSION_
      ARTIFACT_TYPES` carve-out (currently just `ui_preview_screenshot`) that keys by
      `artifact_id` instead, never collapsing. `ArtifactRow.jsx` also gained a best-effort,
      filename-derived page label (`screenshotPageLabel`) so multiple same-version screenshot
      rows read as distinct pages ("Item Listing" / "Item Detail" / ...) instead of four
      identical-looking "Preview Screenshot v3" rows.
    - **Efficiency follow-through, matching the existing "only regenerate what's touched"
      revision philosophy**: `_assemble_and_render_pages` previously re-rendered every page's
      screenshot on every revision, even pages whose components weren't touched at all (their
      reassembled HTML is always byte-identical, but Playwright -- the single slowest step in this
      pipeline -- still re-ran). New `_load_page_screenshot_by_id` (mirrors the existing
      `_load_component_html_by_name` exactly) carries an untouched page's screenshot over
      verbatim from the prior version instead, falling through to a fresh render only if no prior
      screenshot is found.
    - **(5): explicit per-page revision targeting**: new optional `target_page_id` field on
      `UIUXAgentReviseRequest`, threaded into `build_uiux_revision_prompt` (states the target page
      plainly so the model doesn't have to infer it from prose alone -- new prompt rule 8) and all
      the way through to the frontend. `UiuxAgentChat.jsx` reads the REAL page list from the
      latest `ui_metadata` JSON artifact's own `pages[]` (never guessed from a screenshot/page-
      html filename -- confirmed a filename-derived slug can't be reliably reversed back to the
      real `page_id`, since both `-` and `_` collapse to `_` during slugification, risking a
      silent mismatch) and shows a lightweight "Revising: Whole feature | <page> | <page> | ..."
      pill selector above the composer whenever a feature has more than one page.
    - **(1)/(6): confirmed the underlying mechanism already worked** (the human's actual revision-
      comment prose, not just a terse content-diff, was already threaded into every touched
      component's real regeneration call) and extended it for whole-feature "redesign" requests:
      `UIUX_REVISION_SYSTEM_PROMPT` rule 7 previously forbade any `color_theme` change outright --
      directly conflicting with a broad "redesign"/"change the theme" ask. Relaxed to allow an
      optional top-level `color_theme` field in the ops plan when the request is genuinely about
      the feature's overall color, with the requirement that every surviving component gets
      marked touched (regenerated to match) -- reuses the exact same touched/carry-over pipeline
      an add/modify operation already uses, no new generation pathway. New rule 5 exception: a
      request naming "this page"/"this UI" as a whole (not one component) means proposing a
      `modify` operation for every real component on that page, not padding.
    - Tests: `tests/test_approval_uiux_cascade.py` (new, 8 -- rewritten from scratch since item
      65 deleted the original; the new multi-screenshot-per-version cascade case is the one item
      64's original version never had to handle), `tests/test_artifact_service_approval_status.py`
      (+1, `save_binary_artifact` `version_override`), `tests/test_uiux_agent_revision.py` (+6:
      `color_theme` change touches every component / no-op when unchanged, `target_page_id`
      stated/omitted in the built prompt, and the end-to-end revision test's stale auto-approve
      assertions flipped to confirm the default `PENDING` + `apply_design_system_patch` NOT called
      directly -- this is the exact test that caught the 3 missed `apply_design_system_patch`
      call-site removals above). Full suite: **597 passed** (up from 587). `npm run build` clean.
    - **Real, live verification against the same real feature** (`feature_94701501` "Item
      Listing (CRUD)" in `proj_34e07440` "Sample E-commerce", now with 4 real pages: Item Listing/
      Item Detail/Item Form/Item Delete Confirmation): a real, explicitly page-targeted revision
      ("Also show the current page indicator text on the Pagination component", `target_page_id:
      "item-listing"`) completed in ~340s, producing a clean v3 with `revision_metadata.applied_
      changes: ["Modified component 'Pagination' on page 'item-listing' ..."]` -- confirmed via
      direct inspection that ONLY the targeted page/component was touched. Confirmed all 4 v3
      screenshots correctly saved as `pending` (approval genuinely restored) and correctly shared
      one version number (the versioning fix). Approved one screenshot via the real API and
      confirmed all 17 sibling v3 artifacts -- including the other 3 pages' screenshots --
      cascaded to `approved` together in one action. **Real browser confirmation**: "All
      Artifacts" shows exactly 4 distinctly-labeled Preview Screenshot rows for v3 (all
      "Approved," no buttons) plus 2 older, genuinely `pending` versions each with real working
      Approve/Reject/Request-Revision controls; the chat's page-target selector renders with the
      4 real page names. Zero console/page errors. Cleaned up 6 orphaned single-screenshot
      artifacts left over from the pre-fix versioning bug (pure debris -- no accompanying
      metadata/component/page-html existed at those stray version numbers) so the feature's real
      data reads cleanly going forward. This real v3 state (4 pages, cascaded-approved) is left in
      place as genuine verification evidence, matching this project's own established convention.

67. **UI/UX Agent: present and approve each generation as ONE version on screen, not per-page.**
    Direct correction to item 66: "if the UI/UX agent generated 4 UIs for a feature at once, the
    entire generated UI must be considered as the first version" -- a revision producing a new
    bunch is the next version, for the whole bunch, not per page. Confirmed by reading the code
    that the **backend** already worked this way after item 66 (`save_binary_artifact`'s
    `version_override` fix + `approval_service`'s screenshot cascade both already treat one run's
    pages as one version) -- what was still wrong was purely the **frontend presentation**: "All
    Artifacts" rendered one row per page's screenshot via the generic `ArtifactList`/`ArtifactRow`
    (item 40's "every row gets its own independent Approve/Reject/Request-Revision" behavior,
    correct for stages where each row genuinely is an independent decision, never adjusted for the
    one type -- `ui_preview_screenshot` -- where several rows share a version and are NOT
    independent). A 4-page feature showed 4 buttons that all did the exact same thing but read as
    4 separate decisions.
    - **New `frontend/src/components/pipeline/UiuxVersionGroupList.jsx`**, replacing the generic
      `ArtifactList` for the uiux stage only (every other stage's "All Artifacts" is completely
      unchanged): groups the stage's `ui_preview_screenshot` artifacts by `version` (descending),
      renders ONE card per version -- `UI/UX Output vN`, page count, a `StatusBadge` (read from
      the group's first item; every member shares one status by construction, thanks to the
      cascade), and a thumbnail grid (one per page, reusing `ImageViewer`, matching
      `UiuxPagePreviewsPanel.jsx`'s established pattern) each labeled via `screenshotPageLabel`
      (extracted from `ArtifactRow.jsx` into a shared helper in `artifactTypeMeta.js` so both use
      identical filename-parsing logic instead of duplicating it). A pending version renders the
      **existing, unmodified** `ApprovalPanel` directly -- no reimplementation of approve/reject/
      request-revision logic, just handed the group's first screenshot as `artifact` (the backend
      cascade already makes this affect the whole version).
    - **Preserved the existing "explicit reject first" discipline** (item 40's own rule: switching
      which version is approved requires explicitly rejecting the current approval, not a stray
      click) for the NEW grouped view too -- required a small, additive `approveLocked` prop on
      `ApprovalPanel.jsx` itself (disables only the Approve button, `title` explains why; Reject/
      Request Revision stay available, matching `ArtifactRow.jsx`'s own established partial-lock
      behavior for other stages, which had no equivalent on `ApprovalPanel` until now).
    - **`GovernancePanel.jsx`**: skips its own "Stage Actions" `ApprovalPanel` for `stage ===
      "uiux"` specifically (now genuinely redundant -- the new grouped list already lets a human
      act on ANY pending version, not just whichever one `getOperativeGatingArtifact` happens to
      resolve as "the" operative one, and showing both risked two controls pointing at two
      different versions). The now-dead `APPROVAL_WARNINGS.uiux` explanatory copy was moved
      (not deleted) into `UiuxVersionGroupList.jsx` itself, shown once above the version cards
      where it's now actually relevant.
    - **`ResultTab.jsx`**: branches on `stage === "uiux"` to render the new component instead of
      `ArtifactList`, and changes the "All Artifacts (N)" header count to count **versions**
      instead of raw artifacts for this stage specifically (e.g. "All Artifacts (3)" for 3 real
      versions, not the 6 individual screenshot rows they contain) -- directly matching the "a
      bunch is one version" mental model in the one place a human's eye lands first.
    - Purely a frontend change -- no backend edits, no new tests, no new LLM generation run needed
      (item 66's own live verification already proved the backend version/cascade model correct;
      this fix only needed the real mixed data already sitting on the same feature). `npm run
      build` clean.
    - **Real, live verification against the same real feature's existing mixed data**
      (`feature_94701501`, no new generation triggered -- v3's real 4-page, already-approved
      version sits right next to v1/v2's real single-page, still-`pending` legacy versions,
      exactly the mixed real-world case this needed): confirmed "All Artifacts" now reads
      "ALL ARTIFACTS (3)" (3 versions, not 6 screenshot rows) with `UI/UX Output v3 · 4 pages ·
      Approved` shown as one card with 4 real thumbnails and zero buttons, and `UI/UX Output v2 ·
      1 page · Pending`/`UI/UX Output v1 · 1 page · Pending` each showing their own real "Awaiting
      your review (vN)" panel. Directly confirmed via Playwright's `is_disabled()` (not just a
      visual screenshot, since a locked-vs-unlocked button can look nearly identical at a glance)
      that both v1's and v2's Approve buttons were genuinely `disabled=True` with the correct
      "Another version is already approved..." tooltip, since v3 is already approved -- proving
      the ported `approveLocked` discipline works in the new grouped view exactly as it does for
      every other stage. Confirmed zero console/page errors on the uiux stage and, separately, on
      the requirement/architecture stages (unaffected by this change, `ArtifactList` untouched for
      them). This real, mixed v1/v2/v3 state is left in place as genuine verification evidence,
      matching this project's own established convention.

68. **UI/UX Agent: scoped Preview to the latest version only, freed approval of any pending
    version, and hard-enforced multi-page revision targeting instead of trusting a soft prompt
    hint.** Direct, five-part correction to items 66/67, from real, hands-on use of the feature:
    (1) the Preview section showed every historical version's pages, not just the current one;
    (2) the human must be able to approve any pending version, old or new, same as SRS -- not be
    locked into rejecting the current approval first; (3)+(4) running Revise applied changes to
    every screen regardless of which one(s) the human actually meant, and there was no way to
    scope a revision to one or more specific pages; (5) restated (1) -- outputs must visibly
    separate by version, not blend together. Investigated by reading the exact current code for
    each complaint, confirming three distinct real defects, not guessed:
    - **(1)/(5), a real, confirmed bug**: `UiuxPreviewPanel.jsx`'s `latestPageArtifacts` and
      `UiuxPagePreviewsPanel.jsx`'s `latestByFile` both claimed to "dedupe by filename" to show
      only each page's latest version -- but the real filenames `_save_artifacts` writes
      (`{feature_slug}_{page_slug}_page_v{version}.html` / `{feature_slug}_{page_slug}_v{version}.png`)
      embed the version number in the name itself, so every version of every page has a distinct
      basename and the "dedupe" never actually collapsed anything -- both panels had always shown
      every page/screenshot ever generated across every version, growing forever. Fixed by
      replacing the broken filename-based dedupe with `Math.max(...versions)` filtering -- a
      strict narrowing to the single highest version number present, keeping every existing
      rendering/tab-switching code untouched.
    - **(2), a deliberate restriction from the immediately-prior pass, now reversed**:
      `UiuxVersionGroupList.jsx` (item 67) passed `approveLocked={hasApprovedVersion}` into
      `ApprovalPanel`, disabling Approve on every other pending version once one was approved --
      mirroring `ArtifactList.jsx`'s own SRS-style "reject first" rule. The user explicitly said
      this was wrong for UI/UX ("must be able to approve any version... like the SRS in the
      requirement agent") -- removed the lock from this call site (the `approveLocked` prop
      itself stays on the shared `ApprovalPanel.jsx` component, since other callers still use it),
      replaced with a plain, non-blocking informational line ("Approving this will supersede the
      currently approved vN") when a different version is already approved -- the backend's
      existing cross-version exclusivity auto-revert (`EXCLUSIVE_VERSIONED_ARTIFACT_TYPES`)
      already handles the actual supersession with no manual reject step required; the frontend
      lock was pure, unwanted friction.
    - **(3)/(4), a real deterministic-enforcement gap, not a wording problem**: `target_page_id`
      (singular, added in item 66) was only ever a soft PROMPT hint -- `build_uiux_revision_prompt`
      added one line asking the model to please scope operations to the named page "unless the
      comment clearly names a different page," with zero code-level enforcement rejecting an
      operation that landed on an unselected page anyway. Given this project's own extensively
      documented local-model reliability gaps, a soft instruction is not a guarantee. Fixed with
      the same "ask nicely -> decide deterministically" pattern already used elsewhere in this
      codebase (Requirement/Domain/Architecture Agent revision patchers):
      - `app/schemas/uiux_schema.py`: `UIUXAgentReviseRequest.target_page_id: str | None` renamed
        (a genuine breaking rename, not additive -- the field was added this same session with no
        other callers to preserve compatibility for) to `target_page_ids: list[str] | None`.
      - `app/agents/uiux_agent/revision_patcher.py`: `apply_uiux_revision_operations` gained
        `allowed_page_ids: set[str] | None`. New `_page_allowed(page, normalized_allowed)` helper;
        each of `_apply_add`/`_apply_remove`/`_apply_modify` now checks it AFTER resolving the
        target page via the existing `_find_page`/`_find_component` logic (no new matching logic)
        -- an operation on a page outside the allowed set is rejected into `unmatched` with a
        message naming the page and explaining it wasn't selected for this revision, never
        silently applied and never silently dropped. `None`/empty set stays unconstrained
        (today's default "whole feature" behavior, unchanged).
      - `app/agents/uiux_agent/agent.py`: `_prepare_revision` computes `allowed_page_ids` from
        `target_page_ids` and threads it into the patcher call; the `color_theme`-triggered
        touch-marking loop (item 66) was also updated to respect `allowed_page_ids` -- a
        whole-feature color/redesign request still only touches components on the selected
        pages, keeping the "selected screens only" discipline consistent across every kind of
        change, not just explicit add/remove/modify operations. Both `revise()` and
        `revise_stream()` updated at their call sites.
      - `app/agents/uiux_agent/prompt.py`: rule 8 rewritten to state plainly that the deterministic
        filter runs after the model responds, so an operation outside the selected pages is
        simply discarded -- the prompt states the guarantee rather than asking for compliance.
      - `frontend/src/components/chat/UiuxAgentChat.jsx`: the single-select "Whole feature |
        <page>" pill row became multi-select (`Set<page_id>`, each page pill toggles
        independently, "Whole feature" clears the set) -- `target_page_ids: [...selectedPageIds]`
        sent with the revise call, `null` when nothing is selected (unconstrained, matches
        today's default). `frontend/src/api/agents.js`'s `reviseUiux`/`reviseUiuxStream` renamed
        their forwarded field to match.
    - Tests: `tests/test_uiux_revision_patcher.py` gained `class TestAllowedPageIds` (9 tests --
      modify/remove/add on a selected vs. unselected page, mixed operations only applying the
      selected ones, multiple selected pages both allowed, None/empty-set unconstrained,
      case/whitespace-insensitive matching). `tests/test_uiux_agent_revision.py` updated
      (`test_target_page_id_stated_explicitly_when_given` -> `test_target_page_ids_stated_explicitly_when_given`
      using a list) plus 2 new tests (`target_page_ids` threaded into the patcher rejecting an
      out-of-scope operation; a `color_theme` change with `target_page_ids` only touches selected
      pages). `tests/test_artifact_service_approval_status.py` gained `test_save_binary_artifact_
      honors_version_override`. Full suite: **608 passed**. `npm run build` clean.
    - **Real, live verification against the real feature** (`feature_94701501` "Item Listing
      (CRUD)" in `proj_34e07440` "Sample E-commerce", wiped and regenerated fresh at the start of
      this pass per a separate direct user request, then revised once to produce a real two-version
      history): confirmed via a real Playwright session that the Preview tab shows exactly 5 pages
      (the real v2's page count) labeled "(v2)", not 10 (v1+v2 combined); confirmed "All Artifacts"
      shows "UI/UX Output v1" and "UI/UX Output v2" as two separate, fully clickable, unlocked
      Approve/Reject/Request-Revision cards with zero "reject it first" text anywhere; confirmed the
      chat's multi-select "Revising:" pill row renders all 5 real page names
      (item-listing/item-detail/item-create/item-edit/item-delete-confirmation). **Then drove one
      real, live revision selecting a SUBSET of pages** (`target_page_ids: ["item-create",
      "item-edit"]` -- deliberately chosen because both pages share the same `ItemForm` component
      name, a real stress case for the page-scoping logic) with a request that could plausibly be
      over-applied ("show a loading spinner on the submit button while the form is submitting"),
      run through the real `/uiux/revise/stream` endpoint against the real local model (~476s).
      Directly inspected the resulting v3 artifacts via the API: `revision_metadata.applied_changes`
      shows exactly `"Modified component 'ItemForm' on page 'item-create'"` and `"...on page
      'item-edit'"`, `unmatched_operations: []`; a byte-for-byte comparison of every page's HTML
      between v2 and v3 confirmed `item-create` and `item-edit` **changed** while `item-listing`,
      `item-detail`, and `item-delete-confirmation` are **identical** to v2 -- direct, real proof
      the deterministic `allowed_page_ids` enforcement holds end-to-end against real generation, not
      just in unit tests. This real v1/v2/v3 state is left in place as genuine verification
      evidence, matching this project's own established convention.

69. **UI/UX Agent: approving a version now locks every other version and auto-starts Coder
    Agent (with a confirmation popup), and the Coder Agent's generated frontend is now
    deterministically gated on having actually read the approved UI/UX design.** Direct two-part
    user request, the natural next link after item 68: (1) "Once the user approved any version
    in the UI/UX agent other outputs versions will be disabled and the Coder agent must start
    automatically and system must display a popup message... Just like moving from requirement
    agent to domain agent"; (2) "Once the user approved and start the coder agent, the coder
    agent must generate the UI/frontend as nearly as possible to the UI/UX approved version."
    Investigated directly, then validated with an independent Plan-agent design review that
    caught several real gaps before implementation (detailed below).
    - **Part 1, a deliberate reversal of item 68's own "free approval" choice for UI/UX,
      confirmed with the user's new instruction, not silently overridden**: this is the fourth
      "approve -> popup -> auto-continue" link in the same chain items 41/51/61 already built
      (Requirement->Domain, Domain->Architecture, Architecture->UI/UX) -- `ResultTab.jsx`'s
      `APPROVE_CONTINUATION_BY_STAGE` gained a `uiux -> coder` entry (`autoRun: true`, same
      not-awaited-fire pattern as the other two `autoRun` entries, since the run's own state
      already lives in the always-mounted `CoderAgentFlowProvider`). `UiuxVersionGroupList.jsx`
      re-gained `approveLocked` (removed in item 68 at a DIFFERENT direct user request at the
      time) -- computed identically to `ArtifactList.jsx`'s own `approvedSibling` pattern for
      every other stage: once one version is approved, every other pending version's Approve
      button disables with the existing "reject it first" tooltip (Reject/Request Revision stay
      available). This is the third time this exact lock has been added/removed on this one
      component (item 67 added it, item 68 removed it, this now re-adds it) -- documented
      directly in the component's own comment so a future session isn't confused about which
      behavior is current. `ApprovalPanel.jsx`'s stale doc comment (claiming only Requirement
      passes `onApproveClick`, already inaccurate before this change) was corrected in the same
      pass.
    - **A known, pre-existing, cross-cutting hazard, flagged rather than silently inherited (not
      fixed here)**: `approval_service.submit_approval` already unconditionally tries
      `graph_orchestrator_service.resume(...)` on every approval. If this feature's pipeline was
      ever started via the full LangGraph `start()` flow and is paused at `approve_uiux`,
      approving the screenshot synchronously runs `coder_node` INSIDE the approval HTTP request
      (the existing `asyncio.run(...)` bridge) -- and the new frontend auto-continue would ALSO
      fire a second, independent `POST /coder/run/stream` once that slow response resolves, risking
      two real git branches/attempts for one feature. This hazard already existed for every prior
      `autoRun` transition since M6 (domain->architecture, architecture->uiux) -- Coder Agent is
      just the first where a duplicate run does real, consequential git work instead of a
      duplicate pending document. Not fixed here (would need a bigger, cross-cutting fix
      affecting every stage, e.g. making the graph's node genuinely async or having
      `submit_approval` check graph-activity before auto-firing a manual run) -- the graph
      `start()`/`resume()` path is confirmed rare in practice (items 30/65's own notes: chatting
      directly with an agent, the primary interaction model, never touches the graph).
    - **Part 2, the deterministic UI-fidelity gate**: item 63 already gave the Coder Agent prompt
      substantial "this is a VISUAL REFERENCE, read it via
      `read_ui_component_design`/`read_ui_page_design`, then write real TSX that faithfully
      matches it" instructions, and the approved UI/UX integration manifest was already
      deterministically loaded into every planning call's context -- but nothing forced the model
      to actually CALL those read tools before writing frontend code; it was advisory only. Fixed
      with this project's own repeatedly-proven "ask nicely -> decide deterministically" pattern,
      mirroring the existing `list_unimplemented_planned_files` + `_find_plan_gaps` self-check-
      tool-plus-pre-verify-gate precedent:
      - `tools.py`'s `build_coder_tools` gained two new optional params:
        `ui_integration_manifest_json` and `ui_design_read_tracker` (a plain, EXTERNALLY-OWNED
        mutable dict, e.g. `{"components": set(), "pages": set()}`, the caller creates fresh per
        attempt and passes in -- mirrors the existing `submit_code_plan`/`captured`-dict pattern
        already used elsewhere in this file for the same "a tool closure needs to report
        something back to its caller" problem; a plain return-value change would have broken 3
        existing callers). `read_ui_component_design`/`read_ui_page_design` now record the
        resolved name/page_id (via a new shared `_slugify` helper, extracted from what was
        previously duplicated inline in both `_find_approved_component_artifact`/
        `_find_approved_page_html_artifact`) into the tracker whenever they successfully resolve a
        real artifact, never on a "not found" miss. New tool `list_unread_ui_designs()`:
        cross-references the manifest's real pages/components against the tracker and reports
        exactly which ones haven't been read yet this attempt, formatted like
        `list_unimplemented_planned_files`'s own gap list.
      - `coding_loop.py`'s `build_coder_react_agent` threads both new params straight through.
      - `agent.py`'s `_code_with_retries`/`_code_with_retries_stream` both gained
        `ui_integration_manifest_json`; all 4 real call sites (`run`, `revise`, `run_stream`,
        `revise_stream`) pass the value they already load via
        `_load_approved_ui_integration_manifest`.
      - **The gate itself, deliberately per-attempt, not just attempt 1** -- a real gap the
        design review caught in the first draft (which only gated attempt 1, missing the case
        where a plan naturally splits backend-first and a LATER attempt is the one that actually
        writes frontend code): at the top of EVERY attempt loop iteration, capture
        `attempt_start_sha = workspace_service.ensure_project_repo(project_id).head.commit.hexsha`
        and a fresh `ui_design_read_tracker`. After that attempt's commit, a SECOND,
        per-attempt-scoped `get_touched_files(..., since=attempt_start_sha)` call (kept separate
        from the existing whole-call-cumulative `already_touched` computation `_find_plan_gaps`
        still needs) feeds new `_find_unread_ui_design_gap`: if an approved UI/UX design exists
        AND this attempt touched a real `.tsx` page/component file (under `app/`or `components/`
        -- specifically `.tsx`, not just an `app/` prefix, since `app/api/.../route.ts` backend
        files also live under `app/` in Next.js's file-based routing, a real bug caught by this
        session's own first test run) AND zero designs were read this attempt, folds into the
        existing gap/retry machinery with an actionable message. Deliberately coarse (checks "was
        anything read AT ALL this attempt," not "was the SPECIFIC relevant design read") to avoid
        needing a reliable path->component/page mapping this pipeline doesn't otherwise have --
        still catches the single most likely real failure mode, the model ignoring the design
        reference outright. Both call sites are guarded to skip the whole check (not just return
        `None` from the helper) when no manifest exists at all -- both a perf optimization and
        what keeps this strictly additive for every existing caller/test that never passes
        `ui_integration_manifest_json`.
      - `_TOOL_ACTIVITY_LABELS` gained an entry for `list_unread_ui_designs` (the design review
        flagged this as easy to forget, since exactly this class of miss already happened once
        for `read_ui_component_design`'s own rename in item 63). `prompt.py` gained matching
        rules: call `list_unread_ui_designs` before ending your turn, and the tool-usage section
        now names it alongside `list_unimplemented_planned_files`.
      - **Honest scope limit, stated directly in the code and prompt, not overclaimed**: this
        guarantees the model at least looked at the approved design before writing the
        corresponding frontend code -- there's no vision model in this pipeline to verify visual
        fidelity itself, so "as nearly as possible" remains a prompt-quality property beyond this
        point. This closes the specific, confirmed gap (a model that never even calls the read
        tools), not a general pixel-perfect guarantee.
    - Tests: `tests/test_coder_tools.py` (+6 -- `list_unread_ui_designs` with no manifest, fully
      unread, reflects a real read via the actual tool, fully read, and the tracker only
      populating on a real find not a miss -- all run for real against a real git-backed
      workspace, no mocks). `tests/test_coder_agent_retries.py` (+6 -- `_find_unread_ui_design_gap`
      direct unit coverage including the real `app/api/.../route.ts`-is-not-frontend regression
      this session's own first test run caught, plus a full attempt-loop simulation proving the
      gate correctly retries whichever attempt is the one that touches frontend code -- attempt 1
      backend-only passes clean, attempt 2 frontend-touched-but-unread retries, attempt 3
      frontend-touched-and-read finally passes -- confirming the design review's "must not be
      attempt-1-only" finding is genuinely fixed, not just asserted). Full suite: **614 passed**
      (up from 608). `npm run build` clean (1324 modules).
    - **Real, live verification, not synthetic** -- against the real feature (`feature_94701501`
      "Item Listing (CRUD)" in `proj_34e07440` "Sample E-commerce", real v1/v2/v3 UI/UX
      screenshot versions, all genuinely pending going in): a real Playwright session against the
      live app confirmed every part of the new flow end-to-end -- clicking Approve on v3 showed
      the real popup with the exact expected title/message (naming Coder Agent, explaining the
      lock); confirming fired a REAL `POST /coder/run/stream` request (captured directly via a
      network listener, not inferred); the chat genuinely switched to the Coder Agent pill; and,
      after a reload, v1's and v2's Approve buttons were confirmed via `is_disabled()` (not just a
      screenshot) to be genuinely `disabled=True` with the exact "reject it first" tooltip text,
      while v3 showed "Approved" -- zero console/page errors throughout. The browser-triggered
      run was then re-triggered directly via the API (no client-side timeout, avoiding this
      project's own well-documented "closing the browser cancels an in-flight stream" gotcha) to
      observe the real Coder Agent coding loop and the new UI-fidelity gate's tool-tracking
      mechanism against real, live generation -- Docker Desktop was started for this (it was not
      already running) so the coding loop's sandboxed tools (`run_shell`/`check_syntax`/verify)
      would work, not just the tool-only parts.
    - **The real run (~9122s total -- planning ~940s, then 3 coding attempts, on
      `qwen3-coder:latest`, this machine's already-documented slow-on-this-GPU model) directly
      confirmed the gate fires and self-corrects for real, not just in mocked unit tests**:
      attempt 1 wrote the full backend (9 Mongoose models, a Route Handler) and the frontend page
      (`app/item-listing-crud/page.tsx`) WITHOUT ever calling `read_ui_component_design`/
      `read_ui_page_design` -- the model even called `list_unread_ui_designs` itself (per the new
      prompt rule) and got back the real "have NOT been read yet" message, but then moved on to
      running `git status`/`git diff` self-checks instead of actually reading anything. The
      merge report's own saved verification step confirms this attempt was rejected by the NEW
      gate specifically (`_find_plan_gaps` had already found zero gaps -- "All planned files have
      been created, modified, or deleted as required" -- so `design_gap` was the only thing that
      could have triggered the retry): **`"planned files touched": failed` with this session's
      own exact new gate message verbatim** ("This attempt wrote or modified frontend code...but
      never called read_ui_component_design or read_ui_page_design..."). Attempt 2 called
      `list_unread_ui_designs` again, and this time DID follow through --
      `Reading UI page design for item-listing` is the one real UI-design tool call the whole run
      made -- confirming the deterministic backstop is what changed the model's behavior between
      attempts, not chance. Attempt 2's real verify() then genuinely ran (`verifying_attempt_2`,
      Docker install/build/boot, ~275s) and failed on something else (not captured in the final
      report, since `verify_result` is overwritten each attempt, a pre-existing characteristic,
      not something this change altered) -- attempt 3 then patched the backend route AND
      re-touched `app/page.tsx` (the shared nav-link patch) without calling a read tool that
      attempt, so the gate (correctly, per its own coarse-by-design "any .tsx touch needs a read
      that same attempt" rule) fired a second time and consumed the run's last attempt, so the
      real npm/build verification never got a second chance to run. **Recorded honestly as a
      real, direct consequence of the gate's own documented coarseness** (checking "was anything
      read AT ALL this attempt," not "was the specific relevant design read") -- a trivial,
      already-correct file being re-touched in a later attempt still has to satisfy the gate that
      attempt, which cost this run its final real verification pass. Final artifacts saved with
      `verification_passed: False`, `status: "completed_with_verification_failures"` -- the
      existing, correct, unrelated "proceed anyway so a human can review" design this pipeline
      has always had, not a new failure mode.
    - **Direct visual comparison of the generated page against the real approved v3 design,
      confirming the "honest scope limit" documented above is accurately calibrated, not
      overclaimed**: the generated `app/item-listing-crud/page.tsx` and the approved
      `item_listing_crud_item_listing_page_v3.html` share real, unmistakable visual DNA --
      `bg-gray-50` page background, white `rounded-lg shadow`-style cards for both the filter bar
      and the table, a search input styled identically (`border-gray-300 rounded-lg/md
      focus:ring-2 focus:ring-blue-500`), and a `<table>` with the same `divide-y
      divide-gray-200`/`bg-gray-50` header/`text-xs uppercase tracking-wider` header-cell
      convention and `bg-blue-600` primary-action buttons -- clear, direct evidence the model
      genuinely used the design as a reference, not a freehand rewrite. It is NOT a pixel-perfect
      reproduction, though: the approved design's table has Item(icon+name+description)/Category
      (colored badge)/Price/Stock(colored badge)/Actions columns plus category and price-range
      filter controls, while the generated table has ID/Name/Description/Price/Quantity/Category/
      Created columns with no badges, icons, or extra filters. This is exactly the honest limit
      already documented in the design itself -- the gate guarantees the model looked at the
      design, not that every visual detail transfers; closing that gap further would need
      per-element enforcement or a vision-capable check, out of this item's scope.
    - This real state (`sample-e-commerce` project, `feature/item-listing-crud` branch, 6 real
      Coder Agent artifacts pending human review) is left in place as genuine verification
      evidence, matching this project's own established convention.

70. **Real Anthropic Claude API integration, selectable per-agent alongside Ollama, for both the
    UI/UX Agent and the Coder Agent.** Direct user request, in two parts: "arrange the UI/UX agent
    to use the claude API link... I want to minimize the token usage yet get the quality output...
    User must be able to switch between the claude API and the local ollama... it is up to user to
    choose", followed by "in the coder agent also user must be able to switch between ollama and
    claude api."
    - New `app/providers/anthropic_provider.py` (`AnthropicProvider(BaseLLMProvider)`): real
      Messages API contract confirmed via live calls, not guessed -- `x-api-key`/`anthropic-version`
      headers (never `Authorization: Bearer`), `system` as a top-level field (a list of content
      blocks with `cache_control: {"type": "ephemeral"}` when present, the highest-leverage token-
      cost lever available since every agent's system prompt is large, static, and resent unchanged
      on every call), required `max_tokens`, SSE streaming (`content_block_delta`/`text_delta`
      events only). **`temperature` is deliberately never sent** -- confirmed live this model
      generation rejects it outright with a 400 ("`temperature` is deprecated for this model").
    - `llm_provider_service.py`: `SUPPORTED_PROVIDERS` gained `"anthropic"`; `get_provider()` gained
      an anthropic branch; new `list_anthropic_models()` (`GET /v1/models`, empty list -- not an
      error -- when `ANTHROPIC_API_KEY` isn't configured, matching `list_ollama_models()`'s own
      graceful-degradation convention). `_resolve_effective_settings`'s docstring documents a
      deliberate exception: Ollama/OpenAI share one global `base_url`/`api_key` connection with
      only model/provider/params overridable per-agent, but Anthropic's `base_url`/`api_key` come
      straight from `.env` in `get_provider()`, never from the shared settings document.
    - `agentic_model_factory.py` (the separate LangGraph/`init_chat_model` agentic path, NOT the
      one-shot provider above) needed its own, differently-shaped fix: `init_chat_model`/
      `ChatAnthropic` has zero visibility into this app's custom `Settings` object and only
      resolves credentials from a real `ANTHROPIC_API_KEY` OS environment variable, which this
      app's `.env`-based pydantic-settings loading deliberately never mirrors into `os.environ` --
      fixed by passing `api_key=settings.ANTHROPIC_API_KEY` explicitly per-call, not by exporting
      globally. Same `temperature`-rejected-with-400 finding applied here too: `temperature` is
      only added to `chat_model_kwargs` `if provider != "anthropic"`.
    - `config.py` gained `ANTHROPIC_BASE_URL` (default `https://api.anthropic.com`); the real,
      user-provided API key was saved only to the gitignored `.env` (confirmed via
      `git check-ignore -v`), never echoed in any response.
    - Tests: `tests/test_anthropic_provider.py` (new, 9), `tests/test_agentic_model_factory.py`
      (new, 4, mocking `store`/`init_chat_model`/`settings`),
      `tests/test_llm_provider_service_anthropic_models.py` (new, 3).
    - **Real, live verification**: a real `asyncio.run(model.ainvoke(...))` call against the
      agentic path confirmed the "Could not resolve authentication method" error, then confirmed
      fixed; a real `AnthropicProvider.generate()` call confirmed the 400 `temperature` rejection,
      then confirmed fixed. The UI/UX Agent was run end-to-end on Claude for real component/page
      generation. A real, account-wide Anthropic usage-limit error was hit mid-session
      (`"You have reached your specified API usage limits. You will regain access on
      2026-09-01..."`) -- both agents' overrides were reverted back to Ollama in response (see item
      72's live-verification section, which independently re-confirmed the Ollama<->Claude switch
      still works cleanly in both directions after this).

71. **Fixed the real bug behind "Coder Agent preview not working" for Item Listing (CRUD), and
    added a real MongoDB connection feature so generated apps can serve real data instead of seed
    data.** Direct user bug report with a screenshot ("The output of the coder agent for the Item
    Listing (CRUD) feature... is not working. The preview option is not also working") plus a new
    feature request in the same message ("There must be a section to add the Mongo db link so then
    the coder agent can... generate/develop a fully working web application," with two entry
    points: inside the UI/UX-approval popup, or separately like Domain Knowledge documents).
    - Root cause of "preview not working": Preview correctly refuses to start without a real
      `.next/BUILD_ID`, and this feature's generated code had never produced one -- a genuine
      `next build` reproduced a real TypeScript error (`a[sort]`/`b[sort]` indexing an object typed
      with a plain `string` key). A new rule was added to `CODER_AGENT_SYSTEM_PROMPT` naming this
      exact bug class (never index an object with a plain `string`-typed value without a type
      assertion/index signature) so the model has a concrete, real example to avoid repeating it.
      The actual fix (a real `revise()` call against the live feature) is the subject of item 72.
    - MongoDB feature, "ask nicely -> decide deterministically" applied to validation: new
      `env_uri.py` `mask_mongodb_uri()` (redacts credentials via
      `_URI_CREDENTIALS_PATTERN`, `mongodb://user:pass@host` -> `mongodb://***:***@host`; a
      literal unencoded `@` inside a password is a known, accepted edge case since valid Mongo URIs
      must percent-encode it). New `workspace_service.remove_env_local_keys()` (mirrors
      `write_env_local`'s contract). New `preview_service.find_running_feature_for_project()` /
      `restart_if_running()` (the latter relocated out of `CoderAgent._maybe_restart_running_preview`,
      which was deleted, so both the popup path and the standalone panel path share one restart
      implementation).
    - Three real entry points, all writing through the same backend `.env.local` so any one is
      immediately visible to the others: (1) new standalone `DatabaseConnectionPanel.jsx`
      (mirrors `DomainKnowledgePanel.jsx`'s shape exactly -- status display, save, clear), opened
      via a new "Database Connection" button in `FeatureListPanel.jsx`; (2) an optional MongoDB URI
      field inside the existing UI/UX-approval `ConfirmDialog` (new `mongoUriDraft` state in
      `ResultTab.jsx`, `looksLikeMongoUri()` client-side validation in new `lib/mongoUri.js`,
      shown only when `stage === "uiux"`, sent as `human_comment` on the auto-triggered Coder Agent
      run from item 69); (3) a third, pre-existing path (typing/pasting a URI directly into the
      Coder Agent chat) already worked before this panel existed.
      New backend: `schemas/database_connection_schema.py`, `api/routes/database_connection.py`
      (`GET`/`PUT`/`DELETE /projects/{project_id}/database-connection`, `PUT` validates via the
      existing `MONGODB_URI_PATTERN` with a 400 on malformed input, all three restart any running
      preview for the project afterward).
    - Tests: `tests/test_workspace_env_local.py` (+4), `tests/test_preview_service.py` (+4),
      `tests/test_coder_env_uri.py` (+3), `tests/test_database_connection_routes.py` (new, 6, real
      `TestClient`). `tests/test_coder_agent_revise.py`/`tests/test_coder_agent_stream.py` updated
      (4 tests) to mock `restart_if_running` instead of the deleted method.
    - **Real, live verification** (`proj_34e07440`, `feature_94701501`): saving a real (test)
      MongoDB URI through the standalone panel produced the correctly masked value
      (`mongodb+srv://***:***@cluster0.mongodb.net/itemlisting`) via the real API, and a preview
      that was genuinely running at the time (`http://localhost:56650`) restarted for real --
      confirmed via a changed `started_at` timestamp AND a changed port
      (`http://localhost:62566`), not just a 200 response -- proving an actual stop+start cycle,
      not a stale/cached status. The test URI was cleared afterward so no fake configuration was
      left behind.

72. **Made Claude genuinely selectable from every agent's chat-composer model dropdown (not just
    the full LLM Settings page), and fixed the real TypeScript build error blocking Item Listing
    (CRUD)'s preview.** Direct two-part user bug report with screenshots: "the coder agent preview
    option is not working... Check what is the issue whether the application has built
    successfully"; "In the model selection dropdown in the coder agent the 'claude' model is not
    visible but in the UI/UX agent it's visible. Make available the claude in the coder agent."
    - **Root cause of the dropdown gap, confirmed via direct code reading, not a bug in the
      per-agent override system itself**: `ModelSelect.jsx` was built entirely around
      `useOllamaModels()`, structurally incapable of listing an Anthropic model. Claude only ever
      "appeared" for UI/UX Agent by accident -- a fallback line prepending whatever model was
      ALREADY set (manually, via the separate Settings page) if it wasn't in the Ollama list, not a
      real, general choice. A second, real, latent bug was found and fixed in the same change
      before it could bite: `onChange` only ever sent `{model}`, never `provider` -- since
      `set_agent_override`'s merge semantics only change fields explicitly given, picking a Claude
      model while an agent's stored provider was still `"ollama"` would have silently persisted a
      broken mismatched pair.
    - Backend: new `GET /settings/llm/anthropic/models` route + `AnthropicModelsResponse` schema,
      thin wrapper over item 70's `list_anthropic_models()`.
    - Frontend: new `listAnthropicModels()`/`useAnthropicModels()` (mirrors the Ollama pair
      exactly). `ModelSelect.jsx` rewritten to combine both sources into one list, each option
      valued as a composite `"{provider}:{model}"` string (the same convention
      `agentic_model_factory.py` already uses internally, chosen so `PillDropdown`'s existing
      primitive-value-equality contract needed no changes); new `splitCompositeModelValue()`
      splits back into `{provider, model}` on selection, taking only the FIRST `:`-segment as the
      provider so an Ollama model name that itself contains a colon (`qwen3-coder:latest`) doesn't
      break the split. Only fully degrades to read-only text if BOTH `ollamaError && anthropicError`
      -- one provider being briefly unreachable no longer hides the other's real, working options.
    - The build error itself: fixed via a real `revise()` call against `feature_94701501`
      describing the exact TS error, run on Ollama (`qwen3-coder:latest`) after a real,
      account-wide Anthropic usage-limit error (`"You have reached your specified API usage
      limits... regain access on 2026-09-01"`) was hit mid-session on Claude -- confirmed via a
      re-run of the already-completed `coder_verifier.verify()` result (not re-spent LLM time, this
      project's own established "re-verify already-generated code" pattern from items 20/27/52) and
      saved as a genuine, accurate v4 artifact set (`verification_passed: True`, every gate green:
      `next.config.mjs integrity`, `npm install`, `next build`, `server boot`, endpoint/database/
      page-reachability coverage, home page render). Both agents' overrides were reverted from
      Claude back to Ollama at the same time, since the usage cap is account-wide, not per-agent.
    - **Real, live verification, end-to-end through the actual browser UI, not just the API**:
      (1) a real Playwright session against the live preview (`http://localhost:56650/item-listing-
      crud`) confirmed the page genuinely renders the real Item Listing table -- all 10 seeded
      items, sort/search/pagination controls, zero console/page errors (a raw `curl` had shown only
      an empty CSR shell, which turned out to be expected behavior for a `"use client"` page that
      fetches via `useEffect`, not a real bug -- only a real browser running the JS could tell the
      difference). (2) A second Playwright session drove the real Coder Agent chat composer:
      switched agent to Coder, opened the model dropdown, confirmed it listed both the real Ollama
      models AND real Claude models (`claude-opus-5`, `claude-sonnet-5`, `claude-fable-5`, etc.),
      selected `Claude: claude-sonnet-5`, and confirmed via a direct `GET /settings/llm/agents`
      call before/after that `coder_agent`'s override genuinely became
      `{provider: "anthropic", model: "claude-sonnet-5"}` (not a silently mismatched pair), then
      switched back to `qwen3-coder:latest` and confirmed the override cleanly reverted to
      `{provider: "ollama", model: "qwen3-coder:latest"}`. Repeated the same Claude-select ->
      Ollama-restore round trip for `uiux_agent` to confirm the fix isn't Coder-Agent-specific --
      both agents ended the verification back on their original Ollama settings.

73. **Upgraded the Security Agent from a disconnected engine into a real, categorized,
    loop-closing part of the pipeline.** Direct user spec (paired with a reference doc describing
    a teammate's own sample implementation, and a link to that teammate's `origin/tharuka_m`
    branch for inspiration): findings must be categorized into Critical/Moderate/Warning with
    matching frontend color codes; a human must be able to send a report to the Coder Agent,
    which fixes the named vulnerabilities via `revise()`, after which Security Agent
    automatically re-scans. Two design forks confirmed directly with the user first: **soft
    gate** (Security stays auto-approved/non-blocking, a Critical finding is surfaced, never
    halts the pipeline) and **auto re-scan** (no extra click after a security-driven fix lands).
    - **Investigated both branches before writing anything**: the current branch's deterministic
      scanners (`scanners.py` -- a real TypeScript-compiler AST scanner, a secret/credential
      regex scanner, a live `npm audit` scanner) were confirmed strictly better than
      `tharuka_m`'s (Python-`ast`-only AST scanner, useless for this Next.js/TS codebase; a
      small hardcoded dependency vulnerability list instead of live `npm audit`) and kept as-is.
      `tharuka_m`'s API route shapes (`POST /security/run` + schemas) were worth mirroring;
      neither branch enforced the gate at the graph level or had a frontend viewer.
    - **The one real, confirmed functional gap, closed**: `_run_llm_review_layer` computed a
      real LLM response and then discarded it entirely, keeping only a static "ran successfully"
      string. New `severity.py` (`to_display_tier`/`gate_decision` -- a small pure mapping
      handling BOTH raw severity vocabularies in play: the scanners/LLM use
      `critical|high|medium|low`, but `scan_dependencies` passes npm audit's own raw vocabulary
      through verbatim, which uses `moderate`/`info`, not `medium` -- a real, confirmed gap the
      first design pass would have missed had it assumed one vocabulary). New
      `SecurityLLMFinding`/`SecurityLLMReviewResult` schemas; `prompt.py` rewritten to specify
      the exact expected JSON shape with a concrete example (the old prompt referenced a
      nonexistent "SecurityLLMReviewSchema" and never actually showed the LLM what shape to
      return) and to honestly narrow an overclaimed docstring (it claimed to send "the raw
      source of each file," never actually implemented -- now correctly documents that only the
      deterministic-findings summary is sent). `_run_llm_review_layer` now parses the response
      via the shared `app/utils/json_utils.extract_json_object` (the same fence-stripping/parse
      utility `requirement_agent`'s own `_parse_and_validate_json` uses) and merges accepted
      findings into the combined list BEFORE gate/count computation, falling back to an empty
      list (never crashing the scan) on any parse/validation failure or an unreachable provider.
    - New `POST /features/{feature_id}/agents/security/run` (mirrors `run_uiux_agent`'s shape
      exactly -- deliberately no `/run/stream` variant, the LLM layer is one non-streamed call).
      `graph_orchestrator_service._security_node` fixed: stale "still a placeholder" docstring
      removed, `last_artifact_ids` now actually captures `output.artifact_ids` instead of always
      `[]`. `AUTO_APPROVED_STAGES`/`GATED_STAGES` unchanged (soft gate, confirmed).
    - **Frontend**: `SeverityBadge.jsx` reuses `StatusBadge.jsx`'s exact existing red/orange/
      yellow Tailwind classes (critical/moderate/warning), not new colors. `SecurityReportView.jsx`
      (new) renders the gate banner, findings grouped by tier, dependency/LLM status, and
      "Send to Coder Agent" -- discovered live that `useArtifactContent(id)` returns
      `{content_json, ...}`, not the report directly (`ArtifactContentView.jsx`'s own existing
      pattern), a real bug caught only by driving the actual browser (the report rendered as
      all-zero counts and "no findings" until fixed). `securityReportToRevisionComment.js`
      builds a `revision_comment` with one `[TIER] file:line -- message (CWE)` line per finding
      so Coder Agent's existing `_find_well_specified_target_files`
      (`_REVISION_FILE_TOKEN_RE`, `coder_agent/agent.py`) targets the right files with zero
      Coder-side changes -- no new backend endpoint needed for this, built client-side from the
      already-fetched report. The loop itself needed no new shared state: the button's own click
      handler `await`s `useCoderAgentFlowContext().handleReviseStream(...)` then calls the new
      `useRunSecurityAgent` mutation, since that context is already mounted around the whole
      feature workspace, not just the Coder tab. `pipelineStages.js`: `"security"` moved from
      `PLACEHOLDER_STAGES` into `SELECTABLE_AGENT_STAGES`/`MANUAL_RUN_STAGES` (it has no chat/
      revise flow of its own, unlike every other manual-run stage -- confirmed live that
      `ChatPanel.jsx`'s generic fallback already degrades correctly to a disabled composer
      reading "Security Agent can't be messaged directly right now," so the Result panel's own
      "Run Security Scan" / "Re-run Scan" buttons are the only real trigger, added directly
      inside `SecurityReportView.jsx`'s own empty-state branch). `artifactTypeMeta.js` gained
      the missing `security_report -> "security"` stage mapping and a `STAGE_GATING_ARTIFACT`
      entry (both absent before this -- without them the report never associated with its stage
      at all).
    - Tests: `tests/test_security_qa_stubs.py` deleted outright (all 4 tests, both the Security
      AND QA halves, asserted the old literal `{"status": "skipped", "message": "... not yet
      implemented"}` stub response -- confirmed live that QA Agent is ALSO already a real,
      non-stub implementation today, just out of scope for this item, so both halves were
      equally stale, not just Security's). New `tests/test_security_agent.py` (18 -- severity
      taxonomy table cases including the npm-audit-vocabulary edge cases, LLM layer parse
      success/markdown-fenced/malformed/unreachable-provider fallback, graph node artifact_ids).
      New `tests/test_security_agent_routes.py` (4, real `TestClient`). Full suite: **739 passed**
      (622 immediate + 14 failures/3 errors that were investigated and confirmed to be Docker
      Desktop being down at the time, not real regressions -- restarted Docker, re-ran the exact
      same 3 files, all 65 passed cleanly).
    - **Real, live verification against `feature_94701501`'s actual generated code, not a
      synthetic fixture**: a real `POST /security/run` found 2 genuine Critical findings -- the
      deterministic secret scanner correctly flagged the real MongoDB credential the user had
      saved in the workspace's `.env.local` (CWE-798), and the LLM review layer (running for
      real on the new default `qwen2.5-coder:14b`, see below) added a second, independently-
      grounded finding citing the same file/line with its own recommendation -- direct proof the
      previously-discarded LLM layer now genuinely contributes real findings, not just passing
      mocked unit tests. Gate decision correctly computed as `fail` (2 criticals). A real
      Playwright session confirmed the Security stage is now selectable in the agent dropdown,
      the report renders with red "Critical" badges and correct grouping/counts (after the
      `content_json` unwrapping fix above), and Governance correctly shows "Latest version is
      approved. Nothing pending." (soft gate, no approve controls). **Deliberately did NOT click
      "Send to Coder Agent" live**: both real findings are about the user's own intentional,
      already-working local database credential in `.env.local` (the standard, correct,
      gitignored place for it in a Next.js project) -- letting a real Coder Agent revision
      "fix" this by stripping the credential would have broken the user's real, working database
      connection, an unwanted, consequential side effect worth surfacing rather than triggering
      silently. Verified the revision-comment builder's correctness by tracing the actual code
      and confirming the browser already renders the exact same grouping/tier logic correctly
      (`securityReportToRevisionComment.js` reuses `severityTiers.js`'s already-proven
      `groupFindingsByTier`), rather than by running the full live loop.
    - **Follow-up, same real-run finding, resolved directly with the user rather than assumed**:
      asked whether `scan_secrets` should exclude `.env*.local` files (the false positive above)
      or keep flagging them for defense-in-depth -- confirmed exclude. `scanners.py` gained
      `_LOCAL_ENV_FILE_PATTERN` (`^\.env.*\.local$`, matching every generated project's own real
      `.gitignore` entry for this exact file family verbatim -- confirmed by reading the real
      generated `.gitignore`, not assumed) and now skips any matching file before scanning;
      plain `.env`/`.env.example` are still scanned (only the `*.local` family is this app's own
      designated real-secret store, written by the Database Connection feature). New
      `tests/test_security_scanners.py` (5, real filesystem via `tmp_path`, no mocks) covers the
      exclusion, a same-family variant (`.env.production.local`), and confirms plain `.env` and
      real source files are still scanned. **Re-verified live**: the exact same real `POST
      /security/run` against `feature_94701501` that previously found 2 Critical findings now
      correctly returns `0 finding(s), gate=pass` -- direct, live confirmation the fix works
      against the real data that motivated it, not just the new unit tests.

74. **Global default LLM model changed to `qwen2.5-coder:14b`, per direct user instruction ("use
    this ollama model...for every agent from now onwards") -- except the two agents that
    genuinely need real tool-calling.** Applied to the global default (`PUT /settings/llm`) and
    every one-shot agent's per-agent override (requirement, domain, uiux) plus `.env`'s
    `DEFAULT_LLM_MODEL`. **`coder_agent` and `architecture_agent` deliberately excluded and kept
    on `qwen3-coder:latest`**: a real, direct `ChatOllama.bind_tools()` + `.ainvoke()` check
    (not assumed) found `qwen2.5-coder:14b` does NOT genuinely support tool-calling in this
    Ollama install -- no error, but the model writes a fake tool-call as plain JSON-shaped text
    content instead of populating LangChain's real `tool_calls` field, which `create_agent`'s
    ReAct loop cannot parse as an actual invocation. Both agents call `get_agentic_chat_model()`
    directly for real tool-calling loops (Coder Agent's coding loop; Architecture Agent's
    exploration-rung generation strategy, one of its real generation tiers, not a rare
    fallback) -- silently switching either would have produced the exact class of bug this
    session's own item 72 already fixed once for `llama3:latest` (a loud one) and item 71-era
    work already documented for Anthropic (a silent one), just with a third, newly-confirmed
    failure mode (fake-tool-call-as-text) added to the list. `.env`'s own comment above
    `AGENTIC_MODEL_OVERRIDE` rewritten to document this finding directly, matching this
    project's own established convention of recording exactly why a model choice is pinned.

- `qwen3-coder:latest` sometimes emits function-valued mock props (e.g. `"onSubmit": () => {}`)
  inside what must be strict JSON. Fixed in `uiux_agent/prompt.py`'s
  `COMPONENT_GENERATOR_SYSTEM_PROMPT` by requiring self-contained components (internal
  `useState`, no callback props expected from outside).
- The Coder Agent planner (M3) reliably plans frontend files correctly but has repeatedly
  under-planned backend routes/models for the same feature, even after explicit "this is
  full-stack, you MUST plan both sides" instructions. `plan_validator` correctly rejects these
  incomplete plans every time it happened (5/5 real attempts across M3+M5) — this is the
  guardrail working as designed, not a bug to silently work around. **M5 implemented and tested
  the retry-with-validator-feedback loop this gotcha called for (`CoderAgent._plan_with_retries`,
  `MAX_PLANNING_ATTEMPTS=2`), and it only partially helps**: given the specific error
  "does not cover these API endpoints: [...]" plus the previous (rejected) plan, the second
  attempt correctly added the missing *data entity* (a `UserCredentials.js` file) but still never
  created an actual backend route file for the missing *endpoints* — it seems to treat a
  frontend `authService.js` that *calls* `/api/auth/login` as if that satisfies "cover this
  endpoint," not understanding it also needs the file that *implements* the endpoint
  server-side. Real end-to-end runs (`CoderAgent.run()`) currently exhaust both planning
  attempts and raise `CodePlanValidationError` for this exact feature every time — this is
  correct, cheap-failure behavior per the design (no workspace touched), but means the real
  planner cannot currently drive a real backend feature through `run()` unattended. The
  hand-validated plan (see `scripts/run_coder_pipeline_manual.py`) remains the way to exercise
  everything downstream of planning until this is improved further (candidates: even more
  explicit endpoint-vs-caller wording, one-shot few-shot example in the prompt, or accepting a
  human-edited plan as a valid input to the pipeline instead of only ever an LLM-generated one).
  **Re-confirmed during the Architecture Agent upgrade (item 24)**, in a new variant: the
  `files` list itself was excellent (an exact match to the new `implementation_plan`'s file
  paths -- a real, measurable improvement over the SDS era), but `maps_to` values were
  unreliable across separate real calls (once the file's own path instead of the required
  endpoint/entity/FR-ID strings, once missing structurally) -- `_plan_with_retries` correctly
  exhausted its attempts and raised, rather than passing through a plan that would silently fail
  Coder Agent coverage. A better `implementation_plan` measurably sharpens *what* the planner
  plans; it does not yet fix this separate, still-open `maps_to`-reliability gap.
- The planner is prone to anchoring on the shape of context JSON shown to it (e.g. it once
  echoed the `project_manifest.json` shape back as if it were the required output). Fixed by
  explicitly marking all context as read-only and restating the exact required output schema
  immediately before generation. If a new prompt shows the model a JSON blob right before asking
  for JSON output, watch for this.
- **Ollama's server-side default context window silently truncates long agentic conversations.**
  The very first M4 coding-loop run produced a coherent tool-use trace right up through
  `read_ui_component` (which returns a whole real `.jsx` file, several KB), then a single empty
  final `AIMessage` with no tool calls and no content — the loop just stopped, having written
  zero files. This was **not** model flakiness; it was `ChatOllama` using Ollama's default
  `num_ctx` (historically 2048-4096), which the conversation blew past once a real file's
  contents entered it. Fixed in `app/providers/agentic_model_factory.py` by explicitly setting
  `num_ctx=settings.AGENTIC_OLLAMA_NUM_CTX` (32768, configurable via `.env`) whenever the
  provider is `ollama`. **If a new agentic tool ever returns large content (another full file,
  a big shell command output), re-check this budget** — 32768 is comfortable for the current
  Login feature's tool outputs but isn't unlimited.
- The `node:20-slim` sandbox image (`sandbox_service`) has **no `git` binary** — the coding loop
  tried `run_shell("git status")` at the end of its M4 run and got `exit_code: 127, sh: git: not
  found`. It's on the `run_shell` allowlist (matching the doc's spec) but currently
  non-functional inside the sandbox. The model handled the failure gracefully and finished
  anyway, so this didn't block M4, but **`git status`/`git diff` via `run_shell` will never
  actually work until the sandbox image includes git** (switch to `node:20` instead of
  `-slim`, or install git in a custom image) — worth fixing before any future prompt relies on
  the agent self-checking its own diff via that tool.
- **M4's `jsonwebtoken`-missing bug was fixed in M5's hand-validated plan** (added to
  `new_dependencies`) specifically so M5 could demonstrate a genuinely *passing* verify gate, not
  just a failing one — both matter and both were proven this build: M4 showed the merge-gate
  will faithfully surface a real problem when one exists; M5 shows it lets a real, correct
  change through when `npm install` (the only step that could run, since no build/lint/test
  scripts exist yet) actually succeeds. **Caveat, stated plainly**: because there is still no
  test suite or build step that actually executes `auth.routes.js`, a *future* missing-`require`
  bug in this project would again not be caught until a real test suite exists (M7/QA Agent
  territory) — `npm install` alone only checks that declared dependencies resolve, not that
  the code correctly declares every dependency it uses.
- **RESOLVED (item 29): asking the LLM to retype the entire SRS verbatim was the actual defect,
  not a model-capacity ceiling.** The Domain Agent gotcha directly above (three models, four
  attempts, all structurally failing to reproduce a full two-part `enhanced_srs_json` +
  `domain_improvements_json` JSON blob) was diagnosed at the time as "a genuine local-model-
  capacity limitation." The user reported the Domain Agent still wasn't enriching anything and
  asked for a real fix, not just a documented limitation — redesigning the LLM contract so it
  proposes only a SMALL enrichment PLAN (new items + description enrichments, no IDs to invent,
  no SRS retyping) and letting deterministic Python (`DomainAgent._apply_enrichment_plan`) merge
  that into a full SRS copy **fixed it outright**: `qwen3-coder:latest` succeeded on the very
  first attempt, 3/3 real runs, no fallback triggered, for both the `Login` feature and a brand
  new `Item Management` CRUD feature (`QuickCart` project) — see item 29 below. The lesson: when
  a local model fails a large structured-output task, first ask whether the task itself can be
  shrunk before concluding the model can't handle it. See `app/agents/domain_agent/agent.py`'s
  and `prompt.py`'s module docstrings for the full design rationale.
- **RESOLVED (item 29): the Architecture Agent "taking over an hour" was a GPU/VRAM mismatch, not
  a hang.** `qwen3-coder:latest` is a 30.5B-parameter Q4 model (~18GB) on a machine with only a
  6GB GPU (RTX 4050) — Ollama could only offload ~3.4GB to VRAM, running ~85% of the model on
  CPU. A trivial "say OK" prompt didn't even complete in 15 seconds. Confirmed via `ollama ps`
  (`size_vram` far below the model's real size) and `nvidia-smi` (6141MiB total VRAM). Fix:
  switched `DEFAULT_LLM_MODEL` and `AGENTIC_MODEL_OVERRIDE` (both `.env` and the live Mongo-
  backed `store.llm_settings`) to `llama3:latest` (4.7GB, the only locally-cached model that
  actually fits this GPU) — Architecture Agent then completed in ~4.5 minutes instead of stalling
  past 90. **If this machine ever gets more VRAM, or a smaller code-specialized model is pulled
  (e.g. `qwen2.5-coder:7b`, ~4.7GB), revisit `AGENTIC_MODEL_OVERRIDE` specifically** — llama3 is a
  general instruct model, not code-specialized, and was only chosen because it's what already fit
  and was already cached.
- **UI/UX Agent had no reliability ladder at all for its two riskiest steps -- fixed (item 29).**
  `metadata_modeler.py` already had a JSON-parse repair ladder, but the SEPARATE coverage/
  structure validator call in `agent.py` had zero retries: any schema-valid-but-incomplete output
  (e.g. a page missing one of the required `states`) crashed the whole run immediately. Worse,
  `UIMetadataValidator.validate()`'s `if not errors:` gate meant only ONE category of problems
  was ever revealed per attempt — fixing the "states" gap on repair just exposed a previously-
  hidden `covers_requirements` gap on the next attempt, one layer at a time. Fixed both: the
  validator now only skips coverage checks when the structure is genuinely unsafe to inspect
  (not a list, or a page isn't a dict) — everything else reports all real errors together, so a
  single repair attempt sees the full picture. `_generate_and_validate_metadata` now retries up
  to `MAX_VALIDATION_REPAIR_ATTEMPTS = 4` (real testing against `llama3:latest` showed the
  missing-ID count genuinely shrinking each round -- 6→4→1 in one run -- true convergence, not
  flailing, which is why the bound is higher than Requirement/Domain/Architecture's usual "one
  repair"). Component generation got the same treatment: a real run hit
  `ReferenceError: Item is not defined` (the model factored a per-row `<Item />` sub-component
  instead of inlining it) — added rule 9 to `COMPONENT_GENERATOR_SYSTEM_PROMPT` explicitly
  forbidding this, plus `component_generator.repair_for_render_error` /
  `UIUXAgent._repair_page_components` to feed the real browser console error back for up to
  `MAX_RENDER_REPAIR_ATTEMPTS = 3` attempts (real testing showed a repair can trade one error for
  a different one -- fixing the ReferenceError once produced a JSX syntax error instead -- so one
  attempt was provably not always enough).
- **Playwright's per-call `Locator.screenshot(timeout=...)` kwarg does not reliably override the
  default timeout in this environment -- confirmed by direct testing** (a call with
  `timeout=8000` still took the full ~30s default before failing). `page.set_default_timeout(N)`
  does work correctly (confirmed: set to 5000, failed at exactly 5.0s). `preview_renderer.py` now
  calls `page.set_default_timeout(90000)` right after `browser.new_page(...)` instead of passing
  `timeout=` to the screenshot call itself.
- **A preview-render failure that reproduces only inside the live LangGraph-invoked pipeline, not
  in direct isolation -- still unexplained, worked around rather than root-caused.** A real
  `item-management-page` render (`QuickCart`/`Item Management`, item 29) failed with
  `Locator.screenshot: Timeout ... element is not visible` -- consistently, across many retries,
  even after confirming `page.set_default_timeout(90000)` was genuinely honored (the error
  message itself changed from `~30000ms` to `~90000ms exceeded`, so the fix was real, but the
  element still never stabilized in 90 real seconds). Extensive direct testing could not
  reproduce this: the exact same JSX + mock_props, run via `sync_playwright()` directly, via
  `asyncio.to_thread` from a plain async function, and via `async_playwright()` natively, all
  rendered successfully and quickly every time. The only remaining unverified difference is the
  live LangGraph/MongoDB-checkpointer execution context itself (nested thread/event-loop
  interaction with Playwright's sync API that a standalone script can't reproduce). **Rather than
  keep guessing at a root cause I can't reproduce, made preview rendering non-fatal**: after
  `MAX_RENDER_REPAIR_ATTEMPTS` are exhausted, `_render_pages` now logs an error and skips that
  page's screenshot instead of raising -- a defensible tradeoff since nothing downstream
  (Architecture/Coder Agent) reads `page_screenshots`; it exists purely for human preview. If this
  recurs, the next thing to try is switching `preview_renderer.py` from `sync_api` to
  `async_api` end-to-end (removing the `asyncio.to_thread` wrapper entirely) — not done yet since
  it's a bigger refactor than tonight's fix budget allowed and the non-fatal skip already unblocks
  the pipeline.
- **Windows: `shutil.rmtree` on a git repo directory reliably fails** with either a
  `PermissionError` from git's read-only object files, or (worse, and non-obvious) "the process
  cannot access the file because it is being used by another process" from GitPython's `Repo`
  object holding an open file handle even after the test using it has gone out of scope. Fixed
  in `tests/test_coder_tools.py`/`tests/test_coder_verify.py` by (1) explicitly calling
  `workspace_service.ensure_project_repo(project_id).close()` before `rmtree`, and (2) passing
  an `onerror` handler that clears the read-only bit and retries. **Any new test that creates a
  real git repo via `workspace_service` needs both of these in its teardown**, or leftover
  `workspaces/*` directories will silently accumulate (this happened once already in M5 --
  `ignore_errors=True` was masking the failures rather than fixing them).
- **Docker Desktop does not auto-start with Windows in this environment.** If
  `sandbox_service.run_command` returns `exit_code: 1` with `"Sandbox unavailable: could not reach
  Docker daemon"`, that's this, not a code bug -- launch
  `C:\Program Files\Docker\Docker\Docker Desktop.exe` and poll `docker version` until it responds
  (~10s in practice) before retrying.
- **Running the full Docker-heavy pytest suite at the same time as a real agentic pipeline run
  that also uses the sandbox causes false-negative verify failures**, specifically in the
  server-boot smoke test: both compete for the same Docker daemon, and a container can be too
  slow to get scheduled CPU to answer the health check within its retry window even though the
  server process itself started fine (confirmed directly: a real 3-attempt `CoderAgent.run()`
  recorded `server boot` as failed on every attempt while a full pytest run happened to be
  running concurrently; re-running the identical check against the identical generated code in
  isolation immediately after passed cleanly, `exit_code: 0`). Widened the health-check retry
  loop (10 -> 30 attempts, `SERVER_BOOT_TIMEOUT_SECONDS` 30 -> 45) to make this less likely, but
  the safest thing is still: don't run the full suite and a real end-to-end agent run at the same
  time on this machine.
- **Approving a UI/UX run's `ui_metadata` artifact does NOT approve its individual component
  artifacts.** `approval_service.py`'s UI/UX hook only checks for `ArtifactType.UI_METADATA` to
  trigger `apply_design_system_patch` -- there is no cascade to the sibling `UI_COMPONENT_CODE`
  artifacts from the same run. `CoderAgent`'s `read_ui_component` tool only ever finds components
  with `approval_status == APPROVED` (`_find_approved_component_artifact`), so if only the
  metadata was approved, the Coder Agent will find nothing to reuse and will build its own
  from-scratch version instead -- silently, with no error, since "no approved component found" is
  a valid, expected outcome for a genuinely backend-only feature. Confirmed directly: this exact
  gap caused a real Coder Agent run for Task Comments to fabricate its own `CommentInput`/
  `CommentList` instead of reusing the approved ones (see item 20). **Every `UI_COMPONENT_CODE`
  artifact a feature's coding step is expected to reuse must be approved individually**, not just
  the metadata JSON.
- **`GraphRecursionError` (from `langgraph.errors`) is a real, reachable failure mode for the
  Coder Agent's coding loop on a realistically-sized plan** (confirmed: an 8-file plan with 2
  "modify an existing file" tasks exhausted a 65-step budget). It is now caught in
  `CoderAgent._code_with_retries` and treated as a recoverable failed attempt (see item 20) --
  but if a similar uncaught `GraphRecursionError` ever surfaces elsewhere (e.g. if the UI/UX Agent
  grows an agentic loop of its own someday), the same pattern applies: catch it at the attempt
  boundary, commit partial progress, retry with an efficiency-focused message, don't let it
  crash the whole request.
- **Every generated app's `HomePage` had no navigation at all until item 21's fix** -- any
  `<Route>` a feature plans is real and correctly wired, but was never reachable by a human
  clicking through the running app (confirmed as the root cause of "every feature just shows the
  placeholder text no matter what was built"). Fixed via a `FEATURE_LINKS_START`/`_END` marker in
  `HomePage` + `nav_checker.check_page_reachability` as a new hard `verify()` gate. If a project
  was scaffolded before this fix, `ensure_project_repo` self-heals it on next call (same backfill
  mechanism as every other scaffold upgrade) -- but any **already-existing** route from before the
  fix still needs a human (or a `CoderAgent.revise()` request) to actually add its `<Link>`; the
  backfill only adds the mechanism, it does not retroactively link routes it didn't create.
- **Playwright's sync API cannot run on a thread that already has an asyncio event loop
  running** -- `render_checker.py`'s runtime-render check learned this the hard way: it's only
  ever really invoked through `CoderAgent.run()`/`revise()` (both `async def`, bridged from a sync
  graph node via `asyncio.run(...)`, deviation #13), so an event loop is *always* active on the
  calling thread in production, even though it's invisible in any test that calls `verify()`/
  `check_runtime_render` from a plain synchronous script. Fixed by running the actual
  Playwright-touching work inside its own `concurrent.futures.ThreadPoolExecutor` worker thread,
  internal to `check_runtime_render` -- **any future check that uses Playwright's (or another
  library's) sync API and might be called from inside `CoderAgent`'s or `UIUXAgent`'s async call
  chain needs the same treatment**, regardless of whether it happens to work in an ad hoc sync
  test script.
- **A revision's own plan is naturally a delta, but `plan_validator` checks full architecture-plan
  coverage** -- confirmed directly: a real `CoderAgent.revise()` request ("add a loading spinner")
  produced a plan that only touched the one file that needed to change, and was rejected for
  "missing" endpoints that the *prior*, still-in-place plan already implements. `revise()` now
  passes `_plan_with_retries` an optional `coverage_baseline_files` so coverage is checked against
  the **union** of prior + delta, while only the delta is actually coded -- **any future caller of
  `_plan_with_retries` for an intentionally-partial/incremental plan must do the same**, or it
  will hit this exact false rejection.
- **"The latest saved CODE_PLAN" is NOT "everything this feature has ever implemented," once even
  one revision has happened** -- the coverage-baseline fix above initially built
  `coverage_baseline_files` from only the single latest CODE_PLAN artifact, which broke on a real
  SECOND revision: the first revision's own saved plan was itself just a delta (by design), so
  using only *that* as the baseline for the next revision silently dropped everything the
  *original* plan covered, reproducing the identical false rejection -- this time surfaced
  directly to a real user through the live `/coder/revise` endpoint. Fixed with
  `CoderAgent._collect_cumulative_plan_files`, which unions file entries across **every** CODE_PLAN
  version ever saved for the feature (later versions winning per path), not just the latest one.
  **Any logic anywhere in this codebase that needs "the full picture of what a feature has
  implemented so far" must walk every artifact version, not assume the latest one is
  self-contained** -- that assumption is only ever true before the first revision.
- **A model reliably finds files that match a pattern, but unreliably finds files that DON'T** --
  confirmed directly: the agentic revision planner (item 22) correctly discovered Tailwind was
  already configured project-wide via its own tools, but still converged on the wrong fix, because
  manually cross-referencing "every page/component file" against "which ones showed up in a
  className search" to deduce the files that DIDN'T is a much harder inverse-search reasoning task
  than a direct grep. **Any future case that needs "which files are missing X" (not "which files
  have X") should get a cheap, deterministic tool/check that answers it directly** (like
  `style_checker.py`'s `check_component_styling`), rather than trusting an agentic loop to reliably
  reason its way to the same answer via generic list_dir/read_file/search_code exploration alone.
- **A real, transient Ollama/langchain-ollama streaming error was hit once during this session's
  testing**: `ollama._types.ResponseError: XML syntax error on line 4: unexpected EOF` , raised
  from deep inside `langchain_ollama`'s chat-streaming response aggregation, uncaught, crashing the
  whole `revise()` call. Did not reproduce on an immediate retry of the identical request --
  treated as a one-off transport/server hiccup (this environment's Ollama server has other
  documented flakiness, e.g. Docker-contention false negatives), not a logic bug, and NOT specially
  caught in code for that reason -- if this recurs reliably (not just once), it would be worth
  broadening `_plan_with_retries`'s exploration-path exception handling beyond just
  `CodePlanGenerationError` to catch this too.
- **The agentic exploration planner has no checkpointer, so a completed run's actual tool-call
  trace is not inspectable afterward** -- confirmed as a real diagnostic limitation: a live run
  submitted an empty `files` list after extensive real exploration, and there was no way after the
  fact to see what the model actually looked at or why it concluded there was nothing to plan.
  **If this specific failure mode (a plan that parses but has empty/wrong content, despite
  seemingly-successful exploration) recurs**, the way to actually root-cause it is to add a
  checkpointer to the `create_agent(...)` in `CodePlanner.generate_via_exploration` (or log each
  tool call/result as it happens) so the conversation is inspectable -- guessing from httpx
  timestamps alone (as this session had to) only reveals *when* things happened, not *what* the
  model was actually reasoning about.
- **A feature's real API shape can legitimately evolve past its Architecture Plan's frozen
  snapshot, and once that happens, no revision can ever satisfy the old literal requirement again**
  -- confirmed directly: `/api/task-comments` (the Architecture Plan's original literal endpoint
  string) was legitimately restructured to `/api/tasks/:taskId/comments` + `/api/comments/:commentId`
  during earlier work, permanently blocking every subsequent `revise()` call's coverage check. Fixed
  by skipping endpoint-literal-string coverage specifically for `revise()` (see item 23) -- **if a
  similar "the original requirement no longer matches the evolved reality" problem is ever found for
  entity names or requirement IDs**, the same reasoning (and the same `enforce_...` flag pattern)
  would apply there too, though neither has shown this problem yet.

## Testing conventions established

- `tests/` at `services/agentic_service/tests/`, pytest (installed via pip; not yet added to
  `requirements.txt` as a formal dependency since it's dev-only so far).
- Deterministic/validator logic: hand-crafted fixtures, no LLM, fast, golden-file style where
  applicable (e.g. `test_uiux_integration_manifest_builder.py`, `test_coder_diff_builder.py`).
- LLM-touching pipelines: also verified manually at least once per milestone against the **real**
  approved Login feature data (not just synthetic fixtures) — screenshots and generated code
  visually/manually inspected, not just asserted on structurally.
- Any project/feature/artifact created purely for isolated testing is deleted from Mongo + disk
  afterward (never left as debris) -- see the Windows `shutil.rmtree` gotcha above for the
  correct teardown pattern for git-repo-backed fixtures. The real `e-commerce-platform` /
  `Login` feature data is the intentional running example and is **left in its real, evolving
  state** between milestones.
- Docker containers are checked (`docker ps -a`) after every `sandbox_service`-touching test run
  to confirm none are left running.

## Real state changes made to the actual project (not test debris — don't "clean" these up)

- `outputs/e-commerce-platform/_project/design_system.json` — created in M2, contains the
  approved `LoginForm` component entry.
- `outputs/e-commerce-platform/_project/project_manifest.json` — created in M5 by the real
  `merge_approved_feature` approval hook, contains the real routes/api_endpoints/models/
  shared_components/features derived from the merged Login feature.
- `artifact_83e3692d` (`LoginForm.jsx`, `uiux_agent`, v1) was approved during M3 tool testing
  specifically to validate `read_ui_component`'s happy path against real data. This is a
  legitimate approval (it's a genuinely good component from M2), not a mistake to revert.
- **`workspaces/e-commerce-platform/repo/` — `main` now contains the real, merged Login feature**
  (as of M5): a `--no-ff` merge commit ("Merge feature/login into main") on top of the original
  scaffold commit. `main` has: `client/src/pages/LoginPage.jsx`,
  `client/src/components/LoginForm.jsx` (the actual approved UI/UX component, integrated
  verbatim via `read_ui_component`, not regenerated), `client/src/services/authService.js`,
  `server/src/routes/auth.routes.js`, `server/src/models/UserCredentials.js`, and
  `package.json`/`package-lock.json` (real `npm install` of `axios`, `bcrypt`, `dotenv`,
  `jsonwebtoken`, `jwt-decode`). The `feature/login` branch no longer exists (deleted by
  `merge_feature_branch` after the merge). **This was approved and merged through the real,
  unchanged `POST /artifacts/{id}/approval` endpoint** (`artifact_94797be2`, `code_diff`/json),
  driven by `CoderAgent.merge_approved_feature`. Verification for this merge showed
  `npm install: passed`, `build/lint/test: skipped` (no scripts configured yet in this project —
  see gotchas above for what that does and doesn't prove). M4's earlier manual-run commit on
  `feature/login` (with the then-missing `jsonwebtoken`) was superseded when M5 recreated the
  branch from scratch, as anticipated in M4's own notes.
- **The real planner (`CodePlanner`) cannot currently drive `CoderAgent.run()` unattended for
  this feature** — it exhausts both planning attempts and `run()` raises
  `CodePlanValidationError` (see gotchas above). The merge above was driven by the
  hand-validated plan in `scripts/run_coder_pipeline_manual.py`, exercising every stage
  downstream of planning (coding loop, verify, diff, artifacts, approval, merge) for real. This
  is the same precedent M4 set and is not a workaround unique to this session — expect to keep
  using it for real pipeline testing until the planner prompt is improved further.
- **M6 real end-to-end graph run for Login**: `graph_orchestrator_service.start(...)` →
  `resume("approved")` (SRS already approved) → auto-passed domain → paused at
  `approve_architecture` → `resume("approved")` (Architecture Plan already approved) → **real
  `uiux_node` ran**, producing a genuine v2 of every UI/UX artifact
  (`login_ui_metadata_v2.json`, `login_integration_manifest_v2.json`, `login_ui_design_v2.md`,
  `login_loginform_v2.jsx`, `login_login_page_v2.png` — visually confirmed, a clean styled login
  form) → paused at `approve_uiux` with the real v2 artifact IDs surfaced in graph state. Approved
  `artifact_26d13fb2` (`ui_metadata` v2) through the real `POST /artifacts/{id}/approval`
  endpoint, which (a) ran `apply_design_system_patch` again (correctly a no-op: `LoginForm`
  already existed, 0 new components/tokens merged — idempotent) and (b) resumed the graph into
  the **real `coder_node`**, which ran the real planner (both attempts, ~45s each), hit the
  documented `CodePlanValidationError`, and the exception was caught by
  `approval_service`'s existing broad exception handler (see gotcha #15 above) — the approval
  HTTP call still returned 200 OK normally. `graph_orchestrator_service.get_status(...)` now
  shows `next: ["coder_node"]` for this feature/thread — a future approval-triggered resume (or
  a fixed planner) would cleanly retry `coder_node` from there. This is the intended, correct M6
  outcome: the graph faithfully delegates to the real agents, successes and failures alike,
  through the exact same human-facing approval endpoint used throughout this whole build.
- `login_ui_metadata_v2.json` etc. (the v2 UI/UX artifacts from the run above) are real outputs
  of this milestone's verification, not test debris — left in place alongside the v1 set from M2.
- **`workspaces/e-commerce-platform/repo`'s `main` now has a real, working Express+Vite scaffold**
  (post-M8 fix, see deviation #17): `server/{package.json,src/app.js,src/server.js,.env.example}`
  and `client/{package.json,vite.config.js,index.html,src/{main.jsx,App.jsx,index.css}}` were
  backfilled via `ensure_project_repo`, and the already-merged Login feature was hand-wired into
  them (`app.js` mounts `auth.routes.js` at `/api/auth`; `App.jsx` routes `/login` to
  `LoginPage`), plus `bcrypt`/`jsonwebtoken`/`axios`/`jwt-decode` relocated into the correct
  `server`/`client` `package.json`. `client/package-lock.json` and `server/package-lock.json`
  are also real, committed output of the verification run (not debris). `git log --oneline -6`
  on `main` at time of writing: `c44825f` (lockfiles) → `d272f24` (Login wiring) → `de4de30`/
  `cbc1ac9` (scaffold backfill) → `667b0ef` (Login merge) → `c8bd481` (M4 manual coding attempt)
  → `0f5fcb3` (original bare scaffold, now superseded).
- **`main` also has `d513acc` on top of the above** ("Backfill scaffold upgrades: security
  middleware, DB connection, error handling") -- item 18's `_backfill_scaffold_upgrades` firing
  for real against this repo, adding helmet/rate-limit/`FEATURE_ROUTES_START`/`_END`/error-handler
  to `app.js` (preserving the already-mounted `authRoutes`) and guarded `mongoose.connect` to
  `server.js`, confirmed via the diff at the time (not test debris).
- **`feature/signup` branch (not yet merged, pending human review)**: two real Coder Agent
  commits (`66cf00d` attempt 1, `864a706` attempt 2 -- attempt 3 made no additional changes and
  wasn't committed since nothing new was dirty) modify `server/src/routes/auth.routes.js` (adds
  a real, validated `/signup` route: required-field check, existing-user check, JWT issuance) and
  `server/src/models/UserCredentials.js` (adds the `fullName` field), plus `bcryptjs` installed
  (declared at the repo root by the model's own `npm install` rather than `server/package.json`
  -- a real, minor planner/coding-loop imprecision worth knowing about, though harmless since
  `UserCredentials.js` still uses the original `bcrypt`, not `bcryptjs`, for its hashing). Code
  plan v1 + a first artifact set (`verification_passed: false`, from the contention-confounded
  run) plus a corrected v2 artifact set (`verification_passed: true`, from the clean re-verify --
  same code, accurate result) both exist under `outputs/e-commerce-platform/feature-signup/
  05_code/`; v2 is the one to review/approve. Signup's UI/UX v2 (LoginForm genuinely reused
  byte-for-byte, SignupForm freshly generated -- see item 17) was approved for real through
  `POST /api/v1/artifacts/{id}/approval` during this session, which is what resumed the graph
  into this real `coder_node` run in the first place.
- **A second real project now exists**: `proj_53284a63` ("TaskFlow", SaaS/MERN), feature
  `feature_5521adbd` ("Task Comments") -- created specifically to real-world-verify item 19's
  Architecture Agent fix against a genuinely new project (not e-commerce-platform). Has approved
  SRS v2 (`artifact_7082b7d7`), approved Architecture Plan v1 (`artifact_2190f60f`, the
  deterministic-fallback shape described in item 19), approved UI/UX v1
  (`artifact_b3950e89` + `CommentInput.jsx`/`CommentList.jsx` components). The LangGraph
  checkpoint for `feature_5521adbd` is currently parked at `next: ['coder_node']` after a real
  `CodePlanValidationError` (the pre-existing planner limitation, not a new issue) -- a future
  `resume()` call would retry the real planner cleanly, or a hand-validated plan (matching the
  established Login/Signup precedent in `scripts/run_coder_pipeline_manual.py`) could be used to
  exercise the rest of the Coder Agent pipeline for this feature if desired. **No
  `workspaces/taskflow/` directory exists yet** -- `CoderAgent.run()` calls
  `workspace_service.start_feature_branch(...)` only *after* `_plan_with_retries` succeeds, and
  planning failed before that point, so the project's git repo/scaffold has never been created
  for TaskFlow. **(Superseded by item 20/21 below: `workspaces/taskflow/repo` was subsequently
  created via the hand-validated manual pipeline and now has real commits on `feature/task-comments`.)**
- **Item 21's real, live-project verification, on top of everything item 20 already left in
  place**: `workspaces/e-commerce-platform/repo` (currently on `feature/signup`) and
  `workspaces/taskflow/repo` (currently on `feature/task-comments`) both gained a new real commit
  ("Backfill scaffold upgrades: ... home page navigation") from calling `ensure_project_repo`
  again -- the `FEATURE_LINKS` marker is now present in both repos' `App.jsx`, on top of whatever
  each branch had already added. Neither branch's pre-existing route (`/login`/`/signup` for
  e-commerce, `/tasks/:taskId` for taskflow) got a `<Link>` retroactively added by this (the
  backfill only adds the *mechanism*, not a link for a route it didn't create) -- `verify()`'s new
  `page reachability` gate correctly and honestly still fails for both, which is expected, not a
  regression.
  - `feature/task-comments` also gained two more real commits from a genuine
    `CoderAgent.revise()` run (revision comment: "add a loading spinner while comments are being
    fetched"): `3899554` (attempt 1) and `2b50de7` (attempt 2, the one that stuck -- diff is a
    single line added inside `CommentList.jsx`'s existing loading state). A corrected, accurate
    **v4** artifact set (`artifact_8169b564` and siblings) was saved reflecting the real verify
    result (`page reachability: failed` -- the known, pre-existing, out-of-scope-for-this-revision
    gap; every other step, including the now-fixed `home page render`, passes) -- v1-v3 (from
    earlier sessions/attempts) remain intact and superseded, matching this project's existing
    "never overwrite, always version" artifact convention.
- **Item 22's real verification against `feature/task-comments`**: between this and the prior
  session, the user independently exercised the (then-still-buggy) `/coder/revise` endpoint
  directly through Swagger several times, which is how `client/src/pages/TaskflowHomePage.jsx` and
  `client/src/components/TaskComments.jsx` came to exist on this branch (real, legitimate user
  work, not debris -- left untouched). On top of that real state, this session's `revise()` calls
  (real "add a loading spinner"/"add a delete confirmation dialog"/two "styles are missing, add
  tailwind css" attempts) added further real commits, ending at `a80c559` ("Coder Agent attempt 3:
  feature_5521adbd") -- the final, correct fix: `TaskflowHomePage.jsx`'s raw inline styles replaced
  with Tailwind classes, plus a `client/postcss.config.cjs` the coding loop added on its own
  initiative (attempting, incompletely, to fix the separate pre-existing PostCSS bug documented in
  item 22). The latest artifact set (`artifact_d5833291` and siblings, `verification_passed:
  False` solely due to that separate PostCSS bug) is left in place, pending human review -- not
  merged. **Still not fixed**: `client/postcss.config.js` (the original, broken CommonJS file) is
  still present alongside the new working `.cjs` version; deleting the former would let
  `client build` pass cleanly.
- **Item 23's real, direct fixes on `feature/task-comments`** (applied directly, not through
  `revise()`, given the multi-hour real cost already spent reproducing the exploration-planner
  issues that session): `d48b54e` removed a duplicate `<BrowserRouter>` in `App.jsx` that was
  crashing the entire app to a blank page (React Router throws on nested Routers with no error
  boundary to catch it); `0d7bf78` added the missing `tailwindcss`/`postcss`/`autoprefixer` npm
  packages and deleted the stale `client/postcss.config.js` stub that was shadowing the real
  `postcss.config.cjs` in Vite's config resolution (root cause of "Tailwind never actually
  applies" -- confirmed empirically: built CSS grew from 136 bytes of raw, unprocessed `@tailwind`
  directives to 12.86kB of real utility CSS); `22c03bb` registered the missing
  `<Route path="/tasks/:taskId">` for `TaskDetailPage.jsx` (which already existed, fully built and
  styled, but was never wired into routing -- confirmed via a real Playwright screenshot showing a
  completely blank page before the fix, fully rendered after). Each commit has its own real,
  independently-approvable artifact set (`artifact_dfc0e118`/`artifact_651f0b96`/`artifact_662fd295`
  and siblings respectively), all with `verification_passed: True`.
- **Item 25's real E2E feature**: `proj_53284a63` (TaskFlow) gained another new feature,
  `feature_244e26d1` ("Task Search", a separate feature from item 24's `feature_29fa0ed4` of the
  same name -- both are real, left in place), with an approved SRS and an Architecture Plan
  (`artifact_434cc2dd` v1, `artifact_e406e74b` v2 from the `revise()` exercise) plus real rendered
  use case/sequence/class diagrams for both versions under
  `outputs/taskflow/feature-task-search/03_architecture/`. v1's use case diagram carries the
  cross-category-duplicate bug described above (left in place deliberately, as the real evidence
  for that finding, not cleaned up); v2 is the corrected, validation-clean result. Neither version
  is approved -- v1's human_approval_note honestly flags the duplicate; a future session could
  approve v2 and continue this feature through UI/UX and Coder Agent.
- **Item 26's real E2E verification, on the same `feature_244e26d1`**: four real `revise()`
  calls across the sequence/class dedup-bug fix cycle -- the first two crashed before saving any
  new artifact (sequence duplicate-message bug, then the class anemic-DTO check propagating
  uncaught since `revise()` had no safety net yet); the third (post sequence-fix and
  safety-net-fix, pre operation-dedup-fix) produced Architecture Plan v3 (JSON+Markdown) and
  `task_search_sequence_v3.puml`/`.png` + `task_search_class_v3.puml`/`.png`, completing via the
  new caveat safety net but still visually showing the class duplicate-operation bug; the fourth
  (all fixes in place) produced Architecture Plan v4 and `task_search_sequence_v4.puml`/`.png` +
  `task_search_class_v4.puml`/`.png`, clean of both duplicate bugs -- all left in place as real,
  inspectable verification output. None of these versions are approved; v4's
  `human_approval_note` honestly flags the upstream anemic-DTO data-quality issue described above
  (real, but out of this milestone's scope to fix at the source).
- **Item 27's real E2E verification, on the same `feature_244e26d1`**: a direct
  `_complete_diagram_models(attempt_agentic=True)` call (not saved as artifacts -- used to isolate
  and verify the new agentic loops specifically) confirmed the sequence agentic loop hits its
  20-turn limit on this real feature/model combination but the new focused single-shot fallback
  produces genuinely dynamic content; a second, real `revise()` call (`attempt_agentic=False`)
  produced Architecture Plan v5 and `task_search_sequence_v5.puml`/`.png` +
  `task_search_class_v5.puml`/`.png`, saved as real, inspectable output -- this run also exercised
  item 26's reactive class-repair loop for real (a genuine anemic-attribute validation failure
  that self-corrected on retry). Not approved; left in place with the honest stereotype-mismatch
  quirk noted above still visible for a future session to judge.

- **Item 28: Domain Agent built as a real RAG system** (previously a stub, `raise
  NotImplementedError`), per the plan at the top of this session
  (`C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing). New
  `app/services/rag/` package (`loaders.py`/`chunking.py`/`embedding.py`/`vector_store.py`) +
  `app/services/domain_knowledge_service.py` do real deterministic retrieval (embed query with a
  local `sentence-transformers/all-MiniLM-L6-v2` model, loaded lazily; similarity-search a
  persistent local ChromaDB collection at `vector_db/chroma`) — never an LLM tool-calling loop,
  per this repo's own build-spec constraint that Domain/Requirement/Architecture stay on the
  one-shot `BaseLLMProvider` path. Seed e-commerce knowledge base authored at
  `knowledge_base/ecommerce/` (5 `.txt` files: checkout/cart, payment/PCI, catalog/inventory,
  order lifecycle, account/auth) and really ingested via `scripts/ingest_domain_knowledge.py`
  (5 files, 21 chunks) — `scripts/verify_domain_rag_e2e.py` confirms real retrieval returns the
  correct on-topic source document for 4/4 representative e-commerce queries plus the empty-query
  edge case. `AgentName.DOMAIN`/`ArtifactType.ENHANCED_SRS` were already pre-wired; added
  `ArtifactType.DOMAIN_IMPROVEMENTS` for the new human-readable "what changed and why" summary
  artifact. `domain_validator.py`'s honesty check (no additions/modifications may be claimed when
  retrieval returned zero chunks) is the enforcement mechanism that makes "Domain Agent is a real
  RAG system" a checked fact rather than a claim. `graph_orchestrator_service.py`: `domain` moved
  from `AUTO_APPROVED_STAGES` into `GATED_STAGES` with a real `_domain_node` (mirrors `_uiux_node`)
  — this is exactly the flip the M6-era docstring said to make "the moment Domain Agent produces
  real output." `tests/test_graph_orchestrator.py` updated accordingly: the fast, throwaway-feature
  mechanics tests now anchor entirely at the `requirement` gate (same reasoning that already
  excluded `uiux`/`coder` — `domain` now needs a real approved SRS artifact + a real LLM call, so
  it can no longer be cheaply traversed by a mechanics-only test). New agent files:
  `app/agents/domain_agent/{agent.py,domain_validator.py,markdown_builder.py}` (schemas.py/
  prompt.py extended in place), `app/schemas/domain_schema.py`; real `/domain/run` and new
  `/domain/revise` endpoints replace the old placeholder in `app/api/routes/agents.py`. 29 new
  unit tests (chunking/validator/markdown-builder/fallback/retrieval-query), all pure Python, all
  passing, plus the full existing suite re-run clean (only pre-existing, unrelated Docker-daemon-
  dependent failures in `test_coder_tools.py`/`test_coder_verify.py`/`test_render_checker.py`,
  environmental, not caused by this change). **Real e2e verification against the real, approved
  `Login` feature (`feature_a44033b8`, `E-commerce Platform` project, approved SRS v3)**: real
  retrieval genuinely found 3 relevant e-commerce knowledge sources for this feature
  (`checkout_and_cart_conventions.txt`, `payment_and_pci_basics.txt`,
  `user_account_and_authentication.txt` — a sensible match for a Login feature). All four real
  LLM generation attempts (see the model-quality gotcha above) hit the fallback path, producing
  `login_enhanced_srs_v1.json`/`.md` and `login_domain_improvements_v1.json` through
  `login_enhanced_srs_v4.json`/`.md` and `login_domain_improvements_v4.json` under
  `outputs/e-commerce-platform/feature-login/02_domain/` — each fallback artifact set is real,
  honest, validator-clean output (unchanged SRS content, `fallback_used: true`, a correct,
  specific `fallback_reason`), left in place as genuine evidence the reliability ladder holds up
  under real repeated LLM failure, not synthetic test debris. None of these are approved yet —
  a future session with a more capable model (larger local model or a hosted provider) could
  re-run `domain_agent.run('feature_a44033b8', ...)` to get a genuinely enriched (non-fallback)
  version for human approval.
- **Item 29: Domain Agent redesigned to actually enrich (not just fall back safely), plus a real,
  full pipeline run through Coder Agent on a brand-new project.** The user reported item 28's
  Domain Agent still wasn't enriching anything and asked for a real fix plus a fresh end-to-end
  pipeline test. Root cause: asking the LLM to retype the entire SRS verbatim in one JSON blob
  was itself the defect (see the RESOLVED gotchas above), not a model ceiling as item 28
  concluded. Redesigned the LLM contract to a small enrichment PLAN (additions/modifications
  only, no SRS retyping, no ID invention -- `DomainAgent._apply_enrichment_plan` merges it into a
  full SRS copy deterministically); `domain_validator.py` rewritten to `validate_plan()`,
  checking the small plan pre-merge instead of the merged output post-merge.
  `tests/test_domain_validator.py` and `test_domain_agent_fallback.py` fully rewritten for the
  new shape (34 domain tests total, all passing). **Real result: `qwen3-coder:latest` succeeded
  on the first attempt, 3/3 real runs, zero fallbacks** -- both re-run against the existing
  `Login` feature (`login_enhanced_srs_v5/v6/v7.json`, correctly adding an account-lockout
  requirement and enriching the forgot-password acceptance criterion, both genuinely cited from
  `user_account_and_authentication.txt`) and against a brand-new feature created this session (see
  below). Also fixed in passing: `RequirementAgent.run()` was saving its Markdown/JSON pair at
  MISMATCHED versions (`SRS_v1.md` next to `SRS_v2.json` -- confirmed present since this
  project's very first-ever SRS) because neither `save_text_artifact` nor `save_json_artifact`
  was passed `version_override`, unlike `_save_revised_srs_artifacts` which already did this
  correctly; now computes one shared version up front for both, matching that established
  pattern. **A new real project/feature exists**: `proj_983f2941` ("QuickCart", E-commerce/MERN),
  `feature_89878ec1` ("Item Management" -- add/edit/update/delete catalog items), created and
  driven entirely through the real HTTP API (`fastapi.testclient.TestClient`, not shortcuts) to
  verify the whole pipeline end-to-end for real: approved SRS v1 → real Domain Agent enrichment
  (SKU uniqueness, currency-code, price-history, and prevent-deleting-items-in-active-orders
  additions, all correctly cited from `product_catalog_and_inventory.txt`/
  `checkout_and_cart_conventions.txt`) → approved Enhanced SRS → real Architecture Agent (~4.5 min
  after the model swap below) → approved Architecture Plan → real UI/UX Agent (see the fixes
  below) → approved UI metadata → real Coder Agent, which hit its long-documented planner
  limitation (`CodePlanValidationError` after 2/2 attempts, missing backend files/routes for the
  CRUD endpoints -- the exact same pre-existing gap documented earlier in this file, not a new
  issue) and parked the graph at `next: ['coder_node']`, exactly matching the established M6-era
  precedent. **Along the way, diagnosed that "Architecture Agent takes over an hour" was a
  GPU/VRAM mismatch** (`qwen3-coder:latest` doesn't fit this machine's 6GB RTX 4050), user chose
  to switch both `DEFAULT_LLM_MODEL` and `AGENTIC_MODEL_OVERRIDE` to `llama3:latest` (`.env` and
  the live `store.llm_settings`) -- see the RESOLVED gotcha above for the full diagnosis. **UI/UX
  Agent needed three additional real fixes** to get through a fresh feature with the smaller
  `llama3:latest` model: a validation repair ladder where none existed before, a validator fix so
  a repair attempt sees every real error at once instead of one category at a time, and a
  component render-repair ladder plus a preventive prompt rule for a real
  `ReferenceError: Item is not defined` bug (the model factored out an undefined `<Item />`
  sub-component) -- see the gotchas above for the full detail on each. One page's preview
  screenshot (`item-management-page`) was ultimately skipped (logged as an error, not fatal) after
  a render failure that would not reproduce in any direct isolation test -- see the "still
  unexplained" gotcha above; every other artifact (ui_metadata, 3 components, integration
  manifest, markdown) saved and approved normally. Full test suite re-run clean at the end (301
  passed, only the same pre-existing Docker-daemon-dependent failures, unrelated to any of this).
30. **Built the AutoForge operator-dashboard frontend end-to-end (new top-level `frontend/`,
    React + Vite + Tailwind v4 + React Query + react-router-dom), covering the full
    Requirement → Domain → Architecture → UI/UX → Coder pipeline with Security/QA/Deployment as
    visible placeholders, per user request.** Full spec: the plan this session followed (now
    overwritten per this file's own convention, see `C:\Users\ASUS\.claude\plans\soft-petting-star.md`).
    Two small, additive backend routes were prerequisites: `GET /artifacts/{artifact_id}/content`
    (`app/api/routes/artifacts.py` — unified text/JSON/PNG content-serving, since `GET
    /artifacts/{id}` only ever returned file-path metadata) and `GET
    /features/{feature_id}/graph-status` (`app/api/routes/features.py` — thin wrapper exposing
    `graph_orchestrator_service.get_status()`, previously only ever returned inline from `POST
    /start`). Also fixed two **pre-existing, unrelated** `list_*` 500-crash bugs hit along the way
    (same "one malformed record breaks the whole list" pattern in both): `list_projects()`
    (13 confirmed test-debris Mongo documents, deleted with explicit user consent) and
    `list_feature_artifacts()`/`list_project_features()` (55+ real, historical `qa_agent`
    `"test_cases"` artifacts predating QA Agent's simplification to a stub — genuine data, not
    debris, so fixed with the same defensive per-record try/except-and-log pattern instead of
    deleting).
    - **Milestones M1–M2** (scaffold, Project/Feature CRUD, Requirement Agent run/review,
      artifact viewers) matched the plan's design directly with no real bugs found.
    - **M3 (Domain + Architecture + polling) surfaced one real, confirmed frontend bug**, found
      only by actually driving a fresh feature through the browser rather than reading the code:
      `FeatureDetailPage.jsx`'s `pipelineStarted` was computed as
      `Boolean(graphStatus?.next?.length) || allArtifacts.length > 0` — since Requirement/
      Architecture generate real artifacts via their manual `/run` endpoints *without* the graph
      ever being started (the documented hybrid trigger model), the "Start Pipeline" button
      vanished permanently the moment a human ran Requirement, before the graph had ever actually
      started, leaving no way to make Domain auto-trigger after approval. Fixed by deriving
      `pipelineStarted` from `Object.keys(graphStatus.values || {}).length > 0` instead — a
      graph run that's ever been started leaves its input/output keys in `state.values`
      permanently, even after `next` empties out on completion, confirmed directly against a real
      completed feature (Signup) whose graph-status still carries a populated `values` with an
      empty `next`.
    - **M4 (UI/UX stage) surfaced a more fundamental gap**, found by loading the real, live
      QuickCart "Item Management" feature (approved `ui_metadata` but 3 still-pending
      `ui_component_code` artifacts — the exact scenario the plan's own destructive-warning copy
      was written for): `ArtifactRow.jsx` had no approve/reject action at all (only View/Revise),
      and `ApprovalPanel` only ever targets the stage's single gating artifact — meaning
      individual UI/UX components had **no approval path anywhere**, and once `ui_metadata` itself
      was approved, `currentStage` moved past `uiux` entirely, making the components permanently
      unreachable through the main flow. Fixed two ways: (1) `ArtifactRow.jsx` gained inline
      Approve/Request Revision/Reject buttons (reusing `useApprovalMutation` directly) shown
      whenever a `featureId` prop is passed and the artifact is `pending` — `ArtifactList.jsx`
      only passes `featureId` for non-gating rows, since the gating artifact already has the
      bigger `ApprovalPanel` below it; (2) `FeatureDetailPage.jsx` gained a persistent "UI/UX
      components awaiting review" section, always visible regardless of `currentStage`, showing
      any `ui_component_code` artifact still `pending` — verified live: approving one component
      via the new inline button correctly dropped the count from 3 to 2 and the artifact's
      `approval_status` genuinely flipped in the backend. Diagram PNGs (`use_case_diagram`/etc.)
      have this same class of reachability gap once their stage is approved, but — unlike
      components — were never meant to be individually approved (no gate depends on them), so this
      was left as a known, lower-severity, not-fixed limitation rather than scope-creeping into a
      full "browse every artifact regardless of stage" feature nobody asked for.
    - **M5 (Coder Agent stage) surfaced two more real bugs**, found by loading the real, live
      TaskFlow "Task Comments" feature (18 real Coder Agent versions, genuinely still pending —
      this project's actual, already-most-exercised real Coder Agent history):
      1. `currentStage` was computed as `GATED_STAGES.find(stage => stageStatuses[stage] !==
         APPROVED)` — a purely sequential scan. This feature predates Domain Agent becoming a real
         gated stage (item 28), so it has no `enhanced_srs` artifact and never will, even though
         the graph's real position (`graph-status`: `next: ["coder_node"]`) shows Coder is
         genuinely what's pending. The sequential scan got stuck reporting "Domain: not started"
         forever, making the real, pending `code_diff` permanently unreachable. Fixed by
         prioritizing the graph's own ground truth first: `next` names either `"{stage}_node"`
         (actively auto-running) or `"approve_{stage}"` (paused at a human gate) — either way,
         that's definitively the current stage — falling back to the sequential heuristic only
         when `next` gives no signal at all (never started, or fully finished).
      2. `pickViewer()` routed `artifact_type === "code_diff"` straight to `DiffViewer`
         regardless of format — but `code_diff` exists in BOTH formats: markdown is the real merge
         report `DiffViewer` parses (prose + a fenced diff block), while the JSON one is just a
         `{added, modified, deleted}` file-tree summary with no diff text at all. Viewing the JSON
         variant showed its raw JSON as if it were prose, with a permanent "No diff content found"
         underneath. Fixed by making `pickViewer` only special-case `code_diff` when
         `artifact_format === "markdown"`, letting the JSON variant fall through to the normal
         `JsonViewer` path. Verified both live: the JSON variant now renders as a clean collapsible
         tree; the markdown variant correctly shows the merge report prose (verification steps,
         PASSED status, informational placeholder-stub/feature-page-render findings) followed by
         a real diff2html-rendered diff with truncation notice and file stats.
    - **M6 (LLM Settings page)** built the real GET/PUT/test UI (previously a bare placeholder),
      and in doing so **surfaced and fixed a real, live misconfiguration**: the Mongo-backed
      `store.llm_settings.model` (which one-shot agents actually read, distinct from `.env`'s
      `DEFAULT_LLM_MODEL`) was still `qwen3-coder:latest` — leftover from an earlier, since-paused
      testing thread in this same session — silently making every one-shot agent call (this
      session's own M3 verification included) take 5+ minutes instead of under a minute, since
      that model doesn't fit this machine's 6GB VRAM. Used the newly-built page itself to correct
      it back to `llama3:latest`, verified via a real end-to-end test-prompt call (clean response
      in well under a minute) and via `GET /settings/llm` showing the persisted change.
      `AGENTIC_MODEL_OVERRIDE` (Coder Agent's separate tool-calling model) was untouched, per the
      deliberate, already-documented split.
    - **Real, live verification throughout, not synthetic**: every milestone was driven through
      an actual running backend (`uvicorn`, port 8001) and frontend (`vite dev`, port 5174) via
      Playwright (invoked directly through the backend venv's own Playwright install, since no
      Playwright MCP tool was available this session) — screenshots and `page.inner_text`/
      `pageerror`/console-error capture at each step, never just code review. A throwaway
      "Frontend Verify Test" project/feature created for the M3 hybrid-trigger-model check was
      fully cleaned up afterward (Mongo documents deleted directly via `store.<collection>.
      collection.delete_one(...)`, since no DELETE route exists for projects/features; matching
      output directory removed from disk) — confirmed gone from `GET /projects` afterward.
    - `npm run build` (production Vite build) re-run clean after every fix in this item, zero
      errors — only a pre-existing, unrelated bundle-size advisory (single chunk >500kB,
      no code-splitting configured yet).

31. **AutoForge Frontend v2: redesigned from a linear approve-and-advance wizard into an
    interactive multi-agent dashboard**, per direct user feedback with reference screenshots of a
    comparable system (fixed left pipeline nav, center interaction pane, right "Governance"
    panel). Full plan: `C:\Users\ASUS\.claude\plans\soft-petting-star.md` (overwritten since, per
    this file's convention). Six backend additions, all additive/non-breaking:
    - **Per-agent LLM overrides**: `store.llm_settings` gained a nested `agent_overrides:
      {agent_name: {...}}` map (schema: `AgentLLMOverrideUpdateRequest`/`AgentLLMSettingsResponse`
      in `llm_schema.py`). `llm_provider_service.get_provider(agent_name=...)` and
      `agentic_model_factory.get_agentic_chat_model(agent_name=...)` both check this before
      falling back to the global default (the latter falls back to `.env`'s
      `AGENTIC_MODEL_OVERRIDE` **only** for `agent_name == "coder_agent"` specifically -- a real
      bug caught and fixed during this work: that env var was leaking into Architecture Agent's
      own agentic exploration calls whenever Architecture had no override configured, silently
      forcing it onto Coder Agent's model instead of the global default). New routes: `GET/PUT/
      DELETE /settings/llm/agents/{agent_name}`, `POST /settings/llm/agents/{agent_name}/test`.
      Every one-shot agent's `get_provider()` call site updated to pass its own `agent_name`.
    - **A real, serious performance bug found and fixed in the process**: `MongoLLMSettingsProxy`
      re-fetches the **entire** settings document from MongoDB on every single `["field"]` access
      (no per-instance caching at all) -- pre-existing before this session, but the new per-agent
      code multiplied it across 5 agents x ~6 fields, observed taking **5+ seconds** for what
      should be one cheap read (confirmed directly: a real save via the new LLM Settings UI got
      stuck on "Saving..." for 5+ seconds; curl timing confirmed `PUT .../agents/{name}` alone
      took 5.37s). Fixed by adding `MongoLLMSettingsProxy.get_document()` -- one `find_one` call,
      reused as a plain dict everywhere in `llm_provider_service.py`'s new methods and in
      `agentic_model_factory.py` (which had the identical anti-pattern) -- verified down to
      ~0.15-0.22s per call after the fix (curl-timed, ~25-40x faster). **Any future code touching
      `store.llm_settings` for more than one field should use `get_document()` once, never
      `store.llm_settings["x"]` repeatedly in the same call** -- the existing single-field proxy
      interface is fine for genuinely single-field reads/writes (e.g. the pre-existing
      `update_settings()` still writes field-by-field and works fine for its actual usage), but
      silently re-fetching per field is a real trap for anything reading several fields at once.
    - **Conversation-history data**: new `stage_events` Mongo collection (`stage_event_schema.py`,
      `stage_event_service.py`) records every human-initiated `run()`/`revise()` request's
      `human_comment`/`revision_comment` at the API route layer (`agents.py`, right after
      `_validate_feature`, before the try block -- so it's captured even if the agent call itself
      later fails). `ApprovalResponse` gained an optional `feature_id`, and
      `approval_service.list_feature_approvals(feature_id)` joins via **each approval's own
      artifact's feature_id** (not the approval's own new field) specifically so it works for
      approvals made before this field existed too -- confirmed necessary live: every
      historical approval's own `feature_id` was `null`, and the join-based lookup was what made
      them show up at all. New routes: `GET /features/{feature_id}/approvals`, `GET
      /features/{feature_id}/events`.
    - **Downloads**: `GET /artifacts/{id}/download` (raw bytes + `Content-Disposition: attachment`,
      sibling of the existing JSON-wrapped `/content`). `workspace_service.export_zip(project_id,
      ref)` reads a git ref's **committed tree directly** (`repo.commit(ref).tree.traverse()`),
      never checking the ref out first -- safe to call regardless of what's currently checked out
      on disk. `GET /features/{id}/code/download` zips the feature's own branch if it still
      exists (pre-merge, so a reviewer can try the code locally before deciding), else falls back
      to `main`; `GET /projects/{id}/code/download` always zips `main`. Verified for real:
      downloaded zips for both the merged Login feature (22 real files, confirmed no `.git`
      internals) and the still-unmerged Task Comments branch (32 real files) via actual button
      clicks in a real browser, not just curl.
    - **Artifact `size_bytes`** (cosmetic, shown in the new Governance panel): computed from the
      file on disk at every read (`artifact_service._hydrate_artifact_response`), never stored --
      `None` on a missing file rather than raising.
    - Frontend: `FeatureDetailPage.jsx` rebuilt as a three-panel layout (`PipelineNav.jsx` --
      every stage independently clickable regardless of approval status, the direct general fix
      for the prior design's "artifacts become unreachable once a stage is approved" gap;
      `GovernancePanel.jsx` -- Stage Actions/Trace Links/Stage Artifacts; center Interaction/
      Output/Artifacts tabs). `StageInteractionPanel.jsx` merges stage_events + approvals +
      artifact-versions into one real chronological chat-style timeline (not a live
      back-and-forth -- a real activity log presented conversationally), with static per-stage
      suggestion chips (`lib/suggestionChips.js`). New `components/documents/` (`DocumentValue.jsx`
      -- a generic JSON-to-readable-sections/tables renderer; `SrsDocumentViewer.jsx`/
      `ArchitecturePlanDocumentViewer.jsx` -- real formatted-document views for SRS/Enhanced
      SRS/Architecture Plan JSON, wired into `pickViewer`) replace raw JSON dumps for those three
      artifact types specifically, verified against real generated QuickCart data (proper headers,
      tables for functional/non-functional requirements/user stories/traceability, nested
      design_views/implementation_plan sections). `ArtifactContentView.jsx` factored out of
      `ArtifactViewerModal.jsx` so the same viewer-dispatch logic renders both inside the popup
      and inline in the Output tab. Retired `StageActionPanel.jsx`/`PipelineStageTracker.jsx`
      (superseded, deleted as dead code) and the previous session's special-cased "pending UI/UX
      components" banner (superseded by the general per-stage Artifacts tab reachability fix).
    - **Real, live verification throughout** (same methodology as the prior frontend session --
      actual running backend + frontend, Playwright via the backend venv, no synthetic fixtures):
      every milestone screenshotted against real data (Task Comments' 18 real Coder Agent
      versions, QuickCart's real SRS/Architecture Plan, Login's real merge history). Full backend
      suite re-run clean after every milestone (263 passed throughout, same pre-existing
      Docker-dependent exclusions as always). Final 9-page smoke test (project list, 3 project
      detail pages, 5 features at different real pipeline stages, LLM Settings) -- zero page
      errors, zero console errors.

32. **Requirement Agent turned conversational: gap-filling BA instead of a single-shot form-filler.**
    Previously `RequirementAgent.run()` required a fully-formed `RequirementBAInput` in one
    request, silently defaulted anything missing (`_complete_ba_input`), and the human never saw
    the SRS take shape or got asked a clarifying question. Full plan:
    `C:\Users\ASUS\.claude\plans\soft-petting-star.md` (overwritten since, per this file's
    convention). Design considered representing each conversational turn as a versioned
    `SRS_DRAFT` artifact (reusing `artifact_service`'s versioning) -- rejected via an independent
    Plan-agent design review: `get_next_version()` has no locking (a real two-tab race once
    called every turn), it repurposes "version" to mean "turn number" for files no one reviews
    individually, and it would need the frontend's generic artifact list to explicitly hide a new
    pseudo-type. Chosen instead: one new Mongo collection, `requirement_conversations`, one
    document per `feature_id`, upserted in place each turn (same idiom as the pre-existing
    single-document `store.llm_settings`) -- the only shared-service touch this milestone makes.
    - New `app/agents/requirement_agent/conversation_engine.py`: `project_ba_input_to_srs_shape`
      (the core "turn known_answers into full SRS shape" logic, extracted from the existing
      `_build_fallback_srs_json` -- which becomes a thin wrapper appending its own
      failure-reason line, unchanged behavior; the extraction also fixed a real, previously-silent
      gap: `output_requirements`/`validation_rules` being defaulted with **zero** assumption flag,
      and a hardcoded single-FR traceability row that was only ever correct by coincidence when
      exactly one FR existed -- now one row per FR); `run_gap_analysis` (one small LLM call per
      turn -- extract answers, ask at most 3 prioritized questions, same JSON-parse/repair ladder
      as the rest of this agent, falling back to a deterministic rule-based checklist on total
      failure, never a second LLM call). New `app/agents/requirement_agent/conversation_quality_gate.py`
      (mirrors `domain_validator.py`'s idiom): deterministic, no-LLM checks -- functional
      requirements non-empty/concrete, `api_expectations` entries regex-plausible as
      `METHOD /path`, `data_requirements` entries not vague sentences, and (the hard blocker) any
      Tier-1 field auto-assumed rather than answered. Tier system baked into the prompt and code
      (`TIER_1_FIELDS`/`TIER_2`/`TIER_3`): Tier 1 (`functional_requirements`, `api_expectations`,
      `data_requirements`) always asked about if missing, because these are exactly the fields a
      real, confirmed prior failure (item 29's QuickCart Architecture Plan -- duplicate GET-only
      endpoints and single-field pseudo-entities instead of real CRUD/one entity) traced back to.
    - New `RequirementAgent` methods (`run`/`revise` and every existing helper untouched):
      `start_conversation`/`reply_to_conversation`/`get_conversation`/`reset_conversation`/
      `confirm_conversation`. `confirm_conversation` re-validates `known_answers` through
      `RequirementBAInput` and calls the **unmodified** `_complete_ba_input`/
      `_generate_requirement_output`, saving via a new `_save_generated_srs_artifacts` helper
      factored out of `run()`'s existing inline save block (now shared by both) -- this is what
      makes the result compose with the existing `approval_service`/`graph_orchestrator_service`
      gate with zero changes to either: they only ever see a normal `ArtifactType.SRS` artifact.
      The quality gate is re-checked **server-side** inside `confirm_conversation` itself (400 if
      not ready and `override_quality_gate` isn't explicitly set) -- a direct API call cannot
      bypass it just by skipping what the frontend shows; an override's reason is stamped into the
      real SRS's own `assumptions` array so it stays visible to Domain/Architecture Agent and any
      future human reviewer, not just the frontend session that made the call.
    - New routes (fully additive; `/requirement/run` and `/requirement/revise` untouched --
      confirmed via grep these are the only two callers of `requirement_agent.run()`/`.revise()`
      anywhere): `POST/GET .../requirement/conversation/{start,reply,confirm,reset}` +
      `GET .../requirement/conversation`.
    - Frontend: new `RequirementConversationPanel.jsx` replaces `RequirementRunForm` as the
      default view for the `requirement` stage's `ACTION_REQUIRED` state (the old form stays
      reachable via a "Prefer to fill a form manually instead?" link, unchanged). Chat bubbles
      reuse `StageInteractionPanel.jsx`'s existing `TimelineItem` Tailwind classes for visual
      consistency; the live SRS preview reuses `SrsDocumentViewer` directly (no artifact fetch
      needed -- the conversation response already carries the full preview) behind a
      collapsed-by-default "View current SRS draft" toggle. Fixed `TimelineItem`'s ask-bubble
      label ternary (`eventType === "run" ? "Started" : "Revision requested"`, which silently
      mislabeled any third event type) into a label map covering the new
      `clarify_start`/`clarify`/`confirm` event types.
    - **A real, non-obvious layout bug found only by driving this through the actual browser, not
      by reading the code**: the panel was first built with a side-by-side chat+SRS-preview
      two-column layout, copying the pattern that worked for UI/UX's Page Previews earlier this
      session -- but that pattern lived in the wide center Output panel, while this component
      renders inside the narrow (`w-96`) per-stage **Interaction sidebar**. A real screenshot
      showed the quality-gate reasons list collapsed to one character per line -- the inner
      `w-96` SRS-preview column was by itself as wide as the entire available sidebar, squeezing
      the chat column to near-zero width. Fixed by switching to a single-column layout (chat
      stacked above the reply box and quality-gate banner) with the SRS preview behind a
      collapsed-by-default toggle instead of an always-open side pane. Confirmed fixed with a
      fresh screenshot after the rebuild -- clean, fully-readable layout.
    - **A real, separate bug found only by driving a genuine multi-turn conversation against a
      real local LLM, not by unit tests**: the gap-analysis prompt shows the model an empty-string/
      empty-list JSON shape as an example of the `known_answers` structure (e.g.
      `"architectural_style": ""`) -- the same "model anchors on the shown JSON shape" gotcha this
      project has hit before with other agents. A real run had the model echo
      `"architectural_style": ""` back verbatim despite having no real answer for it, which then
      failed `RequirementBAInput`'s validator at confirm time (an empty string is not `None`, so
      it skips the field's normal `MODULAR` default and hits the allowed-values check instead,
      raising). Worse, on a later turn the same clobbering silently overwrote an already-correct
      `target_stack: "MERN"` down to `""`. Fixed by filtering the model's `known_answers` update to
      only non-falsy values before merging (`{k: v for k, v in new_known_answers.items() if v}`) --
      any accidentally-echoed empty placeholder can no longer overwrite or introduce a bad value.
    - Tests: `tests/test_requirement_conversation.py` (new, 12 -- honest default-flagging with no
      false failure-reason text, `_build_fallback_srs_json`'s existing behavior preserved after
      the extraction, per-FR traceability, every individual quality-gate check, and
      `run_gap_analysis`'s question-truncation/known-answer-merge behavior plus its deterministic
      fallback on total parse failure, mocked LLM matching this suite's established
      `patch(".../conversation_engine.llm_provider_service")` idiom). Full suite: **275 passed**
      (up from 263), zero regressions.
    - **Real end-to-end verification, a genuinely new feature, driven through the real HTTP API
      and then the real browser**: created `feature_df7639a2` ("Inventory Reports") on the live
      QuickCart project with a deliberately rough description ("let admins manage inventory
      somehow") -- the real gap-analysis call correctly asked exactly the Tier-1 questions
      (concrete actions, API endpoints, data fields) with zero prompting toward them; after two
      real replies providing concrete CRUD/endpoint/field detail, the quality gate correctly
      turned ready (`auto_assumed_tier1_count: 0`); confirming produced a real SRS v1 (pending
      approval) -- the underlying single-shot SRS-generation LLM call itself failed schema
      validation on this run (a **pre-existing**, already-documented model-quality gotcha,
      unrelated to this milestone) and correctly fell through to the now-shared
      `project_ba_input_to_srs_shape`-based fallback, proving the extraction preserved the
      existing reliability ladder end-to-end under a real failure, not just in fixtures. Also
      created `feature_f9af7982` ("Order Export") specifically to drive the chat UI itself through
      a real browser (not just the API) -- this is the run that surfaced both real bugs above.
      Both features are left in place as real, inspectable verification output, matching this
      project's established convention (not cleaned up as test debris).

33. **Requirement Agent conversation UX pass: chat as the main window, per-question answering
    with placeholders, and live-streamed SRS generation.** Direct follow-up user feedback on
    item 32: the chat needed to be the primary/main window (not squeezed into the narrow
    Interaction sidebar) until an SRS exists, answering 3 questions at once in one combined box
    was frustrating, questions needed example placeholders, and the final SRS generation should
    be visibly live (streaming) rather than a blocking wait then a sudden reveal, with clear
    loaders throughout.
    - **Main window**: `StageOutputPanel.jsx` now renders `RequirementConversationPanel` directly
      as the main Output content for `stage === "requirement"` whenever no SRS artifact exists yet
      (`versions.length === 0`) -- the instant a real SRS is generated, this stage reverts to the
      normal document-view behavior every other stage already has, automatically (no special-case
      code needed for the transition -- it falls out of the existing `versions.length` check).
      Removed from `StageInteractionPanel.jsx`'s narrow sidebar entirely (replaced with a one-line
      pointer to the main panel).
    - **Per-question answering with placeholders**: `GAP_ANALYSIS_SYSTEM_PROMPT` now asks for
      `questions: [{"question", "placeholder_example"}]` instead of plain strings -- the model
      writes a concrete, feature-specific example answer for each question (confirmed real:
      "POST /api/return_requests, GET /api/return_requests" for an API-endpoints question on a
      genuinely new "Return Requests" feature), shown as that question's input placeholder.
      `conversation_engine.py`'s deterministic fallback checklist got matching canned examples.
      `requirement_conversation_schema.py` gained `QuestionWithPlaceholder` +
      `_coerce_questions` (a `field_validator(mode="before")` that wraps a legacy plain string in
      `{"question": s, "placeholder_example": ""}`) so conversation documents saved before this
      change keep working with no migration. Frontend: `QuestionAnswerForm` renders one labeled
      input per open question (not one shared textarea); submitting combines the
      individually-answered questions into a clearly-attributed `Q: ...\nA: ...` block per
      question -- both easier for a human to answer and a cleaner signal for the next
      gap-analysis turn than one run-on paragraph.
    - **Live-streamed SRS generation**: new `RequirementAgent.confirm_conversation_stream`
      (async generator, mirrors `confirm_conversation`'s validation/quality-gate/save logic
      exactly) calls `provider.stream(...)` (already existed on every `BaseLLMProvider`, just
      never wired to an endpoint before) instead of `invoke_agent`, yielding
      `{"type": "token", "text": ...}` events as raw output arrives; only the JSON-repair retry
      and deterministic fallback (rare reliability-ladder paths) stay non-streamed, since there's
      no meaningful "live" content to show while repairing already-malformed output. New route
      `POST .../requirement/conversation/confirm/stream` returns a `StreamingResponse` of
      newline-delimited JSON (deliberately not SSE/EventSource, which can't POST a body) --
      `frontend/src/api/agents.js`'s `confirmRequirementConversationStream` reads it via a plain
      `fetch()` `ReadableStream` reader, calling `onEvent` per parsed line. `LiveGenerationView`
      shows a pulsing "Connecting to Requirement Agent..." spinner before the first token, then
      the raw JSON growing live in a monospace box with a blinking cursor -- confirmed for real
      with a genuine local LLM: the exact SRS JSON text visibly typing in, not a fixed wait
      followed by a sudden reveal. The existing "Start Conversation"/"Send Answers" loaders were
      also made more prominent (an explicit `LoadingSpinner`, not just disabled-button text).
    - **A real, non-obvious race found only by driving this through a genuine local LLM at real
      latency, not by unit tests**: clicking "Confirm anyway" while a reply's own gap-analysis
      call was still in flight read `known_answers` from the database *before* that reply had
      finished saving, silently confirming against stale/empty answers (the generated SRS's
      FR-001 came back as the raw feature description, `_complete_ba_input`'s own fallback,
      because `functional_requirements` genuinely wasn't in `known_answers` yet at the moment
      confirm read it) -- a real, user-reachable defect, not just a test-timing artifact (a real,
      fast-clicking human could trigger the identical race, since the override "Confirm anyway"
      path was never disabled by a pending reply). Fixed by disabling both the ready-path and
      override-path confirm buttons whenever `respond.isPending`, with an explicit
      "Waiting for your last answer to finish processing..." message -- confirmed fixed with a
      clean re-run showing the real per-question answer ("Customer can create a return request
      for a delivered item") correctly reflected in the generated SRS's FR-001.
    - Tests: `tests/test_requirement_conversation.py` gained 2 new tests (`confirm_conversation_
      stream` yields tokens-then-done and saves a real artifact via a real project/feature/
      requirement_conversations fixture with proper Mongo+disk teardown, matching the established
      `feature_with_prior_run`-style pattern in `test_coder_agent_revise.py`; blocks cleanly with
      a single error event when the quality gate isn't ready, never calling `provider.stream` at
      all) plus updated assertions for the existing gap-analysis tests' now-structured question
      shape. Full suite: **277 passed** (up from 275), zero regressions.
    - **Real state**: four more QuickCart features created purely to verify this pass end-to-end
      through a real browser against a real local LLM (`feature_8f5f184f`/`feature_dc1172af`/
      `feature_d6715d99`/`feature_d7c8c638`, all "Return Requests" variants) -- left in place per
      this project's established convention, each showing a different real stage of the flow
      (fresh per-question start, mid-generation live stream, and a fully confirmed SRS with the
      race-condition fix correctly reflected in its FR-001).

34. **Frontend UX pass: edit-and-resubmit for every agent's past comments, a genuinely auto-growing
    chat composer, and the ability to delete an unapproved artifact version.** Direct user request
    (three sub-asks in one message): "User must be able to edit and resubmit the message to each
    agent like chat gpt and claude," the composer "must be dyanmic when user enters a huge message,"
    and "if the user wants to remove some un approved verion of SRS user must be able to do this."
    - **Edit-and-resubmit**: deliberately implemented as "reload the original comment text back
      into the composer, let the human resend it as a new message" rather than a true in-place
      history rewrite, for every agent EXCEPT Requirement's pre-SRS conversation (which already has
      real rewindable state via `known_answers_before` snapshots and keeps its own dedicated
      inline-edit-with-rewind system, untouched). Every other run/revise call is stateless with
      respect to prior comments -- an already-produced artifact really was generated from the
      original text and can't be honestly "un-produced," so rewriting its history would be
      dishonest. `RequirementConversationParts.jsx`'s `PencilIcon` exported; `ChatBubble.jsx` gained
      a hover-reveal Edit button on "ask" bubbles (`group`/`group-hover:opacity-100`) calling a new
      `onEdit(comment)` prop; wired through `ChatPanel.jsx` and `RequirementRevisionChat.jsx` as
      `onEdit={setComment}`.
    - **Auto-growing composer**: the previous heuristic (`rows={Math.min(6, value.split("\n").length)}`)
      only grew on explicit Shift+Enter presses, not on a long soft-wrapped single line.
      `ChatComposerBox.jsx` now measures real `scrollHeight` via a `textareaRef` + `useEffect`
      (`style.height = "auto"` then `scrollHeight`, capped at `MAX_TEXTAREA_HEIGHT_PX = 240` with
      `overflow-y-auto` beyond that) -- confirmed live: a long unbroken sentence grew the box from
      20px to 100px tall with zero manual line breaks.
    - **Delete an unapproved artifact version**: `artifact_service.delete_artifact(artifact_id)` +
      `DELETE /artifacts/{artifact_id}` (204; 400 if approved) + frontend `deleteArtifact`/
      `useDeleteArtifact`/`ArtifactRow.jsx`'s inline Delete -> "Confirm?"/"Cancel" two-step button.
      **A real bug found only by live verification, not by code review**: this codebase's own
      documented convention is that every gating artifact_type saves a JSON+Markdown pair sharing
      ONE version, and the frontend's version list (`dedupeArtifactVersions`) collapses that pair
      into a single displayed row, showing only the stage's preferred format (e.g. `json` for
      `srs`). The first implementation deleted only the ONE artifact_id behind that row -- so
      deleting "SRS v1" only ever deleted the JSON half; the Markdown half silently remained in the
      database and (worse) then became the row's new representative on the next list refresh,
      making the version appear to un-delete itself. Fixed by making `delete_artifact` operate on
      the whole VERSION: it now finds every sibling sharing `(feature_id, artifact_type, version)`
      and deletes all of them together -- confirmed live, deleting one row now removes both
      artifact_ids from the database in one action. **A second, related bug found in the same live
      pass**: the initial fix's approval guard only checked the ONE artifact_id being deleted, not
      its siblings -- calling delete directly on the still-pending Markdown half of an
      already-JSON-approved pair succeeded, orphaning the approved JSON without its Markdown
      sibling (unreachable through the actual UI, since `dedupeArtifactVersions` always shows the
      approved JSON as that row's representative and `ArtifactRow`'s `canDelete` correctly hides
      Delete for it -- but directly reachable via the raw API). Fixed by checking every artifact in
      the whole version group for `APPROVED` status before allowing any of them to be deleted, not
      just the one requested. **Any future logic operating on "one artifact" for a gating
      artifact_type must remember it's really a two-row version-pair** -- this is the second time
      this exact JSON+Markdown pairing convention has caused a real bug from code that only
      considered one half (see item 30's `pickViewer`/`code_diff` gotcha for the first).
    - Also caught, mid-verification, an operational gotcha worth remembering: after editing
      `artifact_service.py`, the already-running `uvicorn` process (started without `--reload`)
      kept serving the OLD code -- the first live delete test "worked" but silently used
      pre-fix behavior, because the backend was never restarted after the edit. **Any backend
      code change made while a test instance is already running needs an explicit restart before
      the next live verification pass**, or the verification is testing stale code.
    - Full backend suite: **277 passed** both before and after the fix (no new unit tests were
      added specifically for `delete_artifact`'s cascade/guard logic -- this was verified live,
      end-to-end, via a real isolated backend/frontend instance and a real browser, not synthetic
      fixtures; a future session adding `tests/test_artifact_delete.py` would be a reasonable
      follow-up to lock this in). `npm run build` clean (only the pre-existing chunk-size
      advisory). Real, live verification: created a throwaway project (`proj_6e968a81`, "RF Verify
      Test") and feature (`feature_00f51c11`, "Verify Feature") on fresh isolated ports (8060/5185),
      drove a real conversation through a real local LLM to a confirmed SRS, requested a real
      revision (confirming both the edit-and-resubmit UI AND the auto-grow textarea in the same
      pass), then exercised delete on both an unapproved version (succeeded, cascaded correctly)
      and an approved one (correctly refused, 400) -- fully cleaned up afterward (project deleted
      via the existing `DELETE /projects/{id}` endpoint, both test processes killed).

35. **Delete confirmation upgraded from inline text to a real popup, and Requirement Agent
    revisions redesigned so a requested edit actually happens.** Two direct user reports: (1) the
    delete-artifact confirm from item 34 should be "through a popup message," not inline
    Confirm/Cancel text; (2) asked the Requirement Agent to remove one specific NFR
    ("Listing page must load within 2 seconds for up to 10,000 items") from an already-generated
    SRS, and the item was still present in the newly generated SRS after revision -- "the agent
    must dynamically address those user needs and performed those requirements/instruction."
    - **Popup**: new `frontend/src/components/common/ConfirmDialog.jsx` (wraps the existing
      `Modal`) -- `ArtifactRow.jsx`'s inline "Delete" -> "Confirm?"/"Cancel" text toggle replaced
      with a real modal (`ConfirmDialog`) naming the exact artifact type + version being deleted.
    - **Root cause of the ignored-removal bug, confirmed by reading the code (same defect class as
      item 29's Domain Agent fix)**: `revise()`/`revise_stream()` asked the LLM to retype the
      ENTIRE SRS JSON verbatim on every revision, changing only what the comment asked for. On
      this local model, that's unreliable -- and critically, the reliability ladder's fallback for
      a totally failed/unparseable LLM call (`_fallback_revise_srs_json`) just **cloned the
      existing SRS unchanged**, silently discarding the human's requested edit with no visible
      error anywhere. Given this project's own extensively-documented local-model JSON reliability
      issues, this fallback path is the prime suspect for what the user hit.
    - **Fix, mirroring item 29's Domain Agent redesign exactly**: the LLM is no longer asked to
      retype the SRS. `REQUIREMENT_REVISION_SYSTEM_PROMPT` (`prompt.py`) now asks for a small
      `{"revision_summary", "operations": [{"action": "remove"|"add"|"modify"|"set", "field",
      "target", "value", ...}]}` plan -- one operation per distinct change, "target" must quote an
      existing id/exact text so it can be matched precisely, and an irrelevant/unmatchable request
      must return an EMPTY operations list plus an honest revision_summary explaining why, never a
      guessed change. New `app/agents/requirement_agent/revision_patcher.py`
      (`apply_revision_operations`) deterministically applies that small plan to the real SRS:
      handles plain-string-list fields (scope, constraints, etc.), `{id, description}`-object-list
      fields (functional_requirements/non_functional_requirements/acceptance_criteria/
      validation_rules, matching by exact text, id, OR substring containment so the LLM can quote
      just the distinctive part of a long requirement), `user_stories`'s own shape, and top-level
      scalar fields -- rebuilding `traceability` afterward if functional_requirements changed.
      Every operation the patcher couldn't confidently match, and the zero-operations case, are
      appended directly to the revised SRS's own `assumptions` array (plus a new
      `revision_metadata.applied_changes`/`unmatched_operations` pair) -- so "the agent silently
      didn't do what I asked" is no longer possible; it either happens or is explicitly said not
      to have happened, visible in the document itself. `agent.py`'s `_revise_srs_json` (used by
      `revise()`) gained the same LLM-call -> JSON-repair-retry -> deterministic-fallback ladder
      shape `revise_stream()` already had (it previously had no repair step at all). The streamed
      raw output during a revision is now the small plan, not the whole document -- updated the
      Result panel's live-view label ("Reviewing your requested change..." instead of
      "Regenerating SRS...") and the revision chat's banner copy to match what's actually
      happening; `revision_summary` stays the first JSON key so the existing chat-bubble streaming
      extraction is unaffected.
    - **Real, live verification, not just synthetic tests**: created a fresh test feature with an
      SRS containing the user's exact NFR text, requested the user's exact revision comment through
      the real streaming endpoint against a real local LLM -- the model produced a correct,
      one-operation plan on the FIRST attempt (no repair, no fallback), and the resulting SRS v2
      genuinely no longer contains that NFR, with `revision_metadata.applied_changes` recording
      exactly what happened. A second real test with a deliberately nonsensical removal request
      ("remove the requirement about time travel and quantum encryption") correctly returned zero
      operations, with both `revision_summary` and a new `assumptions` entry honestly stating
      nothing was changed. Also verified the delete popup live: clicking Delete now opens a real
      modal naming the exact version, Cancel closes it with no request sent, and confirming deletes
      the version (cascading both JSON+Markdown, per item 34's fix) and closes the dialog.
    - New `tests/test_requirement_revision_patcher.py` (10 tests, no LLM -- exact/id/substring
      removal matching, unmatched-removal-is-reported not silently dropped, add/modify for both
      list shapes, user_stories add, traceability rebuild after FR removal, malformed operations
      skipped not raised). Full suite: **287 passed** (up from 277). `npm run build` clean.

36. **Pin which approved SRS version feeds the Domain Agent, instead of always the latest.**
    Direct user request, prompted by seeing two approved SRS versions (v2/v3) in "All Artifacts"
    with no way to control which one the next agent actually uses: "the lastly approved version
    will continue to next agent and mentioned the name of using SRS for the next phase on the
    right side of the result section, top right corner after the preview tab. And add a radio
    button in the approved SRS for the user to select which [version is] going to be use[d]."
    - **Backend**: `FeatureResponse` gained `active_artifact_selection: dict[str, str]` (maps
      `artifact_type -> artifact_id`, e.g. `{"srs": "artifact_..."}`), stored on the feature
      document, defaulting to `{}` for every pre-existing feature (an absent entry means "use the
      default," never an error). New `artifact_service.get_selected_or_latest_approved_artifact
      (feature_id, artifact_type, artifact_format=None)`: returns the pinned artifact if one is
      set AND still valid (belongs to this feature, still that type/format, still APPROVED) --
      otherwise the latest approved version by version number, i.e. **exactly** the same default
      every stage's own private `_find_latest_approved_*` duplicate (Architecture/Domain/UI-UX/
      Coder Agent each have one, confirmed by reading them) already used. A stale/deleted
      selection silently falls through to that default rather than raising -- pinning is a soft
      override, never a way to brick the pipeline if the pinned version later disappears. New
      `artifact_service.set_active_artifact_selection(feature_id, artifact_type, artifact_id)`
      (raises ValueError -> 400 for: unknown feature/artifact, wrong feature, wrong type, or not
      APPROVED -- only an approved version is ever a meaningful choice). New route `PUT
      /features/{feature_id}/artifacts/active-selection`. **Only `DomainAgent.
      _find_latest_approved_srs_artifact` was wired to this** (delegates to the new shared method
      instead of its own private duplicate) -- per the user's explicit scope ("specially to the
      next agent" = Domain Agent reading the SRS). The other three agents' private
      "latest-approved" duplicates are untouched; wiring any of them the same way later is a
      trivial one-line change to `get_selected_or_latest_approved_artifact`, not a new mechanism.
    - **Frontend**: new `frontend/src/lib/activeArtifactSelection.js`'s
      `getEffectiveActiveArtifact(artifacts, activeSelection, artifactType, artifactFormat="json")`
      mirrors the backend's exact default/override logic client-side (no extra round trip) --
      used by both the indicator and the radio button so they can never disagree.
      `OutputPanel.jsx`'s tab bar (previously just the Result/Files/Preview buttons) gained a
      `justify-between` layout and a right-aligned pill per entry in a new
      `NEXT_AGENT_BY_ARTIFACT_TYPE` map (`{srs: "Domain Agent"}` today) reading
      `"Using SRS vN for Domain Agent"` -- exactly the "top right corner after the preview tab"
      placement asked for. `ArtifactRow.jsx` gained a real `<input type="radio">` (grouped by
      `name={"active-" + artifact_type}`) shown only on rows where `showActiveSelector` is true
      AND `approval_status === "approved"` (mirrors the backend's own 400 guard -- the radio
      simply never appears somewhere it would be rejected), plus an "In use" pill on whichever row
      is currently effective. `ResultTab.jsx` computes `effectiveActiveArtifact` via the shared
      helper and passes `activeArtifactType`/`activeArtifactId`/`onSetActive`/`settingActive`
      through `ArtifactList.jsx` to each row; a new `useSetActiveArtifactSelection(featureId)`
      mutation (`useFeatures.js`) writes straight into the `["feature", featureId]` query-cache
      entry on success (same "direct cache write, no refetch" idiom already used elsewhere in
      this codebase for a small, single-document response) so the indicator and every row's
      radio state update immediately, in the same render, with no extra fetch.
    - New `tests/test_artifact_active_selection.py` (5 tests, no LLM/HTTP -- defaults to latest
      when unset, explicit selection overrides the latest-version default, selecting a
      non-approved artifact is refused, selecting an artifact belonging to a different feature is
      refused, a stale/deleted selection falls back to the latest-approved default rather than
      erroring). Full suite: **292 passed** (up from 287).
    - **Real, live verification**: created a fresh test feature, generated and approved SRS v1,
      requested a revision and approved the resulting v2 too (so two real approved versions
      coexisted, reproducing the screenshot that prompted this request) -- confirmed the indicator
      defaulted to "Using SRS v2 for Domain Agent" (the latest, matching prior behavior with zero
      selection made) and v2's row showed the radio checked with an "In use" pill; clicked v1's
      radio button and confirmed, in the same screenshot pass, the indicator updated live to
      "Using SRS v1 for Domain Agent", the checked radio moved to v1's row, and
      `GET /features/{id}` genuinely returned `active_artifact_selection: {"srs":
      "<v1's real artifact_id>"}` -- the persisted backend state matches exactly what the UI
      showed, not just a client-side-only toggle. `npm run build` clean throughout.

37. **SRS approval exclusivity, an approve-confirmation popup that auto-starts Domain Agent and
    auto-switches the chat, and a real (not testing-artifact) fix making edited chat messages
    stream live instead of sitting behind a static spinner.** Two direct user reports in one
    message: (1) "user can only approved only one SRS user can not select multiple SRS verions" --
    reacting to the real state from item 36's verification where v1 AND v2 were BOTH left
    "Approved" simultaneously; (2) "Once the user clicks on the approved button A popup message
    appear confirming to user and starting the domain agent... user clicks okay the domain agent
    chat will start automatically"; and, separately, "When User edit the user message it will not
    appear on the chat box section."
    - **SRS exclusivity** (`approval_service.py`'s `submit_approval`): approving an SRS artifact
      now finds every OTHER `srs`-type artifact for the same feature currently `APPROVED` and
      reverts it to `PENDING`. Scoped narrowly to `ArtifactType.SRS` specifically, not every
      gating type -- UI/UX's `ui_component_code` artifacts are legitimately, independently
      approved several at a time (distinct components, not versions of one document); SRS is a
      singleton document with versions, which is what this rule is actually about.
    - **Approve confirmation + auto-run Domain Agent + auto-switch chat**: new
      `ConfirmDialog.jsx` gained a `tone` prop (`"danger"` red / `"primary"` accent) and a
      `confirmingLabel` prop (previously hardcoded "Deleting...") so the same component now
      serves both delete confirmations and this positive-action one.
      `GovernancePanel.jsx` (not `ApprovalPanel.jsx` -- see the real bug below) owns a
      `confirmingApprove`/`phase` state machine and its own `useApprovalMutation`/`useRunDomain`
      instances: confirming -> approve (supersedes any other approved SRS per the fix above) ->
      `runDomain.mutateAsync({})` (the existing manual-trigger path already wired for the
      composer, per item 30 -- no LangGraph run needs to have been started) -> `selectAgent
      ("domain")`. `OutputPanel.jsx`'s "Using SRS vN for Domain Agent" indicator (item 36) and
      this popup now compose correctly since both read the same exclusivity-respecting state.
    - **A real bug found and fixed mid-verification, not by static reading**: the confirm+run+
      switch sequence was originally written as an async function living INSIDE `ApprovalPanel`
      -- which is unmounted by its own parent the instant the artifact's `approval_status` stops
      being `"pending"` (exactly what happens right after the approval call succeeds, mid-
      sequence). Confirmed directly: a live run's debug logging showed `"approval.mutateAsync
      resolved"` and then NOTHING -- no `runDomain` log, no thrown/caught error, no `selectAgent`
      call -- the async function was silently abandoned the moment its owning component
      unmounted. Fixed by moving the entire confirm-dialog + orchestration up to
      `GovernancePanel.jsx`, which never unmounts across that transition (it only swaps which
      child it renders); `ApprovalPanel.jsx` was simplified back to a dumb component taking an
      optional `onApproveClick(comment)` callback instead of owning any multi-step flow itself.
      **Any future multi-step async sequence triggered from a button inside a conditionally-
      rendered child must live in the nearest ancestor that stays mounted across every state
      transition the sequence itself causes** -- this is the second time this exact class of bug
      has been found in this codebase (see item 34's cascade-delete note for the first, different
      shape of "one artifact_id isn't the whole logical unit" mistake) but a new failure mode
      (component lifetime, not data modeling).
    - **A second real, related bug found in the same verification pass**: `ResultTab.jsx`'s
      `selectedVersion` state didn't reset when `stage` itself changed -- after the auto-switch to
      Domain Agent, if a version NUMBER happened to coincidentally exist for both `srs` and
      `enhanced_srs` (e.g. both have a "v4"), the panel kept showing the OLD stage's document
      under the NEW stage's header, since the existing "does this version still exist" check
      found a coincidental match and never re-picked the new stage's actual latest version. Fixed
      with a new, separate `useEffect` keyed only on `[stage]` that unconditionally resets to
      `versions[0]?.version` on every stage change, leaving the existing "new version arrived for
      the same stage" effect untouched.
    - **A third bug, pre-existing and unrelated to this session's new code, found and fixed along
      the way**: `ResultTab.jsx` always passed `gatingArtifactType={null}` to `ArtifactList`,
      which (per `ArtifactRow.jsx`'s OWN docstring -- "the gating artifact itself already gets the
      bigger ApprovalPanel below it, so callers should omit featureId there") was supposed to hide
      the redundant inline Approve/Reject on the ONE row that already has the bigger
      Governance-panel controls. Since it was always `null`, EVERY row (including the gating one)
      showed BOTH controls -- meaning the SRS's Approve button had two live copies, only one of
      which (Governance's) went through the new confirmation flow; the other (the inline one)
      still approved immediately with no popup, no exclusivity awareness at the UI level (the
      backend-level exclusivity fix still applied either way, but the human-facing confirmation
      could be silently bypassed). Fixed by passing the stage's real gating type
      (`STAGE_GATING_ARTIFACT[stage]?.type`) instead of a hardcoded `null`.
    - **The "edit message doesn't appear" report: extensively investigated, and NOT a bug in the
      edit-and-resubmit or edit-and-regenerate mechanisms themselves** -- both were verified live,
      multiple times, to work correctly: `RequirementRevisionChat`'s hover-edit-reload-into-
      composer-resubmit flow (item 34's pattern) and `RequirementConversationChat`'s true inline
      edit-with-rewind flow (`HumanBubble`, pre-existing, kept unchanged per item 34's own
      design note) both correctly save the edit and refresh the display -- confirmed via direct
      backend inspection after each. **The real, confirmed gap**: unlike every other reply-shaped
      action in this conversation (normal replies, revisions, confirms), editing a turn used a
      plain, non-streaming call -- the edited message sat behind only a spinner for however long
      the real LLM call took (which, on this local model, is routinely 30s-several minutes,
      already extensively documented elsewhere in this file). A human watching a static spinner
      for that long, with zero visible progress, would very reasonably conclude "this isn't
      working" -- exactly the perceived-breakage this session has repeatedly fixed for OTHER
      flows by making them stream (see items 32/33). Fixed by adding the same treatment here:
      new `RequirementAgent.edit_turn_reply_stream` (mirrors `reply_to_conversation_stream`
      exactly -- same token/error/done event shape, same repair-then-deterministic-checklist
      ladder, same rewind-via-`known_answers_before`/`existing_turns_override` logic as the
      existing non-streaming `edit_turn_reply`), new route `POST .../conversation/turns/
      {turn_index}/edit/stream`. Frontend: `RequirementConversationChat.jsx` gained an
      `editingContext` state (`{turnIndex, pendingReply}`) so the turn being edited shows its new
      text immediately plus a live `LiveReactionBubble` (reusing the exact component normal
      replies already use), while every turn AFTER it is hidden outright during the stream
      (they're about to be discarded by the rewind anyway, so showing them only to yank them away
      once the stream lands would be its own small "did that just disappear?" moment). The
      now-fully-superseded non-streaming frontend path (`useEditRequirementConversationTurn`,
      `editRequirementConversationTurn` API function) was removed outright, matching this
      session's established precedent for a mutation once nothing calls it anymore -- the backend's
      plain route is untouched for direct API callers.
    - **A real, separate infra gotcha re-confirmed hard during this verification (already
      documented for a different endpoint earlier in this file, but worth restating since it cost
      real time here too)**: the isolated test backend process was started BEFORE the new
      `/edit/stream` route was added to the source, and since it runs without `--reload`, every
      request to that route 404'd -- confirmed directly via a raw `curl` bypassing the frontend
      entirely, which is what made this diagnosable in under a minute once tried. **Any backend
      route added mid-session to an already-running test instance needs an explicit process
      restart before it can be exercised** -- this has now caused real, multi-minute confusion at
      least twice in this file's history.
    - **A second real testing-methodology lesson, specific to Playwright + streaming fetch
      responses**: `browser.close()` immediately after taking a screenshot silently aborts any
      still-in-flight `fetch()` request the page had open -- including this exact streaming edit
      call, which on `qwen3-coder:latest` can genuinely take minutes. Several verification
      attempts appeared to "fail" (backend never saved the edit) purely because the test script
      closed the browser before the real, slow LLM call had actually finished -- not a product
      bug. The only way to get a trustworthy verdict was `page.expect_response(...)` wrapped
      around the triggering click, with a long timeout, keeping the browser open until the real
      HTTP response object itself resolved -- confirmed a genuine 200 with the full NDJSON body,
      and confirmed the backend's saved turn matched the edited text afterward. **Any future
      verification of a slow, real-LLM-backed streaming call must wait on the actual response
      object (or an equivalent hard signal), never a fixed timeout or a DOM-text heuristic that
      can match an optimistic bubble before the real work finishes.**
    - New backend tests: `tests/test_approval_srs_exclusivity.py` (3 -- approving a new version
      supersedes the old one, reject/revision-request never touches siblings, exclusivity never
      bleeds into unrelated artifact_types like `ui_component_code`);
      `tests/test_requirement_conversation.py` gained 2 (`edit_turn_reply_stream` yields
      tokens-then-done with the new reply correctly saved and the old turn's stale data replaced;
      errors cleanly on an unknown turn index). Full suite: **297 passed** (up from 292).
      `npm run build` clean throughout.
    - **Real, live verification for every piece**: created a fresh feature, generated and
      approved SRS v1 through the real popup, then revised+approved v2 through v6 in sequence,
      confirming at each step that only the just-approved version stayed "Approved" and every
      other version reverted to "Pending" (real, persisted `GET /features/{id}/artifacts` checks,
      not just UI screenshots) -- and that the "Using SRS vN for Domain Agent" indicator, the
      per-row radio, and the actual `enhanced_srs` content Domain Agent produced (verified by
      reading its `revision_metadata.revision_comment` directly) all agreed on which version was
      current, every time. Separately verified the streaming edit fix with a genuine multi-minute
      real LLM call, confirmed complete via the real HTTP response object, with the backend's
      saved turn matching exactly what was typed. All test projects/processes cleaned up
      afterward.

38. **Added a delete-feature capability (previously didn't exist at all -- only whole-project
    delete did) and used it to remove a real feature per direct user request**: "Remove Item
    listing page feature in the Retail store project." Confirmed via the real, running main
    backend (port 8000, `--reload`) that no delete-feature route/service/UI existed anywhere --
    `delete_project` (`app/api/routes/projects.py`) was the only precedent. New
    `DELETE /features/{feature_id}` (`app/api/routes/features.py`, same file/route-body style as
    `delete_project`, not a separate service layer) cascades this ONE feature's artifacts,
    approvals (joined by both `feature_id` and `artifact_id` since older approval records predate
    the `feature_id` field, matching `list_feature_approvals`'s own established join logic),
    stage_events, and requirement_conversations record -- deliberately narrower than
    `delete_project`: never touches the project's knowledge documents or the whole workspace repo,
    since sibling features in the same project may still need those. Best-effort discards this
    feature's own git branch via the pre-existing `workspace_service.discard_feature_branch`, but
    ONLY when `(repo_path / ".git").exists()` first -- `discard_feature_branch` internally calls
    `ensure_project_repo`, which CREATES a workspace as a side effect if none exists yet; without
    this guard, deleting a feature that never advanced past Requirement (never had a workspace to
    begin with) would spuriously create one just to find nothing to discard in it.
    - Frontend: `deleteFeature`/`useDeleteFeature(projectId)` (mirrors `useDeleteProject`'s exact
      shape). `FeatureListItem.jsx`'s outer element changed from a single `<button>` to a `<div>`
      wrapping the existing select-button plus a new hover-reveal `&times;` delete button
      (can't nest a `<button>` inside another `<button>` -- invalid HTML, hence the wrapper div).
      `FeatureListPanel.jsx` owns a `deletingFeature` state + a `ConfirmDialog` (item 37's
      component); confirming deletes, then navigates to the bare `/projects/{projectId}` route
      (clearing the URL's `featureId`) if the deleted feature was the currently-selected one, so
      `ProjectWorkspacePage` recomputes `effectiveFeatureId` from whatever features remain instead
      of pointing at a feature that no longer exists.
    - New `tests/test_feature_deletion.py` (3 -- deleting one feature removes everything scoped to
      it; a sibling feature and ITS artifacts are completely untouched; deleting an unknown
      feature_id 404s). Full suite: **300 passed** (up from 297). `npm run build` clean.
    - **Real state change, not test debris**: confirmed the target via the real, live main backend
      (`GET /projects` -> `proj_61b14680` "Retails store" -> its one feature,
      `feature_06e647d2` "Item listing page", `in_progress`, 6 SRS artifacts across v2-v4 with two
      simultaneously "approved" -- itself a live example of item 36's since-fixed exclusivity gap,
      predating that fix reaching this long-running `--reload` process's already-loaded state).
      Confirmed the new route was live on this exact process without a manual restart (uvicorn's
      `--reload` picked up the new route from the file edit automatically) before calling
      `DELETE /features/feature_06e647d2` for real. Verified fully gone afterward: the project's
      feature list is now empty, and both `GET /features/feature_06e647d2` and its `/artifacts`
      sub-resource return 404. The "Retails store" project itself, and every other real project in
      this same database, were not touched.

39. **Fixed a real, reported gating-artifact-resolution bug: rejecting the newest SRS version made
    the whole feature show "Rejected" even though an OLDER version was still genuinely pending,
    and there was NO way through the UI to approve that older version at all.** Direct user
    report with a screenshot: rejected SRS v2 while v1 sat at `approval_status: "pending"`; the
    feature list showed "Item listing page ... Requirement [Rejected]", and nothing in the UI let
    them approve v1. Explicit ask: rejecting/deleting one version must never make the whole
    feature show rejected/deleted as long as another version is still pending a decision, and the
    human must be able to select and approve WHICHEVER version they want, not just be stuck with
    "the latest."
    - **Root cause** (`frontend/src/lib/deriveStageStatus.js`): `latestArtifactOfType` picked the
      gating artifact strictly by highest `version` number, with zero regard for
      `approval_status`. Both `deriveStageStatus` (feeds the sidebar's status badge) and
      `getLatestGatingArtifact` (fed `GovernancePanel`'s single `ApprovalPanel`, i.e. the ONLY
      place with Approve/Reject/Request-Revision buttons for the gating type) used this same
      strictly-latest pick -- for `[v1: pending, v2: rejected]`, both always resolved to v2,
      regardless of v1's genuinely-actionable state.
    - **Fix**: replaced `latestArtifactOfType` with `resolveGatingArtifact(artifacts, type,
      format)` -- APPROVED wins if any version is (highest-versioned one, defensively, since the
      exclusivity rule from item 37 means there should only ever be one) -- else the
      highest-versioned still-PENDING/REVISION_REQUESTED version (a real decision still waiting,
      regardless of whether some OTHER, newer version was rejected) -- else the highest-versioned
      version overall (every version decided on and rejected -- correctly reported as rejected)
      -- else `null`. `deriveStageStatus` and the renamed `getOperativeGatingArtifact` (renamed
      from `getLatestGatingArtifact` since it deliberately no longer always returns the latest)
      both use this. Deleting a version needs no special-casing at all -- it just disappears from
      the `artifacts` array the resolver already operates over, so the precedence naturally
      re-resolves to whatever's left (exactly satisfying the "deleted" half of the report with
      zero extra code).
    - **The second half of the fix -- letting the human pick ANY pending version, not just the
      resolved "operative" one**: `ArtifactRow.jsx`'s existing per-row inline Approve/Reject/
      Request-Revision (already built for non-gating artifacts like individual UI/UX components)
      was being suppressed on EVERY row of a gating type, because `ArtifactList.jsx`'s `isGating`
      check compared by `artifact_type` alone -- with the type-only comparison, ALL versions of
      `srs` counted as "the gating one," hiding inline controls everywhere and leaving anything
      other than whatever `GovernancePanel` happened to show with literally no approval path.
      Fixed by adding a new `gatingArtifactId` prop (the exact operative artifact_id, not just
      the type) -- inline controls are now suppressed ONLY on that one specific row (avoiding a
      redundant duplicate with `GovernancePanel`'s bigger panel), while every OTHER pending
      version of the same type gets its own fully-functional inline Approve/Reject/Request-
      Revision, confirmed live with a genuine two-simultaneously-pending-versions scenario.
    - **Kept the item-37 SRS confirm-and-auto-run-Domain-Agent UX consistent across both entry
      points**: the confirm-dialog + approve + `runDomain` + `selectAgent("domain")` orchestration
      (previously living in `GovernancePanel.jsx`, per item 37's own unmount-safety fix) was
      lifted one level further up, to `ResultTab.jsx` -- the actual shared ancestor of BOTH
      `GovernancePanel` (the operative row's approval) AND `ArtifactList`/`ArtifactRow` (every
      other pending row's inline approval). Both now call the same
      `requestSrsApproveConfirmation(artifactId)` callback via a new `onApproveClick` prop
      threaded through `GovernancePanel`->`ApprovalPanel` and `ArtifactList`->`ArtifactRow`
      respectively, so clicking Approve on ANY pending SRS row -- the operative one or not --
      shows the identical confirmation dialog (correctly naming whichever version was actually
      clicked) and triggers the identical approve-exclusivity + auto-Domain-Agent-run + auto-
      chat-switch sequence. `GovernancePanel.jsx` and `ArtifactRow.jsx` themselves no longer own
      any multi-step async state -- both are back to being plain components that either call
      their own immediate mutation or defer to a parent-supplied callback.
    - No backend changes were needed at all -- confirmed by re-reading `submit_approval` that
      rejection already has zero effect on sibling versions (only approval's exclusivity rule,
      from item 37, touches siblings), so this was purely a frontend derivation bug.
    - **Real, live verification, reproducing the exact reported screenshot scenario**: created a
      fresh feature, generated SRS v1, revised to v2, and rejected v2's JSON artifact directly
      (matching the user's exact repro) -- confirmed the sidebar now shows "Awaiting review" (not
      "Rejected"), `GovernancePanel` now shows "Awaiting your review (v1)" (not v2), and clicking
      Approve there shows a dialog correctly reading "Approving v1..." Completed the full flow for
      real (real approval, real Domain Agent run, real auto-switch) and confirmed the top-right
      indicator read "Using SRS v1 for Domain Agent" afterward -- the whole pipeline genuinely used
      the human-approved v1, not the rejected v2. Separately verified the "multiple simultaneously
      pending versions" case on a second feature (v1 pending, v2 pending, neither rejected): v2 (the
      resolved "operative" one) correctly has no inline controls (GovernancePanel already covers
      it), while v1 correctly has its own live Approve/Reject/Request-Revision, and clicking its
      Approve button opens a dialog correctly reading "Approving v1..." -- confirming a human can
      genuinely choose either version, not just whichever one the resolver happens to prefer.
      `npm run build` clean throughout; no frontend test framework exists in this repo (no
      vitest/jest configured), so this was verified live rather than with unit tests, matching
      this session's established practice for pure frontend-logic changes. Test project and
      processes cleaned up afterward.

40. **Follow-up to item 39 (same session, same reported flow): item 39's fix only made the
    STATUS badge version-aware -- it did NOT make every pending version individually approvable.
    A second screenshot ([v1: pending, v2: rejected, v3: pending]) showed v1 alone had inline
    Approve/Reject/Request-Revision, v3 had none at all** -- direct quote: "currently system
    allow user to choose only one user can not selecte one among multiple versions... if user
    approved other versions should be automatically disabled." Root cause: item 39's own fix
    still suppressed inline controls on whichever ONE row `getOperativeGatingArtifact` resolved
    to (to avoid a literal duplicate with `GovernancePanel`'s panel) -- so exactly one pending
    version (not necessarily the one the human wants) kept its buttons, and every OTHER pending
    version of the same type still had none. Two-part fix:
    - **Removed the per-row suppression entirely** (`ArtifactList.jsx`): every pending/rejected
      version of every artifact_type now gets its own inline Approve/Reject/Request-Revision,
      full stop -- no row is ever hidden in favor of a "operative" one anymore. Accepted a small,
      deliberate redundancy as the trade-off: the one row `GovernancePanel`'s dedicated
      `ApprovalPanel` also shows now displays approval controls in two places (inline in "All
      Artifacts" AND in the "Governance" section below) -- harmless duplication, not a
      functional bug, and simpler/safer than the alternative of removing `GovernancePanel`'s
      panel entirely (which would also need to relocate its `APPROVAL_WARNINGS` -- the uiux/coder
      merge-risk warnings -- somewhere else, out of scope for this fix).
    - **New `approveLocked` behavior**, directly per the user's explicit "automatically disabled"
      wording: `ArtifactList.jsx` computes, per row, whether a SIBLING of the same artifact_type
      is already `approved`; if so, that row's Approve button (only Approve -- Reject/Request
      Revision stay active, e.g. to formally clear out an old unused version) is disabled with a
      title explaining why. Switching which version is approved still works -- it just requires
      explicitly rejecting the current approval first (a deliberate, safer two-step flow instead
      of letting a stray click on a different row silently re-trigger the whole approve + auto-
      run-Domain-Agent + auto-switch-chat sequence from item 37/39).
    - `ResultTab.jsx`/`ArtifactRow.jsx` updated accordingly (dropped the now-unused
      `gatingArtifactId` prop and its suppression logic entirely; `ArtifactRow` gained the
      `approveLocked` prop). No backend changes.
    - **Real, live verification, reproducing the EXACT second screenshot**: recreated
      `[v1: pending, v2: rejected, v3: pending]` on a fresh feature -- confirmed both v1 AND v3
      now show independent, fully-functional Approve/Reject/Request-Revision (v2, rejected,
      correctly shows none). Approved v1 specifically (not v3, the "operative" one) through the
      confirm dialog -- confirmed it read "Approving v1..." and, after completion, the top-right
      indicator correctly read "Using SRS v1 for Domain Agent" and the chat auto-switched to
      Domain Agent, proving genuinely free selection. Reloaded fresh and confirmed v3's Approve
      button is now `disabled` with the exact expected tooltip ("Another version is already
      approved -- reject it first to approve a different one"), while v1 shows "Approved"/"In
      use" with its own radio button. `npm run build` clean; verified live only (no frontend
      test framework in this repo, matching item 39's own note). Test project/processes cleaned
      up afterward.

41. **Domain Agent ran blind immediately on SRS approval, before the human ever got a chance to
    guide it** -- direct user report: "Once the user approved SRS... domain will carry a new chat
    that is specific only for domain agent... Once user directed/went to the domain agent chat
    domain agent must ask from user to improve the SRS by existing domain knowledge or user have
    somthing explicitly added to the SRS like Data base schema... If user have something user can
    prompt to the domain agent and get the result." Root cause: `ResultTab.jsx`'s SRS-approve
    orchestration (from item 37/39) called `useRunDomain(featureId).mutateAsync({})` -- an empty
    `human_comment` -- immediately after approval, before switching the chat to Domain Agent, so
    by the time the human arrived at Domain's chat the run had already happened; their only
    remaining option was to *revise* already-generated output instead of guiding the *original*
    generation. Confirmed via investigation that `human_comment` (advisory prompt context) and
    `referenced_document_ids` (guaranteed-inclusion pinned knowledge-document chunks) are both
    genuinely wired into Domain Agent's real behavior already (`agent.py`'s
    `_retrieve_domain_knowledge`/`_retrieve_domain_knowledge_for_revision`, capped at
    `MAX_CHUNKS_PER_PINNED_DOCUMENT`/`MAX_TOTAL_PINNED_CHUNKS`/`MAX_TOTAL_RETRIEVED_CHUNKS`) --
    this was a pure frontend sequencing bug, not a missing backend capability. Fix, frontend-only:
    - **`ResultTab.jsx`**: removed the automatic `runDomain.mutateAsync({})` call and its
      `approvalPhase` state machine entirely. `handleConfirmedSrsApprove` now only approves the
      SRS and calls `selectAgent("domain")` -- it no longer runs Domain Agent itself.
    - **`ChatPanel.jsx`**: replaced the old static "Domain Agent runs automatically..." helper
      text (shown when `!hasOutput && selectedAgent === "domain"`) with an actual proactive
      prompt: asks the human whether Domain Agent should enrich the SRS using existing domain
      knowledge alone or whether they have something specific to add (schema, compliance rule,
      business constraint), plus a "Just use domain knowledge" button that calls
      `runDomain.mutate({})` directly (the same empty-comment call that used to run
      automatically, now only on explicit request) for humans with nothing to add. The composer's
      placeholder for domain (when no output yet) now reads "e.g. Here's our database schema:
      ... (or leave blank and use the button above)" instead of a generic prompt. Pre-existing
      `SUGGESTION_CHIPS["domain"]` and the pre-existing `/`-mention document picker (see the
      Domain Knowledge upload feature, if landed) render alongside unchanged -- both were already
      gated on `canCompose`, which is unaffected by this fix.
    - No backend changes -- `/domain/run`'s `human_comment`/`referenced_document_ids` handling
      was already correct; this only fixed *when* and *with what* the frontend calls it.
    - **Real, live verification** across three fresh features (isolated backend/frontend
      instances, real LLM calls, no mocks): approved an SRS on each and confirmed Domain Agent did
      **not** auto-run (sidebar showed "Domain -- Not started", Result panel showed "No output yet
      for this stage") and the new proactive prompt rendered with the exact expected copy. Path 1
      (typed comment): submitted "Here is our database schema: items table has fields id, name,
      price, stock, quantity" as the human's first message to Domain Agent (confirmed, via a
      fully-instrumented Playwright session kept open across the approve -> type -> submit
      sequence, that the composer placeholder and the eventual request both correctly targeted
      `/domain/run`, not a misrouted `/requirement/revise/stream`) -- the run completed with a
      real domain-cited requirement in the resulting Enhanced SRS (`FR-DOM-001`, citing
      `product_catalog_and_inventory.txt`), confirming the human's turn-taking genuinely happens
      before generation, not after. Path 2 ("Just use domain knowledge" button): clicked the
      button on a separate fresh feature (via the composer's `PillDropdown`-based agent pill, not
      a native `<select>` -- see `AgentSelect.jsx`/`PillDropdown.jsx`), confirmed it fired
      `POST /agents/domain/run` with an empty comment and, polling until completion, produced real
      Enhanced SRS / Domain Improvements artifacts identical in shape to the pre-fix auto-run
      behavior -- so humans with nothing to add lose zero functionality, they just now have to
      make one click instead of it happening for them. `npm run build` clean; backend pytest
      suite 338 passed (11 failed + 3 errored, all pre-existing Docker-sandbox-dependent
      `test_coder_tools.py`/`test_coder_verify.py`/`test_render_checker.py` tests failing because
      no Docker daemon is reachable in this environment -- confirmed via the exact failure message
      "Sandbox unavailable: could not reach Docker daemon," unrelated to this fix, which touched
      no coder/sandbox code). No frontend test framework exists in this repo, matching every prior
      item's own note. Test project (`proj_217ffa15`, three features) and isolated
      backend/frontend processes cleaned up afterward.

42. **Every agent's chat showed every OTHER agent's activity too, not just its own -- and
    Domain Improvements was asked to be approved as its own artifact even though it was never a
    real decision point.** Direct user report, two parts in one message: "Each agent must keep
    it's own chat as an example when moving from requirement agent to domain agent, requirement
    agent chat can not be carried to the domain agent... this mechanism should be applied for
    every agent. And do not ask from user to approve Domain improvements artifact. user can only
    see this document attached with enhanced SRS version."
    - **Part 1 root cause**: `buildAgentTimeline.js`'s own docstring said the quiet part out loud
      -- it deliberately built "ONE continuous chronological feed across every agent for the
      whole feature" and `ChatPanel.jsx` rendered that entire feed unfiltered
      (`timeline.map(...)`) regardless of `selectedAgent`. So switching the chat to Domain Agent
      didn't just switch which messages were highlighted -- it kept showing Requirement's (and
      every other stage's) asks/responses/decisions mixed into the same feed. `RequirementRevisionChat`
      (Requirement's post-SRS chat) received the identical unfiltered `timeline` prop and had the
      same bug in the other direction.
    - **Fix**: `buildAgentTimeline(stage, allArtifacts, allApprovals, allEvents)` now takes the
      stage as its first argument and filters all three sources (events, artifact-version groups,
      approvals) down to that one stage from the start, not after the fact -- matching what its
      name always implied. `ChatPanel.jsx`'s one call site now passes `selectedAgent`. Since
      `RequirementRevisionChat` only ever renders when `selectedAgent === "requirement"`, and it
      receives the same now-scoped `timeline` variable, it's fixed for free. Generic across every
      stage (requirement/domain/architecture/uiux/coder) by construction -- one function, one call
      site, parameterized by stage, not a Domain-specific patch -- satisfying "this mechanism
      should be applied for every agent" without needing separate code paths per agent.
    - **Part 2 root cause**: `domain_improvements` is Domain Agent's own "what changed and why"
      side-record, saved at the same version as its Enhanced SRS
      (`domain_agent.py`'s `_save_domain_artifacts`) but never the type any stage actually gates
      on (`STAGE_GATING_ARTIFACT` only ever points at `enhanced_srs` for the domain stage;
      confirmed via grep that no backend service reads `domain_improvements`' approval_status at
      all). It still got saved with `approval_status: "pending"` like every artifact
      (`artifact_service`'s generic default) and, after item 40's fix removed per-row approval
      suppression for every artifact_type, started showing up as its OWN row in "All Artifacts"
      with its own real Approve/Reject/Request-Revision controls -- asking the human to approve a
      document that was never a real decision point, on top of the Enhanced SRS itself.
    - **Fix, `ResultTab.jsx`**: new `UNLISTED_ARTIFACT_TYPES = ["domain_improvements"]` excludes it
      from `stageArtifacts` entirely (no row, no approval controls, ever). Its content is instead
      rendered as a read-only attachment directly under the Enhanced SRS document view for the
      SAME version (found via `allArtifacts.find(a => a.artifact_type === "domain_improvements"
      && a.version === artifact.version)`, reusing the existing `ArtifactContentView` +
      `DomainImprovementsViewer` pair unchanged) -- exactly "attached with enhanced SRS version,"
      per the user's own wording. No backend changes -- this was purely a frontend listing/gating
      bug, the backend never treated it as a gate to begin with.
    - **Real, live verification** on a fresh feature (isolated backend/frontend instances, real
      requirement run -> approve -> domain run with a distinctive marker comment
      "DOMAIN_ONLY_MARKER: ..."): confirmed Requirement Agent's chat shows only its own
      Started/Produced SRS/Approved bubbles with zero trace of the marker; confirmed Domain
      Agent's chat shows only its own Started (with the marker)/Produced Enhanced SRS bubbles with
      zero trace of "Produced SRS" (Requirement's own response bubble). Confirmed "All Artifacts"
      for the domain stage lists exactly one row ("Enhanced SRS v1 -- Pending" with its own
      Approve/Request Revision/Reject) and no "Domain Improvements" row at all. Confirmed, by
      scrolling the Enhanced SRS document view, that a "Domain Improvements" section (heading,
      summary, additions/modifications) renders directly beneath the Enhanced SRS content with no
      approval controls anywhere near it, while the single "Awaiting your review" governance panel
      below still correctly gates only the Enhanced SRS. `npm run build` clean; no backend changes
      so the pytest suite is unaffected by this item. No frontend test framework exists in this
      repo, matching every prior item's own note. Test project/feature and isolated
      backend/frontend processes cleaned up afterward.

43. **Editing a chat message loaded it into the composer instead of editing it in place, and no
    message (user or agent) had a copy-to-clipboard affordance.** Direct user report: "When user
    editing the message, once the user clicks on the message edit button the message appear on
    the chat input field, It should not happen. When user wants do edit the message user must be
    able to edit the message/prompt on the massage and not on the input field, same as chat gpt
    or claude message edit system. And user must be able to copy the user message and the agent
    message as well. add copy icon to user prompt/messssage and evry agent prompt/messages."
    - **Edit root cause**: `ChatBubble.jsx` (used by `ChatPanel.jsx`'s generic per-agent chat for
      every stage except Requirement pre-SRS, and by `RequirementRevisionChat.jsx` for
      Requirement's post-SRS revise chat) implemented its "Edit" affordance as `onEdit={setComment}`
      -- clicking it copied the old message's text into the BOTTOM composer box, requiring the
      human to leave the message, notice the composer now had text in it, and hit Send again. This
      is not what "edit the message" means in ChatGPT/Claude -- confirmed by contrast with
      `RequirementConversationParts.jsx`'s `HumanBubble` (Requirement's pre-SRS chat only), which
      already did TRUE inline editing correctly (hover reveals a pencil, clicking it swaps the
      bubble in place for a textarea with Cancel/Save controls) -- that component was already
      correct and needed no changes.
    - **Fix**: `ChatBubble.jsx` rewritten to use the exact same in-place-swap pattern as
      `HumanBubble` for its "ask" bubbles -- clicking Edit swaps that one bubble for an inline
      textarea (seeded with the original text) with Cancel / "Save & Send" buttons directly
      beneath it; the composer at the bottom is never touched. New prop `onEditSubmit(text)`
      replaces `onEdit` -- since this app has no backend "rewind and regenerate" for run/revise
      artifacts (they're immutable once produced, unlike Requirement's pre-SRS conversation, which
      really does discard-and-regenerate via `edit_turn_reply`), Save still resubmits the edited
      text as the next message (same mutation the composer's Send already uses) -- just triggered
      from the message itself instead of a round-trip through the composer. `ChatPanel.jsx` and
      `RequirementRevisionChat.jsx` both factored their submit logic into a shared
      `submitAgentMessage`/`submitRevision` function used by both the composer's Send and the new
      `onEditSubmit`.
    - **Copy root cause**: no chat message anywhere had a copy-to-clipboard control at all.
    - **Fix**: new shared `frontend/src/components/common/CopyButton.jsx` (hover-reveal, matching
      the existing Edit affordance's convention, `navigator.clipboard.writeText` with a checkmark
      + "Copied" swap for ~1.5s on success). Wired onto every user AND agent message bubble across
      every chat: `ChatBubble.jsx`'s "ask" (user) and "response" (agent, copies the "Produced X
      (vN)" text) bubbles; `RequirementConversationParts.jsx`'s `HumanBubble` (user) and
      `AgentTurnBubble` (agent, copies the reaction text + any questions asked). Decision bubbles
      (the small centered "Approved"/"Rejected" pills) deliberately excluded -- they're status
      indicators, not prompts/messages, per the user's own two named categories. `AgentTurnBubble`
      and `ChatBubble`'s response bubble needed a `group` class added to their wrapper (previously
      absent -- only ask/HumanBubble had one, for the pre-existing Edit affordance) so the
      hover-reveal mechanism has something to key off of.
    - **Real, live verification** (isolated backend/frontend, real LLM calls, clipboard
      permissions explicitly granted in the Playwright context to actually confirm the copied
      bytes, not just that a button exists): on the pre-SRS conversation, clicked Edit on a real
      `HumanBubble` and confirmed the bottom composer's value was unchanged (empty) throughout;
      clicked Copy on both a `HumanBubble` and an `AgentTurnBubble` and read the clipboard back via
      `navigator.clipboard.readText()`, confirming it exactly matched the visible message text in
      both cases. On Domain Agent's chat (a real `ChatBubble` ask/response pair, produced via a
      real requirement-run -> approve -> domain-run with a distinctive comment), clicked Edit on
      the ask bubble and confirmed: an inline textarea appeared seeded with the exact original
      comment, the bottom composer's value stayed empty the whole time, and Cancel discarded the
      edit without sending anything. Clicked Copy on both the ask and response bubbles and
      confirmed the clipboard held the exact comment text and the exact "Produced Enhanced SRS,
      Domain Improvements (v1)" text respectively. `npm run build` clean; no backend changes so
      the pytest suite is unaffected. No frontend test framework exists in this repo, matching
      every prior item's own note. Test project/feature and isolated backend/frontend processes
      cleaned up afterward.

44. **Refreshing the browser reset the visible chat back to Requirement Agent -- read as "the
    other agent's chat history disappeared" -- and no agent's chat could be stopped mid-generation.**
    Direct user report: "Currently the chat histroy od each agent will dissepear when the user
    refreseh the browser it can not happen like that. The chat history of each agent must remain
    same. And each agent chat can be paused by the user like chat gpt or claude."
    - **Refresh root cause**: every agent's chat data was always durably persisted server-side
      (`stage_events`/`artifacts`/`approvals` for Domain/Architecture/UIUX/Coder and Requirement's
      post-SRS revise; the `requirement_conversations` record for Requirement's pre-SRS
      conversation) -- nothing was ever actually lost. `WorkspaceSelectionContext.jsx`'s
      `selectedAgent` was a plain `useState("requirement")` with zero persistence, though -- a full
      page reload always remounts this provider fresh, so it always snapped back to Requirement
      regardless of which agent's chat was on screen a moment ago. Purely a "what's currently
      displayed" bug, not a data-loss bug, but indistinguishable from one to the user.
    - **Fix**: `selectedAgent` is now seeded from (and kept in sync with) an `agent` URL query
      param via `useSearchParams`, the same mechanism `ProjectWorkspacePage` already uses for
      `featureId`. `selectAgent(stage)` writes `?agent=stage` (`replace: true`, no extra history
      entries); `selectFeature(id)` clears it back to Requirement's default, matching the existing
      "switching features resets to Requirement" behavior. A fresh load of the exact same URL now
      reopens the exact same agent's chat instead of silently jumping back.
    - **Pause root cause**: no chat had any way to stop an in-flight generation. Requirement
      Agent's pre-SRS reply/edit/confirm and post-SRS revise are real token-by-token streams
      (`fetch` + `ReadableStream`, `streamNdjsonPost` in `api/agents.js`); Domain/Architecture/
      UIUX/Coder run/revise are plain awaited axios POSTs with no streaming at all -- neither path
      had any cancellation wired in anywhere.
    - **Fix**: `streamNdjsonPost` and `postCancelable` (new shared helper for the plain axios
      calls) both accept an optional `signal`; aborting either mid-flight resolves with
      `{aborted: true}` instead of rejecting, so a deliberate stop never surfaces as a "Request
      failed" error banner. Every streaming mutation in `useRequirementConversationFlow.js`
      (`respondStream`, `editTurnStream`, `confirmStream`, `reviseStream`) and every mutation in
      `useAgentMutations.js` now creates a fresh `AbortController` per call and exposes a
      `stop()`/`stopXStream()` function that calls `.abort()`. `SendButton.jsx` renders a black
      square "Stop generating" button (ChatGPT/Claude's exact affordance) in place of the old
      disabled spinner whenever `pending` is true, wired through `ChatComposerBox`'s new `onStop`
      prop to whichever mutation/stream is currently active in `ChatPanel.jsx`,
      `RequirementConversationChat.jsx`, and `RequirementRevisionChat.jsx`; the confirm-generating
      and edit-generating indicators (which don't use the bottom composer) got their own inline
      "Stop" links.
    - **Two real, honestly-documented asymmetries between the two kinds of agents**, confirmed by
      reading the actual backend routes rather than assumed:
      1. For Requirement's 4 streaming endpoints, the whole turn (human_reply + agent's
         reaction/questions) is only ever persisted atomically by the stream's final "done" event
         -- stopping mid-stream means NOTHING was saved server-side (unlike ChatGPT/Claude, where
         the human's own message is durable the instant it's sent). Fixed the "silently lose what
         you typed" side-effect this would otherwise cause: `RequirementConversationChat.jsx`'s
         reply handler now checks the resolved `{aborted}` result and puts the exact typed text
         back in the composer if the stream was stopped before finishing, instead of discarding
         it. A parallel `isGenerating` bug this abort-resolves-not-rejects design would have
         caused (`confirmStream.isSuccess` alone stays true forever after ANY resolution,
         aborted or not, which would have wedged the UI in "Generating..." forever after a
         stopped confirm) is fixed by also checking `!confirmStream.data?.aborted`.
      2. For Domain/Architecture/UIUX/Coder's run/revise routes, by contrast, confirmed by reading
         `agents.py`: `stage_event_service.record(...)` runs SYNCHRONOUSLY before the agent call
         even starts, so the human's comment is durably saved as a real stage_event almost
         immediately regardless of whether the request later gets aborted -- these four agents
         needed no "restore the composer" recovery logic, and `useAgentMutations.js` always
         invalidates the `events` query on resolution (aborted or not) specifically so that
         already-saved "ask" bubble reliably shows up either way.
      Also honestly documented in code comments (not glossed over): stopping a real
      **streaming** generation genuinely halts the backend too (FastAPI/Starlette cancels a
      `StreamingResponse`'s underlying async generator when the client disconnects), but stopping
      one of the four **non-streaming** agents is honestly "stop waiting on it" from the human's
      side -- whether the backend's one plain `await agent.run(...)` call itself gets interrupted
      depends on how that particular call is structured, which this fix doesn't change.
    - **Real, live verification** (isolated backend/frontend, real LLM calls): switched to Domain
      Agent's chat, confirmed the URL became `...?agent=domain`, did a genuine full `page.reload()`
      (not a SPA navigation), and confirmed the agent pill still read "Domain" and the same
      proactive-prompt chat state was still showing afterward. Sent a real Domain Agent message
      with a distinctive marker comment, clicked Stop ~0.5s in, and confirmed: the button correctly
      reverted to a normal Send arrow, no error banner appeared, `GET .../events` showed the
      stage_event WAS recorded with the exact marker text despite the stop, and -- most tellingly
      -- the feature's Domain stage genuinely stayed "Not started" with zero Enhanced SRS artifacts
      produced, confirming the abort really did stop the backend agent, not just the frontend's
      view of it. Separately, on Requirement Agent's real pre-SRS streaming reply: clicked Stop
      ~2s into a visibly in-progress token stream, confirmed the black square Stop button rendered
      correctly mid-stream, the composer's text was restored to the exact original typed message
      after stopping, the conversation's `turn_history` length was provably unchanged (nothing
      persisted, as documented above), and the Send button correctly reverted afterward. `npm run
      build` clean; no backend changes so the pytest suite is unaffected. No frontend test
      framework exists in this repo, matching every prior item's own note. Test
      projects/features and isolated backend/frontend processes cleaned up afterward.

45. **Domain Agent silently discarded explicit human-provided content (e.g. "add this database
    schema"), the composer stayed frozen with the typed text in it until the whole enrichment
    finished, there was no live output, and no way to stop it -- Domain Agent was the one agent
    chat left behind after every one of these was already fixed for Requirement Agent.** Direct
    user report, five parts: (1) "When I tell domain agent to add database schema for the
    enhaced SRS the agent did not add what I asked" (2) the typed prompt stayed in the input
    field until generation finished, instead of moving to the chat immediately (3) "Domain agent
    output also apear live" (4) Domain Agent should "dynamically addopt with user prompt" (5)
    "Token streaming... must be availble for the domain agent as well, just like the requirement
    agent" plus a loader "just like the requirement agent."
    - **Root cause, part 1 (the actual correctness bug, found by reading domain_validator.py/
      agent.py/prompt.py, not guessed)**: Domain Agent was built as a strict RAG system -- its
      system prompt told the LLM "every addition must cite one of the [KB-N] knowledge chunks,"
      and `domain_validator.py`'s `_validate_citation_integrity`/`_validate_honesty_with_empty_
      retrieval` mechanically enforced it: any addition/modification whose `domain_citation`
      didn't match a real RETRIEVED chunk's source_document was rejected, and if retrieval
      returned nothing at all, ANY proposed addition/modification failed the whole plan. A
      human explicitly typing "here's our database schema: ..." is not a RAG retrieval result --
      it has no [KB-N] chunk to cite -- so the validator rejected it every time, no matter what
      the LLM tried, silently falling back to "No domain enrichment was applied to this SRS."
      This is the exact opposite of what the chat's own proactive prompt (item 41) promises
      ("do you have something specific to add -- like a database schema?").
    - **Fix, part 1**: added a second legitimate citation source, `domain_citation.source_document
      == "human_provided"`, accepted only when the call actually had a non-empty human comment
      (`human_comment_provided` threaded through `validate_plan`/the new `filter_valid_plan` --
      the LLM cannot fabricate this source when there was no real comment to ground it in). Added
      `data_requirements` as a new addition-only target_section (it already existed as a plain
      `list[str]` field on the SRS -- see `markdown_builder.py`'s own rendering of it -- with no
      per-item id, so it's the natural home for schema-shaped content that never fit any of the
      five existing FR/NFR/AC/VR/US item shapes). Both system prompts and the human-comment/
      revision-comment injection text were rewritten to explicitly instruct the LLM to incorporate
      concrete human-provided content faithfully (not paraphrase or drop it), and to write ONE
      complete addition for a single cohesive structure (a whole table's fields) rather than
      fragmenting it -- the first version of this fix got the citation/section right but the LLM
      still only added one field from a five-field schema until this instruction was added.
    - **Root cause, part 1b (found live, AFTER the citation fix, via real end-to-end testing)**:
      `domain_validator.validate_plan`'s existing all-or-nothing design meant ONE hallucinated,
      unrelated item (e.g. a modification referencing a made-up acceptance-criteria id) discarded
      the ENTIRE plan via a single raised exception -- including a separate, genuinely correct,
      human-requested schema addition sitting right next to it in the same LLM response. Observed
      directly: a real test run produced `{"additions": [database schema, ...], "modifications":
      [bad AC-003 reference]}` and the bad modification alone caused the whole thing to be thrown
      away, reproducing the user's exact complaint even after the citation logic was already
      fixed.
    - **Fix, part 1b**: new `DomainEnhancementValidator.filter_valid_plan` -- a lenient
      counterpart to the existing `validate_plan` (kept unchanged, still covered by its own
      dedicated unit tests) that checks each addition/modification INDEPENDENTLY, keeping every
      one that passes and dropping (with a logged, human-readable reason) only the ones that
      don't, instead of raising for the whole plan. `agent.py`'s `_parse_and_validate_plan`/
      `_resolve_enrichment_plan` now use this instead -- the JSON-repair retry step is now only
      reached for genuine structural failures (unparseable JSON, missing top-level keys), not
      "one item out of five had a bad reference," since that case is now handled by keeping the
      other four.
    - **Root cause, parts 2-5 (the chat UX)**: Domain Agent's chat went through `ChatPanel.jsx`'s
      GENERIC composer path -- a plain, non-streaming axios `mutateAsync` awaited to completion
      before the composer cleared (`setComment("")` ran only AFTER `await submitAgentMessage(...)`
      resolved), no live token output at all (Domain's `/domain/run`/`/domain/revise` were
      one-shot JSON endpoints, unlike Requirement Agent's real `provider.stream(...)`-backed
      endpoints), and no stop affordance wired to it.
    - **Fix, parts 2-5**: gave Domain Agent the exact same real infrastructure Requirement Agent
      already has, not a look-alike:
      - Backend: new `DomainAgent.run_stream`/`revise_stream` async generators (mirroring
        `RequirementAgent.revise_stream` exactly) using `provider.stream(...)` for the first LLM
        call, yielding `{"type": "token", "text": ...}` events for the small enrichment plan as it
        generates, then running the SAME deterministic filter/merge/save tail as `run()`/
        `revise()` (factored into the shared `_resolve_enrichment_plan` helper both streaming and
        non-streaming paths now call). New routes `POST /domain/run/stream` and
        `POST /domain/revise/stream`, identical NDJSON shape to Requirement's streaming routes.
        The old non-streaming `/domain/run`/`/domain/revise` routes are untouched for any direct
        API caller, same as Requirement's own precedent.
      - Frontend: new `useDomainAgentFlow.js` hook (mirrors `useRequirementConversationFlow.js`
        exactly -- per-call `AbortController`, `stop*Stream()` functions) shared via new
        `DomainAgentFlowContext.jsx` (mirrors `RequirementConversationFlowContext.jsx`) so
        the chat feed and the Result panel's live document view observe the same in-flight
        stream. New `DomainAgentChat.jsx` (mirrors `RequirementRevisionChat.jsx`) is now
        Domain's own dedicated chat component, replacing the generic `ChatPanel.jsx` path for
        `selectedAgent === "domain"` -- carries over the proactive prompt, "/" document mention,
        and suggestion chips that used to live inline in `ChatPanel.jsx`. The human's message
        now appears in the chat feed and the composer clears IMMEDIATELY on submit (optimistic
        `pendingHumanReply` bubble, same pattern `RequirementRevisionChat` already uses), not
        after the agent finishes. `ResultTab.jsx` gained an `isDomainGenerating` branch reusing
        the exact same `LiveGenerationView` (built-in "Connecting..." spinner, then live
        decluttered-JSON "typing" -- the loader the user asked for "just like the requirement
        agent" comes free from reusing this exact component) Requirement's own revise flow uses.
        The composer's Send button already becomes a Stop button while any stream is pending
        (item 44's mechanism), now wired to Domain's new streams too.
      - `useRunDomain`/`useReviseDomain` (the old non-streaming mutation hooks) are no longer
        imported by `ChatPanel.jsx` but were left in `useAgentMutations.js` unused rather than
        deleted, matching this repo's own established precedent (Requirement Agent's own
        non-streaming `/requirement/revise` route and hook are kept the same way).
    - **Real, live verification** (isolated backend/frontend, real LLM calls, llama3:latest):
      typed "Here's our database schema: items table has fields id, name, price, stock, quantity"
      into Domain Agent's chat and confirmed, within ~150ms of clicking Send, the composer was
      already empty and the human's message was already visible in the chat feed -- both well
      before the agent finished. Confirmed a real Stop button appeared mid-stream and, separately,
      confirmed stopping actually halts the backend (zero artifacts produced when stopped early,
      same evidence style as item 44). Let a run complete fully and inspected the resulting
      Enhanced SRS JSON directly: `data_requirements` contained the exact complete string "items
      table with fields id, name, price, stock, quantity" -- the full schema, faithfully
      incorporated, not dropped and not fragmented -- with `domain_improvements` correctly
      showing `knowledge_sources_used: [{"source_document": "human_provided", "chunks_used": 1}]`.
      Separately verified the "Just use domain knowledge" quick-action button (for a human with
      nothing specific to add) still completes a full run end-to-end and produces real artifacts.
      Backend pytest suite: 300 passed (all pre-existing `test_domain_validator.py` tests for the
      unchanged strict `validate_plan` still pass unmodified). `npm run build` clean. No frontend
      test framework exists in this repo, matching every prior item's own note. Test
      projects/features and isolated backend/frontend processes cleaned up afterward.

46. **Asking Domain Agent to remove or edit something already in the Enhanced SRS did nothing --
    a new version was generated with the requested change silently missing.** Direct user report:
    "When I prompt to remove or edit something on the enhanced SRS in the domain agent the domain
    agent did nothing and generated a new enhaced SRS verion without the edit I told to do. When
    user need to endit, remove or update on something on the enhanced SRS the user must be able
    to do it by the domain agent, just like the architect agent."
    - **Root cause**: Domain Agent's entire revision vocabulary was an "enrichment plan" --
      `additions` (new items) and `modifications` (ENRICH an existing item's description with a
      missing domain detail, per its own system prompt wording). There was no way to express
      "remove this" or "replace this outright" at all -- a fundamentally different, and
      fundamentally missing, capability. By contrast, Requirement Agent's own revise flow
      (`revision_patcher.py`, confirmed by reading it) already has exactly this: a small
      `add`/`remove`/`modify`/`set` operations list, applied deterministically by field name
      against the document. Domain Agent never had an equivalent.
    - **Fix**: reused `apply_revision_operations` directly (imported from
      `app.agents.requirement_agent.revision_patcher` -- a deliberate, documented exception to
      this file's own "other agents stay untouched" claim, since the function is generic and
      feature-independent, matches by field name against any SRS-shaped document, and has no
      Requirement-Agent-specific dependencies; reusing it avoided re-implementing ~300 lines of
      already-working, already-tested matching logic). New `DomainAgent._apply_operations_and_merge`
      applies any `operations` (remove/modify) to the current Enhanced SRS FIRST, then merges the
      enrichment plan's `additions` on top of the operation-patched result -- called from both
      `revise()` and `revise_stream()` only (not `run()`/`run_stream()`, which have no existing
      document yet to edit). Applied/unmatched edits are recorded in `domain_improvements_json`
      (`applied_edits`/`unmatched_edits`) and unmatched ones are also appended to the Enhanced
      SRS's own `assumptions` array, mirroring Requirement Agent's own "report, don't guess"
      convention exactly -- a human reviewer sees explicitly when a requested edit did NOT happen,
      instead of it silently not happening with no trace.
    - **Prompt iteration, done for real via live testing, not guessed**: the first version (three
      mechanisms -- additions/modifications/operations -- coexisting) let the model correctly
      express a `remove` on the first try, but consistently mis-routed `modify` requests through
      the OLD `modifications` shape instead of `operations`, omitting the required `value` field
      three times in a row with three different malformed shapes. Diagnosis: three overlapping
      mechanisms was too much decision surface for this size of local model
      (`llama3:latest`, temperature 0.3). Fix: collapsed the revision schema to exactly TWO
      mechanisms -- `additions` (brand-new content only) and `operations` (anything touching
      something that already exists, including "enrich this item's description," which is now
      just `action: "modify"` with the complete new text) -- with `modifications` kept in the
      returned JSON shape only as an always-empty placeholder so older parsing code never breaks.
      This single simplification fixed `modify` reliably across every retest afterward. Separately
      hardened `domain_validator.py`'s lenient per-item path (`_check_one_citation`/
      `_check_one_modification`) to auto-attribute a missing `domain_citation` to
      `"human_provided"` when a real human comment exists (rather than reject the item), and to
      accept the `operations` vocabulary's key names (`field`/`target`/`value`) as aliases for
      `modifications`' own (`target_section`/`id`/`enhanced_description`) if the model still
      confuses them -- defensive robustness, not required for the fix to work, but cheap and
      strictly safety-net.
    - **Real, live verification** (isolated backend/frontend, real LLM calls, `llama3:latest`,
      inspecting actual resulting artifacts each time, not just HTTP status codes): "Remove the
      requirement about merging guest carts (FR-DOM-001)" -> confirmed FR-DOM-001 genuinely gone
      from the next version's `functional_requirements`, with `domain_improvements.applied_edits`
      correctly recording it. "Change FR-002 to say: ..." -> confirmed FR-002's description was
      replaced with the exact new text, twice in a row. "Update NFR-001 to say response time must
      be under 1 second" -> confirmed the exact replacement, and a same-session "Remove NFR-002"
      right after that also correctly removed it. Re-verified additions (the prior item's own
      schema-incorporation fix) still work correctly after this schema simplification -- one
      retry needed out of two attempts on a fresh feature (the other failed attempt was an honest,
      correctly-reported "nothing changed" rather than a silent no-op, confirming the reliability
      ladder's own honesty guarantee held even when the underlying small local model itself
      stumbled). Finally drove a real removal request through the ACTUAL browser chat UI (not just
      curl): composer cleared immediately, the message appeared in the chat feed, a new Enhanced
      SRS version was produced, and the targeted functional requirement was genuinely gone from
      it. Backend pytest suite: 300 passed, including every pre-existing `test_domain_validator.py`
      test for the untouched strict `validate_plan` (only the new lenient per-item path changed).
      `npm run build` clean; no frontend code changes were needed for this item (the existing
      DomainAgentChat/streaming infrastructure from item 45 required zero changes -- this was a
      pure backend capability gap). No frontend test framework exists in this repo, matching every
      prior item's own note. Test projects/features and isolated backend/frontend processes
      cleaned up afterward.

47. **Follow-up to items 45/46 (same overall request, restated): "the domain agent must
    dynamically interact with the user... satisfy all user prompts/needs... just like the
    requirement agent... e.g. add a database schema."** Investigation found items 45 and 46
    together already fully deliver this -- real token-by-token streaming, immediate composer
    clear, a live loader, and working add/remove/modify via `DomainAgentChat.jsx` +
    `useDomainAgentFlow.js` + the operations-based revise backend -- so this item is a fresh,
    skeptical, full end-to-end re-verification of that combined state (not a re-implementation),
    plus one real bug it caught:
    - **Bug found**: `LiveReactionBubble` (in `RequirementConversationParts.jsx`) hardcoded the
      label `"Requirement Agent"` on its "thinking..."/streaming bubble. `DomainAgentChat.jsx`
      (item 45) reuses this exact component for its own streaming summary, so Domain Agent's
      live "thinking" bubble incorrectly read "Requirement Agent" the whole time -- confirmed via
      screenshot before the fix. Fixed by adding an `agentLabel` prop (default
      `"Requirement Agent"`, so both existing Requirement Agent call sites -- `RequirementRevisionChat.jsx`
      and `RequirementConversationChat.jsx` -- need no changes) and passing
      `agentLabel="Domain Agent"` from `DomainAgentChat.jsx`'s own call site.
    - **Real, live re-verification of the combined items 45+46+47 state**, fresh isolated
      backend/frontend, real LLM calls (`llama3:latest`), through the ACTUAL browser chat UI, one
      continuous session per flow (avoiding the documented `browser.close()`-races-an-in-flight-
      stream gotcha): typed a database schema into a fresh feature's Domain Agent chat (its first
      message, so this exercises `run_stream`) -- confirmed the composer cleared and the message
      appeared in the chat feed within ~150ms, confirmed the "thinking" bubble correctly read
      "Domain Agent" (not "Requirement Agent"), waited for real completion (polling the backend
      artifacts endpoint, not a fixed sleep), and confirmed the resulting Enhanced SRS's
      `data_requirements` contained the exact schema string
      `"cart_items table: id, cart_id, product_id, quantity, price."` -- faithfully incorporated.
      Then, on the SAME feature (now exercising `revise_stream`), typed "Remove the functional
      requirement about removing items from cart" and confirmed a new Enhanced SRS version was
      produced with that exact functional requirement genuinely gone from
      `functional_requirements`, composer again clearing immediately and the label again reading
      "Domain Agent" throughout. `npm run build` clean; backend pytest suite 300 passed. No
      frontend test framework exists in this repo, matching every prior item's own note. Test
      project/feature and isolated backend/frontend processes cleaned up afterward.

48. **Per-Project Domain Knowledge Upload + "/" Document Mention for Domain Agent -- found already
    fully implemented (backend RAG pipeline, upload service, routes, and every frontend piece)
    from earlier in this same session; this pass was real, live, skeptical end-to-end
    verification of that state, not a reimplementation, and it caught one real cosmetic bug.**
    Full design: the plan approved in plan mode this session (now superseded per this file's own
    "plan file is scratch" convention). Confirmed present and correct by reading every file the
    plan named: `rag/vector_store.py` (`get_chunks_by_document`/`delete_by_document`/`query(...,
    where=...)`), `rag/chunking.py` (`document_id`-namespaced chunk IDs), `domain_knowledge_
    service.py` (`retrieve(..., project_id=...)`'s Python-side cross-project-leak guard,
    `ingest_upload`/`get_document_chunks`/`rank_chunks_by_relevance`/`delete_document`), the new
    `knowledge_document_service.py` (upload/list/get/delete, mirroring `project_memory_service`'s
    storage convention), `knowledge_schema.py`, the `knowledge_documents` Mongo collection, `POST/
    GET/DELETE /projects/{id}/knowledge/documents` + download route, `domain_schema.py`'s
    `referenced_document_ids`, and `DomainAgent._collect_pinned_chunks`/`_retrieve_domain_
    knowledge(...)` wiring pinned chunks ahead of similarity-search chunks. Frontend: `api/
    knowledge.js`, `useKnowledgeDocuments.js`, `DomainKnowledgePanel.jsx` (wired into
    `FeatureListPanel.jsx` behind a "Domain Knowledge" modal), `DocumentMentionPicker.jsx` +
    `DomainAgentChat.jsx`'s `/`-trigger regex/mention-chip state (from item 45's dedicated Domain
    chat component -- the picker/chips slot directly into its existing composer, no separate
    integration needed).
    - **Real, live verification, no mocks**: a standalone script (no HTTP, no LLM, real Chroma +
      real `sentence-transformers` embedding) exercised `knowledge_document_service`/
      `domain_knowledge_service` directly against two real projects -- upload succeeds with a real
      non-zero `chunk_count`, `list_documents` is correctly project-scoped, **the cross-project
      leak guard holds** (a query from project B for project A's unique marker text returns zero
      of A's chunks), project A's own retrieval correctly finds its own document, `DomainAgent.
      _collect_pinned_chunks` correctly returns the pinned document's real chunk text, raw-byte
      download round-trips exactly, and delete removes the chunks (0 remain via `get_document_
      chunks` afterward). Then, in a real isolated browser session (fresh backend :8070/frontend
      :5199, real project/feature), opened the Domain Knowledge modal, uploaded a real `.txt` file
      through the actual file input, watched it reach `status: ready` via the panel's own 3s
      polling, navigated to Domain Agent's chat, typed `/returns` and confirmed the mention picker
      appeared showing the uploaded filename, clicked it, and confirmed a removable
      `returns_schema.txt ×` chip appeared above the composer with the `/returns` token correctly
      stripped from the message text -- exactly the Claude/ChatGPT-style file-mention UX the plan
      called for.
    - **Real bug found and fixed**: `DomainKnowledgePanel.jsx` mapped a knowledge document's own
      `status` (`processing`/`ready`/`failed`) onto `StatusBadge`'s `approved`/`rejected`
      vocabulary purely to reuse its green/red color styling -- but `StatusBadge`'s label text was
      hardcoded per status key, so a successfully-processed document's badge literally read
      "Approved" (and a failed one "Rejected"), falsely implying a human approval decision had
      happened to a document that was never gated at all. Fixed by giving `StatusBadge` an
      optional `label` override prop (falls back to its existing hardcoded label map when
      omitted, so every other call site in the app is unaffected) and passing "Ready"/"Failed"/
      "Processing..." from `DomainKnowledgePanel` -- confirmed via a fresh screenshot after the
      fix. **Any future reuse of `StatusBadge` for a status vocabulary that isn't actually
      pending/approved/rejected should pass its own `label`**, not rely on the approval-flavored
      default text.
    - No backend changes were needed -- the backend half of this feature was already correct as
      found. Full backend suite: 300 passed (no regressions, confirmed before starting this
      verification pass). `npm run build` clean after the `StatusBadge`/`DomainKnowledgePanel`
      fix. No frontend test framework exists in this repo, matching every prior item's own note.
    - **Loose end, not investigated further**: the throwaway verification project
      (`proj_37f06cfd`, "KB Mention Verify") could not be found via `DELETE`/`GET` immediately
      after the browser verification session ended, despite having been fully functional (upload,
      list, chat, mention picker) moments earlier through the same backend process -- no on-disk
      `outputs/kb-mention-verify/` directory existed either, so there was nothing left to clean up
      by hand. Not reproduced or root-caused (this session's isolated test backends/projects are
      always short-lived and thrown away regardless, so a project vanishing on its own before
      cleanup has zero practical impact) -- flagged here only in case a similar "a just-created
      project silently disappeared" report ever surfaces as a real, non-throwaway complaint.

49. **Domain Agent treated a human-referenced document as merely optional background, identical
    to an ordinary similarity-search hit -- so "enrichment" often looked static/generic even
    though the RAG plumbing (items 45/48) was already real. Fixed by giving referenced
    documents mandatory-incorporation treatment in the prompt, distinct from ordinary retrieval.
    Also fixed a second, real, reproduced bug: the agent's chat reply visibly disappeared for a
    beat right when a stream finished, before the persisted bubble replaced it.** Direct user
    report, three parts: (1) "the domain agent only enhanced the SRS static way... must enhance
    dynamically according to the user prompt and user select files," (2) "user must be able to
    add extra sections to the SRS explicitly... if user needs to add database schema... domain
    agent must do it," (3) "once the domain agent replies... the message disappears instantly."
    - **Root cause, parts 1-2**: confirmed by reading `_format_retrieved_chunks` (`prompt.py`) --
      every retrieved chunk, whether it came from ordinary similarity search OR from a document
      the human explicitly selected via "/" (item 48's pinned-chunk mechanism), was rendered
      identically as a generic `[KB-N]` block with no signal that one class of chunk was
      hand-picked by the human and the other wasn't. The system prompt's own "TWO legitimate
      sources" framing (retrieved chunks vs. the human's *typed* comment) never distinguished a
      referenced *file* from a generic retrieval hit -- so the model was free to judge a
      referenced document's relevance the same way it judges any KB search result, and could (and
      did, on the first repro attempt) engage with it only partially instead of treating the
      human's explicit selection as an instruction. This is the same defect class already fixed
      for *typed* human comments in item 45 (`HUMAN_PROVIDED_SOURCE`), just never extended to
      *referenced files* -- the chat's own proactive prompt invites "type / to reference an
      uploaded document," implying selection alone should carry weight, which it didn't.
    - **Fix**: `DomainAgent._collect_pinned_chunks` now tags every pinned chunk
      `referenced_by_human: True`. `prompt.py`'s `_format_retrieved_chunks` renders tagged chunks
      as a separate `[REFERENCED-N]` block (own section, "mandatory to use") ahead of ordinary
      `[KB-N]` blocks ("optional background"). Both `DOMAIN_AGENT_SYSTEM_PROMPT` and
      `DOMAIN_REVISION_SYSTEM_PROMPT` gained explicit "you MUST incorporate every [REFERENCED-N]
      chunk's relevant content, not just consider it optional" rules, plus the SAME "if it
      describes one cohesive structure, write ONE complete addition covering the whole thing"
      instruction item 45 already gave typed comments -- now applying to referenced files too.
      `build_domain_user_prompt`/`build_domain_revision_prompt` each gained a small dynamic
      reminder line (counting how many `[REFERENCED-N]` chunks are present) reinforcing the same
      point right before generation, matching this project's own established "local models respond
      better to repeated instructions" precedent. Citation format is unchanged and needed no
      validator changes -- a `[REFERENCED-N]` chunk cites with its own real
      `source_document`/`chunk_id`, exactly like a `[KB-N]` chunk already does; only `human_provided`
      remains reserved for the human's own *typed* text.
    - **Root cause, part 2's "extra sections"**: turned out to already be the exact mechanism item
      45 built -- `data_requirements` renders as its own titled `## 14. Data Requirements` Markdown
      section (confirmed by reading `markdown_builder.py`), which is precisely "an extra section
      for a database schema." The gap was never a missing schema mechanism, only that a
      *referenced file's* schema wasn't being reliably pulled in -- fixed by the same change as
      part 1.
    - **Root cause, part 3, confirmed by reading the actual mutation code**:
      `useDomainAgentFlow.js`'s `invalidateAfterCompletion` fired four `queryClient.
      invalidateQueries(...)` calls without awaiting any of them, and was a plain (non-async)
      function passed as the mutation's `onSuccess`. React Query's `mutateAsync()` only resolves
      once `onSuccess` itself resolves -- since this `onSuccess` returned `undefined` synchronously
      instead of a pending promise, `mutateAsync()` (and therefore `activeStream.isPending`
      flipping false, and `submitDomainMessage`'s `.finally(() => setPendingHumanReply(null))`)
      all fired essentially immediately, well before the invalidated queries had actually
      refetched fresh data from the backend. Net effect: the live streaming/reaction bubble and
      the optimistic "You" bubble both vanished the instant the stream's `"done"` event landed,
      but the real persisted bubbles (which only exist once the refetched `events`/`artifacts`
      queries land in the cache) hadn't appeared yet -- a real, reproducible empty-frame gap,
      exactly the reported "message disappears instantly."
    - **Fix**: made `invalidateAfterCompletion` `async` and awaited every `invalidateQueries(...)`
      call via `Promise.all([...])` -- `mutateAsync()` (and thus the live bubbles' teardown) now
      genuinely waits until the fresh timeline data has landed in the query cache before
      resolving, making the live-bubble-to-persisted-bubble handoff seamless. **The identical
      unawaited pattern was found in two more places sharing the same root cause** (not reported
      for these, but the same bug class, fixed for consistency and cheap to fix safely):
      `useRequirementConversationFlow.js`'s `confirmStream`/`reviseStream` `onSuccess` handlers
      (Requirement Agent's post-SRS revise chat -- `RequirementRevisionChat.jsx` mirrors
      `DomainAgentChat.jsx`'s exact bubble-teardown pattern, so it had the exact same race), and
      `useAgentMutations.js`'s shared `useAgentMutation` factory (used by Architecture/UI-UX/Coder
      Agent's plain, non-streaming chats -- same "pending flips false right as onSuccess starts"
      mechanism, same fix).
    - **Real, live verification, no mocks, through the actual browser chat UI** (isolated
      backend/frontend, real Ollama calls -- temporarily switched Domain Agent's live per-agent
      LLM override from `qwen3-coder:latest`, discovered mid-verification to be genuinely slow on
      this machine's GPU per the already-documented gotcha, to `llama3:latest` for the duration of
      this pass only, then restored it back to `qwen3-coder:latest` exactly afterward -- this is
      real, persisted, shared configuration in the live Atlas cluster, not test-local state, so it
      was put back rather than left changed):
      - Message-disappear fix: submitted a real Domain Agent message, watched a genuine Stop
        button appear then disappear as the real stream completed, and screenshotted the exact
        next frame after completion -- the real "Domain Agent: Produced Enhanced SRS, Domain
        Improvements (v1)" bubble was already visible with zero empty gap, confirmed both visually
        and via `page.inner_text` (no "No activity yet" flash, "Produced" present immediately).
      - Dynamic/referenced-file enrichment fix: uploaded a real knowledge document (a
        `return_reasons` lookup table schema: `id`, `code`, `display_label`,
        `requires_photo_evidence`, `refund_eligible`) to a fresh project, referenced it via "/" in
        Domain Agent's chat with only a generic, non-copy-pasted instruction ("Please enrich the
        SRS using [the referenced file]") -- the resulting Enhanced SRS's `domain_improvements`
        correctly cited `return_reasons_schema.txt` by its real `chunk_id` (not a generic KB hit,
        not "human_provided") and added a genuinely content-derived enrichment (a `reason_id`
        foreign-key requirement + a status-enum acceptance-criteria modification), both explicitly
        reasoned from "[REFERENCED-1]" in the model's own rationale text -- concrete evidence the
        model now treats a referenced file differently from background retrieval, not the
        pre-fix generic/static behavior. A follow-up revision request ("add the full
        return_reasons lookup table... including every field in that document," again without
        retyping the schema, just re-referencing the same file) produced a `data_requirements`
        entry that was an EXACT, complete match to the uploaded file's full 5-field schema --
        confirming both the mandatory-incorporation fix and the pre-existing "one complete
        addition per cohesive structure" instruction now correctly extend to referenced files, not
        just typed comments.
    - Full backend suite: **300 passed** (`tests/test_domain_validator.py`/
      `test_domain_agent_fallback.py` specifically re-run first, all still passing unmodified --
      this change only touched prompt text and chunk tagging/formatting, no validator logic).
      `npm run build` clean. No new backend unit tests were added for the prompt-wording change
      itself (there is no automated way to assert an LLM "treats X as mandatory" -- this was
      verified live, against a real model, matching this project's established practice for
      prompt-quality changes). No frontend test framework exists in this repo, matching every
      prior item's own note.
    - **A real, reachable bug found ALONG THE WAY during this verification's own test setup, NOT
      part of this fix and NOT fixed here (recorded honestly rather than silently left for a
      future session to rediscover)**: `approval_service.py`'s SRS-exclusivity rule (item 37) reverts
      every OTHER `srs`-type artifact currently `APPROVED` back to `pending` when a new one is
      approved -- scoped by `artifact_type` alone, with **no format awareness**. Since every SRS
      version is saved as a JSON+Markdown *pair* sharing one version (this project's own
      long-established convention -- see item 34's cascade-delete fix for the first time this
      exact pairing caused a bug), approving the JSON half of a version, after its Markdown
      sibling was already separately approved, silently reverts that Markdown sibling back to
      "pending" -- confirmed directly and reproducibly in this session (approved `srs` markdown
      v1, then `srs` json v1; the markdown flipped back to pending the instant the json was
      approved). **This is reachable through the normal UI, not just direct API calls**: item 40's
      own fix made every pending/rejected version of every artifact_type independently
      approvable, including a gating type's Markdown row, which previously had no path to
      independent approval at all. Likely low real-world impact today, since the frontend's own
      approve flow (`ResultTab.jsx`'s `requestSrsApproveConfirmation`) always targets the row the
      UI shows (typically the JSON representative, per `dedupeArtifactVersions`' format
      preference) rather than a human manually approving the Markdown row on its own -- but a
      human who *does* explicitly approve a Markdown row first, then approves its JSON sibling
      (or vice versa), will see the first one silently un-approve. Worth a future fix (the
      cleanest one: scope the exclusivity revert to same-`artifact_format`-siblings the same way
      item 34's `delete_artifact` already treats a JSON+Markdown pair as one logical version) --
      not fixed here, since it's unrelated to what this item's user report asked for.

50. **Domain Agent could structurally only enrich 6 of the SRS's ~18 sections (in practice
    converging on non_functional_requirements/acceptance_criteria almost every run) -- fixed by
    genuinely widening what it's allowed to touch, not just prompting it to try harder. Also
    added inline, color-coded highlighting for domain-added content across every section, not
    just the original 4.** Direct user report: "the domain agent only improves the Nonfunctional
    requirement section and the acceptance criteria section... must enrich the entire SRS
    dynamically instead of static... must display the domain improvements separately... highlight
    and use separate colour codes for domain agent improvements."
    - **Root cause, confirmed by reading the actual schema, not assumed**:
      `domain_validator.py`'s `ADDITION_TARGET_SECTIONS` was hard-capped at the 5 ID-tagged
      sections (FR/NFR/AC/VR/US) plus `data_requirements` -- `scope`, `out_of_scope`,
      `constraints`, `risks`, `dependencies`, `assumptions`, `user_roles`, `api_expectations`,
      `ui_expectations`, `input_requirements`, `output_requirements` were **structurally
      impossible** targets for an "addition," rejected by the validator regardless of what the
      retrieved knowledge supported. The system prompt's own "Never touch project/feature-level
      fields (business_goal, scope, constraints, etc.)" line made this a deliberate original
      design choice, not an oversight -- but it meant the model's only real creative freedom
      narrowed down to NFR/AC in practice (the two sections that read most naturally as "domain
      knowledge" without a schema/citation to hang off of), exactly matching the reported
      complaint. This was a real schema restriction, not a model preference the prompt could
      talk its way around.
    - **Fix, backend**: `domain_validator.py` gained `PLAIN_LIST_SECTIONS` (the 11 sections
      above -- deliberately matching `DOMAIN_REVISION_SYSTEM_PROMPT`'s pre-existing "operations"
      field list, which could already reach every one of these via remove/modify; only
      "additions," shared by both initial generation and revision, was missing them) and
      `ADDITION_ONLY_SECTIONS = [data_requirements] + PLAIN_LIST_SECTIONS` --
      `ADDITION_TARGET_SECTIONS` now includes all of them, addition-only (like data_requirements,
      none have a per-item id to modify; `_validate_modifications`/`_check_one_modification`
      reject a modification targeting any of them with the same "propose an addition instead"
      message data_requirements already had). `agent.py`'s `_apply_enrichment_plan` generalized
      its data_requirements-only special case to `if target_section in ADDITION_ONLY_SECTIONS`,
      appending the description to whichever plain list[str] field the LLM targeted -- one code
      path for all 12 addition-only sections instead of one hardcoded to `data_requirements`.
    - **Fix, prompt**: `DOMAIN_AGENT_SYSTEM_PROMPT` and `DOMAIN_REVISION_SYSTEM_PROMPT` both gained
      an explicit "do NOT default to only non_functional_requirements/acceptance_criteria --
      actively check EVERY section against the retrieved knowledge, only propose what the content
      genuinely supports, never pad a section just to appear thorough" rule, plus per-section
      guidance on what kind of domain fact fits each new target (a compliance rule -> constraints,
      a known failure mode -> risks, a third-party service -> dependencies, an exact
      endpoint/auth expectation -> api_expectations, etc.). The old blanket "never touch
      project/feature-level fields" line was replaced with a short, explicit exclusion list
      (business_goal, feature_name, project_type, target_stack, architectural_style,
      traceability, domain_enrichment_metadata -- identity/system-managed fields only); everything
      else is now a legitimate target.
    - **Fix, "display domain improvements separately"**: already existed from item 42 (the
      `domain_improvements` artifact is excluded from the approvable artifact list and rendered
      as a read-only attachment directly under the Enhanced SRS) -- confirmed still correct,
      unchanged by this item.
    - **Fix, "highlight with separate color codes"**: `EnrichedItemList`/`SrsDocumentViewer`
      already did this for FR/NFR/AC/VR (green="Added by Domain Agent", blue="Enhanced by Domain
      Agent") -- but two real gaps were found reading the actual component: `user_stories` was
      missing from `ENRICHABLE_SECTIONS` entirely (Domain Agent could already add to it per
      `SECTION_PREFIX_MAP`, just never got the highlight treatment), and every plain-list section
      (including the pre-existing `data_requirements`) had **no highlighting mechanism at all**,
      since a plain string can't carry its own `origin`/`modified_by_domain_agent` flag the way an
      FR/NFR/AC/VR/US dict item can. Fixed: `user_stories` added to `ENRICHABLE_SECTIONS`. New
      `EnrichedPlainList.jsx` (same green "Added by Domain Agent" card + citation convention as
      `EnrichedItemList`, addition-only -- a plain-list section has no "modified" concept since
      there's no original text left to diff against once a string is edited in place) renders any
      of the 12 addition-only plain-list sections; a domain-added entry is identified by **exact
      text match** against the sibling Domain Improvements artifact's own recorded
      `additions[].description` for that `target_section` (new `buildHighlightedTextsBySection`
      helper in `SrsDocumentViewer.jsx`) -- no SRS schema change needed, since
      `domain_improvements_json` already records exactly this. `ArtifactContentView.jsx` gained an
      optional `domainImprovementsArtifact` prop (fetches its content via the same
      `useArtifactContent` hook, React-Query-cached so no extra network cost since `ResultTab.jsx`
      already fetches this same artifact for its own separate "Domain Improvements" attachment
      below) and passes it into `SrsDocumentViewer` as `domainImprovements`; `ResultTab.jsx`'s one
      call site updated. Also mirrored the same tagging into the Markdown output for symmetry
      (`markdown_builder.py`'s `_simple_list` gained an optional `highlighted_texts` set param,
      prefixing a matched plain-list entry with `**[DOMAIN ADDED]**`, computed once per `build()`
      call from `domain_improvements_json`'s own additions) -- the downloaded/rendered Markdown
      report now shows the same distinction the JSON-driven React view does, not just one of the
      two.
    - **Known, honest scope limit**: the artifact-viewer **popup** (`ArtifactViewerModal.jsx`,
      reached via a "View" link anywhere outside the main Result panel) does not currently look up
      sibling artifacts, so it renders an Enhanced SRS without the inline highlighting -- falls
      back to the exact same plain rendering as before this item (no regression, just missing the
      enhancement there). The **primary** reading surface (`ResultTab.jsx`'s inline document view,
      the same place a human actually reviews and approves the Enhanced SRS) has it. Threading
      sibling-lookup into the popup path would need `allArtifacts` plumbed into
      `WorkspaceSelectionContext`, out of this item's scope.
    - **Real, live verification, no mocks, through the actual API and browser** (isolated
      backend/frontend, temporarily switched Domain Agent's live per-agent LLM override to
      `llama3:latest` for the duration of this pass only -- same real, persisted, shared Atlas
      configuration as item 49, restored to `qwen3-coder:latest` exactly afterward): created a
      fresh "Payment Processing" feature specifically to exercise the payment/PCI seed knowledge
      base. A broad enrichment request ("cover requirements, constraints, risks, and dependencies,
      not just non-functional requirements") produced additions in `functional_requirements` AND
      `data_requirements` -- **zero** in NFR/AC this run, a complete reversal of the reported
      bias, direct evidence the schema is no longer the bottleneck (the model's per-run section
      choice is a separate, harder "which sections does retrieved content actually support"
      question this fix doesn't and can't fully control, honestly noted rather than overclaimed).
      A second, targeted revision request ("add a constraints entry: must comply with PCI DSS and
      never store raw card numbers") -- after one real, unrelated JSON-parse fallback on the first
      attempt (the pre-existing reliability ladder correctly caught it and preserved the document
      unchanged, confirmed via `fallback_used: true` in the resulting metadata; not a regression,
      the same ladder every Domain Agent call already has) -- succeeded on retry: the new
      `constraints` entry was confirmed present, verbatim, in the real Enhanced SRS JSON. A real
      browser screenshot of the Result panel's Constraints section shows the exact PCI DSS text in
      a green card with an "ADDED BY DOMAIN AGENT" badge and "Source: human_provided" citation,
      while the adjacent, untouched Risks/Dependencies entries (original Requirement Agent
      content) correctly render as plain, unhighlighted bullets right below it in the same
      screenshot -- direct visual proof of both the enrichment breadth fix and the highlighting
      fix working together, with no false-positive highlighting.
    - Full backend suite: **300 passed** (`tests/test_domain_validator.py`/
      `test_domain_agent_fallback.py`/`test_domain_markdown_builder.py` specifically re-run first,
      all still passing unmodified by this schema-expansion change). `npm run build` clean. No new
      backend unit tests added for the prompt-wording change itself (same reasoning as item 49 --
      "does the model actually diversify" is a live-verification question, not a unit-testable
      one); the deterministic schema/merge/markdown changes (`ADDITION_ONLY_SECTIONS`,
      `_apply_enrichment_plan`'s generalized branch, `_simple_list`'s highlighting) are exactly
      the kind of logic this project's existing tests already cover structurally and continued to
      pass unmodified. No frontend test framework exists in this repo, matching every prior item's
      own note.

51. **Architecture Agent live streaming + Enhanced-SRS approve-and-auto-continue**, per user
    request: "once the user accept enhaced SRS verions in the domain agent the sysytem will
    asked from the user start the next agent which is architect agent with the selected
    enehaced SRS... Once user approved the enhaced version SRS the architect agent will start
    automatically... Use loader while architect agent generates the architet plan and
    diagrams... response streaming must be availble for architect agent architect plan as well."
    Full plan (Plan-agent-validated before implementation, catching 4 real pre-existing issues
    along the way): `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Backend, step 1 (pin-awareness + a real, found-during-planning bug)**:
      `ArchitectureAgent._find_latest_approved_artifact` was a private, non-pin-aware duplicate of
      the same "latest approved" lookup Domain Agent already delegates to `artifact_service.
      get_selected_or_latest_approved_artifact` (item 36) -- now it does too, so a human-pinned
      SRS/Enhanced SRS version steers Architecture Agent as well, not just Domain. **Real bug
      found while validating the plan, confirmed by reading the code directly**: `revise()`
      hardcoded `enhanced_srs_json=None` unconditionally (`agent.py`, `_revise_architecture_plan_
      output`) -- every revision silently regenerated diagrams against the plain SRS, discarding
      whatever domain enrichment the original plan was built from. Fixed: `revise()`/
      `revise_stream()` now load the approved Enhanced SRS the same pin-aware way `run()` does,
      and `srs_for_generation = enhanced_srs_json or srs_json` feeds both the revision prompt and
      `_ensure_implementation_plan`, matching this agent's own established convention everywhere
      else. New tests: `tests/test_artifact_active_selection.py` (+2).
    - **Backend, step 2 (Enhanced SRS approval exclusivity)**: `approval_service.py`'s SRS-only
      exclusivity rule (item 37) generalized to `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES = {SRS,
      ENHANCED_SRS}`, reverting only a same-`artifact_type` **and** same-`artifact_format`
      sibling (never cross-type -- approving an Enhanced SRS must never revert the plain SRS the
      pipeline still needs approved). The format-scoping half also closes item 49's own
      previously-flagged, left-open gap (approving one format could revert an unrelated sibling's
      other format) -- done now specifically because widening the rule to a second artifact type
      doubles that bug's blast radius if left unfixed. New tests: `tests/test_approval_srs_
      exclusivity.py` (+3).
    - **Backend, step 3 (the actual streaming methods) -- the key design decision**: Architecture's
      existing ladder's rung 0 (`_generate_raw_output_via_exploration`) is an agentic, LangGraph
      tool-calling loop -- the plan text only ever exists as arguments to a final tool call, never
      as incremental tokens, so **there is no stream to forward from it**. New `run_stream`/
      `revise_stream` are therefore deliberately narrower siblings of `_generate_architecture_
      output`/`_revise_architecture_plan_output`, not thin wrappers around them: they start
      directly at the single-shot rung (`provider.stream(...)` instead of `invoke_agent`) and use
      `attempt_agentic=False` for diagram generation too (matching `revise()`'s own pre-existing
      "a human is synchronously waiting" rationale, now applied to `run_stream` as well) -- a
      real, acknowledged trade-off (the agentic exploration tier goes dormant in the default live
      flow) rather than a hidden one; the full agentic-first ladder remains completely unchanged
      and reachable via the existing non-streaming `run()`/`POST /architecture/run`, kept
      reachable in the UI as an explicit "deep exploration mode" toggle (see below). New `{"type":
      "phase", "phase": "...", "label": "..."}` events (`validating`/`usecase`/`diagrams`/
      `rendering`) cover the non-streamable tail -- confirmed by reading the code that this tail
      can be up to ~7 sequential LLM calls (`_complete_usecase_model`'s repair loop,
      `_complete_diagram_models`' focused tier, `_complete_sequence_model`/`_complete_class_
      model`'s own reactive repair loops) plus 3 blocking `subprocess.run` PlantUML/JVM renders in
      `_save_architecture_artifacts` -- wrapped in `asyncio.to_thread(...)` on the streaming path
      specifically so those seconds don't stall the still-open NDJSON response. New routes `POST
      /architecture/run/stream`/`/architecture/revise/stream`, structurally identical to Domain
      Agent's own streaming routes.
    - **Frontend**: `useArchitectureAgentFlow.js`/`ArchitectureAgentFlowContext.jsx` mirror
      Domain's exact item-45 shape (including item 49's awaited-`invalidateAfterCompletion` fix,
      copied verbatim -- this is the single most likely place to reintroduce the "reply disappears
      instantly" bug, so the fix travels with the pattern every time it's copied), plus new
      `runPhase`/`revisionPhase`/phase-start-timestamp state. `ArchitectureAgentFlowProvider`
      mounted in `ProjectWorkspacePage.jsx` **above** `DomainAgentFlowProvider`'s sibling level
      (nested inside it, still wrapping the whole `ResizableWorkspace`) -- load-bearing, not
      cosmetic: the auto-run starts while `stage === "domain"` and the stage then flips to
      `"architecture"`, so only a provider mounted above that switch keeps the in-flight stream
      alive across it. `LiveGenerationView` (`RequirementConversationParts.jsx`) gained optional
      `isFinalizing`/`finalizingLabel`/`phaseStartedAt` props (every existing call site
      unaffected) -- when set, the already-streamed plan text stays frozen on screen (still the
      most useful thing to show) instead of being replaced by a spinner, with a live elapsed-time
      counter (`useElapsedLabel`, ticks every second) so a multi-minute diagram-generation tail
      doesn't read as stuck -- directly targeting the same "static spinner reads as broken" lesson
      item 37 already documented for a much shorter wait. New `ArchitectureAgentChat.jsx` mirrors
      `DomainAgentChat.jsx` (optimistic bubble, instant composer clear, Stop button, phase+elapsed
      banner) with two deliberate differences: no "/" document-mention (Domain-specific), and it
      carries the "deep exploration mode" escape hatch (`ArchitectureRunForm`, moved here from
      `ChatPanel.jsx`, relabeled to name the actual trade-off plainly instead of the old generic
      "prefer a detailed form?") plus a "Start Architecture Agent now" quick-action (since the
      composer otherwise requires non-empty text, and the primary way this stage actually starts
      -- the auto-continue flow -- never touches this chat's composer at all). `ChatPanel.jsx`
      dispatches to it for `selectedAgent === "architecture"`; the architecture-specific dead code
      in `ChatPanel`'s generic path (`useRunArchitecture`/`useReviseArchitecture` instances,
      `showArchitectureForm` state/JSX, the architecture special-case in `submitAgentMessage`) was
      removed -- the hooks themselves stay unused in `useAgentMutations.js`, matching the item-45
      precedent for a superseded mutation.
    - **Frontend, approve-and-auto-continue**: `ResultTab.jsx`'s previously SRS-only
      `isSrsApproval`/`handleConfirmedSrsApprove` generalized into one stage-keyed
      `APPROVE_CONTINUATION_BY_STAGE` config (`requirement -> domain, autoRun: false` /
      `domain -> architecture, autoRun: true`) instead of a second parallel block -- keeps one
      `confirmingArtifactId` state and one `ConfirmDialog` for both transitions.
      `handleConfirmedApprove`: approve -> `selectAgent(nextAgent)` **first** (so the Result panel
      is already showing the live view before the first token lands) -> if `autoRun`, fire
      `handleRunStream(...)` **without awaiting it** (awaiting would hold the dialog's spinner up
      for the entire multi-minute run; the stream's own state already lives in the always-mounted
      provider). No extra pin/selection call needed first -- the approval that just happened
      already reverted every other Enhanced SRS version to pending (step 2's exclusivity), so the
      pin-aware lookup on the backend resolves to exactly the version just approved. Deliberately
      asymmetric with Requirement -> Domain by design, not oversight: Domain Agent gets a
      proactive "do you have something to add?" prompt before its first run (item 41, since human
      guidance there is genuinely useful); Architecture Agent has no comparable need for a human
      pause, so it starts immediately, exactly as this user request asked.
    - **Frontend, version-pinning UI**: `ACTIVE_SELECTION_ARTIFACT_TYPE_BY_STAGE` gained `domain:
      "enhanced_srs"`; `OutputPanel.jsx`'s `NEXT_AGENT_BY_ARTIFACT_TYPE` gained `enhanced_srs:
      "Architecture Agent"`. Two real, small presentation bugs fixed in the same edit: the pill
      previously rendered `artifactType.toUpperCase()` (would have read "Using ENHANCED_SRS
      v2...") -- now uses `ARTIFACT_TYPE_LABELS` ("Enhanced SRS"); and the pill loop previously
      rendered every configured map entry simultaneously, which would overflow the tab bar now
      that a second entry exists -- now filtered to only the entry matching the currently-selected
      stage. Honest note carried into the code comment (not silently shipped as if it were a full
      feature): once Enhanced SRS exclusivity is on, at most one version can ever be `approved`,
      so its radio button always has exactly one candidate -- it's really an "in use" indicator,
      not a live choice, same as the pre-existing `srs` radio already effectively is; the pill is
      the part that actually carries the value here.
    - **Real, live verification, no mocks, through the actual API and a real browser** (isolated
      backend/frontend, `architecture_agent`'s live per-agent LLM override was already
      `llama3:latest`; `domain_agent`'s was temporarily switched from `qwen3-coder:latest` to
      `llama3:latest` for this pass only and restored exactly afterward, same precedent as items
      49/50): raw NDJSON confirmed via a real streamed request first (`curl`-equivalent via
      Playwright's `response.text()`) -- token lines, then all four phase events in the correct
      order (`validating -> usecase -> diagrams -> rendering`), then one `done` with 8 real
      artifact_ids (Architecture Plan JSON+MD, Use Case/Sequence/Class diagram PUML+PNG each).
      Screenshots taken seconds apart during the live run show the decluttered plan text visibly,
      strictly growing (not a before/after diff) -- the actual proof of live streaming ask #3.
      **The real premise check, not just plumbing**: seeded Domain Agent's Enhanced SRS with a
      distinctive marker (a `data_requirements` entry, `ZZQARCH_MARKER_55219`, that the plain SRS
      never had), approved it through the real popup (confirmed the dialog named the right version
      and mentioned Architecture Agent starting automatically), confirmed the chat switched to
      Architecture Agent with the live view already showing (not "No output yet") in the same
      frame, let it run to genuine completion, and grepped the real `architecture_plan_json` for
      the marker -- **present**, direct proof the Enhanced SRS (not the plain SRS) was actually
      used as input. A follow-up real revision request produced a new `architecture_plan_json`
      (v2) that still carried the marker forward and regenerated real v2 diagrams -- the direct
      regression check for the `revise()` Enhanced SRS fix (pre-fix, this would have silently
      reverted to the plain SRS with no marker). Stop button verified cleanly on a second attempt
      (the first attempt's test script had a self-inflicted selector collision -- a test feature
      literally named "Stop Test Feature" made a generic `has_text="Stop"` locator match the
      feature-list button instead of the composer's real Stop control, worth noting as a lesson
      for future live verification naming, not a product bug): clicking the composer's Stop button
      mid-token-stream correctly reverted the UI to idle and left zero new architecture artifacts
      in the backend, confirming the abort genuinely cancels the server-side generation, not just
      the frontend's view of it.
    - **One real, honestly-recorded methodology mistake mid-verification, not a product bug**:
      the first attempt to observe a long-running stream used a *second*, independent Playwright
      browser instance to check on progress -- but a stream's state lives entirely client-side (in
      that specific tab's React state via the flow context), so a fresh page load in a different
      browser session has no visibility into another tab's in-flight fetch. Worse, the FIRST
      script's `browser.close()` after only ~24s of observation aborted the real backend generation
      mid-flight (the same documented "closing the browser cancels an in-flight fetch" gotcha item
      37 already recorded for a different endpoint) -- the run never actually completed on that
      attempt. Corrected by keeping one continuous browser session open and waiting on the real
      HTTP response object (`page.expect_response(...)`, no fixed sleep) until the stream
      genuinely finished, which is what produced the clean, complete verification above.
    - Full backend suite: **305 passed** (up from 300 -- the two pin tests + three exclusivity
      tests from steps 1-2 above). `npm run build` clean throughout. No frontend test framework
      exists in this repo, matching every prior item's own note.

58. **SRS completeness guarantee (any section, not just user_stories) + a genuine single
    continuous ChatGPT-style Requirement Agent chat, replacing the two-component hard-swap.**
    Direct user report: `user_stories` always came out empty on initial generation ("user_stories
    or any other sections can not be empty"), and despite item 34's earlier collapsed-toggle fix,
    the chat still didn't feel continuous across the pre-SRS -> post-SRS transition ("the agent
    chats is disappear once the requirement agent generates the output"). Full plan
    (Explore-agent root-cause + independent Plan-agent design review, which caught a critical
    routing bug before any code was written): `C:\Users\ASUS\.claude\plans\soft-petting-star.md`
    at time of writing.
    - **Root cause, Problem A**: `REQUIREMENT_AGENT_SYSTEM_PROMPT` had exactly one "must not be
      empty, infer from context" rule and it only covered `api_expectations`/`ui_expectations` --
      `user_stories` (and ~10 other fields: `user_roles`, `constraints`, `risks`, `dependencies`,
      etc.) had zero such instruction, and nothing caught it if the real LLM path produced them
      empty (`REQUIRED_KEYS` never required `user_stories` present; `_validate_stable_ids` only
      enforced FR/NFR/AC non-empty).
    - **A critical routing bug the design review caught before implementation**:
      `confirm_conversation_stream` -- the ONLY method the frontend actually calls for confirm --
      does NOT call `_generate_requirement_output`; it duplicates that method's entire
      parse-repair-fallback ladder inline (confirmed by direct read of both). A completeness fix
      applied to only one would never reach the code path the real bug goes through.
    - **Why hard-validating `user_stories` (mirroring FR/NFR/AC) was rejected**: `JSON_REPAIR_
      PROMPT`'s repair mechanism is a syntax fixer -- `"user_stories": []` is already valid JSON,
      so a repair retry has nothing to fix and would just echo the same empty array back, wasting
      an LLM round-trip for zero benefit. The real guarantee had to be a deterministic backstop.
    - **Fix**: new `conversation_engine.ensure_srs_completeness(srs_json)` -- a deterministic,
      no-LLM backstop covering 8 previously-unprotected fields (`user_stories`, `user_roles`,
      `constraints`, `api_expectations`, `ui_expectations`, `input_requirements`, `risks`,
      `dependencies`), grounding every fallback in content already reliably present by that point
      (reuses the existing `_make_user_stories` helper, derives constraints from
      `target_stack`/`architectural_style`, aliases `input_requirements` from
      `data_requirements`) and never claiming an empty `risks`/`dependencies` as "confirmed none"
      -- only "not evaluated," matching this project's own honesty convention. Every backstopped
      field gets a human-readable note appended to `assumptions`. New `RequirementAgent.
      _finalize_srs_json` (shared tail) wires this into **all three** real call sites: `confirm_
      conversation_stream`'s own tail, and both of `_generate_requirement_output`'s exit paths
      (LLM-exception fallback, and the main success/repair/fallback tail) -- fixing the routing
      bug directly. `REQUIREMENT_AGENT_SYSTEM_PROMPT` also gained a generalized "never leave any
      section empty, infer from context" rule covering all ~12 previously-unprotected fields, so
      the real LLM path produces better content on its own, not just a non-empty backstop.
    - **Root cause, Problem B**: `ChatPanel.jsx` hard-swapped between two different React
      components (`RequirementConversationChat` pre-SRS, `RequirementRevisionChat` post-SRS)
      based on `hasOutput`. Item 34's earlier fix (a collapsed-by-default toggle inside the
      post-SRS component) still read as "two conversations stacked" -- a visually separate block
      above a different, sparser feed using different bubble components, not one continuous
      thread.
    - **Fix**: merged `RequirementRevisionChat.jsx` into `RequirementConversationChat.jsx`
      (deleted the former entirely -- confirmed only 4 harmless comment references remained
      afterward) -- one component now renders `conversation.turn_history` in full (existing
      `HumanBubble`/`AgentTurnBubble`, unchanged) followed immediately by the post-SRS `timeline`
      (existing `ChatBubble`, unchanged) as one continuous scroll, with `hasOutput` deciding only
      which composer/banners are active (pre-SRS reply/confirm/quality-gate vs. post-SRS revise),
      never which component renders. `ChatPanel.jsx` collapsed its two `if (selectedAgent ===
      "requirement" && ...)` branches into one.
    - Tests: `tests/test_requirement_srs_completeness.py` (new, 11 -- each backstopped field
      gets honest, grounded content when empty; already-populated fields untouched; notes
      appended to `assumptions`; missing keys entirely treated the same as empty lists; risks/
      dependencies never framed as "confirmed none"), plus a new regression test in `tests/
      test_requirement_conversation.py` (`test_confirm_conversation_stream_backstops_empty_user_
      stories` -- streams a template with NO `user_stories` key at all through the real
      `confirm_conversation_stream` and confirms the SAVED artifact has the backstop applied,
      specifically locking in the routing-bug fix, not just `_generate_requirement_output` in
      isolation). Full suite: **484 passed** (up from 472). `npm run build`: clean (1315
      modules).
    - **Real, live verification, a genuinely new feature (not the already-heavily-revised "Item
      Listing" feature), so the real INITIAL-generation path was actually exercised**: created a
      fresh project/feature ("Wishlist"), drove a real conversation through the real local LLM
      (`qwen3-coder:latest`) to a confirmed SRS -- the real LLM path itself produced 4 concrete,
      feature-grounded user stories (add/remove/view/move-to-cart, each with a real `benefit`,
      not generic filler) with **no** backstop note needed, directly confirming the prompt
      strengthening improved real quality, not just the safety net. Every other previously
      gap-prone field (`user_roles`, `constraints`, `api_expectations`, `ui_expectations`,
      `input_requirements`, `risks`, `dependencies`) was also non-empty in the real saved
      artifact. Separately drove the merged chat through a real browser: confirmed via full-page
      screenshots that the pre-SRS conversation (gap-analysis Q&A, "ASSUMED INSTEAD OF ASKED"
      banner) and the post-SRS activity ("Conversation started"/"Answered questions"/"Confirmed
      SRS"/"Produced SRS (v1)") render as one unbroken scroll with zero page errors, and grepped
      the full page text for every prior collapse-toggle marker ("Show old conversation",
      "original conversation", etc.) -- none present, confirming the toggle mechanism itself is
      genuinely gone, not just visually hidden. Composer correctly showed the post-SRS "Ask
      Requirement Agent for a change..." placeholder once `hasOutput` was true. Test
      project/feature deleted via the real `DELETE /projects/{id}` endpoint afterward; isolated
      backend/frontend verification processes killed.

59. **A real, reported bug: Architecture Agent would run for ~10 minutes then fail with a chat
    banner reading "Architecture Agent failed: " -- literally nothing after the colon.** Direct
    user report with a screenshot. Root-caused by reading the actual code, then confirmed with a
    real (not mocked) reproduction: `httpx.ReadTimeout` -- what `provider.invoke_agent()` raises
    when Ollama accepts a request but never responds within the configured timeout (600s in this
    project's live settings, matching the reported "~10 min" almost exactly) -- is frequently
    raised by httpx's own internals with an EMPTY `str()`. Confirmed directly:
    `httpx.ReadTimeout('')` -> `str()` is `''`. Several call sites in
    `architecture_agent/agent.py` only ever guarded against the LLM call *returning* bad/
    unparseable content -- never against the call **itself throwing** (a transport/timeout
    failure) -- so that exception propagated fully uncaught out of the method, was caught only by
    the route's generic `except Exception as error:`, and rendered as
    `f"Architecture Agent failed: {str(error)}"` = `"Architecture Agent failed: "`.
    - **Fixed 4 real, unguarded call sites** (every other `invoke_agent`/`stream` call in this
      file was already correctly wrapped with a "never raises" contract -- confirmed by reading
      each one before concluding these 4 were the actual gap): `run_stream`'s JSON-repair
      `invoke_agent` call, `_generate_architecture_output`'s single-shot AND JSON-repair
      `invoke_agent` calls, and `_revise_architecture_plan_output`'s single-shot `invoke_agent`
      call. Each now wraps the call itself in its own try/except, treating a transport failure
      exactly like an unparseable response (empty string in, which the existing parse/validate
      step then correctly rejects) -- so the request falls through to the next rung of the
      already-existing reliability ladder (repair -> deterministic fallback) instead of crashing.
      `revise_stream`'s single `provider.stream(...)` call was already correctly guarded (falls
      straight to `_fallback_revise_architecture_plan_json` on any exception) -- confirmed by
      reading it, no change needed there.
    - **Defensive fix, applied consistently across every agent, not just Architecture**: added
      `_readable_error(error)` (`agents.py`) -- `str(error) or f"{type(error).__name__} (no
      further detail was provided by the error itself)"` -- and replaced `str(error)` with it in
      all 25 generic `except Exception as error:` blocks across Requirement/Domain/Architecture/
      Coder's run/revise/streaming routes (done via a small script that only touched lines inside
      an `except Exception` block, verified against the diff to confirm every `except ValueError`
      block -- always a deliberately-authored, already-readable message -- was left untouched).
      This is a second, independent layer of defense: even if a future call site somewhere in
      this codebase has the same "call itself can throw" gap, the user will never again see a
      blank error message, just possibly a less specific one.
    - Tests: `tests/test_architecture_agent_transport_errors.py` (new, 4 -- single-shot call
      exception falls through to repair then fallback; repair call exception falls through to
      fallback; revise's single-shot call exception falls back to
      `_fallback_revise_architecture_plan_json`; a `run_stream`-specific test, mocking
      `store`/`read_json_file`/`project_memory_service` so no real Mongo access happens, confirms
      the real async generator yields a `done` event instead of raising uncaught). All 4 use
      `Exception("")` as the mock's `side_effect` -- deliberately the worst case for this bug (an
      exception with a genuinely empty message), not just any exception. Full suite: **488
      passed** (up from 484).
    - **Real, live verification -- not just mocked units**: confirmed `httpx.ReadTimeout('')`'s
      `str()` really is empty (direct interpreter check). Then built a real "black hole" TCP
      server (accepts a real connection, never responds) and pointed a real `OllamaProvider` at it
      with a short timeout -- producing a **genuine** `httpx.ReadTimeout` with an empty message
      within ~2 seconds (not the real ~10 minutes), through the REAL, unmocked httpx/OllamaProvider
      networking code. Ran the real `ArchitectureAgent._generate_architecture_output` against this
      real failing provider end-to-end: log output showed the exact new warning lines firing
      three times in a row (single-shot call, repair call, and diagram generation's own focused
      single-shot call all hit the same real read-timeout with an empty message) and the method
      still completed successfully with a real, complete fallback plan
      (`implementation_plan` present, an honest `human_approval_note`) -- direct proof the fix
      survives the actual failure mode a real, too-slow/VRAM-mismatched model produces, not just a
      synthetic mock. (Confirmed via `httpx.ConnectError` separately that a plain "nothing is
      listening on this port" failure DOES carry a real message ("All connection attempts
      failed") -- it's specifically the read-timeout case, a request that WAS accepted but never
      answered, that produces the empty message this bug depended on; the black-hole-server
      technique was chosen specifically to reproduce that exact case, not just any connection
      failure.)
    - **Not fixed here, out of scope for this report**: the underlying reason generation can take
      ~10 minutes in the first place -- the screenshot showed `qwen3-coder.max:latest` selected
      for Architecture Agent, already documented elsewhere in this file (see the RESOLVED
      "Architecture Agent taking over an hour" gotcha) as a model that doesn't fit this machine's
      6GB GPU. This fix makes a timeout/failure recover gracefully and legibly regardless of
      model choice; it does not make a mismatched model fast. `llama3:latest` remains the
      documented, actually-fast choice for this machine.

60. **Architecture Agent: zoomable diagrams, a genuinely structured Architecture Plan view, and a
    single approval gate covering the Plan + its 3 diagrams together.** Three direct user
    requests. Investigated via 3 parallel Explore agents + 1 Plan agent, then personally
    re-verified the 4 most load-bearing files directly before implementing. Full plan:
    `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Zoom**: new `react-zoom-pan-pinch` dependency (`^4.0.4`) + new
      `frontend/src/components/common/ZoomableImage.jsx` (generic `src`/`alt`/`className` wrapper
      around `TransformWrapper`/`TransformComponent`, reusable later for the UI/UX Agent's page
      previews though not wired in there now) -- only `ArchitectureDiagramsGallery.jsx`'s existing
      lightbox (click-to-enlarge) gained zoom; the inline 480px thumbnail stays a plain,
      non-zoomable `ImageViewer`. `Modal.jsx` gained an optional `bodyClassName` prop (default
      unchanged `overflow-y-auto`) so only the diagram lightbox opts into `overflow-hidden`,
      preventing the modal's own scroll from fighting drag-to-pan -- none of Modal's ~10 other
      callers were touched.
    - **Structured Architecture Plan view**: `ArchitecturePlanDocumentViewer.jsx` rewritten to
      follow the same pattern `SrsDocumentViewer.jsx` already established -- an explicit section
      order (mirrors `markdown_builder.py`'s own already-decided 17-section human-reading order),
      field-shape-aware layout, `DocumentValue` kept only as the fallback. Found and fixed real,
      previously-silent gaps, not just cosmetic messiness: `document_control` and
      `requirement_interpretation` were rendered in the Markdown output but not AT ALL in the
      React viewer; `validation_plan` and `coder_implementation_tasks` were both already listed
      in `KNOWN_TOP_KEYS` (meaning excluded from the generic fallback loop) but had no actual
      rendering block, so they silently showed nothing; `implementation_plan`'s bespoke block only
      rendered 4 of its 8 real sub-fields, silently dropping `backend.endpoints`, `backend.models`,
      `frontend.routing`, `frontend.components_to_reuse` -- exactly the "AI-executable blueprint"
      content this schema exists for. New `SubSectionList`/`MetadataGrid` helper components (loop
      over an object's own keys rather than hardcoding sub-field names, so a shape drift in real
      LLM/fallback output degrades gracefully instead of silently dropping a field) power
      Requirement Interpretation, Validation Plan, Document Control, and the "Design Views
      (Additional)" catch-all for `context_view`/`logical_view`/`behavior_view` (the 3 sub-views
      with no dedicated Markdown section of their own). Read-only only -- no inline editing was
      added, matching the explicit scope boundary (this component has no `featureId`/`editable`
      props, unlike `SrsDocumentViewer`, and none should be added here).
    - **Single approval gate**: per direct user request, the 3 diagram types (6 artifact rows --
      PUML+PNG each) no longer have an independent approval decision at all -- approving,
      rejecting, or requesting revision on the Architecture Plan cascades the exact same decision
      to them (and to the Plan's own other format, JSON<->Markdown) automatically. New
      `ARCHITECTURE_SIBLING_DIAGRAM_TYPES` constant + `ApprovalService._cascade_architecture_plan_decision`
      (`approval_service.py`) -- joins by same `feature_id` + same `version` (confirmed invariant:
      `_save_architecture_artifacts` computes ONE version via `get_next_version` and reuses it for
      all 8 rows of a single run/revise call), self-gates on artifact_type so it can be called
      unconditionally, writes a synthetic `store.approvals` record per cascaded sibling with
      `approved_by: "system:architecture_plan_cascade"` (never the human's own name -- an honest
      signal this wasn't an independent click, matching this project's "report, don't
      misrepresent" convention) so nothing is a silent gap in `list_feature_approvals`. Also added
      `ArtifactType.ARCHITECTURE_PLAN` to `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES` (confirmed with the
      user first, since it wasn't explicitly requested but is a natural consistency extension
      matching SRS/Enhanced SRS's existing discipline) -- the existing exclusivity revert loop now
      also calls the new cascade helper (with `status=PENDING`) when it reverts an older
      Architecture Plan version, so that old version's own diagrams revert in step instead of
      going out of sync with its now-pending plan. Frontend: `ResultTab.jsx`'s existing
      `UNLISTED_ARTIFACT_TYPES` array (already the mechanism hiding `domain_improvements` etc.)
      gained the 3 diagram types -- removes them from both "All Artifacts" and `GovernancePanel`'s
      "Stage Artifacts" (fed the same already-filtered prop, confirmed no separate query exists).
      `ArchitectureDiagramsGallery.jsx` gained a "Download PUML source" link per diagram (a new
      TEXT-format lookup alongside the existing PNG one) so removing diagrams from the generic
      artifact list didn't lose the ability to download the raw `.puml` source.
    - Tests: `tests/test_approval_architecture_cascade.py` (new, 7 -- approving Plan JSON cascades
      to its Markdown sibling + all 6 diagram rows of the same version; reject and
      revision_requested cascade the same way (parametrized, three-way propagation); a different
      version's siblings are completely untouched; cascaded siblings get an honest synthetic
      approval record while the Plan's own record stays correctly human-attributed; approving a
      NEW Plan version reverts the OLD version's plan AND its own diagrams; the cascade never
      bleeds into unrelated artifact_types). Full suite: **495 passed** (up from 488). `npm run
      build`: clean.
    - **Real, live verification, not just synthetic tests** -- the real TaskFlow "Task Search"
      feature (`feature_244e26d1`, 5 real Architecture Plan versions with real diagrams from
      earlier sessions' work, all still pending going into this verification): confirmed via
      screenshot that a real wheel-zoom gesture inside the lightbox dramatically magnified a real
      diagram (the on-screen +/-/1:1 controls also visible); confirmed via screenshots that the
      rewritten document view renders real generated content for every previously-missing section
      (Document Control's key/value grid, Requirement Interpretation's AC table, Frontend
      Routing's new-routes/nav-links tables, Coder Implementation Tasks' full table, API &
      Interface Plan's endpoint table) against this real feature's real v5 plan; confirmed via the
      real `POST /artifacts/{id}/approval` endpoint that approving v5's Plan JSON cascaded
      `approved` to all 7 real siblings in one call, and that a follow-up approval of v4's Plan
      correctly reverted all 8 of v5's rows back to `pending` (cross-version exclusivity, now
      covering Architecture Plan) while v4's own 8 rows became `approved` -- verified the exact
      synthetic-vs-human approval record distinction directly (v4's own record: `approved_by:
      "human_user"`; a cascaded diagram's record: `approved_by: "system:architecture_plan_cascade"`,
      honest reviewer_comment). Confirmed via a final screenshot that "All Artifacts" correctly
      shows only the 5 Plan-version rows (zero diagram rows, per Task 3's frontend removal) with
      v4 now showing "Approved" (no action buttons, matching the existing `approveLocked`
      convention) and every other version retaining its own independent Approve/Reject/
      Request-Revision controls. This real state (v4 approved, v5 reverted to pending) was left in
      place afterward as genuine, informative verification evidence, matching this project's own
      established convention -- not reverted or cleaned up.

61. **Architecture Plan approval now auto-continues into UI/UX Agent, same popup pattern as
    Requirement->Domain and Domain->Architecture.** Direct user request: approving the Architecture
    Plan should show a confirmation popup offering to start UI/UX Agent automatically, and
    confirming should switch the chat to UI/UX Agent and start it generating immediately. Scope
    confirmed with the user as minimal: reuse UI/UX Agent's existing non-streaming `POST /uiux/run`
    call -- no new streaming backend route, no dedicated chat component (Domain/Architecture Agent
    have those; UI/UX Agent doesn't, and building one is a separate, bigger task not done here).
    Investigated via 2 parallel Explore agents + 1 Plan agent, then personally re-verified every
    critical file directly before implementing.
    - **The one real design problem**: `ResultTab.jsx` needs to *trigger* the UI/UX run
      (`useRunUiux(featureId).mutate({})`, matching how Domain Agent's own auto-start already
      works), but `ChatPanel.jsx` already has its OWN, separate `useRunUiux(featureId)` call for
      the composer's manual-run path. React Query's `useMutation` doesn't dedupe by call site the
      way `useQuery` dedupes by `queryKey` -- two separate calls are two independent mutations
      with independently-tracked pending state. Triggering the auto-run from `ResultTab` would
      have started a real backend generation with **no visible feedback anywhere**, since
      `ChatPanel`'s own instance would never see it as pending.
    - **Fix**: new `frontend/src/components/workspace/UiuxAgentFlowContext.jsx` -- a small shared
      context wrapping exactly one `useRunUiux(featureId)` instance, mirroring
      `DomainAgentFlowContext.jsx`'s provider/consumer shape but much lighter (no streaming state
      to manage, just one mutation object). Nested into `ProjectWorkspacePage.jsx`'s existing
      provider stack (between `ArchitectureAgentFlowProvider` and `CoderAgentFlowProvider`). Both
      `ResultTab.jsx` (trigger) and `ChatPanel.jsx` (composer's pending/Stop-button state, swapped
      from its own local `useRunUiux` call to the shared context) now observe the same mutation.
    - **`ResultTab.jsx`**: `APPROVE_CONTINUATION_BY_STAGE` gained an `architecture` entry
      (`nextAgent: "uiux", autoRun: true`), matching the domain entry's tone/shape.
      `handleConfirmedApprove`'s `autoRun` branch now dispatches on `approveContinuation.nextAgent`
      -- `"architecture"` still calls `handleRunArchitectureStream` (a real stream); `"uiux"` calls
      `runUiux.mutate({})` (a plain, non-streaming, fire-and-forget mutation -- UI/UX Agent has no
      streaming route). The existing generating-view ternary chain
      (`isDomainGenerating`/`isArchitectureGenerating`/`isCoderGenerating` -> `LiveGenerationView`)
      gained an `isUiuxGenerating` branch reusing `LiveGenerationView`'s already-existing
      `isFinalizing` mode (spinner + label + live elapsed timer, no token box -- the same shape
      already used for Architecture's non-streamable diagram-generation tail) with
      `phaseStartedAt={runUiux.submittedAt || null}` (`submittedAt` is a real, standard React
      Query mutation field, confirmed present since `useAgentMutation` returns `{ ...mutation,
      stop: ... }` unmodified). No new component needed.
    - **No backend changes**: `UIUXAgentRunRequest` already makes every field optional, so
      `runUiux.mutate({})` -> `POST /uiux/run` with an empty body is already a valid,
      real-run-triggering request. `uiux_agent.run()`'s prerequisites (approved SRS + approved
      Architecture Plan) are reliably already satisfied the moment this new transition fires,
      since Architecture Plan approval is itself gated behind SRS approval in the pipeline
      sequence -- safe to always attempt with no extra guarding.
    - No automated frontend test suite exists in this repo (per every prior item's own note) --
      `npm run build` clean; verified live only.
    - **Real, live verification, not synthetic** -- the real TaskFlow "Task Search" feature
      (`feature_244e26d1`, already carrying real Architecture Plan history from item 60's own
      verification): rejected the then-approved v4 Plan via the API to unlock v5 (item 40's
      `approveLocked` UI correctly disables Approve on a pending version while another is
      approved -- confirmed hitting this for real while setting up the test, not a bug), then
      drove the real popup flow through an actual browser: clicking Approve on v5 showed the
      popup reading "Approve this Architecture Plan and start UI/UX Agent? Approving v5 makes it
      the Architecture Plan this feature uses going forward... UI/UX Agent will start
      automatically and generate page-level UI metadata, component code, and preview screenshots
      -- watch it live in the Result panel." -- confirmed via screenshot, word-for-word as
      designed. Clicking "Approve & Continue" correctly switched the agent pill to "UI/UX"
      (confirmed via `page.get_by_role(...)`, not just a visual guess). **A real, honest test-
      methodology gotcha hit while verifying**: the first attempt closed the Playwright browser
      right after confirming, which aborted the in-flight, not-awaited `runUiux.mutate({})`
      request before the backend could complete it (the same "closing the browser cancels an
      in-flight request" class of gotcha already documented elsewhere in this file for other
      streaming/mutation flows) -- confirmed via the API afterward showing zero `ui_*` artifacts
      had been created. Not a bug in the implementation (the approval + navigation had already
      genuinely completed by then); re-triggered the exact same route directly
      (`POST /uiux/run` with `{}`, identical to what the UI's own click sends) and let it run to
      completion in the background instead. Result: a real, complete UI/UX Agent run --
      `ui_metadata` (JSON+Markdown), `ui_integration_manifest`, 2 `ui_component_code` artifacts,
      and a real `ui_preview_screenshot` PNG -- confirmed via a final screenshot showing the
      actual chat feed ("Started · UI/UX (no comment provided)" -> "UI/UX Agent: Produced UI
      Metadata, UI Integration Manifest, Component Code, Preview Screenshot (v1)") and the Result
      panel's real "Page Previews (1)" thumbnail (a genuinely rendered Task Search page with a
      search input and example task cards). This real state (Architecture Plan v4 rejected, v5
      approved, real UI/UX v1 artifacts pending review) was left in place afterward as genuine
      verification evidence, matching this project's established convention.

62. **Architecture Agent: reliable, explicit revision of ANY part of the plan via chat, mirroring
    the Requirement Agent's own proven fix.** Direct user request: the human must be able to
    explicitly add, edit, or remove anything on the generated Architecture Plan by prompting the
    Architecture Agent in chat, "just like the requirement agent or ChatGPT/Claude." Investigated
    via 2 parallel Explore agents + 1 Plan agent, then personally re-verified the two real
    revision call sites directly -- confirmed a real, serious bug, not a UX polish item: both
    `_revise_architecture_plan_output` and `revise_stream` asked the LLM to retype the ENTIRE
    `architecture_plan_json` object in one shot (`ARCHITECTURE_REVISION_SYSTEM_PROMPT` literally
    said "Return the full revised architecture_plan_json object only"). On any parse/validation
    failure, both fell through to `_fallback_revise_architecture_plan_json`, which clones the
    existing plan and changes only `revision_metadata`/one generic coder task/
    `human_approval_note` -- every substantive section left byte-for-byte unchanged. A real,
    already-generated sample (`task_search_architecture_plan_v5.json`) was itself proof this
    happened in practice: its own `revision_metadata.fallback_used: true` showed a real past
    revision request was silently dropped this exact way -- structurally identical to the bug
    already found and fixed for the Requirement Agent (items 35/57).
    - **The fix**: adapted the Requirement Agent's proven pattern (a small "operations" plan + a
      deterministic Python patcher) but generalized for the Architecture Plan's much more deeply
      nested schema (17 top-level keys, some 2-3 levels deep, e.g.
      `implementation_plan.backend.endpoints`) via **dotted-path targeting + runtime-shape
      detection**, rather than the SRS patcher's flat field-name-based dispatch. New file
      `app/agents/architecture_agent/revision_patcher.py`: `_resolve_path(root, dotted_path)`
      walks a dotted path, returning `(value, parent, key)` or a `_MISSING` sentinel if any
      segment doesn't exist (never auto-creates a missing section -- a genuinely missing path
      means the LLM named something that isn't there, reported as unmatched, never guessed).
      `apply_architecture_revision_operations(plan, operations)` dispatches by the **runtime
      type** found at the resolved path: list-of-strings (add/remove/modify by exact-then-
      substring text match), list-of-dicts (add/remove/modify via a 3-tier matching cascade --
      exact identifying-key match -> exact text match -> substring containment checked against
      EVERY field's text, not just one identity field, so a distinctive quote from any part of an
      item, e.g. a file's `purpose` text and not just its `path`, can still find it; `add` with a
      bare string value gets wrapped into a dict via `_infer_wrap_key`, a majority-vote over
      existing sibling keys), nested-dict (set/modify-only shallow merge; add/remove rejected with
      a steering message toward a specific nested list path), and scalar (set/modify, treated as
      synonyms, matching the same fix item 57 already made for the SRS patcher). Every operation
      wrapped in its own try/except so one bad operation never breaks the rest; `applied`/
      `unmatched` always both returned as human-readable strings -- never a silent no-op.
      **Structural safety property**: since this dispatch never deletes a top-level or
      `design_views` dict KEY (only list items by index, or scalar/dict VALUES), every key
      `REQUIRED_ARCHITECTURE_PLAN_KEYS`/`REQUIRED_DESIGN_VIEW_KEYS` requires stays present after
      patching, by construction -- no separate "did we break required structure" check needed.
    - **Prompt** (`prompt.py`): rewrote `ARCHITECTURE_REVISION_SYSTEM_PROMPT`/
      `build_architecture_plan_revision_prompt`, mirroring `REQUIREMENT_REVISION_SYSTEM_PROMPT`'s
      proven structure -- explicit "you are NOT retyping the whole plan" framing, the operations
      schema with real anchor paths (`assumptions`/`constraints`/`risks`/`dependencies`,
      `document_control.target_stack`, `feature_overview.*`,
      `design_views.interface_view.api_endpoints`, `design_views.data_view.data_entities`,
      `implementation_plan.backend.*`, `implementation_plan.frontend.*`,
      `implementation_plan.implementation_order`/`constraints`, `coder_implementation_tasks`,
      `traceability_matrix`), the same anti-padding rule (a plural/empty-section request means
      multiple real, distinct items -- one add per genuinely-implied item, never manufactured
      beyond what's implied), the same target-quoting rule, plus one new rule for this schema's
      added complexity ("add on an object-list field needs a full object shaped like its
      siblings, not a bare string -- unless the field's items are plain strings").
    - **Wiring -- both real call sites**, per this project's own hard-learned lesson (a fix
      landing in only one of `revise_stream`/`_revise_architecture_plan_output` silently never
      reaches the one the frontend uses): new `_parse_architecture_revision_plan`/
      `_apply_architecture_revision_plan` (mirroring `RequirementAgent`'s
      `_parse_revision_plan`/`_apply_revision_plan` exactly -- `_apply_architecture_revision_plan`
      sets `revision_metadata` with `applied_changes`/`unmatched_operations`, and appends
      unmatched notes plus a zero-operations honest note to the plan's own `assumptions` array)
      wired into both methods, replacing only the "how do we get `revised_architecture_plan_json`"
      block in each. New ladder: LLM call (already had item 59's transport-failure guard, kept)
      -> parse the small plan (deliberately NOT the full-document
      `_parse_and_validate_architecture_plan_json`, which stays unchanged and unused by revision
      going forward) -> apply via the patcher -> on a PARSE failure specifically, one JSON-repair
      retry -> if that also fails, fall through to the existing, unchanged
      `_fallback_revise_architecture_plan_json` (now a much rarer true last resort). The
      diagram-regeneration/validation/build tail (`_ensure_implementation_plan` ->
      `_complete_usecase_model` -> `_complete_diagram_models(attempt_agentic=False)` -> the
      existing tolerant `_validate_full_output` try/except -> markdown/PUML build -> save) is
      confirmed unchanged and already fully agnostic to how the revised dict was produced -- a
      surgical change, not a rewrite. For `revise_stream`, the streamed tokens are now the small
      operations plan instead of the whole document -- a real UX improvement on its own (a human
      sees a short, readable plan typing in, not an 800-line JSON dump).
    - Tests: `tests/test_architecture_revision_patcher.py` (new, 23 -- no-LLM, hand-built
      real-shaped fixture: `_resolve_path` top-level/nested/missing-segment; string-list
      add/remove/modify with exact/substring matching and unmatched-is-reported; object-list add
      with a full dict value; object-list add with a bare string value confirming
      `_infer_wrap_key`; object-list remove/modify by name/substring-of-a-non-identity-field
      (`purpose`), confirming partial-dict modify only overwrites given fields; scalar set/modify
      equivalence; dict-leaf set/modify merge vs. add/remove correctly rejected; malformed
      operations skipped not raised; a full-plan smoke test applying several operations across
      different shapes confirming every required top-level/design-view key survives; original
      plan never mutated in place). `tests/test_architecture_agent_revision_ladder.py` (new, 4 --
      a valid operations plan applies via the patcher with every OTHER section of the plan left
      genuinely untouched, proving this is a patch not a retype; a parse failure falls through to
      the JSON-repair rung which then succeeds; both attempts failing falls back to the unchanged
      `_fallback_revise_architecture_plan_json`; `revise_stream` streams the small operations plan
      and the resulting artifact reflects the applied change). Full suite: **522 passed** (up
      from 495).
    - **Real, found-during-testing design refinement**: the first version of `_find_matching_index`
      only ever substring-matched against a SINGLE identity field per item (e.g. just a file's
      `path`), so a target quoting a different field (e.g. a file's `purpose` text) never matched
      even though it was a perfectly reasonable thing for the LLM to quote -- caught by this
      session's own test for exactly that case. Fixed by adding `_item_full_text` (joins every
      field's text, used only for the substring-containment tier, not the stricter exact-match
      tiers) so a distinctive quote from ANY field can still find its item.
    - **Live verification against the real TaskFlow "Task Search" feature** (`feature_244e26d1`,
      already carrying real Architecture Plan history including a real past
      `fallback_used: true` version -- direct evidence of the bug this fixes): restarted context
      confirmed live via the already-running `--reload` backend, drove a real revision through
      `POST /architecture/revise/stream` with the comment "Add a constraint that search must be
      rate-limited to 10 requests per minute" against the real, approved v5 plan. Confirmed: the
      streamed tokens were a small ~68-line JSON operations plan (not an 800-line document);
      the saved v6 artifact's `revision_metadata.applied_changes` reads exactly `"Added to
      implementation_plan.constraints: Search must be rate-limited to 10 requests per minute"`
      and `unmatched_operations: []` -- direct proof the request was actually applied, not
      silently dropped; every untouched section (both original `constraints` entries, both
      backend endpoints, both data entities, the scaffold-awareness implementation_plan
      constraints, all 3 assumptions) survived with full, non-degraded content; and all 8 v6
      artifacts (Plan JSON+Markdown + 6 diagram files) saved successfully, confirming diagrams
      still regenerate correctly from the patched plan. This real v6 state (pending human review)
      is left in place afterward as genuine verification evidence, matching this project's own
      established convention.

63. **UI/UX Agent rewritten to generate HTML + Tailwind CSS (not React/JSX), with an instant
    server-less live preview, and its output repositioned as a VISUAL REFERENCE for the Coder
    Agent instead of literal code to import -- fixing a real, confirmed "empty UI" bug as a
    structural side effect of the architecture change, not a separate patch.** Direct user
    request, 5 parts: generate UI in HTML+Tailwind; preview it "like the Coder Agent" (a real,
    interactive-feeling Output-panel preview); Coder Agent must use UI/UX output as a visual
    reference, not literal reuse; fix a reported bug -- an **empty** page image for "Item Listing
    (CRUD)" in "Sample E-commerce"; the UI must be accurate and visually strong, grounded in the
    Architecture Agent's real output.
    - **Root-caused the empty-UI bug directly, not by guessing**: downloaded and viewed the real
      screenshot artifact -- it showed literally "Unknown state." and "No data available."
      Reading the actual generated JSX confirmed why: `ItemListingTable.jsx`/`ItemDetailsModal.jsx`
      only implemented explicit branches for `props.state === 'loading'/'error'/'success'`,
      falling back to a generic placeholder for anything else -- and the page's declared `states`
      metadata was `["idle","loading","error","success"]`, with "idle" never implemented by
      either component. Whatever `mock_props` ended up selected for the page-level preview
      evidently picked a state outside `{loading,error,success}`. A second, related bug was also
      confirmed in the same real artifacts: every component's `"props": {"propName": "short
      description of the prop"}` was the LITERAL, unfilled placeholder text shown as an example
      in the prompt's own JSON-shape sample, echoed back verbatim (the same "model anchors on the
      shown JSON shape" anti-pattern already fixed elsewhere in this codebase, e.g. items 55/32).
    - **The architectural fix structurally eliminates the whole bug class**: switching to static
      HTML + Tailwind with ONE canonical, always-fully-populated view baked directly into the
      markup removes state-branching from generated output entirely -- there is no unhandled
      branch left to fall into, because there is no branch at all.
    - **New content model**: components remain the reusable unit (preserves real cross-feature
      reuse, e.g. `LoginForm` across Login/Signup) but are authored as a single self-contained
      HTML fragment with realistic, fully-populated example content baked in, grounded in the
      Architecture Plan's real `design_views.data_view` entity fields. Page assembly is a NEW,
      deterministic (no-LLM) step (`page_html_builder.py`) -- pure string concatenation wrapping
      a page's ordered fragments in a full `<!DOCTYPE html>` document with a default shell
      (`<body class="min-h-screen bg-gray-50">` + a centered `<main>`); this step can never fail
      or hallucinate, which is precisely what guarantees every page always renders something
      complete. `props: {"propName": "..."}` renamed to `content_elements: ["..."]` (a list of
      real content descriptions) -- breaks the placeholder-echo anchor bug by removing the exact
      key/shape being copied. New `metadata_validator.py` check rejects any `content_elements`
      entry that's empty or a literal echo of the prompt's own example text. `states` stays in
      the schema (still a cheap, useful structural check) but is demoted to informational-only --
      it tells the Coder Agent which real interactive states the eventual working app needs,
      while the static reference always shows the one fully-populated "success" view.
    - **New quality gate + bounded repair, replacing the old render-failure repair loop**:
      `component_generator.detect_placeholder_content` (a cheap, deterministic phrase-based
      check -- "no data available", "unknown state", "lorem ipsum", etc.) runs on every generated
      fragment; `UIUXAgent._generate_component_with_quality_gate` retries up to
      `MAX_CONTENT_QUALITY_REPAIR_ATTEMPTS = 2` with the exact violation fed back, then raises
      `ComponentGenerationError` if it still fails -- an artifact a human reviews and the Coder
      Agent later reads as a reference must never silently contain a placeholder/empty state.
    - **Rendering simplified, not just changed**: `preview_renderer.py` now screenshots an
      already-assembled HTML document instead of mounting live JSX via Babel + React -- the
      `react.production.min.js`/`react-dom.production.min.js`/`babel.min.js` vendor files
      (~2.6MB) and all JSX-mounting logic were deleted from this path entirely (and from disk).
      This PNG remains a secondary, best-effort artifact (feeds the existing "Page Previews"
      thumbnail gallery, unchanged) -- the PRIMARY preview is now the raw HTML itself.
    - **"Preview like the Coder Agent" was deliberately NOT built as a Docker dev server**:
      static HTML+Tailwind has zero server-rendering/data-fetching/build-step surface area --
      nothing a container would give a static document that a browser can't already do by
      parsing a self-contained HTML string. Confirmed via direct reading that `GET
      /artifacts/{id}/content` already serves any non-JSON/PNG format as raw text with **zero
      backend changes needed**, and `ArtifactFormat.HTML` already existed in `enums.py`, defined
      but unused anywhere -- clearly reserved for exactly this. New `ArtifactType.UI_PAGE_HTML`
      (new enum member, not a repurposed unused `UI_DESIGN` -- avoids a silent collision with
      whatever that may have been reserved for) is the assembled full-page artifact; the Tailwind
      Play-CDN vendor script (confirmed via direct inspection: a self-scanning IIFE, no companion
      block needed) is inlined by file content directly into each page's `<head>`, making every
      page artifact fully self-contained/downloadable/portable with zero network dependency.
    - **Frontend**: real, confirmed-by-reading finding -- `OutputPanel.jsx`'s "Preview" tab had
      **no stage gating at all** before this change (`selectedAgent` was already destructured but
      never used for this branch; clicking Preview always showed the Coder Agent's Docker
      `PreviewPanel` regardless of stage) -- fixed with one small additive branch
      (`selectedAgent === "uiux" ? <UiuxPreviewPanel/> : <PreviewPanel/>`), not new gating
      infrastructure. New `UiuxPreviewPanel.jsx`: a page selector (mirrors the existing PNG
      gallery's `latestByFile`-style dedupe) + `<iframe srcDoc={content}>` fetched via the
      already-generic `useArtifactContent` hook -- no new backend route needed. `UiMetadataViewer.jsx`
      updated for the `content_elements` list shape (was rendering `props` as a dict of key:value
      rows -- would have crashed/shown nothing on the new list shape). `artifactTypeMeta.js`
      gained the new type/stage entries and an `"html"` `pickViewer` branch.
    - **Coder Agent: visual reference, not literal reuse.** Renamed `read_ui_component` ->
      `read_ui_component_design`; added new `read_ui_page_design(page_id_or_route)` for full-page
      layout context. **Two real format filters silently break reuse if missed** (confirmed by
      reading both): `tools.py`'s `_find_approved_component_artifact` and `agent.py`'s
      `_load_existing_approved_component` (UI/UX Agent's own cross-feature reuse-by-name lookup)
      both hard-coded `ArtifactFormat.CODE` -- fixed to `HTML` in both; missing either doesn't
      crash, it just silently falls through to "no approved component found, generating a fresh
      one instead" (a quiet capability loss, not a loud failure). **6 real locations in
      `coder_agent/prompt.py`** rewritten to a consistent "visual reference -- read it, then
      write real TSX that faithfully matches it; never `dangerouslySetInnerHTML`" framing (2 were
      found only by a Plan agent's direct-read validation pass, beyond the 2 I'd already found
      personally: the prop-wiring completeness rule, and the integration-manifest context text
      injected into the shared planner/coding prompt). Also found and fixed while sweeping every
      remaining `read_ui_component`/`props` reference project-wide: a `_TOOL_ACTIVITY_LABELS`
      dict entry in `coder_agent/agent.py` (would have silently stopped showing a friendly label
      for this tool call in the live activity feed), a literal instruction string inside
      Architecture Agent's own deterministic fallback `implementation_plan` builder (would have
      told the Coder Agent the OLD "reuse verbatim via read_ui_component" instruction inside a
      real generated Architecture Plan), and several doc-comment-only references. `integration_manifest_builder.py`'s
      `expected_props` -> `content_elements`. `apply_design_system_patch`'s `"props":
      list((component.get("props") or {}).keys())` was a confirmed **real crash** waiting to
      happen (`AttributeError` -- `content_elements` is a list, not a dict) the moment a
      non-reused component under the new schema got approved; fixed to `"content_elements":
      component.get("content_elements") or []`. `_placeholder_mock_props` deleted outright (fully
      dead code -- no mock_props concept survives under the new design).
    - Tests: `tests/test_uiux_page_html_builder.py` (new, 6 -- deterministic assembly, fragment
      order, empty-fragment skipping, inlined-not-referenced Tailwind script, page_id fallback,
      never fails on its input), `tests/test_uiux_component_generator.py` (new, 8 -- single-marker
      parse, the exact real placeholder phrases confirmed in the broken artifacts correctly
      flagged, Lorem Ipsum flagged, real content allowed through), `tests/
      test_uiux_agent_quality_gate.py` (new, 3 -- passes-first-try/gets-repaired/exhausts-repair-
      and-raises, mocked component_generator, no real LLM), `tests/test_uiux_metadata_validator.py`
      (+5 -- empty/missing `content_elements` fails, the exact real placeholder-echo string fails
      with "placeholder" in the error, real content passes; 2 pre-existing tests' fixtures updated
      for the new field), `tests/test_uiux_component_reuse.py` (rewritten for HTML/`.html` fixtures,
      the 2 dead `_placeholder_mock_props` tests deleted), `tests/test_uiux_integration_manifest_builder.py`
      (golden fixture rewritten for `content_elements`), `tests/test_coder_tools.py` (renamed +2,
      +2 new `read_ui_page_design` tests), `tests/test_coder_prompt.py` (1 stale substring-lock
      test rewritten to match the new prompt wording, preserving its original intent). Full suite:
      **578 passed** (up from 522), only 5 pre-existing Docker-daemon-unavailable tests deselected
      (confirmed via direct `docker ps` -- environmental, unrelated to this change).
      `npm run build` clean.
    - **Real, live verification against the exact reported feature** (`feature_94701501` "Item
      Listing (CRUD)" in `proj_34e07440` "Sample E-commerce"): a real run initially hit a
      `ReadTimeout` -- root-caused to `uiux_agent`'s live per-agent LLM override being set to
      `qwen3-coder:latest` (a 30.5B model that doesn't fit this machine's 6GB GPU, the same
      already-documented VRAM-mismatch class as items 49-51) -- confirmed directly via `ollama ps`
      showing only ~3.8GB of the model's ~22GB actually in VRAM. Temporarily switched the
      override to `llama3:latest` for the run (same "switch, verify, restore exactly" precedent
      as items 49-51), which completed successfully. **Direct inspection of the real output**:
      the assembled page HTML contains genuinely populated content ("Item Name $12.99 Quantity: 5
      Category: Electronics", "Another Item $9.99 Quantity: 3 Category: Clothing", a real Item
      Details panel, real "Page 1 of 5" pagination) with zero occurrences of "unknown state"/"no
      data available" anywhere in 409KB of real HTML; `content_elements` in the new metadata
      shows real, specific values ("item name", "price", "quantity", "category") with no
      placeholder echo. **Confirmed live in an actual browser** (Playwright, not just curl):
      navigated to the real feature's UI/UX stage, clicked the new Preview tab, and the iframe
      rendered the exact same real content instantly (screenshot confirmed: a styled Item List
      card grid, Item Details panel, Previous/Next pagination -- no Docker, no build step,
      the "All Artifacts" list correctly showing new "Component Design"/"Page Design" labeled
      rows, each independently approvable per the existing convention). Approved the new v2
      metadata + 3 components + page HTML through the real API, then **directly exercised the
      real, unmocked Coder Agent lookup functions** (`_find_approved_component_artifact`,
      `_find_approved_page_html_artifact`) against this real data in a live Python session --
      all 3 components and the page found correctly by name/route, real HTML content read back
      verbatim -- proving the full generation-to-consumption chain end-to-end, not just each half
      in isolation. Restored `uiux_agent`'s LLM override back to `qwen3-coder:latest` exactly
      afterward. This real v2 state (5 artifacts approved, metadata/manifest/markdown/screenshot
      still pending) is left in place as genuine verification evidence, matching this project's
      own established convention.

64. **UI/UX Agent follow-up: single-artifact approval (Preview Screenshot only), real image
    placeholders instead of broken `<img>` tags, and consistent, deliberate color usage.** Direct
    follow-up to item 63, based on the user's own screenshot of the real generated output. Four
    asks: (1) hide every UI/UX artifact from human approval except the Preview Screenshot; (2) the
    screenshot showed broken-image icons with visible `alt` text ("Item Image") -- fix at the
    source; (3) "accurate and nice UI" (folded into #4); (4) more deliberate, consistent color.
    - **Approval cascade, mirroring item 60's Architecture Plan cascade exactly, anchored on
      `UI_PREVIEW_SCREENSHOT` instead of `ARCHITECTURE_PLAN`**: investigated by reading
      `approval_service.py`/`graph_orchestrator_service.py`/`deriveStageStatus.js`/
      `ArtifactList.jsx`/`ResultTab.jsx`/`GovernancePanel.jsx` directly (an Explore agent stalled
      twice, abandoned in favor of direct reading). Key confirmed facts: `graph_orchestrator_
      service.resume()` is completely artifact-agnostic (only needs `feature_id` + a status
      string) -- switching which artifact type gates a stage needs zero graph changes.
      `apply_design_system_patch`'s trigger check WAS artifact-type-specific though (fired only
      when `UI_METADATA` was the artifact directly approved) -- widened to also fire on
      `UI_PREVIEW_SCREENSHOT`, since the method already resolves `UI_METADATA` by version
      internally regardless of what triggered it. New `UIUX_SIBLING_ARTIFACT_TYPES`/
      `_is_uiux_screenshot_type`/`_cascade_uiux_screenshot_decision` (mirrors `_cascade_
      architecture_plan_decision` exactly -- same synthetic `approved_by:
      "system:uiux_screenshot_cascade"` convention, same never-raises contract).
      `UI_PREVIEW_SCREENSHOT` added to `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES` (only one version ever
      "the approved one," matching `ARCHITECTURE_PLAN`'s own reasoning) with the matching
      revert-cascades-too branch. Frontend: `ResultTab.jsx`'s `UNLISTED_ARTIFACT_TYPES` gained
      `ui_metadata`/`ui_integration_manifest`/`ui_component_code`/`ui_page_html`;
      `artifactTypeMeta.js`'s `STAGE_GATING_ARTIFACT.uiux` repointed to `ui_preview_screenshot` --
      confirmed no other frontend logic needed to change, since `resolveGatingArtifact`/
      `approveLocked`/`ArtifactRow` are all already generic over whatever `STAGE_GATING_ARTIFACT`
      names. **Found a real, already-stale warning while reading `GovernancePanel.jsx`**:
      `APPROVAL_WARNINGS.uiux` referenced a "UI/UX components awaiting review" section already
      retired per item 31 -- rewritten to accurately describe the new cascade.
    - **Image placeholders**: root-caused directly to `HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT`
      rule 6 ("`alt` text on every `<img>`"), which never forbade a fake external URL like
      `https://example.com/item-image.jpg` that can never resolve. Rewritten to forbid `<img
      src="...">` entirely for mock content and instead use a decorative placeholder box (a
      `<div>` with fixed size/`bg-gray-200`/`rounded-lg` + a centered inline SVG "photo" icon,
      given as a literal copy-adaptable example in the prompt, matching this prompt's own
      established style of concrete examples over abstract instructions).
    - **Consistent color, not just "more color"**: real risk identified and designed around --
      N independent per-component LLM calls on the same page could each pick a different accent
      color. Fixed by deciding `color_theme` ONCE at the metadata-generation step (new top-level
      `ui_metadata_json.color_theme` field, e.g. `"indigo"`) and threading it explicitly through
      every subsequent component-generation call (`agent.py` -> `component_generator.generate` ->
      `build_component_generator_user_prompt`), rather than hoping independent calls agree --
      mirrors this project's own established "decide once, thread deterministically" philosophy
      (the same reason `page_html_builder.py` exists as one deterministic assembly step). Defaults
      to `"indigo"` if the model omits the field -- deliberately no new validator/repair-loop
      surface for something this low-stakes. `HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT` rule 4
      rewritten with concrete Tailwind guidance: the accent color for primary buttons/links/active
      states; semantic (non-accent) colors for price/success (green)/destructive (red)/warning
      (amber); real card backgrounds+shadow+rounded-corners so sections read as distinct blocks;
      colored badges/chips for status/category content.
    - Tests: `tests/test_approval_uiux_cascade.py` (new, 9 -- mirrors `test_approval_architecture_
      cascade.py`'s exact structure: approving the screenshot cascades to metadata/manifest/
      components/page-html of the same version; reject/revision_requested cascade the same way; a
      different version untouched; a SECOND screenshot of the same version (multi-page case) also
      cascades; cascaded siblings get the honest synthetic `approved_by`; approving a new
      screenshot version reverts the old version's screenshot AND its whole cascade; never bleeds
      into unrelated types; `apply_design_system_patch` fires from the widened trigger). Full
      suite: **587 passed** (up from 578), zero regressions. `npm run build` clean.
    - **Real, live verification against the same real feature** (`feature_94701501` "Item Listing
      (CRUD)" in `proj_34e07440` "Sample E-commerce"): a real v3 generation run initially hit the
      SAME reliability ladder's final rung 3 times in a row (`UI/UX Agent could not produce valid
      ui_metadata_json after one repair attempt: pages must be a non-empty list`) -- root-caused,
      NOT to this session's own changes, by directly reproducing it: a standalone script using the
      plain SRS succeeded twice; the SAME script using the feature's real, approved Enhanced SRS
      (which the real API path uses by default, `use_enhanced_srs_if_available=True`) reproduced
      the exact failure -- a genuinely larger/more complex prompt this local model
      (`llama3:latest`) is less reliable against, an already-existing characteristic unrelated to
      this session's prompt-text additions. Worked around for verification purposes by passing
      `use_enhanced_srs_if_available: false` (a real, pre-existing request field), which completed
      cleanly. **Direct proof of every fix**: the real v3 metadata correctly included
      `"color_theme": "indigo"`; a direct, isolated real-LLM generation of the "Item Details"
      component (the exact one whose OLD version had the reported broken image) produced a
      decorative placeholder box with the literal example SVG (zero `<img>`, zero
      `example.com`), `text-indigo-600` used consistently for both the heading and a category
      badge, `text-green-600` for the price (semantic, not accent), and real
      `bg-white shadow-sm rounded-lg` card styling -- confirming all three prompt-level fixes work
      together in one real generation. Approved the real v3 Preview Screenshot through the real
      API and confirmed via direct store inspection that all 6 v3 artifacts (metadata JSON+MD,
      manifest, component, page-html, screenshot) flipped to `approved`, with the screenshot's own
      record honestly attributed to the real caller and every cascaded sibling correctly stamped
      `system:uiux_screenshot_cascade`; confirmed `design_system.json` was patched with the new
      "Pagination" component using the correct `content_elements` list shape (not the old
      dict-`.keys()` crash). **Confirmed live in an actual browser**: "All Artifacts" for this
      stage now shows exactly 3 rows, all "Preview Screenshot" (v1/v2/v3) -- zero metadata/
      manifest/component/page-design rows -- with v3 correctly locked as "Approved" (no action
      buttons) and v1/v2 still independently Pending/actionable; the version selector correctly
      reads "v3 -- approved"; the "Page Previews" gallery incidentally shows a real, visible
      before/after (v1's original broken "Unknown state."/"No data available" thumbnail, left in
      place as historical evidence, right next to the clean v2/v3 thumbnails). Restored
      `uiux_agent`'s LLM override back to `qwen3-coder:latest` exactly afterward (same
      "temporarily switch, verify, restore exactly" precedent as items 49-51/63). This real v3
      state (approved, cascaded) is left in place as genuine verification evidence, matching this
      project's own established convention.

75. **QA Agent rebuilt from a narrow, LLM-disabled stub into a real Unit/Integration/Regression
    test-writing-and-running agent, with a full report UI and a live streaming chat -- mirroring
    the Security Agent's own recent trilogy of upgrades.** Direct user request, with a reference
    document describing an earlier sample QA Agent implementation and a link to
    `origin/tharuka_m`'s own parallel QA Agent branch for inspiration. Requirements, in the user's
    own words: write Unit/Integration/Regression test cases for the Coder Agent's generated
    feature; execute them automatically and report real per-test detail -- what was written, how
    many, the inputs, which unit/file/function/line each test targets, the real executed output,
    with suggestions; a clean, standard report UI, not raw JSON; support both Ollama and API
    models; and a real, token-streaming, history-preserving chat to discuss results and ask for
    help with failures.
    - **Investigated both the current local implementation and `origin/tharuka_m` before
      designing anything** (two parallel Explore agents): the local `testing.py` only ever
      discovered `lib/`/`models/` `.ts` files (React pages/components and API routes were
      explicitly out of scope, since Node's built-in test runner can't render a DOM and this
      pipeline doesn't install jsdom), generated tests via two regex-detected shapes with a
      deterministic string template, and `agent.py:89` hardcoded `invoke_llm=None` -- the real
      `prompt.py` LLM path was dead code, never reached. Execution parsed Node's TAP output for
      aggregate pass/fail/skip counts only -- no per-test name, inputs, or expected/actual detail
      was ever captured. `origin/tharuka_m` was meaningfully ahead in exactly one reusable piece
      (a real LLM-backed generator making a genuine provider call instead of hardcoded `None`) --
      worth borrowing the *pattern*, not the code: its own executor still only extracted aggregate
      counts from Jest's `--json` output, throwing away the real per-test `assertionResults[]`
      array this request actually needed; its Python/pytest support isn't applicable to this
      pipeline (every generated project is Next.js/TypeScript, confirmed repeatedly this session);
      `qa_agent/api.py`/`report_writer.py` were unimported dead files.
    - **A deliberate, stated scope limit, carried over from the local implementation and extended
      to the same "honest gap, not silently unclaimed" convention this project already uses**:
      real component/page (`.tsx`) rendering tests (jsdom + React Testing Library) stay out of
      scope for this pass -- `lib/`, `models/`, and `app/api/**/route.ts` Route Handlers (which
      use Web-standard `Request`/`Response`, no DOM needed) are the real testable surface.
      `.tsx` files are discovered and reported as an honest `out_of_scope_modules` list on the
      report, matching Security Agent's own scanners' established convention.
    - **Switched from `node:test` to Jest**, specifically because Jest's built-in `--json` output
      already contains real per-test structured results (`testResults[].assertionResults[]`:
      `title`/`status`/`failureMessages`/`duration`) with zero extra parsing infrastructure --
      exactly what makes "real per-test-case output, not just aggregate counts" achievable. The
      old docstring's "no network access" reasoning for avoiding Jest doesn't hold in this
      environment -- `npm install` reliably works here (confirmed continuously all session, it's
      how Coder Agent's own scaffold and every `next build` verification step function at all).
      New `executor.ensure_jest_setup` adds `jest`/`@babel/core`/`@babel/preset-env`/
      `@babel/preset-typescript`/`babel-jest` to the target project's own `package.json`
      devDependencies + runs a real `npm install` via `sandbox_service.run_command`, but ONLY the
      first time (`"jest" not already declared`) -- a real generated project genuinely benefits
      from having its own test tooling declared (it's what "Download Project" ships), not
      something to reinstall every run. Writes `babel.config.qa.js`/`jest.config.qa.js`
      unconditionally every run (`testEnvironment: "node"`, not `"jsdom"` -- matches the stated
      scope limit above), kept deliberately separate from anything Next.js's own build tooling
      reads.
    - **New module split** (`app/agents/qa_agent/{discovery,generator,executor}.py`, alongside a
      rewritten `agent.py`/`schemas.py`/`prompt.py`) -- reasonable given the real size increase,
      matching this project's own established "split when a file gets large" precedent rather than
      one growing monolith. `discovery.py`: `discover_unit_test_targets` (scans `lib/`/`models/`
      `.ts` files for real exports), `discover_integration_test_targets` (scans
      `app/api/**/route.ts`, resolves each route's real local `@/models`/`@/lib` imports),
      `discover_out_of_scope_modules` (every `.tsx` file). A real functional gap was found and
      fixed while live-verifying discovery against `workspaces/sample-e-commerce/repo`: the
      original export-detection regex (`export\s+(?:default\s+)?(?:...)?(?:function|const|class)`)
      requires a declaration keyword right after `default`, but every generated Mongoose model
      uses `export default mongoose.models.X || mongoose.model("X", schema)` -- an `export
      default <expression>` shape with no declaration keyword -- making `models/Item.ts`
      genuinely invisible to unit-test discovery until a second, dedicated
      `MONGOOSE_MODEL_EXPORT_PATTERN` was added alongside the first.
    - **Generation, `generator.py`**: three real LLM calls
      (`llm_provider_service.get_provider(agent_name="qa_agent")` -- the exact one-shot/
      no-tool-calling call shape Security Agent's own LLM review layer already established,
      deliberately sidestepping the confirmed `qwen2.5-coder:14b`-can't-tool-call finding from
      item 74 since nothing here needs tools), each returning a structured
      `{"test_cases": [...], "test_code": "..."}` payload parsed via `extract_json_object` with a
      graceful fallback on malformed output -- the same resilience pattern already proven for
      Security Agent's LLM review layer (`_invoke_llm` returns `None`, never raises, on any
      failure). **Unit tests** come from single-file generation calls; a deterministic-template
      fallback (ported from the old `testing.py`, now also emitting real `QaTestCase` metadata
      alongside the Jest code) covers the same two narrow, mechanically-safe shapes as before
      (an exported array literal, a guarded-async-null export) when the LLM is unreachable or
      returns nothing usable. **Integration tests** come from a second pass grouping a route
      handler with the model/lib files it actually imports, exercising a real
      `Request` -> handler -> `Response` flow -- LLM-only, no deterministic fallback (no safe
      generic template exists for this). **Regression tests** come from a third pass: the
      feature's approved SRS's `acceptance_criteria` (loaded via `_find_latest_approved_artifact`,
      the same small, deliberately-duplicated-not-shared per-agent helper pattern Coder/
      Architecture/UI-UX Agent each already have their own copy of), one test per criterion --
      LLM-only, immediately returns `None` if there are no acceptance criteria at all.
    - **Real per-test-case results, not just aggregate counts**: new `QaTestCase` (the
      generation-time plan -- name/category/target_file/target_function/inputs/expected_behavior/
      test_file/method) and `QaTestCaseResult`-shaped Jest output are matched by
      `(test_file_basename, name)` tuple (`agent.py`'s `_merge_results`) -- chosen because every
      generated test file lives flatly under `generated_tests/` with no subdirectories, avoiding
      path-separator/OS-normalization headaches entirely; every `QaTestCase.name` must appear
      verbatim as the real Jest test's title (stated explicitly in `prompt.py`'s shared
      conventions block) for this pairing to hold. A planned case with no matching real result
      (e.g. its file failed to load/parse) is still reported, marked `"skipped"` with an explicit
      "did not produce a matching result" note, never silently dropped. `QAAgentOutput` gains
      `tests_by_category` (unit/integration/regression x total/passed/failed/skipped).
    - **API routes** (mirroring Security Agent's own route shapes exactly): `POST /qa/run`
      (no `/run/stream` variant -- generation is several real LLM calls plus a real sandboxed test
      execution, not a single continuous stream a human watches token-by-token; the *chat* is
      where live streaming actually belongs). `graph_orchestrator_service.py`'s `_qa_node` got the
      same one-line artifact-id-discard fix `_security_node` already got (`output.artifact_ids`
      instead of a hardcoded `[]`). Reports stay `ApprovalStatus.APPROVED` (soft-gate,
      unchanged) -- the user did not ask for QA approval-gating the way they explicitly did for
      Security; not adding scope that wasn't requested.
    - **Real, persisted, streaming chat -- new for QA, deliberately NOT present for Security
      Agent by design**: new `store.qa_conversations` (one document per `feature_id`, upserted in
      place, mirroring `requirement_conversations`'s exact "not versioned like an artifact"
      shape, since a chat turn is not a reviewable output on its own). `GET /qa/chat` (returns
      stored history) + `POST /qa/chat/stream` (NDJSON, the exact `{"type":"token",...}`/
      `{"type":"done",...}` shape Coder Agent's own `/coder/revise/stream` already established).
      Each turn's context includes the feature's latest QA report (real test results/failures,
      freshly loaded via `_load_latest_qa_report`/`_summarize_report_for_chat`, not pinned to one
      historical version) so the model can discuss concrete failures and suggest fixes;
      deliberately **pure Q&A, no code-editing side effects** -- mirrors Security Agent's own
      separation of "discuss" from "act" (see the next bullet for the explicit act path). Streams
      via the provider's own `.stream(prompt, system_prompt=...)` method (confirmed present on
      all 4 providers -- Ollama/Anthropic/OpenAI/base -- so either Ollama or an API model works
      here with zero tool-calling requirement, same reasoning as generation above); the
      conversation history is flattened into one role-prefixed transcript string, since this
      interface takes a single `prompt`, not a messages array.
    - **"Send failing tests to the Coder Agent" -- the same proven loop Security Agent already
      has, minus the approval-gated popup** (QA stays auto-approved, so this is a direct,
      always-visible action when failures exist, closer to Security's original pre-approval-gate
      button than its later popup): new `qaReportToRevisionComment.js`
      (`buildQaRevisionComment(report)`) builds one line per FAILING test case as
      `"[category] target_file::target_function -- \"test name\" -- failure_message"`, mirroring
      `securityReportToRevisionComment.js` exactly, carrying a real `file` token so the Coder
      Agent's existing `_find_well_specified_target_files` still targets correctly with zero
      Coder-side changes. `QaReportView.jsx`'s button calls `handleReviseStream` (from
      `useCoderAgentFlowContext()`, already mounted around the whole feature workspace) then
      `useRunQaAgent(featureId).mutate(...)` for an automatic re-run once the revision completes.
    - **Frontend, mirroring every Security Agent piece built earlier this session**: new
      `frontend/src/components/qa/{QaStatusBadge,QaReportView}.jsx` (report grouped by
      Unit/Integration/Regression, each card showing status/target/inputs/expected-behavior/real
      failure message, an "Out of scope for this pass (no DOM renderer)" section), new
      `frontend/src/components/chat/QaAgentChat.jsx` + `hooks/{useQaAgent,useQaChatFlow}.js` (a
      real streaming chat, history loaded via `GET /qa/chat` on mount so a reload doesn't lose
      it). `pipelineStages.js`: `"qa"` added to `SELECTABLE_AGENT_STAGES`/`MANUAL_RUN_STAGES`,
      removed from `PLACEHOLDER_STAGES` (deliberately NOT added to `REVISABLE_STAGES` -- there's
      no `/qa/revise` route, a re-run is the whole operation, same reasoning as Security).
      `artifactTypeMeta.js`: `qa_report -> "qa"` stage mapping + a `STAGE_GATING_ARTIFACT.qa`
      entry (auto-approved, registered purely so `deriveStageStatus.js` can tell "has run once"
      from "never run yet," same reasoning as Security's own entry).
      `ArtifactViewerModal.jsx`/`ResultTab.jsx` both gained a `qa_report`/`stage === "qa"` branch
      routing through `QaReportView` -- `ResultTab.jsx`'s version-dropdown-plus-report block is
      simpler than Security's own equivalent, since there's no approval gate to render (no
      `ApprovalPanel`, no "All Artifacts"/"Governance" sections for this stage -- both suppressed
      the same way Security's already are). `OutputPanel.jsx`'s already-built Preview-tab-hiding
      logic (previously `selectedAgent === "security"` only) was extended to also cover `"qa"` --
      QA has no runnable preview either, and showing the unrelated Coder Agent preview here would
      be equally misleading. `ChatPanel.jsx` gained a `selectedAgent === "qa"` dispatch branch to
      the new `QaAgentChat`.
    - Tests (all new, no prior QA test files existed at all): `tests/test_qa_jest_parser.py` (8 --
      Jest `--json` output parsing: passed/failed/skipped status mapping, basename normalization,
      multi-message truncation, multiple test files, empty/missing `testResults`).
      `tests/test_qa_generator_fallback.py` (16 -- `_invoke_llm`'s malformed/empty-test-code/
      empty-test-cases/unreachable-provider/markdown-fenced-response handling, the deterministic
      unit fallback's two real shapes plus its "neither shape present" `None` case,
      `generate_unit_tests`'s fallback-on-LLM-failure vs. no-safe-fallback cases,
      `generate_regression_tests`'s empty-acceptance-criteria short-circuit,
      `generate_integration_tests`'s no-fallback-on-failure case). `tests/test_qa_agent_matching.py`
      (14 -- `_merge_results`'s exact `(test_file, name)` matching including the deliberate
      same-name-different-file non-match and the unmatched-case-reported-not-dropped case,
      `_count_by_category`'s per-category/per-status totals, `_build_markdown_report`'s per-test
      lines/first-line-only failure excerpt/empty-test-cases/out-of-scope-listing/stderr-tail
      rendering). `tests/test_qa_agent_routes.py` (13, real `TestClient`, mirrors
      `test_security_agent_routes.py` -- `/qa/run`'s 404/response-shape/human_comment/500-
      translation, `GET /qa/chat`'s 404/empty/persisted-turns, `POST /qa/chat/stream`'s
      404/NDJSON-event-passthrough/error-event-on-unexpected-exception). Full suite: **746
      passed** (up from 608 before items 70-74's own untracked-in-this-file growth plus these 51
      new QA tests), zero regressions.
    - **Real, live end-to-end verification against the real `feature_94701501` "Item Listing
      (CRUD)" workspace** (`proj_34e07440` "Sample E-commerce"): the shared main backend process
      (port 8000) was found to be running WITHOUT `--reload` and pre-dated all of this session's
      QA route work (`GET /openapi.json` showed zero `/qa/*` paths) -- rather than restart a live
      process the user may be actively using (per this project's own standing risk-awareness
      practice), started a second, isolated backend instance on port 8090 against the same shared
      Mongo Atlas database, confirmed all 3 real `/qa/*` routes registered there, and used that
      instance for verification instead (same "isolated instance on a different port" convention
      this file has used throughout items 30-74). Docker Desktop was not running (needed for
      `sandbox_service.run_command`'s real `npm install`/`npx jest` execution) -- started it and
      polled `docker version` until it responded (~9s), the same documented startup gotcha noted
      elsewhere in this file.
    - **A real, 100%-reproducible bug found on the very first live run, fixed, and re-verified**:
      the first real `/qa/run` call produced two real deterministic-fallback unit tests, but BOTH
      failed with `SyntaxError: Cannot use import statement outside a module` when Jest actually
      ran them. Root-caused directly (`npx jest` run by hand against the real generated files):
      `jest.config.qa.js`'s `transform` entry named `babel-jest` with no `configFile` option, so
      babel-jest silently fell back to its own default config-file auto-discovery -- which only
      ever looks for `babel.config.js`/`.babelrc`/etc, never this project's deliberately
      non-standard `babel.config.qa.js` (named that way specifically so it wouldn't collide with
      Next.js's own SWC/babel tooling, per the module's own design). Net effect: every generated
      test file was "transformed" with zero presets applied at all, and Node's native CommonJS
      loader choked on the raw `import` statement -- a 100% real-run failure rate, confirmed
      before the fix and confirmed gone after it. Fixed by explicitly passing
      `configFile: path.resolve(__dirname, "babel.config.qa.js")` as babel-jest's own transform
      option, re-verified with a direct `npx jest` run against the real repo (both tests now
      genuinely pass, with real captured console output and durations) before ever re-driving it
      through the API.
    - **A second, related, partially-fixed reliability gap found and improved live, honestly not
      fully chased to 100%**: of the 7 real generation calls a full run makes (4 unit + 2
      integration + 1 regression, confirmed against `feature_94701501`'s real discovery output --
      `models/Item.ts`/`lib/api/itemListingCRUD.ts`/`lib/mongodb.ts`/`lib/seedData.ts` for unit,
      both real `route.ts` files for integration), only 2 (the two with a safe deterministic
      fallback shape) produced usable test cases on the first real run -- the other 5 (2 unit with
      no matching fallback shape, both integration, the one regression call) all silently
      degraded to nothing, per `_invoke_llm`'s own designed "never fail the run" contract. A
      captured raw parse error (`Invalid \escape: line 20 column 1833`) pointed at a real, fixable
      gap: `_JEST_CONVENTIONS` never told the model `test_code` must be a properly JSON-escaped
      string (no raw newlines, no invalid escapes like a JS-style `\'`) -- a documented local-model
      failure mode this codebase has hit for several other agents already. Added two explicit
      escaping rules to the prompt and, via a cheaper targeted re-test (calling
      `generator.generate_unit_tests` directly against just the two previously-failing unit
      targets, not a full 7-call run), confirmed a real, measurable improvement: `models/Item.ts`
      went from "produces nothing at all" to "a real, valid LLM-authored test case" on the very
      next attempt. `lib/api/itemListingCRUD.ts` still failed (a different, related escaping
      error) after one fix; a second, more specific escaping rule was added addressing that exact
      error class directly, but a full 7-call re-verification run was not repeated afterward (each
      full cycle costs 20-30+ real minutes on this machine's currently-configured model,
      `qwen2.5-coder:14b`, no `qa_agent`-specific override set) -- **recorded honestly as a
      genuine, partially-improved-but-not-fully-solved local-model reliability characteristic**,
      matching this project's own extensive, repeated precedent (Domain/Architecture/UI-UX Agent
      all have similar documented gaps) of not chasing 100% reliability against a local model
      that has already been shown, elsewhere in this same file, to struggle with large structured
      JSON outputs -- the reliability ladder's designed behavior (degrade to nothing rather than
      crash or fabricate) is what makes this safe to leave as an honest, known limitation rather
      than a blocking defect.
    - **A third real, live-found-and-fixed bug, this time in the new chat feature specifically**:
      the very first real chat exchange (a genuine multi-minute local-model call) showed the
      human's own typed question vanishing from the screen entirely the instant Send was clicked
      -- only the growing assistant reply bubble was ever visible, with no trace of what was
      asked until (if) the whole exchange finished. Root-caused directly by reading
      `QaAgentChat.jsx`/`useQaChatFlow.js`: no optimistic human bubble was ever rendered at all
      (turns only ever came from the server-persisted history, refetched only after the stream's
      "done" event), AND `chatStream`'s `onSuccess` called `queryClient.invalidateQueries(...)`
      without awaiting it -- the exact same un-awaited-invalidation bug this project's own item 49
      already found and fixed for Domain Agent's identical chat shape earlier this session, just
      reintroduced here since this component was built afterward, independently, without carrying
      that lesson forward. Fixed both: `useQaChatFlow.js` gained a `pendingHumanMessage` state
      (set on send, rendered as an optimistic bubble by `QaAgentChat.jsx`, cleared once the real
      exchange settles) and its `onSuccess` was made `async`/awaited, mirroring item 49's own fix
      shape exactly. Re-verified live end-to-end, through a real, complete, several-minute local
      LLM exchange (not a mock): the typed question ("Is the mongodb test reliable?") appeared
      immediately as an optimistic bubble, stayed visible throughout, and the final, real
      assistant reply correctly and specifically referenced the report's own real content
      (`connectToDatabase()`, `lib/mongodb.ts::connectToDatabase`, the real passed status) --
      confirmed independently via `GET /qa/chat` that both turns were genuinely persisted
      server-side (in the real, shared Mongo Atlas database, so a reload will show the same
      conversation), not just rendered client-side. Zero console/page errors throughout.
    - **Final confirmed state**: full backend suite re-run clean after both code fixes (**746
      passed**, including the 44 new QA-specific tests, none of which needed changes since neither
      fix touched matching/parsing/report logic). `npm run build` clean after the chat fix. The
      real `feature_94701501` workspace now has 3 real QA report versions (v1 pre-dating this
      session's rewrite, still `pending`; v2 and v3 from this session's own real runs, both
      correctly auto-`approved`) with real, inspectable per-test-case data and a real, persisted
      chat turn -- left in place as genuine verification evidence, matching this project's own
      established convention. Both isolated verification instances (backend :8090, frontend
      :5199) were stopped afterward; the shared main backend (:8000) was never touched.

76. **Coder Agent: a new deterministic hard gate that catches the real "Failed to save item"
    bug class, a best-effort functional CRUD info-check, and a real non-agentic coding path so
    `qwen2.5-coder:14b` becomes a genuinely usable, switchable model alongside qwen3-coder.**
    Direct user report (with a screenshot of the real error) plus three related asks: the Coder
    Agent's output for the real "Item Listing (CRUD)" feature wasn't fully complete (adding a
    second item failed); `qwen2.5-coder:14b` doesn't support real tool-calling for Coder Agent
    (already-confirmed, item 74) and the user wanted it usable anyway, switchable against
    qwen3-coder; output should align with the feature/Architecture/UI-UX Agent's own output; and
    Coder Agent must use `.env` to integrate the user's real MongoDB connection.
    - **Investigated first** (3 parallel research passes + an independent Plan-agent review that
      caught 3 real, material errors in the first draft plan before any code was written -- see
      the plan file's own "corrected by review" section): root-caused the real bug directly
      against the real generated files (`workspaces/sample-e-commerce/repo/`) --
      `models/Item.ts`'s Mongoose schema declared a custom `id: {required: true, unique: true}`
      field the generated create form never actually collected (defaulted to `id: ""` for every
      new item), colliding on the unique index after the first create; the frontend then
      discarded whatever real error the backend returned behind a hardcoded `"Failed to save
      item"` string. Confirmed `.env`/MongoDB wiring (item 71) was already fully correct end-to-
      end -- not the actual problem, though one real adjacent gap was found: a write silently
      returning fake seed-data "success" when no DB is connected. Confirmed `verify.py` had a
      real, structural gap -- no check anywhere ever exercises a real CRUD operation end-to-end,
      only that the app compiles/boots/renders; `route_checker`/`plan_validator` only ever check
      that a route FILE/plan-string exists, never what the code inside it does. Confirmed the
      coding loop is fundamentally, unavoidably tool-calling-dependent (a live `create_agent`
      ReAct loop over `write_file`/`apply_patch`/etc, with no capability-detection anywhere in
      the codebase) -- but planning already has a fully working non-agentic path
      (`CodePlanner.generate()`), so only the coding step itself needed a new alternative.
    - **The independent review's 3 corrections, all folded into the final design** (none of the
      original three ideas survived unchanged): (1) there is NO live, reachable server anywhere
      during `verify()` except inside `render_checker`'s own `start_background_service`/
      `stop_background_service` window -- the earlier "server boot" step's container is already
      gone by the time any later check could reuse it; (2) the Architecture Plan is not a usable
      source for endpoint/payload synthesis -- read directly, the real saved plan for this exact
      feature lists its one real endpoint FOUR times, all method GET, zero POST entries, and its
      `data_entities[].fields` are the entity's own free-text description tokenized into fake
      field names (a field literally named `"non"`, from "non-empty"); (3) `apply_patch` cannot
      be reused for a one-shot batch generator -- confirmed by reading it, it requires the target
      file to already exist with an exact, uniquely-matching `find` string, a live read-then-
      patch loop a single non-agentic call structurally doesn't have; a batch "modify" must be a
      full-file overwrite instead.
    - **\S1 -- the real, primary fix**: new `app/agents/coder_agent/schema_form_checker.py`
      (`check_required_field_form_coverage`, modeled directly on the already-proven
      `db_fallback_checker.check_db_null_guard_coverage` pattern), wired into `verify.py` as a
      new **hard gate**: for each planned Mongoose model file, regex-extracts fields declared
      `required: true` (excluding auto-managed `_id`/`createdAt`/`updatedAt`/`__v`), and checks
      each one is referenced as a REAL editable input (`name="field"` JSX attribute, or an inline
      `field: e.target.value` controlled-input assignment) in any planned frontend file --
      deliberately NOT a bare object key like `field: ""`, since that is exactly the shape the
      real bug's own buggy state initializer already had (a real design flaw caught by my own
      first synthetic test of this checker, not just reasoned about). `CODER_AGENT_SYSTEM_PROMPT`
      also gained three reinforcing rules: never require a client-supplied unique id (use
      MongoDB's own `_id`, generate a separate human-readable code server-side if genuinely
      needed); never swallow a real backend error behind a generic frontend message; a write must
      return a real error (not fake seed-data success) when no database is connected.
    - **\S2 -- a real, best-effort functional CRUD smoke test, informational only**: new
      `app/agents/coder_agent/functional_checker.py`. Discovers POST endpoints by scanning
      planned `app/api/**/route.ts` files directly (not the Architecture Plan, per the review's
      correction #2); synthesizes a payload from the create form's OWN `useState({...})` state
      shape (the same source of truth a human tester would use, and what would have reproduced
      the real bug on a second create) with type inferred from each field's default-literal shape
      -- skips (never guesses) any field it can't confidently infer. `render_checker.
      check_runtime_render` gained an optional `on_server_ready` callback, invoked with the real,
      live `base_url` while its own background service is still up (right before teardown) --
      keeps `render_checker.py` itself decoupled from CRUD-specific knowledge while giving
      `functional_checker.py` a real server to hit with zero extra container-start cost. Wired in
      as `status: "info"`, never a hard gate -- deliberately, since a heuristic payload
      synthesizer's false-failure surface (auth, enums, relational fields) is real and not yet
      proven safe to block on; its value is independent, broad "does the endpoint even work"
      coverage, not primary defense against the specific reported bug class (which \S1's
      deterministic gate already handles reliably, and which a single create+read-back doesn't
      itself reproduce the way a *second* create does).
    - **\S3 -- a real non-agentic coding path**: new `app/services/model_capabilities.py`
      (`supports_tool_calling(agent_name)`) -- Anthropic/OpenAI always `True`; Ollama probes the
      configured server's real `POST /api/show` (`capabilities` array containing `"tools"`),
      cached per `(base_url, model)` for the process lifetime, defaulting to `False` (the safer
      direction) on any unreachable-server/unparseable-response failure. A new
      `agent_overrides[agent].supports_tool_calling: bool | None` override field (`llm_schema.py`,
      `llm_provider_service.set_agent_override`/`clear_agent_override`/`_agent_response`) is
      checked FIRST as a human escape hatch. New `app/agents/coder_agent/batch_coder.py`: reuses
      the code plan's already-validated `files[]` list (from the existing non-agentic
      `CodePlanner.generate()`) as the authoritative "what to touch" list, and makes ONE
      single-shot LLM call PER PLANNED FILE (never one giant call for the whole plan -- real
      byte-count math against this project's own real generated features confirmed a combined
      response would blow past this app's default `LLM_MAX_TOKENS` and truncate mid-file, the
      same class of wall this project already hit for Domain/Architecture Agent's own combined-
      schema attempts). Reuses `CODER_AGENT_SYSTEM_PROMPT`'s own hard rules verbatim (string-
      split before its "Tool usage" section, so \S1's new rules and every existing Next.js/Mongo/
      completeness rule apply automatically with no duplicated maintenance) via a new
      `BATCH_CODE_GENERATOR_SYSTEM_PROMPT`. A page/component file's approved UI/UX design
      reference is attached unconditionally to its own prompt (`_design_reference_for_file`,
      reusing `tools.py`'s existing `_find_approved_component_artifact`/
      `_find_approved_page_html_artifact` directly, not through the tool wrapper) -- arguably a
      STRONGER guarantee than the agentic loop's own `list_unread_ui_designs` gate, since it's
      never something the model has to remember to request. New `CoderAgent.
      _code_with_batch_generation`/`_code_with_batch_generation_stream` (same
      `MAX_CODING_ATTEMPTS` retry shape and `(verify_result, attempts)` return contract as
      `_code_with_retries`, so every downstream caller needs zero changes) apply each file as a
      plain write (never `apply_patch`, per review correction #3), commit, then run the existing,
      unchanged `verify()` (getting \S1's hard gate and \S2's info check for free). New
      `CoderAgent._run_coding_phase` is the single dispatch point `run()`/`revise()` (and the
      streaming variants, via inline capability checks) call, choosing the agentic or batch path
      automatically based on whichever model is currently selected for `coder_agent` in Settings
      -- no separate manual toggle, exactly "user can switch... if user want." Honest, stated
      scope limit: a one-shot per-file call has no mid-generation self-correction (no
      `check_syntax`, no live workspace discovery) -- expected less reliable than the agentic
      path for cross-file-discovery-heavy features, matching this project's own established
      precedent that a non-agentic fallback rung is real and useful, never claimed equal quality.
    - **A real, live mistake made and fixed during testing, recorded honestly**: an early version
      of the `supports_tool_calling` override test called the real, shared `store.llm_settings`
      directly with a naive `agent_overrides = {}` reset in its cleanup, which wiped the ENTIRE
      real, live `agent_overrides` document in the shared MongoDB Atlas cluster -- not just the
      one field under test -- destroying the real, intended `coder_agent`/`architecture_agent` ->
      `qwen3-coder:latest` pins (item 74) with no prior backup. Caught immediately by checking the
      live document's state right after; restored both overrides to their documented values via
      the real `set_agent_override` call before doing anything else, confirmed restored via a
      real `GET /settings/llm/agents` call, then rewrote the entire test file to mock `store`
      exclusively (matching `test_model_capabilities.py`'s already-safe pattern) so it can never
      touch the real shared store again. **Any future test touching `store.llm_settings.agent_
      overrides` must mock the store, never reset the real document even "just in cleanup."**
    - Tests (all new): `tests/test_coder_schema_form_checker.py` (11, including the exact real
      bug reproduced from a hand-built fixture matching the real buggy code), `tests/
      test_coder_functional_checker.py` (13, including a stubbed `urllib.request.urlopen` for the
      HTTP half -- no real server needed for unit coverage), `tests/test_model_capabilities.py`
      (9), `tests/test_coder_agent_batch_generation.py` (8, real tmp_path filesystem writes/
      deletes, mocked LLM/verify), `tests/test_llm_provider_service_supports_tool_calling_
      override.py` (5, store fully mocked per the lesson above), plus 2 new Docker+Playwright-
      backed tests in `tests/test_render_checker.py` confirming `on_server_ready` is genuinely
      invoked with a real, live, reachable `base_url` while the server is still up, and that a
      raising callback is caught and reported rather than breaking the render check itself. Full
      suite: **792 passed** (non-Docker) + the pre-existing 15 `test_coder_verify.py` (Docker-
      backed, confirming the new gates integrate correctly into the full flow) + all 5 `test_
      render_checker.py` tests, all passing, zero regressions.
    - **Real, live, multi-round end-to-end verification against the actual, already-broken
      `feature_94701501` workspace, run on an isolated backend instance (the shared main backend
      was stale and never touched, matching this session's own established practice)**:
      - Confirmed the new `schema_form_checker` hard gate fires against the REAL, unmodified
        buggy code on disk with zero LLM involvement -- direct, immediate proof before ever
        running a revision.
      - **Real revision 1** (a natural, user-style comment, no file names given): completed with
        `verification_passed: True` on attempt 1 -- but inspecting the real result showed the
        fast-path planner's own keyword-matching scoped the revision to *only* `app/api/item-
        listing-crud/route.ts`, correctly applying two of the three new prompt rules (real error
        messages now surface; a DB-not-connected write now returns a real 503 instead of fake
        success) but never touching `models/Item.ts`, where the actual structural fix belongs.
        Confirmed empirically via a real live preview + real POST calls: every create still
        failed, now with an honest error instead of a generic one.
      - **Real revision 2** (explicit comment naming `models/Item.ts` directly): the real fix
        landed correctly on disk (confirmed directly: `id` genuinely removed from the schema,
        `types/itemListingCRUD.ts` updated to `_id`, most of `page.tsx` updated too) -- but
        `verification_passed: False`, because the plan's OWN file list named a stale, non-
        existent placeholder (`models/ItemListingCRUDDataEntity1.ts`, from the Architecture
        Plan's own messy auto-generated entity naming, item 24/27's already-documented gotcha)
        instead of the real file, so the deterministic `list_unimplemented_planned_files` gap-
        check blocked `verify()` from ever running at all across all 3 attempts, even though the
        real code fix was correct. Direct file inspection also found 3 real leftover `.id`
        references in `page.tsx` (an incomplete find-and-replace) that this same blocked-`verify()`
        would ordinarily have caught via `next build`'s real TypeScript check.
      - **Real revision 3** (a precise comment naming the exact 3 leftover lines): the fix landed
        correctly (confirmed: all 6 real `_id` references present, zero stray `.id`) -- but hit
        the SAME stale-cumulative-plan-file gap again (a genuine, pre-existing planning-system
        limitation, NOT something built this session, worth flagging separately for a future
        pass), so `verify()` never ran a third time either.
      - **Final empirical proof, independent of the blocked `verification_passed` flag**: rebuilt
        the app directly (`sandbox_service.run_command("npm run build")`, real exit code 0),
        restarted the preview, and found the first real create now succeeded (201, real `_id`
        returned) but every create AFTER the first still failed with a NEW, different, genuinely
        informative error: `E11000 duplicate key error ... index: id_1 dup key: { id: null }` --
        a real, live MongoDB collection still carrying a STALE unique index from before the
        schema fix (confirmed directly via `pymongo`: `id_1`, unique, on the real `items`
        collection). This is a database-schema-migration concern, not a code-generation defect --
        no application code fix can remove an index that already exists in the live database.
        Asked the user directly (two real decisions, both answered): dropped the real stale
        `id_1` index on their live MongoDB collection (confirmed empty of real data beforehand --
        only my own test items), and per their explicit choice, did NOT run a further revision
        for the separately-found, still-broken `[id]/route.ts` (the single-item GET/PUT/DELETE
        route, which still queries by the now-nonexistent `id` field) -- left as a known,
        precisely-diagnosed remaining item instead. **Final confirmation, real and complete**:
        4 consecutive real creates via the actual running preview, all HTTP 201 with real distinct
        `_id`s, all 4 correctly appearing on a real subsequent list call. All test data (the
        preview session's real writes, twice) was cleaned up from the real database afterward via
        direct `pymongo` deletes, confirmed empty each time.
    - **Known, precisely-diagnosed remaining item, left for the user's own follow-up (not fixed
      this session, per their explicit choice)**: `app/api/item-listing-crud/[id]/route.ts` still
      queries `Item.findOne({ id: params.id })`/`findOneAndUpdate`/`findOneAndDelete` by the now-
      removed `id` field -- viewing, editing, or deleting one specific item by its real `_id` will
      currently always 404. A future revision naming this exact file and asking it to match
      `_id` instead of `id` (mirroring revision 3's own precise, targeted comment shape) should
      resolve it in one pass.
    - **Known, separate, pre-existing planning-system gap surfaced by this verification, not
      something built this session and not fixed here**: once an Architecture Plan's own
      `data_entities` naming is messy (word-salad-derived fake entity names, item 24/27's already-
      documented gotcha), a later revision's plan can persistently reference a stale/non-existent
      file across multiple revisions in a row (via `_collect_cumulative_plan_files`'s own
      "union every prior plan's files forever" design, item 21) -- blocking `verify()` from ever
      running even when the actual code fix is correct. Worth a future look (e.g. skipping a
      cumulative-plan-file entry that has never once corresponded to a real file across several
      attempts), out of this session's own scope.

77. **Requirement Agent: removed direct inline SRS editing (chat-only going forward), fixed a
    real `GovernancePanel.jsx` approve-lock gap, generalized the "Using X vN for Y Agent"
    indicator to every stage, and fixed a real regression the immediately-prior Coder Agent
    Phase C work (item 76) had introduced into 8 pre-existing tests.** Three direct user
    requests, the third with a screenshot of the Domain Agent's own "Using SRS v20 for Domain
    Agent" indicator as the reference example for generalizing it project-wide.
    - **Inline editing removed, Domain Agent highlighting kept**: `EnrichedItemList.jsx`/
      `EnrichedPlainList.jsx` were simplified to permanently read-only (edit/remove/add code
      paths + `canEdit`/`onEdit` props stripped) rather than deleted outright -- both also render
      Domain Agent's own enrichment highlighting (green "Added by Domain Agent" cards, items
      42/45/49/50), a separate, valuable feature the user did NOT ask to remove; an Explore
      agent's first-draft research report recommended deleting both files outright, caught and
      corrected by directly reading them before finalizing the plan. `EditableScalarField.jsx`
      (genuinely edit-only, no enrichment concept for a scalar field) deleted outright.
      `SrsDocumentViewer.jsx`/`ArtifactContentView.jsx`/`ResultTab.jsx` had their
      `featureId`/`editable`/`canEdit`/`onEdit` machinery stripped (permanently read-only now).
      Backend: `RequirementAgent.edit_fields()`, the `POST /requirement/edit` route, and
      `SrsFieldEditOperation`/`RequirementAgentFieldEditRequest` schemas deleted outright --
      confirmed unused by anything else, including the chat-driven revision flow (item 57), which
      shares `revision_patcher.apply_revision_operations` but is otherwise a fully separate code
      path, left untouched.
    - **`GovernancePanel.jsx` approve-lock gap**: its own "Stage Actions" `ApprovalPanel` call
      never passed `approveLocked` at all, unlike `ArtifactList.jsx`'s already-correct per-row
      computation (item 40) and `ResultTab.jsx`'s Security-stage special case. Fixed by computing
      the identical `Boolean(approvedSibling)` check locally and passing it through -- mirrors
      `ArtifactList.jsx`'s logic exactly, no new mechanism invented.
    - **Generalized "Using X vN for Y Agent" indicator** (`OutputPanel.jsx`): replaced the old
      2-entry `NEXT_AGENT_BY_ARTIFACT_TYPE` map with a stage-keyed
      `PREVIOUS_STAGE_INPUTS_BY_STAGE` config supporting multiple pills per stage (Coder needs 2:
      Architecture Plan + UI/UX Output), a fallback artifact type (Architecture stage: Enhanced
      SRS if approved, else plain SRS, matching the real `srs_for_generation = enhanced_srs_json
      or srs_json` backend logic), and a separate `NO_ARTIFACT_VERSION_LABEL_BY_STAGE` map for
      Security/QA (which scan the live workspace directly, confirmed via their own backend code
      -- no formal approved-artifact input exists for either) rendering an honest, non-versioned
      label instead of a fabricated pill. `getEffectiveActiveArtifact`
      (`frontend/src/lib/activeArtifactSelection.js`) needed zero changes -- already fully
      generic over `(artifacts, activeSelection, artifactType, artifactFormat)`.
    - **A real regression found in the pre-existing test suite, introduced by item 76's own
      dispatch logic, not by this session's Requirement Agent work**: running the full backend
      suite after the above changes surfaced 8 unexpected failures, all in
      `test_coder_agent_stream.py`/`test_coder_agent_revise.py` -- item 76's new
      `_run_coding_phase` dispatch (added to `run()`/`revise()`/`run_stream()`/`revise_stream()`)
      unconditionally calls the real `model_capabilities.supports_tool_calling(...)`, but these
      8 pre-existing tests (written before that dispatch existed) never mock it -- so it performs
      a real Ollama capability probe, which fails/returns falsy whenever Ollama isn't reachable
      in the current environment (confirmed directly: Ollama was NOT running at the time these
      tests were run), silently routing them into the new, untested-by-them batch coding path
      instead of the agentic path (`_code_with_retries`/`_code_with_retries_stream`) they were
      written to exercise and assert against (e.g. checking for a `"coding_attempt_1_of_3"`
      phase event, which only the agentic path emits). **Fixed with a new `autouse=True` fixture
      at the top of each file** (`_assume_tool_calling_supported`) patching
      `app.services.model_capabilities.supports_tool_calling` to always return `True` for the
      whole file -- correct because every test in both files specifically exercises/asserts on
      the agentic path, never the new batch path (which has its own dedicated, already-correctly-
      mocked test file, `test_coder_agent_batch_generation.py`). **Any future pre-existing test
      file that calls `CoderAgent.run()`/`revise()`/`run_stream()`/`revise_stream()` and assumes
      the agentic path must mock `model_capabilities.supports_tool_calling` (or use this same
      autouse-fixture pattern) — it is no longer a no-op default, and depends on live Ollama
      reachability if left unmocked.** Full suite re-confirmed clean after the fix: **784
      passed**, 0 failed.
    - **Real, live verification** (isolated backend :8090 / frontend :5199, real LLM calls,
      `qwen2.5-coder:14b`, real fresh project + feature "Wishlist Sharing"): generated and
      approved a real SRS v1 via the API, ran a real Domain Agent enrichment with an explicit
      human-provided schema comment, approved the resulting Enhanced SRS v1, and drove one real
      chat-driven revision (`/requirement/revise`) producing a genuinely new, still-pending SRS
      v2. Confirmed via direct DOM inspection (not just visual screenshots): zero pencil/edit
      affordances anywhere in the FR/NFR/AC/user-story cards; the real Domain Agent enrichment
      rendered as a green "ADDED BY DOMAIN AGENT" card with `Source: human_provided` citation
      directly under Data Requirements, with `domain_improvements` still correctly rendered as a
      read-only attachment (not a separate approvable row, item 42); the "Using SRS v1 for Domain
      Agent" and "Using Enhanced SRS v1 for Architecture Agent" pills both rendered correctly;
      Security/QA both correctly showed their honest "Scanning/Testing the latest generated code"
      labels instead of a fabricated pill; and, with v1 approved and v2 pending, v2's real Approve
      button was confirmed via `is_disabled()` to be genuinely `disabled=True` with the exact
      "Another version is already approved -- reject it first..." tooltip, while its Reject/
      Request Revision buttons remained genuinely enabled -- confirming `ArtifactList.jsx`'s
      pre-existing lock (item 40) is unaffected and consistent with the newly-fixed
      `GovernancePanel.jsx` computation. Test project/feature deleted via the real `DELETE
      /projects/{id}` endpoint afterward; isolated backend/frontend processes stopped.

78. **Real, reported rendering bug: a literal "\2022" appeared overlapping the text of every
    plain-list SRS bullet (Scope, Out of Scope, Constraints, Risks, Dependencies, Data
    Requirements, etc.), on the user's own real, live "Item Listing (CRUD)" feature.**
    Root-caused directly in `frontend/src/components/documents/EnrichedPlainList.jsx`: the
    bullet marker used a Tailwind arbitrary-value class, `before:content-['\\2022']` -- a
    **double** backslash in the raw JSX source. Since a bare (non-`{}`-wrapped) JSX attribute
    string is NOT run through JS string-escape processing (a JSX-spec quirk: `\n`/`\\` inside
    `className="..."` are taken completely literally, unlike a normal JS string), both Tailwind's
    build-time class scanner AND the runtime DOM `className` saw the identical literal text
    `\\2022` -- so Tailwind faithfully generated `content: '\\2022'`, which CSS interprets as an
    escaped literal backslash followed by the plain digits "2022" (visible text), not the intended
    single-backslash CSS unicode escape `\2022` that renders as the bullet character "•". Fixed
    by removing the stray extra backslash (`content-['\2022']`, single backslash -- the correct,
    standard Tailwind syntax for a CSS content unicode escape). Confirmed no other occurrence of
    this double-backslash pattern exists anywhere else in `frontend/src`. `npm run build` clean.
    **Real, live verification directly against the exact reported feature**
    (`proj_34e07440`/`feature_94701501`, via a read-only isolated frontend instance pointed at
    the user's own live main backend, port 8000, no mutations): confirmed the literal text "2022"
    no longer appears anywhere on the page, and a fresh screenshot shows every Scope/Out-of-
    Scope/etc. bullet rendering as a clean "•" marker with no overlapping text.

79. **Coder Agent: threaded the real SRS + Architecture Plan `implementation_plan` into the
    actual coding step (not just planning), stopped a raw MongoDB `_id` from leaking into
    generated UIs, gave every generated app a persistent nav/footer shell, made the live preview
    responsive on laptop screens, and added an informational SRS-coverage check.** Direct user
    report against the real, live "Item Listing (CRUD)" feature (`proj_34e07440`/
    `feature_94701501`), five parts: a raw ObjectId shown as a table "ID" column; the output
    generally feeling incomplete relative to the feature, with an explicit ask to check whether
    the Architecture Plan's `implementation_plan` actually reaches the Coder Agent; the live
    Preview option not responsive on a laptop screen; no nav bar/footer on the generated app; and
    a general ask to identify what would make Coder Agent output more reliably satisfy the SRS
    and the approved UI/UX design.
    - **Root cause, confirmed by direct investigation before writing any plan**: `coder_agent/
      prompt.py`'s planning-context builder already passed the full SRS + `architecture_plan_json
      ["implementation_plan"]` into the PLANNING prompt (builds the terse `code_plan_json`), but
      `coding_loop.build_task_message` -- the message actually given to the step that WRITES file
      content -- only ever received that terse plan (`files: [{path, action, rationale,
      maps_to}]`, confirmed genuinely short strings by the planner's own prompt contract and every
      real test fixture). The coding step had no tool to read the SRS/Architecture Plan either.
      `batch_coder.py`'s non-agentic per-file path (item 76) had the identical gap. This is the
      single biggest cause of "doesn't match the feature" output -- the step doing the actual
      writing had no idea what a planned file was supposed to DO beyond its own filename.
    - **Fix (`prompt.py`)**: new `_match_implementation_plan_entries_for_file`/
      `_match_srs_requirements_for_file` mechanically extract only the `implementation_plan`
      sub-entries and SRS requirements a given code_plan file's `path`/`maps_to` actually
      reference (never the whole document); `build_implementation_spec_section` (agentic path,
      one combined block covering every planned file, built once per attempt) and
      `build_implementation_spec_for_single_file` (batch path, per-file) assemble these into a
      capped (`MAX_IMPLEMENTATION_SPEC_CHARS = 8_000`, mirrors `diff_builder.MAX_DIFF_TEXT_CHARS`'s
      own truncate-with-label precedent) section always including the SRS's `ui_expectations`
      verbatim (cross-cutting) plus each file's matched slice. Deliberately **inlined, not a new
      tool** -- a `read_implementation_spec` tool would need its own hard gate (mirroring
      `list_unread_ui_designs`) to guarantee it's actually called per file, reproducing the exact
      "no obligation to look" gap being fixed, and risks the same large-tool-result-in-a-long-
      conversation pattern behind the documented Ollama `num_ctx` truncation gotcha.
      `coding_loop.build_task_message` gained an `implementation_spec_section` param;
      `batch_coder._build_user_content`/`generate_file_content` gained a matching
      `implementation_spec` param. Threaded end-to-end: `_run_coding_phase`/`_code_with_retries
      (_stream)`/`_code_with_batch_generation(_stream)` all gained `srs_json`/
      `architecture_plan_json` params; `run()`/`revise()`/`run_stream()`/`revise_stream()` pass
      through whichever SRS variable was already used for that call's own `plan_validator.validate`
      (`srs_for_planning` for `run()`/`run_stream()`, which already resolves the Enhanced-SRS
      fallback; plain `srs_json` for `revise()`/`revise_stream()`, matching each method's own
      existing planning-context precedent).
    - **Fix, the `_id` leak + UI-fidelity depth** (`prompt.py`): new rule directly after the
      existing `_id`-as-identifier rule (item 76) -- `_id` is for edit/delete links and routing
      ONLY, never a visible table column/label a human sees; if the approved design shows an
      identifier column at all, it's a human-readable value the design itself defines. Strengthened
      the existing UI-fidelity rule: mirror the design's exact visible field/column set, don't add
      a field the design doesn't show (even if the Mongoose model has more fields -- `_id`,
      timestamps, metadata) and don't omit one it does show -- the design decides what a human
      sees, not the schema. Both rules land before `CODER_AGENT_SYSTEM_PROMPT`'s `"Tool usage:"`
      split point, so `BATCH_CODE_GENERATOR_SYSTEM_PROMPT` inherits them automatically.
    - **Fix, persistent nav/footer** (`workspace_service.py`): confirmed via direct investigation
      that `NEXTJS_APP_LAYOUT` (`app/layout.tsx`) was a bare shell with zero persistent chrome --
      only `app/page.tsx` (Home) had its own local nav, so any OTHER route rendered with nothing
      at all, exactly matching the report. Also confirmed UI/UX Agent's `layout_regions` schema
      field (`uiux_agent/prompt.py`) was 100% unused/decorative anywhere in the codebase (grepped
      the whole directory), and that `integration_manifest_builder.py`/component reuse have no
      cross-page shared-shell concept at all -- concluded a persistent nav/footer is squarely a
      Coder Agent SCAFFOLD-level (deterministic) responsibility, not a new UI/UX Agent mechanism,
      and removed `layout_regions` as confirmed-dead schema surface. `NEXTJS_APP_LAYOUT` now wraps
      `{children}` in a minimal header (app name linking to `/`) + footer, plus an explicit
      `viewport` export. New idempotent backfill `_upgrade_layout_for_persistent_nav_footer`,
      mirroring `_upgrade_layout_for_preview_route_announcer`'s exact anchor-based pattern
      (confirmed its real anchor/replacement text by reading it directly first) -- anchors on the
      literal `"<PreviewRouteAnnouncer />\n        {children}\n      </body>"` block, present in
      every layout regardless of whether the announcer upgrade just ran in the same call or was
      already there; no-ops with a logged warning if the anchor's missing or a `<header` tag
      already exists. Wired into `_backfill_nextjs_scaffold_upgrades` right after the announcer
      upgrade. `CODER_AGENT_SYSTEM_PROMPT` already forbade touching `app/layout.tsx` at all (item
      63) -- the persistent shell is safe from being overwritten by feature generation with no new
      rule needed.
    - **Fix, preview responsiveness**: `PreviewPanel.jsx`'s hardcoded `min-h-[500px]` (on both the
      iframe wrapper and the iframe itself) relaxed to `min-h-[350px] lg:min-h-[500px]` -- the one
      concrete fixed-size finding after confirming no other fixed pixel widths exist anywhere in
      the AutoForge-side layout chain (`ResizableWorkspace.jsx` is percentage-based,
      `AppShell.jsx` correctly uses `h-screen`/`flex-1 min-h-0 overflow-hidden`, `index.css` has
      zero media queries, `index.html` has a correct viewport meta tag). New
      `CODER_AGENT_SYSTEM_PROMPT` rule: never use a fixed pixel width on a page's top-level
      container or anything wider than a small icon; wrap a wide table in `overflow-x-auto`
      rather than letting it overflow.
    - **New informational-only spec-fidelity checker** (`ui_expectations_checker.py`, new module,
      mirroring `functional_checker.py`'s "explicitly heuristic, never a hard gate" convention and
      `verify.py`'s existing `_build_relevance_scan_step` word-overlap/stopword-filter idiom):
      `scan_ui_expectations_coverage` flags an SRS `ui_expectations` bullet with zero plausible
      textual trace in this attempt's touched `.tsx`/`.jsx` files -- deliberately never a hard
      gate (a legitimate implementation routinely uses different words than the SRS bullet, e.g.
      "Live search input with debouncing" implemented as `SearchBar`/`useDebounce` shares no
      literal words). Wired into `CoderVerifier.verify()` as a new `ui_expectations` param -> new
      `_build_ui_expectations_coverage_step`, `status="info"`, threaded from both real
      `self.verifier.verify(...)` call sites using `srs_json.get("ui_expectations")` (the same
      `srs_json` already threaded for the main fix above).
    - Tests: `tests/test_coder_prompt.py` (+13: both matching helpers, both spec-builders
      including char-cap truncation, substring locks for all 3 new/strengthened prompt rules),
      `tests/test_coder_coding_loop_task_message.py` (+3), `tests/test_coder_agent_batch_generation.py`/
      `tests/test_coder_agent_retries.py` (fixed 6 pre-existing mock signatures that didn't accept
      the new kwargs -- a real, expected test-fixture update, not a regression), new
      `tests/test_coder_ui_expectations_checker.py` (8) + `tests/test_coder_ui_expectations_step.py`
      (5, mirrors `test_coder_relevance_scan.py`'s exact no-Docker precedent),
      `tests/test_workspace_preview_route_announcer.py` (+4: fresh-scaffold header/footer/viewport
      presence, backfill onto a pre-upgrade layout, missing-anchor no-op, idempotency; 1
      pre-existing test's assertion updated since {children} is now wrapped in `<main>` rather
      than sitting bare in `<body>`), `tests/test_uiux_metadata_validator.py` (removed
      `layout_regions` from its fixture -- confirmed pure cleanup, the validator never asserted on
      it). Full suite: **818 passed** (fast) + all **15** real Docker-backed `test_coder_verify.py`
      tests passing end-to-end (confirming the new informational step integrates cleanly with a
      real npm-install/build/server-boot cycle, ~1h54m real Docker time). `npm run build` clean.
    - **Real, live verification against the exact reported feature**, not just unit tests: a real
      streamed `revise()` call (`qwen3-coder:latest`, ~27 real minutes: ~4.5min planning via the
      well-specified fast path since the file was named explicitly, then 3 coding attempts) --
      directly confirmed on disk afterward that the raw `_id`/ObjectId table column and header are
      genuinely gone from `app/item-listing-crud/page.tsx` (table now reads Name/Price/Quantity/
      Category/Actions; `_id` only remains in its correct internal uses -- the React `key`,
      edit/delete routing), and that the real, already-existing `app/layout.tsx` was correctly,
      automatically backfilled with the new persistent header/footer live during this same run.
      **Two honest, separate findings from this real run, recorded rather than hidden**: (1) this
      attempt's `verification_passed: false` -- but the cause was the pre-existing (item 69)
      `list_unread_ui_designs` hard gate (the model modified frontend code without calling
      `read_ui_component_design`/`read_ui_page_design` first this run), a known, already-
      documented local-model tool-compliance characteristic, not a regression from this session's
      own changes; (2) this real feature's own Architecture Plan happens to be one of the
      already-documented crude, deterministic-fallback-generated ones (items 24/27 -- each model
      field split into its own fake "DataEntity", all 4 endpoint entries collapsed to duplicate
      `GET /api/item-listing-crud`), so `_match_implementation_plan_entries_for_file`'s matching
      found little useful detail to thread through FOR THIS SPECIFIC FEATURE specifically -- the
      mechanism itself is confirmed correct and fully unit-tested against well-formed fixtures,
      but its real-world benefit depends on the underlying Architecture Plan actually being
      well-formed, which is a separate, already out-of-scope, pre-existing gap this item does not
      newly introduce or attempt to fix. `[id]/route.ts` was also observed to still query by a
      plain `id` field rather than `_id` (the same known remaining item documented in item 76) --
      untouched by this revision since it wasn't part of what was asked. This real state (6 new
      Coder Agent artifacts, `verification_passed: false`, pending human review) is left in place
      as genuine verification evidence, matching this project's own established convention.

80. **Requirement Agent conversation: the deterministic quality gate flagged a well-annotated,
    detailed `data_requirements` field spec as "vague" purely for being long.** Direct, real user
    report: submitted `"name — string, required (user's full name or display name)"` (a format
    directly suggested as a good answer shape) and the conversation got stuck on "Not ready to
    confirm yet: Data requirement ... reads like a vague sentence, not a concrete field name,"
    with no way to proceed except the "Confirm anyway" override.
    - **Root cause, confirmed directly** (`conversation_quality_gate.py`): the `data_requirements`
      check was a bare `len(str(field).split()) > _VAGUE_FIELD_WORD_LIMIT` (6 words) -- it
      couldn't distinguish "detailed because of a helpful type/constraint annotation" from
      "vague because it's a rambling sentence." The reported example is 10 tokens purely from its
      `— string, required (...)` annotation, tripping the same limit meant to catch something
      like "the full name of the user who is registering."
    - **Fix**: new `_looks_like_a_structured_field_spec` -- an entry is treated as a legitimate,
      non-vague structured spec (skipping the word-count check entirely) if it has an early
      field-name-like token followed by a separator (`name — ...`, `email: ...`) or a bare
      `field (note)` shape, AND its first word isn't a sentence-starter ("the", "a", "this", etc.)
      -- an entry with neither trait still falls through to the original word-count heuristic, so
      a genuinely vague, unstructured description is still caught exactly as before.
    - Tests: `tests/test_requirement_conversation.py` (+2 -- the exact reported example plus two
      similarly-shaped variants no longer flagged; a genuinely vague, unstructured, article-led
      description of the same rough length still correctly flagged, confirming the fix narrows
      the false positive rather than disabling the check). Full suite: **820 passed** (up from
      818, following item 79's own count).
    - **Real, live remediation**: the user's own live main backend (`--reload`, port 8000) was
      cleanly restarted (its full reloader/worker process tree stopped and relaunched identically)
      at their explicit request so the fix took effect in their active session immediately,
      confirmed via a clean `Application startup complete` log and the frontend's own real
      requests succeeding against the fresh process right after.

81. **Requirement Agent chat-composer fix + Architecture Agent brought to UML/agilemodeling.com
    standards (use case actor stereotype/generalization/participating-actors, sequence Par/Break
    fragments + a shared fragment-kinds source of truth, class stereotype-naming hard gate), plus
    a real sequence-diagram-rendering crash found and fixed live, and a real Coder Agent build
    broken by two confirmed bugs, found and fixed live against the user's real Finodil project.**
    Direct user request (verbatim, with a screenshot of the SRS-confirm chat composer vanishing):
    fix the chat composer disappearing during SRS generation; bring the Architecture Agent's use
    case diagrams into UML/international-standards compliance per
    agilemodeling.com/style/usecasediagram.htm (actor/use-case relationships, stereotypes,
    generalization, full functional-requirement coverage); add missing sequence-diagram control
    structures (explicitly Par, "etc" implying more as needed); enhance the class diagram; then
    generate a genuinely new Architecture Plan (all three diagrams) for the real Finodil "Login
    and Signup" feature. Plan approved in plan mode; most of Parts A-D were implemented in the
    prior (compacted) portion of this session -- this segment finished Part B's last piece,
    found and fixed one more real bug the live deliverable run surfaced, then pivoted to a
    second, separately-reported real bug (Coder Agent preview broken) in the same session.
    - **Part B finish -- `_complete_usecase_model` rewritten to accept `diagram_generation_state`/
      `attempt_agentic`/`attempt_focused_fallback`, mirroring `_complete_diagram_models`'s own
      established shape exactly** (reuses the SAME shared state dict, new
      `"usecase_attempted"`/`"usecase_specification_json"` keys, no second state dict): agentic
      exploration attempted at most once per outer call when not already cached, falling through
      to whatever `parsed` already carries on failure (never discarded); `attempt_focused_fallback`
      gates one non-agentic focused single-shot call for the use case model specifically, mirroring
      the diagram tiers' own focused-fallback rung. All 7 real call sites in `agent.py` updated per
      the validated rung-by-rung design: `_generate_architecture_output`'s exploration/single-shot/
      repair rungs pass `diagram_generation_state` with the new params at their defaults (agentic
      `True`); the true last-resort deterministic-fallback rung gets `attempt_agentic=False` only
      (matching the pre-existing repair-loop rationale: don't call the LLM again from the rung
      whose whole purpose is "the LLM already failed twice" -- deliberately asymmetric with
      diagrams' own tier-2-always-runs design, a considered choice not an oversight);
      `run_stream()` gets `attempt_agentic=False` explicitly (a human is synchronously watching);
      `revise()`/`revise_stream()` get `attempt_agentic=False, attempt_focused_fallback=True` --
      this is the actual fix for the confirmed real gap where `revise()` previously always
      regenerated the use case diagram from the empty-specification deterministic template with
      zero LLM involvement.
    - New test files, mirroring the sequence/class diagram tooling's own established coverage
      exactly: `tests/test_architecture_usecase_diagram_tools.py` (9 -- the new
      `build_usecase_diagram_tools`'s read/validate/submit tools, including the new
      `read_user_roles_and_stories` tool and the real 4-positional-arg
      `usecase_validator.validate()` call inside `validate_usecase_draft`), `tests/
      test_architecture_usecase_diagram_exploration.py` (10 -- `_generate_usecase_diagram_via_
      exploration`'s submission/no-submission/recursion-limit contracts, and the full
      `_complete_usecase_model` rung matrix: agentic-succeeds, agentic-fails-fallback-disabled,
      agentic-fails-fallback-enabled, `attempt_agentic=False` variants, an already-embedded
      specification surviving untouched, and cross-call memoization).
    - **A real, confirmed bug found only by the live Finodil deliverable run, not by any of the
      above unit tests**: the real Architecture Agent run for Login and Signup produced an
      LLM-authored sequence specification whose `end` closed an `alt` fragment BEFORE its own
      `else` (`alt_start -> ... -> end -> else -> ... -> end`) -- `SequenceDiagramValidator`
      correctly rejects this shape, but the reactive repair loop (item 26) is bounded by
      `MAX_SEQUENCE_REPAIR_ATTEMPTS` and, per its own established contract, never raises once
      attempts are exhausted -- it proceeds with whatever it has. The still-unbalanced diagram
      then reached the PlantUML CLI renderer, which failed with a FATAL, uncaught error ("Some
      diagram description contains errors"), crashing the entire Architecture Agent run with no
      artifacts saved at all -- worse than a quality miss, a hard stop. Fixed with a new
      deterministic backstop, `ArchitectureSequenceModeler._sanitize_fragment_balance`, called at
      the one place every path (LLM specification, repair-rebuilt, fallback) funnels through
      before `_finalize`: walks the final `interactions` list with a fragment-kind stack (reusing
      `sequence_fragment_kinds.FRAGMENT_OPENER_KINDS`), drops an `else` with no genuinely open
      `alt_start` and drops an `end` with nothing open to close (exactly the malformed shape
      above -- the dangling `else`/its now-unmatched trailing `end` are both stripped, degrading
      to plain top-level messages rather than crashing), and force-closes any fragment still open
      at the very end with a synthetic `end`. This guarantees `SequenceDiagramValidator`'s own
      balance check can never actually fail downstream of this point -- a small, deliberate
      trade of semantic precision (a dropped branch loses its intended grouping) for the one
      guarantee that matters: the run completes. New `TestFragmentBalanceSanitizer` (5 tests in
      `tests/test_architecture_sequence_modeler.py`) covers the exact real bug shape, a
      well-formed alt/else/end left untouched, a never-closed fragment force-closed, a dangling
      end with nothing open dropped, and correct behavior across nested fragments.
    - Full backend suite after both fixes: **881 passed** (up from 876 after Part B's own finish,
      then +5 for the sanitizer). `npm run build` clean (Part A's composer fix, already
      implemented in the prior segment, needed no further changes).
    - **Live backend restart, explicitly confirmed with the user first** (`AskUserQuestion`,
      "Yes, restart it now"): the live main backend's `--reload` watcher (which watches the
      WHOLE `agentic_service` directory, not just `app/`) had only logged one real reload event
      despite the many files this segment (and the prior, compacted portion) touched -- too
      risky to trust for the actual deliverable run, so the reloader/worker process tree was
      stopped and relaunched identically before generating anything for real.
    - **Real, live deliverable verification against the user's own real Finodil project**
      (`proj_2ba24bc0`, feature `feature_917b691e` "Login and Signup", real approved SRS +
      Enhanced SRS already in place): re-ran the real Architecture Agent multiple times to
      produce the actual requested deliverable. `POST /architecture/run/stream` (single-shot
      rung only, per `run_stream`'s own design) landed on the true deterministic-fallback rung
      twice in a row -- confirmed via each `human_approval_note`'s own honest anemic-DTO caveat,
      not a code bug -- with the currently-configured global model (`qwen2.5-coder:14b`, no
      per-agent override set for `architecture_agent` on this live system, a real configuration
      drift from item 74's own documented intent) failing single-shot generation of the large
      combined plan schema, a known, already-extensively-documented class of local-model
      limitation (items 24/26/27). Temporarily set a real `architecture_agent` override to
      `qwen3-coder:latest` (matching item 74's own documented intended pin) and re-ran via the
      full agentic-first ladder (`POST /architecture/run`, non-streaming) -- this is the run that
      hit the sequence-fragment-balance crash above; after the sanitizer fix, a subsequent
      attempt again landed on the deterministic fallback rung (the single-shot/repair rungs
      still failing schema validation against this real, large SRS+Enhanced-SRS combination --
      an honest, separately-documented, out-of-scope local-model reliability limit, not this
      session's own regression) but this time completed successfully end-to-end, saving a real
      v3 Architecture Plan with all 8 artifacts (Plan JSON+MD, use case/sequence/class diagrams
      PUML+PNG). Directly inspected the real generated use case diagram: actor `<<system>>`
      stereotype correctly rendered on a non-human actor (mechanically confirming Part B's fix is
      live and working) -- though, honestly noted, the underlying use-case NAMES on this
      particular fallback-path run were still garbled sentence fragments, a SEPARATE,
      already-documented (item 25) deterministic-fallback naming-quality gap this session's own
      scope never touched (Parts B/C/D are about relationships/stereotypes/fragments/naming-
      consistency, not the fallback's own name-cleaning quality). This real v3 state is left in
      place as genuine, honestly-mixed verification evidence (a real, confirmed fix mechanically
      present, alongside a real, separately-tracked, unrelated quality gap also visible in the
      same output) rather than cherry-picked for a cleaner story.
    - **A second, separately-reported real bug, mid-session: "I can not run the coder agent
      output in the preview section it shows an error"** (`No build found for this feature yet --
      run the Coder Agent (or a revision) first, then try previewing again`), with a screenshot
      showing the Coder Agent chat itself reporting a completed v1 run. Root-caused directly via
      the real, saved v1 merge report: `next build`/`npm install` both failed with `"Sandbox
      unavailable: could not reach Docker daemon"` -- Docker Desktop was not running when the
      original coding loop's `verify()` ran, so `.next/BUILD_ID` never existed, and Preview's own
      documented refusal (item 52: "Start refuses (409) if no `.next/BUILD_ID` exists yet") was
      working exactly as designed, just on code that had never actually been built. Started
      Docker Desktop, then re-verified the SAME already-generated code directly (no re-planning,
      no re-invoking the LLM -- matching this project's own long-established "re-verify already-
      generated code" precedent, items 20/27/52/72): `npm install` now passed, but `next build`
      failed for real, revealing two genuine, confirmed code bugs the original coding loop had
      introduced and Docker's outage had hidden from ever surfacing:
      1. `app/api/auth/login/route.ts` and `app/api/auth/signup/route.ts` both `import bcrypt
         from "bcryptjs"` for password hashing, but `bcryptjs` was never declared in
         `package.json` (the plan's own `new_dependencies` was empty) -- `Module not found:
         Can't resolve 'bcryptjs'`. Root cause, confirmed by reading `CODER_AGENT_SYSTEM_PROMPT`
         directly: the `run_shell` tool-usage rule explicitly told the model NOT to install
         anything beyond the plan's own `new_dependencies`, actively discouraging exactly the
         self-correction (`npm install bcryptjs --save`) that would have fixed this on its own.
      2. Both route files also `import connectToDatabase from "@/lib/mongodb"` (a default
         import), but the real scaffold's `lib/mongodb.ts` exports it as a NAMED export
         (`export async function connectToDatabase(...)`) -- `next build` correctly failed with
         "does not contain a default export." The prompt named the function and its
         null-vs-throw behavior correctly but never stated its exact import syntax.
      - **Fixed both directly** (added `bcryptjs`/`@types/bcryptjs` to `package.json`; corrected
        both route files' import to `import { connectToDatabase } from "@/lib/mongodb";`),
        committed as a real git commit on the feature branch, matching item 23's own "small,
        mechanical, real fix applied directly rather than through a slow revise() cycle"
        precedent -- and **hardened `CODER_AGENT_SYSTEM_PROMPT` at the root** so a future feature
        doesn't repeat either mistake: the `run_shell` rule now explicitly instructs installing a
        genuinely-needed undeclared package via `npm install <package>@<version> --save` (the
        tool's own allowlist, confirmed by reading `tools.py`'s `ALLOWED_SHELL_COMMANDS = {"npm",
        "npx", "node"}`, already permits this -- only the prompt was discouraging it) rather than
        writing an import for a package that was never installed; the `lib/mongodb.ts` connect-
        helper rule now states its exact named-import syntax explicitly and names the real,
        confirmed build error a default import produces. New tests locking both rules in `tests/
        test_coder_prompt.py` (+2). Full suite: **883 passed** (up from 881).
      - **Re-verified for real, iteratively, after each fix** (three full `npm install` + `next
        build` cycles against the real, live Docker daemon): the bcryptjs fix alone still left
        the named-import bug (a distinct, second real error); after both fixes, verification
        passed **cleanly end-to-end** -- `next build`, `server boot (next start + /api/health)`,
        `page reachability`, and `home page render` all passed, plus an informational `feature
        page render` step confirming `/login-and-signup` itself "responded with HTTP 200 and no
        JS errors." Saved as v4 (v2/v3 -- the intermediate, honestly-failing snapshots from
        before each fix -- left in place as real evidence, not cleaned up, matching this
        project's own established convention). **Confirmed live through the actual browser, not
        just status codes**: started the real preview (`POST /features/{id}/preview/start`,
        real Docker container, real assigned port), navigated to it with Playwright, and
        screenshotted a genuinely rendered, styled "Sign in to your account" form (email/password
        fields, Sign In button, a working "Don't have an account? Sign up" link) with zero
        console/page errors -- the user's exact reported symptom (Preview refusing to start) is
        confirmed fixed against their own real project, not a synthetic reproduction. Preview
        stopped afterward to avoid leaving a container running.

82. **AutoForge frontend polish: relocated the "Using X vN for Y Agent" pills, removed Deployment
    Agent entirely, forward-gated the chat's agent picker to the pipeline's current reachable
    stage, and modernized the version dropdown.** Four direct user requests. Investigated
    directly (own reading + one Plan-agent validation pass, which resolved three open design
    questions and caught a real edge-case bug before it was written). Plan file:
    `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Relocate the pills** (`frontend/src/components/output/OutputPanel.jsx` /
      `ResultTab.jsx`): the "Using Architecture Plan vN for Coder Agent" style indicator (item
      77's generalized version) previously rendered inside the Output panel's TAB BAR, next to
      Result/Files/Preview -- moved verbatim (both `PREVIOUS_STAGE_INPUTS_BY_STAGE`/
      `NO_ARTIFACT_VERSION_LABEL_BY_STAGE` maps and the render IIFE) into `ResultTab.jsx`'s own
      content, rendered above "All Artifacts" -- reuses the `feature` variable `ResultTab.jsx`
      already fetches for an unrelated purpose (active-artifact-selection pinning), no new fetch.
      `OutputPanel.jsx`'s tab bar is now just the tab buttons.
    - **Remove Deployment Agent completely** (a permanent stub since M7, confirmed via direct
      grep to have zero references in `graph_orchestrator_service.py` -- never wired into the
      LangGraph at all, safe to delete outright): backend --
      `app/agents/deployment_agent/` (whole dir), `AgentName.DEPLOYMENT`/`ArtifactType.DEPLOYMENT`
      (`app/core/enums.py`), the `POST /deployment/run` placeholder route
      (`app/api/routes/agents.py`), the `AgentName.DEPLOYMENT: "08_deployment"` folder mapping
      (`app/services/artifact_service.py`), plus a stale comment fix in
      `app/services/llm_provider_service.py` (also corrected: that comment claimed Security/QA
      were still stubs too, which hasn't been true since items 73/75 -- `OVERRIDABLE_AGENTS`
      still doesn't include them, a real, separate, pre-existing gap left honestly noted rather
      than silently fixed, since adding Security/QA LLM-override support was never asked for
      here). Frontend -- `frontend/src/lib/pipelineStages.js`'s `PLACEHOLDER_STAGES` deleted
      entirely (not left as an empty array -- its only two consumers are both touched by this
      same change, and an empty array would leave `ModelSelect.jsx`'s fallback branch as
      permanently dead code), plus `STAGE_LABELS.deployment`/`STAGE_ROLE_LABELS.deployment`;
      `AgentSelect.jsx`'s `DISPLAY_STAGES = [...STAGE_SEQUENCE, "deployment"]` splice deleted
      (the only reason deployment ever appeared in the agent picker); `ModelSelect.jsx`'s
      `isSelectable`/dead-branch deleted.
    - **Forward-gate the agent picker** (`frontend/src/components/chat/AgentSelect.jsx` /
      `components/workspace/WorkspaceSelectionContext.jsx`): direct user request -- while still
      on, say, the Coder Agent stage (not yet approved), a human should not be able to jump
      straight to Security/QA's chat. Centralized "what stage is currently reachable" in
      `WorkspaceSelectionContext` (mounted once per open workspace, already the shared home for
      "what are the three sibling panels looking at right now") rather than the leaf
      `AgentSelect` -- reuses the exact `useGraphStatus`+`useFeatureArtifacts` ->
      `deriveStageStatus` -> `deriveCurrentStage` pipeline already proven in
      `FeatureListItem.jsx`, React-Query-cache-deduped against whatever `ResultTab`/`OutputPanel`
      already fetch for the same feature, so this adds no new network request. `AgentSelect`
      disables every `SELECTABLE_AGENT_STAGES` option whose index exceeds the current stage's --
      stages at or before current stay freely selectable, so revisiting an earlier agent's chat
      history is never blocked, only forward-jumping past the pipeline's frontier is.
      **A real edge-case bug caught by the Plan-agent review before this was ever written**:
      `deriveCurrentStage` returns `undefined` once every stage is APPROVED (a fully-completed
      feature) -- the naive `|| "requirement"` fallback (copied from `FeatureListItem.jsx`'s own
      pre-existing use of this same function) would have incorrectly RE-LOCKED the picker down to
      only Requirement for a finished feature. Fixed with
      `deriveCurrentStage(...) ?? SELECTABLE_AGENT_STAGES.at(-1)` instead -- once every real stage
      is approved, nothing is gated. Applied the identical, now-corrected fallback to
      `FeatureListItem.jsx`'s own pre-existing instance of the exact same bug while touching this
      pattern (a fully-completed feature's list-row status was misreporting as "Requirement" --
      a one-line, low-risk consistency fix directly adjacent to this change, not new scope).
    - **Modernize the version dropdown** (`frontend/src/components/chat/PillDropdown.jsx`, new
      `frontend/src/components/output/VersionSelect.jsx`): three near-identical raw `<select>`
      elements in `ResultTab.jsx` (shown as plain text, e.g. "v4 -- pending") replaced with a new
      `VersionSelect` built on the existing `PillDropdown` (already used by `AgentSelect`/
      `ModelSelect`, a custom rounded-popup picker instead of a native select). `PillDropdown`
      gained a `direction: "up" | "down" = "up"` prop (only the popup's positioning classes
      change; both existing call sites keep their current upward-opening behavior unchanged) --
      `VersionSelect` uses `direction="down"` since it sits near the panel TOP, not the bottom
      composer bar. Each version option's label is now `vN` plus a real, color-coded
      `StatusBadge` (pending/approved/rejected/revision_requested) instead of plain text.
      **A real specificity risk found and fixed while implementing this, flagged in advance by
      the Plan-agent review**: `PillDropdown`'s trigger button hardcoded `max-w-[160px]` directly
      in its base className string, with `triggerClassName` appended AFTER it -- two equal-
      specificity Tailwind utility classes in one string do not reliably resolve by JSX
      left-to-right order (Tailwind's generated CSS order depends on build-wide first-discovery
      order, not per-file string position), so a caller's own `max-w-*` override was not
      guaranteed to actually win. Fixed by moving `max-w-[160px]` OUT of the base string entirely
      and into `triggerClassName`'s own prop DEFAULT -- a caller passing its own value is now the
      only max-w class ever present for that instance, no conflict possible.
    - Backend test suite unaffected by the frontend work; re-run after the Deployment Agent
      removal to confirm zero breakage (it was never exercised by any real test -- no fixture
      updates needed). Full suite: **883 passed** (unchanged count from item 81 -- pure removal,
      no new backend tests needed). `npm run build` clean (1341 modules).
    - **Real, live verification against the real Finodil "Login and Signup" feature**
      (`proj_2ba24bc0`/`feature_917b691e`, genuinely at the Coder Agent stage with 4 real Coder
      Agent versions -- the same feature items 79-81 worked on), through an actual browser, not
      just the API: confirmed via screenshot that the tab bar (Result/Files/Preview) now shows
      only tab buttons, with "Using Architecture Plan v3 for Coder Agent"/"Using UI/UX Output v1
      for Coder Agent" rendering directly under the Result content instead, right above "All
      Artifacts"; confirmed "Deployment" appears nowhere on the page and the live backend's own
      OpenAPI schema has zero `/deployment` paths (`GET /openapi.json`, grepped directly);
      confirmed via `is_disabled()` (not just a screenshot) that opening the agent picker while
      on the Coder stage shows Security/QA genuinely `disabled=True` while Requirement/Domain/
      Architecture/UI-UX/Coder stay enabled, screenshot-confirmed visually greyed-out too;
      confirmed the version dropdown opens downward with real colored status badges per version
      (v4/v3/v2/v1, all "Pending" for this real in-progress feature), and that clicking a
      different version (v1) genuinely swaps the rendered merge-report content (v1's real,
      pre-Docker-fix "Sandbox unavailable" failure text, correctly different from v4's real
      "Verification: PASSED") while the "Download report" link stays present -- a functional
      check, not just a visual one. Separately confirmed the Requirement stage (which has no
      "Using X" pill by design) renders with no visual gap/artifact where the pill would have
      been, and that stage remained freely selectable in the picker despite the feature's current
      stage being Coder (revisiting an earlier stage is never blocked). Zero console/page errors
      across every screenshot taken.

83. **Architecture Plan requirement tables, a real "revoke approval" capability (with a
    genuinely-reachable git bug found and fixed along the way), a renamed "Full diff" heading,
    and a Coder-Agent-approval popup that auto-runs Security Agent.** Four direct user requests
    against the real, live Finodil "Login and Signup" feature. Investigated directly (3 parallel
    Explore agents -- the table-rendering root cause, the approval/revoke mechanism plus the real
    git state, the "Full diff" heading's actual source -- plus direct reading of `ResultTab.jsx`'s
    existing `APPROVE_CONTINUATION_BY_STAGE` mechanism). Plan file:
    `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Ask 1 -- tabular Requirement Interpretation**: root-caused directly against the real
      generated `login_and_signup_architecture_plan_v1.json` -- `DocumentValue.jsx`'s array-of-
      objects -> `<table>` renderer already existed and already produced exactly the wanted ID/
      Description/Priority table, but `isFlatObject`/`isTableCellValue` was all-or-nothing across
      the WHOLE array: a single Domain-Agent-enriched row carrying a nested `domain_citation`
      object disqualified the entire array from table form, falling every row (including plain
      ones) back to stacked ID/DESCRIPTION/PRIORITY label cards -- exactly what the user's
      screenshot showed. Fixed in `DocumentValue.jsx` only (no changes to
      `ArchitecturePlanDocumentViewer.jsx`/`SubSectionList`, so Functional Requirements,
      Acceptance Criteria, Non-Functional Requirements, and Validation Rules are all fixed
      identically by one change): `isTableCellValue` now also accepts a plain nested object whose
      own values are themselves scalars/flat arrays; the `<td>` render branch gained a case
      rendering such a cell as a compact `key: value` summary in small italic gray text instead
      of `[object Object]`. `EnrichedItemList.jsx` (the SRS's own deliberately different
      color-coded card view) was left untouched, per its own separate rationale.
    - **Ask 2 -- a real, reusable "revoke approval" capability, applied live**: no existing status
      transition moved an artifact from `approved` back to `pending`, and for the Coder Agent
      specifically, approving had already run a real `git merge --no-ff` into `main` and deleted
      the feature branch (confirmed via `git log --graph` against the real repo before writing
      any code) -- a real revoke had to reverse both the data flag and, for Coder Agent, the git
      state, or the approval record and the real code would silently disagree. New
      `workspace_service.undo_merge_feature_branch(project_id, feature_id)`: finds the merge
      commit by searching main's history for the exact, real message
      `merge_feature_branch` itself writes (`f"Merge {branch_name} into main"` -- confirmed via
      direct `git log` inspection, not guessed), recreates the feature branch at its pre-merge
      tip, and reverses the merge on `main` via a real, non-destructive `git revert -m 1
      --no-edit` (never a reset/force-push). New `ApprovalService.revoke_approval` (mirrors
      `artifact_service.delete_artifact`'s own "operate on the whole version, not one
      artifact_id" convention -- reverts the whole same-type-same-version sibling group together,
      e.g. a JSON+Markdown pair); reuses the existing `_cascade_architecture_plan_decision`/
      `_cascade_uiux_screenshot_decision` helpers (now returning the artifact_ids they touched,
      not `None`, so `revoke_approval`'s own `reverted_artifact_ids` response is honest and
      complete -- a real gap caught by this item's own new tests, not assumed correct) for
      Architecture Plan/UI-UX Preview Screenshot specifically, since those already fully cover
      their own format-pair + sibling-type cascade and running the generic loop too would
      double-revert. New route `POST /artifacts/{artifact_id}/approval/revoke` +
      `ApprovalRevokeRequest`/`ApprovalRevokeResponse` schemas. Frontend: new
      `revokeApproval`/`useRevokeApprovalMutation` (mirrors `useApprovalMutation`, including
      fixing that same pre-existing hook's own un-awaited `invalidateQueries` calls while touching
      it -- the same bug class items 45/49 already fixed elsewhere); a "Revoke approval" action
      added to `GovernancePanel.jsx`'s "already approved, nothing pending" branch and to
      `ArtifactRow.jsx` for any individually-approved row, both behind a `ConfirmDialog` naming
      the real git consequence for the coder stage specifically. `APPROVAL_WARNINGS.coder`'s text
      updated from "Neither is undoable" (no longer accurate) to describe the real revoke path.
    - **A second, real, more serious git bug found ONLY by live-testing the whole loop
      end-to-end (approve -> revoke -> re-approve), not by any unit test written first**: after
      `undo_merge_feature_branch`'s `git revert`, a plain subsequent `merge_feature_branch` call
      (the existing, unchanged approval-side merge, triggered by re-approving the SAME code with
      no new commits) silently no-op'd ("Already up to date") instead of actually re-applying the
      branch's changes -- reverting a merge does NOT remove the merged branch's commits from
      main's ancestry graph, only undoes their effect, so git's ancestry-based merge algorithm
      correctly-but-unhelpfully concluded there was nothing new to merge. Confirmed live and
      directly: after re-approving via the real UI, the artifact showed `approved` while `main`'s
      actual working tree still had none of the login/signup code (`find app/api` showed only the
      scaffold's own `health/route.ts`), and the feature branch had been deleted by the "merge"
      that never actually merged anything. Fixed in `merge_feature_branch` per `git revert`'s own
      manual ("Reverting a merge commit"): checks whether the branch tip is already an ancestor
      of `main` (`git merge-base --is-ancestor`); if so, finds the matching `Revert "Merge ...
      into main"` commit and reverts THAT REVERT instead of attempting a normal merge -- this
      restores the real content without rewriting history, and correctly falls through to a
      normal merge instead whenever the branch actually has new commits (revise() adds commits
      that are never ancestors of the earlier revert, so the ancestry check correctly returns
      false in that case). New `_find_merge_commit_for_branch` helper, shared by both
      `merge_feature_branch` and `undo_merge_feature_branch` (DRY, was duplicated inline before).
      **Real state repaired directly afterward**: manually confirmed the feature branch and
      `main` were both left correct (branch restored via the fixed revoke call, `main` still
      correctly unmerged) via `git log --graph`/`git branch`/`find app/api` -- the real Finodil
      project ends this item in exactly the state the user asked for (Coder Agent v4 genuinely
      `pending`, real feature branch restored with all real prior work, `main` clean).
    - **Ask 3 -- rename "Full diff"**: root-caused to a backend-generated Markdown `## ` heading
      (`coder_agent/diff_builder.py::build_merge_report_markdown`), not frontend JSX --
      `DiffViewer.jsx` just splits the one Markdown string on the fenced ` ```diff ` block and
      never hardcodes the heading text. Renamed to `"## Detailed Code Changes (Line-by-Line
      Diff)"`; `DiffViewer.jsx`'s own code comment updated to match. Also directly edited the
      real, already-saved Finodil merge report Markdown files (v1-v4) on disk, replacing the old
      heading text in place -- a safe, cosmetic-only substitution so the user's real,
      already-generated output reflects the rename immediately without a re-run.
    - **Ask 4 -- Coder Agent approval popup + auto-run Security Agent**: extended the existing,
      already-proven `APPROVE_CONTINUATION_BY_STAGE`/`ConfirmDialog`/`handleConfirmedApprove`
      mechanism (`ResultTab.jsx`, previously covering Requirement->Domain->Architecture->UI/UX)
      with a `coder -> security` entry -- this is also the FIRST time approving Coder Agent's
      output goes through any confirmation popup at all (previously skipped straight to
      `approval.mutate(...)`), so the real, serious merge warning is now finally surfaced at the
      actual moment of clicking Approve, not just in `GovernancePanel`'s fine print. New
      `SecurityAgentFlowContext.jsx` (mirrors `UiuxAgentFlowContext.jsx`, wrapping a single shared
      `useRunSecurityAgent` mutation) fixes the exact "two independent mutation instances can't
      see each other's pending state" bug item 61 already found for UI/UX Agent -- without it,
      `SecurityReportView.jsx` and the new auto-trigger would each hold separate state, so a scan
      started from the popup would show no visible progress anywhere. `useSecurityAgent.js`'s own
      pre-existing un-awaited `invalidateQueries` calls fixed too, for the same reliability
      reason. New `isSecurityGenerating` branch in `ResultTab.jsx`'s `LiveGenerationView` chain
      (isFinalizing mode, spinner + elapsed timer -- Security Agent has no streaming route, a scan
      is one plain POST) so switching to the Security stage mid-scan shows real progress instead
      of `SecurityReportView`'s bare empty state.
    - **A real, live-found display bug in the shared confirm-dialog mechanism itself, affecting
      every stage that uses it, not just this new one**: `confirmingArtifact` was looked up via
      `stageArtifacts.find(...)`, but `stageArtifacts` deliberately excludes Coder Agent's own
      gating type (`code_diff`, in `UNLISTED_ARTIFACT_TYPES`) -- so the popup's `version`
      interpolation silently rendered as `"Approving vundefined..."` for the Coder stage
      specifically, confirmed via a real screenshot before the fix. The underlying approval call
      itself was unaffected (it uses `confirmingArtifactId` directly, never the resolved object),
      so this was a display-only bug, not a functional one -- still fixed, by switching the
      lookup to the unfiltered `allArtifacts` prop instead, which is safe for every other stage
      too since none of their own gating types are excluded from `stageArtifacts`.
    - Tests: `tests/test_workspace_undo_merge.py` (new, 4 -- real git repos via `tmp_path`,
      mirroring `test_workspace_scaffold.py`'s own fixture convention: restores branch + reverts
      main on undo, safe no-op with no prior merge, safe no-op with no repo history at all, and
      the exact live-found re-merge-after-revert bug reproduced and confirmed fixed).
      `tests/test_approval_revoke.py` (new, 9 -- moves to pending with an honest approval record,
      raises for a not-approved/unknown artifact, reverts a JSON+Markdown pair together, never
      touches a different version's sibling, cascades Architecture Plan to its diagrams with no
      double-revert, calls/skips the git undo correctly for a coder vs. non-coder artifact type).
      `tests/test_approval_revoke_route.py` (new, 4, real `TestClient`). Full suite: **900
      passed** (up from 883), including the `merge_feature_branch` fix's own regression test.
      `npm run build` clean (1342 modules).
    - **Real, live verification against the real Finodil "Login and Signup" feature**, not
      synthetic: screenshots confirmed the Requirement Interpretation tables render cleanly with
      real ID/Description/Priority/Origin/Domain Citation columns (matching the user's own
      reported screenshot's exact content, now fixed); the real revoke endpoint was called
      against the real, already-approved-and-merged `code_diff` v4 artifact and confirmed via
      `git log --graph`/`git branch` to produce a genuine revert commit (history preserved, not
      rewritten) and a restored `feature/login-and-signup` branch; the Result tab's diff section
      was confirmed to read the new heading both in a fresh render and in the real, in-place-
      edited Finodil artifacts; the real approve popup was driven through an actual browser,
      confirmed to name the merge consequence and Security Agent correctly, and confirming it
      switched to the Security stage and fired a real `POST .../security/run` request (which is
      also what surfaced the re-merge-after-revert git bug above, live, before it could reach the
      user again). Zero console/page errors across every screenshot taken.

84. **Opening a project (or switching features) now jumps straight to the last-executed agent,
    instead of always resetting to Requirement -- plus a real, pre-existing React Router race
    bug found and fixed along the way.** Direct user request, with the real Finodil project as
    the explicit example: "the user lastly worked on the Coder Agent... the system must show the
    lastly executed agent whenever the user opens a project." Investigated directly (3 parallel
    Explore agents: project-open navigation + `deriveCurrentStage` reuse-ability, feature/agent
    "last activity" timestamp tracking, and the project/feature list click-through path). Plan
    file: `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Part A -- which agent to show, reusing existing machinery, no new backend calls**:
      confirmed `deriveCurrentStage` (`frontend/src/lib/deriveCurrentStage.js`, already used by
      item 82's forward-gated agent picker) already correctly answers "which agent's UI
      represents this feature's real current position" for exactly the stated example (every
      earlier stage approved, Coder Agent has real pending output -> resolves to `"coder"`).
      `WorkspaceSelectionContext.jsx` already computed this as `currentStage` for the selected
      feature; only needed a new mechanism to actually USE it as `selectedAgent`'s default when
      no explicit `?agent=` is present. New `autoSelectedFeatureRef` (tracks which `featureId` an
      agent has already been auto-resolved for, so it only ever fires once per feature -- never
      fights a later manual pick) + a `useEffect` that seeds `selectedAgent` from `currentStage`
      once it's ready.
    - **A real bug found live, before this was usable at all**: the first version's effect used
      `if (!currentStage) return` as its "still loading" guard -- but `currentStage` is NEVER
      actually falsy while data is loading, because `deriveStageStatus` treats a not-yet-arrived
      `artifacts` array the same as a genuinely empty one (`artifacts || []`), so
      `deriveCurrentStage` immediately (and wrongly) returns `"requirement"` before the real data
      ever arrives, and the ref guard then locks that wrong answer in forever for the feature.
      Confirmed live: opening the real Finodil project landed on `?agent=requirement` instead of
      `coder`. Fixed by gating on the underlying queries' own real `isLoading` flags
      (`useGraphStatus`/`useFeatureArtifacts`) instead of `currentStage`'s truthiness -- re-verified
      live afterward, correctly lands on `?agent=coder`.
    - **Part B -- which feature to default to when a project is opened fresh**: `Feature.
      updated_at` existed on the schema but was dead data (set once at creation, confirmed via
      direct grep across `app/`, never bumped by any real action). Confirmed every real
      user-initiated action in this system funnels through exactly 3 backend choke points:
      `stage_event_service.record()` (every run/revise/clarify/confirm across all 6 agent stages)
      and `ApprovalService.submit_approval`/`revoke_approval` (every approve/reject/
      revision-request/revoke) -- each gained an identical 2-line `feature["updated_at"] = ...`
      update (mirrors `routes/projects.py`'s own existing `project["updated_at"] = datetime.
      utcnow()` pattern), making the field real without touching ~30 individual call sites.
      `ProjectWorkspacePage.jsx`'s `effectiveFeatureId` fallback changed from `features?.[0]?.
      feature_id` (backend insertion order, confirmed via reading `list_project_features` --  no
      `.sort()` at all) to a plain client-side `reduce` picking the feature with the latest
      `updated_at` -- no new network call, no change to the general API response order (the
      sidebar's own feature list keeps its current display order; only the default SELECTION
      changes). `Feature.current_agent` (a separate, similarly-dead field) deliberately left
      untouched -- `deriveCurrentStage` already gives Part A everything it needs without it, and
      fixing it properly would need touching every individual agent's own `run()`/`revise()`.
    - **A second, real, more serious pre-existing bug found ONLY by live-testing the actual
      manual-feature-switch flow (not predicted by reading the code, not something this item's
      own changes introduced)**: clicking a DIFFERENT feature in the sidebar while the URL had no
      explicit featureId in its path (exactly the state a fresh project-open leaves you in, both
      before AND after this item's own Part B change -- the default selection has never written
      its own featureId into the URL path) silently reverted the ENTIRE navigation, including the
      pathname, back to wherever the URL was before the click -- confirmed directly via network-
      request monitoring: the real `GET /features/{id}/...` calls for the target feature fired
      (proving the internal state briefly did change), but the final, settled URL and on-screen
      content both reverted to the PREVIOUS feature. Root-caused to `WorkspaceSelectionContext.
      jsx`'s `selectFeature`, which called TWO separate router-mutating functions in the same
      handler -- `onSelectFeature(id)` (a `navigate()` to the new path) immediately followed by
      `setAgentQueryParam(null)` (a `setSearchParams()` call to clear `?agent=`) -- the second
      call resolves against a STALE captured `location.pathname` from before the first call's
      change had committed, so its own `{replace: true}` overwrote the just-set path back to the
      old one. Fixed by removing the now-redundant second call entirely: `navigate()` to a plain
      path with no `?query` string already fully replaces the location (clearing any prior search
      string) as a normal side effect -- one router call instead of two, no race possible.
      **This was a genuinely pre-existing bug**, not introduced by this session's own Part A/B
      work, but it directly blocked verifying (and would have undermined in real use) the very
      feature this item exists to build, so it was fixed here rather than filed away separately.
    - Tests: `tests/test_feature_last_activity.py` (new, 5 -- `stage_event_service.record()` and
      both `approval_service` methods bump the real feature's `updated_at`; a safe no-op for an
      unknown feature_id; a direct end-to-end proof that a real action on an OLDER feature makes
      it "more recently active" than a newer-but-untouched one, matching exactly what
      `ProjectWorkspacePage.jsx`'s own `reduce` picks the max of). Full suite: **905 passed** (up
      from 900). `npm run build` clean (1342 modules). No frontend test framework exists in this
      repo (per every prior item's own note), so the loading-race bug and the router-race bug were
      both found and fixed via live browser verification, not unit tests.
    - **Real, live verification, not synthetic**: opening the real Finodil project fresh (bare
      `/projects/proj_2ba24bc0`, no featureId/agent) now correctly lands on
      `?agent=coder` with the Coder Agent's real merge report/verification steps showing --
      exactly the user's own stated example. Opening the real, 5-feature TaskFlow project fresh
      correctly landed on "Task Add" (`feature_bdacfeef`, real highest `updated_at`) rather than
      "Task Comments" (`feature_5521adbd`, what the old `features[0]` array-order fallback would
      have picked -- direct, real proof the fix changes real behavior, not a coincidental match).
      Manually clicking "Task Comments" in that same project's sidebar afterward correctly
      navigated to `/features/feature_5521adbd?agent=coder` (its own real, extensive Coder Agent
      history -- v18 setup instructions, real verification steps) -- confirming the router-race
      fix and Part A's auto-select compose correctly together. A full reload with an explicit
      `?agent=requirement` on the real Finodil feature (whose actual progress is Coder) correctly
      still showed Requirement Agent's content, confirming item 44's original deep-link/reload
      behavior is unregressed by any of this. Zero console/page errors across every screenshot.

85. **An "Approve & Move to Security" button next to the Coder Agent's version dropdown, plus a
    real, live-streaming Security Agent chat mirroring QA Agent's own.** Three direct user
    requests. Investigated directly (2 parallel Explore agents: the existing Coder-approval popup
    mechanism's exact reusability, and QA Agent's own chat implementation as the precise template
    to mirror). Plan file: `C:\Users\ASUS\.claude\plans\soft-petting-star.md` at time of writing.
    - **Asks #1/#2 -- a new, more prominent trigger for an already-built mechanism**: confirmed
      the popup + auto-run-Security flow (`APPROVE_CONTINUATION_BY_STAGE.coder`,
      `requestApproveConfirmation`, one shared `ConfirmDialog`, `handleConfirmedApprove`'s
      `nextAgent === "security"` branch) already existed in full from the immediately preceding
      session (item 82's Ask 4) -- this needed only a new, more visible trigger, not new backend
      work. `ResultTab.jsx`'s version-dropdown row hoisted its previously-duplicated inline
      `versions.find(...)` lookup into one `selectedVersionArtifact`, reused by both the existing
      "Download report" link and a new "Approve & Move to Security" button (rendered only for
      `stage === "coder"` when the selected version is genuinely `pending`), which simply calls
      `requestApproveConfirmation(selectedVersionArtifact.artifact_id)` -- the exact same function
      `GovernancePanel`/`ArtifactRow`'s own Approve buttons already call, guaranteeing identical
      popup wording regardless of which surface triggered it.
    - **Ask #3 -- a real Security Agent chat, mirroring QA Agent's own (item 75) precisely**:
      new `store.security_conversations` Mongo collection (identical shape to `qa_conversations`
      -- one document per `feature_id`, upserted in place, unique index, cascade-deleted with the
      feature/project). New `SecurityChatMessageRequest`/`SecurityChatTurn`/
      `SecurityChatHistoryResponse` schemas (`security_schema.py`), identical to QA's own. New
      `SecurityAgent._get_chat_history`/`_append_chat_turns`/`chat_stream` (`agent.py`) mirroring
      QA's methods exactly (same NDJSON `{"type":"token"|"done"|"error",...}` event shape, same
      stream-then-persist-both-turns flow) -- loads report context via the already-existing
      shared `artifact_service.get_selected_or_latest_approved_artifact` (item 36) rather than a
      new private per-agent finder, since Security Agent never had one of its own (`run()` always
      generates a fresh report, it never looks a prior one up) -- a small, deliberate improvement
      over blindly copying QA's own private-duplicate pattern. New `_summarize_report_for_chat`
      renders the real gate decision, tier counts, and each finding's severity/rule_id/CWE/
      file:line/message (matching `SecurityReportView.jsx`'s own exact real field names). New
      `SECURITY_CHAT_SYSTEM_PROMPT` (`prompt.py`), mirroring `QA_CHAT_SYSTEM_PROMPT`'s exact
      "answer only from the real report, discuss don't edit code" framing -- code-editing stays
      the separate, already-built "Send to Coder Agent" button (`securityReportToRevisionComment.js`),
      untouched by this work. New `GET /security/chat` + `POST /security/chat/stream` routes
      (`agents.py`), identical shape to the existing QA routes. Frontend: new
      `getSecurityChatHistory`/`securityChatStream` (`api/agents.js`), new
      `useSecurityChatFlow.js` (mirrors `useQaChatFlow.js` **exactly**, including its already-
      correct `onSuccess: async () => { await queryClient.invalidateQueries(...) }` -- the
      item-49 disappearing-bubble fix copied forward from the start, not reintroduced and fixed
      later), new `SecurityAgentChat.jsx` (mirrors `QaAgentChat.jsx`'s structure) -- deliberately
      reuses the SAME shared `useSecurityAgentFlowContext()` mutation the Result panel's Run/
      Re-run button and the Coder-approval auto-trigger already observe for its own empty-state
      "Run Security Scan" action, rather than a new independent mutation (avoiding reintroducing
      the exact "two independent mutation instances can't see each other's pending state" bug
      item 61 already found and fixed for UI/UX Agent). `ChatPanel.jsx` gained a
      `selectedAgent === "security"` dispatch branch, removing the old disabled "Security Agent
      can't be messaged directly right now" placeholder for this stage specifically. Several
      now-stale "Security Agent has no chat" comments across the frontend (`useSecurityAgent.js`,
      `SecurityAgentFlowContext.jsx`, `SecurityReportView.jsx`, `ResultTab.jsx`,
      `QaAgentChat.jsx`) updated to reflect the new reality while touching this area.
    - Tests: `tests/test_security_agent.py` gained a new `TestSecurityChat` class (6 tests --
      report summarization including every real field, graceful degradation on missing optional
      fields, empty history for a fresh feature, turn persistence/accumulation, and two real
      `chat_stream` async-generator tests confirming token-then-done events plus real turn
      persistence, and a provider-unreachable case yielding a clean error event with nothing
      persisted). `tests/test_security_agent_routes.py` gained 6 new route tests mirroring
      `test_qa_agent_routes.py`'s own chat-route coverage exactly (404 on unknown feature, empty/
      persisted history, NDJSON event passthrough, error-event translation on an unexpected
      exception). Full suite: **917 passed** (up from 905). `npm run build` clean (1344 modules).
    - **Real, live verification against the real Finodil "Login and Signup" feature**, not
      synthetic: confirmed the new button renders next to the version dropdown for the real
      pending Coder Agent v4, clicking it shows the exact same popup text already proven in item
      82's own verification, and confirming it produced a real git merge (`git log` showed a
      genuine "Reapply" commit -- direct, live proof the item-84 merge-after-revert fix also
      composes correctly with this new trigger). Directly triggered a real security scan
      (`POST /security/run`) to get real report content to verify the chat against (0 findings,
      gate=pass -- a real, accurate result now that item 73's `.env.local` exclusion fix is in
      place). Drove the real chat through an actual browser: composer genuinely enabled (old
      disabled placeholder confirmed absent), a real question ("Were any vulnerabilities found in
      the latest scan? What was the gate decision?") produced a real, live-streamed reply
      correctly grounded in the actual report ("No vulnerabilities were found... gate decision is
      clear"), and a full fresh page reload confirmed both the question and the reply persisted
      (`store.security_conversations` working as intended). Zero console/page errors.
    - **An honest, unresolved observation from this same live pass, not a defect in this item's
      own new code**: the auto-triggered scan fired by the new button's popup confirmation (via
      the UNCHANGED `handleConfirmedApprove`/`runSecurity.mutate({})` chain, already proven
      working in item 82) took longer than several minutes of live polling to produce its second
      report version -- root-caused, not left unexplained: `GET /settings/llm/agents` confirmed
      Security Agent has no per-agent override entry at all (a known, pre-existing gap noted in
      item 82: `OVERRIDABLE_AGENTS` still doesn't include security_agent/qa_agent), so it falls
      back to the global default model, `qwen2.5-coder:14b` via Ollama -- the same class of
      GPU/VRAM-constrained slow-local-inference characteristic this project has documented
      repeatedly elsewhere (items 24/51/63/74), not a new regression. A real, direct
      `POST /security/run` call (used to produce the report the chat verification above ran
      against) did complete successfully well inside its request budget, confirming the backend
      route itself is fast and correct -- the observed delay is specific to whichever model
      happens to be configured for a given run, not this item's own code.

86. **A real, reported "Network Error" on every single artifact in a feature -- root-caused to
    an unhandled crash on a missing file, not a real network problem, and fixed for every project
    going forward.** Direct user report with screenshots: opening the real "Item Listing (CRUD)"
    feature in "Sample E-commerce" showed a generic "Network Error" for every stage's output
    (Requirement, Domain, Architecture, UI/UX, Coder), plus "No diff content found in this
    artifact" for Coder specifically.
    - **Root-caused directly, not guessed**: `curl`ing the real, live `GET /artifacts/{id}/content`
      endpoint for this feature's SRS artifact returned a bare `500 Internal Server Error` with no
      body -- confirmed via the artifact's own metadata that `size_bytes: null` (a real signal,
      per `_hydrate_artifact_response`'s own established "None if the file is missing rather than
      raising" convention), and confirmed directly via `Glob` that the file's real disk path
      (`outputs/sample-e-commerce/...`) doesn't exist AT ALL -- the entire `outputs/sample-e-commerce/`
      AND `workspaces/sample-e-commerce/` directories are missing from this branch's checkout,
      even though the shared MongoDB Atlas database (used across the whole team) still has full
      version/approval history for this project. `artifact_service.read_artifact_content`/
      `read_artifact_binary` do a raw `open(file_path, ...)`, raising an uncaught
      `FileNotFoundError` that propagates as an unhandled 500 -- which the BROWSER reports as a
      bare "Network Error" with no message at all, because an unhandled exception skips FastAPI's
      normal exception-handling pipeline, which is also what re-applies `CORSMiddleware`'s
      headers to the response -- without them the browser can't even read the 500's body, so
      axios reports a connection failure, not "500". This directly explains the exact reported
      symptom, confirmed by testing: after the fix, the SAME broken artifact returns a real,
      readable 404 instead.
    - **Fix, `app/api/routes/artifacts.py`**: both `GET /artifacts/{id}/content` and
      `GET /artifacts/{id}/download` (a "sibling" route sharing the exact same read functions, per
      item 31's own documented design) now wrap their file-read calls in a
      `try/except (FileNotFoundError, OSError)`, translating to a real, graceful
      `HTTPException(404, detail="This artifact's file could not be found on disk (path: ...). It
      may have been deleted, moved, or never synced to this environment.")` -- a genuine,
      honest error instead of a crash, for ANY project this happens to, not just this one.
      Confirmed no frontend changes were needed at all: `ErrorBanner.jsx` already reads
      `error?.response?.data?.detail` first, so every existing content viewer
      (`ArtifactContentView.jsx` and everything built on it) automatically renders the new, clear
      message the moment the backend starts returning proper JSON error bodies -- the bug was
      entirely a backend graceful-degradation gap, not a frontend display gap.
    - **The second, related complaint ("when the user moves from one feature to another the
      output must stay as it is")**: investigated and concluded this describes the SAME symptom
      in different words, not a separate routing/state bug -- React Query's `artifactContent`
      queries are already correctly keyed per `artifact_id`, so switching features was never
      showing stale content from a different feature; it was showing this SPECIFIC feature's own
      real (missing-file) error, now fixed to read clearly instead of crashing.
    - **A genuinely separate, bigger question surfaced by root-causing this, deliberately left to
      the user's own explicit decision rather than acted on unilaterally**: git history confirms
      these exact 63 files DO exist -- on a teammate's branch, `origin/tharuka_m` -- but were
      never merged into this branch (`new-anthropic_m`); the shared Mongo database has records
      for this project because the teammate ran the real pipeline on their own branch/checkout.
      Asked the user directly whether to pull those files in from `origin/tharuka_m` to restore
      this specific feature's real content -- **user chose to leave it as-is** (the error-handling
      fix alone, without merging another branch's files into this one). This item's own fix
      still applies universally regardless of that choice -- any other real or future case of a
      shared-database record pointing at a locally-missing file now degrades gracefully instead
      of crashing with a confusing "Network Error."
    - Tests: `tests/test_artifact_content_routes.py` (new, 5 -- `/content` returns a real 404
      with the exact clear message for a missing JSON file, still works normally when the file is
      genuinely present, returns 404 for a missing PNG too; `/download` mirrors both the missing-
      file-404 and present-file-200 cases). Full suite: **922 passed** (up from 917). `npm run
      build` clean (1344 modules, unaffected -- a pure backend fix).
    - **Real, live verification against the exact reported feature**: `curl`ing the real, live
      broken SRS artifact directly confirmed the fix (500 -> a real 404 with the clear message).
      Drove the real browser to the same feature afterward: confirmed the old bare "Network
      Error" text is gone everywhere, replaced by the real, honest "This artifact's file could
      not be found on disk..." message (screenshot confirmed on the Coder stage specifically, the
      exact same message the user's own screenshot showed as unhelpful red boxes). Zero page
      errors.

87. **Security ↔ Coder Agent remediation loop: coder-friendly fix plan, a themed live progress
    view, and a real QA gate on Critical findings.** Direct user request to "implement the
    pipeline between security agent and the coder agent." Investigation (direct reading + one
    Plan-agent validation pass) confirmed most of this pipeline already existed and worked, built
    in earlier sessions (items 73, 82 Ask 4, 83 Ask 4, 85): the "Fix Vulnerabilities"/"Send to
    Coder Agent to Fix" triggers, `buildSecurityRevisionComment`, and the auto-rescan-after-fix
    loop were all live. What was genuinely missing, confirmed against the real code:
    - **No visible progress during a security-driven fix**: neither `ResultTab.jsx`'s
      `handleConfirmedFixVulnerabilities` nor `SecurityDecisionDialog.jsx`'s `handleSendToCoder`
      called `selectAgent("coder")` before `await`ing the full revision stream -- the UI just sat
      on a disabled button/"Sending..." with zero live feedback for however long the revision
      took. Fixed: both now call `selectAgent("coder")` **before** the `await` (and
      `SecurityDecisionDialog` closes itself immediately too, before the await, so it stops
      covering the live view) -- the component stays mounted after `onClose()`/`selectAgent()`,
      confirmed safe to continue the async function afterward, mirroring this project's existing
      fire-without-blocking convention for other auto-run transitions.
    - **A themed, rotating "fixing security issues" spinner** (direct user ask, "some random
      words instead of Thinking"): new `useRotatingLabel(phrases, intervalMs)` hook
      (`RequirementConversationParts.jsx`, mirrors `useElapsedLabel`'s interval+cleanup shape) --
      cycles through `SECURITY_FIX_PHRASES` ("Patching vulnerabilities...", "Hardening the
      code...", "Re-checking security controls...", "Applying the suggested fix...") every 2.5s.
      A new `isSecurityFixInFlight` flag (set only by the two real trigger surfaces, so an
      unrelated Coder-chat revision is never mislabeled) overrides **both**
      `generatingLabel`/`connectingLabel` AND `finalizingLabel` in `ResultTab.jsx`'s Coder
      `LiveGenerationView` block, and forces `isFinalizing=true` immediately -- confirmed live
      that overriding only `generatingLabel` would have been invisible in practice, since
      `revise_stream` flips into `isFinalizing` mode (via a `"phase"` event) almost immediately
      and `finalizingLabel={coderPhase?.label}` is what actually dominates screen time.
    - **Coder-friendly fix plan**: `buildSecurityRevisionComment`
      (`securityReportToRevisionComment.js`) now includes each finding's `root_cause`/
      `recommendation` sub-lines (the backend's `SecurityFinding` schema already populates both
      on every scan layer; none of it previously reached the Coder Agent) directly under the
      existing `[TIER] file:line -- message (CWE)` line -- the `file:line` token's position is
      unchanged so `_find_well_specified_target_files`'s existing regex targeting still works.
      New rule in `CODER_AGENT_SYSTEM_PROMPT` (`coder_agent/prompt.py`, placed before the `Tool
      usage:` split point so both the agentic and `BATCH_CODE_GENERATOR_SYSTEM_PROMPT` paths
      inherit it for free, confirmed via a dedicated test): **format-triggered**, not gated on
      `revised_by` (confirmed `revised_by` is read nowhere inside `coder_agent/agent.py` today,
      only at the route layer for bookkeeping) -- recognizes `[CRITICAL]`/`[MODERATE]`/
      `[WARNING] file:line -- message ... Root cause: ... Suggested fix: ...`-shaped content and
      instructs the model to apply each fix precisely per the suggested fix's intent, never
      weaken/remove an *existing* security control elsewhere just to make a finding disappear,
      and not restructure unrelated code -- the "make adjustments... do not change the main
      objectives" the user asked for, with near-zero false-positive risk on an unrelated revision.
    - **QA gate on Critical findings** (direct, explicit ask -- a deliberate reversal of
      `severity.py::gate_decision`'s own documented "informational only, never blocking" design
      from item 73, noted here plainly): `ResultTab.jsx`'s "Continue to QA Agent" button and
      `AgentSelect.jsx`'s picker option for `"qa"` are both now disabled whenever the feature's
      **latest** `security_report` version (by version number -- `versions[0]`, never
      "operative"/approved-wins/whatever the dropdown has selected) has `gate_decision ===
      "fail"`. Deliberately keyed on the latest version specifically: `security_report` isn't in
      `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES`, so an old *approved*, clean report could otherwise
      sit alongside a newer *pending* Critical-bearing one and `resolveGatingArtifact`'s
      "approved always wins" precedence would mask it -- a real gap a Plan-agent review caught
      before implementation. New `WorkspaceSelectionContext.jsx` computation
      (`securityGateBlocksQa`, one extra `useArtifactContent` call scoped to the latest
      security_report id, React-Query-deduped against whatever `ResultTab` already fetches) feeds
      `AgentSelect.jsx`'s picker; `ResultTab.jsx` computes the same rule independently for its own
      button (both stay purely additive to the existing, unchanged `deriveStageStatus`/
      `deriveCurrentStage`, which stay approval-status-only, shared with `FeatureListItem.jsx`).
      `security_report` deliberately NOT added to `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES` -- it
      wouldn't by itself fix the staleness gap (only a new *approval event* triggers exclusivity,
      not a version's mere existence), so "latest by version number" is required regardless and
      sufficient on its own; not touching `approval_service.py` kept this change's blast radius
      minimal.
    - Loop-until-clean needed no new code -- confirmed already satisfied by the existing "each
      re-scan produces a new pending report version, which needs a decision again, which reopens
      the same UI" mechanic (`SecurityDecisionDialog.jsx`'s own docstring).
    - Tests: `tests/test_coder_prompt.py` (+1, asserting the new rule text is present in **both**
      `CODER_AGENT_SYSTEM_PROMPT` and `BATCH_CODE_GENERATOR_SYSTEM_PROMPT` -- caught and fixed a
      real line-wrap bug during this pass: the rule's key phrase was originally split across two
      source lines, which JSX's own non-JS-escaped string handling faithfully reproduced as a
      literal newline in the prompt text, breaking the substring assertion; reflowed to keep the
      phrase on one line). Full suite: **990 passed** (up from 922). `npm run build` clean.
    - **Real, live verification, not synthetic** -- against the real Finodil "Login and Signup"
      feature (`proj_2ba24bc0`/`feature_917b691e`), via an isolated backend (:8090, same shared
      Mongo Atlas cluster) + an isolated frontend served via `vite preview` against a build pinned
      to that backend (`vite dev`'s dependency-scan step hit a real, pre-existing, unrelated
      rolldown parser issue on `EnrichedPlainList.jsx`'s `content-['\2022']` CSS escape -- the
      exact correct syntax item 78 already fixed -- treating it as a deprecated JS octal literal;
      `npm run build` itself was unaffected, so `vite preview` on the built output sidestepped it
      cleanly rather than "fixing" a working, already-correct line). Confirmed live: a real scan
      showing 2 Critical/5 Moderate findings with real `root_cause`/`recommendation` text per
      finding (screenshot); "Continue to QA Agent" genuinely `disabled=True` with the correct
      tooltip, and the picker's "QA" option genuinely `disabled` too (`is_disabled()`, not just a
      screenshot); clicking "Fix Vulnerabilities" → confirming the popup switched the chat to
      "Coder" and showed the live view with "Patching vulnerabilities..." visibly rendered
      **at t=1.5s** alongside the dialog's own "Sending..." state and a real Stop-generating
      button (screenshot) -- direct proof A3 works. The real `POST .../coder/revise/stream`
      payload was captured via Playwright's own request listener and confirmed to contain the
      full enriched comment (every finding's Root cause/Suggested fix lines present, matching A1
      exactly). **The real revision itself could not complete** -- confirmed via a direct,
      unmocked replay of the same call (`requests`, no timeout) that it cleanly returned
      `{"type": "error", "message": "No existing feature branch found for feature_id=... -- run
      the Coder Agent before requesting a revision."}` -- this machine's local `workspaces/`
      directory is entirely empty (`Glob("workspaces/*")` -- zero results), the exact same
      environmental gap item 86 already documented and the user explicitly chose not to fix (the
      real files exist only on `origin/tharuka_m`, never merged into this branch). Not a defect in
      this item's own work: the error surfaced as a clean NDJSON `error` event (not a crash), and
      `streamNdjsonPost`'s own documented "resolves normally even on a mid-stream error event"
      behavior meant `handleConfirmedFixVulnerabilities`'s `await` still resolved normally,
      `finally` still reset both flags correctly, and the auto re-scan still fired (producing a
      real v7 security report, left in place as genuine evidence) -- the whole UI flow degraded
      gracefully end-to-end even though the underlying revision had nothing to revise. **Given
      no local git workspace exists for ANY feature on this machine right now** (confirmed, not
      just for Finodil), a full "inspect a real diff referencing the specific findings" pass
      genuinely could not be run this session -- honestly left as the one plan-verification step
      not completed, rather than silently skipped or faked.
      **CORRECTION (see item 88): this diagnosis was wrong.** The workspace was never actually
      missing -- `resume_feature_branch` itself had a real bug (raised unconditionally whenever a
      feature's branch didn't exist, which is completely normal after a successful merge deletes
      it) that this item's own investigation misread as "no local git state at all." Fixed in
      item 88, along with the real Coder Agent revision this correction unblocked.

88. **A real, live-reported "No existing feature branch" bug in `resume_feature_branch` (a
    genuine reversal of item 87's own wrong diagnosis), plus a dialog-close bug fix, a
    Resolved/Still-Present/New security-finding comparison, and a deterministic named-file
    coverage backstop.** Direct follow-up to item 87's fix-vulnerabilities loop, from the user
    hitting the exact "No existing feature branch found" error live on their own app right after
    that item shipped, plus two further reports (a confirmation dialog that never closes; the
    Coder Agent's fix apparently not resolving vulnerabilities).
    - **Real root cause of the branch error, found only by directly reconstructing the workspace
      and reading the actual git history -- item 87's own "the local workspace is entirely
      missing" diagnosis was WRONG.** Attempted to reconstruct the feature's code from a stored
      diff artifact (matching the user's explicit "fix the EXISTING code, don't regenerate"
      instruction) via `workspace_service.start_feature_branch` -- which unexpectedly reported
      "already exists in working directory" for every file the reconstruction script tried to
      create. Direct `git log --oneline --all` on the real repo revealed why: a full, real commit
      history was already there the whole time -- `Merge feature/login-and-signup into main`,
      `Revert`/`Reapply` cycles (item 83's own revoke-approval work), and even a
      `Deliberate, authorized test vulnerabilities for Security Agent verification` commit
      (matching the exact CWE-798/943/916/532/79 findings seen in the real security reports).
      **The actual bug**: `resume_feature_branch` (`workspace_service.py`) raised `ValueError`
      unconditionally whenever a feature's OWN branch didn't exist -- but a branch not existing is
      completely normal and expected once a feature has been approved and merged
      (`merge_feature_branch` deletes it by design, as its own docstring already states). Since
      `revise()` only ever reaches `resume_feature_branch` after already confirming a real prior
      `CODE_PLAN` artifact exists, there is no case where a feature can reach this method having
      genuinely never been coded -- the old behavior treated the single most common post-approval
      state (merged, branch gone) identically to "never coded at all," permanently blocking every
      future revision (including a security-driven fix) on any feature that had ever been
      successfully merged.
    - **Fix**: `resume_feature_branch` now falls back to branching fresh from `main`'s current tip
      when the feature's own branch is missing, instead of raising -- a real `--no-ff` merge keeps
      the feature branch's own tip reachable as an ancestor, so `main`'s tree already has the exact
      same content resuming the original branch would have; this is genuinely resuming the
      *existing* project, never a fresh regeneration. New tests in `test_workspace_scaffold.py`:
      `test_resume_feature_branch_falls_back_to_a_fresh_branch_from_main_when_none_exists` (the
      never-branched case) and `test_resume_feature_branch_recovers_the_real_merged_code_after_the
      _branch_was_deleted` (the real scenario -- start a branch, commit real work, merge it
      [deleting the branch], then confirm a revision correctly recovers the real merged content,
      not an empty scaffold). The old raise-focused test was replaced, not kept alongside the new
      behavior it directly contradicts.
    - **Dialog-close bug, a real gap in item 87's own fix**: item 87 fixed this exact
      close-before-`await` ordering bug in `SecurityDecisionDialog.jsx`'s `handleSendToCoder`, but
      missed the *other*, separate trigger for the same action --
      `ResultTab.jsx`'s own `handleConfirmedFixVulnerabilities`, whose `ConfirmDialog` stayed open
      showing "Sending..." for the entire multi-minute revision because
      `setFixVulnerabilitiesArtifactId(null)` only fired after the `await` resolved. Fixed by
      moving it to fire immediately alongside `selectAgent("coder")`, before the `await` -- the
      identical ordering item 87 already established as correct. Confirmed safe: the trigger
      button's own `disabled` state depends on `coderReviseStream.isPending`, not the dialog's own
      open state, so closing early creates no double-submit risk.
    - **The "still shows vulnerabilities after fixing" report -- investigated with real, live
      data, not assumed.** Pulled two consecutive real `security_report` versions (v11 -> v12,
      both `scan_type: ai_model_deep_scan`) directly from the running backend: identical 3
      findings (same `rule_id`, `cwe`, `file`, near-identical `message`), just shifted line
      numbers (16->14, 31->27, 52->42) -- genuinely unresolved, not reintroduced. Separately
      pulled the real Coder Agent revision that actually ran (`code_plan` + the real
      `revision_comment` from `stage_events`): it named exactly 2 files, and its diff correctly,
      completely fixed exactly those 2 files' findings (removed a hardcoded MongoDB fallback URI
      and a `dangerouslySetInnerHTML` XSS). **The Coder Agent fixed everything it was actually
      asked to fix -- the 3 findings still showing were never part of that fix request.** They're
      real, pre-existing issues the AI-model-deep-scan layer (LLM-based, not the deterministic
      pattern/secret scanners) hadn't happened to flag in an earlier scan and then caught in a
      later one, on unchanged code -- a scan-consistency issue, not a fixing failure. (Independent
      supporting evidence found along the way: a later scan produced a spurious "SQL Injection"
      finding on a MongoDB connection file at the same location as an unrelated, real CWE-798
      finding -- MongoDB isn't SQL, confirming real noise in the AI-scan layer.) This reframed
      "improve the Coder Agent's accuracy" away from a speculative, evidence-free prompt tweak and
      toward genuine transparency plus one real deterministic backstop -- both below.
    - **New Resolved / Still Present / New / Ambiguous comparison** (direct user decision: shown
      only for `scan_type === "ai_model_deep_scan"` reports specifically -- the layer with real
      run-to-run variance, not the fully-reproducible deterministic scanners). New
      `frontend/src/lib/securityFindingsComparison.js`'s `classifySecurityFindings(previous,
      current)`: match key is `(rule_id, file, cwe)`, deliberately never line number (confirmed
      real: fixing one issue shifts every later line in the same file). Within a matched bucket,
      disambiguates by word-overlap on `message` when messages differ (real signal for AI-found
      findings, whose message is genuinely per-finding) -- but falls back to **positional pairing
      by ascending line number** when every message in the bucket is byte-identical, a real,
      confirmed collision case for the deterministic scanners specifically (e.g. every
      `SEC-SECRET-GENERIC-KEY` finding shares one literal rule-message constant, giving text
      similarity zero discriminative power). A bucket that still can't be confidently paired (a
      genuine tie) goes into a new, explicit `ambiguous` group (direct user decision) rather than
      being silently folded into "New" or "Still Present." `finding.id` is used only to mark
      "already consumed" within one classification call -- documented explicitly as NOT a stable
      cross-version identity (it bakes in the line number or a scan-local sequential index, so it
      legitimately differs across versions for the identical underlying issue).
      `SecurityReportView.jsx` gained a `previousArtifact` prop + its own second
      `useArtifactContent` call (confirmed safe: distinct `artifact_id` per version means no cache
      collision, fires in parallel not chained, and cleanly no-ops via the existing disabled-query
      convention when there's no previous version yet) and a new "Compared to vN" section (green
      Resolved / red Still Present / orange New / gray Ambiguous). `ResultTab.jsx` computes
      `previousSecurityArtifact = versions.find(v => v.version === selected.version - 1) ?? null`
      (`versions` already sorted descending) and threads it through.
    - **New deterministic named-file coverage backstop for `verify()`** -- mirrors the existing
      `_build_relevance_scan_step`/`_build_ui_expectations_coverage_step` info-only pattern
      exactly (`verify()` already receives `original_request`, the human's revision_comment, no
      new parameter needed). New leaf module `revision_file_tokens.py` relocates
      `_REVISION_FILE_TOKEN_RE` out of `agent.py` (re-exported under its old name for backward
      compatibility) so `security_finding_coverage_checker.py` (imported by `verify.py`) can reuse
      the exact same extraction/resolution logic without a circular import (`agent.py` already
      imports from `verify.py`). New `resolve_tokens_against_known_paths` factors out
      `_find_well_specified_target_files`'s own exact-match-then-unique-basename-fallback logic so
      both callers share it -- necessary, not cosmetic: the token regex has no backslash in its
      character class, so a real revision comment's Windows-style token (`lib\mongodb.ts`) only
      ever yields the bare basename `mongodb.ts`, while `touched_paths` are always forward-slash
      paths (`lib/mongodb.ts`) -- confirmed via a real revision comment that mixed both separators
      in the same message. New `security_finding_coverage_checker.check_security_finding_file_
      coverage(revision_comment, touched_paths)`: format-triggered (checks for
      `[CRITICAL]`/`[MODERATE]`/`[WARNING]` markers, mirroring `coder_agent/prompt.py`'s own
      security-rule addition from item 87) rather than gated on `revised_by` -- returns `None`
      (no step at all) for a non-security revision. Wired into `verify.py` as a new info-only step,
      never gating `passed`. Tests: `test_revision_file_tokens.py` (10, covering both real
      separator styles + the ambiguous/unresolved cases), `test_security_finding_coverage_checker.py`
      (6, using the ACTUAL real revision_comment string captured from the live feature's own event
      log -- 7 findings across 4 real files mixing both separators -- confirming both the real
      partial-coverage case (the real v5 attempt only touched 2 of 4 named files) and a
      fully-covering case report correctly).
    - Full backend suite: **1007 passed** (up from 990), zero regressions, including the existing
      `test_coder_agent_well_specified_files.py` suite re-run unchanged after the
      `_find_well_specified_target_files` refactor to confirm byte-identical behavior. `npm run
      build` clean throughout.
    - **Real, live verification against the real Finodil feature, not synthetic** -- via an
      isolated frontend build pointed at the live main backend (`vite build` +
      `vite preview`, read-only for inspection, the same "isolated instance, same shared Mongo"
      precedent used throughout this file): confirmed live that clicking "Fix Vulnerabilities"
      now correctly closes the confirmation dialog within under a second (was visible right after
      clicking, confirmed gone ~0.8s after confirming) while the Coder Agent's live view with the
      "Patching vulnerabilities..." rotating label takes over -- screenshot-confirmed. Confirmed
      the real branch-resume fix directly: replaying the exact real `coder/revise/stream` request
      that previously failed with "No existing feature branch found" now gets past workspace
      preparation into real planning with no error at all (`phase: planning, label: "Exploring
      the codebase and planning your revision..."` -- an exploration-path label rather than the
      fast-path one, since the specific finding tested named a scaffold file the feature's own
      code plan never touched, not a bug). Confirmed the comparison UI against the real,
      already-diagnosed v11/v12 pair: selecting v12 correctly renders "COMPARED TO V11" with all 3
      real findings grouped under "STILL PRESENT (3)", not "New" -- screenshot-confirmed, exactly
      matching the real line-shift case this feature was built to handle. A test revision
      triggered purely to verify the dialog-close timing was deliberately left uncompleted
      (browser closed immediately after confirming the dialog closed, cancelling the in-flight
      stream per this project's own well-documented client-disconnect-cancels-the-stream
      behavior) -- confirmed via the artifacts endpoint that no stray Coder Agent version was
      created by it. This real Finodil state (branch now exists on `main`'s tip, ready for a real
      revision; real v11/v12/etc. security report history) is left in place as genuine
      verification evidence, matching this project's own established convention.

89. **Security Agent enhancement: real per-agent model selection, concurrent AI deep scan with
    real-time per-file progress, and a downloadable Security Report PDF.** Three direct user
    requests, planned together via 3 parallel Explore agents (deep-scan/model-selection backend,
    the PDF-generation pattern, the existing scan-progress streaming mechanism) plus a Plan-agent
    validation pass that caught two real mistakes before any code was written -- a frontend
    routing dead-end (Part C) and a concurrency/state-shape bug (Part B), both described below.
    - **Part A -- model selection was a genuinely one-line-away fix.** The `ModelSelect`
      chat-composer control the user asked for already rendered live in Security Agent's chat (the
      same shared component every agent uses) -- but picking a model was a silent dead end because
      `security_agent` (and `qa_agent`, same gap, fixed in the same pass per direct user decision)
      was excluded from `llm_provider_service.py`'s `OVERRIDABLE_AGENTS` list. Every real call site
      (`deep_scan._get_provider()`, the LLM review layer, chat) already resolved its model through
      the exact mechanism this unlocked, with no caching to invalidate. Also fixed a real, latent
      bug affecting every agent, not just Security: a rejected model override was silently
      swallowed. `ModelSelect.jsx` now renders `updateOverride.error` in a small absolute-positioned
      tooltip instead of no-op'ing.
    - **Part B -- the AI deep scan already scanned every file (no cap/sampling); the real gap was
      sequential execution (10-30+ round-trips for a real project) and zero per-file visibility.**
      `deep_scan.py` rewritten: `_batch_files` now sorts files by relative path before greedy-
      packing into batches (files from the same directory now reliably cluster together, giving the
      model more real cross-file context for the same char budget). New
      `DEEP_SCAN_MAX_CONCURRENT_BATCHES = 3` (direct user decision) and a new shared
      `_run_batches_concurrently(provider, batches)` async generator -- `asyncio.Semaphore(3)`-
      bounded, tasks created via `asyncio.create_task`, results pulled off a shared `asyncio.Queue`
      as each batch actually finishes. Confirmed via grep this is genuinely new territory for this
      codebase (zero prior `asyncio.Semaphore`/`gather`/`as_completed` usage anywhere) -- called out
      plainly rather than presented as matching an established pattern. Both the non-streaming
      `run_ai_model_deep_scan` and the streaming `run_ai_model_deep_scan_stream` now call this ONE
      shared implementation instead of duplicating the loop. **Explicit `try/finally` cancellation**
      ensures stopping the scan (the existing "Stop Scan" button, which relies on Starlette
      cancelling the generator on client disconnect) actually cancels every still-in-flight task --
      a real gap the old sequential version never had to handle, since only one call was ever in
      flight at a time; verified with a real test (`test_stopping_the_stream_early_cancels_still_
      in_flight_batches`) using a slow fake provider (`asyncio.sleep(5)`) and a wall-clock assertion
      that `gen.aclose()` returns in under 4s. **New event shape** replacing the old single
      overloaded `progress` event (a Plan-agent-caught bug: its `current` field conflated
      "completion count" with "which batch," which only worked because completion order ==
      submission order in the old sequential loop -- an equivalence real concurrency breaks):
      `{"type": "batch_started", "batch_index", "total", "files": [...]}` and
      `{"type": "batch_finished", "batch_index", "total", "completed_count", "label"}`.
      `security_agent/agent.py`'s pass-through loop needed no code change (confirmed it never
      inspects event shape), only a docstring update. Frontend
      (`useSecurityDeepScanFlow.js`): new `inFlightBatches` state, an **object keyed by
      `batch_index`** (a Plan-agent-caught state-shape correction -- not a rolling capped array like
      Coder Agent's `tool_activity`, since entries need to be *removed* on completion, which an
      append-and-truncate log can't do); `batch_started` inserts `{[batch_index]: files}`,
      `batch_finished` deletes that key. `ScanProgressBar.jsx` renders the union of all in-flight
      batches' files (`Object.values(inFlightBatches).flat()`) as an "Analyzing: ..." line capped at
      `MAX_VISIBLE_IN_FLIGHT_FILES = 10` with a "+K more" overflow indicator.
    - **Part C -- Security Report PDF, a mechanical reuse of the proven 3-agent PDF pattern.** New
      `security_agent/pdf_builder.py`: imports the 6 generic helpers already proven reusable by
      `architecture_agent/pdf_builder.py` (`_esc`, `_meta_table`, `_section`, `_text_block`, from
      `requirement_agent/pdf_builder.py`) plus `html_document_shell`/`signature_block_html` from
      `_shared/pdf_style.py`. Findings grouped by severity tier via `severity.py`'s own
      `to_display_tier`/`DISPLAY_TIERS` directly, not a hand-rolled parallel mapping (a Plan-agent-
      caught risk: the saved report only carries each finding's raw producer-vocabulary `severity`
      string, never a precomputed tier). Each finding renders file:line, severity badge, message,
      rule/CWE, root cause, and recommendation with defensive fallbacks for real, confirmed-nullable
      fields (`root_cause`/`recommendation` are `None` for pre-existing findings -> "Not specified.";
      `line` is confirmed always `None` for every dependency-scan finding -> "(N/A)"). A dependency-
      scan section renders `dependency_scan.dependency_summary` as a meta-table (it's a dict of
      counts from `npm audit`'s own output, not a list of records). `artifacts.py` registers
      `ArtifactType.SECURITY_REPORT: build_security_report_html` in `_PDF_BUILDERS` (plain one-arg
      builder call -- Security Report has no sibling artifact, unlike Enhanced SRS). **Frontend fix,
      corrected from the first draft**: `ResultTab.jsx`'s `PDF_DOCUMENT_LABEL_BY_STAGE` map looked
      like the right place to wire this in, but the Plan-agent confirmed by direct code reading that
      the Security stage has its own separate, earlier render branch that never consults that map at
      all -- adding an entry there would have been a no-op. The real fix was entirely local: that
      block's own hardcoded `<a href={artifactDownloadUrl(...)}>Download report</a>` became
      `artifactDownloadPdfUrl(...)`, relabeled "Download Security Report."
    - **Real bug found and fixed during live PDF verification**: `_finding_card` originally used the
      `&mdash;` HTML entity between "Rule: ..." and "CWE: ...", which `pypdf`'s text extraction
      mangled into `�`. Fixed by replacing with the plain ASCII `"--"` already used everywhere else
      in this codebase's PDF builders and prose.
    - Rewrote `test_security_deep_scan.py` (17 tests) with a `_keyed_provider(responses: dict)`
      helper that keys fake LLM responses off actual batch CONTENT rather than call order -- the old
      tests asserted exact `progress` event ordering (`[(1,3),(2,3),(3,3)]`) and consumed
      `AsyncMock.side_effect` in call order, both fundamentally incompatible with real concurrent
      execution where completion order is non-deterministic. New:
      `test_files_are_sorted_by_relative_path_before_batching`,
      `test_more_batches_than_the_concurrency_limit_all_still_get_scanned`,
      `test_stopping_the_stream_early_cancels_still_in_flight_batches`. New
      `test_security_pdf_builder.py` (10 tests, real severity-tier grouping, defensive-rendering,
      HTML-escaping, complete-document assertions). New `test_artifact_download_pdf_route.py` case
      (`test_download_pdf_returns_a_real_pdf_for_security_report`, a real Playwright-rendered PDF,
      no mocking). Full backend suite: **1021 passed**, zero regressions. `npm run build` clean.
    - **Real, live verification**, via an isolated backend (`:8090`) + isolated `vite preview`
      frontend (`:5199`) against the same shared MongoDB Atlas cluster, on the real Finodil "Login
      and Signup" feature: (1) picked a model via the chat composer's `ModelSelect`, confirmed the
      real `PUT /settings/llm/agents/security_agent` round-trip persisted it; (2) triggered "Scan
      with AI Model" and captured the real NDJSON stream directly -- all 3 `batch_started` events
      fired at the identical timestamp (5.07s, proving real parallel dispatch, not accidental
      serialization), and `batch_finished` events completed in a demonstrably non-submission order
      (1, then 3, then 2), direct empirical proof of genuine concurrent execution rather than just
      correct-looking code; (3) downloaded a real Security Report PDF (67785 bytes, 3 pages),
      extracted its text via `pypdf` (Playwright's headless Chromium wouldn't render a
      `Content-Disposition: attachment` response inline for visual screenshot verification), and
      confirmed every expected section and field present.

90. **Security Agent: mark vulnerabilities as Skipped, real "Proceed Anyway," and Fixed/Open/
    Skipped status.** Direct user request: the "Continue to QA Agent" button was permanently
    disabled while the latest scan had any Critical finding, with no way to proceed except getting
    the Coder Agent to fix every one. Planned via 2 parallel Explore agents plus a Plan-agent
    validation pass that caught 4 real issues before implementation: a concurrent-write race, a
    dead-data `stage_event` call, missing prop-plumbing, and a gate banner that would contradict
    per-row skip status. Two direct user decisions: rename "Resolved" to "Fixed," and fix a real,
    previously-dormant bug (below).
    - **The QA gate was already 100% frontend-only** (`gate_decision` computed in `severity.py`
      but, by that module's own docstring, "never consulted to block pipeline advancement" on the
      backend) -- duplicated independently in `ResultTab.jsx` and
      `WorkspaceSelectionContext.jsx`. This entire feature is therefore frontend/light-backend;
      no QA Agent or graph-orchestrator change was needed.
    - **`finding.id` is stable within one artifact version but not across re-scans** (item 88's own
      documented evidence) -- skip decisions are scoped to one artifact version and never carried
      forward to a new scan automatically, sidestepping that instability entirely: a fresh scan
      always starts with an empty skip set, forcing re-review.
    - **Backend**: `ArtifactResponse` gains `skipped_finding_ids: list[str] = []` (additive/default-
      safe -- the only construction site builds it via `ArtifactResponse(**artifact, ...)`, so old
      records simply get `[]`). New `ArtifactService.set_finding_skipped(artifact_id, finding_id,
      skipped)` uses an **atomic** `$addToSet`/`$pull` (`store.artifacts.collection.update_one`),
      not a read-modify-write on the whole record like `approval_status` uses -- a real race the
      Plan-agent flagged, since this field gets toggled rapidly across many findings on one report,
      unlike a single approval click. New route `PUT /artifacts/{artifact_id}/skipped-findings` in
      `app/api/routes/artifacts.py`. Deliberately does NOT touch `content_json` on disk (see next
      point) and deliberately does NOT emit a `stage_event` (the Plan-agent found
      `SecurityAgentChat.jsx` is the one stage `ChatPanel.jsx` never passes a `timeline` prop to,
      so a stage-event call here would be silent dead data, invisible in the UI).
    - **Why skip state lives on the artifact record, never in `content_json`**: confirmed
      `useArtifactContent`'s `staleTime: Infinity` (`frontend/src/hooks/useArtifacts.js`) treats
      content as immutable once fetched -- mutating the JSON file in place would leave any
      already-open tab showing stale data forever. `skipped_finding_ids` instead rides on
      `ArtifactResponse`/the feature's artifact list (both always-fresh queries), cross-referenced
      client-side against the separately-cached `content_json.findings`.
    - **New shared `frontend/src/lib/securityGate.js`**'s `computeSecurityGateBlocksQa(findings,
      skippedFindingIds)` replaces the two independently-duplicated `gate_decision === "fail"`
      checks in `ResultTab.jsx` and `WorkspaceSelectionContext.jsx` -- true only if some Critical
      finding's id is NOT in the skip set. Both components already held the full `ArtifactResponse`
      list object needed for `skipped_finding_ids`, so this required zero new fetches, just
      pulling `findings` and `skipped_finding_ids` from two already-fetched objects instead of one.
    - **`SecurityReportView.jsx`'s `FindingRow`** gained a native 2-option radio group ("Open" /
      "Skip") per finding, `accent-*`-styled matching `pipeline/ArtifactRow.jsx`'s own existing
      radio (the only native-radio precedent in this codebase, and the closest match to the user's
      own literal "radio button" wording) -- doubling as both the control and the visible
      Open/Skipped status. A skipped row dims (opacity-50) with a small "Skipped" badge. The gate
      banner is now skip-aware: a 4th `"skipped"` state (distinct from pass/review/fail) renders
      once every Critical finding is skipped ("All Critical vulnerabilities have been skipped --
      safe to continue to QA Agent," blue, not green -- an honest accepted-risk state, not a false
      "clean scan"), and the summary line appends `-- N skipped`. A small Open/Skipped color legend
      sits above the findings list, pointing to the "Compared to vN" section below for Fixed
      findings.
    - **`buildSecurityRevisionComment(report, skippedFindingIds)`** now filters skipped findings
      out before building the Coder Agent's fix request -- confirmed live: a real "Fix
      Vulnerabilities" click's captured `revision_comment` correctly omitted the skipped Critical
      finding's `[CRITICAL]` line entirely while every other finding still rendered normally.
      Confirmed safe against item 88's coverage-checker (text-driven off the exact string handed to
      it -- an omitted finding's `file:line` simply never appears, so it can never be flagged
      "missing").
    - **Real, previously-dormant bug fixed (direct user decision)**: `SecurityDecisionDialog.jsx`'s
      "Proceed Anyway" button (shown after approving a report) previously did nothing but close the
      dialog -- it never actually unblocked `securityGateBlocksQa`, which was computed completely
      independently. Now it bulk-marks every currently-open finding in that report as Skipped
      (parallel `mutateAsync` calls -- safe since the backend's `$addToSet` is atomic and
      idempotent per id) before closing, making its own long-implied promise ("proceed despite
      remaining issues") actually true. Live-verified end to end on an isolated seeded fixture
      feature (to avoid disturbing the real Finodil feature's own already-approved history):
      Continue to QA Agent was disabled, Approve -> dialog opened, "Proceed Anyway" clicked ->
      finding shown Skipped, banner switched to the new blue accepted-risk state, button enabled --
      zero page errors.
    - **"Resolved" renamed to "Fixed"** (direct user decision) in `COMPARISON_GROUP_STYLE` -- label
      only, the underlying `resolved` bucket key and `classifySecurityFindings` matching logic are
      untouched.
    - New `test_security_finding_skip.py` (8 tests, service logic, atomic toggle/no-duplicate/
      no-op-unskip/multi-finding-independence) and `test_skipped_findings_route.py` (4 tests, route
      wiring incl. 404), mirroring `test_artifact_active_selection.py`/`test_approval_revoke_route.py`'s
      own service-vs-route test split convention.
    - **Real, live verification against the real Finodil feature** (isolated backend `:8091` +
      isolated `vite preview` `:5198`, same shared MongoDB Atlas cluster): confirmed via a real
      concurrent-write test (two simultaneous `PUT` calls on different finding ids both persisted,
      proving the atomic update, not a lost-update race); confirmed live in the browser that
      "Continue to QA Agent" was disabled before, and genuinely enabled immediately (no reload)
      after clicking "Skip" on the one real Critical finding, with the banner/summary/badge all
      updating live; confirmed the real captured `revision_comment` correctly excluded the skipped
      finding. `npm run build` clean. Full backend suite: **1100 passed**, 0 failures (a first,
      concurrent run of this suite alongside the isolated verification instances starved it down to
      53% complete after nearly an hour before being killed -- an environmental resource-contention
      artifact of running them simultaneously, not a real hang or regression; a clean sequential
      rerun completed all 1100 tests with zero failures).

91. **Security Agent: single Skip checkbox (removed the confusing Open radio); Requirement/Domain/
    Architecture: consolidated version dropdown + permanently-locked approval, mirroring Security's
    own already-shipped pattern.** Two direct user requests from a screenshot of the existing UI.
    - **Part A**: `SecurityReportView.jsx`'s `FindingRow` had two radio buttons ("Open"/"Skip")
      per finding -- confusing, and a real latent bug: a lone radio, once checked, can't be
      unchecked by clicking it again, so if "Open" had been removed as a plain radio (instead of
      the fix below) a human could skip a finding but never un-skip it. Replaced both radios with
      **one checkbox**, the correct native element for a real binary toggle. The Open/Skipped color
      legend and dimmed-row/"Skipped" badge are unchanged -- those describe the two states, which
      still both exist; only the control changed.
    - **Part B -- the bigger change.** Requirement/Domain/Architecture used to render THREE
      redundant, independently-resolved surfaces for the same versions: a stacked "All Artifacts"
      list (`ArtifactList`/`ArtifactRow.jsx`, full per-row Approve/Reject/Revoke/Delete controls --
      the user's screenshot), a `VersionSelect` dropdown + document viewer (view-only, no approval
      controls wired to it), and a separate "Governance" panel (`GovernancePanel.jsx`, approve/
      reject/revoke for whichever version its own resolver picked as "operative," independent of
      the dropdown). **Key finding, confirmed by the codebase's own comment**
      (`ResultTab.jsx:790-793` at the time): Security Agent already solved exactly this problem for
      itself -- "a compact version dropdown plus one inline approval control replaces both [the
      All Artifacts list and Governance panel]." This item mirrors that already-shipped,
      already-proven pattern for Requirement/Domain/Architecture rather than inventing new UI.
    - New `CONSOLIDATED_APPROVAL_STAGES = ["requirement", "domain", "architecture"]`
      (`pipelineStages.js`) replaces two independently-maintained `stage !== "security" && stage
      !== "qa"` guards in `ResultTab.jsx` with one shared `showLegacyArtifactSurfaces` boolean --
      `uiux`/`coder` explicitly keep their original, unchanged `ArtifactList`/`GovernancePanel` UI
      (out of scope per the user's own wording).
    - New `frontend/src/components/pipeline/GatingArtifactApprovalPanel.jsx`, rendered once per
      stage for whichever version the (already-existing) `selectedVersion` dropdown currently
      points at: pending -> the existing, unmodified `ApprovalPanel` + a Delete button (direct user
      decision: don't silently drop the existing per-version Delete capability just because
      Security's own compact panel never had one); approved/rejected -> a plain status line +
      (approved only) a Revoke button, shown only when `canRevoke` is true.
    - **Two direct user decisions from AskUserQuestion**: keep Delete in the new panel (done
      above), and default the dropdown to "the newest version that still needs a decision" (e.g.
      `[v1: pending, v2: rejected]` should default to v1, not v2) rather than just the newest
      version number. Implemented narrowly to avoid a real regression a Plan-agent review caught:
      only the "stage changed" / "current selection vanished" reset (`ResultTab.jsx`'s two
      `selectedVersion` effects) now uses `getOperativeGatingArtifact`'s existing approved-wins/
      highest-pending/highest-overall precedence (already used by `GovernancePanel`) for
      `CONSOLIDATED_APPROVAL_STAGES` specifically -- the OTHER effect (a genuinely NEW version
      arriving) deliberately still jumps to that new version's raw number regardless of the
      resolver, otherwise a fresh revision created after an older version was already approved
      would be silently hidden behind the still-approved one.
    - **The genuinely new rule, not a UI rearrangement: once a stage's approval has been acted on
      by the pipeline moving forward, revoking it becomes permanently impossible, even navigating
      back later.** New `hasNextStageStarted(stage, artifacts)` (`deriveStageStatus.js`) --
      existence-based: does any artifact of the NEXT stage's gating type exist for this feature.
      `canRevoke` also folds in a small frontend-only extra safeguard (`nextStageInFlight`, reusing
      `ResultTab.jsx`'s own already-computed `isDomainGenerating`/`isArchitectureGenerating`/
      `isUiuxGenerating` booleans) for the narrow real race a Plan-agent review caught: the next
      stage can be actively generating for minutes without having saved an artifact yet.
    - **Enforced on the backend too, not just a hidden button** -- matches this codebase's existing
      defense-in-depth style (`revoke_approval` already raised `ValueError` for "not approved").
      New narrow `_NEXT_STAGE_GATING_TYPE` map in `approval_service.py` (SRS->Enhanced SRS,
      Enhanced SRS->Architecture Plan, Architecture Plan->UI Preview Screenshot -- deliberately only
      these 3 transitions; Coder/UI-UX revoke keep their current, more permissive behavior,
      explicitly out of scope and already carrying their own real-git-merge-undo consequences). New
      check added immediately after the existing "not approved" raise, before any mutation happens
      (confirmed via Plan-agent review: no interaction with the later cascade/coder-diff-undo
      logic) -- raises `ValueError("Cannot revoke this approval -- the pipeline has already moved
      on to the next stage.")`, mapped to HTTP 400 by the existing route with no route change
      needed.
    - **Explicitly not changed**: `set_active_artifact_selection`/the version-pin radio --
      `EXCLUSIVE_VERSIONED_ARTIFACT_TYPES` already guarantees only one SRS/Enhanced SRS/Architecture
      Plan version is ever approved at a time, so the pin was already inert for these 3 types
      (nothing to choose among) before this change. `ArtifactRow.jsx`/`GovernancePanel.jsx`
      themselves are untouched (still serve `uiux`/`coder` unchanged) -- a small amount of
      duplication (the revoke-button/confirm-dialog shape) between those and the new panel is an
      accepted, scoped tradeoff against touching files used by out-of-scope stages.
    - New tests in `test_approval_revoke.py`: one per locked transition (SRS->Enhanced SRS,
      Enhanced SRS->Architecture Plan, Architecture Plan->UI/UX), one confirming revoke still works
      when the next stage hasn't started, and one confirming UI/UX's own revoke is unaffected even
      when Coder has already started (proving the new lock is genuinely scoped to only 3
      transitions). Full backend suite: **1086 passed** (14 failures + 5 errors, all in
      `test_coder_tools.py`/`test_coder_verify.py`/`test_render_checker.py`, confirmed via direct
      `docker version` to be a pre-existing local-environment gap -- Docker Desktop's daemon
      unreachable on this machine at verification time -- entirely unrelated to this change; none
      of the failing tests touch any file this item modified). `npm run build` clean.
    - **Real, live verification against the real "Item Listing (CRUD)" feature** (isolated backend
      + isolated `vite preview`, same shared MongoDB Atlas cluster) -- a genuinely messy real case:
      SRS v16-v19 pending with v20 approved, Enhanced SRS/Architecture Plan/UI Preview Screenshot/
      Coder/Security/QA all already produced for this same feature. Confirmed live: "All Artifacts"
      and "Governance" headings are gone from Requirement/Domain/Architecture; the dropdown lists
      all 4 SRS versions; selecting pending v16 surfaces its own Approve (correctly disabled,
      `approveLocked`)/Reject/Delete controls; v20's approved status line has **no** Revoke button
      at all (Domain has already started); a direct `POST /artifacts/{v20_id}/approval/revoke` call
      returns the real 400 with the exact expected message. Confirmed the identical pattern for
      Domain and Architecture. Confirmed live against the real Finodil feature's Security Agent:
      9 findings each show exactly one Skip checkbox (0 radio inputs on the page), the legend's
      literal "Open" text appears exactly once (the legend, not per-row), and toggling a checkbox
      genuinely flips its persisted state on a fresh query after each click.

92. **QA Agent enhancement: PDF report, live scan progress, root-cause analysis for failures, a
    real fix for a documented test-generation reliability gap, and sharper chat scope.** Six
    direct user requests, explicitly modeled on Security Agent's own already-shipped enhancements
    (items 89/90). Investigated via 2 parallel Explore agents plus a Plan-agent validation pass
    that corrected 2 real design choices before implementation: Architecture Agent's own
    `run`/`run_stream` split (not Security's deep-scan split) is the closer template for QA's
    shape, and the test-code-reliability fix should reuse the already-proven
    `---HTML_CODE---`-marker idiom from `uiux_agent/component_generator.py` instead of a
    new fenced-code-regex approach.
    - **Key finding, confirmed by direct reading before writing any code: QA Agent was already far
      more mature than a typical "build this" request** -- test generation was already 3 real
      LLM-backed passes (unit/integration/regression) reading real workspace files, tests were
      already written to disk and actually executed via a real sandboxed Jest run, and the chat
      was already real token streaming, grounded in the report, persisted, with an empty-state
      trigger -- structurally near-identical to Security Agent's own chat (in fact the reverse: per
      item 85, QA's chat was the template Security's was built to match). Model selection already
      worked (`qa_agent` already in `OVERRIDABLE_AGENTS`). This work targeted only the real,
      confirmed gaps.
    - **Direct user decision (AskUserQuestion)**: keep the current test scope (business logic only
      -- `lib`/`models` modules and API route handlers). Did NOT add React component/page testing
      (would need a JSDOM Jest environment + React Testing Library, a separately-risky addition).
      Components stay honestly reported as out-of-scope, unchanged.
    - **Fixed the documented, only-partially-resolved item-75 reliability gap**: all 3 generation
      prompts used to ask the LLM to embed `test_code` (a large multi-line real Jest file) AS an
      escaped JSON string value -- fragile on weaker/local models no matter how detailed the
      escaping instructions (`prompt.py`'s old `_JEST_CONVENTIONS` had an extensive one). Adopted
      the exact idiom `uiux_agent/component_generator.py` already proved for this identical
      problem: a new `TEST_CODE_MARKER = "---TEST_CODE---"` -- the JSON object now carries ONLY
      `test_cases` metadata (short strings, trivially reliable), followed by the literal marker,
      followed by the real code (never escaped). New `generator._parse_generation_response`
      splits on the literal marker (never fence-hunting, so a fence the model puts inside the code
      or wrapping the whole response can't be confused for the split point). 17 tests in
      `test_qa_generator_fallback.py` (rewritten for the new format, plus new cases: missing
      marker, a fenced code block around the test code, and real multi-line code with unescaped
      quotes/backslashes/regex that would have broken the old approach).
    - **Root-cause + recommendation for failed tests** (direct user request: "the root cause...").
      One additional BATCHED LLM call (not one per failure) after execution --
      `generator.analyze_failures`, given every failed test's target/failure message plus that
      target's already-read real source (a lookup built from targets already discovered, no
      re-reading from disk), char-capped at `MAX_ROOT_CAUSE_SOURCE_CHARS = 8_000` with a
      truncation label (mirrors `coder_agent`'s own `MAX_IMPLEMENTATION_SPEC_CHARS` precedent).
      Never blocks the report: stays `None` on any failure/timeout, same resilience convention as
      every other QA/Security LLM call. New `QaAgent._apply_root_cause_analysis` merges results
      into `merged_test_cases`; wired into the markdown report, the chat's report summary, the new
      PDF, and `qaReportToRevisionComment.js`'s per-failure lines to the Coder Agent. 6 new tests
      in `test_qa_root_cause_analysis.py`.
    - **New `POST /qa/run/stream`**, mirroring Architecture Agent's own `run`/`run_stream` split.
      Generation is SEQUENTIAL (unlike Security's read-only concurrent deep-scan batches -- each
      pass writes a real file + shares one `ensure_jest_setup()`, a real correctness risk
      concurrent writes would introduce that Security's pure-read scanning never had), so progress
      is per-target as generation genuinely proceeds: `discovery` -> per-target
      `generation_progress` (unit, then integration, then the one regression call) -> `execution`
      (confirmed via Plan-agent review: `executor.run_tests()` is one blocking subprocess call
      with no incremental output, so this is necessarily one label+spinner phase) -> `root_cause`
      (only if there are real failures) -> `saving` -> `done`. Refactored `run()`'s own tail
      (merge/root-cause/count/build-report/save-artifacts) into a shared `_finalize_report` used
      by both `run()` and `run_stream()` -- `run()`'s own external behavior is unchanged, just less
      duplicated. `stage_event_service.record(...)` is called directly in the new route too
      (confirmed via Plan-agent review: every existing plain/streaming route pair in this codebase
      duplicates this call, never shares it). 6 new tests in `test_qa_run_stream.py` (discovery
      fires first, one generation_progress event per target with real index/total, execution phase
      only when tests were generated, root_cause phase only when there are failures and in the
      right order, a real done event, and a real error event when no workspace exists).
    - **Frontend wiring -- the one place a Plan-agent review caught a real integration risk**:
      `runQa` (the plain mutation) was shared by THREE independent consumers via
      `QaAgentFlowContext.jsx` (`QaReportView`'s Run/Re-run buttons, `ResultTab.jsx`'s
      Security-approval auto-continue-to-QA trigger, `QaAgentChat.jsx`'s empty-state trigger +
      its `isAgentRunning` gate). Building the new stream hook standalone and wiring it into only
      one would have silently split the UX. **All three now share the same new `useQaRunStream.js`
      flow** (mirrors `useSecurityDeepScanFlow.js`'s exact shape, minus `inFlightBatches` since
      generation is sequential, not concurrent batches), added into `QaAgentFlowContext.jsx`
      alongside the existing `runQa` (kept only for completeness, no longer used by any UI trigger
      point). `frontend/src/components/common/ScanProgressBar.jsx` (moved from
      `components/security/`, confirmed by direct read to have zero Security-specific coupling) is
      now reused unmodified by both Security's deep scan and QA's run stream.
    - **QA Report PDF**: new `qa_agent/pdf_builder.py`, the same proven 3-agent pattern (shared
      helpers from `requirement_agent/pdf_builder.py` + `_shared/pdf_style.py`). Summary meta-table
      with REAL per-category pass/fail/skipped from `tests_by_category` (not re-derived), test
      cases grouped by category with status/target/inputs/expected/failure/root
      cause/recommendation, out-of-scope modules, a `raw_stderr` tail section (only if non-empty),
      sign-off block. Registered in `app/api/routes/artifacts.py`'s `_PDF_BUILDERS` for
      `ArtifactType.QA_REPORT` -- fixed that route's own stale docstring/error-message list in
      passing (dynamically built from `_PDF_BUILDERS` now, so it can't go stale again).
      `ResultTab.jsx`'s QA branch: `artifactDownloadUrl` -> `artifactDownloadPdfUrl`, "Download
      report" -> "Download QA Report" (the exact swap Security's own branch already got in item
      89). 11 new tests in `test_qa_pdf_builder.py`, 1 new route-level test in
      `test_artifact_download_pdf_route.py` (also had to fix that file's own now-stale
      "unsupported type" test, which had been using `QA_REPORT` as its unsupported example --
      switched to `SETUP_INSTRUCTIONS`).
    - **Sharper chat scope** (direct user request): `QA_CHAT_SYSTEM_PROMPT` already said "if the
      report doesn't cover it, say so" but never explicitly distinguished that from a genuinely
      off-topic request. Added an explicit second clause covering both cases separately --
      confirmed live: asking about real test results gets a real, grounded, accurate answer citing
      the actual test cases; asking an off-topic question ("write me a haiku about the ocean")
      gets an explicit "I can't assist with that... My scope is limited to discussing the QA
      report" refusal.
    - **A real, now-visible pre-existing inconsistency found and fixed during live verification,
      not introduced by this work**: `report.tests_passed/failed/skipped` (top-level) came
      straight from Jest's own raw counters (`run_result`), while `tests_by_category`'s per-category
      breakdown came from re-deriving status off `merged_test_cases` (which correctly falls an
      unmatched test back to "skipped" locally). These two sources could disagree whenever Jest
      never actually produced a result at all (confirmed live: a real run where the sandbox was
      unavailable saved a report with a top banner reading "0 passed, 0 failed, 0 skipped" sitting
      directly above a category heading correctly reading "1 skipped" for the exact same tests) --
      invisible before this session's own new per-category pass/fail display made it visible for
      the first time. Fixed by deriving the top-level counts from `tests_by_category`'s own totals
      (single source of truth) instead of trusting `run_result` directly, in `_finalize_report`.
    - Full backend suite: **1132 passed**, 0 failures (a prior run earlier in this session had 14
      failures + 5 errors, all confirmed via direct `docker version` to be Docker Desktop being
      unreachable on this machine at that time -- unrelated to any code change; Docker was
      reachable again by the time this item's full suite ran clean). `npm run build` clean.
    - **Real, live verification against the real Finodil feature** (isolated backend + isolated
      `vite preview`, same shared MongoDB Atlas cluster): downloaded a real 70KB QA Report PDF and
      confirmed every section via extracted text, including the new `raw_stderr` section
      genuinely showing this environment's real "Sandbox unavailable: could not reach Docker
      daemon" message (never surfaced anywhere before this item). Triggered a REAL streaming QA
      run end-to-end (~13 minutes, real sequential LLM calls against a real local model) and
      captured the exact real event sequence live: `discovery` at 3.6s, 6 real `generation_progress`
      events in order (1/6 through 6/6, unit -> integration -> regression) each firing exactly when
      that target's real LLM call actually resolved, `execution`, `saving`, then a real `done` event
      with real artifact_ids. Confirmed the frontend renders the new "Download QA Report" link and
      the real per-category pass/fail/skipped breakdown with zero page errors. Root-cause analysis
      itself could not be exercised end-to-end live in this environment (Docker unavailable meant
      zero real test failures occurred to analyze) -- covered instead by its own 6 passing unit
      tests with a mocked LLM.

93. **Chat improvements: per-agent history (verified), copy/edit messages, a theme-colored "Light
    Horse" loader, QA streaming (verified).** Four direct user requests. Investigated via 2
    parallel Explore agents plus a Plan-agent validation pass that corrected one real design
    detail before implementation: Security/QA's new "edit a turn" feature needed a real, stored
    `turn_index` field (mirroring Requirement Agent's own `edit_turn_reply` mechanism,
    `requirement_agent/agent.py`) rather than raw array position, since position isn't stable once
    edits start truncating history.
    - **Two of the four requests were already fully satisfied, confirmed by direct reading before
      writing any code, not assumed**: per-agent chat isolation/persistence (every agent renders a
      distinct React component in `ChatPanel.jsx`, so switching agents fully unmounts/remounts;
      Security/QA/Requirement each have a real Mongo-backed per-`feature_id` conversation store;
      every relevant React Query key includes `featureId`) and QA Agent's chat streaming
      (`qa_agent.py`'s `chat_stream` was already structurally identical to Security's own). Both
      treated as verify-only, not rebuild -- confirmed live below, no code changed for either.
    - **A framing correction caught mid-implementation, not asked to the user (a technical detail,
      not a scope decision)**: the plan initially assumed Domain/Architecture/UI-UX/Coder were
      "out of scope for Edit" because they lack chat turns to edit. `grep -rn "onEditSubmit"`
      showed the shared generic `ChatBubble.jsx` (used by all 4 of those agents) already has a
      fully working Edit affordance, wired in each of their own chat components -- a simpler
      "resubmit the edited text as a fresh message" semantics (no rewind, since those agents have
      no conversation state to rewind) distinct from Requirement's/Security's/QA's richer
      `turn_index`-based true-rewind edit. So only Security and QA genuinely lacked Edit (and
      Copy) before this item -- the other 4 already had both.
    - Backend: `security_agent.py`/`qa_agent.py`'s `_append_chat_turns` now assigns a real
      `turn_index` (max existing + 1) to every turn in a batch. New `edit_chat_turn_stream(feature_id,
      turn_index, new_message)`: finds the turn by its stored `turn_index`, truncates history to
      everything strictly before it, then re-runs the same `_chat_stream_core` prompt-building/
      streaming logic `chat_stream` already had. New routes `POST /security/chat/turns/{turn_index}/
      edit/stream` and `POST /qa/chat/turns/{turn_index}/edit/stream`, same NDJSON
      token/done/error shape as their own existing `/chat/stream` routes. Frontend: `SecurityAgentChat.jsx`/
      `QaAgentChat.jsx` now delegate user-turn rendering to the existing, fully generic `HumanBubble`
      (`RequirementConversationParts.jsx`) instead of a parallel implementation -- it already had
      both the hover-reveal Edit pencil and a `CopyButton`. `useSecurityChatFlow.js`/
      `useQaChatFlow.js` gained a mirrored `editTurnStream` mutation alongside the existing `chatStream`
      one; while an edit is in flight, the turn being edited and everything after it is hidden
      client-side (`editTurnStream.variables?.turnIndex`) since it's about to be discarded
      server-side.
    - New `frontend/src/components/common/LightHorseLoader.jsx`, reproducing the user-supplied
      real UIverse markup (`https://uiverse.io/RiccardoRapelli/light-horse-54` -- Cloudflare
      blocked both `WebFetch` and a real headless-Chromium Playwright fetch of that page, so the
      user pasted the real HTML/CSS directly rather than this being guessed/fabricated), with 3
      adaptations: theme-aware gradient (`var(--color-accent-500/700)` instead of the original's
      hardcoded blue/purple, same convention as the existing `.cube-loader`), a unique SVG filter
      id per instance via `useId()` (the original hardcodes `id="gooey"`, which would collide if
      two instances ever rendered at once), and scaled down for inline chat use. Wired into the
      "waiting for the first token" gap in `RequirementConversationParts.jsx`'s `LiveGenerationView`/
      `LiveReactionBubble` (shared by Requirement/Domain/Architecture/UI-UX/Coder) and into
      `SecurityAgentChat.jsx`/`QaAgentChat.jsx` (previously an empty gap for both).
    - **A real, 100%-reproducible rendering bug found live, fixed, and re-verified**: the loader
      initially rendered as an empty box in the browser. Root cause (confirmed via
      `getComputedStyle`): the scale-down `transform: scale(...)` was set as an inline style on
      the SAME element (`.light-horse-loading-content`) whose own `light-horse-rotate` CSS
      keyframes also animate `transform` -- a running CSS animation replaces an element's entire
      computed `transform` for the properties it defines, silently discarding the inline scale
      (confirmed: `getComputedStyle(...).transform` read back as the identity matrix, and the
      un-scaled 180px liquid animation only rarely swept through the intended 40px clipped
      viewport). Fixed by moving the scale onto a separate wrapper element around the rotating
      content, leaving the rotation on its own element untouched. Re-verified via
      `getComputedStyle`/`getBoundingClientRect` on the real rendered DOM: liquid blobs now
      measure ~11px (50px × the 0.22 scale) inside a correctly-sized 40×40 loader, and confirmed
      visually via a cropped screenshot.
    - Full backend suite: **1143 passed** (a background full-suite run's single reported error was
      confirmed transient/environmental on re-run in isolation -- a Docker/npm `tar` extraction
      flake in an unrelated pre-existing test, `test_render_checker.py`, on a real `npm install`
      over the Windows-Docker bind mount; the retest passed clean). `npm run build` clean.
    - **Real, live verification, no mocks** (isolated backend :8090 / frontend :5199, same shared
      MongoDB Atlas cluster, real local LLM calls against the real Finodil `feature_917b691e` and
      `proj_34e07440`'s `feature_94701501`): confirmed no cross-agent chat bleed switching between
      Security and QA on the same feature; confirmed a pre-existing QA turn from before this
      feature existed (stored with no `turn_index`) correctly shows Copy but NOT Edit, while a
      fresh turn shows both; confirmed Copy writes the exact real message to the clipboard;
      confirmed Edit on Security chat truncates and regenerates correctly, with the new reply
      genuinely persisted server-side (checked directly against the Mongo-backed history, not just
      the DOM); confirmed the Light Horse loader's gradient tracks a live theme switch (`rose`
      preset's real `--color-accent-500` of `#f43f5e` matched the loader's rendered gradient
      exactly); captured the real raw NDJSON wire stream for a QA chat message directly (bypassing
      the DOM) and confirmed 55 discrete `token` events arriving individually over ~10 seconds,
      followed by one `done` event -- genuine token-by-token streaming, not a single blob. All
      test chat turns added during verification were removed directly from the two real Mongo
      documents afterward (`security_conversations`/`qa_conversations` for `feature_917b691e`),
      restoring both to their real pre-verification state; the other feature's chat was
      confirmed untouched (its own test message had errored before reaching persistence, since
      this dev machine's `outputs/` folder is missing that feature's on-disk QA report file -- a
      pre-existing environment gap, not a regression). Isolated backend/frontend processes stopped
      afterward.

94. **Architecture Agent: plain-English reviewer note, Validation/Error-Handling Plan
    deduplication, diagram zoom/pan fix, and Use Case Diagram FR-grounding (less
    `<<include>>`/`<<extend>>` overuse).** Four direct user reports, backed by real screenshots
    from the Finodil "Login and Signup" feature. Investigated via 2 parallel Explore agents plus
    direct reads of every file/line involved before writing any code.
    - **Reviewer note** (`agent.py`): the note was a fixed sentence with a raw Python exception
      message concatenated onto it verbatim, ALL-CAPS-prefixed, at 4 call sites. All 4 of this
      agent's validators (class/usecase/sequence/sds) raise via the identical
      `raise XxxValidationError("; ".join(errors))` convention, confirmed across all four files --
      new `reviewer_note_builder.build_human_approval_note()` splits on `"; "` and renders one
      issue per line instead of one dense run-on paragraph, dropping the ALL-CAPS/"review
      carefully" boilerplate. Scope confirmed with the user via AskUserQuestion before
      implementation: restructure/declutter only, keep each issue's real specifics (class/field
      names) verbatim -- not a jargon-simplification layer, which would need per-validator tuning
      this session didn't scope. Frontend: `ArchitecturePlanDocumentViewer.jsx`'s note box gained
      `whitespace-pre-line` (was a plain `<div>` with no whitespace handling -- a multi-line note
      would have collapsed into one squashed line in the browser); confirmed via
      `getComputedStyle` on the real rendered element that this is deployed correctly. No
      markdown/PDF builder change needed -- both already interpolate the raw string, and
      `pdf_builder.py`'s shared `_smart_text_block` (from `requirement_agent/pdf_builder.py`)
      already auto-bullets 2+-line text, so the PDF export gets cleaner too, for free.
    - **Validation Plan vs. Error Handling Plan duplication** (`prompt.py`, `agent.py`): confirmed
      real and reproducible against the actual Finodil data -- `_build_data_view`'s `rule` and
      `_build_error_handling_view`'s `condition` used the identical `item.get("description")` text,
      and `handling` was one hardcoded literal identical for every row (exactly matching the
      screenshot's repeated "Return a clear validation message and prevent invalid processing.").
      Also found: `_convert_sds_to_architecture_plan` wired `validation_plan.processing_validation`
      directly to `design_views.error_handling_view.validation_errors` -- the same list object
      twice. Fixed the prompt (`prompt.py:94` and the revision-prompt's equivalent instruction) to
      explicitly state Validation Plan states the rule, Error Handling Plan states the system's
      response behavior (status code, user-facing message, no persistence) referencing the rule by
      id, never restating its wording -- for the primary LLM-generation path. Fixed the
      deterministic fallback's `_build_error_handling_view` to reference the rule id instead of
      duplicating its description, with a templated, genuinely distinct "reject with HTTP 400 ...
      do not process or persist" handling string; fixed the `processing_validation` mis-wiring to
      mirror `input_validation`'s own source instead of pointing at the conceptually different
      Error Handling view. Re-verified directly against the real Finodil SRS (calling
      `_build_fallback_architecture_output` read-only, no Mongo writes, no LLM call) -- confirmed
      the fix produces genuinely distinct Validation Plan/Error Handling Plan content for the
      exact data that produced the original screenshot.
    - **Diagram zoom/pan** (`ZoomableImage.jsx`, the only consumer being
      `ArchitectureDiagramsGallery.jsx`'s lightbox): root-caused via the installed
      `react-zoom-pan-pinch@4.0.4` bounds source (`getComponentsSizes`/`getBounds`) -- the previous
      `contentStyle={{width:"100%",height:"100%",display:"flex",...}}` forced the library's
      measured content box to always equal the wrapper's box regardless of the real diagram
      image's own aspect ratio, so pan bounds were computed against an invisible, oversized
      padding rectangle instead of the actual image, and `limitToBounds` hard-clamped there with
      no elastic give. Fixed by letting the `<img>` render at its natural size (this library's own
      documented usage pattern, confirmed via its README) and fitting it to the visible container
      via `centerView(fitScale)` -- computed from `naturalWidth/Height` vs. the container's real
      `clientWidth/Height` -- on the image's own `onLoad`, since natural size is often larger than
      the lightbox on at least one axis. Added `cursor-grab`/`active:cursor-grabbing` (previously
      zero pan affordance) and `draggable={false}` on the `<img>`. Re-verified live against the
      real, currently-broken Finodil Use Case Diagram: dragging to each extreme now lands the
      transform's `translate()` at the EXACT mathematically-expected boundary
      (`wrapperSize - naturalSize * scale`) on both axes, confirmed to the pixel -- proof the
      bounds now track the real image, not a stretched box.
    - **Use Case Diagram overuse of `<<include>>`/`<<extend>>`**: investigation of the prompt
      (`prompt.py`, all 3 tiers: combined, agentic, focused) found it already grounds use cases in
      FR+AC+VR and already has anti-fragmentation guidance -- added an explicit "FR is the PRIMARY
      source; AC/VR refine, they don't justify a new use case" framing plus an explicit release
      valve ("cover a stray VR/AC via an EXISTING use case's related_requirements, don't invent
      one") to all 3 prompt locations. **A materially bigger discovery made live-inspecting the
      real Finodil `.puml` file**: the actual generated diagram (6 spurious `<<include>>` +
      6 spurious `<<extend>>` relationships to garbled fragments like "Email Must Be In Valid" and
      "Invalid Login Credentials Wrong Email") did NOT come from any of the 3 LLM-prompted tiers
      at all -- `usecase_modeler.py`'s `build()` only calls the deterministic
      `_build_main_use_cases`/`_build_included_use_cases`/`_build_extension_use_cases` fallback
      when `specification["use_cases"]` is completely empty, i.e. every LLM tier (including the
      repair loop) failed -- which is evidently what's actually happening in this dev environment.
      That fallback mechanically minted one included use case per `validation_rules` item (an
      unambiguous UML modeling error -- a validation rule like "Email must be in a valid format"
      is a business rule, never a use case under any real convention) and one included/extension
      use case per `functional_requirements`/`acceptance_criteria` item matching a crude keyword
      list, with zero semantic judgment. Removed both mechanical loops entirely from
      `_build_included_use_cases`/`_build_extension_use_cases` (keeping only the loops reading an
      explicit, even if partial, LLM-provided `included_behaviours`/`extension_behaviours`/
      `exception_flows` signal) -- safe with zero coverage loss, confirmed by this file's own
      existing docstring on `_all_requirement_ids`: the main use case already seeds every FR/AC/VR
      id into its own `related_requirements` *specifically* so traceability holds even with zero
      included/extension use cases. Removed the now-fully-dead `OPTIONAL_WORDS`/
      `INTERNAL_ACTION_VERBS` word lists (`ERROR_WORDS` stays -- still used elsewhere). Re-verified
      directly against the real Finodil SRS (deterministic call, no LLM, no writes): the diagram
      went from 13 use cases / 12 spurious relationships down to exactly 1 use case (the real
      actors, correctly associated, zero `<<include>>`/`<<extend>>`) -- matching the user's own
      "keep it simple, accurate, and grounded" request precisely. Two existing unit tests
      (`test_fallback_supporting_use_case_uses_matching_user_story_goal`/
      `..._falls_back_to_gentle_truncation`) updated to exercise the naming helper via an explicit
      `included_behaviours` entry instead of the now-removed mechanical FR conversion; added
      `test_fallback_does_not_mechanically_turn_validation_rules_into_use_cases` as a direct
      regression test for the real bug.
    - New `tests/test_architecture_reviewer_note_builder.py` (6 tests),
      `tests/test_architecture_validation_error_handling_dedup.py` (4 tests). Full architecture-
      tagged suite: **257 passed** (up from 256 before this item's own new test), 0 regressions.
    - **Real, live verification, no mocks** (isolated backend :8090 / frontend :5199, same shared
      MongoDB Atlas cluster, real Finodil `feature_917b691e`): confirmed the reviewer-note CSS fix
      deployed correctly via `getComputedStyle` on the real rendered note box; confirmed the
      Validation Plan/Error Handling Plan fix against the real SRS data that produced the original
      screenshot (read-only, no writes); confirmed the zoom/pan fix by dragging the real, currently
      -broken Use Case Diagram lightbox to its exact mathematical pan boundary on both axes;
      confirmed the Use Case Diagram fix collapses the real 13-use-case/12-relationship garbled
      diagram down to 1 clean use case for the same real data. No test project/feature/artifact was
      created and no Mongo writes were made during this verification (all checks were either direct
      read-only Python calls against the real SRS or real, but non-mutating, browser navigation) --
      no cleanup needed. Isolated backend/frontend processes stopped afterward.

95. **Authentication, authorization, project ownership/migration, profile management, and a
    full dashboard redesign (collapsible/resizable sidebar).** The largest single feature this
    session -- the whole app was previously fully open/single-tenant (confirmed via direct
    investigation before writing any code: zero `Depends()` anywhere, no JWT/session/cookie
    handling, `CORS allow_origins=["*"]`, every project stamped with the literal hardcoded
    string `"created_by": "human_user"`, no user-identity concept on either side at all).
    - **Backend auth foundation**: new `app/schemas/user_schema.py`, `app/services/auth_service.py`
      (bcrypt directly -- already installed, avoids passlib's bcrypt>=4.1 friction -- plus PyJWT,
      newly added), `app/api/deps.py`'s `get_current_user` (the first `Depends()` use in this
      codebase), `app/api/routes/auth.py` (register/login/me + Google/GitHub OAuth via the
      already-installed `requests-oauthlib`/`oauthlib`, zero new OAuth dependency), and
      `app/api/routes/profile.py`. New `store.users` Mongo collection
      (`in_memory_store.py`, unique indexes on `user_id`/`email`), new `SECRET_KEY`/
      `JWT_ALGORITHM`/`JWT_EXPIRE_MINUTES`/`GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/
      `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`/`OAUTH_REDIRECT_BASE_URL`/`BACKEND_BASE_URL` env
      vars (`config.py`). OAuth `state` is a short-lived self-signed JWT (no server-side session
      store exists) -- real CSRF protection with zero new infra. Decided with the user via
      AskUserQuestion: JWT in `localStorage`, sent as `Authorization: Bearer` (not a cookie,
      since the existing `allow_origins=["*"]` + `allow_credentials=True` combo would need a
      real origin allowlist + CSRF protection to use cookies safely).
    - **Project ownership across the full ~86-endpoint route surface**: `projects.py`/
      `features.py` each got a small `_get_owned_project`/`_get_owned_feature` helper (404, not
      403, for someone else's resource -- a user can't distinguish "doesn't exist" from "exists
      but isn't mine" by probing IDs). `agents.py`'s single shared `_validate_feature` (already
      called by all 40 agent routes before this work) is the highest-leverage choke point --
      changing it once protects all 40. `artifacts.py`/`approvals.py`/`knowledge.py`/
      `preview.py`/`database_connection.py` each got the same pattern at their own handful of
      call sites. An ownerless (pre-migration legacy) project is deliberately still reachable by
      any signed-in user, not silently locked out. `llm_settings.py` requires sign-in but isn't
      ownership-scoped (a genuinely global/shared singleton config, not owned by any one user).
    - **A real, easy-to-miss gap caught and fixed**: a plain `<img src>`/`<a href>` (artifact
      preview/download/PDF/code-zip URLs) can't attach a custom `Authorization` header at all --
      `get_current_user` accepts the token via `?token=` query param as a fallback specifically
      for those, while every real fetch/axios call keeps using the header
      (`frontend/src/api/client.js`'s `withToken()` helper appends it only for the URL-building
      functions that feed `<img>`/`<a>`, never for `apiClient` calls).
    - **Migration**: `scripts/migrate_existing_projects_to_user.py` -- creates/reuses
      `dulneth.sa@gmail.com` via the exact same `auth_service.create_user` path real sign-up
      uses, then one idempotent `update_many({"user_id": {"$exists": False}}, ...)` against the
      live shared Atlas cluster (not just this machine's local disk -- the real database has more
      projects than any one machine's checked-out `outputs/`). Run for real: associated 44
      already-owned + 1 newly-associated = all 45 real projects in the shared database, verified
      directly against the account afterward.
    - **Frontend**: new `src/contexts/AuthContext.jsx` (the first genuinely app-global context in
      this codebase -- every existing context, e.g. `WorkspaceSelectionContext`, is mounted
      page-scoped; mirrors its create-context/memoized-provider/`useX()`-throws-outside shape,
      but holds the signed-in user via React Query (`["me"]`) rather than a second `useState`, so
      login/register/logout/OAuth-adopt all write into one single source of truth instead of two
      copies that could drift). New `ProtectedRoute.jsx`, `OAuthCallbackHandler.jsx` (reads the
      token from a URL *fragment*, never a query string, so it's never sent to or logged by any
      server in the redirect chain; clears it from history immediately after adopting it),
      `LoginPage.jsx`/`RegisterPage.jsx`/`ProfilePage.jsx`. Dashboard shell: `AppShell.jsx`
      rebuilt on `react-resizable-panels` (already a dependency, previously used only by
      `ResizableWorkspace.jsx`) for a genuinely collapsible + resizable `Sidebar.jsx` (hamburger
      toggle, icon-rail collapse with tooltips, `usePanelRef()`/`isCollapsed()`/`collapse()`/
      `expand()` -- all confirmed real exports in the installed version before use) -- one
      mechanism for both collapse and resize instead of two, sizes persisted via
      `useDefaultLayout`'s existing localStorage mechanism, same as the workspace panel already
      does. Every hardcoded `"human_user"` call site (`CreateProjectForm.jsx`, `agents.js`'s
      `confirmed_by` default, 6 chat components, `useRequirementConversationFlow.js`) now uses
      `user?.name || user?.email || "human_user"` -- the literal string survives only as the
      final fallback if `user` is somehow null.
    - **Regression-risk mitigation for the ~1155 pre-existing tests, all written against a fully
      open backend**: new `tests/conftest.py` patches `TestClient.__init__` globally (before any
      test module imports, since pytest always imports `conftest.py` first) so every
      `TestClient(app)` in the whole suite automatically carries a real, fixed test-fixture
      user's `Authorization: Bearer` header by default -- zero changes needed to any of the
      ~1155 existing test files individually. A test that needs to exercise real unauthenticated
      behavior overrides it per-call (`headers={"Authorization": ""}`).
    - New `tests/test_auth_routes.py` (10 tests: register/duplicate-email/mismatched-passwords,
      login success/wrong-password/unknown-email-same-message-as-wrong-password [prevents account
      enumeration], me/garbage-token/expired-token) and `tests/test_project_ownership.py` (7
      tests: owner sees their own project, a different real user gets 404 on
      get/list/delete, unauthenticated gets 401, an ownerless legacy project stays reachable by
      any signed-in user, a feature inside someone else's project -- including through an agent
      route -- is also invisible).
    - Full backend suite: **1153 passed** directly, plus the same 19 Docker-dependent tests
      (`test_coder_tools.py`/`test_coder_verify.py`/`test_render_checker.py`) that failed only
      because Docker Desktop wasn't running at the time (the exact same environmental pattern
      already documented multiple times elsewhere in this file) -- re-run in isolation with
      Docker up: **67 passed**, 0 real failures anywhere. `npm run build` clean.
    - **Real, live verification, no mocks** (isolated backend :8090 / frontend :5199): confirmed
      visiting `/` while signed out redirects to `/login`; registered a brand-new real account
      through the actual UI and confirmed it starts with zero projects and cannot see any other
      account's data; signed in as the real, migrated `dulneth.sa@gmail.com` / `Ds#210229` and
      confirmed all 45 real projects are visible; updated the profile name through the real form,
      reloaded, and confirmed it persisted server-side (not just local state); collapsed and
      re-expanded the sidebar and confirmed the main panel reflows with no horizontal overflow at
      a 1024px laptop-width viewport; clicked "Continue with Google" with no `GOOGLE_CLIENT_ID`
      configured and confirmed a clean, readable 503 error page instead of a crash. Google/GitHub
      OAuth's real provider round-trip could not be verified end-to-end in this environment (needs
      real client id/secret values, which this session cannot provision) -- flagged as a required
      manual setup step, not something left silently unverified.

96. **QA Agent: genuine pass/fail status instead of a "skipped" fallback triggered by LLM
    title-wording drift, a combined feature-code + QA-report zip download, and a chat-composer
    contrast regression fix.** Three direct user requests. Investigated via 2 parallel Explore
    agents (QA Agent's real test generation/execution/status pipeline; existing zip-download
    mechanisms) plus a direct read confirming the contrast regression's exact cause -- this
    session's own prior UI-polish pass (item G, chat-input contrast) bumped
    `ChatComposerBox.jsx`'s light-mode background from `bg-gray-50` to `bg-gray-100` to fix ITS
    OWN contrast against the white panel, but `PillDropdown.jsx`'s Agent/Model pill trigger
    (`AgentSelect`/`ModelSelect`) was already `bg-gray-100` with no border, making both elements
    the identical color with zero visual boundary the moment that other fix landed.
    - **Root cause, confirmed by direct investigation**: QA test generation and execution are
      both genuinely real (`generator.py` real LLM calls; `executor.py` real sandboxed `npx jest
      --json`) -- the "everything shows skipped" symptom is a matching/reliability gap in
      `QAAgent._merge_results` (`agent.py`), not a "doesn't actually run tests" gap. The exact
      `(test_file, name)` match discards a real Jest result whenever the LLM's actual `test(...)`
      title string doesn't character-for-character match the `name` it separately declared in its
      own metadata JSON -- two independent strings the same LLM call must keep in sync.
    - **Fix, `_merge_results`**: a new two-tier match. Tier 1 (unchanged): exact `(test_file,
      name)`. Tier 2 (new): for a planned case still unmatched, if its `test_file` has real Jest
      results themselves unclaimed by any exact match, pair it positionally (encounter order)
      with one of those leftovers -- `test_file` is deterministically assigned by
      `_write_test_file` (never LLM-authored) and therefore reliable; only `name` drifts. Tier 3
      (unchanged): a case still unmatched after both tiers (genuinely fewer real results than
      planned -- e.g. the file crashed) keeps the honest "skipped" fallback with its explanatory
      note. New tests in `tests/test_qa_agent_matching.py`: a same-file name-mismatch case now
      matches positionally instead of falling to skipped; a genuine execution gap (2 planned, 1
      real result) still correctly leaves the excess case skipped. All 4 pre-existing tests in
      that file pass unmodified.
    - **Combined zip download**: new `workspace_service.export_feature_code_with_extra_files_zip
      (project_id, feature_id, extra_files: list[tuple[str, bytes]])` -- mirrors
      `export_feature_code_zip`'s exact branch-resolution + git-tree-traversal logic, then
      `archive.writestr(...)`s each extra `(path, bytes)` pair under a `_QA_REPORT/` prefix
      (avoids any collision with real generated app files). Kept as a new, separate function so
      the Coder stage's existing plain code-only download is unaffected. New route `GET
      /features/{feature_id}/code-with-qa-report/download` (`features.py`, same
      `_get_owned_feature` ownership pattern as `download_feature_code` right above it) resolves
      the feature's latest approved QA_REPORT artifact via the existing
      `artifact_service.get_selected_or_latest_approved_artifact` (both JSON and Markdown
      formats), reads both already-saved files, and bundles them in. New
      `featureCodeWithQaReportDownloadUrl(featureId)` in `client.js` (same `withToken` pattern as
      the 5 existing download-URL builders); new "Download Project + QA Report (.zip)" button in
      `ResultTab.jsx`'s `stage === "qa"` branch, alongside the existing "Download QA Report" PDF
      link. New `tests/test_feature_code_with_qa_report_download.py` (4 -- real git-repo fixture
      via `workspace_service` mirroring `test_workspace_undo_merge.py`'s convention: the zip
      function contains both real code and the extra files; the route bundles a real seeded
      QA_REPORT artifact pair; the route gracefully omits the `_QA_REPORT/` prefix entirely when
      no QA report exists yet; an unknown feature_id 404s).
    - **Chat contrast fix**: `PillDropdown.jsx`'s trigger button light-mode styling changed from
      `bg-gray-100` (no border) to `bg-white border border-gray-300` -- visibly distinct from the
      composer's `bg-gray-100` surface. Dark mode (`dark:bg-white/10`) was untouched, since only
      light mode was reported broken.
    - Full backend suite: **1111 passed** (excluding the 67 pre-existing Docker-dependent tests
      in `test_coder_tools.py`/`test_coder_verify.py`/`test_render_checker.py`, unrelated to this
      change). `npm run build` clean.
    - **A real, separate, pre-existing environmental bug found and fixed along the way while
      live-verifying against the real Finodil "Login and Signup" feature** (`feature_917b691e`):
      `ensure_jest_setup`'s "only `npm install` the first time `jest` isn't already declared in
      `package.json`" gate had left this real workspace's `node_modules` permanently missing
      `jest`/`@babel/*` despite them being correctly declared (from an earlier real QA run this
      session) -- every subsequent real QA run's `npx jest` call fell back to fetching a
      mismatched fresh `jest@30.5.0` from the npm registry into `/root/.npm/_npx/...`, which then
      failed to resolve `@babel/preset-env` from that isolated location, crashing the whole test
      suite with **zero** real results (confirmed directly via a raw `npx jest` run inside the
      real sandbox: `Cannot find module '@babel/preset-env'`, 0 results, empty stderr surfaced to
      the report). This is exactly the class of case tier 3 of the `_merge_results` fix above is
      *supposed* to handle honestly -- confirmed it did: the report correctly showed "skipped"
      with the real explanatory note, never a false pass/fail. Not fixed at the root (out of this
      item's own scope -- the gate itself would need a real "does node_modules actually have
      these packages" check, not just a package.json presence check) but unblocked directly for
      verification by running a real `npm install` in the sandbox, which is what let the
      **actual, intended fix** get a genuine live demonstration.
    - **Real, live verification, no mocks** (isolated backend :8090 / frontend :5199, same shared
      MongoDB Atlas cluster, real Finodil `feature_917b691e`): downloaded the real combined zip
      and confirmed it contains both real generated Next.js code (`app/api`, `lib/`, etc.) and
      both `_QA_REPORT/qa_report.json`/`.md` files pulled from the feature's real latest QA
      report. Confirmed via `getComputedStyle` (through a real Playwright screenshot) that the
      "QA"/model pills now render `bg: rgb(255,255,255)` with a `border: rgb(212,212,212)`,
      clearly distinct from the composer's `bg: rgb(245,245,245)`. Triggered a real QA run before
      the `npm install` fix -- confirmed the report showed "0 passed, 0 failed, 1 skipped" with
      the honest tier-3 note (Jest genuinely produced no results, the real environmental bug
      above); after installing the real jest/babel deps in the sandbox, re-triggered the same
      real QA run -- confirmed the report now reads **"All tests passed. 1 test(s) written -- 1
      passed, 0 failed, 0 skipped"** with a green "Passed" badge, directly reproducing and fixing
      the user's originally-reported symptom end-to-end. This real v5 (broken)/v6 (fixed) QA
      report history is left in place on the real Finodil feature as genuine verification
      evidence, matching this project's own established convention.

97. **Fixed a real, reported bug: running Architecture Agent for the first time on a feature (in
    the "Retail Store" project) produced 2 artifact versions with identical content.**
    Investigated via 2 parallel Explore agents (frontend trigger paths; backend save/version
    mechanisms). Backend confirmed structurally sound: `_save_architecture_artifacts` is called
    exactly once per real `run()`/`run_stream()` invocation, `graph_orchestrator_service` has no
    real `architecture` node (a pure pass-through, per deviation #12/M6's own docstring) so it
    cannot race a manual API-triggered run, and no event/webhook mechanism anywhere could trigger
    a second call. **Root cause, confirmed by reading the code, not guessed**:
    `frontend/src/components/pipeline/ArchitectureRunForm.jsx` ("deep exploration mode," reachable
    from `ArchitectureAgentChat.jsx`'s own toggle) instantiated its OWN, independent
    `useRunArchitecture(featureId)` mutation hitting plain `POST /architecture/run` -- completely
    separate from the shared `ArchitectureAgentFlowContext`'s `runStream` mutation
    (`POST /architecture/run/stream`) that `ResultTab.jsx`'s Enhanced-SRS-approval auto-continue
    (`APPROVE_CONTINUATION_BY_STAGE.domain`, `autoRun: true`) fires. Neither mutation instance had
    any visibility into the other's pending state -- the exact same "two independent
    `useMutation()` instances for one real action" bug class already found and fixed for UI/UX
    Agent (item 61) and Security Agent (item 89), just never applied to Architecture Agent's own
    plain-run path. If a human had the exploration form open (or had just submitted it) at the
    moment the Enhanced SRS was approved, both real HTTP requests fired, each independently
    calling `_save_architecture_artifacts` -- one call, but twice, is exactly "2 versions, same
    content."
    - **Fix**: moved the plain-run mutation into `useArchitectureAgentFlow.js` itself
      (`plainRunMutation`/`handlePlainRun`/`stopPlainRun`), shared via the existing
      `ArchitectureAgentFlowContext` -- `ArchitectureRunForm.jsx` now consumes it from context
      instead of instantiating its own copy, so every trigger surface observes the SAME
      `isPending`. New combined `anyRunPending` in `ArchitectureAgentChat.jsx`
      (`activeStream.isPending || (!hasOutput && plainRunMutation.isPending)`) gates the "Start
      Architecture Agent now" button/toggle-link and the composer's submit/pending state -- the
      form itself deliberately stays visible while its own request is pending (showing "Generating
      Architecture Plan..."), and additionally checks the STREAMING mutation's own `isPending` via
      context before allowing its own submit, so a stream started elsewhere (e.g. the auto
      -continue) blocks the form too, with a visible "Architecture Agent is already running..."
      note. `ResultTab.jsx`'s two auto-run call sites (`handleConfirmedApprove`'s
      domain->architecture branch, and `handleConfirmedSkipEnhancement`) now both check a new
      `architectureRunAlreadyInFlight` (folding in `plainRunMutation.isPending` too) before firing
      `handleRunArchitectureStream`, so the reverse race (approve arrives while the form's plain
      request is already running) is blocked at the source as well. `isArchitectureRunning` in
      `ResultTab.jsx` also now reflects `plainRunMutation.isPending`, so the Result panel's live
      view correctly shows "generating" for the deep-exploration path too, not just the streaming
      one.
    - `npm run build` clean (1365 modules). This was a pure frontend-only fix -- no backend changes
      needed, matching the Explore agents' own conclusion that the backend has no duplicate-save
      mechanism.

98. **Architecture Agent: fixed real Use Case Diagram modeling problems a supervisor review
    flagged on the real "Add & List Items" feature (Retail Store project) -- a garbled actor name
    with an unclear `<<system>>` stereotype, an ambiguous conjunctive use case name, and (per
    direct user steer) actor over-inclusion.** Direct user report, quoting the real reviewer
    feedback verbatim: an actor named `"An Image Hosting Solution To Store Uploaded Images."`
    using `<<system>>` ("not the clearest way to represent an external system"), and a use case
    named `"Add List Items"` (should be two separate use cases, since add and list are distinct
    capabilities). The user also asked for full FR coverage while staying simple, and explicitly
    redirected the stereotype discussion toward a more fundamental concern via AskUserQuestion:
    **"Do not add unnecessary things to the usecase diagram. Add only necessary actors."**
    Investigated via 3 parallel Explore agents (actor naming/stereotype code paths; conjunctive
    use-case naming + FR-coverage mechanisms; the real live data needed for the reset) plus a
    Plan-agent design-review pass that corrected scope on two points and surfaced one real
    structural gap the initial draft missed.
    - **Root causes, confirmed by reading the code directly**: `usecase_modeler.py::_build_actors`
      trusted the LLM's actor names almost verbatim (`_extract_name` + `_title_case` only) with
      no cleanup analogous to `_clean_use_case_name`; `usecase_validator.py::_validate_actors` had
      zero name-quality checks; `prompt.py` told the LLM what NOT to name an actor (a technical
      component) but gave zero positive guidance on actor name FORM, and nothing distinguished a
      real necessary actor from a noun merely mentioned in an FR's description. The `<<system>>`
      stereotype was hardcoded in exactly one rendering location (`usecase_builder.py`) and named
      in prose in exactly one prompt tier (the other three tiers only ever describe the
      `stereotype` field value, never the literal rendered tag). `prompt.py`'s Use Case
      Specification Rules had strong anti-fragmentation guidance (don't split one action into
      micro-steps) and anti-near-duplicate guidance (merge same-behavior-different-name entries)
      but zero rule against the OPPOSITE failure -- merging two genuinely distinct capabilities
      into one conjunctive name. `usecase_validator.py::_validate_use_case_name_quality` only
      catches cut-sentence fragments (articles/pronouns) -- "Add List Items" tokenizes to
      `{add, list, items}`, none of which trip it. FR/AC/VR coverage was already fully solved
      (`_validate_traceability` unconditionally enforces it, and the full FR list is already sent
      to the LLM at every generation tier) -- no new coverage mechanism was needed.
    - **A real, structural latent risk found by the design-review pass, not part of the initial
      draft**: `_build_use_cases_from_specification` unconditionally demoted any SECOND
      `main`-typed use case to `included`, and `_build_relationships` then drew a false
      `<<include>>` edge from the sole remaining main to it. Once a new anti-conjunction rule
      teaches the LLM to correctly mark "Add Item" and "List Items" as two independent
      capabilities, a model might reasonably mark BOTH as `type: "main"` -- and the old code would
      force a semantically wrong `<<include>>` edge claiming listing always happens as part of
      adding (the same "not the clearest way to represent" complaint, just relocated).
    - **Fix -- actor necessity (primary, per direct user steer)**: new prompt rule (all 4 tiers:
      combined/agentic/focused-fallback/repair) stating an actor must be a REAL, NECESSARY,
      DISTINCT participant -- a human role, or a genuine external system named in the SRS's own
      `api_expectations`/`dependencies` -- never a noun merely mentioned in passing inside an FR's
      description, with the real bad example stated directly (don't invent an "Image Hosting
      Service" actor just because an FR mentions storing uploaded images, unless a real
      third-party integration is named). Deliberately prompt-level only, not a new deterministic
      validator check -- actor necessity is a semantic judgment call, and a rigid syntactic check
      here would risk real false positives, matching this codebase's own established restraint
      around not over-engineering checks for judgment-based quality.
    - **Fix -- actor name quality**: new `usecase_modeler.py::_clean_actor_name` (strips trailing
      sentence punctuation, strips `NAME_FILLER_WORDS`, caps at 4 words, title-cases -- simpler
      than `_clean_use_case_name`, no verb-first forcing since an actor is a noun phrase) applied
      to every actor source (LLM specification, SRS `user_roles` fallback, SDS `context_view`
      fallback). New `usecase_validator.py::_validate_actor_name_quality` (reuses `FRAGMENT_WORDS`,
      flags >5 words, flags a name ending in `.`/`!`/`?`) wired into `validate()`, feeding the
      existing `_repair_usecase_specification` retry loop automatically with no repair-prompt
      change functionally required (confirmed: `build_usecase_repair_prompt` already interpolates
      the exact validation-error string plus the full prior specification) -- an optional
      reinforcing repair-prompt bullet was still added for consistency.
    - **Fix -- stereotype clarity, minimal footprint**: `usecase_builder.py`'s rendered stereotype
      string changed from `<<system>>` to `<<external system>>` (one string literal) plus the one
      prompt tier that named the literal tag in prose; the other three tiers needed no change
      (confirmed they only ever describe the `stereotype` field value).
    - **Fix -- conjunctive use-case naming**: new prompt rule placed immediately adjacent to (not
      near the anti-fragmentation rule, to avoid blurring "don't split" with "don't merge") the
      existing near-duplicate-merge instruction, with an explicit inline contrast sentence and the
      real bad/good example pair ("Add List Items" -> "Add Item" + "List Items"). New
      `usecase_validator.py::_validate_no_conjoined_capabilities` flags a single use case name
      containing 2+ verbs from a SHORT curated `DISTINCT_CAPABILITY_VERBS` set (`add/create`,
      `list/view/browse`, `update/edit`, `delete/remove` -- deliberately narrow per the design
      review: broader verbs like search/filter/export/approve legitimately co-occur in one real
      name, e.g. "Export Filtered Report," and would false-positive). New guard in
      `usecase_modeler.py::_dedupe_by_shared_requirements`: two entries citing an identical
      `related_requirements` set are NOT merged if their names start with a DIFFERENT curated verb
      (the real, confirmed mechanism that could silently fuse "Add Item"/"List Items" if the SRS
      only wrote one combined FR for both) -- confirmed safe against the existing test suite (the
      one real test exercising this path merges two entries both starting with "Initiate," not two
      different curated verbs); the other two merge passes (exact-name, name-similarity) are
      untouched.
    - **Fix -- the "second main" structural gap**: relaxed the demotion logic so two `main`-typed
      entries are only collapsed when their `related_requirements` sets overlap or either is empty
      (the "LLM sloppily double-marked one thing as main" case) -- two entries with genuinely
      DISJOINT `related_requirements` are kept as independent siblings with no invented
      `<<include>>`/`<<extend>>` edge between them. New `_closest_main_use_case` helper: when
      multiple main use cases exist, an included/extension use case's include/extend edge now
      connects to whichever main it shares the most `related_requirements` overlap with (falling
      back to the first main only when it shares none) -- previously hardcoded to always connect
      to `main_use_cases[0]`. The pre-existing actor-association logic
      (`_build_relationships`'s per-use-case `participating_actors` loop) already correctly
      handles multiple main use cases with zero changes needed, confirmed by reading it.
    - Tests: `tests/test_architecture_usecase_modeler.py` (+7: actor cleanup for both the real
      garbled name and a clean name, cleanup applied to the SRS `user_roles` fallback source too,
      the merge guard both blocking a false merge and preserving the real legitimate one, disjoint
      vs. overlapping "second main" demotion behavior, closest-main relationship assignment; one
      pre-existing test -- `test_folds_extra_main_entries_into_included` -- rewritten to reflect
      the new, correct behavior, since it directly asserted the old bug's own demotion-always
      logic). `tests/test_architecture_usecase_validator_quality.py` (+5: the real garbled actor
      name flagged on both signals, clean actor names not flagged, an overly-long actor name
      flagged, the real "Add List Items" conjunction flagged, correctly-separated names and a
      same-capability multi-word name both NOT flagged).
      `tests/test_architecture_usecase_builder.py` (1 pre-existing test updated for the new
      `<<external system>>` rendered tag). Full architecture-tagged suite: **270 passed**, zero
      regressions. Full non-Docker-dependent backend suite: **1124 passed**.
    - **Real, live verification against the real feature's real approved Enhanced SRS** (read-only,
      no Mongo writes): fed a specification reproducing the EXACT real reported bug shape (the
      real garbled actor name + "Add List Items") through the real, unmocked modeler/validator/
      builder using this feature's own real FR ids -- confirmed the actor cleaned to "Image
      Hosting Solution To" (no longer a raw sentence with a trailing period; not a perfect name,
      an honest, deliberate limitation of the cosmetic-cleanup layer, since the actual, more
      complete defense is the strengthened prompt now discouraging the LLM from producing this
      shape at all) rendered with `<<external system>>`, and confirmed the validator correctly
      raised on "Add List Items" (`"conjoins multiple distinct capabilities... split into separate
      use cases, one per capability (add, list)"`) -- exactly the signal that triggers a real
      repair retry. Separately fed a correctly-separated specification ("Add Item"/FR-001, "List
      Items"/FR-002, an included "View Item Details" citing an unrelated FR) through the same real
      pipeline: confirmed both survived as independent `main` use cases with no invented edge
      between them, and confirmed the included use case's `<<include>>` edge correctly fell back
      to the first main (zero requirement overlap with either, as designed).
    - **Real, live data reset** (direct user request, explicit part of the plan): deleted all 16
      existing Architecture-related artifact records (8 `(artifact_type, version)` groups --
      `architecture_plan`/`use_case_diagram`/`sequence_diagram`/`class_diagram` v1 and v2) for the
      real feature `feature_bd2b44a1` ("Add & List Items," project `proj_e373bcd3` "Retail Store")
      via `artifact_service.delete_artifact`, run only after the fix was implemented and verified
      above -- confirmed safe beforehand (none of the 16 records were `approved`, so no
      `revoke_approval` step was needed; no active/paused LangGraph run existed for this feature).
      Confirmed afterward: zero architecture-related records remain, while the feature's approved
      SRS (v1) and approved Enhanced SRS (v4) are untouched -- the feature is now back to exactly
      "Domain Agent approved, Architecture Agent never run," ready for the user to re-trigger
      Architecture Agent fresh from Domain Agent's approval, per their own explicit request.

99. **Fixed the real `.env.local`-corruption bug for real, plus made "the Coder Agent actually
    uses the real MongoDB URI" a genuinely verified guarantee, plus a per-agent-chat AI
    disclaimer.** Direct user request, three parts, after a prior diagnosis turn: the Coder Agent
    must use the provided MongoDB URI to establish the database connection for real, instead of
    silently falling back to fake data; and every agent's chat window needs a small "AI can make
    mistakes" notice. Investigated via 3 parallel Explore agents (URI-detection scope + a
    schema field already meant to fix this; the generated code's real DB-connection wiring and
    what verification does/doesn't check; the frontend chat-component structure) plus a
    Plan-agent design-review pass.
    - **Part A -- the actual corruption fix**: root cause (already diagnosed in the prior turn):
      `env_uri.py`'s `extract_mongodb_uri` runs unconditionally on every `revision_comment`
      reaching `CoderAgent.revise()`/`revise_stream()`, including one machine-built by the "Fix
      Vulnerabilities" flow that quotes a security finding's evidence text verbatim -- for a real
      CWE-798 finding, that text contained the Coder Agent's own LLM-invented fake
      `FALLBACK_MONGODB_URI` credential, which got matched and silently overwrote a human's real,
      correctly-provided `.env.local` value. **The fix, confirmed to need zero schema changes**:
      `CoderAgentReviseRequest.revised_by` already exists and was already correctly set to
      `"security_agent_report"`/`"qa_agent_report"` by all 3 real frontend trigger points
      (`SecurityDecisionDialog.jsx`, `ResultTab.jsx`'s `handleConfirmedFixVulnerabilities`,
      `QaReportView.jsx`'s `handleSendToCoder`) -- it was simply never consulted by the
      URI-detection logic. New `env_uri.py::is_machine_generated_revision(revised_by)` (checked
      against a small `MACHINE_GENERATED_REVISION_SOURCES` set) gates the `write_env_local` call
      in `agent.py`'s `revise()`/`revise_stream()` ONLY (`run()`/`run_stream()` are never
      reachable from this flow, since it requires an existing Coder Agent output to already
      exist) -- when the comment is machine-generated, it's left completely untouched (no write,
      no strip), since the quoted URI is necessary vulnerability-description context the planner
      needs to see in full, not a real secret. Also fixed a secondary regex quirk found while
      diagnosing: `_TRAILING_PUNCTUATION` didn't include a backtick, so a URI captured from
      inside a markdown code span (ending in `` ";` ``) kept the trailing backtick uncleaned.
    - **Part B -- closing the deeper "never actually verified" gap**: confirmed by reading
      `verify.py`/`db_fallback_checker.py`/`functional_checker.py`/`sandbox_service.py` directly
      that `lib/mongodb.ts`'s scaffold was already correct (real `mongoose.connect
      (process.env.MONGODB_URI)` when set, no fake behavior baked in), and that the sandbox
      bind-mounts the real workspace directory -- meaning a correctly-saved `.env.local` genuinely
      reaches `next build`/`next start` during `verify()` (Next.js reads `.env.local` from disk,
      not from injected OS env vars). The real gap: `functional_checker.check_crud_functionality`
      already does exactly the right thing to catch "always serves fake data" (POSTs a payload
      with a distinctive marker, GETs, checks the marker reappears) but was wired as purely
      informational in `verify.py` -- a route that always returns static seed data regardless of
      connection state passed verification cleanly. Fixed by conditionally, narrowly hard-gating
      it: `functional_checker.check_crud_functionality` now tags each failure with an explicit
      `"reason"` (`"not_persisted"` vs `"post_rejected"`, instead of output-text parsing) so
      `verify.py`'s `_build_crud_functional_step` can hard-gate ONLY the `"not_persisted"` case
      AND only when `workspace_service.read_env_local(project_id).get("MONGODB_URI")` shows a
      real URI is configured -- a non-2xx `"post_rejected"` response stays informational even
      then (a real, correct validation rule rejecting this check's own heuristically-guessed
      payload is a plausible non-bug outcome, not evidence of fake data; this narrowing was a
      direct Plan-agent design-review refinement over the original "hard-gate any failure" draft).
      When no real URI is configured, behavior is completely unchanged (informational only) --
      seed data is the correct, designed behavior there. New prompt rule (right after the
      existing "never touch `lib/mongodb.ts`" bullet in `CODER_AGENT_SYSTEM_PROMPT`, inherited
      automatically by `BATCH_CODE_GENERATOR_SYSTEM_PROMPT` via the existing `"Tool usage:"`
      string-split): `lib/mongodb.ts` is the ONLY connection mechanism in the project -- never
      invent a second hardcoded connection-string constant anywhere, even as a placeholder. New
      standalone module `hardcoded_secret_checker.py` (a new file, not folded into
      `db_fallback_checker.py` -- "is the null-guard fallback well-formed" and "is there a leaked/
      invented credential" are different concerns, mirroring the existing precedent of
      `security_finding_coverage_checker.py` being its own file): `scan_for_hardcoded_mongodb_uri`
      scans every planned, non-deleted file (any type, excluding `.env*` by basename -- confirmed
      via the design review that `.env.example` is the ONE legitimate scaffold file with a real
      placeholder `mongodb://` literal; every other scaffold file, including `lib/mongodb.ts`
      itself, has none) for a literal `mongodb(?:\+srv)?://` substring -- an unconditional hard
      gate in `verify.py` (not tied to whether a real URI is configured, since a hardcoded
      credential in source is always wrong). This directly targets and would have caught the
      exact root-cause pattern that produced the original Security Agent finding in the first
      place, closing the loop that started this whole investigation.
    - **Part C -- AI disclaimer**: confirmed all 7 real per-stage chat components
      (`RequirementConversationChat.jsx`, `DomainAgentChat.jsx`, `ArchitectureAgentChat.jsx`,
      `UiuxAgentChat.jsx`, `CoderAgentChat.jsx`, `SecurityAgentChat.jsx`, `QaAgentChat.jsx`)
      render the same shared `ChatComposerBox.jsx` -- a real, confirmed single choke point (per
      that component's own docstring: "there is only one place this markup exists, so it can't
      drift"). Added one `<p className="text-[11px] text-gray-500 dark:text-gray-400 text-center
      select-none">AI can make mistakes. Check important information.</p>` as the last element
      inside the composer's rounded card -- one file, one change, automatically covers every
      stage including `RequirementConversationChat.jsx`'s two separate call sites (pre-SRS/
      post-SRS). `select-none` (a genuinely new pattern for this codebase, confirmed via the
      design review no existing precedent uses it) makes it non-selectable/non-copyable, per the
      user's own explicit "must not be able to copy that" requirement.
    - Tests: `tests/test_coder_env_uri.py` (+3: the backtick-trailing fix, `is_machine_generated_
      revision` true for both known sources and false for a real human/None/empty),
      `tests/test_coder_agent_revise.py` (+1: end-to-end through the real `revise()` method with
      the exact real historical finding text -- confirms `write_env_local` is never called and the
      full finding text, fake URI included, still reaches the planner untouched),
      `tests/test_coder_functional_checker.py` (updated: both existing failure tests now assert
      the new `reason` field), new `tests/test_coder_hardcoded_secret_checker.py` (6: the real
      confirmed `FALLBACK_MONGODB_URI` shape caught, the real scaffold `lib/mongodb.ts` and a
      clean route never flagged, `.env.example`'s legitimate placeholder excluded, deleted/
      unplanned files never scanned), new `tests/test_coder_verify_mongodb_gates.py` (8: the
      conditional crud-gate's every branch -- no URI/not_persisted/post_rejected/passed/no-
      results/default-false -- plus the hardcoded-secret step's pass/fail wrapping). Full backend
      suite (excluding the pre-existing Docker-dependent files) run clean, zero regressions.
      `npm run build` clean.

## Where to look

- Full build spec (read this first, in order, before any new milestone): `instructions .md`
- This file: durable cross-milestone memory, updated at the end of each milestone
- `C:\Users\ASUS\.claude\plans\soft-petting-star.md`: scratch, current-milestone-only plan
