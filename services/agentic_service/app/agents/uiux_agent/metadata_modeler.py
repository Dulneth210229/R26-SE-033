"""
UI/UX Agent metadata modeler.

Purpose:
- Ask the LLM (one-shot, via the existing llm_provider_service -- no tool
  calling needed) for ui_metadata_json.
- Parse and repair its output.

This mirrors architecture_agent's JSON-extraction/repair pattern -- give up and let the caller
decide once repair is exhausted (the UI/UX Agent fails loudly rather than synthesizing a fallback
here, since a guessed-at UI plan is more likely to be actively wrong than merely absent).

Real, confirmed gap this file fixes: the JSON-repair step (distinct from the SEPARATE
coverage/structure validation-repair loop in agent.py, which already retries up to
MAX_VALIDATION_REPAIR_ATTEMPTS times) previously got exactly ONE repair attempt before raising --
a real run against qwen3-coder:latest (a genuinely capable model) failed this exact way on a real
feature: two consecutive responses in a row both came back with an empty/missing "pages" list.
repair_until_valid() below widens this to MAX_JSON_REPAIR_ATTEMPTS tries and is shared by both
generate() (non-streaming run()'s own repair phase) and UIUXAgent.run_stream() (whose first LLM
call already happened via provider.stream(), so it calls this method directly instead of
duplicating the retry logic inline, which is also what used to leave run_stream() with the same
one-shot gap independently).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agents.uiux_agent.prompt import (
    UIUX_METADATA_SYSTEM_PROMPT,
    UIUX_JSON_REPAIR_PROMPT,
    build_uiux_json_repair_prompt,
    build_uiux_metadata_user_prompt,
    build_uiux_validation_repair_prompt,
)
from app.core.enums import AgentName
from app.services.llm_provider_service import llm_provider_service
from app.utils.logger import get_logger

logger = get_logger(__name__)


class UIMetadataGenerationError(Exception):
    """Raised when the LLM output could not be parsed into ui_metadata_json after every repair
    attempt is exhausted."""


class UIUXMetadataModeler:
    """
    Generates ui_metadata_json from approved SRS + Architecture Plan + the
    project's existing design system.
    """

    # See module docstring -- a real run against qwen3-coder:latest needed more than one repair
    # round to recover from a missing/empty "pages" list. 3 repair attempts (on top of the
    # initial generation) gives real convergence room without an unbounded retry loop.
    MAX_JSON_REPAIR_ATTEMPTS = 3

    async def generate(
        self,
        project: dict,
        feature: dict,
        srs_json: dict,
        enhanced_srs_json: dict | None,
        architecture_plan_json: dict,
        design_system_json: dict,
        ui_preferences: dict,
        human_comment: str | None,
    ) -> tuple[dict[str, Any], str]:
        """
        Returns (ui_metadata_json, raw_llm_output).
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)

        prompt = build_uiux_metadata_user_prompt(
            project=project,
            feature=feature,
            srs_json=srs_json,
            enhanced_srs_json=enhanced_srs_json,
            architecture_plan_json=architecture_plan_json,
            design_system_json=design_system_json,
            ui_preferences=ui_preferences,
            human_comment=human_comment,
        )

        raw_output = await provider.invoke_agent(
            [
                {"role": "system", "content": UIUX_METADATA_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ]
        )

        try:
            return self._extract_json_object(raw_output), raw_output
        except ValueError:
            pass

        return await self.repair_until_valid(raw_output, provider)

    async def repair_until_valid(self, raw_output: str, provider: Any = None) -> tuple[dict[str, Any], str]:
        """
        Retry the JSON-repair prompt up to MAX_JSON_REPAIR_ATTEMPTS times, feeding back the
        previous (still-invalid) output each round, until it parses into a valid ui_metadata_json
        (a dict with a non-empty "pages" list) or every attempt is exhausted. Raises
        UIMetadataGenerationError only after the last attempt still fails -- this agent's
        deliberate "fail loudly, never fabricate a fallback" design (see module docstring) is
        unchanged, only the number of real chances to recover before that happens.
        """

        if provider is None:
            provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)

        last_error: ValueError | None = None

        for attempt in range(1, self.MAX_JSON_REPAIR_ATTEMPTS + 1):
            repair_prompt = build_uiux_json_repair_prompt(raw_output)

            raw_output = await provider.invoke_agent(
                [
                    {"role": "system", "content": UIUX_JSON_REPAIR_PROMPT},
                    {"role": "user", "content": repair_prompt},
                ]
            )

            try:
                return self._extract_json_object(raw_output), raw_output
            except ValueError as error:
                last_error = error
                logger.warning(
                    "UI/UX metadata JSON repair attempt %s/%s still invalid: %s",
                    attempt, self.MAX_JSON_REPAIR_ATTEMPTS, error,
                )

        raise UIMetadataGenerationError(
            f"UI/UX Agent could not produce valid ui_metadata_json after "
            f"{self.MAX_JSON_REPAIR_ATTEMPTS} repair attempts: {last_error}"
        ) from last_error

    async def repair_for_validation(self, raw_output: str, validation_error: str) -> tuple[dict[str, Any], str]:
        """
        One targeted repair attempt for output that parsed fine but failed the coverage/
        structure validator (metadata_validator.py) -- distinct from the JSON-parse repair
        above. Mirrors Requirement/Domain/Architecture Agent's "one repair attempt" reliability
        pattern; the caller (UIUXAgent) still fails loudly if this also comes back invalid,
        preserving this agent's original no-fabricated-fallback design.
        """

        provider = llm_provider_service.get_provider(agent_name=AgentName.UIUX.value)
        repair_prompt = build_uiux_validation_repair_prompt(raw_output, validation_error)

        repaired_output = await provider.invoke_agent(
            [
                {"role": "system", "content": UIUX_METADATA_SYSTEM_PROMPT},
                {"role": "user", "content": repair_prompt},
            ]
        )

        return self._extract_json_object(repaired_output), repaired_output

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        cleaned = text.strip()

        cleaned = re.sub(r"^```json\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^```\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")

            if start == -1 or end == -1 or end <= start:
                raise ValueError("No JSON object found in UI/UX Agent output.")

            parsed = json.loads(cleaned[start : end + 1])

        if not isinstance(parsed, dict):
            raise ValueError("UI/UX Agent output must be a JSON object.")

        if not isinstance(parsed.get("pages"), list) or not parsed["pages"]:
            raise ValueError("ui_metadata_json.pages must be a non-empty list.")

        return parsed
