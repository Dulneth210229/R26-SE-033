"""
QA Agent test execution.

Ensures Jest is set up in the target project (added to package.json + installed ONCE, persisted
-- see agent.py's own module docstring for why Jest replaced the earlier zero-dependency
`node:test` runner: its built-in `--json` output already carries real per-test structured
results, `testResults[].assertionResults[]`, which is what actually makes "real per-test-case
output" possible without inventing a parser), then runs the generated suite for real through the
same sandboxed command-execution path every other agent uses (`sandbox_service`, matching
scanners.py's `scan_dependencies` and testing.py's earlier `run_tests` for the same
dependency-injection reasoning), and parses the real results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

JEST_DEV_DEPENDENCIES = {
    "jest": "^29.7.0",
    "@babel/core": "^7.24.0",
    "@babel/preset-env": "^7.24.0",
    "@babel/preset-typescript": "^7.24.0",
    "babel-jest": "^29.7.0",
}

BABEL_CONFIG_FILENAME = "babel.config.qa.js"
JEST_CONFIG_FILENAME = "jest.config.qa.js"
JEST_RESULTS_FILENAME = "qa_jest_results.json"

BABEL_CONFIG_CONTENT = """module.exports = {
  presets: [
    ["@babel/preset-env", { targets: { node: "current" } }],
    "@babel/preset-typescript",
  ],
};
"""

# Kept deliberately separate from anything Next.js's own build tooling reads (no jest.config.js,
# no touching next.config.mjs) -- QA's own config, QA's own concern. testEnvironment stays "node"
# (not "jsdom"): this pass only targets lib/models/route-handler logic, none of which needs a
# DOM (see discovery.py's own module docstring for the full scope statement).
#
# The transform's second element explicitly passes `configFile` to babel-jest -- confirmed by a
# real live run that without it, babel-jest silently falls back to its own config auto-discovery
# (which only ever looks for "babel.config.js"/".babelrc"/etc, never this file's deliberately
# non-standard "babel.config.qa.js" name), so every generated test file was transformed with NO
# presets at all and failed with "SyntaxError: Cannot use import statement outside a module" --
# a 100% real-run failure rate this one line fixes.
_JEST_CONFIG_TEMPLATE = r"""const path = require("path");

