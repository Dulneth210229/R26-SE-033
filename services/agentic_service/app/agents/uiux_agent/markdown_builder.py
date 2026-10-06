"""
UI/UX Agent Markdown builder.

Purpose:
Convert ui_metadata_json (+ the integration manifest) into a human-readable
ui_design_markdown summary for the approval reviewer. Deterministic -- no LLM
involved, mirroring architecture_agent/markdown_builder.py's shape.
"""

from __future__ import annotations

from typing import Any


class UIUXMarkdownBuilder:
    """
    Converts ui_metadata_json into ui_design_markdown.
    """

    def build(
        self,
        feature_name: str,
        ui_metadata_json: dict[str, Any],
        integration_manifest_json: dict[str, Any],
    ) -> str:
        pages = ui_metadata_json.get("pages", [])

        sections = [
            f"# UI/UX Design: {feature_name}",
            "",
            "> Review the attached page screenshots alongside this summary. "
            "The screenshots show the literal generated components -- there is no "
            "later regeneration step that could introduce drift from what you approve here.",
            "",
            "---",
            "",
        ]

        for page in pages:
            sections.append(self._page_section(page))

        new_components = self._collect_new_components(pages)
        new_tokens = self._collect_new_tokens(pages)

        sections.append("## Design System Impact")
        sections.append("")
        sections.append("### New components introduced")
        sections.append(self._simple_list(new_components) if new_components else "None -- fully reused existing components.")
        sections.append("")
        sections.append("### New design tokens introduced")
        sections.append(self._token_list(new_tokens) if new_tokens else "None -- fully reused the existing design system.")
        sections.append("")

        notes = ui_metadata_json.get("notes")
        if notes:
            sections.extend(["---", "", "## Notes", "", notes, ""])

        return "\n".join(sections)

    def _page_section(self, page: dict[str, Any]) -> str:
        components = page.get("components", []) or []

        lines = [
            f"## Page: {page.get('name', 'Untitled Page')}",
            "",
            f"- **Route:** `{page.get('route', 'n/a')}`",
            f"- **Actors:** {', '.join(page.get('actors', [])) or 'none'}",
            f"- **Covers requirements:** {', '.join(page.get('covers_requirements', [])) or 'none'}",
            f"- **States:** {', '.join(page.get('states', [])) or 'none'}",
            "",
            "### Components",
            "",
        ]

        for component in components:
            reused = component.get("reused_from_design_system", False)
            tag = "reused" if reused else "new"
            lines.append(f"- **{component.get('name')}** ({tag})")
            covers = component.get("covers_ui_expectations", [])
            if covers:
                lines.append(f"  - Covers UI expectations: {', '.join(covers)}")
            if not reused and component.get("new_component_justification"):
                lines.append(f"  - Why new: {component['new_component_justification']}")

        lines.append("")
        lines.append("---")
        lines.append("")

        return "\n".join(lines)

    def _collect_new_components(self, pages: list[dict[str, Any]]) -> list[str]:
        names = []
        for page in pages:
            for component in page.get("components", []) or []:
                if not component.get("reused_from_design_system", False):
                    names.append(component.get("name"))
        return names

    def _collect_new_tokens(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tokens = []
        for page in pages:
            tokens.extend(page.get("new_design_tokens", []) or [])
        return tokens

    def _simple_list(self, items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    def _token_list(self, tokens: list[dict[str, Any]]) -> str:
        return "\n".join(
            f"- `{token.get('token')}`: {token.get('value', 'n/a')} -- {token.get('justification', '')}"
            for token in tokens
        )


uiux_markdown_builder = UIUXMarkdownBuilder()
