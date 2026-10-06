"""
UI/UX Agent component generator.

Purpose:
- Generate one static HTML + Tailwind CSS fragment at a time, scoped per-component rather than
  one giant call for the whole feature -- smaller, more reliable generations, and a single broken
  component can be retried without regenerating everything else (per the build plan).

Output format: plain HTML, not React/JSX -- a single self-contained fragment with realistic,
fully-populated example content baked directly into the markup. There is no more mock_props/props
concept: content lives directly in the markup, so there is nothing left to select a wrong render
state from (this is the structural fix for a real, confirmed bug -- a page previously rendered
"Unknown state."/"No data available" because the LLM-authored JSX only handled 3 of 4 declared
states and the preview picked the unhandled one; static HTML has no state branches to fall into).

Output format is still a delimited text marker, not JSON: embedding a multi-line HTML code block
inside a JSON string is a common source of escaping failures with LLMs (unescaped newlines/
quotes). A plain text marker avoids that failure mode entirely -- simpler than before, since there
is no longer a second JSON payload (mock_props) to parse alongside the code.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.uiux_agent.prompt import (
    HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT,
    build_component_format_repair_prompt,
    build_component_generator_user_prompt,
    build_component_quality_repair_prompt,
)
from app.core.enums import AgentName
from app.services.llm_provider_service import llm_provider_service

HTML_CODE_MARKER = "---HTML_CODE---"

# Real, confirmed failure mode (Sample E-commerce / Item Listing feature): a generated fragment
# rendering nothing but a generic "no data"/"unknown state" message instead of real content.
# Checked case-insensitively against the fragment's rendered text content.
PLACEHOLDER_CONTENT_PHRASES = [
    "no data available",
    "unknown state",
    "loading...",
    "error occurred",
    "coming soon",
    "lorem ipsum",
    "to be implemented",
    "todo",
    "placeholder",
]


class ComponentGenerationError(Exception):
    """Raised when a component could not be generated in the required format."""


class UIUXComponentGenerator:
    """
    Generates one component's HTML fragment source.
    """

    async def generate(
        self,
        project: dict,
        feature: dict,
        page_metadata: dict,
        component_metadata: dict,
        data_entities: list,
        design_system_json: dict,
        ui_preferences: dict,
        human_comment: str | None,
        color_theme: str = "indigo",
    ) -> tuple[dict[str, Any], str]:
        """
        Returns ({"html_code": str}, raw_llm_output).

        color_theme: the ONE Tailwind color family chosen once per feature (ui_metadata_json's
        own "color_theme" field, see agent.py) -- threaded through so every component on every
        page of this feature agrees on the same accent color, rather than each independent LLM
        call picking its own.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)

        prompt = build_component_generator_user_prompt(
            project=project,
            feature=feature,
            page_metadata=page_metadata,
            component_metadata=component_metadata,
            data_entities=data_entities,
            design_system_json=design_system_json,
            ui_preferences=ui_preferences,
            human_comment=human_comment,
            color_theme=color_theme,
        )

        raw_output = await provider.invoke_agent(
            [
                {"role": "system", "content": HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        try:
            return self._parse(raw_output), raw_output
        except ValueError:
            pass

        repaired_output = await provider.invoke_agent(
            [
                {"role": "system", "content": HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT},
                {"role": "user", "content": build_component_format_repair_prompt(raw_output)},
            ]
        )

        try:
            return self._parse(repaired_output), repaired_output
        except ValueError as error:
            component_name = component_metadata.get("name", "unknown")
            raise ComponentGenerationError(
                f"Component '{component_name}' could not be generated in the required "
                f"format after one repair attempt: {error}"
            ) from error

    async def repair(self, html_code: str, issue_description: str) -> tuple[dict[str, Any], str]:
        """
        One targeted repair attempt for a fragment that parsed fine but has a real problem --
        either it crashed during the actual Playwright preview render, or it failed the
        content-quality gate (empty/placeholder content instead of a real, populated view).
        Distinct from generate()'s own format-only repair, which never sees either of those.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)
        repair_prompt = build_component_quality_repair_prompt(html_code, issue_description)

        repaired_output = await provider.invoke_agent(
            [
                {"role": "system", "content": HTML_COMPONENT_GENERATOR_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ]
        )

        return self._parse(repaired_output), repaired_output

    def detect_placeholder_content(self, html_code: str) -> str | None:
        """
        Cheap, deterministic quality gate: returns a human-readable violation description if the
        fragment is empty/whitespace-only or contains an obvious generic-placeholder phrase
        instead of real content, else None. This is what catches the real bug class at the
        source, before a human ever sees a broken preview.

        Checks only the fragment's rendered/visible TEXT (see _visible_text), never the raw
        markup -- a real, confirmed false positive this fixes: a bare "placeholder" phrase
        previously matched against the WHOLE lowered HTML string, so any legitimate
        `<input placeholder="Search...">` attribute (exactly what a real search/filter component
        needs) always tripped this gate and made the component un-generatable, exhausting every
        repair attempt and crashing the whole run even though the fragment was correct.
        """

        stripped = html_code.strip()
        if not stripped:
            return "The fragment is empty."

        visible_text = self._visible_text(stripped)
        for phrase in PLACEHOLDER_CONTENT_PHRASES:
            if phrase in visible_text:
                return (
                    f"The fragment contains the placeholder/generic phrase {phrase!r} instead of "
                    "real, populated example content."
                )

        return None

    def _visible_text(self, html_code: str) -> str:
        """
        Best-effort extraction of a fragment's rendered/visible text -- strips every tag
        (including its attributes, e.g. `placeholder="..."`, `class="..."`) so the
        content-quality check above only ever sees what a human would actually see on screen,
        never markup. Not a full HTML parser -- a regex tag-strip is sufficient here since this
        is a quality heuristic, not a correctness-critical parse.
        """

        without_tags = re.sub(r"<[^>]*>", " ", html_code)
        return re.sub(r"\s+", " ", without_tags).strip().lower()

    def _parse(self, text: str) -> dict[str, Any]:
        if HTML_CODE_MARKER not in text:
            raise ValueError(f"Output missing required marker {HTML_CODE_MARKER}.")

        html_section = text.split(HTML_CODE_MARKER, 1)[1].strip()

        html_section = re.sub(r"^```(?:html)?\s*", "", html_section, flags=re.IGNORECASE)
        html_section = re.sub(r"\s*```$", "", html_section)
        html_section = html_section.strip()

        if not html_section:
            raise ValueError("HTML_CODE section must not be empty.")

        return {"html_code": html_section}


uiux_component_generator = UIUXComponentGenerator()
