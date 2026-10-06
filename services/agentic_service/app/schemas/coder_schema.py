"""
Coder Agent API schema.
"""

from pydantic import BaseModel, Field


class CoderAgentRunRequest(BaseModel):
    """
    Request body for running Coder Agent.
    """

    use_enhanced_srs_if_available: bool = Field(
        default=True,
        description="Use approved Enhanced SRS if it exists."
    )

    human_comment: str | None = Field(
        default=None,
        example="Implement the Login feature."
    )


class CoderAgentReviseRequest(BaseModel):
    """
    Request body for revising the latest Coder Agent output.

    Unlike CoderAgentRunRequest, this always builds on the existing feature
    branch (never resets it) -- a revision is a targeted change on top of
    already-verified work, not a fresh attempt at the same plan.

    Example:
        "Add a loading spinner while comments are being fetched."
        "The delete button doesn't call the API -- fix it."
    """

    revision_comment: str = Field(
        ...,
        example="Add basic client-side validation to the signup form."
    )

    revised_by: str = Field(
        default="human_user",
        example="human_user"
    )
