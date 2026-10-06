"""
Agent schemas.

These schemas define request bodies for running agents.

Actual LLM logic will be added later.
For now, we define the input shape clearly.
"""

from pydantic import BaseModel, Field


class AgentRunRequest(BaseModel):
    """
    Generic request to run an agent.

    feature_id identifies which feature the agent should process.
    human_comment is optional and used during revision.
    """
    human_comment: str | None = Field(
        default=None,
        example="Add forgot password requirement."
    )


class AgentRunResponse(BaseModel):
    """
    Generic response after an agent run starts or completes.
    """
    feature_id: str
    agent_name: str
    status: str
    message: str
    artifact_ids: list[str] = []