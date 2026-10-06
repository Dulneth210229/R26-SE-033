"""
Unit tests for SequenceDiagramValidator's out-of-scope check
(app/agents/architecture_agent/sequence_validator.py). No LLM involved.

Same fix as usecase_validator.py (see test_architecture_usecase_validator.py
for the full rationale): require ALL of a forbidden phrase's meaningful
stems to be present in a message, not just any 2, so generic shared domain
vocabulary (account/email/user/signup) stops false-positiving.
"""

from app.agents.architecture_agent.sequence_validator import (
    SequenceDiagramValidationError,
    SequenceDiagramValidator,
)


def _sequence_json(message_text: str) -> dict:
    return {
        "diagram_title": "Test Sequence",
        "participants": [
            {"id": "P1", "name": "Customer", "type": "actor"},
            {"id": "P2", "name": "API", "type": "boundary"},
        ],
        "interactions": [
            {"kind": "message", "from": "P1", "to": "P2", "message": "Submit request", "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "P2", "to": "P1", "message": message_text, "related_requirements": ["FR-001"]},
            {"kind": "message", "from": "P2", "to": "P1", "message": "Return response", "related_requirements": ["FR-001"]},
        ],
    }


def _srs_json(out_of_scope_text: str) -> dict:
    return {
        "functional_requirements": [{"id": "FR-001", "description": "Do the thing."}],
        "out_of_scope": [out_of_scope_text],
    }


def test_real_false_positive_account_verification_no_longer_flagged():
    validator = SequenceDiagramValidator()
    srs_json = _srs_json("Account verification via email")
    sequence_json = _sequence_json(
        "Display a clear error message and do not create a duplicate account for an already-registered email"
    )

    validator.validate(srs_json, sequence_json)


def test_real_false_positive_profile_customization_no_longer_flagged():
    validator = SequenceDiagramValidator()
    srs_json = _srs_json("User profile customization after signup")
    sequence_json = _sequence_json("Create a new account for the signed-up user")

    validator.validate(srs_json, sequence_json)


def test_genuine_out_of_scope_violation_is_still_caught():
    validator = SequenceDiagramValidator()
    srs_json = _srs_json("Account verification via email")
    sequence_json = _sequence_json("Send an email verification link to confirm the account")

    try:
        validator.validate(srs_json, sequence_json)
        assert False, "expected SequenceDiagramValidationError for a genuine out-of-scope violation"
    except SequenceDiagramValidationError as error:
        assert "out-of-scope" in str(error)
