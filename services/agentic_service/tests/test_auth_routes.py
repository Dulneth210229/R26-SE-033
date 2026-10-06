"""
Tests for auth routes -- register/login/me, duplicate-email rejection, wrong-password
rejection, and missing/expired/invalid-token rejection.

Real TestClient(app) against the real app object, real Mongo writes with explicit teardown --
established convention (see test_approval_revoke_route.py). Every TestClient constructed here
already carries a default Authorization header for a fixed fixture user (see conftest.py) --
tests that specifically need to exercise UNAUTHENTICATED behavior override that per-call with
an empty Authorization header.
"""

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services.in_memory_store import store

client = TestClient(app)

TEST_EMAIL = "auth_route_test_user@example.com"


@pytest.fixture(autouse=True)
def _cleanup():
    store.users.collection.delete_many({"email": TEST_EMAIL})
    yield
    store.users.collection.delete_many({"email": TEST_EMAIL})


def _register():
    return client.post(
        "/api/v1/auth/register",
        json={
            "email": TEST_EMAIL,
            "contact_number": "+1 555-000-0000",
            "password": "Passw0rd1",
            "confirm_password": "Passw0rd1",
        },
    )


def test_register_creates_a_real_account_and_returns_a_usable_token():
    response = _register()

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == TEST_EMAIL
    assert "password_hash" not in body["user"]
    assert body["token_type"] == "bearer"

    stored = store.users.collection.find_one({"email": TEST_EMAIL})
    assert stored is not None
    assert stored["password_hash"] != "Passw0rd1"  # never stored in plain text


def test_register_rejects_mismatched_confirm_password():
    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": TEST_EMAIL,
            "contact_number": "+1 555-000-0000",
            "password": "Passw0rd1",
            "confirm_password": "SomethingElse2",
        },
    )
    assert response.status_code == 422


def test_register_rejects_a_duplicate_email():
    first = _register()
    assert first.status_code == 200

    second = _register()
    assert second.status_code == 400
    assert "already exists" in second.json()["detail"]


def test_login_with_correct_credentials_succeeds():
    _register()

    response = client.post("/api/v1/auth/login", json={"email": TEST_EMAIL, "password": "Passw0rd1"})
    assert response.status_code == 200
    assert response.json()["user"]["email"] == TEST_EMAIL


def test_login_with_wrong_password_is_rejected():
    _register()

    response = client.post("/api/v1/auth/login", json={"email": TEST_EMAIL, "password": "WrongPassword9"})
    assert response.status_code == 401


def test_login_with_unknown_email_is_rejected_with_the_same_message_as_wrong_password():
    """
    Never reveals whether the account exists -- the exact same generic message both times
    prevents account enumeration.
    """
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody-here@example.com", "password": "whatever1"})

    _register()
    wrong_password = client.post("/api/v1/auth/login", json={"email": TEST_EMAIL, "password": "WrongPassword9"})

    assert unknown.status_code == 401
    assert wrong_password.status_code == 401
    assert unknown.json()["detail"] == wrong_password.json()["detail"]


def test_me_requires_authentication():
    response = client.get("/api/v1/auth/me", headers={"Authorization": ""})
    assert response.status_code == 401


def test_me_returns_the_signed_in_user():
    token = _register().json()["access_token"]

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["email"] == TEST_EMAIL


def test_me_rejects_a_garbage_token():
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401


def test_me_rejects_an_expired_token():
    _register()
    user_id = store.users.collection.find_one({"email": TEST_EMAIL})["user_id"]

    now = datetime.now(timezone.utc)
    expired_payload = {"sub": user_id, "iat": now - timedelta(days=8), "exp": now - timedelta(days=1)}
    expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert response.status_code == 401
