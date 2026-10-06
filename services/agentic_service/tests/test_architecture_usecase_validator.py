"""
Unit tests for UseCaseQualityValidator's out-of-scope check
(app/agents/architecture_agent/usecase_validator.py). No LLM involved.

Locks in a real bug fix: the original implementation flagged a diagram
element as "out of scope" whenever it shared just 2 stems with a forbidden
SRS out_of_scope phrase, regardless of how many stems that phrase had or
whether the actual distinguishing word was present at all. Since generic
words like "account"/"email"/"user"/"signup" are common to any signup-
related content, this false-positived on every real Architecture Agent run
for a Signup feature (three confirmed real cases below), making the whole
fallback path -- the last resort with no further recourse -- unusable.
"""

from app.agents.architecture_agent.usecase_validator import (
    UseCaseQualityValidator,
    UseCaseValidationError,
)


def _usecase_json(name: str, description: str) -> dict:
    return {
        "system_boundary": "Test System",
        "diagram_title": "Test Diagram",
        "actors": [{"id": "A1", "name": "Customer"}],
        "use_cases": [
            {
                "id": "UC1",
                "name": name,
                "description": description,
                "related_requirements": ["FR-001"],
            }
        ],
        "relationships": [{"from": "A1", "to": "UC1", "type": "association", "related_requirements": ["FR-001"]}],
        "notes": [],
    }


def _srs_json(out_of_scope_text: str) -> dict:
    return {
        "functional_requirements": [{"id": "FR-001", "description": "Do the thing."}],
        "out_of_scope": [out_of_scope_text],
    }


def test_real_false_positive_account_verification_no_longer_flagged():
    validator = UseCaseQualityValidator()
    srs_json = _srs_json("Account verification via email")
    usecase_json = _usecase_json(
        "Handle Error Message",
        "And Does Given an email that is already registered, the system displays a clear "
        "error message and does not create a duplicate account.",
    )

    # Should not raise -- this is real content from a real Signup feature run that was
    # incorrectly rejected before the fix (duplicate-email detection, not email verification).
    validator.validate(srs_json, {}, {}, usecase_json)


def test_real_false_positive_password_recovery_functionality_no_longer_flagged():
    validator = UseCaseQualityValidator()
    srs_json = _srs_json("Password recovery functionality")
    usecase_json = _usecase_json(
        "Register New User",
        "Given a new, unregistered email, valid password, and full name, the user is "
        "registered and redirected to the dashboard with a valid JWT.",
    )

    validator.validate(srs_json, {}, {}, usecase_json)


def test_real_false_positive_profile_customization_no_longer_flagged():
    validator = UseCaseQualityValidator()
    srs_json = _srs_json("User profile customization after signup")
    usecase_json = _usecase_json(
        "Signup",
        "Allow new users to create an account so they can access personalized shopping features.",
    )

    validator.validate(srs_json, {}, {}, usecase_json)


def test_genuine_out_of_scope_violation_is_still_caught():
    validator = UseCaseQualityValidator()
    srs_json = _srs_json("Account verification via email")
    usecase_json = _usecase_json(
        "Verify Account Email",
        "Given a signup request, the system sends an email verification link to confirm the account.",
    )

    try:
        validator.validate(srs_json, {}, {}, usecase_json)
        assert False, "expected UseCaseValidationError for a genuine out-of-scope violation"
    except UseCaseValidationError as error:
        assert "out-of-scope" in str(error)


def test_out_of_scope_item_with_no_meaningful_stems_is_ignored():
    validator = UseCaseQualityValidator()
    srs_json = _srs_json("N/A")
    usecase_json = _usecase_json("Do Something", "Some description.")

    validator.validate(srs_json, {}, {}, usecase_json)
