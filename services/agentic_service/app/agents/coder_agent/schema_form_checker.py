"""
Coder Agent schema/form coverage checker (Next.js + Mongoose).

Purpose:
A real, reported bug ("Failed to save item" on a live generated Item Listing CRUD feature) traced
back to a Mongoose model declaring a `required: true` field (a custom `id` string) that no
generated form ever actually collected -- every create silently sent an empty value for it,
colliding on the field's own unique index after the first item and throwing an opaque 500 the
frontend then blanketed into a generic "Failed to save item" message. Prompt-only rules ("never
require a client-supplied id") are not fully reliable on their own -- this codebase's own
repeated lesson about local-model prompt compliance -- so this module closes the gap
deterministically, the same "cheap, regex-based, explicitly not a real AST analysis, best-effort"
precedent already established by db_fallback_checker.check_db_null_guard_coverage.

check_required_field_form_coverage: for each planned, non-deleted Mongoose model file, extracts
field names declared `required: true` (or `required: [true, "message"]`), excluding fields this
pipeline's own scaffold/Mongoose itself already manages automatically (_id, createdAt, updatedAt,
__v -- a real Mongoose document always has these regardless of what any form submits). For each
remaining required field, checks whether the field name appears as a REAL, editable form input (a
JSX `name="fieldName"` attribute, or an inline controlled-input assignment like `fieldName:
e.target.value`) in ANY of the plan's own touched frontend files (.tsx pages/components) --
scanning every touched frontend file rather than trying to resolve one single "matching" page is
simpler and no less accurate in practice, since a feature's create/edit form is typically the only
page that ever imports the model's create endpoint anyway. Deliberately does NOT treat a bare
object key (e.g. `fieldName: ""` in a useState initializer) as evidence of coverage -- that is
exactly the shape the real reported bug's own buggy code already had (a dead default value with no
way for a human to ever change it), so counting it would make this checker blind to the one bug
class it exists to catch. A required field with no real-input match anywhere is reported "missing"
-- wired into
verify.py as a hard gate, since a client genuinely has no way to satisfy a `required` field it was
never given a way to set, and this catches exactly that mechanically, regardless of which model
(agentic or non-agentic) produced the code.

Known, honest limitation (regex, not a real AST parser, same class of gap every sibling checker in
this file already documents): a field whose own schema-object literal contains a NESTED brace
(e.g. a `validate: { validator: ..., message: ... }` sub-object) before its `required: true` key
will not be detected, since the pattern deliberately never crosses a `{`/`}` boundary to avoid
misattributing a later field's `required: true` to an earlier one with none. Rare in the real,
generated schemas this project produces (which use flat, single-line field definitions), and a
false negative here (missing a real gap) is the safe failure direction for a hard gate.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_REQUIRED_FIELD_PATTERN = re.compile(
    r"(\w+)\s*:\s*\{[^{}]*?required\s*:\s*(?:true\b|\[\s*true\b)", re.DOTALL
)

_AUTO_MANAGED_FIELD_NAMES = {"_id", "createdAt", "updatedAt", "__v"}

_MODEL_FILE_PATTERN = re.compile(r"^models/[^/]+\.tsx?$")
_FRONTEND_FILE_SUFFIXES = (".tsx",)


def _is_model_file(path: str) -> bool:
    return bool(_MODEL_FILE_PATTERN.match(path))


def _extract_required_fields(content: str) -> list[str]:
    names = []
    for match in _REQUIRED_FIELD_PATTERN.finditer(content):
        name = match.group(1)
        if name not in _AUTO_MANAGED_FIELD_NAMES and name not in names:
            names.append(name)
    return names


def _field_referenced_in_form(content: str, field: str) -> bool:
    """
    Deliberately does NOT match a bare object key like `field: ""` -- that pattern is exactly
    what the real reported bug's OWN buggy state initializer looked like (`id: ""` sitting in a
    useState default with no way for a human to ever change it), so treating "the key exists
    somewhere" as evidence of coverage would make this checker blind to the exact bug it exists
    to catch. Requires real evidence the field is genuinely settable: a JSX `name="field"`
    attribute (this codebase's generated forms wire a single generic onChange handler keyed by
    each input's own `name`, so the field's name literally only appears here) or an inline
    controlled-input assignment (`field: e.target.value`), the other realistic React pattern.
    """
    name_attr_pattern = re.compile(rf'name\s*=\s*["\']{re.escape(field)}["\']')
    inline_assignment_pattern = re.compile(
        rf"\b{re.escape(field)}\s*:\s*(?:e|event)\.target\.value"
    )
    return bool(name_attr_pattern.search(content) or inline_assignment_pattern.search(content))


def check_required_field_form_coverage(workspace_root: Path, code_plan_json: dict[str, Any]) -> list[dict[str, str]]:
    """
    Returns [{"field", "model_file", "status": "missing"}, ...] -- only fields with no detected
    form reference anywhere are reported; a field found in at least one frontend file, or a model
    file with no `required: true` fields at all, is fine.
    """
    files = code_plan_json.get("files", []) or []
    non_deleted = [entry for entry in files if entry.get("action") != "delete"]

    model_paths = [entry.get("path", "") for entry in non_deleted if _is_model_file(entry.get("path", ""))]
    frontend_paths = [
        entry.get("path", "") for entry in non_deleted
        if entry.get("path", "").endswith(_FRONTEND_FILE_SUFFIXES)
    ]

    if not model_paths or not frontend_paths:
        return []

    frontend_contents: list[str] = []
    for path in frontend_paths:
        file_path = workspace_root / path
        if not file_path.exists():
            continue
        try:
            frontend_contents.append(file_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError):
            continue

    results: list[dict[str, str]] = []

    for model_path in model_paths:
        file_path = workspace_root / model_path
        if not file_path.exists():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        for field in _extract_required_fields(content):
            if not any(_field_referenced_in_form(frontend_content, field) for frontend_content in frontend_contents):
                results.append({"field": field, "model_file": model_path, "status": "missing"})

    return results
