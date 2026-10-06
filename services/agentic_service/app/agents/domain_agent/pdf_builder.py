"""
Domain Agent Enhanced SRS PDF Builder.

Purpose:
Convert Enhanced SRS JSON + Domain Improvements JSON into a real, table-based
HTML document -- the same section structure as the Requirement Agent's own
SRS PDF (the Enhanced SRS is the same shape), reusing its shared table/list
helpers directly (no copy-pasted table-building code), plus a domain-specific
highlighting pass (a light green tint on a domain-added/enhanced row,
mirroring the frontend's own EnrichedItemList.jsx/EnrichedPlainList.jsx
convention) and a trailing "Domain Improvements" section.
"""

from __future__ import annotations

from typing import Any

from app.agents._shared.pdf_style import html_document_shell, signature_block_html
from app.agents.requirement_agent.pdf_builder import (
    _esc,
    _meta_table,
    _section,
    _smart_text_block,
    _text_block,
    _traceability_table,
)


def _domain_badge(item: dict[str, Any]) -> str:
    if item.get("origin") == "domain_agent":
        return '<span class="badge">Domain Added</span>'
    if item.get("modified_by_domain_agent"):
        return '<span class="badge">Domain Enhanced</span>'
    return ""


def _plain_list_highlighted(items: list[Any], highlighted_texts: set[str]) -> str:
    if not items:
        return '<p class="empty-note">Not specified.</p>'
    lis = []
    for item in items:
        if item in highlighted_texts:
            lis.append(
                f'<li><span class="badge">Domain Added</span> {_esc(item)}</li>'
            )
        else:
            lis.append(f"<li>{_esc(item)}</li>")
    return f'<ul class="plain-list">{"".join(lis)}</ul>'


