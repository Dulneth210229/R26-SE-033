"""
Coder Agent functional CRUD checker (Next.js + MongoDB).

Purpose:
Every other check in this pipeline proves the app *compiles*, *boots*, *renders*, and (per
route_checker.check_route_coverage) has a route FILE exporting the right HTTP method name -- none
of them ever exercise what a handler's own code actually does with a real request. Confirmed
directly: the real, reported "Failed to save item" bug passed every existing gate, because a POST
handler that validates input then throws on a real Mongoose write is indistinguishable, to every
static check in this codebase, from one that works. This module closes that specific gap with a
real HTTP POST-then-GET exercise against the app's own already-running server (see render_checker.
check_runtime_render's `on_server_ready` callback -- this module never starts its own server;
there is no live, reachable server anywhere else during verify()).

Deliberately informational-only (never gates `verification_passed`), unlike schema_form_checker.py
(the deterministic, hard-gated fix for the exact reported bug class). The reason is real and
specific, not caution for its own sake: payload synthesis here is a best-effort heuristic over
whatever a create form's own state initializer happens to look like -- it will correctly skip (not
fail) an endpoint requiring auth, an enum-constrained field, a relational/foreign-key field, or a
file upload, but a synthesizer confident enough to try and wrong often enough to matter is a real,
plausible risk for a heuristic this young. This check's value is independent, broader "does the
endpoint even work at all" coverage; a single create+read-back also does NOT itself reproduce a
*second-create* duplicate-key failure the way the real reported bug manifested -- that specific
class is what schema_form_checker's deterministic, hard-gated field-coverage check exists to catch
reliably. Real failure detail (the actual HTTP status + response body) is always surfaced, feeding
the next coding attempt's retry context regardless of this check's own soft status.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_POST_HANDLER_PATTERN = re.compile(
    r"export\s+(?:async\s+)?function\s+POST\b|export\s+const\s+POST\s*="
)

_USE_STATE_OBJECT_PATTERN = re.compile(
    r"useState\s*\(\s*\{([^{}]*)\}\s*\)", re.DOTALL
)

_STRING_LITERAL_VALUE = re.compile(r"""^["'](.*)["']$""")
_NUMBER_LITERAL_VALUE = re.compile(r"^-?\d+(?:\.\d+)?$")

_MARKER_VALUE = "AutoForgeCrudCheck"
REQUEST_TIMEOUT_SECONDS = 10


def _is_route_handler_path(path: str) -> bool:
    return path.startswith("app/api/") and path.endswith(("route.ts", "route.js"))


def _endpoint_from_route_path(path: str) -> str:
    """app/api/items/route.ts -> /api/items (the inverse of route_checker's own translation --
    Next.js's file-based routing means the file path already IS the route)."""
    without_route_file = path.rsplit("/", 1)[0]
    return "/" + without_route_file[len("app/"):] if without_route_file.startswith("app/") else "/" + without_route_file


def discover_post_endpoints(workspace_root: Path, code_plan_json: dict[str, Any]) -> list[dict[str, str]]:
    """Only planned, non-deleted, non-parameterized (no "[..]" segment -- a create endpoint is
    always the collection route, never an item-by-id one) route files exporting POST."""
    results: list[dict[str, str]] = []

    for file_entry in code_plan_json.get("files", []) or []:
        if file_entry.get("action") == "delete":
            continue

        path = file_entry.get("path", "")
        if not _is_route_handler_path(path) or "[" in path:
            continue

        file_path = workspace_root / path
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if _POST_HANDLER_PATTERN.search(content):
            results.append({"endpoint": _endpoint_from_route_path(path), "file": path})

    return results


def _infer_placeholder(raw_value: str, mark_as_distinctive: bool) -> Any | None:
    raw_value = raw_value.strip()

    string_match = _STRING_LITERAL_VALUE.match(raw_value)
    if string_match:
        return _MARKER_VALUE if mark_as_distinctive else "test"

    if _NUMBER_LITERAL_VALUE.match(raw_value):
        return 1

    if raw_value in ("true", "false"):
        return True

    return None  # can't confidently infer (a variable reference, Date.now(), an array, etc.)


def synthesize_payload_from_form(frontend_files_content: list[str]) -> dict[str, Any] | None:
    """
    Best-effort: finds the first `useState({...})` call, across the given frontend files in
    order, whose object literal has at least 2 keys (a plausible multi-field create-form state,
    as opposed to a single loading/open boolean) and synthesizes a minimal payload from its own
    keys/default-value shapes. Returns None if no confident candidate is found -- deliberately
    never guesses at a payload it isn't reasonably sure about.
    """
    for content in frontend_files_content:
        for match in _USE_STATE_OBJECT_PATTERN.finditer(content):
            body = match.group(1)
            entries = [entry.strip() for entry in body.split(",") if entry.strip()]

            pairs: list[tuple[str, str]] = []
            for entry in entries:
                if ":" not in entry:
                    continue
                key, _, value = entry.partition(":")
                pairs.append((key.strip(), value.strip()))

            if len(pairs) < 2:
                continue

            payload: dict[str, Any] = {}
            for index, (key, raw_value) in enumerate(pairs):
                placeholder = _infer_placeholder(raw_value, mark_as_distinctive=(index == 0))
                if placeholder is not None:
                    payload[key] = placeholder

            if payload:
                return payload

    return None


def _http_request(base_url: str, path: str, method: str, body: dict[str, Any] | None) -> dict[str, Any]:
    url = base_url + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data is not None else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
            return {"status_code": response.status, "body": raw_body}
    except urllib.error.HTTPError as error:
        raw_body = error.read().decode("utf-8", errors="replace")
        return {"status_code": error.code, "body": raw_body}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"status_code": None, "body": str(error)}