module.exports = {
  testEnvironment: "node",
  testMatch: ["<rootDir>/generated_tests/**/*.test.ts"],
  transform: {
    "^.+\\.tsx?$": ["babel-jest", { configFile: path.resolve(__dirname, "%s") }],
  },
  moduleNameMapper: { "^@/(.*)$": "<rootDir>/$1" },
  moduleFileExtensions: ["ts", "js", "json"],
};
"""

JEST_CONFIG_CONTENT = _JEST_CONFIG_TEMPLATE % BABEL_CONFIG_FILENAME


def ensure_jest_setup(repo_path: Path, project_id: str, run_command_fn: Callable) -> None:
    """Idempotent: adds jest + babel devDependencies to package.json (if not already declared --
    a real generated project genuinely benefits from having its own test tooling declared, it's
    what "Download Project" ships) and runs a real `npm install` whenever the real jest package
    isn't actually present in node_modules yet. The two small config files are rewritten
    unconditionally every run (cheap, keeps them in sync with this module).

    Real, confirmed incident this install-gate fix closes: the previous version treated "jest" is
    a KEY in package.json's devDependencies as proof jest was actually installed -- a declaration
    -only check. Once declared (e.g. by an earlier successful run), every LATER run skipped
    `npm install` forever, even after node_modules was later found broken/missing/never populated
    (a fresh checkout, a corrupted install, an interrupted first run). `npx jest` then silently
    fell back to fetching a mismatched version on the fly, which failed to resolve
    @babel/preset-env, crashing the whole suite with ZERO real results -- which then cascaded into
    every planned test case being reported as unresolved (see _merge_results in agent.py).
    Checking for the real, installed package ON DISK instead of the package.json declaration is
    what actually prevents this recurring.
    """
    package_json_path = repo_path / "package.json"

    if package_json_path.exists():
        try:
            data = json.loads(package_json_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        dev_deps = data.get("devDependencies", {})
        if "jest" not in dev_deps:
            dev_deps.update(JEST_DEV_DEPENDENCIES)
            data["devDependencies"] = dev_deps
            package_json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    (repo_path / BABEL_CONFIG_FILENAME).write_text(BABEL_CONFIG_CONTENT, encoding="utf-8")
    (repo_path / JEST_CONFIG_FILENAME).write_text(JEST_CONFIG_CONTENT, encoding="utf-8")

    jest_actually_installed = (repo_path / "node_modules" / "jest" / "package.json").exists()
    if not jest_actually_installed:
        run_command_fn(project_id, "npm install", ".", 180)


def run_tests(repo_path: Path, project_id: str, run_command_fn: Callable | None = None) -> dict[str, Any]:
    """Returns {"results": [{"name","test_file","status","duration_ms","failure_message"}, ...],
    "passed", "failed", "exit_code", "raw_stderr"}. `test_file` on each result is just
    the basename (e.g. "Item.test.ts") -- every generated test file lives flatly under
    generated_tests/ with no subdirectories, so this is what agent.py matches back to each
    QaTestCase's own `test_file` (set the same way at generation time). `status` is always
    "passed" or "failed" -- never "skipped" (direct user requirement, see agent.py's own
    _finalize_report for how a genuine "Jest produced nothing" case is surfaced honestly as a
    distinct environment_failure signal instead)."""
    if run_command_fn is None:
        from app.services.sandbox_service import sandbox_service
        run_command_fn = lambda pid, cmd, cwd, timeout: sandbox_service.run_command(
            project_id=pid, command=cmd, cwd=cwd, timeout=timeout
        )

    ensure_jest_setup(repo_path, project_id, run_command_fn)

    command = (
        f"npx jest --config {JEST_CONFIG_FILENAME} --json --outputFile={JEST_RESULTS_FILENAME} "
        f"--testTimeout=15000"
    )
    result = run_command_fn(project_id, command, ".", 180)

    results_path = repo_path / JEST_RESULTS_FILENAME
    if not results_path.exists():
        return {
            "results": [], "passed": 0, "failed": 0,
            "exit_code": result.get("exit_code"),
            "raw_stderr": (result.get("stderr") or "")[:4000] or (result.get("stdout") or "")[:4000],
        }

    try:
        raw_text = results_path.read_text(encoding="utf-8")
        jest_output = json.loads(raw_text)
    except (OSError, json.JSONDecodeError):
        return {
            "results": [], "passed": 0, "failed": 0,
            "exit_code": result.get("exit_code"),
            "raw_stderr": "Jest produced an unparseable results file.",
        }
    finally:
        results_path.unlink(missing_ok=True)

    return _parse_jest_output(jest_output, result.get("exit_code"))


def _parse_jest_output(jest_output: dict[str, Any], exit_code: int | None) -> dict[str, Any]:
    """Every real assertion resolves to "passed" or "failed" only -- never "skipped" (direct user
    requirement). Jest's own native non-passed/failed statuses ("pending" from test.skip/
    describe.skip, "todo" from it.todo -- forbidden outright in prompt.py's own testing
    conventions, and caught deterministically before ever reaching Jest by generator.py's
    scan_for_forbidden_jest_constructs) and a genuinely missing status key both resolve to
    "failed" here as the honest last-resort default -- this assertion's real outcome could not be
    determined, which is closer to "failed" than either "passed" or a forbidden third status."""
    results: list[dict[str, Any]] = []
    passed = failed = 0

    for test_file_result in jest_output.get("testResults", []):
        test_file = Path(test_file_result.get("name", "")).name
        for assertion in test_file_result.get("assertionResults", []):
            status = assertion.get("status")
            if status == "passed":
                passed += 1
            else:
                status = "failed"
                failed += 1

            failure_messages = assertion.get("failureMessages") or []
            results.append({
                "name": assertion.get("title", ""),
                "test_file": test_file,
                "status": status,
                "duration_ms": assertion.get("duration"),
                "failure_message": (
                    "\n".join(failure_messages)[:2000] if failure_messages
                    else (None if assertion.get("status") == "passed" else
                          f"Jest reported this test as {assertion.get('status', '(no status)')!r}, "
                          "not a real pass/fail assertion outcome -- see the testing conventions "
                          "in prompt.py for what real Jest constructs are expected.")
                ),
            })

    return {
        "results": results,
        "passed": passed,
        "failed": failed,
        "exit_code": exit_code,
        "raw_stderr": "",
    }
