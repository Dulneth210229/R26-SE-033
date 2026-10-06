"""
UI/UX Agent metadata coverage validator.

Purpose:
Validate that ui_metadata_json actually covers every actor and every
screen/interaction implied by the approved SRS. Mirrors the coverage-checking
pattern in architecture_agent/sds_validator.py -- same idea (collect required
IDs, collect covered IDs, diff, raise on any gap), new target document.

This validator is feature-independent: no login/cart/payment-specific logic.
"""

from __future__ import annotations

from typing import Any


class UIMetadataValidationError(Exception):
    """
    Raised when ui_metadata_json does not fully cover the approved SRS.

    Per the build plan: fail loudly here rather than silently proceeding on
    an incomplete mapping -- this is a cheap, deterministic check that catches
    an entire class of "the login page forgot the forgot-password link" bugs
    before a human ever reviews the output.
    """


class UIMetadataValidator:
    """
    Generic coverage validator for ui_metadata_json against an approved SRS.
    """

    # Real, confirmed bug (Sample E-commerce / Item Listing feature): the model echoed the
    # prompt's own example text/field name back verbatim instead of writing real content -- these
    # are the exact strings that showed up in practice, kept case-insensitive/stripped so the
    # check survives minor rewording.
    _PLACEHOLDER_CONTENT_ELEMENTS = {
        "propname",
        "short description of the prop",
        "real, specific content this component displays, e.g. item name, item price",
        "content",
        "value",
        "data",
    }

    def validate(self, srs_json: dict[str, Any], ui_metadata_json: dict[str, Any]) -> None:
        errors: list[str] = []

        errors.extend(self._validate_structure(ui_metadata_json))

        # Coverage checks only need pages to be a non-empty list of dicts to run safely (they
        # call .get() on each page) -- a page-level content gap like missing "states" doesn't
        # make coverage checks unsafe to run, so it must not suppress them. Reporting every
        # real error in one pass matters because a repair attempt only gets one shot: if this
        # gate were "no structural errors at all", a model that both omits "states" AND misses
        # requirement coverage would only ever be told about one problem per attempt, never both.
        if self._is_safe_for_coverage_checks(ui_metadata_json):
            errors.extend(self._validate_actor_coverage(srs_json, ui_metadata_json))
            errors.extend(self._validate_ui_expectation_coverage(srs_json, ui_metadata_json))
            errors.extend(self._validate_requirement_id_coverage(srs_json, ui_metadata_json))

        if errors:
            raise UIMetadataValidationError("; ".join(errors))

    def _is_safe_for_coverage_checks(self, ui_metadata_json: dict[str, Any]) -> bool:
        pages = ui_metadata_json.get("pages")

        return isinstance(pages, list) and bool(pages) and all(isinstance(page, dict) for page in pages)

    def _validate_structure(self, ui_metadata_json: dict[str, Any]) -> list[str]:
        pages = ui_metadata_json.get("pages")

        if not isinstance(pages, list) or not pages:
            return ["ui_metadata_json.pages must be a non-empty list."]

        errors = []

        for index, page in enumerate(pages):
            if not isinstance(page, dict):
                errors.append(f"pages[{index}] must be a JSON object.")
                continue

            if not page.get("page_id") or not page.get("name"):
                errors.append(f"pages[{index}] must have page_id and name.")

            components = page.get("components", [])
            if not isinstance(components, list):
                errors.append(f"pages[{index}].components must be a list.")
            else:
                errors.extend(self._validate_content_elements(index, page.get("page_id"), components))

            states = page.get("states", [])
            required_states = {"idle", "loading", "error", "success"}
            if not required_states.issubset(set(states)):
                errors.append(
                    f"pages[{index}] ({page.get('page_id')}) is missing required states: "
                    f"{sorted(required_states - set(states))}"
                )

        return errors

    def _validate_content_elements(
        self, page_index: int, page_id: Any, components: list[Any]
    ) -> list[str]:
        """
        Catches the real, confirmed bug behind an "empty UI" screenshot at the source: a
        component whose declared content is empty or a literal, unfilled echo of the prompt's own
        example text never had real content to render in the first place, regardless of what the
        component-generation step later does with it.
        """
        errors: list[str] = []

        for component_index, component in enumerate(components):
            if not isinstance(component, dict):
                continue

            name = component.get("name") or f"components[{component_index}]"
            content_elements = component.get("content_elements")

            if not isinstance(content_elements, list) or not content_elements:
                errors.append(
                    f"pages[{page_index}] ({page_id}) component '{name}' has an empty/missing "
                    "content_elements list -- must name the real, specific content it displays."
                )
                continue

            for entry in content_elements:
                normalized = str(entry).strip().lower()
                if not normalized or normalized in self._PLACEHOLDER_CONTENT_ELEMENTS:
                    errors.append(
                        f"pages[{page_index}] ({page_id}) component '{name}' has a placeholder/"
                        f"empty content_elements entry ({entry!r}) instead of real content."
                    )

        return errors

    def _validate_actor_coverage(
        self, srs_json: dict[str, Any], ui_metadata_json: dict[str, Any]
    ) -> list[str]:
        actors_required = set(srs_json.get("user_roles", []) or [])

        if not actors_required:
            return []

        actors_covered: set[str] = set()
        for page in ui_metadata_json.get("pages", []):
            actors_covered.update(page.get("actors", []) or [])

        missing = actors_required - actors_covered
        if missing:
            return [f"ui_metadata_json does not cover these actors from SRS user_roles: {sorted(missing)}"]

        return []

    def _validate_ui_expectation_coverage(
        self, srs_json: dict[str, Any], ui_metadata_json: dict[str, Any]
    ) -> list[str]:
        expectations_required = {
            item.get("element")
            for item in srs_json.get("ui_expectations", []) or []
            if isinstance(item, dict) and item.get("element")
        }

        if not expectations_required:
            return []

        expectations_covered: set[str] = set()
        for page in ui_metadata_json.get("pages", []):
            for component in page.get("components", []) or []:
                if isinstance(component, dict):
                    expectations_covered.update(component.get("covers_ui_expectations", []) or [])

        missing = expectations_required - expectations_covered
        if missing:
            return [f"ui_metadata_json does not cover these SRS ui_expectations: {sorted(missing)}"]

        return []

    def _validate_requirement_id_coverage(
        self, srs_json: dict[str, Any], ui_metadata_json: dict[str, Any]
    ) -> list[str]:
        """
        Every user story and every UI-observable acceptance criterion must be
        referenced by at least one page's covers_requirements list.

        "UI-observable" acceptance criteria are ones whose text implies a
        screen or interaction (redirect, display, message, page, link, form,
        click) -- purely backend-only criteria are out of scope for UI/UX
        coverage.
        """
        ui_observable_keywords = [
            "redirect", "display", "message", "page", "link", "form", "click",
            "show", "shown", "screen", "navigate", "button",
        ]

        required_ids = {
            item.get("id")
            for item in srs_json.get("user_stories", []) or []
            if isinstance(item, dict) and item.get("id")
        }

        for item in srs_json.get("acceptance_criteria", []) or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue

            description = str(item.get("description", "")).lower()
            if any(keyword in description for keyword in ui_observable_keywords):
                required_ids.add(item["id"])

        if not required_ids:
            return []

        covered_ids: set[str] = set()
        for page in ui_metadata_json.get("pages", []):
            covered_ids.update(page.get("covers_requirements", []) or [])

        missing = required_ids - covered_ids
        if missing:
            return [f"ui_metadata_json does not cover these SRS requirement IDs: {sorted(missing)}"]

        return []
