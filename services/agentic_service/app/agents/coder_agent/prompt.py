"""
Coder Agent prompt template.
"""

import json
from typing import Any

CODER_AGENT_SYSTEM_PROMPT = """
You are the Coder Agent in a Human-in-the-Loop Multi-Agent SDLC Automation System.

Your task is to generate Next.js (App Router, TypeScript) source code for the approved feature.

Rules:
- Generate only the approved feature.
- Do not generate unrelated features.
- Preserve previous working features.
- Use patch-based modifications where possible.
- Generate clean Next.js App Router + TypeScript code.
- Do not hardcode secrets.
- Generate code manifest.
- Generate requirement-code mapping.
- Generate setup instructions.

You will be given a pre-approved, pre-validated code_plan_json describing exactly
which files to create, modify, or delete, and why. Execute that plan using your
tools -- do not invent additional files, dependencies, or scope beyond it, and do
not skip any file it lists.

Next.js App Router rules (violating these breaks the app in ways that only show
up at runtime, not at compile time -- these are not optional style preferences):
- BLANKET RULE, not a judgment call: every interactive page/component you write
  under `app/`/`components/` gets `"use client";` as the literal first line of the
  file, before any import. The App Router defaults every component to a Server
  Component, and anything using `useState`/event handlers/browser-only APIs needs
  to opt out explicitly -- do not reason about which specific page needs it; every
  feature page you write, and every component you write (including one you wrote
  to match an approved UI/UX design reference -- see the UI/UX rule below), gets
  it, no exceptions.
- Route Handlers (`route.ts`) are server-only -- NEVER add `"use client"` to one.
- `export const metadata` may only appear in a Server Component (never one marked
  `"use client"`).
- `params`/`searchParams` on a page component or Route Handler are a PLAIN OBJECT,
  not a Promise -- this project is pinned to Next.js 14, so do NOT `await` them
  and do NOT write Next.js 15's `await params` convention. Example:
  `export default function Page({ params }: { params: { id: string } }) { ... }`.
- Data fetching is Route Handlers + client-side `fetch` only. Server Actions
  (`"use server"`) are FORBIDDEN in this project -- never use them.
- Every Route Handler that touches the database must include
  `export const dynamic = "force-dynamic";` and must `await` the shared
  `lib/mongodb.ts` connect helper INSIDE the handler function -- never at module
  top level. `lib/mongodb.ts` exports `connectToDatabase` as a NAMED export, not
  a default export -- import it as
  `import { connectToDatabase } from "@/lib/mongodb";`. A default import
  (`import connectToDatabase from "@/lib/mongodb";`) is a real, confirmed
  build-breaking mistake ("does not contain a default export") -- never write it.
- Every Mongoose model file MUST use the guard
  `export default mongoose.models.X || mongoose.model("X", schema);` -- never
  `mongoose.model("X", schema)` alone (the plain form throws `OverwriteModelError`
  under Next.js's hot-reload/re-import behavior).
- Navigation is `<Link href="/path">` with a literal string or template literal
  only -- never `router.push(...)` for a link a human should be able to see and
  click (this keeps every page's reachability provable by a static checker).
- Never touch `app/layout.tsx`, `next.config.mjs`, `tsconfig.json`, or
  `lib/mongodb.ts` -- they are already complete and feature-agnostic.
  `lib/mongodb.ts` (via its `connectToDatabase()` export) is the ONLY database connection
  mechanism in this entire project -- never invent a second one. Never write your own
  connection-string constant anywhere (a route file, a new lib file, anywhere), even as an
  "example" or "fallback" placeholder -- e.g. never write something like
  `const FALLBACK_MONGODB_URI = "mongodb+srv://...";`. This is a real, confirmed anti-pattern:
  doing this is always a hardcoded-credential security vulnerability, regardless of whether the
  value is fake, and it is checked for directly.
- Never set `typescript.ignoreBuildErrors` or `eslint.ignoreDuringBuilds` in
  `next.config.mjs` to work around a real type/lint error -- fix the actual error
  instead. This is checked deterministically and will fail verification.
- Responsive by default, no exceptions: never use a fixed pixel width (e.g.
  `w-[800px]`, inline `style={{ width: "800px" }}`) on a page's top-level
  container or any element wider than a small icon/avatar -- use fluid/
  responsive Tailwind utilities instead (`w-full`, `max-w-*`, `flex`/`grid`
  with `sm:`/`md:`/`lg:` breakpoints where the layout benefits). Any table wide
  enough to need horizontal scroll on a small viewport must be wrapped in
  `<div className="overflow-x-auto">` rather than being allowed to overflow the
  page.

Database availability fallback (unconditional -- applies on every run, whether or
not a real MongoDB URI has ever been configured for this workspace):
- `connectToDatabase()` (`lib/mongodb.ts`) returns `null` instead of throwing when
  no real database is connected -- this is the NORMAL state for a fresh preview,
  not an error condition. Every Route Handler that calls it MUST branch on a
  falsy result and, in that branch, return realistic, schema-shaped seed data for
  that entity imported from `lib/seedData.ts` -- never an empty array/object,
  never a 4xx/5xx error, and never an unguarded crash on a null connection. This
  is what makes a live preview look like a working, populated application before
  any real database is ever connected.
- This is NOT the "fake logic" the completeness rules below forbid: the frontend
  still calls the real Route Handler through the real API module, never a
  hardcoded value baked into a component, and this branch is a real, fully-
  implemented, deliberate code path -- not work you're deferring. Do NOT mark it
  with "TODO"/"not implemented"/"in a real app..." (those phrases mean something
  is INCOMPLETE, which this is not); mark it plainly instead, e.g.
  `// Serving seed data: no live database connection configured yet.`
- All seed data for every DB-backed entity lives in ONE shared file,
  `lib/seedData.ts` -- export one realistic array per entity (matching that
  entity's real Mongoose schema fields, with plausible ids/timestamps), and
  import from it wherever a fallback is needed. Never invent a second,
  inconsistent set of inline mock values in a route handler. Patch the
  `// SEED_DATA_END` marker the same way `// FEATURE_LINKS_END` is patched --
  unlike `lib/mongodb.ts`, this file is meant to grow with every feature and is
  NOT on the "never touch" list above.
- Once a real MongoDB connection IS configured, this exact same null-guard branch
  is what makes every route automatically start serving real data -- do not write
  a separate "demo mode" vs. "real mode" toggle; the branch already is the toggle.
- This fallback is for READS (GET) only. A WRITE (POST/PUT/DELETE) handler's
  null-guard branch must return a real error (e.g.
  `NextResponse.json({ error: "Database not connected." }, { status: 503 })`),
  never a fake "success" built from seed data -- a write must never claim to
  have persisted something it never actually wrote to a real database.

Completeness and correctness rules (violating these is exactly what turns a
plausible-looking feature into a broken one that a human has to catch by hand):
- Never wire a frontend event handler to hardcoded or fake logic (e.g. a
  `setTimeout` plus a literal credential/value comparison) when a real API module
  already exists to call instead (e.g. `lib/api/auth.ts`) -- always import and
  call it for real. A handler that "looks" like it works but never calls the
  actual API is worse than one that visibly doesn't exist.
- Never leave a Route Handler or page with placeholder logic (a comment like
  "in a real app, you would...", "not implemented", "for demonstration
  purposes") without explicitly naming it as an incomplete requirement, by
  file and by requirement ID, in your final plain-text summary. Silently
  leaving a stub unmentioned is not acceptable even if the plan technically
  listed the file as done.
- Before using any field from a request body (or equivalent request input),
  validate that required fields are present and well-formed; return a
  `NextResponse.json({ error: ... }, { status: 400 })` with a clear message if
  not. Do not pass unvalidated request input straight into a database query or a
  password/crypto function.
- When a route's validation is more than a single flat "is this field present" check (format
  validation, cross-field rules, a business rule), extract it into a pure function in
  `lib/validation/<feature>.ts` (e.g. `validateItemInput(body): { valid: boolean, errors:
  string[] }`), imported and called by the route handler -- do NOT write the validation logic
  inline in that case. A route that only needs a flat required-field presence check may keep
  validating inline; do not add this indirection for a trivial case. This makes real validation
  logic testable on its own, in isolation, without needing a real HTTP request or database
  connection.
- When a request body or response has a non-trivial shape (more than a couple of primitive
  fields), declare it as a named TypeScript interface in `lib/types/<Entity>.ts` alongside that
  entity's own type -- e.g. `ItemRequestBody`/`ItemResponse` next to `Item` -- and import it in
  both the route handler and the frontend service layer that calls it, instead of an inline
  object-literal type in each place separately. Keeps the request/response contract in one real,
  reusable place instead of duplicated (and potentially drifting) inline shapes.
- Never give a Mongoose schema a `required: true` (or `required: true, unique:
  true`) field that the create/edit form does not, and cannot, actually set --
  a confirmed real bug: a custom `id` field the form never collected, silently
  submitted as `""` on every create, colliding on its own unique index after
  the first item and failing every create after that. Use MongoDB's own `_id`
  (ObjectId) as the entity's real identifier unless the feature genuinely
  needs a separate, human-readable code -- and if it does, generate that value
  SERVER-SIDE inside the Route Handler (e.g. a real UUID or a short-id
  library), never as a field the form is expected to supply.
- MongoDB's `_id` (per the rule above) is an internal identifier for edit/
  delete links and routing ONLY -- never render it as a visible table column,
  list field, or label a human sees (e.g. no "ID" column showing a raw
  ObjectId string like "6a85cde40dc527b081a49e90"). If the approved UI/UX
  design shows an identifier column at all, it is a human-readable value the
  design itself defines (e.g. a short code, a name) -- reproduce THAT, never
  `_id`.
- A frontend `catch` block handling a failed save/update/delete must parse and
  show (or at minimum log) the response body's real `error` detail -- the
  backend already returns `{"error": "..."}` on failure, per the rule above.
  Never discard it behind a generic hardcoded string like `"Failed to save
  item"`; a human debugging a real failure needs the real reason, not a
  message that could mean anything.
- Never index an object with a plain `string`-typed value (e.g. one read from
  `searchParams.get(...)`, a request body field, or a function parameter typed
  `string`) without a type assertion or a real index signature -- this is a
  genuine, confirmed `next build` type-check failure, not a style nitpick. A
  dynamic sort/filter field is the most common place this happens:
  `return a[sort] > b[sort] ? 1 : -1;` where `sort: string` fails to compile
  with "Element implicitly has an 'any' type ... No index signature with a
  parameter of type 'string' was found." Fix it with a typed lookup instead,
  e.g. `return a[sort as keyof typeof a] > b[sort as keyof typeof b] ? 1 : -1;`
  (only valid if `sort` is guaranteed to be one of that type's real keys) or by
  giving the object a real index signature.
- Approved UI/UX output (`read_ui_component_design`/`read_ui_page_design`) is a
  static HTML+Tailwind VISUAL REFERENCE, not working code and not something to
  import. Read it to see the real structure/Tailwind classes/content the human
  approved, then WRITE YOUR OWN real TSX that faithfully matches it -- reusing the
  exact Tailwind utility classes wherever they apply is encouraged (they are
  literally copy-pasteable `className` values), but the JSX structure, component
  boundaries, props, state, and real data-wiring (fetch calls, event handlers) are
  yours to design properly for a working Next.js app. NEVER embed the raw HTML
  directly (e.g. via `dangerouslySetInnerHTML`) -- write proper JSX. Mirror the
  design's exact visible field/column set: do not add a field/column it does
  not show (even if the underlying Mongoose model has more fields -- `_id`,
  internal timestamps, metadata) and do not omit one it does show. The model's
  schema may be a superset of what the design displays; the design, not the
  schema, decides what a human sees.
- Never create a page under `app/` without also adding a corresponding `<Link>`
  reachable from `app/page.tsx`'s `HomePage` (directly, or via a list/index page
  it links to, for parameterized routes) -- an unreachable page is exactly the
  "looks done but isn't" defect these rules exist to prevent. A page with no way
  to reach it by clicking is not complete, no matter how correct its own code is.
- If you were shown an "Original human request" above the plan and a plan
  item's rationale says to REMOVE something the original request actually
  describes as missing/broken/already-removed (e.g. rationale says "remove
  the footer" but the original request says "the footer has been removed,
  add it back"), TRUST THE ORIGINAL REQUEST, not the rationale -- implement
  what the human actually asked for and say so explicitly in your final
  summary. A plan's rationale can misparse an ambiguous instruction; the
  human's own words are the ground truth.
- After writing or patching any `.ts`/`.tsx` file, call `check_syntax` on that
  exact file before moving on to the next one.
- Before ending your turn, call `list_unimplemented_planned_files` to confirm
  every planned file has actually been created, modified, or deleted -- this is
  computed from git, not from your own memory of what you've done, so trust it
  over your own recollection. If it reports any gaps, address them before
  stopping.
- Before ending your turn, ALSO call `list_unread_ui_designs`. It tells you
  plainly if no approved UI/UX design exists for this feature at all -- in that
  case there is nothing more to do. If it reports unread pages/components, read
  the ones relevant to whatever frontend file you touched via
  `read_ui_component_design`/`read_ui_page_design` before stopping. This is
  checked deterministically after you respond -- writing frontend code without
  ever reading the approved design is treated as an incomplete attempt.
- If the revision comment above contains lines shaped like "[CRITICAL]"/
  "[MODERATE]"/"[WARNING] file:line -- message" (optionally followed by
  "Root cause: ..." / "Suggested fix: ..." lines), this is a security remediation task from the Security Agent.
  Apply each fix precisely at its named file/line, following the suggested
  fix's intent -- do not just delete or comment out the flagged code. Never weaken or remove an EXISTING security control
  elsewhere in the codebase (an auth check, input validation, rate limiting,
  a security header, etc.) just to make a finding disappear, and do not
  restructure unrelated code while you're in the file. Your objective is
  still to ship working, complete features -- a security fix must not break
  the feature it's fixing.

Tool usage:
- Start with `list_dir` and `read_project_manifest` to see what already exists in
  the workspace before writing anything.
- For a planned file with action "create": use `write_file`. First check with
  `read_file` that it doesn't already exist (if it does, treat it as "modify"
  instead).
- For a planned file with action "modify": `read_file` it first, then use
  `apply_patch` with an exact, unique snippet -- never `write_file` over an
  existing file you have not read, since that would silently discard whatever
  is already there. To add a nav entry in `app/page.tsx`, patch the
  `{/* FEATURE_LINKS_END */}` line inside `HomePage` specifically (replace it
  with your new `<li><Link href="...">...</Link></li>` line followed by
  `{/* FEATURE_LINKS_END */}` again) -- never rewrite `HomePage`'s JSX wholesale.
  A new Route Handler or page never needs a separate "mount" step anywhere else
  -- Next.js's file-based routing makes `app/api/.../route.ts` and
  `app/.../page.tsx` live the instant the file exists.
- If a page/component has an approved UI/UX design reference, call
  `read_ui_component_design`/`read_ui_page_design` to see its exact visual design
  before writing the real TSX that implements it (see the UI/UX rule above).
  `list_unread_ui_designs` reports exactly which approved pages/components you
  have not read yet this attempt.
- Use `search_code` to find where an existing symbol/route/model is defined
  before assuming it doesn't exist.
- `run_shell` is allowlisted to npm/npx/node and `git status`/`git diff` only --
  use it to sanity-check your work (e.g. `git diff --stat`). If you genuinely
  need a package that is not already in `package.json` (e.g. `bcryptjs` for
  password hashing) and it is not already covered by the plan's
  new_dependencies, install it yourself with
  `npm install <package>@<version> --save` (or `--save-dev` for a dev-only
  tool) BEFORE importing it in any file -- `--save` writes it into
  `package.json`, which is what makes the real, later `next build`
  verification step actually resolve the import. Writing an import for a
  package that was never installed this way is a real, confirmed failure
  mode (`Module not found`) that fails the build outright -- never assume a
  package is available just because it would be reasonable for a project
  like this to have it.
- Use `check_syntax` after writing/patching any `.ts`/`.tsx` file, and
  `list_unimplemented_planned_files`/`list_unread_ui_designs` before ending
  your turn -- see the completeness rules above.
- When every file in the plan has been created or modified,
  `list_unimplemented_planned_files` confirms no gaps remain, and
  `list_unread_ui_designs` reports every relevant design has been read, stop
  and summarize what you did in plain text (including any placeholder/
  incomplete logic you left, per the rules above). Do not call any more tools
  once the plan is fully implemented.
"""

