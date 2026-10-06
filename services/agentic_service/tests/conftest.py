"""
Test-suite-wide setup.

Every existing test in this suite constructs `client = TestClient(app)` at module level and
calls it with no Authorization header, since the whole backend was unauthenticated when they
were written. Rather than touch every one of those files individually, this module patches
`TestClient.__init__` (BEFORE any test module is imported -- pytest always imports conftest.py
first) so every TestClient instance carries a default `Authorization: Bearer <token>` header for
one real, fixed test-fixture user, the same way passing `headers=` to `httpx.Client()` would --
a per-call `headers=` a test explicitly passes still overrides this on that one call, exactly
httpx's normal client-default-vs-per-request-header merge behavior.

A test that specifically wants to exercise UNAUTHENTICATED behavior (a real 401) does so
explicitly, e.g. `client.get(url, headers={"Authorization": ""})` -- see
tests/test_auth_routes.py.

The fixture user's own user_id is intentionally fixed/known (not random per test run) so
anything that inspects `store.projects[...]["user_id"]`/etc. in an existing test sees a stable
value across runs.
"""

from starlette.testclient import TestClient

from app.services import auth_service

TEST_FIXTURE_USER_EMAIL = "test-fixture-user@autoforge.local"


def _ensure_test_fixture_user() -> dict:
    existing = auth_service.get_user_by_email(TEST_FIXTURE_USER_EMAIL)
    if existing:
        return existing

    return auth_service.create_user(
        email=TEST_FIXTURE_USER_EMAIL,
        password="TestFixture1",
        name="Test Fixture User",
    )


_test_user = _ensure_test_fixture_user()
_test_token = auth_service.create_access_token(_test_user["user_id"])

TEST_FIXTURE_USER_ID = _test_user["user_id"]

_original_init = TestClient.__init__


def _patched_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self.headers["Authorization"] = f"Bearer {_test_token}"


TestClient.__init__ = _patched_init
