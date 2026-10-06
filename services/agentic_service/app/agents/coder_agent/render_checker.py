"""
Coder Agent runtime-render checker (Next.js).

Purpose:
Prove that pages the Coder Agent's build produces actually render without
crashing when loaded in a real browser -- not just that they compile
(verify.py's `next build` step) and are linked
(nav_checker.check_page_reachability). Neither of those static checks can
catch a page that is reachable and compiles cleanly but throws at runtime
(e.g. an undefined prop access, a Server Component that crashes during
render) -- this closes that gap.

Deliberately NOT a live dev-server + iterate-until-correct loop (that
approach was evaluated and rejected -- see CLAUDE.md for the full
reasoning: no reliable domain-agnostic way to judge "does this look right"
beyond what this check already does, real added cost per coding attempt,
and it would inherit this project's already-documented Docker-contention
flakiness). Instead:
- Serves the ALREADY-BUILT .next output via `next start` (the real
  production server, correctly handling both static and dynamic
  Server-Component routes) -- no extra build, reuses what verify.py's
  `next build` step already produced.
- One-shot check per verify() call, not a retry loop.
- Uses Playwright's sync API (same dependency and calling convention as
  uiux_agent/preview_renderer.py) from the HOST process to navigate to each
  page and check the real HTTP response status plus zero `pageerror`
  events -- the migration's one genuine free correctness upgrade over the
  old MERN-era check: under SSR there is no client-side `#root` element to
  inspect for emptiness (and a crashing Server Component still returns
  non-empty HTML, so that old check was already the wrong signal even on
  the stack it was written for) -- the real HTTP status code is strictly
  stronger evidence either way.

Gate strictness (decided, not this module's concern to enforce -- verify.py
wires the result up this way): the home page failing is a hard gate (cheap,
no data dependency, exactly the thing that was silently broken project-wide
before nav_checker/render_checker existed). Feature pages are checked too
but reported informationally only, since their rendering can legitimately
vary with backend data state (e.g. an empty list before any data exists).
"""

from __future__ import annotations

import concurrent.futures
import time
import urllib.error
import urllib.request
from typing import Any, Callable

from playwright.sync_api import sync_playwright

from app.services.sandbox_service import sandbox_service

NEXT_START_CONTAINER_PORT = 3000
NEXT_START_COMMAND = f"npx next start -H 0.0.0.0 -p {NEXT_START_CONTAINER_PORT}"

# `next start`'s cold start (loading the full production server, its route
# manifest, etc.) is slower than `vite preview`'s -- widened from the
# MERN-era budget (20 attempts / 1s) to give it real room before declaring
# the preview server unreachable an infra failure rather than a slow boot.
READINESS_POLL_ATTEMPTS = 40
READINESS_POLL_INTERVAL_SECONDS = 1


class RenderCheckError(Exception):
    """Raised when the runtime-render check itself could not run (infra failure, not a page defect)."""


def check_runtime_render(
    project_id: str,
    reachable_routes: list[str],
    on_server_ready: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Serves the built .next output and checks the home page plus every given
    route for JS errors / a non-2xx/3xx HTTP response.

    reachable_routes: routes already proven reachable by nav_checker (only
    those are worth checking here -- an unreachable route's render state
    isn't actionable for a human anyway).

    on_server_ready: optional callback invoked with the real, live base_url
    (e.g. "http://localhost:54321") while this function's own background
    service is still up, right before it's torn down -- this is the ONE
    window during verify() where a real, reachable server exists at all (the
    earlier "server boot" step's server is gone by the time this function
    ever runs, see verify.py's own module docstring). Lets a caller (e.g.
    functional_checker.check_crud_functionality) run a real HTTP exercise
    against the app without starting a second server. This module stays
    decoupled from what the callback actually does -- a plain callback, not
    an import -- its return value (any JSON-serializable dict) is passed
    through verbatim under this function's own result as "crud_check". A
    raising callback is treated as a soft failure (caught, reported, never
    lets an unrelated check's bug take down the render check itself).

    Returns:
        {
            "home_page": {"status": "passed"|"failed", "output": str},
            "feature_pages": [{"route": str, "status": "passed"|"failed", "output": str}, ...],
            "crud_check": dict | None,  # on_server_ready's own return value, or None if not given
        }

    Raises RenderCheckError if the preview server itself never became
    reachable (an infra problem, distinct from a page rendering badly).

    Runs the actual check in a dedicated worker thread. Playwright's sync
    API (used here, and by preview_renderer.py) refuses to run on any thread
    with an already-running asyncio event loop -- and this function's real
    caller, CoderAgent.run()/revise(), is itself async, invoked from a sync
    graph node via asyncio.run(...) (see CLAUDE.md deviation #13), so an
    event loop genuinely is running on the calling thread for every real
    invocation. A fresh worker thread has no event loop of its own,
    sidestepping this regardless of the caller's context, with no change to
    this function's signature or its callers.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(
            _check_runtime_render_on_worker_thread, project_id, reachable_routes, on_server_ready
        ).result()


def _check_runtime_render_on_worker_thread(
    project_id: str,
    reachable_routes: list[str],
    on_server_ready: Callable[[str], dict[str, Any]] | None,
) -> dict[str, Any]:
    service = sandbox_service.start_background_service(
        project_id=project_id,
        command=NEXT_START_COMMAND,
        cwd=".",
        container_port=NEXT_START_CONTAINER_PORT,
    )
    host_port = service["host_port"]
    container = service["container"]

    try:
        base_url = f"http://localhost:{host_port}"
        _wait_until_ready(base_url)

        home_result = _check_page(base_url, "/")
        feature_results = [
            {"route": route, **_check_page(base_url, route)} for route in reachable_routes if route != "/"
        ]

        crud_check = None
        if on_server_ready is not None:
            try:
                crud_check = on_server_ready(base_url)
            except Exception as error:  # noqa: BLE001 -- a caller's own check must never break this one
                crud_check = {"status": "failed", "output": f"CRUD check raised unexpectedly: {error}"}

        return {"home_page": home_result, "feature_pages": feature_results, "crud_check": crud_check}

    finally:
        sandbox_service.stop_background_service(container)


def _wait_until_ready(base_url: str) -> None:
    for _ in range(READINESS_POLL_ATTEMPTS):
        try:
            urllib.request.urlopen(base_url, timeout=2)
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            time.sleep(READINESS_POLL_INTERVAL_SECONDS)

    raise RenderCheckError(
        f"next start never became reachable at {base_url} after "
        f"{READINESS_POLL_ATTEMPTS * READINESS_POLL_INTERVAL_SECONDS}s."
    )


def _check_page(base_url: str, route: str) -> dict[str, str]:
    url = base_url + route

    console_errors: list[str] = []

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 800})
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text) if msg.type == "error" else None,
                )
                page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))

                response = page.goto(url, timeout=15_000)
                page.wait_for_timeout(500)

                response_status = response.status if response is not None else None
            finally:
                browser.close()
    except Exception as error:
        return {"status": "failed", "output": f"Failed to load {route}: {error}"}

    if response_status is None or response_status >= 400:
        return {
            "status": "failed",
            "output": f"{route} responded with HTTP status {response_status}.",
        }

    if console_errors:
        return {
            "status": "failed",
            "output": f"{route} rendered with JS errors: {console_errors}",
        }

    return {
        "status": "passed",
        "output": f"{route} responded with HTTP {response_status} and no JS errors.",
    }
