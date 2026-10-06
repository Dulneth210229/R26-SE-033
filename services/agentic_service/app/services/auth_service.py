"""
Authentication service.

Purpose:
- Hash/verify passwords (bcrypt, used directly -- already an installed dependency, avoids
  passlib's known friction with bcrypt>=4.1).
- Issue/verify JWT access tokens (PyJWT).
- Create/look up user records in store.users.

An OAuth-created account (Google/GitHub) has no password hash at all -- password_hash is None,
and authenticate_user() only ever applies to the email/password sign-in path.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


class AuthError(Exception):
    """Raised for any authentication failure (bad credentials, bad/expired token, etc.)."""


def hash_password(plain_password: str) -> str:
    return bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str:
    """
    Return the user_id encoded in a valid token, or raise AuthError.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as error:
        raise AuthError("Token has expired.") from error
    except jwt.InvalidTokenError as error:
        raise AuthError("Invalid token.") from error

    user_id = payload.get("sub")
    if not user_id:
        raise AuthError("Invalid token.")

    return user_id


def get_user_by_email(email: str) -> dict[str, Any] | None:
    document = store.users.collection.find_one({"email": email.lower()})
    if document is None:
        return None
    document.pop("_id", None)
    return document


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    return store.users.get(user_id)


def create_user(
    email: str,
    password: str | None = None,
    contact_number: str | None = None,
    name: str | None = None,
    profile_picture_url: str | None = None,
    auth_provider: str = "password",
) -> dict[str, Any]:
    """
    Create a new user record. Raises AuthError if the email is already registered.

    password is None for an OAuth-created account (no password to hash).
    """
    if get_user_by_email(email):
        raise AuthError("An account with this email already exists.")

    now = datetime.now(timezone.utc)
    user_id = generate_id("user")

    user = {
        "user_id": user_id,
        "email": email.lower(),
        "password_hash": hash_password(password) if password else None,
        "contact_number": contact_number,
        "name": name,
        "profile_picture_url": profile_picture_url,
        "auth_provider": auth_provider,
        "created_at": now,
        "updated_at": now,
    }

    store.users[user_id] = user

    return user


def authenticate_user(email: str, password: str) -> dict[str, Any]:
    """
    Verify email/password credentials. Raises AuthError on any failure -- deliberately the
    same generic message for "no such account" and "wrong password," so a login attempt never
    reveals which one was wrong (prevents account enumeration).
    """
    user = get_user_by_email(email)

    if not user or not user.get("password_hash"):
        raise AuthError("Invalid email or password.")

    if not verify_password(password, user["password_hash"]):
        raise AuthError("Invalid email or password.")

    return user


def get_or_create_oauth_user(
    email: str,
    auth_provider: str,
    name: str | None = None,
    profile_picture_url: str | None = None,
) -> dict[str, Any]:
    """
    Log in via an existing account (matched by email, regardless of how it was originally
    created) or create a new OAuth-only account. Never overwrites an existing password_hash.
    """
    existing = get_user_by_email(email)
    if existing:
        return existing

    return create_user(
        email=email,
        password=None,
        name=name,
        profile_picture_url=profile_picture_url,
        auth_provider=auth_provider,
    )
