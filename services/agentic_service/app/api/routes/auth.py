"""
Authentication routes.

Manual sign-up/sign-in (email + password) plus Google/GitHub OAuth. Every successful login
(password or OAuth) returns the same TokenResponse shape -- the frontend stores access_token
and sends it as an `Authorization: Bearer <access_token>` header on every subsequent request.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.schemas.user_schema import TokenResponse, UserCreateRequest, UserLoginRequest, UserResponse
from app.services import auth_service, oauth_service

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/register", response_model=TokenResponse)
def register(request: UserCreateRequest):
    """
    Create a new account and immediately sign in (returns a real access token, same as /login).
    """
    try:
        user = auth_service.create_user(
            email=request.email,
            password=request.password,
            contact_number=request.contact_number,
        )
    except auth_service.AuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    token = auth_service.create_access_token(user["user_id"])
    return TokenResponse(access_token=token, user=UserResponse(**user))


@router.post("/login", response_model=TokenResponse)
def login(request: UserLoginRequest):
    """
    Sign in with email + password.
    """
    try:
        user = auth_service.authenticate_user(request.email, request.password)
    except auth_service.AuthError as error:
        raise HTTPException(status_code=401, detail=str(error)) from error

    token = auth_service.create_access_token(user["user_id"])
    return TokenResponse(access_token=token, user=UserResponse(**user))


@router.get("/me", response_model=UserResponse)
def get_me(current_user: dict = Depends(get_current_user)):
    """
    Return the signed-in user's own record.
    """
    return UserResponse(**current_user)


@router.get("/google/login")
def google_login():
    """
    Redirect the browser to Google's OAuth consent screen.
    """
    try:
        return oauth_service.build_authorization_redirect("google")
    except oauth_service.OAuthNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/google/callback")
def google_callback(code: str, state: str | None = None):
    """
    Google redirects here after the user approves access. Exchanges the code, resolves/creates
    the account, then redirects to the frontend with a real access token.
    """
    try:
        return oauth_service.complete_login("google", code, state)
    except oauth_service.OAuthNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except oauth_service.OAuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@router.get("/github/login")
def github_login():
    """
    Redirect the browser to GitHub's OAuth consent screen.
    """
    try:
        return oauth_service.build_authorization_redirect("github")
    except oauth_service.OAuthNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/github/callback")
def github_callback(code: str, state: str | None = None):
    """
    GitHub redirects here after the user approves access. Exchanges the code, resolves/creates
    the account, then redirects to the frontend with a real access token.
    """
    try:
        return oauth_service.complete_login("github", code, state)
    except oauth_service.OAuthNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except oauth_service.OAuthError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
