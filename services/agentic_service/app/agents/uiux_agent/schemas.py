"""
UI/UX Agent internal schemas.
"""

from pydantic import BaseModel


class UIUXAgentInput(BaseModel):
    """
    Internal input passed to UIUXAgent.

    Mirrors ArchitectureAgentInput's shape: the agent receives already-loaded
    context (not artifact IDs) so it does not need to know how those artifacts
    were located.
    """

    project: dict
    feature: dict
    srs_json: dict
    enhanced_srs_json: dict | None = None
    architecture_plan_json: dict
    design_system_json: dict
    ui_preferences: dict = {}
    human_comment: str | None = None


class UIUXAgentOutput(BaseModel):
    """
    Internal output produced by UIUXAgent.

    ui_metadata_json:
        Validated design-tokens + page/component tree, coverage-checked
        against the approved SRS.

    component_files:
        component name -> generated HTML fragment source text.

    page_html_files:
        page_id -> the fully-assembled, self-contained HTML document for that page (see
        page_html_builder.py) -- this is what a human previews live via <iframe srcDoc> and what
        the Coder Agent reads as a full-page visual reference.

    page_screenshots:
        page_id -> PNG bytes (one best-effort screenshot per page, for the "Page Previews"
        thumbnail gallery only -- secondary to page_html_files, never blocking).

    integration_manifest_json:
        Deterministic route/nav/content manifest for the future Coder Agent.

    ui_design_markdown:
        Human-readable summary for the approval reviewer.

    raw_llm_output:
        Original ui_metadata_json LLM output, for debugging.
    """

    ui_metadata_json: dict
    component_files: dict[str, str] = {}
    page_html_files: dict[str, str] = {}
    page_screenshots: dict[str, bytes] = {}
    integration_manifest_json: dict = {}
    ui_design_markdown: str = ""
    raw_llm_output: str
    artifact_ids: list[str] = []
