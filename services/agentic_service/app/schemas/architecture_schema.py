"""
Architecture Agent API schemas.

The Architecture Agent generates:
- Architecture Plan JSON
- Architecture Plan Markdown
- Use Case Diagram PlantUML/PNG
- Sequence Diagram PlantUML/PNG
- Class Diagram PlantUML/PNG

Important:
The user asked not to generate a separate API contract.
"""

from pydantic import BaseModel, Field


class ArchitectureAgentRunRequest(BaseModel):
    """
    Request body for running Architecture Agent.
    """

    use_enhanced_srs_if_available: bool = Field(
        default=True,
        description="Use approved Enhanced SRS if it exists."
    )

    architecture_notes: str | None = Field(
        default=None,
        example="Use MVC style and keep the feature simple for a Next.js implementation."
    )

    human_comment: str | None = Field(
        default=None,
        example="Generate Architecture Plan and UML diagrams for Login feature."
    )


class ArchitectureAgentReviseRequest(BaseModel):
    """
    Request body for revising the latest Architecture Plan.

    The revision can ask for changes in:
    - Architecture Plan content
    - Use Case Diagram behaviour
    - Sequence Diagram flow
    - Class Diagram entities/classes

    Diagram files are not manually edited. Instead, the Architecture Plan is
    revised and the diagrams are regenerated from the revised plan using the
    existing deterministic diagram generation pipeline.
    """

    revision_comment: str = Field(
        ...,
        example="Update the sequence diagram to include account lockout after failed login attempts."
    )

    revised_by: str = Field(
        default="human_user",
        example="human_user"
    )
