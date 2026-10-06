"""
Google/GitHub OAuth service.

Purpose:
Standard OAuth2 authorization-code flow for both providers, built on requests_oauthlib
(already an installed dependency -- no new library needed). The `state` parameter is a
short-lived, self-signed JWT (reusing the same SECRET_KEY as regular access tokens, under a
distinct "purpose" claim) rather than a server-side session store, since this backend has none
today -- this still gives real CSRF protection: a callback with a missing/expired/tampered
state is rejected before any account is created or logged into.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi.responses import RedirectResponse
from requests_oauthlib import OAuth2Session

from app.core.config import settings
from app.services import auth_service

_STATE_PURPOSE = "oauth_state"
_STATE_EXPIRE_MINUTES = 10

PROVIDER_CONFIG: dict[str, dict[str, Any]] = {
    "google": {
        "authorization_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": ["openid", "email", "profile"],
    },
    "github": {
        "authorization_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "userinfo_url": "https://api.github.com/user",
        "scope": ["read:user", "user:email"],
    },
}


class OAuthError(Exception):
    """Raised when an OAuth callback can't be completed (bad state, bad code, no email, ...)."""


class OAuthNotConfiguredError(Exception):
    """Raised when a provider's client id/secret haven't been set in .env yet."""


def _get_credentials(provider: str) -> tuple[str, str]:
    if provider == "google":
        client_id, client_secret = settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    else:
        client_id, client_secret = settings.GITHUB_CLIENT_ID, settings.GITHUB_CLIENT_SECRET

    if not client_id or not client_secret:
        raise OAuthNotConfiguredError(
            f"{provider.title()} sign-in isn't configured on this server yet -- "
            f"{provider.upper()}_CLIENT_ID/{provider.upper()}_CLIENT_SECRET are missing from .env."
        )

    return client_id, client_secret


def _redirect_uri(provider: str) -> str:
    return f"{settings.BACKEND_BASE_URL}{settings.API_PREFIX}/auth/{provider}/callback"


def _sign_state() -> str:
    now = datetime.now(timezone.utc)
    payload = {"purpose": _STATE_PURPOSE, "iat": now, "exp": now + timedelta(minutes=_STATE_EXPIRE_MINUTES)}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _verify_state(state: str | None) -> None:
    if not state:
        raise OAuthError("Missing OAuth state -- please try signing in again.")
    try:
        payload = jwt.decode(state, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.InvalidTokenError as error:
        raise OAuthError("This sign-in link has expired -- please try again.") from error
    if payload.get("purpose") != _STATE_PURPOSE:
        raise OAuthError("Invalid OAuth state -- please try signing in again.")


def build_authorization_redirect(provider: str) -> RedirectResponse:
    client_id, _ = _get_credentials(provider)
    config = PROVIDER_CONFIG[provider]

    session = OAuth2Session(client_id, scope=config["scope"], redirect_uri=_redirect_uri(provider))
    authorization_url, _ = session.authorization_url(config["authorization_url"], state=_sign_state())

    return RedirectResponse(authorization_url)


def _fetch_userinfo(provider: str, session: OAuth2Session) -> tuple[str, str | None, str | None]:
    """
    Return (email, name, profile_picture_url). Raises OAuthError if no usable email is found.
    """
    config = PROVIDER_CONFIG[provider]
    response = session.get(config["userinfo_url"], headers={"Accept": "application/json"})
    response.raise_for_status()
    profile = response.json()

    if provider == "google":
        email = profile.get("email")
        name = profile.get("name")
        picture = profile.get("picture")
    else:
        email = profile.get("email")
        name = profile.get("name") or profile.get("login")
        picture = profile.get("avatar_url")

        # GitHub only returns `email` on /user if the account's primary email is public --
        # fall back to /user/emails (granted by the "user:email" scope) for the verified
        # primary address otherwise.
        if not email:
            emails_response = session.get("https://api.github.com/user/emails", headers={"Accept": "application/json"})
            emails_response.raise_for_status()
            for entry in emails_response.json():
                if entry.get("primary") and entry.get("verified"):
                    email = entry.get("email")
                    break

    if not email:
        raise OAuthError(
            f"Your {provider.title()} account has no accessible email address -- "
            "sign in with a provider/account that has a verified email, or use manual sign-up."
        )

    return email, name, picture


def complete_login(provider: str, code: str, state: str | None) -> RedirectResponse:
    _verify_state(state)

    client_id, client_secret = _get_credentials(provider)
    config = PROVIDER_CONFIG[provider]

    session = OAuth2Session(client_id, redirect_uri=_redirect_uri(provider))

    try:
        session.fetch_token(
            config["token_url"],
            code=code,
            client_secret=client_secret,
            headers={"Accept": "application/json"},
        )
        email, name, picture = _fetch_userinfo(provider, session)
    except OAuthError:
        raise
    except Exception as error:
        raise OAuthError(f"{provider.title()} sign-in failed: {error}") from error

    user = auth_service.get_or_create_oauth_user(
        email=email,
        auth_provider=provider,
        name=name,
        profile_picture_url=picture,
    )
    token = auth_service.create_access_token(user["user_id"])

    return RedirectResponse(f"{settings.OAUTH_REDIRECT_BASE_URL}/auth/callback#token={token}")
