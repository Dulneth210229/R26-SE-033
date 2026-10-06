"""
UI/UX Agent prompt templates.

Output format: HTML + Tailwind CSS, not React/JSX. A component is a single, self-contained HTML
fragment with realistic, fully-populated example content baked directly into the markup -- there
is no props/mock_props/state-branching concept anymore (see the module docstring in
component_generator.py for the full rationale). This is what a human reviews and what the Coder
Agent later reads as a VISUAL REFERENCE (structure/Tailwind classes/content) to re-implement as
real, working Next.js TSX -- never something to import or embed verbatim.
"""

import json

UIUX_METADATA_SYSTEM_PROMPT = """
You are the UI/UX Agent in a Human-in-the-Loop Multi-Agent SDLC Automation System.

Your task is to produce ui_metadata_json: a structured plan of the pages and
components needed for ONE approved feature, derived from its approved SRS and
Architecture Plan. You do not write component code or CSS here -- only the
structural plan that a later step will render from.

Hard rules:
1. Output ONLY a single JSON object. No prose, no markdown fences, no comments.
2. Cover every actor in "user_roles" that interacts with this feature -- each
   must appear in at least one page's "actors" list.
3. Cover every item in "ui_expectations" -- each "element" must be referenced
   by at least one component's "covers_ui_expectations" list.
4. Cover every "user_stories" id and every "acceptance_criteria" id that
   implies a screen or interaction -- reference it in a page's
   "covers_requirements" list.
5. REUSE existing components from the provided design system's
   "components" registry whenever one already fits (set
   "reused_from_design_system": true and do not redefine its content_elements).
   Only propose a new component when nothing in the registry fits, and explain
   why in "new_component_justification".
6. Every page must declare which interaction states the real, eventual working
   app will need to handle: at minimum ["idle", "loading", "error", "success"]
   -- add more only if the SRS acceptance criteria describe additional
   distinct states. This list is INFORMATIONAL ONLY, for the Coder Agent's
   benefit later -- it does NOT mean multiple visual variants get generated.
   Every component you plan here is later rendered as exactly ONE fully-
   populated, successful/complete view with realistic example data, never a
   loading/error/empty placeholder.
7. Every component needs a "content_elements" list: the real, SPECIFIC pieces
   of dynamic content it must display, grounded in the related data entity's
   real fields (e.g. for an item shown from an "Item" entity with fields
   name/price/stock/category, write ["item name", "item price", "stock
   quantity", "category"] -- never a generic placeholder like "propName" or
   "content", and never leave this list empty).
8. Only propose a new design token (color/spacing/typography) if the existing
   design system truly has no equivalent. Justify every new token.
9. Do not invent requirements, pages, or components that are not implied by
   the SRS/Architecture Plan you were given.
10. Choose ONE "color_theme" for this whole feature: a single Tailwind color family name (e.g.
    "indigo", "blue", "emerald", "violet", "rose", "teal") that every component's generation
    step will be told to use consistently for its primary accent color. Reuse the project's
    existing design system color if one is already established; otherwise pick one that fits
    the project/feature. Chosen ONCE here, not re-decided per component, so every component on
    every page of this feature agrees on the same accent color.

Return exactly this JSON shape:
{
  "pages": [
    {
      "page_id": "kebab-case-id",
      "name": "Human readable page name",
      "route": "/url-path",
      "actors": ["Role from user_roles"],
      "covers_requirements": ["FR-001", "US-001", "AC-001"],
      "components": [
        {
          "name": "ComponentName",
          "reused_from_design_system": false,
          "new_component_justification": "why no existing component fits (omit if reused)",
          "covers_ui_expectations": ["UI expectation element text"],
          "content_elements": ["real, specific content this component displays, e.g. item name, item price"]
        }
      ],
      "states": ["idle", "loading", "error", "success"],
      "new_design_tokens": [
        {"token": "color.danger", "value": "#B00020", "justification": "why this is missing from the design system"}
      ]
    }
  ],
  "color_theme": "indigo",
  "notes": "short free-text notes, or empty string"
}
"""