def check_crud_functionality(
    workspace_root: Path, code_plan_json: dict[str, Any], base_url: str
) -> list[dict[str, Any]]:
    """
    Returns one result per candidate endpoint:
    {"endpoint", "status": "passed"|"failed"|"skipped", "output"}.

    "skipped" means no confident POST endpoint or payload was found (never treated as a failure).
    "failed" means a real POST returned a non-2xx status, or the created value never showed up on
    a follow-up GET -- the real response status/body is always included in `output`.
    """
    endpoints = discover_post_endpoints(workspace_root, code_plan_json)
    if not endpoints:
        return [{"endpoint": None, "status": "skipped", "output": "No planned POST endpoint found to check."}]

    frontend_paths = [
        entry.get("path", "") for entry in code_plan_json.get("files", []) or []
        if entry.get("action") != "delete" and entry.get("path", "").endswith(".tsx")
    ]
    frontend_contents = []
    for path in frontend_paths:
        file_path = workspace_root / path
        if not file_path.exists():
            continue
        try:
            frontend_contents.append(file_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue

    payload = synthesize_payload_from_form(frontend_contents)
    if payload is None:
        return [{
            "endpoint": None, "status": "skipped",
            "output": "Could not confidently synthesize a create payload from any planned form's "
            "own state -- skipping the functional check for this attempt.",
        }]

    results: list[dict[str, Any]] = []
    for endpoint_info in endpoints:
        endpoint = endpoint_info["endpoint"]
        post_result = _http_request(base_url, endpoint, "POST", payload)
        status_code = post_result["status_code"]

        if status_code is None or not (200 <= status_code < 300):
            results.append({
                "endpoint": endpoint, "status": "failed", "reason": "post_rejected",
                "output": f"POST {endpoint} with a synthesized payload {payload!r} returned "
                f"HTTP {status_code}: {post_result['body'][:500]}",
            })
            continue

        get_result = _http_request(base_url, endpoint, "GET", None)
        marker_present = _MARKER_VALUE in (get_result["body"] or "")

        if not marker_present:
            # Distinguished from "post_rejected" above via an explicit "reason" field (not
            # output-text parsing) specifically so verify.py can hard-gate on THIS failure shape
            # alone when a real MongoDB URI is configured -- a 2xx response already means the
            # backend accepted the payload as valid, so the write's own value never reappearing is
            # real, unambiguous evidence of a route that isn't genuinely persisting to (or reading
            # from) the real database, as opposed to "post_rejected," which a real, correct
            # validation rule can legitimately trigger against a heuristically-guessed payload.
            results.append({
                "endpoint": endpoint, "status": "failed", "reason": "not_persisted",
                "output": f"POST {endpoint} returned HTTP {status_code}, but the created item's "
                f"distinctive value ({_MARKER_VALUE!r}) never appeared on a follow-up GET -- "
                "the write may not have actually persisted.",
            })
            continue

        results.append({
            "endpoint": endpoint, "status": "passed",
            "output": f"POST {endpoint} returned HTTP {status_code} and the created item was "
            "confirmed present on a follow-up GET.",
        })

    return results
