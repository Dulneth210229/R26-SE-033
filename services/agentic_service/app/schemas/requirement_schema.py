"""
Requirement Agent API schemas.

These schemas define the structure of the BA input that will be sent
from Swagger or frontend to the Requirement Agent.

The Requirement Agent uses this data to generate:
- SRS Markdown
- SRS JSON

Important:
The user can also provide architectural_style here.
This does not mean the Requirement Agent generates architecture.
It only records the preferred architectural style as a requirement/design constraint.
"""

from pydantic import BaseModel, Field, field_validator

from app.core.enums import ArchitectureStyle


class RequirementBAInput(BaseModel):
    """
    Structured BA input for one feature.

    Example feature:
        Login

    Example project:
        E-commerce Platform

    The frontend or Swagger will send this object to the Requirement Agent.
    """

    project_type: str | None = Field(
        default=None,
        example="E-commerce",
        description="Type of application, such as E-commerce, LMS, CRM, SaaS."
    )

    feature_name: str | None = Field(
        default=None,
        example="Login",
        description="Name of the feature being developed."
    )

    target_stack: str | None = Field(
        default="Next.js",
        example="Next.js",
        description="Technology stack for the generated application."
    )

    architectural_style: ArchitectureStyle | str = Field(
        default=ArchitectureStyle.MODULAR,
        example="modular",
        description=(
            "Preferred architecture style. Examples: modular, monolithic, "
            "mvc, microservices, layered, clean_architecture."
        )
    )

    user_roles: list[str] = Field(
        default_factory=list,
        example=["Customer", "Admin"],
        description="User roles involved in this feature."
    )

    business_goal: str | None = Field(
        default=None,
        example="Allow registered users to securely access their account.",
        description="Business goal of this feature."
    )

    functional_requirements: list[str] = Field(
        default_factory=list,
        example=[
            "User can login using email and password",
            "System validates credentials",
            "System returns authentication token after successful login"
        ],
        description="Initial functional requirements from the user or BA."
    )

    non_functional_requirements: list[str] = Field(
        default_factory=list,
        example=[
            "Login response should be fast",
            "UI should be responsive",
            "Errors should be clear"
        ],
        description="Performance, usability, reliability, and other quality requirements."
    )

    acceptance_criteria: list[str] = Field(
        default_factory=list,
        example=[
            "Given valid credentials, the user should be logged in successfully."
        ],
        description="Optional acceptance criteria provided by the user."
    )

    ui_expectations: list[str] = Field(
        default_factory=list,
        example=[
            "Modern login form",
            "Responsive design",
            "Clear error messages"
        ],
        description="Initial UI expectations. UI/UX Agent will handle detailed UI later."
    )

    api_expectations: list[str] = Field(
        default_factory=list,
        example=[
            "POST /api/auth/login",
            "Return JWT token after successful login"
        ],
        description="Initial API expectations. Architecture Agent will refine this later."
    )

    data_requirements: list[str] = Field(
        default_factory=list,
        example=[
            "Email",
            "Password",
            "User role"
        ],
        description="Data needed by this feature."
    )

    constraints: list[str] = Field(
        default_factory=list,
        example=[
            "Use Next.js with TypeScript",
            "Use JWT authentication"
        ],
        description="Technical or business constraints."
    )

    assumptions: list[str] = Field(
        default_factory=list,
        example=[
            "User account already exists"
        ],
        description="Assumptions made for this feature."
    )

    @field_validator("architectural_style", mode="before")
    @classmethod
    def normalize_architectural_style(cls, value):
        """
        Normalize user input for architectural style.

        This lets the user type:
        - MVC
        - mvc
        - microservice
        - microservices
        - modular

        and still stores a consistent value.
        """
        if value is None:
            return ArchitectureStyle.MODULAR

        normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")

        aliases = {
            "microservice": "microservices",
            "micro_services": "microservices",
            "mvc_architecture": "mvc",
            "modular_architecture": "modular",
            "monolith": "monolithic",
            "monolithic_architecture": "monolithic",
            "clean": "clean_architecture",
            "clean_architecture": "clean_architecture",
        }

        normalized = aliases.get(normalized, normalized)

        allowed_values = {style.value for style in ArchitectureStyle}

        if normalized not in allowed_values:
            raise ValueError(
                "Invalid architectural_style. Allowed values are: "
                "modular, monolithic, mvc, microservices, layered, clean_architecture."
            )

        return normalized


class RequirementAgentRunRequest(BaseModel):
    """
    Request body for running the Requirement Agent.

    human_comment is useful when the user requests a revision.
    Example:
        "Add forgot password requirement."
    """

    ba_input: RequirementBAInput
    human_comment: str | None = Field(
        default=None,
        example="Add forgot password requirement."
    )

class RequirementAgentReviseRequest(BaseModel):
    """
    Request body for revising an existing SRS.

    This is used when the user reviews the SRS and asks for changes.

    Example:
        "Add forgot password requirement."
        "Add account lockout after 5 failed attempts."
        "Change architecture preference from MVC to modular."
    """

    revision_comment: str = Field(
        ...,
        example="Add forgot password requirement and related acceptance criteria."
    )

    revised_by: str = Field(
        default="human_user",
        example="human_user"
    )


