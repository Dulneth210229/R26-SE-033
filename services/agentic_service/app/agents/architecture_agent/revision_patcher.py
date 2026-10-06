"""
Deterministic Architecture Plan revision patcher.

Why this exists:
Architecture Agent's revise() used to ask the LLM to retype the ENTIRE architecture_plan_json
object verbatim for every revision -- the exact same defect this project already found and fixed
for the Requirement Agent (see requirement_agent/revision_patcher.py) and the Domain Agent: a
local model asked to reproduce a large document byte-for-byte, with only one or two fields
actually changed, is unreliable. On a genuine parse failure the reliability ladder's fallback
(_fallback_revise_architecture_plan_json) just clones the existing plan unchanged, discarding the
human's request entirely with no visible error -- confirmed as a REAL, already-reached failure
mode, not hypothetical (a real generated plan's own revision_metadata.fallback_used=True proves a
past revision request was silently dropped this exact way).

The fix mirrors the Requirement Agent's: ask the LLM for a SMALL, targeted list of operations
(add / remove / modify / set) instead of the whole document, then apply those operations to the
existing plan deterministically in Python.

Why this is a NEW file rather than reusing requirement_agent/revision_patcher.py directly: the
Architecture Plan schema is far more deeply nested (e.g. implementation_plan.backend.endpoints,
design_views.interface_view.api_endpoints) and far more heterogeneous in how its list items are
keyed (a file by "path", an endpoint by "method"+"path", a data entity by "name", a coder task by
"task_id") -- there is no single dominant "description" field the way FR/NFR/AC/VR have. So this
patcher dispatches by the RUNTIME SHAPE found at a resolved dotted path, not by a fixed map of
known top-level field names. The proven 3-tier matching cascade (exact-id-like-key match -> exact
text match -> substring containment) and the never-silent applied/unmatched reporting contract are
mirrored exactly, not reinvented.
"""

from __future__ import annotations

import copy
import re
from typing import Any

# Sentinel distinguishing "path resolved to a real None/empty value" from "path doesn't exist at
# all" -- the latter must be reported as unmatched (the LLM named something that isn't in the
# plan), the former is a legitimate, patchable scalar value.
_MISSING = object()

