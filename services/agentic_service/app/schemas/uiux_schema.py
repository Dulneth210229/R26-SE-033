"""
UI/UX Agent API schema.
"""

from pydantic import BaseModel, Field


class UIUXAgentRunRequest(BaseModel):
    """
    Request body for running UI/UX Agent.
    """

    use_enhanced_srs_if_available: bool = Field(
        default=True,
        description="Use approved Enhanced SRS if it exists."
    )

    ui_preferences: dict = Field(
        default_factory=dict,
        description="Optional free-form UI preferences (theme, tone, layout hints).",
    )

    human_comment: str | None = Field(
        default=None,
        example="Generate UI metadata for the Login feature."
    )


class UIUXAgentReviseRequest(BaseModel):
    """
    Request body for revising already-generated UI/UX Agent output.
    """

    revision_comment: str = Field(
        ...,
        example="Add a 'no items found' empty state message to the item list component.",
    )

    revised_by: str | None = Field(
        default=None,
        description="Optional identifier of who requested the revision.",
    )

    target_page_ids: list[str] | None = Field(
        default=None,
        description=(
            "Optional page_ids to explicitly scope this revision to, when a feature has more "
            "than one page/UI -- lets a human pick one or more specific pages rather than "
            "relying on the LLM to infer scope from the comment's prose alone. Every operation "
            "resolving to a page outside this set is deterministically rejected (never silently "
            "applied), not just discouraged by the prompt. None/empty means unconstrained -- the "
            "whole feature."
        ),
        example=["item-listing-page"],
    )