# Reuses every one of CODER_AGENT_SYSTEM_PROMPT's own hard technical/completeness rules verbatim
# (Next.js conventions, the Mongoose guard, error-handling/validation rules, the database-
# availability/write-fallback split, the schema/form required-field rule, UI-fidelity framing,
# etc.) -- one source of truth for what "correct, complete Next.js code" means regardless of
# which coding path produced it. Only the framing before those rules and the "Tool usage" section
# after them differ, since batch_coder.py's own generator (see app/agents/coder_agent/
# batch_coder.py's module docstring for why this path exists at all) has no tools, no live
# filesystem access, and writes exactly one file's complete content per call.
BATCH_CODE_GENERATOR_SYSTEM_PROMPT = (
    """
You are the Coder Agent, in single-file, NO-TOOL-CALLING mode -- your model does not support real
tool-calling, so instead of exploring the workspace and writing files yourself, you are given
everything you need for exactly ONE planned file in this message, and must return that one file's
complete, real content as a small JSON response. You have no filesystem access of your own.

"""
    + CODER_AGENT_SYSTEM_PROMPT.split("Tool usage:")[0].strip()
    + """

Your response format (this mode has no tools -- this JSON object IS your entire output):
- Return ONLY this JSON object, no prose before or after it:
  {"content": "the file's COMPLETE real content -- valid source code for its own file type,
  JSON-escaped as a single string (every real newline as \\n, every double-quote as \\", every
  literal backslash doubled) -- never a diff, never a partial snippet, the ENTIRE file exactly as
  it should exist on disk"}
- If the given action is "modify", your returned content REPLACES the current file shown to you
  entirely -- you are not patching, you are writing the whole new file, so carry over everything
  from the current version you are not deliberately changing.
- If an approved UI/UX design reference was given for this file, follow the UI-fidelity rule
  above exactly as if you had called `read_ui_component_design`/`read_ui_page_design` yourself --
  it is given to you directly here because this mode has no tool call to request it with.
"""
)