# Priority-ordered keys checked when building a human-readable "what is this item" string, or when
# matching a human-quoted `target` against a list item -- covers every real key shape this
# project's own generated Architecture Plans actually use across their many differently-shaped
# nested lists (files, endpoints, data entities, coder tasks, traceability rows, etc.).
_TEXT_KEY_PRIORITY = ("id", "name", "path", "endpoint", "task_id", "task", "source_id", "description")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _item_text(item: Any) -> str:
    """Best-effort human-readable text for one list item, regardless of its shape."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        # Endpoint-shaped items (a "method" alongside a "path"/"endpoint") read far better as
        # "GET /api/x" than as just the bare path -- and this project's real schema has TWO
        # differently-keyed endpoint list shapes (implementation_plan.backend.endpoints uses
        # "path"; design_views.interface_view.api_endpoints uses "endpoint"), so both are checked.
        method = item.get("method")
        path_like = item.get("path") or item.get("endpoint")
        if method and path_like:
            return f"{method} {path_like}"
        for key in _TEXT_KEY_PRIORITY:
            if item.get(key):
                return str(item[key])
        return " ".join(str(v) for v in item.values() if isinstance(v, (str, int, float)))
    return str(item)


def _item_full_text(item: Any) -> str:
    """
    Every string/number field of an item, space-joined -- broader than _item_text (which only
    ever returns ONE identity-ish field, e.g. just a file's "path"). Used only for the substring-
    containment matching tier below, so a distinctive quote from ANY field of an item (not just
    its identity field -- e.g. a file's "purpose" text, not just its "path") can still find it.
    """
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return " ".join(str(value) for value in item.values() if isinstance(value, (str, int, float)))
    return str(item)


def _find_matching_index(items: list, target: str | None) -> int | None:
    """
    Find the item whose text best matches `target` -- exact match against one of the common
    identifying keys first, then exact match against the item's overall best-effort text, then
    substring containment (checked against every field's text, not just the identity field) in
    either direction -- lets the LLM quote just a distinctive fragment of any part of an item
    instead of reproducing its full text character-for-character.
    """
    if not target:
        return None

    target_norm = _normalize(str(target))

    for index, item in enumerate(items):
        if isinstance(item, dict):
            for key in _TEXT_KEY_PRIORITY:
                if key in item and item[key] and _normalize(str(item[key])) == target_norm:
                    return index

    for index, item in enumerate(items):
        if _normalize(_item_text(item)) == target_norm:
            return index

    for index, item in enumerate(items):
        item_norm = _normalize(_item_full_text(item))
        if item_norm and (target_norm in item_norm or item_norm in target_norm):
            return index

    return None


def _infer_wrap_key(items: list) -> str:
    """
    When an `add`/`modify` operation supplies a bare string `value` for a field whose items are
    JSON objects, decide which key to wrap it under -- majority-vote over which _TEXT_KEY_PRIORITY
    key existing sibling items actually use (e.g. a plan whose items all have "name" wraps into
    {"name": value}), defaulting to "description" when there's nothing to learn from (an empty
    list, or items with none of the known keys).
    """
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        for key in _TEXT_KEY_PRIORITY:
            if key in item:
                counts[key] = counts.get(key, 0) + 1
                break
    if not counts:
        return "description"
    return max(counts, key=counts.get)


def _resolve_path(root: dict, dotted_path: str) -> tuple[Any, dict | None, str | None]:
    """
    Walk `root` by "."-separated segments. Returns (value, parent_dict, last_key) so a caller can
    both read the current value and mutate it in place via parent_dict[last_key] = ..., or
    (_MISSING, None, None) if any segment doesn't exist. Deliberately never auto-creates a missing
    section -- every real required section already exists by the time a revision runs (the plan
    was already generated and validated once), so a genuinely missing path means the LLM named
    something that isn't actually in the plan; that must be reported as unmatched, not guessed at.
    """
    if not dotted_path:
        return _MISSING, None, None

    segments = dotted_path.split(".")
    current = root

    for segment in segments[:-1]:
        if not isinstance(current, dict) or segment not in current:
            return _MISSING, None, None
        current = current[segment]

    last_key = segments[-1]
    if not isinstance(current, dict) or last_key not in current:
        return _MISSING, None, None

    return current[last_key], current, last_key


def apply_architecture_revision_operations(
    architecture_plan_json: dict, operations: list[dict]
) -> tuple[dict, list[str], list[str]]:
    """
    Apply a small list of revision operations to a copy of `architecture_plan_json`.

    Each operation is a dict with "action" ("add" | "remove" | "modify" | "set"), a dotted "field"
    path (e.g. "implementation_plan.backend.endpoints"), and "target"/"value" as appropriate.
    Returns (patched_plan, applied, unmatched) -- `applied`/`unmatched` are human-readable notes,
    never raised as exceptions: an operation this function can't confidently apply is reported,
    not guessed at or silently dropped.

    Structural safety: this function never deletes a dict KEY (only list items by index, or
    scalar/dict VALUES) -- every top-level and design_views key present before patching is still
    present after, by construction, so a revision can never accidentally strip a section the
    validator requires.
    """
    patched = copy.deepcopy(architecture_plan_json)
    applied: list[str] = []
    unmatched: list[str] = []

    for operation in operations:
        if not isinstance(operation, dict):
            unmatched.append(f"Skipped malformed operation: {operation!r}")
            continue

        action = str(operation.get("action", "")).strip().lower()
        field = str(operation.get("field", "")).strip()

        try:
            value_at_path, parent, key = _resolve_path(patched, field)

            if value_at_path is _MISSING:
                unmatched.append(f"Skipped '{action} {field}' -- path not found in the current Architecture Plan.")
                continue

            if isinstance(value_at_path, list):
                _apply_list_operation(parent, key, action, operation, applied, unmatched, field)
            elif isinstance(value_at_path, dict):
                _apply_dict_leaf_operation(parent, key, action, operation, applied, unmatched, field)
            elif value_at_path is None or isinstance(value_at_path, (str, int, float, bool)):
                _apply_scalar_operation(parent, key, action, operation, applied, unmatched, field)
            else:
                unmatched.append(f"Skipped '{action} {field}' -- unsupported value type at this path.")
        except Exception as error:  # noqa: BLE001 -- one bad operation must never break the rest
            unmatched.append(f"Skipped operation on '{field}' (action={action}) due to error: {error}")

    return patched, applied, unmatched


def _apply_list_operation(
    parent: dict, key: str, action: str, operation: dict, applied: list[str], unmatched: list[str], field: str
) -> None:
    items = list(parent.get(key, []))

    if action == "add":
        value = operation.get("value")
        if value in (None, ""):
            unmatched.append(f"Skipped 'add {field}' -- no value provided.")
            return
        if isinstance(value, dict):
            items.append(value)
            applied.append(f"Added to {field}: {_item_text(value)}")
        elif items and isinstance(items[0], dict):
            # Existing items are objects but the LLM supplied a bare string -- wrap it under
            # whichever key this field's siblings actually use, rather than rejecting a
            # perfectly reasonable request just because it wasn't phrased as a full JSON object.
            wrap_key = _infer_wrap_key(items)
            items.append({wrap_key: value})
            applied.append(f"Added to {field}: {value}")
        else:
            items.append(value)
            applied.append(f"Added to {field}: {value}")
        parent[key] = items
        return

    target = operation.get("target")
    if not target and not isinstance(operation.get("value"), dict):
        target = operation.get("value")
    index = _find_matching_index(items, target)

    if index is None:
        unmatched.append(f"Could not find a matching entry in {field} for: {target!r}")
        return

    if action == "remove":
        removed = items.pop(index)
        parent[key] = items
        applied.append(f"Removed from {field}: {_item_text(removed)}")
        return

    if action in ("modify", "set"):
        value = operation.get("value")
        if value in (None, ""):
            unmatched.append(f"Skipped '{action} {field}' -- no replacement value provided.")
            return
        if isinstance(items[index], dict):
            if isinstance(value, dict):
                # Partial merge -- a request to change just one field (e.g. "response") doesn't
                # need to restate the whole endpoint/file/entity object.
                items[index] = {**items[index], **value}
            else:
                wrap_key = _infer_wrap_key(items)
                items[index] = {**items[index], wrap_key: value}
        else:
            items[index] = value
        parent[key] = items
        applied.append(f"Modified {field} entry: {_item_text(items[index])}")
        return

    unmatched.append(f"Skipped unsupported action '{action}' on {field}.")


def _apply_dict_leaf_operation(
    parent: dict, key: str, action: str, operation: dict, applied: list[str], unmatched: list[str], field: str
) -> None:
    """A resolved path pointing at a nested OBJECT (e.g. implementation_plan.frontend.routing),
    not a list -- only set/modify (a shallow merge) make sense here. add/remove are rejected with
    a message steering the model toward a specific nested list path instead of silently no-op'ing,
    since "add to a dict" is ambiguous without knowing which of its own sub-fields is meant."""
    if action in ("modify", "set"):
        value = operation.get("value")
        if not isinstance(value, dict):
            unmatched.append(
                f"Skipped '{action} {field}' -- value must be a JSON object to merge into this section."
            )
            return
        current = dict(parent.get(key, {}) or {})
        current.update(value)
        parent[key] = current
        applied.append(f"Updated {field}.")
        return

    unmatched.append(
        f"Skipped '{action} {field}' -- this is a nested section, not a list. Target a specific "
        f"field inside it instead (e.g. '{field}.<sub_field>')."
    )


def _apply_scalar_operation(
    parent: dict, key: str, action: str, operation: dict, applied: list[str], unmatched: list[str], field: str
) -> None:
    if action in ("set", "modify"):
        value = operation.get("value")
        if value in (None, ""):
            unmatched.append(f"Skipped '{action} {field}' -- no value provided.")
            return
        parent[key] = value
        applied.append(f"Set {field}.")
        return

    unmatched.append(f"Skipped unsupported action '{action}' on scalar field '{field}'.")
