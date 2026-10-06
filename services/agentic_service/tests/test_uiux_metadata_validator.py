"""
Unit tests for UIMetadataValidator -- hand-crafted inputs, no LLM involved.

Mirrors how architecture_agent's validators should be tested: confirm the
validator actually rejects incomplete coverage rather than silently passing.
"""

import pytest

from app.agents.uiux_agent.metadata_validator import (
    UIMetadataValidationError,
    UIMetadataValidator,
)

SRS = {
    "user_roles": ["Customer", "Admin"],
    "ui_expectations": [
        {"element": "Login Form", "expectation": "Must include email/password fields."},
        {"element": "Forgot Password Link", "expectation": "Must be visible near the login form."},
    ],
    "user_stories": [
        {"id": "US-001", "role": "Customer", "goal": "log in", "benefit": "access account"},
        {"id": "US-002", "role": "Customer", "goal": "reset password", "benefit": "regain access"},
    ],
    "acceptance_criteria": [
        {"id": "AC-001", "description": "user must be redirected to the dashboard on success"},
        {"id": "AC-002", "description": "system must display a generic error message on failure"},
        {"id": "AC-003", "description": "backend must log the failed attempt"},  # not UI-observable
    ],
}


def _complete_page(**overrides) -> dict:
    page = {
        "page_id": "login-page",
        "name": "Login Page",
        "route": "/login",
        "actors": ["Customer", "Admin"],
        "covers_requirements": ["US-001", "US-002", "AC-001", "AC-002"],
        "components": [
            {
                "name": "LoginForm",
                "reused_from_design_system": False,
                "covers_ui_expectations": ["Login Form", "Forgot Password Link"],
                "content_elements": ["email field label", "password field label", "forgot password link"],
            }
        ],
        "states": ["idle", "loading", "error", "success"],
        "new_design_tokens": [],
    }
    page.update(overrides)
    return page


@pytest.fixture
def validator():
    return UIMetadataValidator()


def test_complete_metadata_passes(validator):
    ui_metadata_json = {"pages": [_complete_page()], "notes": ""}
    validator.validate(SRS, ui_metadata_json)  # should not raise


def test_missing_actor_coverage_fails(validator):
    page = _complete_page(actors=["Customer"])  # Admin missing
    with pytest.raises(UIMetadataValidationError, match="Admin"):
        validator.validate(SRS, {"pages": [page]})


def test_missing_ui_expectation_coverage_fails(validator):
    page = _complete_page()
    page["components"][0]["covers_ui_expectations"] = ["Login Form"]  # Forgot Password Link missing
    with pytest.raises(UIMetadataValidationError, match="Forgot Password Link"):
        validator.validate(SRS, {"pages": [page]})


def test_missing_requirement_id_coverage_fails(validator):
    page = _complete_page(covers_requirements=["US-001"])  # US-002, AC-001, AC-002 missing
    with pytest.raises(UIMetadataValidationError, match="US-002"):
        validator.validate(SRS, {"pages": [page]})


def test_backend_only_acceptance_criterion_not_required(validator):
    # AC-003 ("backend must log...") has no UI-observable keywords, so it
    # must NOT be required in covers_requirements.
    page = _complete_page(covers_requirements=["US-001", "US-002", "AC-001", "AC-002"])
    validator.validate(SRS, {"pages": [page]})  # should not raise despite AC-003 being uncovered


def test_missing_required_states_fails(validator):
    page = _complete_page(states=["idle", "loading"])  # error, success missing
    with pytest.raises(UIMetadataValidationError, match="error"):
        validator.validate(SRS, {"pages": [page]})


def test_missing_page_id_or_name_fails(validator):
    page = _complete_page()
    del page["page_id"]
    with pytest.raises(UIMetadataValidationError, match="page_id"):
        validator.validate(SRS, {"pages": [page]})


def test_empty_pages_fails(validator):
    with pytest.raises(UIMetadataValidationError, match="non-empty list"):
        validator.validate(SRS, {"pages": []})


def test_empty_content_elements_fails(validator):
    page = _complete_page()
    page["components"][0]["content_elements"] = []
    with pytest.raises(UIMetadataValidationError, match="content_elements"):
        validator.validate(SRS, {"pages": [page]})


def test_missing_content_elements_key_fails(validator):
    page = _complete_page()
    del page["components"][0]["content_elements"]
    with pytest.raises(UIMetadataValidationError, match="content_elements"):
        validator.validate(SRS, {"pages": [page]})


def test_placeholder_content_elements_echo_fails(validator):
    # Real, confirmed bug (Sample E-commerce / Item Listing feature): the model echoed the
    # prompt's own example field-name text back verbatim instead of writing real content.
    page = _complete_page()
    page["components"][0]["content_elements"] = ["propName", "short description of the prop"]
    with pytest.raises(UIMetadataValidationError, match="placeholder"):
        validator.validate(SRS, {"pages": [page]})


def test_real_content_elements_pass(validator):
    page = _complete_page()
    page["components"][0]["content_elements"] = ["item name", "item price", "stock quantity"]
    validator.validate(SRS, {"pages": [page]})  # should not raise
