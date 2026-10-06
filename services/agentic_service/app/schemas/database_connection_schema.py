"""
Per-project database-connection (MongoDB URI) schemas.

A project's real MongoDB connection string, once saved, is what makes every generated route that
already has the guarded `mongoose.models.X || mongoose.model(...)` / `connectToDatabase()`
fallback (see workspace_service.py's scaffold templates) automatically start serving real data
instead of seed data -- no code regeneration needed, since the branch is already the toggle (see
prompt.py's own "Database availability fallback" rule). This is the standalone entry point for
setting/clearing it, independent of any specific Coder Agent run/revision (see
coder_agent/env_uri.py for the other entry point: typing/pasting a URI directly into the Coder
Agent chat).
"""

from pydantic import BaseModel, Field


class DatabaseConnectionResponse(BaseModel):
    """
    Never includes the raw connection string -- only whether one is configured and a
    credential-redacted display value (see env_uri.mask_mongodb_uri). Mirrors this project's
    established "no reason to show a credential once it's been handled" security convention.
    """

    configured: bool
    masked_uri: str | None = Field(default=None, example="mongodb+srv://***:***@cluster0.xxx.mongodb.net/mydb")


class DatabaseConnectionSaveRequest(BaseModel):
    mongodb_uri: str = Field(
        ..., example="mongodb+srv://user:password@cluster0.xxx.mongodb.net/mydb?retryWrites=true"
    )
