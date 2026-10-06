"""
ID generator utility.

This creates unique IDs for:
- projects
- features
- artifacts
- approvals

For MVP, UUID is enough.
Later, this can be replaced with database-generated IDs.
"""

from uuid import uuid4


def generate_id(prefix: str) -> str:
    """
    Generate a readable unique ID.

    Example:
        generate_id("proj") -> "proj_6f8a9c2b"
    """
    short_id = uuid4().hex[:8]
    return f"{prefix}_{short_id}"