_CODE_PLANNER_SHARED_HARD_RULES = """
2. This is a full-stack Next.js feature. You MUST plan BOTH sides -- planning
   only frontend files (pages/components/hooks/lib) without the backend
   Route Handler/model files that actually implement each required
   endpoint and entity below is INCOMPLETE and will be rejected.
2a. "maps_to" is a JSON ARRAY OF STRINGS, never a single string, and its
   elements are NOT a description of the file or a note about "where this
   comes from in the architecture plan" -- each element must be one exact,
   verbatim string COPIED CHARACTER-FOR-CHARACTER from the
   required_endpoints / required_entities / required_requirement_ids lists
   below (e.g. copy "/api/items" or "Item" or "FR-002" exactly as shown,
   never paraphrase, prefix, or describe it). One file's "maps_to" commonly
   needs MULTIPLE array elements -- e.g. a single routes file implementing
   three endpoints needs all three endpoint strings in its "maps_to" array.
   CORRECT:   "maps_to": ["/api/items", "/api/items/:id", "Item", "FR-002"]
   WRONG:     "maps_to": "Architecture Plan: server/src/routes/items.js"
   WRONG:     "maps_to": "implements the Item entity and item endpoints"
   WRONG (not an array): "maps_to": "/api/items"
3. Every API endpoint listed under "required_endpoints" below must be
   referenced (by its literal endpoint string, copied exactly, per rule 2a)
   in the "maps_to" list of at least one planned BACKEND file (e.g. a route
   or controller that implements it) -- referencing it from a frontend
   API-calling file does NOT count as covering the endpoint.
4. Every data entity listed under "required_entities" below must be
   referenced (by its literal name string, copied exactly, per rule 2a) in
   the "maps_to" list of at least one planned backend model/schema file.
5. Every functional requirement id listed under "required_requirement_ids"
   below must be referenced in the "maps_to" list of at least one planned
   file.
6. Prefer "modify" over "create" for any path the project manifest says
   already exists. Do not re-plan files for other, already-merged features.
7. If an approved UI/UX design reference is provided, plan the frontend page/
   component to VISUALLY MATCH that reference (real TSX written to faithfully
   reproduce its structure/Tailwind classes/content) -- it is a design reference
   to re-implement, not a file to import verbatim.
8. Do not invent files, dependencies, or env vars beyond what the SRS/
   Architecture Plan implies.
9. THE PROJECT ALREADY HAS A WORKING, RUNNABLE SCAFFOLD (Next.js App Router +
   TypeScript) -- do not plan to create or rewrite any of it:
   - `package.json` (next, react, react-dom, typescript, mongoose already
     declared), `next.config.mjs`, `tsconfig.json`, `app/layout.tsx` (root
     layout), `app/globals.css`, `lib/mongodb.ts` (guarded Mongoose connect
     helper), `app/api/health/route.ts`.
   - `app/page.tsx` (the home page -- already has a
     `{/* FEATURE_LINKS_START */}` / `{/* FEATURE_LINKS_END */}` marker pair
     inside its nav for new pages to link from).
   To add a new backend endpoint for this feature: plan a "create" for
   `app/api/<resource>/route.ts` (a collection endpoint, e.g. GET/POST
   `/api/tasks`) and, if there is an item-level endpoint too (e.g. GET/PUT/
   DELETE `/api/tasks/:id`), a SEPARATE "create" for
   `app/api/<resource>/[id]/route.ts` -- these are ALWAYS two different
   files under Next.js's file-based routing, never one combined router file.
   Each is automatically live the instant it exists -- there is no "mount
   the router" step to plan.
   To add a new backend model: plan a "create" for the new model file (e.g.
   `models/<Entity>.ts`) using mongoose with the
   `mongoose.models.X || mongoose.model(...)` guard.
   To add a new frontend page: plan a "create" for `app/<route>/page.tsx`
   (a Client Component -- its first line must be `"use client";`) AND a
   single "modify" on `app/page.tsx` that adds a real `<Link href="...">`
   to it from `HomePage` -- a page with no way to reach it by clicking is
   NOT complete. `app/page.tsx` has a `{/* FEATURE_LINKS_START */}` /
   `{/* FEATURE_LINKS_END */}` marker pair inside `HomePage` for exactly
   this purpose.
   If the route is parameterized (e.g. `/tasks/[taskId]`), do NOT link
   directly to it -- there is no real id value at the nav level. Instead: if
   a top-level "list" page for that resource already exists (e.g. `/tasks`,
   each item linking to its own `/tasks/[taskId]`), link `HomePage` to the
   list page instead. If no such list page exists yet, plan one as part of
   this feature: a "create" for a list/index page that fetches the
   collection and links to each item's detail route, plus its own
   `app/tasks/page.tsx` and a `HomePage` link to it. Recognizing that a
   parameterized route needs a reachable list-page ancestor is a planning
   decision, not just a coding-loop patch -- do not leave a parameterized
   route as the only way in.
   Never plan to touch `app/layout.tsx`, `next.config.mjs`, `tsconfig.json`,
   or `lib/mongodb.ts` -- they are already complete and feature-agnostic.
9a. Whenever this feature's plan includes any backend file that reads from the
   database (a Route Handler under `app/api/**/route.ts` calling
   `connectToDatabase()`, or a new model), also plan a "modify" of
   `lib/seedData.ts` (it already exists in the scaffold as an empty shell with
   a `// SEED_DATA_START` / `// SEED_DATA_END` marker pair) adding this
   feature's own `export const seed<Entity> = [...]` block before the END
   marker -- this is the one shared file every DB-backed route falls back to
   when no real database is connected. Plan it like any other real file; never
   leave it to be invented ad hoc mid-coding.
10. Distinguish "remove X" from "X has been removed" / "X is missing" /
   "X is broken" -- these are OPPOSITE actions, and getting this backwards
   silently does the wrong thing while looking plausible in the plan.
   "Remove X" / "delete X" / "get rid of X" means X currently EXISTS and the
   human wants it DELETED -- plan a "modify" that removes it.
   "X has been removed" / "X is missing" / "add back X" / "X used to be
   there" / "bring back X" means X does NOT currently exist (or was already
   deleted) and the human wants it RESTORED/ADDED BACK -- plan a "modify"
   (or "create") that ADDS it, never one that removes it again.
   Worked example: the request "add styles and also add the footer, the
   footer has been removed" is asking you to RESTORE the footer (plan to
   ADD a Footer component/section back), NOT to remove it a second time --
   "the footer has been removed" is a statement of a past problem to fix,
   not an instruction. When in doubt, re-read the exact phrase: an
   imperative verb ("remove", "delete") aimed at something the human is
   currently complaining about existing is a removal; a passive/past-tense
   description ("has been removed", "is missing", "is broken") aimed at
   something the human wants back is a restoration.
"""

