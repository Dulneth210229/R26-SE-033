"""
Unit tests for the Requirement Agent's conversational gap-filling loop.

Pure Python where possible (project_ba_input_to_srs_shape, conversation_quality_gate.assess) --
no LLM/Mongo. run_gap_analysis tests mock llm_provider_service, matching the established pattern
used elsewhere in this test suite (see test_architecture_usecase_repair.py).
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.requirement_agent.agent import RequirementAgent
from app.agents.requirement_agent.conversation_engine import (
    MAX_QUESTIONS_PER_TURN,
    TIER_1_FIELDS,
    project_ba_input_to_srs_shape,
    run_gap_analysis,
)
from app.schemas.requirement_conversation_schema import RequirementConversationConfirmRequest
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id
from app.agents.requirement_agent.conversation_quality_gate import assess

PROJECT = {
    "project_id": "proj_1",
    "project_name": "QuickCart",
    "project_type": "E-commerce",
    "target_stack": "MERN",
}
FEATURE = {
    "feature_id": "feature_1",
    "feature_name": "Item Management",
    "feature_description": "let admins manage inventory somehow",
}

CONCRETE_BA_INPUT = {
    "functional_requirements": [
        "Admin can create an item",
        "Admin can edit an item",
        "Admin can delete an item",
    ],
    "api_expectations": [
        "POST /api/items",
        "GET /api/items",
        "PUT /api/items/:id",
        "DELETE /api/items/:id",
    ],
    "data_requirements": ["name", "description", "price", "stock_quantity"],
    "user_roles": ["Admin"],
    "business_goal": "Let admins keep the product catalog accurate and up to date.",
}


# ---------------------------------------------------------------------------
# project_ba_input_to_srs_shape
# ---------------------------------------------------------------------------

def test_empty_ba_input_flags_every_default_honestly():
    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, {})

    for field in ["functional_requirements", "api_expectations", "data_requirements", "user_roles"]:
        assert field in defaulted_fields

    # No claim of a parsing failure -- that line belongs only to the wrapper
    # (_build_fallback_srs_json), never to the live-preview projection itself.
    assert not any("parsing failed" in a for a in srs_json["assumptions"])
    assert srs_json["risks"] == []


def test_concrete_ba_input_does_not_default_tier1_fields():
    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, CONCRETE_BA_INPUT)

    for field in TIER_1_FIELDS:
        assert field not in defaulted_fields

    assert len(srs_json["functional_requirements"]) == 3
    assert srs_json["functional_requirements"][0]["id"] == "FR-001"


def test_traceability_has_one_row_per_functional_requirement():
    srs_json, _ = project_ba_input_to_srs_shape(PROJECT, FEATURE, CONCRETE_BA_INPUT)

    assert len(srs_json["traceability"]) == 3
    assert {row["requirement_id"] for row in srs_json["traceability"]} == {"FR-001", "FR-002", "FR-003"}


def test_build_fallback_srs_json_wrapper_still_adds_failure_reason_and_risk():
    """The existing LLM-failure fallback path (agent.py's _build_fallback_srs_json) must keep
    its exact prior behavior after being refactored to delegate to project_ba_input_to_srs_shape."""
    agent = RequirementAgent()

    srs_json = agent._build_fallback_srs_json(PROJECT, FEATURE, {}, reason="malformed JSON")

    assert any("parsing failed: malformed JSON" in a for a in srs_json["assumptions"])
    assert any("may need human refinement" in r for r in srs_json["risks"])


# ---------------------------------------------------------------------------
# conversation_quality_gate.assess
# ---------------------------------------------------------------------------

def test_quality_gate_blocks_on_empty_functional_requirements():
    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, {})

    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert result.ready is False
    assert result.auto_assumed_tier1_count == len(TIER_1_FIELDS)
    assert any("No functional requirements" in r for r in result.reasons)


def test_quality_gate_blocks_when_sole_fr_just_restates_description():
    ba_input = dict(CONCRETE_BA_INPUT)
    ba_input["functional_requirements"] = [FEATURE["feature_description"]]

    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, ba_input)
    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert result.ready is False
    assert any("just restates the feature description" in r for r in result.reasons)


def test_quality_gate_flags_malformed_api_endpoint():
    ba_input = dict(CONCRETE_BA_INPUT)
    ba_input["api_expectations"] = ["an API for items"]

    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, ba_input)
    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert result.ready is False
    assert any("doesn't look like a real" in r for r in result.reasons)


def test_quality_gate_flags_vague_data_requirement():
    ba_input = dict(CONCRETE_BA_INPUT)
    ba_input["data_requirements"] = ["the item should probably have some kind of name and description field"]

    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, ba_input)
    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert result.ready is False
    assert any("vague sentence" in r for r in result.reasons)


def test_quality_gate_does_not_flag_a_well_annotated_structured_field_spec():
    # Real, reported bug: a detailed, well-formed field spec ("name -- type, notes") was flagged
    # as "vague" purely for exceeding a plain word count, even though the extra words are a type
    # annotation and a clarifying note, not sentence padding.
    ba_input = dict(CONCRETE_BA_INPUT)
    ba_input["data_requirements"] = [
        "name — string, required (user's full name or display name)",
        "email: string, required, unique, valid email format",
        "createdAt (auto-generated timestamp)",
    ]

    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, ba_input)
    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert not any("vague sentence" in r for r in result.reasons)


def test_quality_gate_still_flags_a_long_field_description_with_no_structure():
    # A genuinely vague, unstructured description (no field-name-then-separator shape) must
    # still be caught -- the fix narrows the false positive, it doesn't disable the check.
    ba_input = dict(CONCRETE_BA_INPUT)
    ba_input["data_requirements"] = ["the full name of the user who is registering for an account"]

    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, ba_input)
    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert result.ready is False
    assert any("vague sentence" in r for r in result.reasons)


def test_quality_gate_passes_when_tier1_and_business_goal_are_all_answered():
    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, CONCRETE_BA_INPUT)

    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert result.ready is True
    assert result.reasons == []
    assert result.auto_assumed_tier1_count == 0


def test_quality_gate_flags_boilerplate_business_goal():
    ba_input = dict(CONCRETE_BA_INPUT)
    del ba_input["business_goal"]

    srs_json, defaulted_fields = project_ba_input_to_srs_shape(PROJECT, FEATURE, ba_input)
    result = assess(srs_json, defaulted_fields, FEATURE["feature_description"])

    assert any("generic template" in r for r in result.reasons)


# ---------------------------------------------------------------------------
# run_gap_analysis
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_gap_analysis_merges_known_answers_and_truncates_questions():
    llm_response = json.dumps(
        {
            "known_answers": {"functional_requirements": ["Admin can create an item"]},
            "questions": ["Q1?", "Q2?", "Q3?", "Q4?", "Q5?"],
            "assumptions": ["Defaulted target_stack to MERN."],
        }
    )

    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value=llm_response)

    with patch("app.agents.requirement_agent.conversation_engine.llm_provider_service") as mock_llm:
        mock_llm.get_provider.return_value = provider

        result = await run_gap_analysis(
            project=PROJECT, feature=FEATURE, known_answers={"user_roles": ["Admin"]}, latest_reply="We need item CRUD."
        )

    # Previously known field preserved (LLM response didn't repeat it), new field merged in.
    assert result.known_answers["user_roles"] == ["Admin"]
    assert result.known_answers["functional_requirements"] == ["Admin can create an item"]

    # Defensively truncated regardless of what the LLM returned.
    assert len(result.questions) == MAX_QUESTIONS_PER_TURN
    assert provider.invoke_agent.await_count == 1


@pytest.mark.asyncio
async def test_run_gap_analysis_falls_back_to_deterministic_checklist_on_total_parse_failure():
    provider = MagicMock()
    provider.invoke_agent = AsyncMock(return_value="not json at all, sorry")

    with patch("app.agents.requirement_agent.conversation_engine.llm_provider_service") as mock_llm:
        mock_llm.get_provider.return_value = provider

        result = await run_gap_analysis(
            project=PROJECT, feature=FEATURE, known_answers={}, latest_reply=None
        )

    # Raw attempt + one repair attempt, then the deterministic checklist -- no third LLM call.
    assert provider.invoke_agent.await_count == 2
    assert len(result.questions) <= MAX_QUESTIONS_PER_TURN
    assert all("question" in q and "placeholder_example" in q for q in result.questions)
    assert any("actions" in q["question"] for q in result.questions)
    assert all(q["placeholder_example"] for q in result.questions)


# ---------------------------------------------------------------------------
# confirm_conversation_stream
# ---------------------------------------------------------------------------

import shutil

from app.utils.slugify import slugify

VALID_SRS_JSON_TEMPLATE = {
    "project_name": "Stream Test Project",
    "project_type": "E-commerce",
    "feature_name": "Stream Test Feature",
    "target_stack": "MERN",
    "architectural_style": "modular",
    "business_goal": "Real business goal",
    "functional_requirements": [
        {"id": "FR-001", "description": "Admin can create an item", "priority": "Must Have"}
    ],
    "non_functional_requirements": [
        {"id": "NFR-001", "description": "Fast", "category": "Performance"}
    ],
    "acceptance_criteria": [{"id": "AC-001", "description": "Given valid input, item is created."}],
    "constraints": [],
    "assumptions": [],
    "traceability": [],
}


@pytest.fixture
def conversation_fixture():
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": "Stream Test Project",
        "project_type": "E-commerce",
        "target_stack": "MERN",
    }
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Stream Test Feature",
        "feature_description": "let admins manage items",
    }
    store.requirement_conversations[feature_id] = {
        "feature_id": feature_id,
        "known_answers": {
            "functional_requirements": ["Admin can create an item"],
            "api_expectations": ["POST /api/items"],
            "data_requirements": ["name", "price"],
            "business_goal": "Real business goal",
        },
        "srs_preview": {},
        "open_questions": [],
        "assumptions_flagged": [],
        "turn_history": [],
        "status": "gathering",
        "quality_gate": None,
    }

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["requirement_conversations"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})

    output_root = f"outputs/{slugify('Stream Test Project')}/feature-{slugify('Stream Test Feature')}"
    shutil.rmtree(output_root, ignore_errors=True)


@pytest.mark.asyncio
async def test_confirm_conversation_stream_yields_tokens_then_done(conversation_fixture):
    feature_id = conversation_fixture["feature_id"]

    srs_json = dict(VALID_SRS_JSON_TEMPLATE)
    srs_json["project_id"] = conversation_fixture["project_id"]
    srs_json["feature_id"] = feature_id

    raw_json = json.dumps(srs_json)
    chunks = [raw_json[i : i + 20] for i in range(0, len(raw_json), 20)]

    provider = MagicMock()

    async def fake_stream(prompt, system_prompt=None, **kwargs):
        for chunk in chunks:
            yield chunk

    provider.stream = fake_stream

    agent = RequirementAgent()
    events = []

    with patch("app.agents.requirement_agent.agent.llm_provider_service") as mock_llm:
        mock_llm.get_provider.return_value = provider

        async for event in agent.confirm_conversation_stream(feature_id, RequirementConversationConfirmRequest()):
            events.append(event)

    token_events = [e for e in events if e["type"] == "token"]
    done_events = [e for e in events if e["type"] == "done"]

    # Real, in-order token streaming -- reassembling every yielded chunk reproduces the raw
    # output exactly, and at least one token event arrived before "done".
    assert len(token_events) == len(chunks)
    assert "".join(e["text"] for e in token_events) == raw_json
    assert len(done_events) == 1
    assert len(done_events[0]["artifact_ids"]) == 2

    saved_conversation = store.requirement_conversations.get(feature_id)
    assert saved_conversation["status"] == "confirmed"


@pytest.mark.asyncio
async def test_confirm_conversation_stream_backstops_empty_user_stories(conversation_fixture):
    """
    Real, confirmed routing bug this locks in: confirm_conversation_stream is the ONLY method the
    frontend actually calls for confirm, and it duplicates _generate_requirement_output's entire
    ladder inline rather than calling it -- a completeness fix applied to only one of them would
    silently never reach the other. VALID_SRS_JSON_TEMPLATE deliberately has no "user_stories" key
    at all (matching the real, reported bug: nothing in REQUIRED_KEYS required it), so streaming
    it through confirm_conversation_stream and finding a non-empty user_stories in the SAVED
    artifact proves ensure_srs_completeness actually ran on this specific real code path.
    """
    feature_id = conversation_fixture["feature_id"]

    srs_json = dict(VALID_SRS_JSON_TEMPLATE)
    srs_json["project_id"] = conversation_fixture["project_id"]
    srs_json["feature_id"] = feature_id
    assert "user_stories" not in srs_json  # confirms the fixture itself reproduces the real gap

    raw_json = json.dumps(srs_json)

    provider = MagicMock()

    async def fake_stream(prompt, system_prompt=None, **kwargs):
        yield raw_json

    provider.stream = fake_stream

    agent = RequirementAgent()

    with patch("app.agents.requirement_agent.agent.llm_provider_service") as mock_llm:
        mock_llm.get_provider.return_value = provider

        events = [
            event
            async for event in agent.confirm_conversation_stream(feature_id, RequirementConversationConfirmRequest())
        ]

    done_event = next(e for e in events if e["type"] == "done")
    json_artifact_id = next(
        aid for aid in done_event["artifact_ids"]
        if store.artifacts[aid]["artifact_format"] == "json"
    )
    saved_srs = json.load(open(store.artifacts[json_artifact_id]["file_path"], encoding="utf-8"))

    assert len(saved_srs["user_stories"]) >= 1
    assert any("user_stories" in note for note in saved_srs["assumptions"])


@pytest.mark.asyncio
async def test_confirm_conversation_stream_blocks_when_quality_gate_not_ready(conversation_fixture):
    feature_id = conversation_fixture["feature_id"]

    # Strip the Tier-1 answers this fixture seeded so the quality gate genuinely fails.
    conversation = dict(store.requirement_conversations[feature_id])
    conversation["known_answers"] = {}
    store.requirement_conversations[feature_id] = conversation

    agent = RequirementAgent()
    provider = MagicMock()
    provider.stream = MagicMock()  # must never be called -- blocked before any LLM call

    events = []

    with patch("app.agents.requirement_agent.agent.llm_provider_service") as mock_llm:
        mock_llm.get_provider.return_value = provider

        async for event in agent.confirm_conversation_stream(feature_id, RequirementConversationConfirmRequest()):
            events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    provider.stream.assert_not_called()

    saved_conversation = store.requirement_conversations.get(feature_id)
    assert saved_conversation["status"] == "gathering"


# ---------------------------------------------------------------------------
# edit_turn_reply_stream
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_edit_turn_reply_stream_yields_tokens_then_done_with_the_new_reply(conversation_fixture):
    feature_id = conversation_fixture["feature_id"]

    conversation = dict(store.requirement_conversations[feature_id])
    conversation["turn_history"] = [
        {
            "turn_index": 1,
            "questions_asked": [{"question": "What roles?", "placeholder_example": "Admin"}],
            "human_reply": "original reply",
            "assumptions_flagged_this_turn": [],
            "agent_reaction": "Thanks for the original reply.",
            "known_answers_before": {"functional_requirements": ["Admin can create an item"]},
        }
    ]
    store.requirement_conversations[feature_id] = conversation

    gap_response = {
        "reaction": "Got it -- capturing your edited reply.",
        "known_answers": {"functional_requirements": ["Admin can create an item"], "user_roles": ["Admin"]},
        "questions": [{"question": "Any constraints?", "placeholder_example": "Must be fast"}],
        "assumptions": [],
    }
    raw_json = json.dumps(gap_response)
    chunks = [raw_json[i : i + 15] for i in range(0, len(raw_json), 15)]

    provider = MagicMock()

    async def fake_stream(prompt, system_prompt=None, **kwargs):
        for chunk in chunks:
            yield chunk

    provider.stream = fake_stream

    agent = RequirementAgent()
    events = []

    with patch("app.agents.requirement_agent.agent.llm_provider_service") as mock_llm:
        mock_llm.get_provider.return_value = provider

        async for event in agent.edit_turn_reply_stream(feature_id, 1, "the edited reply"):
            events.append(event)

    token_events = [e for e in events if e["type"] == "token"]
    done_events = [e for e in events if e["type"] == "done"]

    assert len(token_events) == len(chunks)
    assert "".join(e["text"] for e in token_events) == raw_json
    assert len(done_events) == 1

    state = done_events[0]["state"]
    assert len(state["turn_history"]) == 1
    assert state["turn_history"][0]["human_reply"] == "the edited reply"
    assert state["turn_history"][0]["agent_reaction"] == "Got it -- capturing your edited reply."

    saved_conversation = store.requirement_conversations.get(feature_id)
    assert saved_conversation["turn_history"][0]["human_reply"] == "the edited reply"


@pytest.mark.asyncio
async def test_edit_turn_reply_stream_errors_on_unknown_turn_index(conversation_fixture):
    feature_id = conversation_fixture["feature_id"]

    agent = RequirementAgent()
    events = []

    async for event in agent.edit_turn_reply_stream(feature_id, 99, "irrelevant"):
        events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "99" in events[0]["message"]