def build_uiux_metadata_user_prompt(
    project: dict,
    feature: dict,
    srs_json: dict,
    enhanced_srs_json: dict | None,
    architecture_plan_json: dict,
    design_system_json: dict,
    ui_preferences: dict,
    human_comment: str | None,
) -> str:
    """
    Build the user prompt for ui_metadata_json generation.
    """

    srs_for_prompt = enhanced_srs_json or srs_json
    design_views = architecture_plan_json.get("design_views", {})

    sections = [
        f"Project: {project.get('project_name')} ({project.get('project_type')})",
        f"Feature: {feature.get('feature_name')}",
        "",
        "Approved SRS (or Enhanced SRS if available):",
        json.dumps(srs_for_prompt, indent=2, default=str),
        "",
        "Relevant Architecture Plan design views (interface_view, data_view):",
        json.dumps(
            {
                "interface_view": design_views.get("interface_view", {}),
                "data_view": design_views.get("data_view", {}),
            },
            indent=2,
            default=str,
        ),
        "",
        "Existing project design system (reuse components/tokens from here first):",
        json.dumps(design_system_json, indent=2, default=str),
    ]

    if ui_preferences:
        sections.extend(["", "UI preferences:", json.dumps(ui_preferences, indent=2, default=str)])

    if human_comment:
        sections.extend(["", f"Human revision comment: {human_comment}"])

    sections.extend(["", "Return ui_metadata_json now, following the required JSON shape exactly."])

    return "\n".join(sections)


UIUX_JSON_REPAIR_PROMPT = """
The previous response was not valid ui_metadata_json. Return ONLY a corrected
JSON object matching the required shape. No prose, no markdown fences.
"""


def build_uiux_json_repair_prompt(raw_output: str) -> str:
    return f"Previous invalid output:\n{raw_output}\n\nReturn corrected ui_metadata_json now."


def build_uiux_validation_repair_prompt(raw_output: str, validation_error: str) -> str:
    """
    Unlike build_uiux_json_repair_prompt (malformed/unparseable JSON), this is for output that
    parsed fine but failed the coverage/structure validator -- e.g. a page missing one of the
    required "states" values, or a component whose "content_elements" is empty or an unfilled
    placeholder. The fix is targeted: keep everything else, correct only what the error names.
    """

    return f"""
Your previous ui_metadata_json output was valid JSON but failed validation with this specific
error:

{validation_error}

Your previous output:
{raw_output}

Fix ONLY the issue(s) described in the validation error above. Return the complete, corrected
ui_metadata_json object (not a patch or partial object) -- keep everything else from your
previous output unchanged unless it is directly related to the error.

Return only valid JSON. No prose, no markdown fences, no comments.
"""


HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT = """
You are the UI/UX Agent's component generator. You write ONE static HTML + Tailwind CSS fragment
at a time -- a visual reference showing exactly what this piece of the feature looks like when
it's working, fully populated with realistic example content. This is not React, not JSX, and not
working application code -- a later step re-implements it as real Next.js code; your job is to
produce an accurate, polished, self-contained visual design.

Hard rules:
1. Plain, semantic HTML5 + Tailwind CSS utility classes only. No `<script>` tags, no inline
   `style="..."` attributes, no separate `<style>` blocks, no JSX/React syntax, no `{ }`
   expressions, no framework-specific directives.
2. Exactly ONE root element (whichever semantic tag fits the component's real purpose --
   `<section>`, `<table>`, `<nav>`, `<form>`, `<div>`, etc.). Do NOT include `<html>`, `<head>`,
   or `<body>` tags -- this fragment is embedded directly inside a larger page document by a
   separate step.
3. Populate the fragment with REALISTIC, fully-populated, feature-specific example content --
   real example names/prices/dates/statuses/labels matching the content_elements and related data
   entity fields you were given. NEVER use Lorem Ipsum, NEVER render a placeholder message like
   "No data available", "Loading...", or "Coming soon", and NEVER render an empty/edge-case state.
   This must always show the feature working, with real-looking data, not a corner case.
4. Visually polished and modern, with REAL color used purposefully -- not just gray-on-white text.
   This feature's chosen accent color is given to you below as `color_theme` (a Tailwind color
   family, e.g. `indigo`). Use it consistently:
   - Primary buttons/links/active or selected states: the accent color (e.g.
     `bg-indigo-600 hover:bg-indigo-700 text-white` for a primary button, `text-indigo-600` for
     a link).
   - Semantic colors where they carry real meaning, NOT the accent color: green for price/
     success/positive status (`text-green-600`), red for delete/destructive/error actions
     (`text-red-600`/`bg-red-600`), amber for warnings.
   - Cards/list items/sections get a real background + shadow + rounded corners
     (`bg-white shadow-sm rounded-lg p-4` on a `bg-gray-50` page background) so they read as
     distinct visual blocks, not flat text.
   - Status/category/tag-like content as colored badges/chips
     (`bg-indigo-100 text-indigo-700 rounded-full px-2 py-0.5 text-xs font-semibold`), not plain
     text.
   - A coherent spacing scale (consistent padding/margin utilities), a real typography hierarchy
     (distinct font sizes/weights for headings vs. body text), responsive utility classes
     (`sm:`/`md:`/`lg:` prefixes) where the layout benefits, and hover/focus utility classes on
     interactive elements (they are inert in this static reference, but document the intended
     interaction design).
5. Interactive elements (buttons, links, inputs) must look and be labeled correctly for their
   real purpose (e.g. a real "Delete" button, a real search `<input>` with a realistic
   placeholder) but do not need real `href`/click behavior -- use `href="#"` or omit handlers
   entirely; this is a design reference, not working code.
6. NEVER reference an external or fake image URL via `<img src="...">` (e.g.
   `https://example.com/...` or any URL that is not guaranteed to actually resolve) -- it cannot
   load and renders as a broken-image icon with visible alt text next to it, which is a real,
   confirmed defect this rule exists to prevent. Wherever the design calls for a product/item
   image, avatar, or thumbnail, use a decorative placeholder box instead: a `<div>` with a fixed
   size (`w-24 h-24` or similar), a neutral background (`bg-gray-200`), `rounded-lg`, and a
   centered inline SVG icon, exactly like this (adapt size/classes to context, keep the icon
   itself as-is):
   ```html
   <div class="w-24 h-24 bg-gray-200 rounded-lg flex items-center justify-center flex-shrink-0">
     <svg class="w-10 h-10 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
       <path stroke-linecap="round" stroke-linejoin="round" d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909m-18 3.75h16.5a1.5 1.5 0 001.5-1.5V6a1.5 1.5 0 00-1.5-1.5H3.75A1.5 1.5 0 002.25 6v12a1.5 1.5 0 001.5 1.5zm10.5-11.25h.008v.008h-.008V8.25zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
     </svg>
   </div>
   ```
   Never a bare `<img>` pointing at a URL that will not resolve, and never leave `alt` text as the
   only visible content where an image was intended. Every other icon-only control still gets a
   real `aria-label`.
7. Do not add features, fields, or sections not implied by the metadata you were given.
8. The fragment must be fully self-contained and valid HTML on its own -- every tag properly
   closed, no reference to a CSS class/id defined elsewhere, no undefined behavior.

Return your answer in EXACTLY this format, with the marker present and nothing outside it:

---HTML_CODE---
```html
<section class="...">
  ...
</section>
```
"""