_CODE_PLAN_JSON_SHAPE = """
Return exactly this JSON shape ("maps_to" is always an array, per rule 2a -- note the collection
route file below covers TWO endpoints, both listed, while the item endpoint is a SEPARATE file).
"summary" is the FIRST key, before "files" -- write it first, since it's shown live to the human
while you're still generating the rest of the plan:
{
  "summary": "one paragraph describing the overall plan",
  "files": [
    {
      "path": "models/Item.ts",
      "action": "create",
      "rationale": "Mongoose schema for the Item entity",
      "maps_to": ["Item"]
    },
    {
      "path": "app/api/items/route.ts",
      "action": "create",
      "rationale": "Route Handler implementing the item collection endpoints (list/create)",
      "maps_to": ["/api/items", "FR-001"]
    },
    {
      "path": "app/api/items/[id]/route.ts",
      "action": "create",
      "rationale": "Route Handler implementing the single-item endpoints (get/update/delete)",
      "maps_to": ["/api/items/:id", "FR-002"]
    }
  ],
  "new_dependencies": ["npm-package-name"],
  "env_vars_needed": ["JWT_SECRET"]
}
"""


CODE_PLANNER_SYSTEM_PROMPT = f"""
You are the Coder Agent's planner. You do NOT write code here -- you produce a
scoped, traceable plan of which files a later coding step must create, modify,
or delete for ONE approved feature in a persistent Next.js codebase.

This plan is the guardrail that keeps an open-ended coding step from
improvising architecture: it must execute your plan, not invent scope. Because
of that:

Hard rules:
1. Output ONLY a single JSON object. No prose, no markdown fences, no comments.
{_CODE_PLANNER_SHARED_HARD_RULES}
{_CODE_PLAN_JSON_SHAPE}"""


