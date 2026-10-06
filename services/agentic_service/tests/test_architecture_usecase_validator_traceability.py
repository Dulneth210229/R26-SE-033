"""
Unit tests for UseCaseQualityValidator's traceability check (app/agents/architecture_agent/
usecase_validator.py's _validate_traceability) and the new generalization-relationship endpoint-
type check (_validate_relationships). No LLM involved.

Sibling to test_architecture_usecase_validator.py (out-of-scope) and
test_architecture_usecase_validator_quality.py (name quality/fragmentation), which are left
untouched. Real, confirmed gap this locks in: traceability previously only checked
functional_requirements (FR) coverage, never acceptance_criteria (AC) or validation_rules (VR),
even though the prompt asks the LLM to cite all three.
"""

from app.agents.architecture_agent.usecase_validator import (
    UseCaseQualityValidator,
    UseCaseValidationError,
)


def _usecase_json(use_case_related_requirements: list[str]) -> dict:
    return {
        "system_boundary": "Test System",
        "diagram_title": "Test Diagram",
        "actors": [{"id": "ACT-001", "name": "Customer", "type": "primary", "stereotype": "human"}],
        "use_cases": [
            {
                "id": "UC-001",
                "name": "Search Tasks",
                "description": "A customer searches for tasks.",
                "category": "main",
                "related_requirements": use_case_related_requirements,
            }
        ],
        "relationships": [
            {"from": "ACT-001", "to": "UC-001", "type": "association", "related_requirements": []},
        ],
        "notes": [],
    }


class TestFullRequirementCoverageTraceability:
    def test_missing_functional_requirement_coverage_is_flagged(self):
        validator = UseCaseQualityValidator()
        srs_json = {"functional_requirements": [{"id": "FR-001", "description": "x"}]}
        usecase_json = _usecase_json(use_case_related_requirements=[])

        try:
            validator.validate(srs_json, {}, {}, usecase_json)
            assert False, "expected UseCaseValidationError for missing FR traceability"
        except UseCaseValidationError as error:
            assert "FR IDs" in str(error)
            assert "FR-001" in str(error)

    def test_missing_acceptance_criteria_coverage_is_flagged(self):
        validator = UseCaseQualityValidator()
        srs_json = {"acceptance_criteria": [{"id": "AC-001", "description": "x"}]}
        usecase_json = _usecase_json(use_case_related_requirements=[])

        try:
            validator.validate(srs_json, {}, {}, usecase_json)
            assert False, "expected UseCaseValidationError for missing AC traceability"
        except UseCaseValidationError as error:
            assert "AC IDs" in str(error)
            assert "AC-001" in str(error)

    def test_missing_validation_rule_coverage_is_flagged(self):
        validator = UseCaseQualityValidator()
        srs_json = {"validation_rules": [{"id": "VR-001", "description": "x"}]}
        usecase_json = _usecase_json(use_case_related_requirements=[])

        try:
            validator.validate(srs_json, {}, {}, usecase_json)
            assert False, "expected UseCaseValidationError for missing VR traceability"
        except UseCaseValidationError as error:
            assert "VR IDs" in str(error)
            assert "VR-001" in str(error)

    def test_fr_ac_vr_all_covered_does_not_raise(self):
        validator = UseCaseQualityValidator()
        srs_json = {
            "functional_requirements": [{"id": "FR-001", "description": "x"}],
            "acceptance_criteria": [{"id": "AC-001", "description": "x"}],
            "validation_rules": [{"id": "VR-001", "description": "x"}],
        }
        usecase_json = _usecase_json(use_case_related_requirements=["FR-001", "AC-001", "VR-001"])

        validator.validate(srs_json, {}, {}, usecase_json)

    def test_no_requirements_at_all_short_circuits_cleanly(self):
        validator = UseCaseQualityValidator()
        usecase_json = _usecase_json(use_case_related_requirements=[])

        validator.validate({}, {}, {}, usecase_json)


class TestGeneralizationEndpointTypeConsistency:
    def _usecase_json_with_relationships(self, relationships: list[dict]) -> dict:
        base = _usecase_json(use_case_related_requirements=[])
        base["use_cases"].append({
            "id": "UC-002", "name": "Pay By Card", "description": "x", "category": "included",
            "related_requirements": [],
        })
        base["actors"].append({"id": "ACT-002", "name": "Admin", "type": "secondary", "stereotype": "human"})
        base["relationships"] = relationships
        return base

    def test_use_case_to_use_case_generalization_is_valid(self):
        validator = UseCaseQualityValidator()
        usecase_json = self._usecase_json_with_relationships([
            {"from": "ACT-001", "to": "UC-001", "type": "association", "related_requirements": []},
            {"from": "UC-002", "to": "UC-001", "type": "generalization", "related_requirements": []},
        ])

        validator.validate({}, {}, {}, usecase_json)

    def test_actor_to_actor_generalization_is_valid(self):
        validator = UseCaseQualityValidator()
        usecase_json = self._usecase_json_with_relationships([
            {"from": "ACT-001", "to": "UC-001", "type": "association", "related_requirements": []},
            {"from": "ACT-002", "to": "ACT-001", "type": "generalization", "related_requirements": []},
        ])

        validator.validate({}, {}, {}, usecase_json)

    def test_mixed_actor_to_use_case_generalization_is_rejected(self):
        # A generalization must connect two use cases or two actors -- an actor generalizing a
        # use case (or vice versa) is not valid UML.
        validator = UseCaseQualityValidator()
        usecase_json = self._usecase_json_with_relationships([
            {"from": "ACT-001", "to": "UC-001", "type": "association", "related_requirements": []},
            {"from": "ACT-002", "to": "UC-002", "type": "generalization", "related_requirements": []},
        ])

        try:
            validator.validate({}, {}, {}, usecase_json)
            assert False, "expected UseCaseValidationError for a mixed-type generalization"
        except UseCaseValidationError as error:
            assert "not a mix" in str(error)
