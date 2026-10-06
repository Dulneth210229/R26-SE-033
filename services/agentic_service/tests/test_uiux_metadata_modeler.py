"""
Tests for UIUXMetadataModeler's JSON-repair ladder -- real, confirmed gap this locks in: a real
run against qwen3-coder:latest produced an empty/missing "pages" list twice in a row (the
initial generation AND the old one-shot repair), crashing the whole request even though the
SEPARATE coverage/structure validation-repair loop (agent.py's MAX_VALIDATION_REPAIR_ATTEMPTS)
already tolerates multiple rounds for a different failure class. repair_until_valid() now gives
JSON-parse-level failures the same real chance to converge.

Mocks the LLM provider directly (no real HTTP), matching this project's established
mock-provider convention for agent-level tests.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.uiux_agent.metadata_modeler import UIMetadataGenerationError, UIUXMetadataModeler

VALID_METADATA_JSON = '{"pages": [{"page_id": "p", "components": []}], "color_theme": "indigo"}'
EMPTY_PAGES_JSON = '{"pages": [], "color_theme": "indigo"}'
MISSING_PAGES_JSON = '{"color_theme": "indigo"}'
NOT_JSON_AT_ALL = "Sorry, I can't help with that."


@pytest.fixture
def modeler():
    return UIUXMetadataModeler()


@pytest.mark.asyncio
async def test_repair_until_valid_succeeds_on_first_repair_attempt(modeler):
    provider = AsyncMock()
    provider.invoke_agent = AsyncMock(return_value=VALID_METADATA_JSON)

    parsed, raw = await modeler.repair_until_valid(EMPTY_PAGES_JSON, provider)

    assert parsed["pages"] == [{"page_id": "p", "components": []}]
    assert raw == VALID_METADATA_JSON
    assert provider.invoke_agent.await_count == 1


@pytest.mark.asyncio
async def test_repair_until_valid_recovers_after_multiple_bad_attempts(modeler):
    """The exact real failure this fix targets: two consecutive bad responses (previously fatal
    after just one), then a third, valid one -- repair_until_valid must keep trying."""
    provider = AsyncMock()
    provider.invoke_agent = AsyncMock(
        side_effect=[EMPTY_PAGES_JSON, MISSING_PAGES_JSON, VALID_METADATA_JSON]
    )

    parsed, raw = await modeler.repair_until_valid(NOT_JSON_AT_ALL, provider)

    assert parsed["pages"]
    assert provider.invoke_agent.await_count == 3


@pytest.mark.asyncio
async def test_repair_until_valid_raises_only_after_every_attempt_exhausted(modeler):
    provider = AsyncMock()
    provider.invoke_agent = AsyncMock(return_value=EMPTY_PAGES_JSON)

    with pytest.raises(UIMetadataGenerationError, match="after 3 repair attempts"):
        await modeler.repair_until_valid(NOT_JSON_AT_ALL, provider)

    assert provider.invoke_agent.await_count == modeler.MAX_JSON_REPAIR_ATTEMPTS


@pytest.mark.asyncio
async def test_generate_needs_no_repair_when_first_response_is_already_valid(modeler):
    with patch("app.agents.uiux_agent.metadata_modeler.llm_provider_service") as mock_service:
        provider = AsyncMock()
        provider.invoke_agent = AsyncMock(return_value=VALID_METADATA_JSON)
        mock_service.get_provider.return_value = provider

        parsed, raw = await modeler.generate(
            project={}, feature={}, srs_json={}, enhanced_srs_json=None,
            architecture_plan_json={}, design_system_json={}, ui_preferences={}, human_comment=None,
        )

        assert parsed["pages"]
        assert provider.invoke_agent.await_count == 1


@pytest.mark.asyncio
async def test_generate_delegates_to_repair_until_valid_and_recovers(modeler):
    """generate()'s own repair phase must get the same widened retry budget, not just
    repair_until_valid() called directly."""
    with patch("app.agents.uiux_agent.metadata_modeler.llm_provider_service") as mock_service:
        provider = AsyncMock()
        provider.invoke_agent = AsyncMock(
            side_effect=[NOT_JSON_AT_ALL, EMPTY_PAGES_JSON, VALID_METADATA_JSON]
        )
        mock_service.get_provider.return_value = provider

        parsed, raw = await modeler.generate(
            project={}, feature={}, srs_json={}, enhanced_srs_json=None,
            architecture_plan_json={}, design_system_json={}, ui_preferences={}, human_comment=None,
        )

        assert parsed["pages"]
        # 1 initial generation call + 2 repair calls before the 3rd response finally parsed.
        assert provider.invoke_agent.await_count == 3


@pytest.mark.asyncio
async def test_generate_raises_ui_metadata_generation_error_after_all_attempts_fail(modeler):
    with patch("app.agents.uiux_agent.metadata_modeler.llm_provider_service") as mock_service:
        provider = AsyncMock()
        provider.invoke_agent = AsyncMock(return_value=NOT_JSON_AT_ALL)
        mock_service.get_provider.return_value = provider

        with pytest.raises(UIMetadataGenerationError):
            await modeler.generate(
                project={}, feature={}, srs_json={}, enhanced_srs_json=None,
                architecture_plan_json={}, design_system_json={}, ui_preferences={}, human_comment=None,
            )

        # 1 initial generation call + MAX_JSON_REPAIR_ATTEMPTS repair calls.
        assert provider.invoke_agent.await_count == 1 + modeler.MAX_JSON_REPAIR_ATTEMPTS