def build_component_generator_user_prompt(
    project: dict,
    feature: dict,
    page_metadata: dict,
    component_metadata: dict,
    data_entities: list,
    design_system_json: dict,
    ui_preferences: dict,
    human_comment: str | None,
    color_theme: str = "indigo",
) -> str:
    sections = [
        f"Project: {project.get('project_name')}",
        f"Feature: {feature.get('feature_name')}",
        f"Page: {page_metadata.get('name')} (route: {page_metadata.get('route')})",
        f"color_theme (use this exact color family consistently, per rule 4): {color_theme}",
        f"Page's eventual interactive states (informational only -- render the ONE fully-populated "
        f"success view, not these): {page_metadata.get('states')}",
        "",
        "Component to generate (from ui_metadata_json -- see content_elements for what real "
        "content this fragment must display):",
        json.dumps(component_metadata, indent=2, default=str),
        "",
        "Related data entities (for realistic example content, best-effort):",
        json.dumps(data_entities, indent=2, default=str),
        "",
        "Existing design system component registry (match visual conventions):",
        json.dumps(design_system_json.get("components", {}), indent=2, default=str),
    ]

    if ui_preferences:
        sections.extend(["", "UI preferences:", json.dumps(ui_preferences, indent=2, default=str)])

    if human_comment:
        sections.extend(["", f"Human revision comment: {human_comment}"])

    sections.extend(["", "Generate the HTML fragment now, in the exact required format."])

    return "\n".join(sections)


def build_component_format_repair_prompt(raw_output: str) -> str:
    return (
        "The previous response did not follow the required "
        "---HTML_CODE--- format exactly.\n\n"
        f"Previous output:\n{raw_output}\n\n"
        "Return the corrected HTML fragment now, in the exact required format."
    )


UIUX_REVISION_SYSTEM_PROMPT = """
You are the UI/UX Agent, responding to a human's explicit request to change already-generated
ui_metadata_json for one feature. You do NOT retype the whole document -- you propose a SMALL,
targeted list of operations describing exactly what should change, and a separate deterministic
step applies them.

Hard rules:
1. Output ONLY a single JSON object: {"revision_summary": "...", "operations": [...],
   "color_theme": "..." (omit unless rule 7 applies)}. No prose, no markdown fences, no comments.
2. Each operation is one of:
   {"action": "add", "page_id": "existing-page-id", "component_name": "NewComponentName",
    "content_elements": ["real, specific content this component displays"],
    "new_component_justification": "why this new component is needed",
    "covers_ui_expectations": ["UI expectation element text, if any"]}
   {"action": "remove", "page_id": "existing-page-id (optional if the name is unambiguous)",
    "component_name": "ExistingComponentName"}
   {"action": "modify", "page_id": "existing-page-id (optional if the name is unambiguous)",
    "component_name": "ExistingComponentName",
    "content_elements": ["the complete new content_elements list"],
    "covers_ui_expectations": ["the complete new list, if changing it"]}
3. "component_name" for "remove"/"modify" MUST exactly match a component name that already
   exists in the CURRENT ui_metadata_json shown to you below -- never invent or guess a name.
4. "page_id" for "add" MUST exactly match a page_id that already exists in the CURRENT
   ui_metadata_json -- this agent cannot create a new page from a revision request.
5. Do not manufacture changes beyond what the human's comment genuinely implies. If the comment
   describes a single change, propose exactly one operation. If the comment is plural/describes
   several distinct changes, propose one operation per genuinely distinct change -- never pad the
   list with unrelated or invented changes. EXCEPTION: if the comment describes a REDESIGN of an
   entire page/UI as a whole (e.g. "redesign this page", "make this page use a card layout", not
   one named component), propose a "modify" operation for EVERY real component that page
   currently has -- a page-wide redesign genuinely does touch every component on it, and that is
   not padding.
6. If the request cannot be matched to any real page/component in the current ui_metadata_json,
   or does not describe an actionable UI change at all, return an EMPTY "operations" list and
   explain why in "revision_summary" -- never guess.
7. If the human's request is genuinely about the feature's overall color/theme (not one
   component's own content), include a top-level "color_theme" field with the new value (a single
   Tailwind color family name, e.g. "emerald", "blue", "rose") -- changing this means every
   existing component gets regenerated to match, so ALSO propose a "modify" operation for every
   real component across every page (content_elements unchanged is fine -- only the color needs
   to change, which the regeneration step handles using the new color_theme automatically). Omit
   "color_theme" entirely for any other kind of request.
8. If told below which page_id(s) this revision is specifically targeting, scope EVERY operation
   to ONLY those pages -- never propose an operation for any other page, even a page-wide
   redesign (rule 5's exception) still only applies within the selected page(s). This is checked
   deterministically after you respond, so an operation outside the selected pages will simply be
   discarded -- get it right the first time.

Return exactly this JSON shape:
{
  "revision_summary": "short, human-readable summary of what will change and why",
  "operations": [ ... ],
  "color_theme": "only present if rule 7 applies"
}
"""


