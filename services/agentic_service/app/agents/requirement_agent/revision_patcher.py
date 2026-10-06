"""
Deterministic SRS revision patcher.

Why this exists:
Asking the LLM to retype the ENTIRE SRS JSON verbatim for every revision (the original design)
is the exact same defect this project already found and fixed for the Domain Agent (see
CLAUDE.md item 29): a local model asked to reproduce a large document byte-for-byte, with only
one or two fields actually changed, is unreliable -- it can silently drop the requested edit
while still returning otherwise-plausible JSON, and on a genuine parse failure the reliability
ladder's fallback used to just clone the existing SRS unchanged, discarding the human's request
entirely with no visible error.

The fix mirrors Domain Agent's: ask the LLM for a SMALL, targeted list of operations (add /
remove / modify / set) instead of the whole document, then apply those operations to the existing
SRS deterministically in Python. A small ask is far more reliable, and a deterministic apply means
"remove this exact NFR" either genuinely happens or is reported as unmatched -- it can no longer
silently no-op inside an otherwise-valid-looking full-document retype.
"""

from __future__ import annotations

import re
from typing import Any

# Fields whose items are plain strings.
STRING_LIST_FIELDS = {
    "scope",
    "out_of_scope",
    "user_roles",
    "ui_expectations",
    "api_expectations",
    "data_requirements",
    "input_requirements",
    "output_requirements",
    "constraints",
    "assumptions",
    "risks",
    "dependencies",
}

# Fields whose items are {"id": "<PREFIX>-NNN", "description": "...", ...} objects.
ID_DESCRIPTION_LIST_FIELDS = {
    "functional_requirements": "FR",
    "non_functional_requirements": "NFR",
    "acceptance_criteria": "AC",
    "validation_rules": "VR",
}

# user_stories has its own distinct shape ({id, role, goal, benefit}) -- handled separately.
USER_STORIES_FIELD = "user_stories"

# Top-level scalar fields a revision may directly overwrite.
SCALAR_FIELDS = {"business_goal", "architectural_style", "target_stack"}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _item_text(item: Any) -> str:
    """Best-effort human-readable text for one list item, regardless of its shape."""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in ("description", "goal", "id"):
            if item.get(key):
                return str(item[key])
        return " ".join(str(v) for v in item.values() if isinstance(v, (str, int, float)))
    return str(item)


def _find_matching_index(items: list, target: str) -> int | None:
    """
    Find the item whose text best matches `target` -- exact match first (case/whitespace
    insensitive), then substring containment in either direction. Substring containment is what
    lets the LLM quote just the distinctive part of a long requirement instead of reproducing it
    character-for-character.
    """
    if not target:
        return None

    target_norm = _normalize(target)

    for index, item in enumerate(items):
        if isinstance(item, dict) and _normalize(str(item.get("id", ""))) == target_norm:
            return index

    for index, item in enumerate(items):
        if _normalize(_item_text(item)) == target_norm:
            return index

    for index, item in enumerate(items):
        item_norm = _normalize(_item_text(item))
        if item_norm and (target_norm in item_norm or item_norm in target_norm):
            return index

    return None


def _next_id(items: list[dict], prefix: str) -> str:
    max_index = 0
    for item in items:
        match = re.match(rf"^{re.escape(prefix)}-(\d+)$", str(item.get("id", "")))
        if match:
            max_index = max(max_index, int(match.group(1)))
    return f"{prefix}-{max_index + 1:03d}"


