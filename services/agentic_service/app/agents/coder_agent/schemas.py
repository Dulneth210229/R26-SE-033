"""
Coder Agent internal schemas.
"""

from pydantic import BaseModel


class CoderAgentInput(BaseModel):
    """
    Internal input passed to CoderAgent.

    Mirrors ArchitectureAgentInput/UIUXAgentInput's shape: the agent receives
    already-loaded context (not artifact IDs) so it does not need to know how
    those artifacts were located.
    """

    project: dict
    feature: dict
    srs_json: dict
    enhanced_srs_json: dict | None = None
    architecture_plan_json: dict
    ui_integration_manifest_json: dict | None = None
    project_manifest_json: dict
    human_comment: str | None = None


class CoderAgentOutput(BaseModel):
    """
    Internal output produced by CoderAgent.

    code_plan_json:
        The validated plan the coding loop executed.

    verification_passed:
        Whether the sandboxed build/lint/test gate passed after the last
        coding attempt. False means the human is looking at a diff that
        failed verification -- merge is still gated on their explicit
        approval, but the report must make this impossible to miss.

    file_tree_json / code_manifest_json / requirement_code_map_json /
    setup_instructions_markdown / merge_report_markdown:
        Deterministic outputs built by diff_builder.py from the real git diff
        -- never from the coding loop's self-report.
    """

    code_plan_json: dict
    verification_passed: bool
    file_tree_json: dict
    code_manifest_json: dict
    requirement_code_map_json: dict
    setup_instructions_markdown: str
    merge_report_markdown: str
    artifact_ids: list[str] = []


class CoderAgentEnvSaveResult(BaseModel):
    """
    Returned by CoderAgent.revise()/revise_stream() instead of
    CoderAgentOutput when a revision comment is JUST a MongoDB URI (see
    env_uri.py) -- a real, deliberate short-circuit around the normal
    plan/code/verify cycle, since nothing about the generated code changes.
    Deliberately not shoehorned into CoderAgentOutput's shape (no
    code_plan_json/diff/verification fields make sense here).
    """

    saved: bool
    preview_restarted: bool
    message: str
