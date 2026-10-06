"""
Agent-level tests for UIUXAgent's new revision capability (run()/run_stream()/revise()/
revise_stream()) -- the "small ops plan + deterministic patcher, reuse the existing
per-component quality-gated generation pipeline, carry untouched components over verbatim"
design. No real LLM/HTTP/Docker/Playwright: provider.invoke_agent/stream, artifact_service,
component_generator, and uiux_preview_renderer are all mocked directly, matching this project's
established convention (see test_architecture_agent_revision_ladder.py).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.uiux_agent.agent import UIUXAgent
from app.agents.uiux_agent.prompt import build_uiux_revision_prompt
from app.agents.uiux_agent.schemas import UIUXAgentInput
from app.schemas.uiux_schema import UIUXAgentReviseRequest

CURRENT_METADATA = {
    "pages": [
        {
            "page_id": "item-listing-page",
            "name": "Item Listing Page",
            "route": "/items",
            "components": [
                {
                    "name": "ItemListingTable",
                    "reused_from_design_system": False,
                    "content_elements": ["item name", "item price"],
                },
                {
                    "name": "Pagination",
                    "reused_from_design_system": False,
                    "content_elements": ["page number"],
                },
            ],
        }
    ],
    "color_theme": "indigo",
}


@pytest.fixture
def agent():
    return UIUXAgent()


@pytest.fixture
def agent_input():
    return UIUXAgentInput(
        project={"project_id": "proj_revtest", "project_name": "RevisionTest"},
        feature={"feature_id": "feature_revtest", "feature_name": "Item Listing"},
        srs_json={},
        architecture_plan_json={"design_views": {"data_view": {"data_entities": []}}},
        design_system_json={},
        human_comment="Remove the pagination component",
    )


def _valid_ops_plan_json() -> str:
    return json.dumps({
        "revision_summary": "Removed the Pagination component as requested.",
        "operations": [{"action": "remove", "component_name": "Pagination"}],
    })


class TestPrepareRevision:
    def test_applies_operations_and_computes_touched_components(self, agent):
        plan = {
            "revision_summary": "Add an empty-state banner.",
            "operations": [
                {
                    "action": "add",
                    "page_id": "item-listing-page",
                    "component_name": "EmptyStateBanner",
                    "content_elements": ["no items found message"],
                }
            ],
        }

        patched, touched = agent._prepare_revision(CURRENT_METADATA, plan, "Add an empty state", "human_user")

        assert touched == {"EmptyStateBanner"}
        assert patched["revision_metadata"]["revision_summary"] == "Add an empty-state banner."
        assert patched["revision_metadata"]["applied_changes"]
        assert patched["revision_metadata"]["unmatched_operations"] == []

    def test_zero_operations_produces_honest_no_changes_note(self, agent):
        plan = {"revision_summary": "That request doesn't map to any UI change.", "operations": []}

        patched, touched = agent._prepare_revision(CURRENT_METADATA, plan, "do something unrelated", "human_user")

        assert touched == set()
        assert patched["revision_metadata"]["no_changes_note"]
        # Original components untouched.
        assert patched["pages"][0]["components"] == CURRENT_METADATA["pages"][0]["components"]

    def test_color_theme_change_touches_every_surviving_component(self, agent):
        """A genuine color_theme change (UIUX_REVISION_SYSTEM_PROMPT rule 7) means every
        surviving component needs regenerating to match the new theme, not just a metadata-field
        edit -- reuses the same touched-components pipeline an add/modify operation already
        uses."""
        plan = {
            "revision_summary": "Switched the accent color to emerald.",
            "operations": [],
            "color_theme": "emerald",
        }

        patched, touched = agent._prepare_revision(CURRENT_METADATA, plan, "make it emerald", "human_user")

        assert patched["color_theme"] == "emerald"
        assert touched == {"ItemListingTable", "Pagination"}
        assert any("emerald" in change for change in patched["revision_metadata"]["applied_changes"])

    def test_target_page_ids_threaded_into_patcher_rejects_out_of_scope_operation(self, agent):
        """Real, confirmed gap this locks in: _prepare_revision previously never threaded
        target_page_ids into the patcher at all, so the deterministic enforcement never actually
        fired for a real revision -- only relying on the soft prompt hint."""
        two_page_metadata = {
            "pages": [
                {"page_id": "item-listing-page", "components": [{"name": "ItemListingTable", "content_elements": ["a"]}]},
                {"page_id": "item-detail-page", "components": [{"name": "ItemDetailCard", "content_elements": ["b"]}]},
            ],
            "color_theme": "indigo",
        }
        plan = {
            "revision_summary": "x",
            "operations": [
                {"action": "modify", "component_name": "ItemDetailCard", "content_elements": ["changed"]}
            ],
        }

        patched, touched = agent._prepare_revision(
            two_page_metadata, plan, "change the detail card", "human_user",
            target_page_ids=["item-listing-page"],
        )

        assert touched == set()
        detail_page = next(p for p in patched["pages"] if p["page_id"] == "item-detail-page")
        assert detail_page["components"][0]["content_elements"] == ["b"]
        assert patched["revision_metadata"]["unmatched_operations"]

    def test_color_theme_change_with_target_page_ids_only_touches_selected_pages(self, agent):
        two_page_metadata = {
            "pages": [
                {"page_id": "item-listing-page", "components": [{"name": "ItemListingTable", "content_elements": ["a"]}]},
                {"page_id": "item-detail-page", "components": [{"name": "ItemDetailCard", "content_elements": ["b"]}]},
            ],
            "color_theme": "indigo",
        }
        plan = {"revision_summary": "x", "operations": [], "color_theme": "emerald"}

        patched, touched = agent._prepare_revision(
            two_page_metadata, plan, "make the listing page emerald", "human_user",
            target_page_ids=["item-listing-page"],
        )

        assert patched["color_theme"] == "emerald"
        assert touched == {"ItemListingTable"}

    def test_color_theme_unchanged_when_same_as_current(self, agent):
        plan = {"revision_summary": "no-op", "operations": [], "color_theme": "indigo"}

        patched, touched = agent._prepare_revision(CURRENT_METADATA, plan, "no real change", "human_user")

        assert patched["color_theme"] == "indigo"
        assert touched == set()

    def test_never_mutates_the_original_metadata(self, agent):
        import copy

        original = copy.deepcopy(CURRENT_METADATA)
        plan = {"revision_summary": "x", "operations": [{"action": "remove", "component_name": "Pagination"}]}

        agent._prepare_revision(CURRENT_METADATA, plan, "remove pagination", "human_user")

        assert CURRENT_METADATA == original


class TestParseAndResolveRevisionPlan:
    def test_parse_valid_plan(self, agent):
        parsed = agent._parse_uiux_revision_plan(_valid_ops_plan_json())
        assert parsed["operations"][0]["action"] == "remove"

    def test_parse_missing_operations_key_raises(self, agent):
        with pytest.raises(ValueError):
            agent._parse_uiux_revision_plan(json.dumps({"revision_summary": "no operations key"}))

    def test_parse_non_json_raises(self, agent):
        with pytest.raises(ValueError):
            agent._parse_uiux_revision_plan("not json at all")

    @pytest.mark.asyncio
    async def test_resolve_falls_through_to_repair_on_parse_failure(self, agent):
        provider = MagicMock()
        provider.invoke_agent = AsyncMock(return_value=_valid_ops_plan_json())

        plan = await agent._resolve_uiux_revision_plan(provider, "not valid json")

        assert plan["operations"][0]["action"] == "remove"
        provider.invoke_agent.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_resolve_never_raises_when_both_attempts_fail(self, agent):
        provider = MagicMock()
        provider.invoke_agent = AsyncMock(return_value="still not valid json")

        plan = await agent._resolve_uiux_revision_plan(provider, "not valid json either")

        assert plan["operations"] == []
        assert plan["revision_summary"]


class TestGenerateComponentsForRevision:
    @pytest.mark.asyncio
    async def test_untouched_component_carried_over_verbatim_touched_component_regenerated(self, agent, agent_input):
        agent._generate_component_with_quality_gate = AsyncMock(return_value="<section>NEW TABLE</section>")

        with patch.object(
            agent, "_load_component_html_by_name", return_value="<nav>OLD PAGINATION VERBATIM</nav>"
        ) as mock_load:
            component_files, page_component_order = await agent._generate_components(
                agent_input,
                CURRENT_METADATA,
                touched_components={"ItemListingTable"},
                carry_over_version=3,
            )

        assert component_files["ItemListingTable"] == "<section>NEW TABLE</section>"
        assert component_files["Pagination"] == "<nav>OLD PAGINATION VERBATIM</nav>"
        agent._generate_component_with_quality_gate.assert_awaited_once()
        mock_load.assert_called_once_with("feature_revtest", 3, "Pagination")
        assert page_component_order["item-listing-page"] == ["ItemListingTable", "Pagination"]

    @pytest.mark.asyncio
    async def test_missing_prior_html_falls_back_to_fresh_generation(self, agent, agent_input):
        agent._generate_component_with_quality_gate = AsyncMock(return_value="<section>REGENERATED</section>")

        with patch.object(agent, "_load_component_html_by_name", return_value=None):
            component_files, _order = await agent._generate_components(
                agent_input,
                CURRENT_METADATA,
                touched_components=set(),
                carry_over_version=3,
            )

        # Neither component was "touched," but since the prior-HTML lookup found nothing for
        # either, both fall through to fresh generation rather than silently omitting content.
        assert component_files["ItemListingTable"] == "<section>REGENERATED</section>"
        assert component_files["Pagination"] == "<section>REGENERATED</section>"
        assert agent._generate_component_with_quality_gate.await_count == 2

    @pytest.mark.asyncio
    async def test_run_mode_unaffected_by_the_new_optional_params(self, agent, agent_input):
        """touched_components/carry_over_version both default to None -- run()'s own existing
        fresh-generation behavior (including the reused_from_design_system lookup) must be
        completely unchanged."""
        metadata = {
            "pages": [
                {
                    "page_id": "p1",
                    "components": [
                        {"name": "ReusedThing", "reused_from_design_system": True, "content_elements": ["x"]},
                    ],
                }
            ],
            "color_theme": "indigo",
        }
        agent._generate_component_with_quality_gate = AsyncMock(return_value="<section>FRESH</section>")

        with patch.object(agent, "_load_existing_approved_component", return_value="<section>REUSED</section>") as mock_reuse:
            component_files, _order = await agent._generate_components(agent_input, metadata)

        assert component_files["ReusedThing"] == "<section>REUSED</section>"
        mock_reuse.assert_called_once()
        agent._generate_component_with_quality_gate.assert_not_awaited()


@pytest.mark.asyncio
async def test_revise_stream_end_to_end_only_touched_component_regenerated():
    """Full revise_stream() run: mocks store/read_json_file/artifact_service/component_generator/
    preview_renderer so no real Mongo/disk/LLM/Playwright access happens. Confirms: streamed
    tokens are the small ops plan (not the whole document), the removed component is genuinely
    gone from the saved output, the untouched component's HTML is carried over byte-for-byte
    (never regenerated), every artifact is saved with the default PENDING approval_status (human
    approval restored -- this stage no longer auto-approves), and apply_design_system_patch is
    NOT called directly from this method anymore (that only happens via approval_service.py's
    cascade once a human actually approves the Preview Screenshot)."""

    agent = UIUXAgent()

    fake_feature = {"feature_id": "feature_revstream", "project_id": "proj_revstream", "feature_name": "Item Listing"}
    fake_project = {"project_id": "proj_revstream", "project_name": "RevStreamTest"}
    fake_metadata_artifact = {"file_path": "metadata.json", "version": 3}

    provider = MagicMock()

    async def fake_stream(prompt, system_prompt=None, **kwargs):
        yield _valid_ops_plan_json()

    provider.stream = fake_stream

    saved_calls = []

    def fake_save_json_artifact(**kwargs):
        saved_calls.append(("json", kwargs))
        response = MagicMock()
        response.artifact_id = f"artifact_{len(saved_calls)}"
        return response

    def fake_save_text_artifact(**kwargs):
        saved_calls.append(("text", kwargs))
        response = MagicMock()
        response.artifact_id = f"artifact_{len(saved_calls)}"
        return response

    def fake_save_binary_artifact(**kwargs):
        saved_calls.append(("binary", kwargs))
        response = MagicMock()
        response.artifact_id = f"artifact_{len(saved_calls)}"
        return response

    with (
        patch("app.agents.uiux_agent.agent.store") as mock_store,
        patch("app.agents.uiux_agent.agent.read_json_file", return_value=dict(CURRENT_METADATA)),
        patch("app.agents.uiux_agent.agent.llm_provider_service") as mock_llm_service,
        patch("app.agents.uiux_agent.agent.uiux_design_system_service") as mock_design_system_service,
        patch.object(agent, "_find_latest_uiux_artifact", return_value=fake_metadata_artifact),
        patch.object(agent, "_load_approved_architecture_plan", return_value={}),
        patch.object(
            agent, "_load_component_html_by_name", return_value="<nav>OLD PAGINATION VERBATIM</nav>"
        ) as mock_load_prior,
        patch.object(agent.component_generator, "generate", new=AsyncMock()) as mock_generate,
        patch("app.agents.uiux_agent.agent.artifact_service") as mock_artifact_service,
        patch.object(agent, "apply_design_system_patch") as mock_patch,
        patch(
            "app.agents.uiux_agent.agent.uiux_preview_renderer.render_page_png",
            return_value=b"fake-png-bytes",
        ),
    ):
        mock_store.features.get.return_value = fake_feature
        mock_store.projects.get.return_value = fake_project
        mock_llm_service.get_provider.return_value = provider
        mock_design_system_service.load.return_value = {}
        mock_artifact_service.get_next_version.return_value = 4
        mock_artifact_service.save_json_artifact.side_effect = fake_save_json_artifact
        mock_artifact_service.save_text_artifact.side_effect = fake_save_text_artifact
        mock_artifact_service.save_binary_artifact.side_effect = fake_save_binary_artifact

        events = [
            event
            async for event in agent.revise_stream(
                feature_id="feature_revstream",
                request=UIUXAgentReviseRequest(
                    revision_comment="Remove the pagination component", revised_by="human_user"
                ),
            )
        ]

    token_events = [e for e in events if e.get("type") == "token"]
    phase_events = [e for e in events if e.get("type") == "phase"]
    done_events = [e for e in events if e.get("type") == "done"]

    assert token_events, "expected at least one streamed token event"
    assert "".join(e["text"] for e in token_events) == _valid_ops_plan_json()
    assert {e["phase"] for e in phase_events} == {"components", "assembly"}
    assert done_events, f"expected a 'done' event, got: {[e.get('type') for e in events]}"

    # The removed component (Pagination) is genuinely gone from the patched metadata -- it's
    # never iterated by _generate_components at all, so nothing was regenerated for it.
    # ItemListingTable is the ONE remaining, untouched component: its HTML is carried over
    # verbatim from the prior version, never (re)generated via component_generator.generate --
    # confirming this was a targeted patch, not a full regeneration.
    mock_generate.assert_not_awaited()
    mock_load_prior.assert_any_call("feature_revstream", 3, "ItemListingTable")

    # No save call overrides approval_status anymore -- every artifact defaults to PENDING,
    # requiring a real human decision (see approval_service.py's UI/UX cascade).
    assert saved_calls, "expected at least one artifact save call"
    for _kind, call_kwargs in saved_calls:
        assert "approval_status" not in call_kwargs

    # apply_design_system_patch is no longer called directly from revise_stream() -- it's only
    # ever triggered by approval_service.py once a human actually approves the output.
    mock_patch.assert_not_called()


class TestBuildUiuxRevisionPromptTargetPage:
    """Real, explicit multi-page revision targeting (direct user correction): a human can pin
    exactly which page(s) a revision is about when a feature has more than one -- selecting one
    or more specific screens, not just a single page or the whole feature."""

    def test_target_page_ids_stated_explicitly_when_given(self):
        prompt = build_uiux_revision_prompt(
            project={"project_name": "P", "project_type": "E-commerce"},
            feature={"feature_name": "Item Listing"},
            current_ui_metadata_json=CURRENT_METADATA,
            revision_comment="make it more colorful",
            revised_by="human_user",
            target_page_ids=["item-listing-page", "item-detail-page"],
        )

        assert "item-listing-page" in prompt
        assert "item-detail-page" in prompt
        assert "rule 8" in prompt

    def test_no_target_page_line_when_not_given(self):
        prompt = build_uiux_revision_prompt(
            project={"project_name": "P", "project_type": "E-commerce"},
            feature={"feature_name": "Item Listing"},
            current_ui_metadata_json=CURRENT_METADATA,
            revision_comment="make it more colorful",
            revised_by="human_user",
        )

        assert "rule 8" not in prompt
