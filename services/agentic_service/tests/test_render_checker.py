"""
Real, Docker+Playwright-backed tests for the Coder Agent's runtime-render
checker (app/agents/coder_agent/render_checker.py), for the Next.js
scaffold. No mocking of Docker or Playwright here -- this is infra-level
(like test_coder_verify.py's real npm-install/boot/build tests), proving
the actual mechanism works: serving a real built .next output via
`next start` in a container with a published port, and a real host-side
Playwright browser navigating to it.
"""

import os
import shutil
import stat

import pytest

from app.agents.coder_agent.render_checker import check_runtime_render
from app.services.in_memory_store import store
from app.services.sandbox_service import sandbox_service
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def built_project():
    """
    A real throwaway project with the app actually built (next build), so
    there's a real .next output for `next start` to serve.
    """
    project_id = generate_id("project")
    store.projects[project_id] = {"project_id": project_id, "project_name": f"Render Test {project_id}"}
    workspace_service.ensure_project_repo(project_id)

    # 240s was too tight once Tailwind's devDependencies were added to the
    # scaffold (confirmed directly: a real, otherwise-successful install can
    # take up to ~7 minutes over a slow Windows-Docker-Desktop bind mount) --
    # matches verify.py's own INSTALL_TIMEOUT_SECONDS widening for the same
    # reason.
    install_result = sandbox_service.run_command(project_id, "npm install", cwd=".", timeout=600)
    assert install_result["exit_code"] == 0, install_result["stderr"]

    build_result = sandbox_service.run_command(project_id, "npm run build", cwd=".", timeout=300)
    assert build_result["exit_code"] == 0, build_result["stderr"]

    yield project_id

    repo_path = workspace_service.get_repo_path(project_id)
    workspace_service.ensure_project_repo(project_id).close()
    store.database["projects"].delete_one({"project_id": project_id})
    shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


def test_home_page_renders_cleanly_on_untouched_scaffold(built_project):
    result = check_runtime_render(built_project, reachable_routes=[])

    assert result["home_page"]["status"] == "passed"
    assert result["feature_pages"] == []


def test_check_runtime_render_works_when_called_from_a_running_event_loop(built_project):
    """
    Reproduces a real bug found running CoderAgent.revise() end-to-end:
    check_runtime_render's real caller (verify(), called synchronously from
    inside CoderAgent.run()/revise(), both async, without its own thread)
    always executes with an asyncio event loop already running on that
    thread. Playwright's sync API raises if used directly on such a thread
    -- every real coding attempt failed "home page render" with "Playwright
    Sync API inside the asyncio loop" before this was fixed (running the
    check's Playwright work in its own dedicated worker thread internally).
    A plain synchronous call, like the test above, does not exercise this at
    all -- calling it directly (not via asyncio.to_thread, which would
    already dodge the bug) from inside a running coroutine is what
    reproduces the exact real call pattern.
    """
    import asyncio

    async def _drive():
        return check_runtime_render(built_project, [])  # called directly, not awaited/threaded

    result = asyncio.run(_drive())

    assert result["home_page"]["status"] == "passed"


def test_on_server_ready_callback_is_invoked_with_a_real_reachable_base_url(built_project):
    """
    Real, live proof of the mechanism functional_checker.py's own CRUD smoke test relies on --
    on_server_ready is called with the real base_url WHILE the background service is still up
    (before its own teardown), and its return value flows through under result["crud_check"].
    """
    calls: list[str] = []

    def _on_server_ready(base_url: str) -> dict:
        import urllib.request

        # A real request against the real, still-running server, confirming the URL passed in
        # is genuinely live at the moment this callback runs, not a URL for an already-torn-down
        # or not-yet-started server.
        response = urllib.request.urlopen(base_url, timeout=5)
        calls.append(base_url)
        return {"status": "passed", "output": f"real check saw HTTP {response.status}"}

    result = check_runtime_render(built_project, reachable_routes=[], on_server_ready=_on_server_ready)

    assert len(calls) == 1
    assert calls[0].startswith("http://localhost:")
    assert result["crud_check"] == {"status": "passed", "output": "real check saw HTTP 200"}


def test_on_server_ready_exception_is_caught_and_reported_not_propagated(built_project):
    def _raising_callback(base_url: str) -> dict:
        raise RuntimeError("a bug in the caller's own check")

    result = check_runtime_render(built_project, reachable_routes=[], on_server_ready=_raising_callback)

    assert result["home_page"]["status"] == "passed"  # unrelated to the crud_check callback failing
    assert result["crud_check"]["status"] == "failed"
    assert "a bug in the caller's own check" in result["crud_check"]["output"]


def test_sandbox_background_service_publishes_a_reachable_port(built_project):
    service = sandbox_service.start_background_service(
        project_id=built_project,
        command="npx next start -H 0.0.0.0 -p 3000",
        cwd=".",
        container_port=3000,
    )
    try:
        assert isinstance(service["host_port"], int)
        assert service["host_port"] > 0

        import urllib.request

        for _ in range(40):
            try:
                response = urllib.request.urlopen(f"http://localhost:{service['host_port']}", timeout=2)
                assert response.status == 200
                break
            except Exception:
                import time

                time.sleep(1)
        else:
            pytest.fail("next start never became reachable on the published host port")
    finally:
        sandbox_service.stop_background_service(service["container"])
