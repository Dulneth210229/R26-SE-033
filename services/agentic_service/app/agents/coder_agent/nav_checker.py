"""
Coder Agent navigation/page-reachability checker (Next.js App Router).

Purpose:
Prove every page a feature adds is actually reachable by a human clicking
through the app starting from "/", not just that it compiles and its folder
exists under app/. This targets the same real bug class the MERN-era
checker was built for (a route registered with no link to it, so the app
only ever shows the home page) -- unchanged by the migration, since
file-based routing makes a page automatically LIVE the instant its
app/**/page.tsx file exists, but does nothing to make it DISCOVERABLE.

This is a best-effort, regex-based static check (like route_checker.py's
check_route_coverage), not a real JSX/AST parser or a live browser check --
it will miss unusual navigation styles (e.g. router.push() with no <Link> at
all -- which the Coder Agent's prompt forbids for exactly this reason) and
can't verify that clicking a link actually works at runtime, only that a
page and a link to it both exist in the source.

Algorithm:
- Every folder under app/ (excluding app/api/, which never contains pages)
  that has its own page.tsx is a route that must be proven reachable, other
  than "/" itself (app/page.tsx), which is the entry point and trivially
  reachable. Only page.tsx creates a route -- layout.tsx/loading.tsx/
  error.tsx/not-found.tsx/default.tsx/route.ts do not, and are never
  mistaken for one since this only ever globs for files literally named
  page.tsx/page.js.
- A non-parameterized route is reachable if some `<Link href="X">` (or
  `<a href="X">`) exists ANYWHERE under the repo -- not just in app/page.tsx,
  since a link to a detail page often lives in a separate list page
  component file.
- A parameterized route (a folder segment wrapped in "[...]", e.g.
  "/tasks/[id]") can never be linked to directly (there is no real id value
  at the nav level) -- it is reachable only if its static prefix (e.g.
  "/tasks" for "/tasks/[id]") is itself a registered route that is, in
  turn, linked from somewhere. This mirrors the planner prompt's guidance:
  a parameterized detail route needs a reachable list/index page ancestor.
"""

from __future__ import annotations

import re
from pathlib import Path

_LINK_PATTERNS = [
    re.compile(r'<Link\s+href="([^"]+)"'),
    re.compile(r'<Link\s+href=\{`([^`$]*)\$\{'),  # href={`/prefix/${id}`} -> captures "/prefix/"
    re.compile(r'<Link\s+href=\{`([^`]*)`\}'),  # href={`/fully/static`} (no interpolation)
    re.compile(r'<a\s+href="([^"]+)"'),
]

_EXCLUDED_DIRS = {"node_modules", ".git", ".next"}
_PAGE_FILE_NAMES = ("page.tsx", "page.js")


def check_page_reachability(workspace_root: Path) -> list[dict[str, str]]:
    """
    Returns [{"route": "/tasks/[id]", "status": "reachable"|"unreachable"}, ...]
    for every page under app/ other than the home page ("/"). Returns [] if
    there's no app/ directory or no non-root pages registered yet.
    """
    app_root = workspace_root / "app"

    if not app_root.exists():
        return []

    route_paths = sorted(_discover_page_routes(app_root))

    if not route_paths:
        return []

    registered_paths = set(route_paths)
    linked_paths = _collect_linked_paths(workspace_root)

    results: list[dict[str, str]] = []

    for route_path in route_paths:
        if _is_parameterized(route_path):
            prefix = _static_prefix(route_path)
            reachable = prefix in registered_paths and _path_is_linked(prefix, linked_paths)
        else:
            reachable = _path_is_linked(route_path, linked_paths)

        results.append({"route": route_path, "status": "reachable" if reachable else "unreachable"})

    return results


def _discover_page_routes(app_root: Path) -> set[str]:
    """
    Every page.tsx/page.js under app/ (excluding app/api/) becomes a route,
    derived from its folder path relative to app/. The home page ("/",
    app/page.tsx itself) is excluded -- it's the entry point, trivially
    reachable, and not something a feature needs to link to.
    """
    routes: set[str] = set()

    for page_file in app_root.rglob("*"):
        if page_file.name not in _PAGE_FILE_NAMES:
            continue
        if any(part in _EXCLUDED_DIRS for part in page_file.parts):
            continue

        relative_dir = page_file.parent.relative_to(app_root)

        if relative_dir == Path("."):
            continue  # app/page.tsx itself -- the home page, always reachable

        parts = relative_dir.parts
        if "api" in parts:
            continue  # defensive -- app/api/ never contains pages

        route = "/" + "/".join(parts)
        routes.add(route)

    return routes


def _collect_linked_paths(workspace_root: Path) -> set[str]:
    linked: set[str] = set()

    for extension in ("*.tsx", "*.ts"):
        for file_path in workspace_root.rglob(extension):
            if any(part in _EXCLUDED_DIRS for part in file_path.parts):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            for pattern in _LINK_PATTERNS:
                for match in pattern.finditer(content):
                    linked.add(match.group(1))

    return linked


def _path_is_linked(path: str, linked_paths: set[str]) -> bool:
    normalized = path.rstrip("/")
    return any(linked.rstrip("/") == normalized for linked in linked_paths)


def _is_parameterized(path: str) -> bool:
    return any(segment.startswith("[") for segment in path.split("/"))


def _static_prefix(path: str) -> str:
    static_segments: list[str] = []

    for segment in path.split("/"):
        if segment.startswith("["):
            break
        static_segments.append(segment)

    return "/".join(static_segments) or "/"