def apply_revision_operations(srs_json: dict, operations: list[dict]) -> tuple[dict, list[str], list[str]]:
    """
    Apply a small list of revision operations to a copy of `srs_json`.

    Each operation is a dict with an "action" key ("remove" | "add" | "modify" | "set") and a
    "field" key naming one of this SRS's own top-level fields. Returns (patched_srs, applied,
    unmatched) -- `applied`/`unmatched` are human-readable notes for logging/the revision summary,
    never raised as exceptions: an operation this function can't confidently apply is reported,
    not guessed at.
    """

    patched = dict(srs_json)
    applied: list[str] = []
    unmatched: list[str] = []

    for operation in operations:
        if not isinstance(operation, dict):
            unmatched.append(f"Skipped malformed operation: {operation!r}")
            continue

        action = str(operation.get("action", "")).strip().lower()
        field = str(operation.get("field", "")).strip()

        try:
            # A real, confirmed gap: a request to change an EXISTING scalar value (e.g. "update
            # the business goal to also mention...") naturally reads to the model as "modify,"
            # not "set" -- but only "set" was ever accepted here, so a perfectly reasonable
            # synonym silently fell through to the unsupported-field catch-all below and the
            # requested change never happened. "modify"/"set" are treated as equivalent for
            # scalar fields specifically (there's no meaningful difference for a field that's
            # always present, unlike a list where add/modify/remove are genuinely distinct).
            if action in ("set", "modify") and field in SCALAR_FIELDS:
                value = operation.get("value")
                if value:
                    patched[field] = value
                    applied.append(f"Set {field}.")
                else:
                    unmatched.append(f"Skipped '{action} {field}' -- no value provided.")
                continue

            if field == USER_STORIES_FIELD:
                _apply_user_story_operation(patched, action, operation, applied, unmatched)
                continue

            if field in ID_DESCRIPTION_LIST_FIELDS:
                _apply_id_description_operation(patched, field, action, operation, applied, unmatched)
                continue

            if field in STRING_LIST_FIELDS:
                _apply_string_list_operation(patched, field, action, operation, applied, unmatched)
                continue

            unmatched.append(f"Skipped operation on unsupported field '{field}' (action={action}).")
        except Exception as error:  # noqa: BLE001 -- one bad operation must never break the rest
            unmatched.append(f"Skipped operation on '{field}' (action={action}) due to error: {error}")

    if "functional_requirements" in patched:
        patched["traceability"] = _rebuild_traceability(patched.get("functional_requirements", []))

    return patched, applied, unmatched


def _apply_string_list_operation(
    patched: dict, field: str, action: str, operation: dict, applied: list[str], unmatched: list[str]
) -> None:
    items = list(patched.get(field, []))

    if action == "add":
        value = operation.get("value")
        if not value:
            unmatched.append(f"Skipped 'add {field}' -- no value provided.")
            return
        items.append(value)
        patched[field] = items
        applied.append(f"Added to {field}: {value}")
        return

    target = operation.get("target") or operation.get("value")
    index = _find_matching_index(items, target)

    if index is None:
        unmatched.append(f"Could not find a matching entry in {field} for: {target!r}")
        return

    if action == "remove":
        removed = items.pop(index)
        patched[field] = items
        applied.append(f"Removed from {field}: {removed}")
    elif action == "modify":
        new_value = operation.get("value")
        if not new_value:
            unmatched.append(f"Skipped 'modify {field}' -- no replacement value provided.")
            return
        items[index] = new_value
        patched[field] = items
        applied.append(f"Modified {field} entry to: {new_value}")
    else:
        unmatched.append(f"Skipped unsupported action '{action}' on {field}.")