CODE_PLANNER_AGENTIC_REVISION_SYSTEM_PROMPT = f"""
You are the Coder Agent's planner, revising an already-implemented and
verified feature in response to a human's revision comment. You do NOT write
code here -- you produce a scoped, traceable plan of which files a later
coding step must create, modify, or delete.

Unlike a normal planning call, you have READ-ONLY tools to look at the real,
current codebase before deciding: `list_dir`, `read_file`, `search_code`,
`read_project_manifest`, `read_ui_component_design`, `read_ui_page_design`,
`check_component_styling`. Use
them. You do NOT have write_file/apply_patch -- you cannot and must not
change anything, only look.

Hard rules:
1. When you are done exploring and are confident in your plan, call
   `submit_code_plan` exactly once with your final plan as a JSON string in
   the exact shape below. This is your only way to finish -- do not output
   the plan as chat text.
1a. If the human's revision comment describes a broad or systemic issue
   WITHOUT naming specific files (e.g. "styles are missing, add tailwind
   css", "error handling is missing", "add accessibility labels everywhere"),
   you MUST use your tools to find EVERY existing page/component file
   actually affected before finalizing your plan -- do not guess from file
   names alone, and do not stop after finding just one matching file if
   others also match. A partial fix that only touches one of several
   affected files is exactly the kind of incomplete result this exploration
   step exists to prevent.
   For a STYLING/CSS-related comment specifically, call
   `check_component_styling` FIRST -- it directly reports which
   page/component files currently use Tailwind classes, only raw inline
   styles, or neither. Trust it over your own inference: finding which
   files DO NOT already use Tailwind is a much harder thing to reliably
   figure out by reading files one at a time than the tool's direct answer.
   A file it reports as "styled" is very likely already fine and does not
   need a plan entry; a file it reports as "unstyled" or "inline_styles" is
   a real candidate that probably does. Do not conclude the fix is a
   project-wide config file (e.g. index.css, tailwind.config.js) unless you
   have actually confirmed Tailwind is not yet configured at all -- if it
   already is (check for existing `@tailwind` directives / a
   tailwind.config.js), the real gap is almost always in the individual
   page/component files the tool flagged, not the global setup.
1b. Your turn budget is limited -- be efficient. Your job here is ONLY to
   decide WHICH files need a plan entry and WHY, not to write the actual
   code changes (a separate, later coding step does that, and it will read
   each file itself before editing it). This means:
   - Prefer a summarizing tool (`check_component_styling`,
     `read_project_manifest`, `search_code`) over reading full file
     contents one at a time -- those tools exist precisely so you don't
     have to open every file individually to decide what's affected.
   - Only call `read_file` on a specific candidate file when a summarizing
     tool's answer is genuinely ambiguous about whether it needs a plan
     entry -- not to double-check every file it already gave you a clear
     answer for, and not to preview what the eventual code change will
     look like (that's the coding step's job).
   - As soon as you can name the affected file(s) and why, call
     `submit_code_plan` -- do not keep exploring "just to be thorough" once
     you are already confident.
   If the comment DOES name specific files, you may still use the tools to
   confirm their current content before planning a change, but exhaustive
   exploration is not required.
{_CODE_PLANNER_SHARED_HARD_RULES}
{_CODE_PLAN_JSON_SHAPE}"""


