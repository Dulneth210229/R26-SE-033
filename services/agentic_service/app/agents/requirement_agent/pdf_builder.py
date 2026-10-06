"""
Requirement Agent SRS PDF Builder.

Purpose:
Convert SRS JSON into a real, table-based HTML document (mirroring the
frontend's own SrsDocumentViewer.jsx), rendered to PDF by app.services.
pdf_service. This is a NEW template, not a reuse of
RequirementSRSMarkdownBuilder's bulleted Markdown output -- the latter renders
prose bullets, not the tables a "good" SRS document is expected to have.
"""

from __future__ import annotations

import html
import re
from typing import Any

from app.agents._shared.pdf_style import html_document_shell, signature_block_html

# A cheap, best-effort sentence-boundary split (same "good enough heuristic" convention as e.g.
# coder_agent/ui_expectations_checker.py's own word-overlap check) -- good enough to decide
# "does this prose field have multiple distinct points worth bulleting," never used for anything
# that needs to be exact.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")

# Abbreviations that would otherwise falsely look like a sentence boundary ("e.g. Google login"
# has a capital letter right after a period that isn't really the end of a sentence).
_ABBREVIATION_WORDS = {
    "e.g.", "i.e.", "etc.", "vs.", "approx.", "dr.", "mr.", "mrs.", "no.", "fig.", "eq.",
}


