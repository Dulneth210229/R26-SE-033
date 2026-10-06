"""
Architecture Agent Reviewer Note Builder.

Purpose:
Turn a raw validation-failure exception into a clean, plain-English addition
to human_approval_note -- never a dense, ALL-CAPS, single-paragraph dump of
the raw exception text.
"""

from __future__ import annotations


def build_human_approval_note(
    base_note: str,
    validation_error: Exception | str | None = None,
    context: str = "",
) -> str:
    """
    Compose the reviewer-facing approval note.

    With no validation_error, returns base_note unchanged. Otherwise, every
    validator in this agent (class_validator, usecase_validator,
    sequence_validator, sds_validator) raises via the same
    `"; ".join(errors)` convention, so splitting on "; " reliably recovers
    the individual issues -- rendered as one issue per line (rather than one
    dense run-on sentence) so the frontend's whitespace-pre-line note box and
    the PDF export's _smart_text_block (which auto-bullets 2+ line text) both
    turn this into a real, scannable list.
    """

    base_note = (base_note or "").strip()

    if validation_error is None:
        return base_note

    error_text = str(validation_error).strip()
    if not error_text:
        return base_note

    issues = [issue.strip() for issue in error_text.split("; ") if issue.strip()]
    if not issues:
        return base_note

    intro = "Automatic checks found a few issues to look at before approving"
    if context:
        intro = f"{intro} {context}"

    body = "\n".join(issues)
    return f"{base_note}\n\n{intro}:\n\n{body}".strip()