def _requirement_table_domain(title_cols: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="empty-note">Not specified.</p>'
    rows = []
    for item in items:
        item_id = item.get("id", "N/A")
        description = item.get("description", "No description provided.")
        priority = item.get("priority")
        category = item.get("category")
        extra = priority or category or "—"
        badge = _domain_badge(item)
        rows.append(
            f"<tr><td>{_esc(item_id)}</td>"
            f"<td>{_esc(description)} {badge}</td>"
            f"<td>{_esc(extra)}</td></tr>"
        )
    return (
        '<table class="data-table"><thead><tr>'
        f"<th>ID</th><th>Description</th><th>{_esc(title_cols)}</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


def _user_story_cards_domain(items: list[dict[str, Any]]) -> str:
    if not items:
        return '<p class="empty-note">Not specified.</p>'
    cards = []
    for item in items:
        story_id = item.get("id", "N/A")
        role = item.get("role", "user")
        goal = item.get("goal", "use the feature")
        benefit = item.get("benefit", "achieve the business goal")
        badge = _domain_badge(item)
        card_class = "card domain-added" if item.get("origin") == "domain_agent" else "card"
        cards.append(
            f'<div class="{card_class}">'
            f'<div class="card-title">{_esc(story_id)} {badge}</div>'
            f"As a <strong>{_esc(role)}</strong>, I want to <strong>{_esc(goal)}</strong>, "
            f"so that <strong>{_esc(benefit)}</strong>."
            "</div>"
        )
    return "".join(cards)


def _enrichment_summary_html(domain_improvements_json: dict[str, Any] | None) -> str:
    if not domain_improvements_json:
        return '<p class="empty-note">No domain enrichment was applied to this SRS.</p>'

    summary = domain_improvements_json.get("summary", "")
    additions = domain_improvements_json.get("additions", [])
    modifications = domain_improvements_json.get("modifications", [])
    no_changes_note = domain_improvements_json.get("no_changes_note")
    sources = domain_improvements_json.get("knowledge_sources_used", [])

    parts = []
    if summary:
        parts.append(_smart_text_block(summary))
    if no_changes_note:
        parts.append(f'<p class="empty-note">{_esc(no_changes_note)}</p>')

    if sources:
        rows = "".join(
            f"<li>{_esc(source.get('source_document', 'N/A'))} "
            f"({_esc(source.get('chunks_used', 0))} chunk(s) used)</li>"
            for source in sources
        )
        parts.append(f'<h3 class="subsection-title">Knowledge Sources Used</h3><ul class="plain-list">{rows}</ul>')

    if additions:
        cards = []
        for addition in additions:
            cards.append(
                '<div class="card domain-added">'
                f'<div class="card-title">{_esc(addition.get("new_id", "N/A"))} '
                f'({_esc(addition.get("target_section", "N/A"))})</div>'
                f'{_esc(addition.get("description", ""))}<br/>'
                f'<em>Rationale: {_esc(addition.get("rationale", "N/A"))}</em>'
                "</div>"
            )
        parts.append(f'<h3 class="subsection-title">Additions</h3>{"".join(cards)}')

    if modifications:
        cards = []
        for modification in modifications:
            cards.append(
                '<div class="card domain-added">'
                f'<div class="card-title">{_esc(modification.get("id", "N/A"))} '
                f'({_esc(modification.get("target_section", "N/A"))})</div>'
                f'<em>Before:</em> {_esc(modification.get("original_description", "N/A"))}<br/>'
                f'<em>After:</em> {_esc(modification.get("enhanced_description", "N/A"))}<br/>'
                f'<em>Rationale:</em> {_esc(modification.get("rationale", "N/A"))}'
                "</div>"
            )
        parts.append(f'<h3 class="subsection-title">Modifications</h3>{"".join(cards)}')

    if not additions and not modifications and not no_changes_note:
        parts.append('<p class="empty-note">No domain enrichment was applied to this SRS.</p>')

    return "".join(parts)


def build_enhanced_srs_html(
    enhanced_srs_json: dict[str, Any], domain_improvements_json: dict[str, Any] | None = None
) -> str:
    """
    Build a complete, self-contained Enhanced SRS HTML document.
    """
    plain_list_additions_by_section: dict[str, set[str]] = {}
    for addition in (domain_improvements_json or {}).get("additions", []):
        section = addition.get("target_section")
        description = addition.get("description")
        if section and description:
            plain_list_additions_by_section.setdefault(section, set()).add(description)

    def highlighted(section_key: str, items: list[str]) -> str:
        return _plain_list_highlighted(items, plain_list_additions_by_section.get(section_key, set()))

    feature_name = enhanced_srs_json.get("feature_name", "Untitled Feature")

    meta_rows = [
        ("Project ID", enhanced_srs_json.get("project_id", "N/A")),
        ("Project Name", enhanced_srs_json.get("project_name", "N/A")),
        ("Project Type", enhanced_srs_json.get("project_type", "N/A")),
        ("Feature ID", enhanced_srs_json.get("feature_id", "N/A")),
        ("Feature Name", enhanced_srs_json.get("feature_name", "N/A")),
        ("Target Stack", enhanced_srs_json.get("target_stack", "Next.js")),
        ("Preferred Architectural Style", enhanced_srs_json.get("architectural_style", "modular")),
    ]

    sections = [
        _section(1, "Project Information", _meta_table(meta_rows)),
        _section(2, "Business Goal", _smart_text_block(enhanced_srs_json.get("business_goal"))),
        _section(3, "Scope", highlighted("scope", enhanced_srs_json.get("scope", []))),
        _section(4, "Out of Scope", highlighted("out_of_scope", enhanced_srs_json.get("out_of_scope", []))),
        _section(5, "User Roles", highlighted("user_roles", enhanced_srs_json.get("user_roles", []))),
        _section(
            6,
            "Functional Requirements",
            _requirement_table_domain("Priority", enhanced_srs_json.get("functional_requirements", [])),
        ),
        _section(
            7,
            "Non-Functional Requirements",
            _requirement_table_domain(
                "Priority/Category", enhanced_srs_json.get("non_functional_requirements", [])
            ),
        ),
        _section(8, "User Stories", _user_story_cards_domain(enhanced_srs_json.get("user_stories", []))),
        _section(
            9,
            "Acceptance Criteria",
            _requirement_table_domain("Priority/Category", enhanced_srs_json.get("acceptance_criteria", [])),
        ),
        _section(
            10, "Input Requirements", highlighted("input_requirements", enhanced_srs_json.get("input_requirements", []))
        ),
        _section(
            11,
            "Output Requirements",
            highlighted("output_requirements", enhanced_srs_json.get("output_requirements", [])),
        ),
        _section(12, "UI Expectations", highlighted("ui_expectations", enhanced_srs_json.get("ui_expectations", []))),
        _section(
            13, "API Expectations", highlighted("api_expectations", enhanced_srs_json.get("api_expectations", []))
        ),
        _section(14, "Data Requirements", highlighted("data_requirements", enhanced_srs_json.get("data_requirements", []))),
        _section(
            15,
            "Validation Rules",
            _requirement_table_domain("Priority/Category", enhanced_srs_json.get("validation_rules", [])),
        ),
        _section(16, "Constraints", highlighted("constraints", enhanced_srs_json.get("constraints", []))),
        _section(17, "Assumptions", highlighted("assumptions", enhanced_srs_json.get("assumptions", []))),
        _section(18, "Risks", highlighted("risks", enhanced_srs_json.get("risks", []))),
        _section(19, "Dependencies", highlighted("dependencies", enhanced_srs_json.get("dependencies", []))),
        _section(
            20,
            "Requirement Traceability Summary",
            _traceability_table(enhanced_srs_json.get("traceability", [])),
        ),
        _section(21, "Domain Agent Enrichment Summary", _enrichment_summary_html(domain_improvements_json)),
        _section(
            22,
            "Human Approval Note",
            _text_block(
                "This Enhanced SRS was generated by the Domain Agent using retrieval-augmented "
                "generation (RAG) over the project's domain knowledge base. A human reviewer "
                "must approve this artifact before it is passed to the Architecture Agent."
            ),
        ),
        _section(23, "Document Sign-Off", signature_block_html()),
    ]

    body_html = "".join(sections)
    body_html += (
        '<div class="doc-footer">Generated by AutoForge -- Domain Agent. '
        "This document is a formatted export of the underlying Enhanced SRS artifact.</div>"
    )

    return html_document_shell(
        title=f"Enhanced Software Requirements Specification: {feature_name}",
        subtitle="Domain Agent -- Enhanced SRS with Domain Knowledge Enrichment",
        body_html=body_html,
    )
