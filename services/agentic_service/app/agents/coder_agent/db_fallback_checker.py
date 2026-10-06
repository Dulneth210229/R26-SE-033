"""
Coder Agent database-fallback checker (Next.js App Router + MongoDB).

Purpose:
The Coder Agent's prompt now teaches an unconditional rule: every Route
Handler that calls `connectToDatabase()` must branch on a falsy result and
serve realistic seed data from `lib/seedData.ts` instead of an empty/error
response -- so a live preview looks like a working, populated application
even before any real database is connected (see prompt.py's "Database
availability fallback" rule block). Prompt-only rules with no verify()
backstop reliably degrade across coding attempts (this codebase's own
repeated lesson) -- this module closes that gap with the same two-tier,
deterministic, best-effort static-check pattern route_checker.py already
established:

- check_db_null_guard_coverage: for each planned, non-deleted Route Handler
  file that calls `connectToDatabase()`, does the file contain SOME branch
  keyed on a falsy check of that call's result? Regex-based, not a real AST
  analysis -- it will miss unusual guard styles and can't verify the branch
  actually returns anything, only that the mechanical shape of a null check
  exists. Treated as a hard gate in verify.py, same rationale as
  check_route_coverage: it targets the cheapest, most mechanical form of
  "claims to guard against no DB but doesn't" bug (an unguarded crash).
- scan_for_db_fallback_quality: among files that DO have a detected guard,
  flags one whose branch body looks like a bare empty array/object or an
  error response instead of populated data. Deliberately informational only
  (never gates verification) -- judging whether fallback data is "realistic"
  is not something a regex heuristic can reliably do; this exists so a human
  reviewer sees a likely-weak fallback in the merge report, not so the
  pipeline blocks on it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_CONNECT_CALL_PATTERN = re.compile(
    r"(?:const|let|var)\s+(\w+)\s*=\s*await\s+connectToDatabase\s*\(\s*\)"
)

_BARE_FALLBACK_PATTERNS = [
    re.compile(r"NextResponse\.json\(\s*\[\s*\]"),
    re.compile(r"NextResponse\.json\(\s*\{\s*\}"),
    re.compile(r"status:\s*(?:4\d\d|5\d\d)"),
    re.compile(r"unavailable", re.IGNORECASE),
]


def _has_null_guard(content: str, variable: str) -> bool:
    guard_pattern = re.compile(
        rf"if\s*\(\s*!\s*{re.escape(variable)}\b|if\s*\(\s*{re.escape(variable)}\s*===?\s*null\b"
    )
    return bool(guard_pattern.search(content))


def _is_route_handler_path(path: str) -> bool:
    return path.startswith("app/api/") and path.endswith(("route.ts", "route.js"))


def check_db_null_guard_coverage(workspace_root: Path, code_plan_json: dict[str, Any]) -> list[dict[str, str]]:
    """
    Returns [{"file": path, "status": "missing"}, ...] -- only files with a
    detected connectToDatabase() call but no detected null-guard branch are
    reported; a file with no DB call at all, or with a guard found, is fine.
    """
    results: list[dict[str, str]] = []

    for file_entry in code_plan_json.get("files", []):
        if file_entry.get("action") == "delete":
            continue

        path = file_entry.get("path", "")
        if not _is_route_handler_path(path):
            continue

        file_path = workspace_root / path
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        match = _CONNECT_CALL_PATTERN.search(content)
        if not match:
            continue

        if not _has_null_guard(content, match.group(1)):
            results.append({"file": path, "status": "missing"})

    return results


def scan_for_db_fallback_quality(workspace_root: Path, touched_paths: list[str]) -> list[dict[str, Any]]:
    """
    Informational-only best-effort scan (same "flag it for a human, never
    gate on it" precedent as route_checker.scan_for_placeholder_stubs).
    """
    findings: list[dict[str, Any]] = []

    for relative_path in touched_paths:
        if not _is_route_handler_path(relative_path):
            continue

        file_path = workspace_root / relative_path
        if not file_path.exists() or not file_path.is_file():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        match = _CONNECT_CALL_PATTERN.search(content)
        if not match or not _has_null_guard(content, match.group(1)):
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            for pattern in _BARE_FALLBACK_PATTERNS:
                if pattern.search(line):
                    findings.append({"file": relative_path, "line": line_number, "snippet": line.strip()})
                    break

    return findings
