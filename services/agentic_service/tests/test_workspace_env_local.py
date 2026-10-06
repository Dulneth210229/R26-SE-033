"""
Unit tests for WorkspaceService.write_env_local/read_env_local -- the only
realistic way a human-provided value (e.g. a MongoDB URI) can ever reach a
generated app, since sandbox/preview containers never see host env vars and
Docker cannot inject one into an already-running container (see env_uri.py's
module docstring). Real git repos (same fixture/teardown convention as
test_workspace_scaffold.py), no LLM/Docker.
"""

import os
import shutil
import stat

import pytest

from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_id():
    pid = generate_id("project")
    store.projects[pid] = {"project_id": pid, "project_name": f"Env Local Test {pid}"}

    yield pid

    repo_path = workspace_service.get_repo_path(pid)
    if (repo_path / ".git").exists():
        workspace_service.ensure_project_repo(pid).close()
    store.database["projects"].delete_one({"project_id": pid})
    if repo_path.parent.exists():
        shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_read_env_local_returns_empty_dict_when_absent(project_id):
    assert workspace_service.read_env_local(project_id) == {}


def test_write_env_local_creates_file_and_is_readable(project_id):
    changed = workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db"})

    assert changed is True
    assert workspace_service.read_env_local(project_id) == {"MONGODB_URI": "mongodb://localhost/db"}


def test_write_env_local_creates_workspace_if_it_does_not_exist_yet(project_id):
    # No ensure_project_repo() call first -- must work even before any Coder Agent run has ever
    # created the workspace (e.g. a URI arriving on the very first chat message).
    repo_path = workspace_service.get_repo_path(project_id)
    assert not repo_path.exists()

    workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db"})

    assert (repo_path / ".env.local").exists()


def test_write_env_local_merges_preserving_other_keys(project_id):
    workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db", "FOO": "bar"})
    workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://otherhost/db"})

    values = workspace_service.read_env_local(project_id)
    assert values == {"MONGODB_URI": "mongodb://otherhost/db", "FOO": "bar"}


def test_write_env_local_returns_false_when_nothing_changes(project_id):
    workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db"})
    changed = workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db"})

    assert changed is False


def test_remove_env_local_keys_returns_false_when_file_absent(project_id):
    assert workspace_service.remove_env_local_keys(project_id, ["MONGODB_URI"]) is False


def test_remove_env_local_keys_returns_false_when_key_not_present(project_id):
    workspace_service.write_env_local(project_id, {"FOO": "bar"})
    assert workspace_service.remove_env_local_keys(project_id, ["MONGODB_URI"]) is False
    assert workspace_service.read_env_local(project_id) == {"FOO": "bar"}


def test_remove_env_local_keys_removes_only_the_given_key(project_id):
    workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db", "FOO": "bar"})

    changed = workspace_service.remove_env_local_keys(project_id, ["MONGODB_URI"])

    assert changed is True
    assert workspace_service.read_env_local(project_id) == {"FOO": "bar"}


def test_remove_env_local_keys_leaves_the_file_present_but_empty(project_id):
    workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db"})
    workspace_service.remove_env_local_keys(project_id, ["MONGODB_URI"])

    env_path = workspace_service.get_repo_path(project_id) / ".env.local"
    assert env_path.exists()
    assert workspace_service.read_env_local(project_id) == {}


def test_env_local_is_gitignored_and_never_committed(project_id):
    workspace_service.write_env_local(project_id, {"MONGODB_URI": "mongodb://localhost/db"})
    repo = workspace_service.ensure_project_repo(project_id)

    # .env.local must never show up as an untracked file (it's covered by the scaffold's own
    # .gitignore, see NEXTJS_GITIGNORE) -- if this ever regresses, a real MongoDB credential
    # could end up committed.
    assert ".env.local" not in repo.untracked_files
    assert not repo.is_dirty(untracked_files=True)