def _build_shared_planner_context_sections(
    project: dict,
    feature: dict,
    srs_json: dict,
    architecture_plan_json: dict,
    ui_integration_manifest_json: dict | None,
    project_manifest_json: dict,
    human_comment: str | None,
    previous_plan_json: dict | None,
    validation_feedback: str | None,
) -> list[str]:
    """
    The context section shared by both the single-shot planner
    (build_code_planner_user_prompt) and the agentic revision planner
    (build_agentic_revision_planner_user_prompt) -- required coverage lists,
    SRS, architecture design_views, project manifest, UI/UX manifest, the
    human's comment, and any prior-attempt validation feedback. Each caller
    appends its own final instructions (JSON-only vs explore-then-submit).
    """
    design_views = architecture_plan_json.get("design_views", {})
    required_endpoints = [
        item.get("endpoint")
        for item in design_views.get("interface_view", {}).get("api_endpoints", [])
        if isinstance(item, dict) and item.get("endpoint")
    ]
    required_entities = [
        item.get("name")
        for item in design_views.get("data_view", {}).get("data_entities", [])
        if isinstance(item, dict) and item.get("name")
    ]
    required_requirement_ids = [
        item.get("id")
        for item in srs_json.get("functional_requirements", [])
        if isinstance(item, dict) and item.get("id")
    ]

    sections = [
        f"Project: {project.get('project_name')} (target stack: {project.get('target_stack', 'Next.js')})",
        f"Feature: {feature.get('feature_name')}",
        "",
        f"required_endpoints (must all appear in some file's maps_to): {required_endpoints}",
        f"required_entities (must all appear in some file's maps_to): {required_entities}",
        f"required_requirement_ids (must all appear in some file's maps_to): {required_requirement_ids}",
        "",
        "Approved SRS:",
        json.dumps(srs_json, indent=2, default=str),
        "",
        "Approved Architecture Plan design_views:",
        json.dumps(design_views, indent=2, default=str),
        "",
        "Project manifest (routes/models/components that already exist -- prefer 'modify' over "
        "'create' for these, and do not duplicate them):",
        json.dumps(project_manifest_json, indent=2, default=str),
    ]

    implementation_plan = architecture_plan_json.get("implementation_plan")
    if implementation_plan:
        sections.extend(
            [
                "",
                "Architecture implementation plan (the approved end-to-end blueprint your code "
                "plan must realize -- follow its file paths, endpoint specs, model fields, and "
                "implementation order. Use ITS exact file paths for your \"files\" entries "
                "unless the project manifest shows a conflicting file already exists):",
                json.dumps(implementation_plan, indent=2, default=str),
            ]
        )

    if ui_integration_manifest_json:
        sections.extend(
            [
                "",
                "Approved UI/UX integration manifest (routes/content a human already approved the "
                "VISUAL DESIGN of -- call read_ui_component_design/read_ui_page_design to see the "
                "actual HTML+Tailwind reference, then write real TSX that faithfully matches it; "
                "it is a design reference to re-implement, not markup to import). IMPORTANT: this "
                "manifest describes what to wire in, it does NOT mean these files exist in the "
                "codebase yet. Check the project manifest above for what actually already exists; "
                "if it's empty or doesn't list a file, you must plan to CREATE it (e.g. a page "
                "matching the approved design), not 'modify' something that isn't there.",
                json.dumps(ui_integration_manifest_json, indent=2, default=str),
            ]
        )

    if human_comment:
        sections.extend(["", f"Human revision comment: {human_comment}"])

    if validation_feedback:
        sections.extend(
            [
                "",
                "---",
                "Your previous plan attempt was REJECTED by a deterministic coverage check. "
                "Here is exactly what was wrong:",
                validation_feedback,
                "",
                "Your previous (rejected) plan, for reference:",
                json.dumps(previous_plan_json or {}, indent=2, default=str),
                "",
                "Fix ONLY the specific gaps listed above -- add the missing files/maps_to "
                "entries. Keep everything that was already correct.",
            ]
        )

    return sections


# The planning prompt above already shows the full SRS + implementation_plan -- but that only
# ever informs the terse code_plan_json (files: [{path, action, rationale, maps_to}], deliberately
# short strings only, see _CODE_PLANNER_SHARED_HARD_RULES's maps_to rules). The actual CODING step
# (coding_loop.build_task_message / batch_coder.py's per-file prompt) previously received ONLY
# that terse plan -- no field-level endpoint/model detail, no SRS acceptance criteria/ui
# expectations at all. This is the confirmed root cause of "the generated app doesn't match the
# feature": the coding step had no way to know what a planned file was actually supposed to DO,
# only that it should exist. The helpers below build a bounded, per-file-scoped slice of the real
# spec for the coding step -- deliberately NOT a new tool (a `read_implementation_spec` tool would
# need its own hard gate, mirroring list_unread_ui_designs, to guarantee it's actually called per
# file, reproducing the same "no obligation to look" gap; and repeated large tool results risk the
# same Ollama num_ctx truncation class of bug already documented for this agent). Inlining once,
# capped by MAX_IMPLEMENTATION_SPEC_CHARS (mirrors diff_builder.MAX_DIFF_TEXT_CHARS's own
# truncate-with-label precedent), needs no new enforcement machinery.
MAX_IMPLEMENTATION_SPEC_CHARS = 8_000

# A file's own requirement context always includes at least this many requirements even when
# maps_to has no requirement-ID-shaped entry at all -- a file should never get zero context.
_SRS_FALLBACK_REQUIREMENT_COUNT = 3


def _match_implementation_plan_entries_for_file(
    file_entry: dict[str, Any], implementation_plan: dict[str, Any]
) -> dict[str, Any]:
    """
    Mechanically extract only the implementation_plan sub-entries this ONE code_plan file
    entry's path/maps_to actually reference -- never the whole implementation_plan. Matches:
    backend.files[] by .path == file_entry["path"]; backend.endpoints[] by .path in maps_to (or
    in a matched file's own implements_endpoints); backend.models[] by .name in maps_to;
    frontend.pages[] by .path == path or .route in maps_to; frontend.services[] by
    .path == path. Returns {} when nothing matches (e.g. a config/scaffold file with no real
    spec entry of its own).
    """
    path = file_entry.get("path")
    maps_to = [m for m in file_entry.get("maps_to", []) if isinstance(m, str)]
    backend = implementation_plan.get("backend", {}) if isinstance(implementation_plan, dict) else {}
    frontend = implementation_plan.get("frontend", {}) if isinstance(implementation_plan, dict) else {}

    matched_files = [
        f for f in backend.get("files", []) if isinstance(f, dict) and f.get("path") == path
    ]

    endpoint_paths = set(maps_to)
    for f in matched_files:
        endpoint_paths.update(f.get("implements_endpoints") or [])
    matched_endpoints = [
        e for e in backend.get("endpoints", []) if isinstance(e, dict) and e.get("path") in endpoint_paths
    ]

    matched_models = [
        m for m in backend.get("models", []) if isinstance(m, dict) and m.get("name") in maps_to
    ]

    matched_pages = [
        p
        for p in frontend.get("pages", [])
        if isinstance(p, dict) and (p.get("path") == path or p.get("route") in maps_to)
    ]

    matched_services = [
        s for s in frontend.get("services", []) if isinstance(s, dict) and s.get("path") == path
    ]

    result: dict[str, Any] = {}
    if matched_files:
        result["backend_file"] = matched_files
    if matched_endpoints:
        result["endpoints"] = matched_endpoints
    if matched_models:
        result["models"] = matched_models
    if matched_pages:
        result["pages"] = matched_pages
    if matched_services:
        result["services"] = matched_services
    return result


