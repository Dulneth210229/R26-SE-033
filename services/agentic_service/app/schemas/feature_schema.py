"""
Feature schemas.

A feature is one SDLC unit.

Examples:
- Login
- Signup
- Product Listing
- Cart
- Checkout

Each feature goes through all agents one by one.
"""

from datetime import datetime
from pydantic import BaseModel, Field
from app.core.enums import FeatureStatus, AgentName


class FeatureCreateRequest(BaseModel):
    """
    Request body for creating a new feature inside a project.
    """
    feature_name: str = Field(..., example="Login")
    feature_description: str = Field(
        ...,
        example="Allow users to login using email and password."
    )


class FeatureResponse(BaseModel):
    """
    API response for a feature.
    """
    feature_id: str
    project_id: str
    feature_name: str
    feature_description: str
    feature_status: FeatureStatus
    current_agent: AgentName | None
    created_at: datetime
    updated_at: datetime
    # Maps artifact_type -> artifact_id, e.g. {"srs": "artifact_xyz"} -- lets a human explicitly
    # pin which APPROVED version of a given artifact_type feeds the next stage (e.g. which SRS
    # version the Domain Agent reads), instead of always defaulting to the latest approved version
    # by version number. Missing/empty for every feature created before this existed -- callers
    # must treat an absent entry as "use the default (latest approved)", never as an error.
    active_artifact_selection: dict[str, str] = Field(default_factory=dict)


class SetActiveArtifactSelectionRequest(BaseModel):
    """
    Request body for pinning which approved artifact version of one artifact_type should feed
    the next pipeline stage for this feature.
    """
    artifact_type: str = Field(..., example="srs")
    artifact_id: str = Field(..., example="artifact_5615cbda")