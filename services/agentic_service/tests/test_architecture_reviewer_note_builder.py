"""
Unit tests for build_human_approval_note -- a real, reported bug: the
reviewer-facing note used to concatenate a raw, ALL-CAPS-prefixed exception
message onto the fixed instruction sentence, producing one dense, technical
run-on paragraph instead of a clean, plain-English summary.
"""

from app.agents.architecture_agent.reviewer_note_builder import build_human_approval_note

BASE_NOTE = "This Architecture Plan must be reviewed and approved before the UI/UX Agent or Coder Agent starts."


def test_no_validation_error_returns_the_base_note_unchanged():
    assert build_human_approval_note(BASE_NOTE, None) == BASE_NOTE


def test_empty_validation_error_returns_the_base_note_unchanged():
    assert build_human_approval_note(BASE_NOTE, "") == BASE_NOTE


def test_single_issue_renders_as_a_clean_line_not_a_raw_dump():
    error = "Dto class 'LoginAndSignupRequest' only has placeholder attributes (['field']) -- add real, feature-specific fields."
    note = build_human_approval_note(BASE_NOTE, error)

    assert BASE_NOTE in note
    assert "AUTOMATIC VALIDATION FAILED" not in note
    assert error in note


def test_multiple_semicolon_joined_issues_render_one_per_line():
    error = (
        "Dto class 'LoginAndSignupRequest' only has placeholder attributes (['field']) -- add "
        "real, feature-specific fields.; Dto class 'LoginAndSignupSuccessResponse' has no "
        "attributes -- an anemic DTO/entity is not a useful class diagram element.; Dto class "
        "'LoginAndSignupErrorResponse' has no attributes -- an anemic DTO/entity is not a useful "
        "class diagram element."
    )
    note = build_human_approval_note(BASE_NOTE, error)

    assert "AUTOMATIC VALIDATION FAILED" not in note
    lines = [line for line in note.split("\n") if line.strip()]
    # base note + intro + 3 distinct issue lines, none of them semicolon-joined together
    issue_lines = [line for line in lines if line.startswith("Dto class")]
    assert len(issue_lines) == 3
    assert "LoginAndSignupRequest" in issue_lines[0]
    assert "LoginAndSignupSuccessResponse" in issue_lines[1]
    assert "LoginAndSignupErrorResponse" in issue_lines[2]


def test_context_is_folded_into_the_intro_sentence():
    note = build_human_approval_note(BASE_NOTE, "Some issue.", context="on the revised diagrams")
    assert "on the revised diagrams" in note
    assert "AUTOMATIC VALIDATION FAILED" not in note


def test_accepts_a_real_exception_instance_not_just_a_string():
    note = build_human_approval_note(BASE_NOTE, ValueError("Some issue."))
    assert "Some issue." in note