def _match_srs_requirements_for_file(file_entry: dict[str, Any], srs_json: dict[str, Any]) -> list[dict[str, Any]]:
    """
    functional_requirements/acceptance_criteria entries whose "id" appears in this file's
    maps_to. Falls back to the first _SRS_FALLBACK_REQUIREMENT_COUNT functional requirements if
    maps_to has no requirement-ID-shaped string at all -- a file should never get zero
    requirement context just because its plan entry only named an endpoint/entity.
    """
    maps_to = set(file_entry.get("maps_to", []) or [])
    all_requirements = [
        item
        for item in (srs_json.get("functional_requirements", []) or []) + (srs_json.get("acceptance_criteria", []) or [])
        if isinstance(item, dict)
    ]
    matched = [item for item in all_requirements if item.get("id") in maps_to]
    if matched:
        return matched
    return [
        item
        for item in (srs_json.get("functional_requirements", []) or [])
        if isinstance(item, dict)
    ][:_SRS_FALLBACK_REQUIREMENT_COUNT]


def build_implementation_spec_for_single_file(
    file_entry: dict[str, Any], srs_json: dict[str, Any], architecture_plan_json: dict[str, Any]
) -> str:
    """
    The real spec detail relevant to ONE planned file -- its matched implementation_plan
    sub-entries + matched SRS requirements + the SRS's ui_expectations (always, cross-cutting).
    Used by batch_coder.py's per-file, no-tool-calling prompt, where inlining is the only option.
    Returns "" when there is nothing to show (e.g. srs_json/architecture_plan_json both empty).
    """
    implementation_plan = architecture_plan_json.get("implementation_plan") or {}
    matched_plan = _match_implementation_plan_entries_for_file(file_entry, implementation_plan)
    matched_requirements = _match_srs_requirements_for_file(file_entry, srs_json)
    ui_expectations = srs_json.get("ui_expectations") or []

    parts: list[str] = []
    if ui_expectations:
        parts.append("SRS UI expectations (apply project-wide, not just to this file):")
        parts.append(json.dumps(ui_expectations, indent=2, default=str))
    if matched_requirements:
        parts.append("Relevant SRS requirements for this file:")
        parts.append(json.dumps(matched_requirements, indent=2, default=str))
    if matched_plan:
        parts.append("Relevant Architecture implementation_plan detail for this file:")
        parts.append(json.dumps(matched_plan, indent=2, default=str))

    if not parts:
        return ""

    text = "\n".join(parts)
    if len(text) > MAX_IMPLEMENTATION_SPEC_CHARS:
        text = text[:MAX_IMPLEMENTATION_SPEC_CHARS] + "\n... (truncated)"
    return text


def build_implementation_spec_section(
    code_plan_json: dict[str, Any], srs_json: dict[str, Any], architecture_plan_json: dict[str, Any]
) -> str:
    """
    ONE combined block covering every file in code_plan_json's own matched spec detail, for the
    AGENTIC coding path (coding_loop.build_task_message) -- the loop shares one long conversation
    across every file, so this is built once per attempt, not per file. SRS ui_expectations is
    included once at the top (cross-cutting); each file then gets its own matched requirements +
    implementation_plan slice. Capped by MAX_IMPLEMENTATION_SPEC_CHARS so total growth stays
    bounded and proportional to the plan's own size, never the whole SRS/implementation_plan
    dumped wholesale. Returns "" when there is nothing to show.
    """
    implementation_plan = architecture_plan_json.get("implementation_plan") or {}
    ui_expectations = srs_json.get("ui_expectations") or []
    files = code_plan_json.get("files", []) if isinstance(code_plan_json, dict) else []

    parts: list[str] = []
    if ui_expectations:
        parts.append("SRS UI expectations (apply project-wide, to every page/component you write):")
        parts.append(json.dumps(ui_expectations, indent=2, default=str))

    for file_entry in files:
        if not isinstance(file_entry, dict):
            continue
        matched_plan = _match_implementation_plan_entries_for_file(file_entry, implementation_plan)
        matched_requirements = _match_srs_requirements_for_file(file_entry, srs_json)
        if not matched_plan and not matched_requirements:
            continue
        parts.append(f"For {file_entry.get('path')}:")
        if matched_requirements:
            parts.append(json.dumps({"requirements": matched_requirements}, indent=2, default=str))
        if matched_plan:
            parts.append(json.dumps(matched_plan, indent=2, default=str))

    if not parts:
        return ""

    text = "\n".join(parts)
    if len(text) > MAX_IMPLEMENTATION_SPEC_CHARS:
        text = text[:MAX_IMPLEMENTATION_SPEC_CHARS] + "\n... (truncated)"
    return text


def _build_cumulative_touched_files_section(coverage_baseline_files: list[dict[str, Any]]) -> list[str]:
    """
    Shared by build_code_planner_user_prompt (only when the caller is CoderAgent.revise()'s
    fast path -- see _find_well_specified_target_files) and
    build_agentic_revision_planner_user_prompt (always) -- renders the identical "files this
    feature has already touched" block so a planner call knows which files are real and already
    exist (correct "modify") vs. genuinely new (correct "create"), regardless of which planner
    method is actually answering.
    """
    if not coverage_baseline_files:
        return []

    touched_paths = sorted(
        entry.get("path")
        for entry in coverage_baseline_files
        if isinstance(entry, dict) and entry.get("path")
    )
    if not touched_paths:
        return []

    return [
        "",
        "Files this feature has already touched across all previous plan versions "
        "(a starting point, not necessarily the full picture -- use your tools to "
        "check their current content, and to find other files if the human's "
        "comment describes something broader than these):",
        "\n".join(f"- {path}" for path in touched_paths),
    ]


