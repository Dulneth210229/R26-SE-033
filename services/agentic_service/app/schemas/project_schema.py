"""
Project schemas.

These Pydantic models define the request and response shape
for project-related APIs.

A project represents the full target application, such as:
- E-commerce Platform
- LMS Platform
- CRM System
"""

from datetime import datetime
from pydantic import BaseModel, Field


class ProjectCreateRequest(BaseModel):
    """
    Request body for creating a project.

    user_id is NOT part of this request body -- it's stamped server-side from the
    authenticated caller (see app/api/routes/projects.py's create_project), never trusted from
    the client.
    """
    project_name: str = Field(..., example="E-commerce Platform")
    project_type: str = Field(..., example="E-commerce")
    target_stack: str = Field(default="Next.js", example="Next.js")
    created_by: str = Field(default="human_user", example="ba_user")


class ProjectUpdateRequest(BaseModel):
    """
    Request body for editing an existing project's details.

    All fields optional -- only the ones the user actually changed need to be sent.
    """
    project_name: str | None = Field(default=None, example="E-commerce Platform")
    project_type: str | None = Field(default=None, example="E-commerce")
    target_stack: str | None = Field(default=None, example="Next.js")


class ProjectResponse(BaseModel):
    """
    API response returned after creating or reading a project.
    """
    project_id: str
    project_name: str
    project_type: str
    target_stack: str
    created_by: str
    user_id: str | None = None
    created_at: datetime
    updated_at: datetime