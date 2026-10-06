"""
Unit tests for WorkspaceService.get_touched_files' `since` parameter -- the
core fix for a real, confirmed false-success bug: comparing a coding
attempt's touched files against `main` unconditionally is only correct for a
file's FIRST-EVER revision. Once any earlier revision has touched a file, it
permanently differs from `main` forever after, so a later attempt that makes
ZERO real changes still looks like it "touched" every previously-touched
file -- exactly what let a real no-op revision silently report
"verification: PASSED". Real git repos (same fixture/teardown convention as
test_workspace_env_local.py), no LLM/Docker.
"""

import os
import shutil
import stat

import pytest

from app.services.in_memory_store import store
from app.services.workspace_service import MAIN_BRANCH, workspace_service
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_and_feature():
    pid = generate_id("project")
    fid = generate_id("feature")
    store.projects[pid] = {"project_id": pid, "project_name": f"Touched Files Since Test {pid}"}
    store.features[fid] = {
        "project_id": pid,
        "feature_id": fid,
        "feature_name": "Touched Files Since Feature",
    }

    yield pid, fid

    repo_path = workspace_service.get_repo_path(pid)
    if (repo_path / ".git").exists():
        workspace_service.ensure_project_repo(pid).close()
    store.database["projects"].delete_one({"project_id": pid})
    store.database["features"].delete_one({"feature_id": fid})
    if repo_path.parent.exists():
        shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_get_touched_files_defaults_to_comparing_against_main(project_and_feature):
    project_id, feature_id = project_and_feature
    workspace_service.start_feature_branch(project_id, feature_id)

    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "app" / "new-file.txt").write_text("hello", encoding="utf-8")

    touched = workspace_service.get_touched_files(project_id, feature_id)
    assert "app/new-file.txt" in touched["added"]


def test_get_touched_files_since_a_later_sha_excludes_earlier_revisions_changes(project_and_feature):
    """
    The exact scenario that caused the real bug: attempt 1 touches a file and
    commits; attempt 2 (a later revision) makes NO new changes at all. Diffing
    against `main` (the old, unconditional default) would still show the file
    as touched, since it was never reverted -- diffing against attempt 2's own
    starting SHA correctly shows nothing touched.
    """
    project_id, feature_id = project_and_feature
    workspace_service.start_feature_branch(project_id, feature_id)

    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "app" / "page.tsx").write_text("// attempt 1 change", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, message="attempt 1")

    repo = workspace_service.ensure_project_repo(project_id)
    revision_start_sha = repo.head.commit.hexsha

    # attempt 2 makes zero further changes -- nothing written, nothing committed.

    touched_since_main = workspace_service.get_touched_files(project_id, feature_id)
    assert "app/page.tsx" in touched_since_main["modified"]

    touched_since_revision_start = workspace_service.get_touched_files(
        project_id, feature_id, since=revision_start_sha
    )
    assert touched_since_revision_start == {"added": [], "modified": [], "deleted": []}


def test_get_touched_files_since_still_detects_real_new_changes(project_and_feature):
    project_id, feature_id = project_and_feature
    workspace_service.start_feature_branch(project_id, feature_id)

    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "app" / "page.tsx").write_text("// attempt 1 change", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, message="attempt 1")

    repo = workspace_service.ensure_project_repo(project_id)
    revision_start_sha = repo.head.commit.hexsha

    (repo_path / "app" / "globals.css").write_text("/* attempt 2 change */", encoding="utf-8")

    touched = workspace_service.get_touched_files(project_id, feature_id, since=revision_start_sha)
    assert "app/globals.css" in touched["modified"]
    assert "app/page.tsx" not in touched["modified"]


def test_get_touched_files_since_defaults_to_main_branch_constant(project_and_feature):
    project_id, feature_id = project_and_feature
    workspace_service.start_feature_branch(project_id, feature_id)

    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "app" / "new-file.txt").write_text("hello", encoding="utf-8")

    explicit = workspace_service.get_touched_files(project_id, feature_id, since=MAIN_BRANCH)
    default = workspace_service.get_touched_files(project_id, feature_id)
    assert explicit == default