def _apply_id_description_operation(
    patched: dict, field: str, action: str, operation: dict, applied: list[str], unmatched: list[str]
) -> None:
    prefix = ID_DESCRIPTION_LIST_FIELDS[field]
    items = list(patched.get(field, []))

    if action == "add":
        description = operation.get("value") or operation.get("description")
        if not description:
            unmatched.append(f"Skipped 'add {field}' -- no description provided.")
            return
        new_item = {"id": _next_id(items, prefix), "description": description}
        if field == "functional_requirements":
            new_item["priority"] = operation.get("priority", "Should Have")
        elif field == "non_functional_requirements":
            # Previously never set at all (not even a default) despite the prompt schema now
            # documenting "category" -- the exact same silent-default gap already fixed for
            # user_stories' "benefit" (see _apply_user_story_operation).
            new_item["category"] = operation.get("category", "General")
        items.append(new_item)
        patched[field] = items
        applied.append(f"Added to {field}: {description}")
        return

    target = operation.get("target") or operation.get("value")
    index = _find_matching_index(items, target)

    if index is None:
        unmatched.append(f"Could not find a matching entry in {field} for: {target!r}")
        return

    if action == "remove":
        removed = items.pop(index)
        patched[field] = items
        applied.append(f"Removed from {field}: {removed.get('description', removed)}")
    elif action == "modify":
        new_description = operation.get("value") or operation.get("description")
        if not new_description:
            unmatched.append(f"Skipped 'modify {field}' -- no replacement description provided.")
            return
        items[index] = {**items[index], "description": new_description}
        patched[field] = items
        applied.append(f"Modified {field} entry to: {new_description}")
    else:
        unmatched.append(f"Skipped unsupported action '{action}' on {field}.")


def _apply_user_story_operation(
    patched: dict, action: str, operation: dict, applied: list[str], unmatched: list[str]
) -> None:
    items = list(patched.get(USER_STORIES_FIELD, []))

    if action == "add":
        role = operation.get("role", "User")
        goal = operation.get("value") or operation.get("goal")
        if not goal:
            unmatched.append("Skipped 'add user_stories' -- no goal provided.")
            return
        new_item = {
            "id": _next_id(items, "US"),
            "role": role,
            "goal": goal,
            "benefit": operation.get("benefit", "complete the intended business process"),
        }
        items.append(new_item)
        patched[USER_STORIES_FIELD] = items
        applied.append(f"Added user story: {role} -- {goal}")
        return

    target = operation.get("target") or operation.get("value")
    index = _find_matching_index(items, target)

    if index is None:
        unmatched.append(f"Could not find a matching user story for: {target!r}")
        return

    if action == "remove":
        removed = items.pop(index)
        patched[USER_STORIES_FIELD] = items
        applied.append(f"Removed user story: {removed.get('goal', removed)}")
    elif action == "modify":
        # Previously only ever overwrote "goal", even when the operation carried "role"/
        # "benefit" -- a real gap for the field-by-field inline-edit UI, which needs to be able
        # to edit any part of a user story, not just its goal text. Backward-compatible: an
        # operation that only sends "value"/"goal" (every existing caller) behaves identically.
        new_goal = operation.get("value") or operation.get("goal")
        new_role = operation.get("role")
        new_benefit = operation.get("benefit")
        if not new_goal and not new_role and not new_benefit:
            unmatched.append(
                "Skipped 'modify user_stories' -- no replacement goal/role/benefit provided."
            )
            return
        updated = dict(items[index])
        if new_goal:
            updated["goal"] = new_goal
        if new_role:
            updated["role"] = new_role
        if new_benefit:
            updated["benefit"] = new_benefit
        items[index] = updated
        patched[USER_STORIES_FIELD] = items
        changed_parts = [
            part for part, value in (("goal", new_goal), ("role", new_role), ("benefit", new_benefit)) if value
        ]
        applied.append(f"Modified user story ({', '.join(changed_parts)}): {updated.get('goal')}")
    else:
        unmatched.append(f"Skipped unsupported action '{action}' on user_stories.")


def _rebuild_traceability(functional_requirements: list[dict]) -> list[dict]:
    """Keep traceability in sync with whatever functional_requirements now looks like -- reuses
    the same shape conversation_engine._build_traceability produces, without importing across
    that module (this one has no other dependency on conversation_engine)."""
    if not functional_requirements:
        return []
    return [
        {
            "requirement_id": fr["id"],
            "related_acceptance_criteria": [],
            "notes": "Generated by deterministic SRS projection -- refine once acceptance criteria are finalized.",
        }
        for fr in functional_requirements
        if isinstance(fr, dict) and fr.get("id")
    ]
