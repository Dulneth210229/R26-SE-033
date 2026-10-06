"""
Unit tests for executor.ensure_jest_setup -- the real, historical reliability bug this closes:
the earlier version treated "jest" being a KEY in package.json's devDependencies as proof jest was
actually installed (a declaration-only check). Once declared, every later run skipped
`npm install` forever, even after node_modules was later found broken/missing -- `npx jest` then
silently fell back to a mismatched on-the-fly install, crashing the whole suite with zero real
results. The fix checks node_modules/jest/package.json's real, physical existence on disk instead.
No real npm/Docker/sandbox involved -- run_command_fn is a plain recording stub.
"""

import json

import pytest

from app.agents.qa_agent.executor import (
    BABEL_CONFIG_FILENAME,
    JEST_CONFIG_FILENAME,
    ensure_jest_setup,
)


def _recording_run_command_fn(calls: list):
    def _fn(project_id, command, cwd, timeout):
        calls.append(command)
        return {"exit_code": 0, "stdout": "", "stderr": ""}
    return _fn


def test_runs_npm_install_when_node_modules_jest_is_genuinely_missing_even_though_declared(tmp_path):
    # Reproduces the real historical incident: jest is already declared in package.json (e.g. from
    # an earlier successful run), but node_modules/jest itself is missing/broken on disk.
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "app", "devDependencies": {"jest": "^29.7.0"}}), encoding="utf-8",
    )
    calls: list = []

    ensure_jest_setup(tmp_path, "project_1", _recording_run_command_fn(calls))

    assert any("npm install" in call for call in calls)


def test_skips_npm_install_when_jest_is_genuinely_already_installed_on_disk(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "app", "devDependencies": {"jest": "^29.7.0"}}), encoding="utf-8",
    )
    jest_pkg_dir = tmp_path / "node_modules" / "jest"
    jest_pkg_dir.mkdir(parents=True)
    (jest_pkg_dir / "package.json").write_text("{}", encoding="utf-8")
    calls: list = []

    ensure_jest_setup(tmp_path, "project_1", _recording_run_command_fn(calls))

    assert not any("npm install" in call for call in calls)


def test_adds_jest_devdependency_when_not_yet_declared(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "app"}), encoding="utf-8")
    calls: list = []

    ensure_jest_setup(tmp_path, "project_1", _recording_run_command_fn(calls))

    data = json.loads((tmp_path / "package.json").read_text(encoding="utf-8"))
    assert "jest" in data["devDependencies"]
    assert any("npm install" in call for call in calls)


def test_writes_the_babel_and_jest_config_files_unconditionally(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "app", "devDependencies": {"jest": "^29.7.0"}}), encoding="utf-8",
    )
    jest_pkg_dir = tmp_path / "node_modules" / "jest"
    jest_pkg_dir.mkdir(parents=True)
    (jest_pkg_dir / "package.json").write_text("{}", encoding="utf-8")

    ensure_jest_setup(tmp_path, "project_1", _recording_run_command_fn([]))

    assert (tmp_path / BABEL_CONFIG_FILENAME).exists()
    assert (tmp_path / JEST_CONFIG_FILENAME).exists()


def test_does_not_raise_when_package_json_is_missing(tmp_path):
    calls: list = []

    ensure_jest_setup(tmp_path, "project_1", _recording_run_command_fn(calls))

    # No package.json to add a devDependency to -- still writes config and still installs, since
    # node_modules/jest can't possibly exist either.
    assert any("npm install" in call for call in calls)
