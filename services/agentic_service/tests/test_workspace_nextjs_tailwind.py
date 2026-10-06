"""
Unit tests for the Next.js scaffold's Tailwind CSS wiring (new scaffold files
+ globals.css directives + package.json devDependencies) and its idempotent
upgrade path for a project scaffolded before Tailwind was added -- confirmed
real bug: Tailwind utility classNames were inert, unprocessed class-name soup
with zero visual effect since nothing in the scaffold ever processed them.

Real git repos (same fixture/teardown convention as test_workspace_scaffold.py),
no LLM/Docker.
"""

import os
import shutil
import stat

import pytest

from app.services.in_memory_store import store
from app.services.workspace_service import NEXTJS_SCAFFOLD_FILES, workspace_service
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_id():
    pid = generate_id("project")
    store.projects[pid] = {"project_id": pid, "project_name": f"Tailwind Scaffold Test {pid}"}

    yield pid

    repo_path = workspace_service.get_repo_path(pid)
    if (repo_path / ".git").exists():
        workspace_service.ensure_project_repo(pid).close()
    store.database["projects"].delete_one({"project_id": pid})
    if repo_path.parent.exists():
        shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_fresh_project_has_tailwind_config_and_postcss_config(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    assert "tailwind.config.js" in NEXTJS_SCAFFOLD_FILES
    assert "postcss.config.mjs" in NEXTJS_SCAFFOLD_FILES
    assert (repo_path / "tailwind.config.js").exists()
    assert (repo_path / "postcss.config.mjs").exists()

    postcss = (repo_path / "postcss.config.mjs").read_text(encoding="utf-8")
    assert "tailwindcss" in postcss
    assert "export default" in postcss  # forces ESM regardless of package.json's own "type"


def test_fresh_project_globals_css_has_tailwind_directives(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    globals_css = (repo_path / "app" / "globals.css").read_text(encoding="utf-8")
    assert "@tailwind base;" in globals_css
    assert "@tailwind components;" in globals_css
    assert "@tailwind utilities;" in globals_css


def test_fresh_project_package_json_declares_tailwind_dev_dependencies(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    package_json = (repo_path / "package.json").read_text(encoding="utf-8")
    assert '"tailwindcss"' in package_json
    assert '"postcss"' in package_json
    assert '"autoprefixer"' in package_json


def test_upgrade_backfill_adds_tailwind_to_a_pre_tailwind_project(project_id):
    """
    Simulates a real, already-scaffolded (pre-Tailwind) Next.js project by
    stripping the Tailwind pieces back out after the first ensure_project_repo
    call, then confirming a second call (mirroring how a repo already on disk
    gets retrofitted automatically, per this project's own established
    scaffold-upgrade convention) restores them without touching customized
    content.
    """
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)
    repo = workspace_service.ensure_project_repo(project_id)

    # Simulate a pre-Tailwind repo: strip the tailwind config files, the
    # @tailwind directives, and the devDependencies, then commit that as
    # if it were the project's real prior state.
    (repo_path / "tailwind.config.js").unlink()
    (repo_path / "postcss.config.mjs").unlink()
    (repo_path / "app" / "globals.css").write_text(
        "body {\n  margin: 0;\n  color: hotpink; /* a real feature's own customization */\n}\n",
        encoding="utf-8",
    )
    import json

    package_json_path = repo_path / "package.json"
    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    data["devDependencies"].pop("tailwindcss", None)
    data["devDependencies"].pop("postcss", None)
    data["devDependencies"].pop("autoprefixer", None)
    package_json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # `git add -A` alone already stages the two deletions above (the files
    # were removed from disk with .unlink()) -- a separate index.remove()
    # call would fail since those paths are already gone from the index.
    repo.git.add(A=True)
    repo.index.commit("Simulate a pre-Tailwind project state")

    # Real retrofit path: calling ensure_project_repo again.
    workspace_service.ensure_project_repo(project_id)

    assert (repo_path / "tailwind.config.js").exists()
    assert (repo_path / "postcss.config.mjs").exists()

    globals_css = (repo_path / "app" / "globals.css").read_text(encoding="utf-8")
    assert "@tailwind base;" in globals_css
    # The feature's own customization must survive the upgrade untouched.
    assert "hotpink" in globals_css

    package_json = json.loads(package_json_path.read_text(encoding="utf-8"))
    assert "tailwindcss" in package_json["devDependencies"]
    assert "postcss" in package_json["devDependencies"]
    assert "autoprefixer" in package_json["devDependencies"]


def test_upgrade_backfill_is_idempotent_when_tailwind_already_present(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo = workspace_service.ensure_project_repo(project_id)
    before_sha = repo.head.commit.hexsha

    workspace_service.ensure_project_repo(project_id)
    repo_after = workspace_service.ensure_project_repo(project_id)

    assert repo_after.head.commit.hexsha == before_sha
    assert not repo_after.is_dirty(untracked_files=True)
