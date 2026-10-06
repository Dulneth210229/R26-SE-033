"""
Unit tests for /projects/{project_id}/database-connection (app.api.routes.database_connection) --
the standalone entry point for saving/viewing/clearing a project's MongoDB connection string,
independent of any specific Coder Agent run. Real TestClient (established convention, see
test_feature_deletion.py), real workspace_service-backed .env.local on disk (no LLM/Docker).
"""

import os
import shutil
import stat

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id

client = TestClient(app)


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_id():
    pid = generate_id("project")
    store.projects[pid] = {"project_id": pid, "project_name": f"DB Connection Test {pid}"}

    yield pid

    repo_path = workspace_service.get_repo_path(pid)
    if (repo_path / ".git").exists():
        workspace_service.ensure_project_repo(pid).close()
    store.database["projects"].delete_one({"project_id": pid})
    if repo_path.parent.exists():
        shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_get_returns_404_for_unknown_project():
    response = client.get("/api/v1/projects/proj_does_not_exist/database-connection")
    assert response.status_code == 404


def test_get_reports_not_configured_when_unset(project_id):
    response = client.get(f"/api/v1/projects/{project_id}/database-connection")

    assert response.status_code == 200
    assert response.json() == {"configured": False, "masked_uri": None}


def test_put_rejects_a_non_mongodb_string(project_id):
    response = client.put(
        f"/api/v1/projects/{project_id}/database-connection", json={"mongodb_uri": "not a real uri"}
    )

    assert response.status_code == 400
    assert workspace_service.read_env_local(project_id) == {}


def test_put_saves_a_valid_uri_and_get_reflects_it_masked(project_id):
    uri = "mongodb+srv://myuser:s3cr3t@cluster0.abcde.mongodb.net/mydb"

    put_response = client.put(f"/api/v1/projects/{project_id}/database-connection", json={"mongodb_uri": uri})
    assert put_response.status_code == 200
    assert put_response.json()["configured"] is True
    assert "s3cr3t" not in put_response.json()["masked_uri"]

    # The raw value is never returned over the API, but IS genuinely saved to disk -- confirmed
    # directly via the real workspace_service, not just trusting the response.
    assert workspace_service.read_env_local(project_id) == {"MONGODB_URI": uri}

    get_response = client.get(f"/api/v1/projects/{project_id}/database-connection")
    assert get_response.json() == {
        "configured": True,
        "masked_uri": "mongodb+srv://***:***@cluster0.abcde.mongodb.net/mydb",
    }


def test_delete_clears_a_saved_uri(project_id):
    client.put(
        f"/api/v1/projects/{project_id}/database-connection",
        json={"mongodb_uri": "mongodb://localhost:27017/mydb"},
    )

    delete_response = client.delete(f"/api/v1/projects/{project_id}/database-connection")
    assert delete_response.status_code == 204

    assert workspace_service.read_env_local(project_id) == {}
    get_response = client.get(f"/api/v1/projects/{project_id}/database-connection")
    assert get_response.json() == {"configured": False, "masked_uri": None}


def test_delete_is_a_clean_no_op_when_nothing_was_ever_saved(project_id):
    response = client.delete(f"/api/v1/projects/{project_id}/database-connection")
    assert response.status_code == 204
