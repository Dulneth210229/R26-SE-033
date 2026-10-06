"""
Coder Agent code plan validator.

Purpose:
Validate that code_plan_json actually covers every SDS endpoint/entity and
every SRS functional requirement relevant to this feature. Mirrors the
coverage-checking pattern in architecture_agent/sds_validator.py -- collect
required strings, collect covered strings, diff, raise on any gap.

This validator is feature-independent: no login/cart/payment-specific logic.
"""

from __future__ import annotations

from typing import Any


class CodePlanValidationError(Exception):
    """
    Raised when code_plan_json does not fully cover the approved SRS/
    Architecture Plan.

    Per the build plan: reject and retry the plan call (not the whole coding
    loop) if coverage is incomplete -- this is a much cheaper place to catch
    a missing endpoint than after the agent has already written code.
    """


class CodePlanValidator:
    """
    Generic coverage validator for code_plan_json against an approved SRS +
    Architecture Plan.
    """

    def validate(
        self,
        srs_json: dict[str, Any],
        architecture_plan_json: dict[str, Any],
        code_plan_json: dict[str, Any],
        enforce_endpoint_coverage: bool = True,
    ) -> None:
        """
        enforce_endpoint_coverage: set False for CoderAgent.revise() calls
        only. The Architecture Plan's api_endpoints are a snapshot from
        before the feature was ever implemented -- for a first run(), every
        one of those literal endpoint strings genuinely must exist somewhere
        in the plan. But a revision builds on an ALREADY-implemented,
        already-approved feature, whose real API shape can legitimately
        evolve past that snapshot (e.g. a refactor from a flat
        `/api/task-comments` to a properly nested `/api/tasks/:taskId/comments`
        + `/api/comments/:commentId`) -- confirmed as a real, reachable,
        totally-blocking case: once that happens, no future revision plan can
        ever satisfy the old literal string again, since it is no longer
        what is actually implemented, and every revise() call would fail
        this check forever regardless of turn budget or plan quality. Entity
        and requirement-ID coverage remain enforced either way -- those
        track WHAT the feature does, not the exact shape of its API, and are
        far less likely to legitimately go stale the same way.
        """
        errors: list[str] = []

        errors.extend(self._validate_structure(code_plan_json))

        if not errors:
            if enforce_endpoint_coverage:
                errors.extend(self._validate_endpoint_coverage(architecture_plan_json, code_plan_json))
            errors.extend(self._validate_entity_coverage(architecture_plan_json, code_plan_json))
            errors.extend(self._validate_requirement_coverage(srs_json, code_plan_json))

        if errors:
            raise CodePlanValidationError("; ".join(errors))

    def _validate_structure(self, code_plan_json: dict[str, Any]) -> list[str]:
        files = code_plan_json.get("files")

        if not isinstance(files, list) or not files:
            return ["code_plan_json.files must be a non-empty list."]

        errors = []
        valid_actions = {"create", "modify", "delete"}

        for index, file_entry in enumerate(files):
            if not isinstance(file_entry, dict):
                errors.append(f"files[{index}] must be a JSON object.")
                continue

            if not file_entry.get("path"):
                errors.append(f"files[{index}] must have a non-empty path.")

            if file_entry.get("action") not in valid_actions:
                errors.append(
                    f"files[{index}] ({file_entry.get('path')}) has invalid action: "
                    f"{file_entry.get('action')!r} (must be one of {sorted(valid_actions)})"
                )

            if not isinstance(file_entry.get("maps_to"), list):
                errors.append(f"files[{index}] ({file_entry.get('path')}) must have a maps_to list.")

        return errors

    def _collect_covered(self, code_plan_json: dict[str, Any]) -> set[str]:
        covered: set[str] = set()

        for file_entry in code_plan_json.get("files", []):
            if isinstance(file_entry, dict):
                covered.update(str(item) for item in file_entry.get("maps_to", []) or [])

        return covered

    def _validate_endpoint_coverage(
        self, architecture_plan_json: dict[str, Any], code_plan_json: dict[str, Any]
    ) -> list[str]:
        design_views = architecture_plan_json.get("design_views", {}) or {}
        api_endpoints = design_views.get("interface_view", {}).get("api_endpoints", []) or []

        required = {
            item.get("endpoint")
            for item in api_endpoints
            if isinstance(item, dict) and item.get("endpoint")
        }

        if not required:
            return []

        missing = required - self._collect_covered(code_plan_json)
        if missing:
            return [f"code_plan_json does not cover these API endpoints: {sorted(missing)}"]

        return []

    def _validate_entity_coverage(
        self, architecture_plan_json: dict[str, Any], code_plan_json: dict[str, Any]
    ) -> list[str]:
        design_views = architecture_plan_json.get("design_views", {}) or {}
        data_entities = design_views.get("data_view", {}).get("data_entities", []) or []

        required = {
            item.get("name")
            for item in data_entities
            if isinstance(item, dict) and item.get("name")
        }

        if not required:
            return []

        missing = required - self._collect_covered(code_plan_json)
        if missing:
            return [f"code_plan_json does not cover these data entities: {sorted(missing)}"]

        return []

    def _validate_requirement_coverage(
        self, srs_json: dict[str, Any], code_plan_json: dict[str, Any]
    ) -> list[str]:
        required = {
            item.get("id")
            for item in srs_json.get("functional_requirements", []) or []
            if isinstance(item, dict) and item.get("id")
        }

        if not required:
            return []

        missing = required - self._collect_covered(code_plan_json)
        if missing:
            return [f"code_plan_json does not cover these functional requirement IDs: {sorted(missing)}"]

        return []


code_plan_validator = CodePlanValidator()