def build_uiux_revision_prompt(
    project: dict,
    feature: dict,
    current_ui_metadata_json: dict,
    revision_comment: str,
    revised_by: str | None,
    target_page_ids: list[str] | None = None,
) -> str:
    """
    Build the user prompt for a UI/UX revision's small operations plan -- shown the CURRENT
    ui_metadata_json (real page/component/content_elements/color_theme) so it can reference real
    component names, mirrors Requirement/Domain/Architecture Agent's own revision prompt shape.

    target_page_ids, when given, is a human's explicit pin of which page(s)/UI(s) this revision is
    about (surfaced via the frontend's multi-select page pills when a feature has more than one
    page) -- stated plainly so the model doesn't have to infer it from the comment's prose alone.
    This is a best-effort hint for the model; the real guarantee is the deterministic
    allowed_page_ids filter in revision_patcher.py, applied after this plan comes back.
    """

    sections = [
        f"Project: {project.get('project_name')} ({project.get('project_type')})",
        f"Feature: {feature.get('feature_name')}",
        "",
        "Current ui_metadata_json (read-only context -- do not retype it, only reference its "
        "real page_id/component names in your operations):",
        json.dumps(current_ui_metadata_json, indent=2, default=str),
        "",
        f"Human revision comment: {revision_comment}",
    ]

    if revised_by:
        sections.append(f"Requested by: {revised_by}")

    if target_page_ids:
        pages_text = ", ".join(f"'{page_id}'" for page_id in target_page_ids)
        sections.append(
            f"The human explicitly selected page_id(s) {pages_text} as the target of this "
            "revision -- see rule 8."
        )

    sections.extend(["", "Return the revision operations plan now, following the required JSON shape exactly."])

    return "\n".join(sections)


UIUX_REVISION_JSON_REPAIR_PROMPT = """
The previous response was not a valid revision operations plan. Return ONLY a corrected JSON
object matching the required {"revision_summary", "operations"} shape. No prose, no markdown
fences.
"""


def build_uiux_revision_json_repair_prompt(raw_output: str) -> str:
    return f"Previous invalid output:\n{raw_output}\n\nReturn the corrected revision operations plan now."


def build_component_quality_repair_prompt(html_code: str, violation: str) -> str:
    """
    Distinct from build_component_format_repair_prompt (output format issues): this is for a
    fragment that parsed fine but failed the content-quality gate -- it's empty, whitespace-only,
    or contains a generic placeholder message instead of real, populated example content.
    Feeding back the exact violation is far more targeted than a blind full regeneration.
    """

    return f"""
Your previously generated HTML fragment failed a content quality check:

{violation}

Your previous HTML fragment:
{html_code}

Fix the issue above. This fragment is a VISUAL REFERENCE that must always show the feature
working with realistic, fully-populated example content -- never an empty/loading/error/
placeholder message, and never Lorem Ipsum. Ground every piece of content in the real
content_elements and data entity fields you were given.

Return the complete corrected fragment now, in the exact required format (the marker plus a full
HTML fragment -- not a patch, not commentary).
"""