def _build_keyword_hint_files_section(keyword_hint_files: list[str]) -> list[str]:
    """
    Shared by build_agentic_revision_planner_user_prompt only -- renders the list of files a
    cheap, deterministic keyword search of the human's revision comment against the real
    workspace turned up (CoderAgent._find_keyword_hint_files, "Tier 1b"). Explicitly framed
    as UNVERIFIED: a keyword/content match can find files that merely mention a topic without
    being the actually-broken one (confirmed real -- grepping "tailwind"/"css" for a "styles
    are missing" request finds the files that already correctly use Tailwind, not the one
    unstyled file). This is why the caller never lets this list skip exploration -- it's only
    ever a starting point for the model's own tools to confirm or override.
    """
    if not keyword_hint_files:
        return []

    return [
        "",
        "A quick keyword search of this comment against the codebase suggests these files "
        "might be related to the human's request -- this is NOT a guarantee, especially for "
        "a request about something MISSING (e.g. absent styling, a missing validation check) "
        "since a keyword search only finds files that already mention a topic, never files "
        "that are missing one. Use your own tools to confirm before trusting this list, and "
        "look further if it doesn't actually cover the request:",
        "\n".join(f"- {path}" for path in keyword_hint_files),
    ]


def build_code_planner_user_prompt(
    project: dict,
    feature: dict,
    srs_json: dict,
    architecture_plan_json: dict,
    ui_integration_manifest_json: dict | None,
    project_manifest_json: dict,
    human_comment: str | None,
    previous_plan_json: dict | None = None,
    validation_feedback: str | None = None,
    coverage_baseline_files: list[dict[str, Any]] | None = None,
) -> str:
    sections = _build_shared_planner_context_sections(
        project=project,
        feature=feature,
        srs_json=srs_json,
        architecture_plan_json=architecture_plan_json,
        ui_integration_manifest_json=ui_integration_manifest_json,
        project_manifest_json=project_manifest_json,
        human_comment=human_comment,
        previous_plan_json=previous_plan_json,
        validation_feedback=validation_feedback,
    )

    # Only ever non-empty for CoderAgent.revise()'s fast path (see
    # _find_well_specified_target_files) -- run()'s/run_stream()'s first-time planning has
    # nothing to pass here, since there is no prior plan history for a brand-new feature.
    if coverage_baseline_files:
        sections.extend(_build_cumulative_touched_files_section(coverage_baseline_files))

    sections.extend(
        [
            "",
            "---",
            "Everything above (SRS, Architecture Plan, project manifest, UI/UX manifest) is "
            "READ-ONLY CONTEXT for you to plan from. It is NOT the output shape.",
            "",
            "Your response must be a single JSON object with EXACTLY these top-level keys, "
            "and no others: \"files\", \"new_dependencies\", \"env_vars_needed\", \"summary\". "
            "Each entry in \"files\" must have exactly: \"path\", \"action\", \"rationale\", "
            "\"maps_to\". Do not output \"routes\", \"api_endpoints\", \"models\", "
            "\"shared_components\", or \"features\" as top-level keys -- those are the shape of "
            "the project manifest shown above, not of your answer.",
            "",
            "Return code_plan_json now, following the required JSON shape exactly.",
        ]
    )

    return "\n".join(sections)


def build_agentic_revision_planner_user_prompt(
    project: dict,
    feature: dict,
    srs_json: dict,
    architecture_plan_json: dict,
    ui_integration_manifest_json: dict | None,
    project_manifest_json: dict,
    human_comment: str | None,
    previous_plan_json: dict | None,
    validation_feedback: str | None,
    coverage_baseline_files: list[dict[str, Any]],
    keyword_hint_files: list[str] | None = None,
) -> str:
    """
    Same context as build_code_planner_user_prompt, plus a real, cumulative
    list of every file this feature has touched across ALL previously saved
    plan versions (not just the latest -- see
    CoderAgent._collect_cumulative_plan_files) -- seeds the agentic planner
    with already-known real file paths so it isn't starting from nothing,
    while its read-only tools let it look further (e.g. a styling request
    may reasonably span files this feature never itself touched).

    keyword_hint_files: an unverified starting-point hint from a cheap keyword search of the
    real workspace (CoderAgent._find_keyword_hint_files, "Tier 1b") -- see
    _build_keyword_hint_files_section for why this is explicitly never treated as trustworthy
    on its own.
    """
    sections = _build_shared_planner_context_sections(
        project=project,
        feature=feature,
        srs_json=srs_json,
        architecture_plan_json=architecture_plan_json,
        ui_integration_manifest_json=ui_integration_manifest_json,
        project_manifest_json=project_manifest_json,
        human_comment=human_comment,
        previous_plan_json=previous_plan_json,
        validation_feedback=validation_feedback,
    )

    if coverage_baseline_files:
        sections.extend(_build_cumulative_touched_files_section(coverage_baseline_files))

    if keyword_hint_files:
        sections.extend(_build_keyword_hint_files_section(keyword_hint_files))

    sections.extend(
        [
            "",
            "---",
            "Everything above is READ-ONLY CONTEXT, not the output shape. Use your tools to "
            "explore the real codebase, then call submit_code_plan exactly once with your "
            "final code_plan_json (the same shape shown in your instructions) serialized as "
            "a JSON string -- with EXACTLY these top-level keys: \"files\", "
            "\"new_dependencies\", \"env_vars_needed\", \"summary\". Each entry in \"files\" "
            "must have exactly: \"path\", \"action\", \"rationale\", \"maps_to\".",
        ]
    )

    return "\n".join(sections)


CODE_PLAN_JSON_REPAIR_PROMPT = """
The previous response was not valid code_plan_json. Return ONLY a corrected
JSON object matching the required shape. No prose, no markdown fences.
"""


def build_code_plan_repair_prompt(raw_output: str) -> str:
    return f"Previous invalid output:\n{raw_output}\n\nReturn corrected code_plan_json now."