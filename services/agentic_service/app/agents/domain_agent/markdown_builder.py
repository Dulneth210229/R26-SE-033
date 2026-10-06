"""
Domain Agent Markdown Builder.

Purpose:
Convert Domain Agent Enhanced SRS JSON + Domain Improvements JSON into
human-readable Markdown that makes the difference from the raw SRS
immediately visible: every domain-added item is tagged [DOMAIN ADDED],
every domain-enriched item is tagged [DOMAIN ENHANCED], and a trailing
"Domain Agent Enrichment Summary" section lists every change with its
rationale and citation in plain language.

Why this file exists:
- The LLM should generate only JSON to avoid parsing errors.
- Markdown is generated safely by backend Python code, mirroring
  RequirementSRSMarkdownBuilder's approach.
- This keeps Domain Agent formatting isolated from other agents.
"""

from typing import Any


class DomainEnhancedSRSMarkdownBuilder:
    """
    Converts Enhanced SRS JSON + Domain Improvements JSON into Markdown.
    """

    def build(self, enhanced_srs_json: dict[str, Any], domain_improvements_json: dict[str, Any]) -> str:
        # Plain list[str] sections (scope, constraints, risks, etc.) have no per-item dict to hang
        # an origin flag on, unlike the FR/NFR/AC/VR/US items _requirement_list already tags --
        # so domain-added entries in those sections are matched by exact text against
        # domain_improvements_json's own recorded additions (grouped by target_section) instead.
        # Real, reported gap this closes alongside the schema expansion itself: Domain Agent could
        # already add to only 6 sections; even data_requirements (the one plain-list section it
        # always had) never visually distinguished a domain-added entry from an original one in
        # this Markdown, unlike every ID-tagged section.
        plain_list_additions_by_section: dict[str, set[str]] = {}
        for addition in domain_improvements_json.get("additions", []):
            section = addition.get("target_section")
            description = addition.get("description")
            if section and description:
                plain_list_additions_by_section.setdefault(section, set()).add(description)

        def highlighted(section_key: str, items: list[str]) -> str:
            return self._simple_list(items, plain_list_additions_by_section.get(section_key))

        return f"""# Enhanced Software Requirements Specification: {enhanced_srs_json.get("feature_name", "Untitled Feature")}

This document is the Domain Agent's enrichment of the approved SRS. Items tagged
**[DOMAIN ADDED]** did not exist in the original SRS. Items tagged **[DOMAIN ENHANCED]** existed
before but had their description enriched with domain knowledge -- the original wording is shown
alongside the enhanced wording.

## 1. Project Information

- **Project ID:** {enhanced_srs_json.get("project_id", "N/A")}
- **Project Name:** {enhanced_srs_json.get("project_name", "N/A")}
- **Project Type:** {enhanced_srs_json.get("project_type", "N/A")}
- **Feature ID:** {enhanced_srs_json.get("feature_id", "N/A")}
- **Feature Name:** {enhanced_srs_json.get("feature_name", "N/A")}
- **Target Stack:** {enhanced_srs_json.get("target_stack", "Next.js")}
- **Preferred Architectural Style:** {enhanced_srs_json.get("architectural_style", "modular")}

---

## 2. Business Goal

{enhanced_srs_json.get("business_goal", "Not specified.")}

---

## 3. Scope

{highlighted("scope", enhanced_srs_json.get("scope", []))}

---

## 4. Out of Scope

{highlighted("out_of_scope", enhanced_srs_json.get("out_of_scope", []))}

---

## 5. User Roles

{highlighted("user_roles", enhanced_srs_json.get("user_roles", []))}

---

## 6. Functional Requirements

{self._requirement_list(enhanced_srs_json.get("functional_requirements", []))}

---

## 7. Non-Functional Requirements

{self._requirement_list(enhanced_srs_json.get("non_functional_requirements", []))}

---

## 8. User Stories

{self._user_story_list(enhanced_srs_json.get("user_stories", []))}

---

## 9. Acceptance Criteria

{self._requirement_list(enhanced_srs_json.get("acceptance_criteria", []))}

---

## 10. Input Requirements

{highlighted("input_requirements", enhanced_srs_json.get("input_requirements", []))}

---

## 11. Output Requirements

{highlighted("output_requirements", enhanced_srs_json.get("output_requirements", []))}

---

## 12. UI Expectations

{highlighted("ui_expectations", enhanced_srs_json.get("ui_expectations", []))}

---

## 13. API Expectations

{highlighted("api_expectations", enhanced_srs_json.get("api_expectations", []))}

---

## 14. Data Requirements

{highlighted("data_requirements", enhanced_srs_json.get("data_requirements", []))}

---

## 15. Validation Rules

{self._requirement_list(enhanced_srs_json.get("validation_rules", []))}

---

## 16. Constraints

{highlighted("constraints", enhanced_srs_json.get("constraints", []))}

---

## 17. Assumptions

{highlighted("assumptions", enhanced_srs_json.get("assumptions", []))}

---

## 18. Risks

{highlighted("risks", enhanced_srs_json.get("risks", []))}

---

## 19. Dependencies

{highlighted("dependencies", enhanced_srs_json.get("dependencies", []))}

---

## 20. Requirement Traceability Summary

{self._traceability_list(enhanced_srs_json.get("traceability", []))}

---

## 21. Domain Agent Enrichment Summary

{self._enrichment_summary(domain_improvements_json)}

---

## 22. Human Approval Note

This Enhanced SRS was generated by the Domain Agent using retrieval-augmented generation (RAG)
over the project's domain knowledge base.

A human reviewer must approve this artifact before it is passed to the Architecture Agent.
"""

    def _simple_list(self, items: list[Any], highlighted_texts: set[str] | None = None) -> str:
        if not items:
            return "- Not specified."

        highlighted_texts = highlighted_texts or set()
        return "\n".join(
            f"- {'**[DOMAIN ADDED]** ' if item in highlighted_texts else ''}{item}" for item in items
        )

    def _requirement_list(self, items: list[dict[str, Any]]) -> str:
        """
        Convert requirement dictionaries into Markdown bullets, tagging
        Domain Agent additions/enrichments inline.
        """
        if not items:
            return "- Not specified."

        lines = []

        for item in items:
            item_id = item.get("id", "N/A")
            description = item.get("description", "No description provided.")
            priority = item.get("priority")
            category = item.get("category")

            extra = ""

            if priority:
                extra = f" — Priority: {priority}"
            elif category:
                extra = f" — Category: {category}"

            tag = self._domain_tag(item)

            lines.append(f"- **{item_id}**{tag}: {description}{extra}")

            if item.get("modified_by_domain_agent") and item.get("original_description"):
                lines.append(f"  - *Original wording:* {item['original_description']}")

            citation = item.get("domain_citation")
            if citation:
                lines.append(
                    f"  - *Domain source:* {citation.get('source_document', 'N/A')} "
                    f"({citation.get('chunk_id', 'N/A')})"
                )

        return "\n".join(lines)

    def _domain_tag(self, item: dict[str, Any]) -> str:
        if item.get("origin") == "domain_agent":
            return " **[DOMAIN ADDED]**"

        if item.get("modified_by_domain_agent"):
            return " **[DOMAIN ENHANCED]**"

        return ""

    def _user_story_list(self, items: list[dict[str, Any]]) -> str:
        if not items:
            return "- Not specified."

        lines = []

        for item in items:
            story_id = item.get("id", "N/A")
            role = item.get("role", "user")
            goal = item.get("goal", "use the feature")
            benefit = item.get("benefit", "achieve the business goal")
            tag = self._domain_tag(item)

            lines.append(
                f"- **{story_id}**{tag}: As a **{role}**, "
                f"I want to **{goal}**, so that **{benefit}**."
            )

        return "\n".join(lines)

    def _traceability_list(self, items: list[dict[str, Any]]) -> str:
        if not items:
            return "- Not specified."

        lines = []

        for item in items:
            requirement_id = item.get("requirement_id", "N/A")
            related_criteria = item.get("related_acceptance_criteria", [])
            notes = item.get("notes", "")

            if isinstance(related_criteria, list):
                related_text = ", ".join(related_criteria)
            else:
                related_text = str(related_criteria)

            lines.append(
                f"- **{requirement_id}** → Acceptance Criteria: {related_text or 'N/A'}"
            )

            if notes:
                lines.append(f"  - Notes: {notes}")

        return "\n".join(lines)

    def _enrichment_summary(self, domain_improvements_json: dict[str, Any]) -> str:
        summary = domain_improvements_json.get("summary", "")
        additions = domain_improvements_json.get("additions", [])
        modifications = domain_improvements_json.get("modifications", [])
        no_changes_note = domain_improvements_json.get("no_changes_note")
        sources = domain_improvements_json.get("knowledge_sources_used", [])

        lines = []

        if summary:
            lines.append(summary)
            lines.append("")

        if no_changes_note:
            lines.append(f"> {no_changes_note}")
            lines.append("")

        if sources:
            lines.append("**Knowledge sources used:**")
            for source in sources:
                lines.append(
                    f"- {source.get('source_document', 'N/A')} "
                    f"({source.get('chunks_used', 0)} chunk(s) used)"
                )
            lines.append("")

        if additions:
            lines.append("**Additions:**")
            for addition in additions:
                lines.append(
                    f"- **{addition.get('new_id', 'N/A')}** ({addition.get('target_section', 'N/A')}): "
                    f"{addition.get('description', '')}"
                )
                lines.append(f"  - *Rationale:* {addition.get('rationale', 'N/A')}")
            lines.append("")

        if modifications:
            lines.append("**Modifications:**")
            for modification in modifications:
                lines.append(
                    f"- **{modification.get('id', 'N/A')}** ({modification.get('target_section', 'N/A')})"
                )
                lines.append(f"  - *Before:* {modification.get('original_description', 'N/A')}")
                lines.append(f"  - *After:* {modification.get('enhanced_description', 'N/A')}")
                lines.append(f"  - *Rationale:* {modification.get('rationale', 'N/A')}")
            lines.append("")

        if not additions and not modifications and not no_changes_note:
            lines.append("No domain enrichment was applied to this SRS.")

        return "\n".join(lines) if lines else "No domain enrichment was applied to this SRS."
