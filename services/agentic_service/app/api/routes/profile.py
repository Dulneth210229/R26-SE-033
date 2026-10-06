"""
Profile routes.

Every route here is scoped to the signed-in caller's OWN record only (current_user["user_id"])
-- there is no "update any user" path, so a user can never modify another account's profile.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.schemas.user_schema import PasswordUpdateRequest, ProfileUpdateRequest, UserResponse
from app.services import auth_service
from app.services.in_memory_store import store

router = APIRouter(prefix="/profile", tags=["Profile"])


@router.get("", response_model=UserResponse)
def get_profile(current_user: dict = Depends(get_current_user)):
    """
    Return the signed-in user's own profile.
    """
    return UserResponse(**current_user)


@router.put("", response_model=UserResponse)
def update_profile(request: ProfileUpdateRequest, current_user: dict = Depends(get_current_user)):
    """
    Update the signed-in user's own name/contact number/profile picture. Only the fields
    provided are changed.
    """
    user = store.users.get(current_user["user_id"])

    if request.name is not None:
        user["name"] = request.name

    if request.contact_number is not None:
        user["contact_number"] = request.contact_number

    if request.profile_picture_url is not None:
        user["profile_picture_url"] = request.profile_picture_url

    user["updated_at"] = datetime.now(timezone.utc)

    return UserResponse(**user)


@router.put("/password", status_code=204)
def update_password(request: PasswordUpdateRequest, current_user: dict = Depends(get_current_user)):
    """
    Change the signed-in user's own password. Rejected for an OAuth-only account (no existing
    password to confirm against) and when the current password doesn't match.
    """
    if not current_user.get("password_hash"):
        raise HTTPException(
            status_code=400,
            detail="This account signed in via Google/GitHub and has no password to change.",
        )

    if not auth_service.verify_password(request.current_password, current_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Current password is incorrect.")

    user = store.users.get(current_user["user_id"])
    user["password_hash"] = auth_service.hash_password(request.new_password)
    user["updated_at"] = datetime.now(timezone.utc)