def _esc(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _meta_table(rows: list[tuple[str, Any]]) -> str:
    cells = "".join(
        f'<tr><td class="meta-label">{_esc(label)}</td><td>{_esc(value)}</td></tr>'
        for label, value in rows
    )
    return f'<table class="meta-table">{cells}</table>'


def _plain_list(items: list[Any]) -> str:
    if not items:
        return '<p class="empty-note">Not specified.</p>'
    lis = "".join(f"<li>{_esc(item)}</li>" for item in items)
    return f'<ul class="plain-list">{lis}</ul>'


def _text_block(value: Any) -> str:
    return f'<p class="section-body">{_esc(value) or "Not specified."}</p>'


def _split_sentences(text: str) -> list[str]:
    """
    Split free text into distinct points: an explicit newline-separated
    structure first (some LLM output already writes one point per line), else
    a sentence-boundary regex, with an abbreviation guard so "e.g. Google
    login" doesn't get treated as two sentences.
    """
    if "\n" in text.strip():
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        if len(lines) >= 2:
            return lines

    raw_parts = _SENTENCE_BOUNDARY.split(text)
    parts: list[str] = []
    for part in raw_parts:
        if parts:
            last_word = parts[-1].rsplit(" ", 1)[-1].lower()
            if last_word in _ABBREVIATION_WORDS:
                parts[-1] = f"{parts[-1]} {part}"
                continue
        parts.append(part)
    return [p.strip() for p in parts if p.strip()]


def _smart_text_block(value: Any) -> str:
    """
    Render free text as a plain paragraph (today's exact `_text_block`
    behavior) unless it genuinely contains 2+ distinct points, in which case
    it renders as a real bullet list instead -- "bullet if needed," never a
    pointless one-item bullet for a short single sentence.
    """
    text = "" if value is None else str(value).strip()
    if not text:
        return '<p class="section-body">Not specified.</p>'

    sentences = _split_sentences(text)
    if len(sentences) < 2:
        return f'<p class="section-body">{_esc(text)}</p>'

    items = "".join(f"<li>{_esc(sentence)}</li>" for sentence in sentences)
    return f'<ul class="plain-list">{items}</ul>'


def _requirement_table(title_cols: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="empty-note">Not specified.</p>'
    rows = []
    for item in items:
        item_id = item.get("id", "N/A")
        description = item.get("description", "No description provided.")
        priority = item.get("priority")
        category = item.get("category")
        extra = priority or category or "—"
        rows.append(
            f"<tr><td>{_esc(item_id)}</td><td>{_esc(description)}</td>"
            f"<td>{_esc(extra)}</td></tr>"
        )
    return (
        '<table class="data-table"><thead><tr>'
        f"<th>ID</th><th>Description</th><th>{_esc(title_cols)}</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _user_story_cards(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="empty-note">Not specified.</p>'
    cards = []
    for item in items:
        story_id = item.get("id", "N/A")
        role = item.get("role", "user")
        goal = item.get("goal", "use the feature")
        benefit = item.get("benefit", "achieve the business goal")
        cards.append(
            '<div class="card">'
            f'<div class="card-title">{_esc(story_id)}</div>'
            f"As a <strong>{_esc(role)}</strong>, I want to <strong>{_esc(goal)}</strong>, "
            f"so that <strong>{_esc(benefit)}</strong>."
            "</div>"
        )
    return "".join(cards)


def _traceability_table(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="empty-note">Not specified.</p>'
    rows = []
    for item in items:
        requirement_id = item.get("requirement_id", "N/A")
        related_criteria = item.get("related_acceptance_criteria", [])
        notes = item.get("notes", "")
        related_text = (
            ", ".join(related_criteria) if isinstance(related_criteria, list) else str(related_criteria)
        )
        rows.append(
            f"<tr><td>{_esc(requirement_id)}</td><td>{_esc(related_text or 'N/A')}</td>"
            f"<td>{_esc(notes or '—')}</td></tr>"
        )
    return (
        '<table class="data-table"><thead><tr>'
        "<th>Requirement ID</th><th>Acceptance Criteria</th><th>Notes</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _section(number: int, title: str, body_html: str) -> str:
    return (
        f'<section class="doc-section"><h2 class="section-title">{number}. {_esc(title)}</h2>'
        f"{body_html}</section>"
    )


def build_srs_html(srs_json: dict[str, Any]) -> str:
    """
    Build a complete, self-contained SRS HTML document from SRS JSON.
    """
    feature_name = srs_json.get("feature_name", "Untitled Feature")

    meta_rows = [
        ("Project ID", srs_json.get("project_id", "N/A")),
        ("Project Name", srs_json.get("project_name", "N/A")),
        ("Project Type", srs_json.get("project_type", "N/A")),
        ("Feature ID", srs_json.get("feature_id", "N/A")),
        ("Feature Name", srs_json.get("feature_name", "N/A")),
        ("Target Stack", srs_json.get("target_stack", "Next.js")),
        ("Preferred Architectural Style", srs_json.get("architectural_style", "modular")),
    ]

    sections = [
        _section(1, "Project Information", _meta_table(meta_rows)),
        _section(2, "Business Goal", _smart_text_block(srs_json.get("business_goal"))),
        _section(3, "Scope", _plain_list(srs_json.get("scope", []))),
        _section(4, "Out of Scope", _plain_list(srs_json.get("out_of_scope", []))),
        _section(5, "User Roles", _plain_list(srs_json.get("user_roles", []))),
        _section(
            6,
            "Functional Requirements",
            _requirement_table("Priority", srs_json.get("functional_requirements", [])),
        ),
        _section(
            7,
            "Non-Functional Requirements",
            _requirement_table("Priority/Category", srs_json.get("non_functional_requirements", [])),
        ),
        _section(8, "User Stories", _user_story_cards(srs_json.get("user_stories", []))),
        _section(
            9,
            "Acceptance Criteria",
            _requirement_table("Priority/Category", srs_json.get("acceptance_criteria", [])),
        ),
        _section(10, "Input Requirements", _plain_list(srs_json.get("input_requirements", []))),
        _section(11, "Output Requirements", _plain_list(srs_json.get("output_requirements", []))),
        _section(12, "UI Expectations", _plain_list(srs_json.get("ui_expectations", []))),
        _section(13, "API Expectations", _plain_list(srs_json.get("api_expectations", []))),
        _section(14, "Data Requirements", _plain_list(srs_json.get("data_requirements", []))),
        _section(
            15,
            "Validation Rules",
            _requirement_table("Priority/Category", srs_json.get("validation_rules", [])),
        ),
        _section(16, "Constraints", _plain_list(srs_json.get("constraints", []))),
        _section(17, "Assumptions", _plain_list(srs_json.get("assumptions", []))),
        _section(18, "Risks", _plain_list(srs_json.get("risks", []))),
        _section(19, "Dependencies", _plain_list(srs_json.get("dependencies", []))),
        _section(
            20,
            "Requirement Traceability Summary",
            _traceability_table(srs_json.get("traceability", [])),
        ),
        _section(
            21,
            "Human Approval Note",
            _text_block(
                "This SRS was generated by the Requirement Agent. A human reviewer must "
                "approve this artifact before it is passed to the Domain Agent."
            ),
        ),
        _section(22, "Document Sign-Off", signature_block_html()),
    ]

    body_html = "".join(sections)
    body_html += (
        '<div class="doc-footer">Generated by AutoForge -- Requirement Agent. '
        "This document is a formatted export of the underlying SRS artifact.</div>"
    )

    return html_document_shell(
        title=f"Software Requirements Specification: {feature_name}",
        subtitle="Requirement Agent -- Software Requirements Specification (SRS)",
        body_html=body_html,
    )
