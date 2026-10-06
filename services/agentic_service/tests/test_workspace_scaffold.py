"""
Unit tests for workspace_service's deterministic runnable scaffold (Next.js
App Router + TypeScript by default) and its idempotent backfill into repos
that predate a given scaffold file.

Also covers _detect_stack and the legacy-MERN freeze path: a repo already on
the old Express+Vite convention (e.g. the real, pre-migration
e-commerce-platform/taskflow projects) must only ever get MERN backfills,
never Next.js files written alongside it.

No LLM, no Docker -- these only assert on-disk file presence/content and git
history, not runnability (verify.py's tests cover the real npm-install/boot/
build proof).
"""

import os
import shutil
import stat

import pytest

from app.services.in_memory_store import store
from app.services.workspace_service import (
    MERN_SCAFFOLD_FILES,
    NEXTJS_SCAFFOLD_FILES,
    _LEGACY_CLIENT_APP_JSX_V1,
    _LEGACY_SERVER_APP_JS_V1,
    _LEGACY_SERVER_SERVER_JS_V1,
    workspace_service,
)
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project_id():
    pid = generate_id("project")
    store.projects[pid] = {"project_id": pid, "project_name": f"Scaffold Test {pid}"}

    yield pid

    repo_path = workspace_service.get_repo_path(pid)
    if (repo_path / ".git").exists():
        workspace_service.ensure_project_repo(pid).close()
    store.database["projects"].delete_one({"project_id": pid})
    if repo_path.parent.exists():
        shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_fresh_project_gets_full_nextjs_scaffold_on_disk(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    for relative_path in NEXTJS_SCAFFOLD_FILES:
        assert (repo_path / relative_path).exists(), f"missing {relative_path}"

    # The legacy MERN scaffold must never appear alongside it.
    assert not (repo_path / "server").exists()
    assert not (repo_path / "client").exists()


def test_scaffold_committed_on_main(project_id):
    repo = workspace_service.ensure_project_repo(project_id)

    assert repo.active_branch.name == "main"
    assert not repo.is_dirty(untracked_files=True)

    committed_files = repo.git.ls_tree("-r", "--name-only", "HEAD").splitlines()
    for relative_path in NEXTJS_SCAFFOLD_FILES:
        assert relative_path in committed_files
    assert ".gitignore" in committed_files


def test_gitignore_covers_next_build_output_and_env_files(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    gitignore = (repo_path / ".gitignore").read_text(encoding="utf-8")
    assert ".next/" in gitignore
    assert "node_modules/" in gitignore
    assert ".env*.local" in gitignore
    assert "*.tsbuildinfo" in gitignore


def test_scaffold_uses_pinned_nextjs_version_and_exposes_health_route(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    package_json = (repo_path / "package.json").read_text(encoding="utf-8")
    assert '"next": "14.2.5"' in package_json
    assert '"^' not in package_json.split('"next"')[1].split(",")[0]

    health_route = (repo_path / "app" / "api" / "health" / "route.ts").read_text(encoding="utf-8")
    assert "export async function GET" in health_route
    assert "status" in health_route


def test_scaffold_home_page_has_feature_links_marker(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    page = (repo_path / "app" / "page.tsx").read_text(encoding="utf-8")
    assert "{/* FEATURE_LINKS_START */}" in page
    assert "{/* FEATURE_LINKS_END */}" in page


def test_scaffold_mongodb_helper_is_guarded(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    lib_mongodb = (repo_path / "lib" / "mongodb.ts").read_text(encoding="utf-8")
    assert "MONGODB_URI" in lib_mongodb
    assert "return null" in lib_mongodb  # guarded, never throws when unset


def test_backfill_removes_a_stale_next_config_ts_left_from_before_the_mjs_rename(project_id):
    # Confirmed real, build-breaking bug: Next.js 14 (this project's pinned
    # version) refuses to build at all if next.config.ts is present, even
    # when a correct next.config.mjs also exists alongside it -- a repo
    # scaffolded before the scaffold's config file was renamed to .mjs must
    # have the stale .ts one actively removed, not just the .mjs one added.
    repo = workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    stale_config = repo_path / "next.config.ts"
    stale_config.write_text(
        'import type { NextConfig } from "next";\n\nconst nextConfig: NextConfig = {};\n\n'
        "export default nextConfig;\n",
        encoding="utf-8",
    )
    repo.index.add(["next.config.ts"])
    repo.index.commit("simulate a pre-mjs-rename repo state")

    reopened_repo = workspace_service.ensure_project_repo(project_id)

    assert not stale_config.exists()
    assert (repo_path / "next.config.mjs").exists()
    assert not reopened_repo.is_dirty(untracked_files=True)
    committed_files = reopened_repo.git.ls_tree("-r", "--name-only", "HEAD").splitlines()
    assert "next.config.ts" not in committed_files


def test_backfill_adds_missing_nextjs_scaffold_file_without_touching_existing_ones(project_id):
    repo = workspace_service.ensure_project_repo(project_id)
    repo_path = workspace_service.get_repo_path(project_id)

    # Simulate an old repo created before app/globals.css was part of the
    # scaffold, and simulate a feature having already customized layout.tsx.
    (repo_path / "app" / "globals.css").unlink()
    repo.index.remove(["app/globals.css"])
    repo.index.commit("simulate pre-scaffold-fix repo state")

    custom_layout = "// customized by a prior feature\n" + (repo_path / "app" / "layout.tsx").read_text(
        encoding="utf-8"
    )
    (repo_path / "app" / "layout.tsx").write_text(custom_layout, encoding="utf-8")
    repo.index.add(["app/layout.tsx"])
    repo.index.commit("simulate a prior feature's customization")

    reopened_repo = workspace_service.ensure_project_repo(project_id)

    assert (repo_path / "app" / "globals.css").exists()
    assert (repo_path / "app" / "layout.tsx").read_text(encoding="utf-8") == custom_layout
    assert not reopened_repo.is_dirty(untracked_files=True)


def test_backfill_is_idempotent_when_nothing_missing(project_id):
    workspace_service.ensure_project_repo(project_id)
    repo = workspace_service.ensure_project_repo(project_id)
    commit_count_before = sum(1 for _ in repo.iter_commits())

    workspace_service.ensure_project_repo(project_id)

    commit_count_after = sum(1 for _ in repo.iter_commits())
    assert commit_count_after == commit_count_before


def _init_legacy_mern_repo(repo_path):
    from git import Repo

    repo_path.mkdir(parents=True, exist_ok=True)
    repo = Repo.init(repo_path, initial_branch="main")

    (repo_path / ".gitignore").write_text("node_modules/\n.env\n", encoding="utf-8")

    for relative_path, content in MERN_SCAFFOLD_FILES.items():
        file_path = repo_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    repo.index.add([".gitignore", *MERN_SCAFFOLD_FILES.keys()])
    repo.index.commit("simulate a pre-migration MERN project")
    return repo


def test_existing_mern_repo_is_detected_and_frozen_not_migrated(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    _init_legacy_mern_repo(repo_path)

    workspace_service.ensure_project_repo(project_id)

    # Still MERN -- no Next.js files written alongside it.
    assert (repo_path / "server" / "src" / "app.js").exists()
    assert not (repo_path / "app").exists()
    assert not (repo_path / "next.config.mjs").exists()
    assert not (repo_path / "package.json").exists() or "next" not in (
        repo_path / "package.json"
    ).read_text(encoding="utf-8")


def test_existing_mern_repo_still_gets_its_own_legacy_backfill(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)

    # Simulate a MERN repo predating client/src/index.css.
    (repo_path / "client" / "src" / "index.css").unlink()
    repo.index.remove(["client/src/index.css"])
    repo.index.commit("simulate pre-scaffold-fix MERN repo state")

    workspace_service.ensure_project_repo(project_id)

    assert (repo_path / "client" / "src" / "index.css").exists()
    assert not (repo_path / "app").exists()


def test_server_scaffold_uses_express_and_exposes_health_route(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    _init_legacy_mern_repo(repo_path)
    workspace_service.ensure_project_repo(project_id)

    app_js = (repo_path / "server" / "src" / "app.js").read_text(encoding="utf-8")
    assert "express" in app_js
    assert "/api/health" in app_js

    server_package_json = (repo_path / "server" / "package.json").read_text(encoding="utf-8")
    assert '"express"' in server_package_json


def test_client_scaffold_is_a_real_vite_react_app(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    _init_legacy_mern_repo(repo_path)
    workspace_service.ensure_project_repo(project_id)

    client_package_json = (repo_path / "client" / "package.json").read_text(encoding="utf-8")
    assert '"vite"' in client_package_json
    assert '"react"' in client_package_json

    assert (repo_path / "client" / "index.html").exists()
    assert (repo_path / "client" / "vite.config.js").exists()

    main_jsx = (repo_path / "client" / "src" / "main.jsx").read_text(encoding="utf-8")
    assert "createRoot" in main_jsx


def _reset_to_legacy_scaffold(repo, repo_path, app_js_content: str, server_js_content: str) -> None:
    """
    Rewrite an already-scaffolded MERN repo's app.js/server.js/package.json
    back to their pre-upgrade (legacy) shape, to simulate a repo that was
    scaffolded before the helmet/rate-limit/mongoose-connect/error-handler
    upgrade shipped -- exactly the real e-commerce-platform project's state
    at the time this upgrade was written.
    """
    import json

    (repo_path / "server" / "src" / "app.js").write_text(app_js_content, encoding="utf-8")
    (repo_path / "server" / "src" / "server.js").write_text(server_js_content, encoding="utf-8")

    package_json_path = repo_path / "server" / "package.json"
    data = json.loads(package_json_path.read_text(encoding="utf-8"))
    data["dependencies"].pop("helmet", None)
    data["dependencies"].pop("express-rate-limit", None)
    package_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    repo.index.add(["server/src/app.js", "server/src/server.js", "server/package.json"])
    repo.index.commit("simulate pre-upgrade legacy scaffold state")


def test_upgrade_backfill_replaces_untouched_legacy_app_js_and_server_js_wholesale(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)
    _reset_to_legacy_scaffold(repo, repo_path, _LEGACY_SERVER_APP_JS_V1, _LEGACY_SERVER_SERVER_JS_V1)

    workspace_service.ensure_project_repo(project_id)

    app_js = (repo_path / "server" / "src" / "app.js").read_text(encoding="utf-8")
    server_js = (repo_path / "server" / "src" / "server.js").read_text(encoding="utf-8")
    package_json = (repo_path / "server" / "package.json").read_text(encoding="utf-8")

    assert "helmet" in app_js
    assert "express-rate-limit" in app_js
    assert "FEATURE_ROUTES_END" in app_js
    assert "err.stack" in app_js
    assert "mongoose.connect" in server_js
    assert '"helmet"' in package_json
    assert '"express-rate-limit"' in package_json


def test_upgrade_backfill_preserves_a_customized_app_js_router_mount(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)

    # Simulate the real e-commerce-platform scenario: a feature already
    # mounted its own router into the legacy app.js before this upgrade
    # existed.
    customized_app_js = _LEGACY_SERVER_APP_JS_V1.replace(
        'const cors = require("cors");\n',
        'const cors = require("cors");\nconst authRoutes = require("./routes/auth.routes");\n',
    ).replace(
        "module.exports = app;",
        'app.use("/api/auth", authRoutes);\n\nmodule.exports = app;',
    )
    _reset_to_legacy_scaffold(repo, repo_path, customized_app_js, _LEGACY_SERVER_SERVER_JS_V1)

    workspace_service.ensure_project_repo(project_id)

    app_js = (repo_path / "server" / "src" / "app.js").read_text(encoding="utf-8")

    assert 'app.use("/api/auth", authRoutes);' in app_js
    assert "helmet" in app_js
    assert "express-rate-limit" in app_js
    assert "FEATURE_ROUTES_END" in app_js
    assert "err.stack" in app_js


def test_upgrade_backfill_is_idempotent_on_customized_app_js(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)
    customized_app_js = _LEGACY_SERVER_APP_JS_V1.replace(
        "module.exports = app;", 'app.use("/api/auth", authRoutes);\n\nmodule.exports = app;'
    )
    _reset_to_legacy_scaffold(repo, repo_path, customized_app_js, _LEGACY_SERVER_SERVER_JS_V1)

    workspace_service.ensure_project_repo(project_id)
    first_pass = (repo_path / "server" / "src" / "app.js").read_text(encoding="utf-8")

    workspace_service.ensure_project_repo(project_id)
    second_pass = (repo_path / "server" / "src" / "app.js").read_text(encoding="utf-8")

    assert first_pass == second_pass
    assert first_pass.count("helmet()") == 1
    assert first_pass.count("FEATURE_ROUTES_END") == 1


def test_upgrade_backfill_skips_customized_server_js_without_corrupting_it(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)
    customized_server_js = _LEGACY_SERVER_SERVER_JS_V1 + "\n// a feature added this comment\n"
    _reset_to_legacy_scaffold(repo, repo_path, _LEGACY_SERVER_APP_JS_V1, customized_server_js)

    workspace_service.ensure_project_repo(project_id)

    server_js = (repo_path / "server" / "src" / "server.js").read_text(encoding="utf-8")
    assert server_js == customized_server_js
    assert "mongoose.connect" not in server_js


def _reset_to_legacy_client_app_jsx(repo, repo_path, app_jsx_content: str) -> None:
    """
    Rewrite an already-scaffolded MERN repo's client/src/App.jsx back to its
    pre-FEATURE_LINKS-upgrade (legacy, link-free) shape -- exactly the real
    state e-commerce-platform's and taskflow's App.jsx were found in (a
    feature's <Route> added, but HomePage never linking to it).
    """
    (repo_path / "client" / "src" / "App.jsx").write_text(app_jsx_content, encoding="utf-8")
    repo.index.add(["client/src/App.jsx"])
    repo.index.commit("simulate pre-nav-fix legacy App.jsx state")


def test_upgrade_backfill_replaces_untouched_legacy_app_jsx_wholesale(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)
    _reset_to_legacy_client_app_jsx(repo, repo_path, _LEGACY_CLIENT_APP_JSX_V1)

    workspace_service.ensure_project_repo(project_id)

    app_jsx = (repo_path / "client" / "src" / "App.jsx").read_text(encoding="utf-8")
    assert "FEATURE_LINKS_START" in app_jsx
    assert "FEATURE_LINKS_END" in app_jsx
    assert "Link" in app_jsx.split("\n")[1]  # the react-router-dom import line


def test_upgrade_backfill_preserves_a_customized_app_jsx_route(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)

    # Simulate the real e-commerce-platform/taskflow scenario: a feature
    # already added its own route to the legacy App.jsx before this
    # upgrade existed, but HomePage was never touched.
    customized_app_jsx = _LEGACY_CLIENT_APP_JSX_V1.replace(
        'import { Routes, Route } from "react-router-dom";\n',
        'import { Routes, Route } from "react-router-dom";\nimport LoginPage from "./pages/LoginPage";\n',
    ).replace(
        '<Route path="/" element={<HomePage />} />',
        '<Route path="/" element={<HomePage />} />\n      <Route path="/login" element={<LoginPage />} />',
    )
    _reset_to_legacy_client_app_jsx(repo, repo_path, customized_app_jsx)

    workspace_service.ensure_project_repo(project_id)

    app_jsx = (repo_path / "client" / "src" / "App.jsx").read_text(encoding="utf-8")

    assert '<Route path="/login" element={<LoginPage />} />' in app_jsx
    assert "FEATURE_LINKS_START" in app_jsx
    assert "FEATURE_LINKS_END" in app_jsx
    assert "Link" in app_jsx.split("\n")[1]


def test_upgrade_backfill_is_idempotent_on_customized_app_jsx(project_id):
    repo_path = workspace_service.get_repo_path(project_id)
    repo = _init_legacy_mern_repo(repo_path)
    customized_app_jsx = _LEGACY_CLIENT_APP_JSX_V1.replace(
        '<Route path="/" element={<HomePage />} />',
        '<Route path="/" element={<HomePage />} />\n      <Route path="/login" element={<LoginPage />} />',
    )
    _reset_to_legacy_client_app_jsx(repo, repo_path, customized_app_jsx)

    workspace_service.ensure_project_repo(project_id)
    first_pass = (repo_path / "client" / "src" / "App.jsx").read_text(encoding="utf-8")

    workspace_service.ensure_project_repo(project_id)
    second_pass = (repo_path / "client" / "src" / "App.jsx").read_text(encoding="utf-8")

    assert first_pass == second_pass
    assert first_pass.count("FEATURE_LINKS_START") == 1


def test_resume_feature_branch_checks_out_existing_branch_without_resetting(project_id):
    feature_id = generate_id("feature")
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Resume Test Feature",
    }

    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "marker.ts").write_text("// prior work", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "prior revision work")

    repo = workspace_service.ensure_project_repo(project_id)
    repo.git.checkout("main")

    branch_name = workspace_service.resume_feature_branch(project_id, feature_id)

    assert branch_name == f"feature/{workspace_service._feature_slug(feature_id)}"
    assert repo.active_branch.name == branch_name
    assert (repo_path / "lib" / "marker.ts").exists()

    store.database["features"].delete_one({"feature_id": feature_id})


def test_resume_feature_branch_falls_back_to_a_fresh_branch_from_main_when_none_exists(project_id):
    # Real, confirmed bug: this used to raise unconditionally, but the feature branch being
    # missing is routinely completely normal -- most commonly because it was already approved,
    # merged into main, and cleanly deleted by merge_feature_branch's own established post-merge
    # cleanup (see the two tests below for that exact real scenario). A revision only ever reaches
    # resume_feature_branch after CoderAgent.revise() has already confirmed a real prior CODE_PLAN
    # artifact exists, so there is genuinely no "never coded at all" case this method needs to
    # guard against -- falling back to a fresh branch from main's current tip is always safe.
    feature_id = generate_id("feature")
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Never Branched Feature",
    }
    workspace_service.ensure_project_repo(project_id)

    branch_name = workspace_service.resume_feature_branch(project_id, feature_id)

    repo = workspace_service.ensure_project_repo(project_id)
    assert branch_name == f"feature/{workspace_service._feature_slug(feature_id)}"
    assert repo.active_branch.name == branch_name
    assert repo.head.commit.hexsha == repo.heads["main"].commit.hexsha

    store.database["features"].delete_one({"feature_id": feature_id})


def test_resume_feature_branch_recovers_the_real_merged_code_after_the_branch_was_deleted(project_id):
    # The exact real scenario found live: approve + merge a feature (which deletes its own
    # branch, by design -- see merge_feature_branch), then request a revision. Confirms the
    # fallback branch's working tree actually has the real, merged feature content -- not an
    # empty/bare scaffold -- since main's tree already includes it after a real --no-ff merge.
    feature_id = generate_id("feature")
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Merged Then Revised Feature",
    }

    workspace_service.start_feature_branch(project_id, feature_id)
    repo_path = workspace_service.get_repo_path(project_id)
    (repo_path / "lib" / "real_feature_marker.ts").write_text("// real merged content", encoding="utf-8")
    workspace_service.commit_changes(project_id, feature_id, "real feature work")
    workspace_service.merge_feature_branch(project_id, feature_id)

    repo = workspace_service.ensure_project_repo(project_id)
    assert f"feature/{workspace_service._feature_slug(feature_id)}" not in [h.name for h in repo.heads]

    branch_name = workspace_service.resume_feature_branch(project_id, feature_id)

    assert repo.active_branch.name == branch_name
    assert (repo_path / "lib" / "real_feature_marker.ts").exists()

    store.database["features"].delete_one({"feature_id": feature_id})
