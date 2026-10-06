"""
Shared FastAPI dependencies.

Purpose:
get_current_user resolves the Authorization: Bearer <token> header into a real user record --
the first use of FastAPI's Depends() in this codebase (every other route file uses plain
function calls, e.g. agents.py's _validate_feature). Route handlers add
`current_user: dict = Depends(get_current_user)` to require a signed-in caller.
"""

from __future__ import annotations

from typing import Any

from fastapi import Header, HTTPException, Query

from app.services import auth_service


def get_current_user(
    authorization: str | None = Header(default=None),
    token: str | None = Query(default=None),
) -> dict[str, Any]:
    """
    Decode/verify the JWT and return the corresponding user record. Raises 401 if it's missing,
    malformed, or invalid/expired -- or if it's valid but no longer refers to an existing user
    (e.g. deleted account).

    Accepts the token two ways: the normal `Authorization: Bearer <token>` header (every axios/
    fetch call from the frontend), OR a `?token=` query parameter -- needed because a plain
    `<img src>`/`<a href>` (artifact content/download/PDF/code-zip URLs) can't attach a custom
    header at all. The query-param path is used ONLY where the frontend has no other way to
    authenticate the request; every fetch/axios-driven call keeps using the header.
    """
    if authorization and authorization.startswith("Bearer "):
        raw_token = authorization.removeprefix("Bearer ").strip()
    elif token:
        raw_token = token
    else:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    try:
        user_id = auth_service.decode_access_token(raw_token)
    except auth_service.AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error

    user = auth_service.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User no longer exists.")

    return user
