"""
Tests confirming a project (and everything scoped under it -- features, artifacts, agent
routes) created by one user is invisible to a different signed-in user, and that an ownerless
(pre-migration legacy, no user_id at all) project is still reachable by any signed-in user
rather than becoming permanently inaccessible the moment auth shipped.

Real TestClient(app), real Mongo writes with explicit teardown -- established convention. Every
TestClient constructed here defaults to a fixed fixture user's token (see conftest.py); this
file additionally creates a SECOND, distinct real user to prove cross-user isolation.
"""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import auth_service
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

OTHER_USER_EMAIL = "project_ownership_other_user@example.com"


@pytest.fixture
def other_user_client():
    """
    A second TestClient authenticated as a DIFFERENT real user than the default fixture user
    every other TestClient in this suite carries.
    """
    store.users.collection.delete_many({"email": OTHER_USER_EMAIL})
    user = auth_service.create_user(email=OTHER_USER_EMAIL, password="OtherPass1")
    token = auth_service.create_access_token(user["user_id"])

    other_client = TestClient(app)
    other_client.headers["Authorization"] = f"Bearer {token}"

    yield other_client

    store.users.collection.delete_many({"email": OTHER_USER_EMAIL})


@pytest.fixture
def owned_project():
    """
    A real project created THROUGH the API (as the default fixture user, via TestClient(app)'s
    conftest-attached token), so it has a real user_id stamped on it.
    """
    client = TestClient(app)
    response = client.post(
        "/api/v1/projects",
        json={"project_name": "Ownership Test Project", "project_type": "SaaS"},
    )
    assert response.status_code == 200
    project_id = response.json()["project_id"]

    yield project_id

    store.projects.collection.delete_one({"project_id": project_id})


@pytest.fixture
def ownerless_project():
    """
    A project seeded directly into the store with no user_id at all -- the shape every existing
    test fixture in this suite already uses, and the real shape pre-migration data has.
    """
    project_id = generate_id("proj")
    now = datetime.utcnow()
    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": "Ownerless Legacy Project",
        "project_type": "SaaS",
        "target_stack": "Next.js",
        "created_by": "human_user",
        "created_at": now,
        "updated_at": now,
    }

    yield project_id

    store.projects.collection.delete_one({"project_id": project_id})


def test_owner_can_see_their_own_project(owned_project):
    client = TestClient(app)
    response = client.get(f"/api/v1/projects/{owned_project}")
    assert response.status_code == 200
    assert response.json()["project_id"] == owned_project


def test_a_different_user_cannot_see_someone_elses_project(owned_project, other_user_client):
    response = other_user_client.get(f"/api/v1/projects/{owned_project}")
    assert response.status_code == 404


def test_a_different_user_cannot_list_someone_elses_project(owned_project, other_user_client):
    response = other_user_client.get("/api/v1/projects")
    assert response.status_code == 200
    ids = [p["project_id"] for p in response.json()]
    assert owned_project not in ids


def test_a_different_user_cannot_delete_someone_elses_project(owned_project, other_user_client):
    response = other_user_client.delete(f"/api/v1/projects/{owned_project}")
    assert response.status_code == 404

    still_there = store.projects.get(owned_project)
    assert still_there is not None


def test_unauthenticated_request_cannot_reach_a_project_at_all(owned_project):
    client = TestClient(app)
    response = client.get(f"/api/v1/projects/{owned_project}", headers={"Authorization": ""})
    assert response.status_code == 401


def test_an_ownerless_legacy_project_is_reachable_by_any_signed_in_user(ownerless_project, other_user_client):
    default_client_response = TestClient(app).get(f"/api/v1/projects/{ownerless_project}")
    other_user_response = other_user_client.get(f"/api/v1/projects/{ownerless_project}")

    assert default_client_response.status_code == 200
    assert other_user_response.status_code == 200


def test_a_feature_inside_someone_elses_project_is_also_invisible(owned_project, other_user_client):
    client = TestClient(app)
    feature_response = client.post(
        f"/api/v1/projects/{owned_project}/features",
        json={"feature_name": "Login", "feature_description": "Login feature"},
    )
    assert feature_response.status_code == 200
    feature_id = feature_response.json()["feature_id"]

    response = other_user_client.get(f"/api/v1/features/{feature_id}")
    assert response.status_code == 404

    agent_route_response = other_user_client.get(f"/api/v1/features/{feature_id}/agents/requirement/conversation")
    assert agent_route_response.status_code == 404

    store.features.collection.delete_one({"feature_id": feature_id})
