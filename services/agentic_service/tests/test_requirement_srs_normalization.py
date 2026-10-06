"""
Unit tests for RequirementAgent._normalize_plain_list_fields (wired into
_parse_and_validate_json) -- a real, confirmed bug: the LLM generating an SRS
mimicked functional_requirements/acceptance_criteria/etc.'s {"id", "description"}
object shape for data_requirements, a field documented as a plain list[str]
(RequirementBAInput/requirement_schema.py). Nothing checked the SHAPE of these
fields before saving, only that required top-level keys were present -- the
malformed artifact saved cleanly and crashed the frontend's document viewer
("Objects are not valid as a React child (found: object with keys {id,
description})"), reproduced against a real, live generated SRS.

No LLM -- _parse_and_validate_json takes a raw JSON string directly.
"""

import json

import pytest

from app.agents.requirement_agent.agent import PLAIN_LIST_SRS_FIELDS, RequirementAgent

BASE_SRS = {
    "project_id": "proj_x",
    "project_name": "Sample",
    "project_type": "E-commerce",
    "feature_id": "feature_x",
    "feature_name": "Item Listing",
    "target_stack": "Next.js",
    "architectural_style": "modular",
    "business_goal": "Manage a catalog of items.",
    "functional_requirements": [{"id": "FR-001", "description": "User can create an item."}],
    "non_functional_requirements": [{"id": "NFR-001", "description": "Fast."}],
    "acceptance_criteria": [{"id": "AC-001", "description": "Given..."}],
    "constraints": [],
    "assumptions": [],
    "traceability": [],
}


@pytest.fixture
def agent():
    return RequirementAgent()


def test_object_shaped_data_requirements_are_normalized_to_plain_strings(agent):
    srs = dict(BASE_SRS)
    srs["data_requirements"] = [
        {"id": "DR-001", "description": "price (number, required, minimum value 0.01)"},
        {"id": "DR-002", "description": "name (string, required)"},
    ]

    parsed = agent._parse_and_validate_json(json.dumps(srs))

    assert parsed["data_requirements"] == [
        "price (number, required, minimum value 0.01)",
        "name (string, required)",
    ]
    assert all(isinstance(entry, str) for entry in parsed["data_requirements"])


def test_already_plain_string_entries_are_left_unchanged(agent):
    srs = dict(BASE_SRS)
    srs["data_requirements"] = ["price: number, required"]

    parsed = agent._parse_and_validate_json(json.dumps(srs))

    assert parsed["data_requirements"] == ["price: number, required"]


def test_mixed_string_and_object_entries_are_all_normalized(agent):
    srs = dict(BASE_SRS)
    srs["data_requirements"] = [
        "quantity: integer, required",
        {"id": "DR-002", "description": "category: string, required"},
    ]

    parsed = agent._parse_and_validate_json(json.dumps(srs))

    assert parsed["data_requirements"] == [
        "quantity: integer, required",
        "category: string, required",
    ]


def test_object_entry_missing_a_description_falls_back_to_json_dump(agent):
    srs = dict(BASE_SRS)
    srs["data_requirements"] = [{"id": "DR-001", "unexpected_key": "no description here"}]

    parsed = agent._parse_and_validate_json(json.dumps(srs))

    # Never raises, never leaves a bare object -- worst case is a readable JSON string.
    assert len(parsed["data_requirements"]) == 1
    assert isinstance(parsed["data_requirements"][0], str)
    assert "unexpected_key" in parsed["data_requirements"][0]


def test_id_tagged_sections_are_never_touched_by_normalization(agent):
    """functional_requirements/non_functional_requirements/acceptance_criteria are SUPPOSED to
    be {id, description} objects -- normalization must only ever touch PLAIN_LIST_SRS_FIELDS."""
    srs = dict(BASE_SRS)

    parsed = agent._parse_and_validate_json(json.dumps(srs))

    assert parsed["functional_requirements"] == [{"id": "FR-001", "description": "User can create an item."}]


def test_every_plain_list_field_is_covered():
    """
    Sanity-locks PLAIN_LIST_SRS_FIELDS against a real regression: if a new plain-list SRS field
    is ever added to the schema, this list needs to be updated too, or the new field would be
    silently unprotected against the exact same crash class this fix addresses.
    """
    assert PLAIN_LIST_SRS_FIELDS == [
        "scope", "out_of_scope", "user_roles", "input_requirements", "output_requirements",
        "ui_expectations", "api_expectations", "data_requirements", "constraints",
        "assumptions", "risks", "dependencies",
    ]
