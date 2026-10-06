"""
Unit tests for SequenceDiagramValidator's new quality checks added by the
Sequence Diagram rewrite (app/agents/architecture_agent/sequence_validator.py):
_validate_message_quality and the loop_start fragment-balance extension.
No LLM involved.

Sibling to tests/test_architecture_sequence_validator.py, which owns the
out-of-scope regression fixtures and is left untouched.
"""

from app.agents.architecture_agent.sequence_validator import (
    SequenceDiagramValidationError,
    SequenceDiagramValidator,
)


def _base_sequence_json(interactions: list[dict]) -> dict:
    return {
        "diagram_title": "Test Sequence",
        "participants": [
            {"id": "P1", "name": "Customer", "type": "actor"},
            {"id": "P2", "name": "API", "type": "boundary"},
            {"id": "P3", "name": "Service", "type": "control"},
        ],
        "interactions": interactions,
    }


class TestMessageQualityDetection:
    def test_duplicate_message_outside_loop_is_flagged(self):
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Process request", "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "P2", "to": "P3", "message": "process request", "related_requirements": ["FR-001"]},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        try:
            validator.validate(srs_json, sequence_json)
            assert False, "expected SequenceDiagramValidationError for a duplicate message"
        except SequenceDiagramValidationError as error:
            assert "Duplicate sequence message" in str(error)

    def test_repeated_message_inside_loop_is_not_flagged(self):
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "loop_start", "condition": "For each matching item"},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Fetch next item", "related_requirements": ["FR-001"]},
            {"kind": "end"},
            {"kind": "message", "from": "P3", "to": "P1", "message": "Return results", "related_requirements": ["FR-001"]},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        # A loop naturally repeats its body -- must not raise.
        validator.validate(srs_json, sequence_json)

    def test_nested_fragment_inside_loop_still_suppresses_duplicate_check(self):
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "loop_start", "condition": "For each item"},
            {"kind": "alt_start", "condition": "Item is valid"},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Process item", "related_requirements": ["FR-001"]},
            {"kind": "end"},
            {"kind": "end"},
            {"kind": "message", "from": "P3", "to": "P1", "message": "Return results", "related_requirements": ["FR-001"]},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        validator.validate(srs_json, sequence_json)


class TestLoopFragmentBalance:
    def test_loop_start_requires_matching_end(self):
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "loop_start", "condition": "For each item"},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Process item", "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "P3", "to": "P1", "message": "Return results", "related_requirements": ["FR-001"]},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        try:
            validator.validate(srs_json, sequence_json)
            assert False, "expected SequenceDiagramValidationError for an unclosed loop fragment"
        except SequenceDiagramValidationError as error:
            assert "unclosed combined fragment" in str(error)

    def test_balanced_loop_fragment_does_not_raise(self):
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "loop_start", "condition": "For each item"},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Process item", "related_requirements": ["FR-001"]},
            {"kind": "end"},
            {"kind": "message", "from": "P3", "to": "P1", "message": "Return results", "related_requirements": ["FR-001"]},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        validator.validate(srs_json, sequence_json)

    def test_par_start_requires_matching_end(self):
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "par_start", "condition": "Notify and audit concurrently"},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Send notification", "related_requirements": ["FR-001"]},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        try:
            validator.validate(srs_json, sequence_json)
            assert False, "expected SequenceDiagramValidationError for an unclosed par fragment"
        except SequenceDiagramValidationError as error:
            assert "unclosed combined fragment" in str(error)

    def test_balanced_par_and_break_fragments_do_not_raise(self):
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "break_start", "condition": "Validation fails"},
            {"kind": "message", "from": "P2", "to": "P1", "message": "Return validation error", "related_requirements": ["FR-001"]},
            {"kind": "end"},
            {"kind": "par_start", "condition": "Notify and audit concurrently"},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Send notification", "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "P2", "to": "P3", "message": "Write audit entry", "related_requirements": ["FR-001"]},
            {"kind": "end"},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        validator.validate(srs_json, sequence_json)

    def test_unrecognized_interaction_kind_is_still_rejected(self):
        # Confirms the validator's own allowlist (via FRAGMENT_OPENER_KINDS) stays strict --
        # a genuinely unrecognized kind must still be rejected, not silently accepted.
        validator = SequenceDiagramValidator()
        sequence_json = _base_sequence_json([
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "critical_start", "condition": "Something"},
        ])
        srs_json = {"functional_requirements": [{"id": "FR-001"}]}

        try:
            validator.validate(srs_json, sequence_json)
            assert False, "expected SequenceDiagramValidationError for an unrecognized kind"
        except SequenceDiagramValidationError as error:
            assert "Invalid sequence interaction kind" in str(error)
