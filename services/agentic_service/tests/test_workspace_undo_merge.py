"""
Unit tests for workspace_service.undo_merge_feature_branch -- reversing a real
merge_feature_branch call (recreate the feature branch at its pre-merge tip, revert the merge
commit on main via a real, non-destructive `git revert`) so an already-approved-and-merged Coder
Agent artifact's approval can genuinely be revoked. Real git repos via tmp_path (same fixture
convention as test_workspace_scaffold.py), no LLM/Docker.
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
    store.projects[pid] = {"project_id": pid, "project_name": f"Undo Merge Test {pid}"}

    yield pid

    repo_path = workspace_service.get_repo_path(pid)
    if (repo_path / ".git").exists():
        workspace_service.ensure_project_repo(pid).close()
    store.database["projects"].delete_one({"project_id": pid})
    if repo_path.parent.exists():
        shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def _seed_feature(project_id: str) -> str:
    feature_id = generate_id("feature")
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Undo Merge Test Feature",
    }
    return feature_id


def test_undo_merge_restores_branch_and_reverts_main(project_id):
    feature_id = _seed_feature(project_id)

    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "new_marker.ts").write_text("// real feature work", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "add new marker")
    workspace_service.merge_feature_branch(project_id, feature_id)

    repo = workspace_service.ensure_project_repo(project_id)
    assert repo.active_branch.name == "main"
    branch_name = f"feature/{workspace_service._feature_slug(feature_id)}"
    assert branch_name not in [head.name for head in repo.heads]
    assert (repo_path / "lib" / "new_marker.ts").exists()

    restored = workspace_service.undo_merge_feature_branch(project_id, feature_id)

    assert restored == branch_name
    # A real, non-destructive revert -- main gains a NEW commit, it isn't rewritten/reset away.
    assert repo.active_branch.name == "main"
    assert not (repo_path / "lib" / "new_marker.ts").exists()
    assert repo.head.commit.message.strip().startswith("Revert")

    # The feature branch is restored at its real pre-merge tip -- the work is not lost.
    assert branch_name in [head.name for head in repo.heads]
    restored_branch_tip = next(head for head in repo.heads if head.name == branch_name).commit
    restored_files = {item.path for item in restored_branch_tip.tree.traverse()}
    assert "lib/new_marker.ts" in restored_files

    store.database["features"].delete_one({"feature_id": feature_id})


def test_undo_merge_is_a_safe_no_op_when_no_merge_ever_happened(project_id):
    feature_id = _seed_feature(project_id)
    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "marker.ts").write_text("// never merged", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "work in progress")

    result = workspace_service.undo_merge_feature_branch(project_id, feature_id)

    assert result is None
    # Nothing on disk/git was touched -- the branch and its commit are exactly as left.
    repo = workspace_service.ensure_project_repo(project_id)
    branch_name = f"feature/{workspace_service._feature_slug(feature_id)}"
    assert branch_name in [head.name for head in repo.heads]

    store.database["features"].delete_one({"feature_id": feature_id})


def test_remerging_after_a_revert_with_no_new_commits_actually_restores_the_content(project_id):
    """
    Real, live-found bug: a plain `git merge --no-ff branch` after undo_merge_feature_branch's
    revert silently no-ops ("Already up to date") -- the branch's commits are still ancestors of
    main, even though the revert undid their effect, so git sees nothing new to merge. The
    artifact would end up marked approved with the code never actually landing on main. This
    reproduces the exact real sequence: merge -> revoke (revert) -> re-approve (merge again) with
    zero new commits in between -- confirms merge_feature_branch's own real-content check fixes it.
    """
    feature_id = _seed_feature(project_id)
    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "new_marker.ts").write_text("// real feature work", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "add new marker")
    workspace_service.merge_feature_branch(project_id, feature_id)
    assert (repo_path / "lib" / "new_marker.ts").exists()

    workspace_service.undo_merge_feature_branch(project_id, feature_id)
    assert not (repo_path / "lib" / "new_marker.ts").exists()

    # Re-approve the SAME code, no new commits -- this is the exact scenario that used to
    # silently no-op.
    workspace_service.merge_feature_branch(project_id, feature_id)

    assert (repo_path / "lib" / "new_marker.ts").exists()
    repo = workspace_service.ensure_project_repo(project_id)
    branch_name = f"feature/{workspace_service._feature_slug(feature_id)}"
    assert branch_name not in [head.name for head in repo.heads]

    store.database["features"].delete_one({"feature_id": feature_id})


def test_undo_merge_is_a_safe_no_op_for_a_feature_with_no_repo_history_at_all(project_id):
    feature_id = _seed_feature(project_id)
    workspace_service.ensure_project_repo(project_id)

    result = workspace_service.undo_merge_feature_branch(project_id, feature_id)

    assert result is None

    store.database["features"].delete_one({"feature_id": feature_id})
