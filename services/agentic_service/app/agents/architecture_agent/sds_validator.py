"""
Architecture Agent Architecture Plan Validator.

Purpose:
Validate that the generated Architecture Plan is complete and covers the
approved SRS.

This validator is feature-independent.
It does not contain Login-specific, Cart-specific, Payment-specific, or LMS-specific logic.
"""

from __future__ import annotations

from typing import Any


class ArchitecturePlanValidationError(Exception):
    """
    Raised when the generated Architecture Plan is incomplete or not aligned with the SRS.
    """


class ArchitecturePlanValidator:
    """
    Generic validator for feature-level Architecture Plan artifacts.
    """

    REQUIRED_TOP_LEVEL_KEYS = [
        "document_control",
        "feature_overview",
        "requirement_interpretation",
        "architecture_approach",
        "design_views",
        "frontend_architecture_plan",
        "backend_architecture_plan",
        "validation_plan",
        "coder_implementation_tasks",
        "traceability_matrix",
        "assumptions",
        "constraints",
        "risks",
        "dependencies",
        "human_approval_note",
    ]

    REQUIRED_DESIGN_VIEWS = [
        "context_view",
        "logical_view",
        "interface_view",
        "data_view",
        "behavior_view",
        "error_handling_view",
        "security_authorization_view",
        "quality_attributes_view",
    ]

    FORBIDDEN_PLAN_KEYS = [
        "use_case_diagram_reference",
        "sequence_diagram_reference",
        "class_diagram_reference",
    ]

    def validate(self, srs_json: dict[str, Any], architecture_plan_json: dict[str, Any]) -> None:
        """
        Validate Architecture Plan structure and SRS coverage.

        Raises:
            ArchitecturePlanValidationError if the Architecture Plan is incomplete.
        """

        errors: list[str] = []

        errors.extend(self._validate_required_structure(architecture_plan_json))
        errors.extend(self._validate_no_diagram_reference_sections(architecture_plan_json))
        errors.extend(self._validate_design_views(architecture_plan_json))
        errors.extend(self._validate_traceability_coverage(srs_json, architecture_plan_json))
        errors.extend(self._validate_interface_coverage(srs_json, architecture_plan_json))
        errors.extend(self._validate_data_coverage(srs_json, architecture_plan_json))
        errors.extend(self._validate_quality_coverage(srs_json, architecture_plan_json))
        errors.extend(self._validate_coder_tasks(srs_json, architecture_plan_json))
        errors.extend(self._validate_implementation_plan(srs_json, architecture_plan_json))
        errors.extend(self._validate_no_weak_sds_text(architecture_plan_json))

        if errors:
            raise ArchitecturePlanValidationError("; ".join(errors))

    def _validate_required_structure(self, architecture_plan_json: dict[str, Any]) -> list[str]:
        errors = []

        for key in self.REQUIRED_TOP_LEVEL_KEYS:
            if key not in architecture_plan_json:
                errors.append(f"Architecture Plan missing required top-level key: {key}")

        return errors

    def _validate_no_diagram_reference_sections(self, architecture_plan_json: dict[str, Any]) -> list[str]:
        errors = []

        for key in self.FORBIDDEN_PLAN_KEYS:
            if key in architecture_plan_json:
                errors.append(f"Architecture Plan must not include diagram reference section: {key}")

        return errors

    def _validate_design_views(self, architecture_plan_json: dict[str, Any]) -> list[str]:
        errors = []

        design_views = architecture_plan_json.get("design_views")

        if not isinstance(design_views, dict):
            return ["Architecture Plan design_views must be a JSON object."]

        for view_name in self.REQUIRED_DESIGN_VIEWS:
            if view_name not in design_views:
                errors.append(f"Architecture Plan missing required design view: {view_name}")

        return errors

    def _validate_traceability_coverage(
        self,
        srs_json: dict[str, Any],
        architecture_plan_json: dict[str, Any]
    ) -> list[str]:
        errors = []

        required_ids = []
        required_ids.extend(self._collect_ids(srs_json.get("functional_requirements", [])))
        required_ids.extend(self._collect_ids(srs_json.get("acceptance_criteria", [])))
        required_ids.extend(self._collect_ids(srs_json.get("validation_rules", [])))
        required_ids.extend(self._collect_ids(srs_json.get("non_functional_requirements", [])))

        traceability = architecture_plan_json.get("traceability_matrix", [])

        if not isinstance(traceability, list):
            return ["Architecture Plan traceability_matrix must be a list."]

        covered_ids = set()
        for item in traceability:
            if isinstance(item, dict) and item.get("source_id"):
                covered_ids.add(str(item["source_id"]))

        missing = [source_id for source_id in required_ids if source_id not in covered_ids]

        if missing:
            errors.append(f"Architecture Plan traceability_matrix missing SRS IDs: {missing}")

        return errors

    def _validate_interface_coverage(
        self,
        srs_json: dict[str, Any],
        architecture_plan_json: dict[str, Any]
    ) -> list[str]:
        errors = []

        interface_view = architecture_plan_json.get("design_views", {}).get("interface_view", {})

        api_expectations = srs_json.get("api_expectations", [])
        input_requirements = srs_json.get("input_requirements", [])
        output_requirements = srs_json.get("output_requirements", [])

        api_endpoints = interface_view.get("api_endpoints", [])
        request_models = interface_view.get("request_models", [])
        response_models = interface_view.get("response_models", [])

        if api_expectations and not api_endpoints:
            errors.append("SRS has API expectations but Architecture Plan interface_view.api_endpoints is empty.")

        if input_requirements and not request_models:
            errors.append("SRS has input requirements but Architecture Plan interface_view.request_models is empty.")

        if output_requirements and not response_models:
            errors.append("SRS has output requirements but Architecture Plan interface_view.response_models is empty.")

        expected_paths = [
            item.get("endpoint")
            for item in api_expectations
            if isinstance(item, dict) and item.get("endpoint")
        ]

        actual_paths = [
            item.get("endpoint")
            for item in api_endpoints
            if isinstance(item, dict) and item.get("endpoint")
        ]

        for path in expected_paths:
            if path not in actual_paths:
                errors.append(f"Architecture Plan interface_view missing API endpoint from SRS: {path}")

        return errors

    def _validate_data_coverage(
        self,
        srs_json: dict[str, Any],
        architecture_plan_json: dict[str, Any]
    ) -> list[str]:
        data_requirements = srs_json.get("data_requirements", [])

        if not data_requirements:
            return []

        data_view = architecture_plan_json.get("design_views", {}).get("data_view", {})
        data_entities = data_view.get("data_entities", [])

        if not data_entities:
            return ["SRS has data requirements but Architecture Plan data_view.data_entities is empty."]

        return []

    def _validate_quality_coverage(
        self,
        srs_json: dict[str, Any],
        architecture_plan_json: dict[str, Any]
    ) -> list[str]:
        nfrs = srs_json.get("non_functional_requirements", [])

        if not nfrs:
            return []

        quality_view = architecture_plan_json.get("design_views", {}).get("quality_attributes_view", {})
        quality_text = str(quality_view).strip()

        if not quality_text or quality_text == "{}":
            return ["SRS has NFRs but Architecture Plan quality_attributes_view is empty."]

        return []

    def _validate_coder_tasks(
        self,
        srs_json: dict[str, Any],
        architecture_plan_json: dict[str, Any]
    ) -> list[str]:
        tasks = architecture_plan_json.get("coder_implementation_tasks", [])
        fr_ids = self._collect_ids(srs_json.get("functional_requirements", []))

        if not isinstance(tasks, list) or not tasks:
            return ["Architecture Plan must include coder_implementation_tasks for the Coder Agent."]

        if not fr_ids:
            return []

        covered_ids = set()
        for task in tasks:
            if isinstance(task, dict):
                covered_ids.update(str(item) for item in task.get("related_requirements", []) or [])

        missing = [fr_id for fr_id in fr_ids if fr_id not in covered_ids]
        if missing:
            return [f"Coder implementation tasks missing Functional Requirement IDs: {missing}"]

        return []

    def _validate_implementation_plan(
        self,
        srs_json: dict[str, Any],
        architecture_plan_json: dict[str, Any]
    ) -> list[str]:
        """
        The implementation_plan is the Coder Agent's end-to-end blueprint --
        its presence and minimal substance are required, conditioned on what
        the SRS actually asks for (a feature with no API expectations does
        not need backend file entries, etc.).
        """

        implementation_plan = architecture_plan_json.get("implementation_plan")

        if not isinstance(implementation_plan, dict):
            return ["Architecture Plan missing required implementation_plan object."]

        errors = []

        backend = implementation_plan.get("backend")
        frontend = implementation_plan.get("frontend")

        if not isinstance(backend, dict):
            errors.append("implementation_plan.backend must be a JSON object.")
        if not isinstance(frontend, dict):
            errors.append("implementation_plan.frontend must be a JSON object.")

        if not implementation_plan.get("implementation_order"):
            errors.append("implementation_plan.implementation_order must be a non-empty list.")
        if not implementation_plan.get("constraints"):
            errors.append("implementation_plan.constraints must be a non-empty list.")

        if isinstance(backend, dict):
            if srs_json.get("api_expectations") and not backend.get("files"):
                errors.append(
                    "SRS has API expectations but implementation_plan.backend.files is empty."
                )
            if srs_json.get("data_requirements") and not backend.get("models"):
                errors.append(
                    "SRS has data requirements but implementation_plan.backend.models is empty."
                )

        if isinstance(frontend, dict):
            if srs_json.get("ui_expectations") and not frontend.get("pages"):
                errors.append(
                    "SRS has UI expectations but implementation_plan.frontend.pages is empty."
                )

        return errors

    def _validate_no_weak_sds_text(self, architecture_plan_json: dict[str, Any]) -> list[str]:
        text = str(architecture_plan_json).lower()

        weak_phrases = [
            "fallback sds",
            "software design specification",
            "sds must be reviewed",
            "approval-ready sds",
            "this sds",
            "software design specification",
            "requirement considered in fallback sds",
        ]

        return [
            f"Architecture Plan contains old SDS wording: {phrase}"
            for phrase in weak_phrases
            if phrase in text
        ]

    def _collect_ids(self, items: list[Any]) -> list[str]:
        ids = []

        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))

        return ids


# Backward-compatible aliases so older imports do not break immediately.
SDSValidationError = ArchitecturePlanValidationError
ArchitectureSDSValidator = ArchitecturePlanValidator
