"""
Coder Agent route checker (Next.js App Router).

Purpose:
plan_validator.py only ever checks that a *planned* endpoint appears in some
file's `maps_to` list -- it never checks the *generated code itself*, so a
plan that fully passes validation gives no guarantee the coding loop actually
implemented every endpoint it claimed to cover (e.g. a route file that exists
but exports no handler function). This module closes that gap with two
deterministic, post-code, best-effort static checks:

- check_route_coverage: for each planned endpoint (a "/..." string in some
  file's maps_to), does the Next.js Route Handler file its path resolves to
  actually exist and export a recognized HTTP-method function? Next.js's
  file-based routing means the file path IS the route -- there is no
  mount-prefix indirection to resolve the way the legacy Express scaffold
  needed (no app.js to cross-reference). Endpoint strings keep their
  ":param" notation everywhere else in this codebase (SRS, architecture
  plan, maps_to) -- this is the one place that gets translated into
  Next.js's "[param]" folder convention, purely to derive the expected file
  path. This is regex-based export matching, not a real AST analysis -- it
  will miss unusual export styles and can't verify behavior, only that SOME
  recognized handler was registered in the right file. Treated as a hard
  gate in verify.py precisely because it targets the cheapest, most
  mechanical form of "claims to cover this endpoint but doesn't" bug.
- scan_for_placeholder_stubs: a phrase-based scan for the exact class of
  "in a real app, you would..." placeholder logic found in the real,
  already-merged Login feature (pre-migration). Stack-agnostic, unchanged
  by the Next.js migration. Deliberately informational only (never gates
  verification) -- these phrases are common enough in legitimate comments
  that treating every hit as a hard failure would be too false-positive-
  prone; it exists so a human reviewer sees it in the merge report, not so
  the pipeline blocks on it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_ROUTE_HANDLER_EXPORT_PATTERN = re.compile(
    r"export\s+(?:async\s+)?function\s+(GET|POST|PUT|DELETE|PATCH)\b"
    r"|export\s+const\s+(GET|POST|PUT|DELETE|PATCH)\s*="
)

_PLACEHOLDER_PATTERNS = [
    re.compile(r"in a real app", re.IGNORECASE),
    re.compile(r"not (?:yet )?implemented", re.IGNORECASE),
    re.compile(r"for demonstration purposes", re.IGNORECASE),
    re.compile(r"\bTODO\b"),
    re.compile(r"\bfor now\b", re.IGNORECASE),
]


def _expected_route_file_candidates(endpoint: str) -> list[str]:
    """
    Translate an endpoint path (e.g. "/api/tasks/:id") into the Next.js
    Route Handler file path(s) that must implement it (e.g.
    "app/api/tasks/[id]/route.ts") -- a dynamic segment ":name" becomes a
    "[name]" folder. Returns both the .ts and .js form since the Coder
    Agent's prompt mandates TypeScript but this check stays honest about
    what would actually satisfy Next.js's routing regardless.
    """
    segments = [segment for segment in endpoint.strip("/").split("/") if segment]
    translated = [
        f"[{segment[1:]}]" if segment.startswith(":") else segment
        for segment in segments
    ]
    # `endpoint` already starts with "/api/..." -- app/ is the App Router
    # root, so the file path is app/<endpoint-segments>/route.ts, not
    # app/api/<endpoint-segments>/route.ts (which would double up "api").
    base = "app/" + "/".join(translated) + "/route"
    return [f"{base}.ts", f"{base}.js"]


def check_route_coverage(workspace_root: Path, code_plan_json: dict[str, Any]) -> list[dict[str, str]]:
    """
    For each planned, non-deleted file whose maps_to includes an
    endpoint-shaped string (starts with "/"), check whether the Route
    Handler file that endpoint's path resolves to actually exists and
    exports at least one recognized HTTP-method function.

    Returns [{"endpoint", "file", "status": "found"|"missing"}, ...].
    """
    results: list[dict[str, str]] = []
    checked: set[str] = set()

    for file_entry in code_plan_json.get("files", []):
        if file_entry.get("action") == "delete":
            continue

        endpoints = [
            item
            for item in file_entry.get("maps_to", []) or []
            if isinstance(item, str) and item.startswith("/")
        ]

        for endpoint in endpoints:
            if endpoint in checked:
                continue
            checked.add(endpoint)

            candidates = _expected_route_file_candidates(endpoint)
            route_file = next(
                (workspace_root / candidate for candidate in candidates if (workspace_root / candidate).exists()),
                None,
            )

            if route_file is None:
                results.append({"endpoint": endpoint, "file": candidates[0], "status": "missing"})
                continue

            try:
                content = route_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                results.append({
                    "endpoint": endpoint,
                    "file": route_file.relative_to(workspace_root).as_posix(),
                    "status": "missing",
                })
                continue

            has_handler = bool(_ROUTE_HANDLER_EXPORT_PATTERN.search(content))
            results.append({
                "endpoint": endpoint,
                "file": route_file.relative_to(workspace_root).as_posix(),
                "status": "found" if has_handler else "missing",
            })

    return results


def scan_for_placeholder_stubs(workspace_root: Path, touched_paths: list[str]) -> list[dict[str, Any]]:
    """
    Best-effort scan of every touched file for placeholder-stub language
    (e.g. "in a real app, you would...", "not implemented", "TODO").
    Never used as a pass/fail gate -- see module docstring.
    """
    findings: list[dict[str, Any]] = []

    for relative_path in touched_paths:
        file_path = workspace_root / relative_path

        if not file_path.exists() or not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            for pattern in _PLACEHOLDER_PATTERNS:
                if pattern.search(line):
                    findings.append({"file": relative_path, "line": line_number, "snippet": line.strip()})
                    break

    return findings
