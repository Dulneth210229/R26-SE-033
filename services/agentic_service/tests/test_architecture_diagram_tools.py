"""
Unit tests for the dedicated diagram-generation tools
(app/agents/architecture_agent/diagram_tools.py): build_sequence_diagram_tools
/ build_class_diagram_tools. No LLM involved -- these exercise the read/
validate/submit tools directly, including the real modeler+validator
pipeline that validate_sequence_draft/validate_class_draft calls into.
"""

import json

from app.agents.architecture_agent.class_modeler import ArchitectureClassModeler
from app.agents.architecture_agent.class_validator import ClassDiagramValidator
from app.agents.architecture_agent.diagram_tools import (
    build_class_diagram_tools,
    build_sequence_diagram_tools,
)
from app.agents.architecture_agent.sequence_modeler import ArchitectureSequenceModeler
from app.agents.architecture_agent.sequence_validator import SequenceDiagramValidator

SRS = {
    "feature_name": "Task Search",
    "functional_requirements": [{"id": "FR-001", "description": "Search tasks by keyword."}],
    "acceptance_criteria": [{"id": "AC-001", "description": "Matching tasks are displayed."}],
}
ARCHITECTURE_PLAN = {
    "design_views": {
        "interface_view": {"api_endpoints": [{"method": "GET", "endpoint": "/api/task-search"}]},
        "data_view": {"data_entities": [{"name": "Task"}]},
    }
}

VALID_SEQUENCE_DRAFT = {
    "participants": [
        {"name": "Registered User", "type": "actor"},
        {"name": "TaskSearchBoundary", "type": "boundary"},
        {"name": "TaskSearchController", "type": "control"},
    ],
    "interactions": [
        {"kind": "message", "from": "Registered User", "to": "TaskSearchBoundary", "message": "Type keyword", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "TaskSearchBoundary", "to": "TaskSearchController", "message": "Search tasks", "message_type": "sync", "related_requirements": ["FR-001"]},
        {"kind": "message", "from": "TaskSearchController", "to": "TaskSearchBoundary", "message": "Return results", "message_type": "return", "related_requirements": ["AC-001"]},
    ],
}

# References a participant name that doesn't exist -- the modeler drops the
# message entirely, leaving the diagram genuinely too weak, a real error.
INVALID_SEQUENCE_DRAFT = {
    "participants": [{"name": "User", "type": "actor"}],
    "interactions": [
        {"kind": "message", "from": "User", "to": "Ghost", "message": "Do thing", "message_type": "sync", "related_requirements": ["FR-001"]},
    ],
}

VALID_CLASS_DRAFT = {
    "classes": [
        {"name": "TaskSearchController", "stereotype": "control",
         "operations": [{"name": "searchTasks", "parameters": ["request"], "return_type": "Response", "visibility": "+"}],
         "related_requirements": ["FR-001"]},
        {"name": "Task", "stereotype": "entity",
         "attributes": [{"name": "title", "type": "String", "visibility": "-"}],
         "related_requirements": ["FR-001"]},
    ],
    "relationships": [
        {"from": "TaskSearchController", "to": "Task", "type": "association", "label": "reads",
         "source_multiplicity": "1", "target_multiplicity": "0..*"},
    ],
}

# Anemic DTO -- real, confirmed quality failure mode.
INVALID_CLASS_DRAFT = {
    "classes": [
        {"name": "TaskSearchController", "stereotype": "control", "related_requirements": ["FR-001"]},
        {"name": "Task", "stereotype": "entity",
         "attributes": [{"name": "id", "type": "String", "visibility": "+"}],
         "related_requirements": ["FR-001"]},
    ],
    "relationships": [],
}


class TestSequenceDiagramTools:
    def _build(self):
        return build_sequence_diagram_tools(
            srs_json=SRS,
            architecture_plan_json=ARCHITECTURE_PLAN,
            sequence_modeler=ArchitectureSequenceModeler(),
            sequence_validator=SequenceDiagramValidator(),
        )

    def test_read_functional_requirements(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = json.loads(by_name["read_functional_requirements"].invoke({}))
        assert result == SRS["functional_requirements"]

    def test_read_acceptance_criteria(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = json.loads(by_name["read_acceptance_criteria"].invoke({}))
        assert result == SRS["acceptance_criteria"]

    def test_read_interface_and_data_context(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = json.loads(by_name["read_interface_and_data_context"].invoke({}))
        assert result["interface_view"] == ARCHITECTURE_PLAN["design_views"]["interface_view"]
        assert result["data_view"] == ARCHITECTURE_PLAN["design_views"]["data_view"]

    def test_validate_sequence_draft_reports_valid(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_sequence_draft"].invoke({"specification_json": json.dumps(VALID_SEQUENCE_DRAFT)})
        assert result == "VALID"

    def test_validate_sequence_draft_reports_real_errors(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_sequence_draft"].invoke({"specification_json": json.dumps(INVALID_SEQUENCE_DRAFT)})
        assert "VALID" != result
        assert "interactions" in result or "too weak" in result

    def test_validate_sequence_draft_handles_malformed_json(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_sequence_draft"].invoke({"specification_json": "{not json"})
        assert "Invalid JSON" in result

    def test_validate_sequence_draft_nudges_after_three_failed_attempts(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        results = [
            by_name["validate_sequence_draft"].invoke({"specification_json": json.dumps(INVALID_SEQUENCE_DRAFT)})
            for _ in range(3)
        ]
        assert "unlikely to help" not in results[0]
        assert "unlikely to help" not in results[1]
        assert "unlikely to help" in results[2]

    def test_submit_sequence_specification_captures_argument(self):
        tools, captured = self._build()
        by_name = {t.name: t for t in tools}
        draft_json = json.dumps(VALID_SEQUENCE_DRAFT)
        result = by_name["submit_sequence_specification"].invoke({"specification_json": draft_json})
        assert "submitted" in result.lower()
        assert captured["sequence_json"] == draft_json


class TestClassDiagramTools:
    def _build(self, sequence_specification_json=VALID_SEQUENCE_DRAFT):
        return build_class_diagram_tools(
            srs_json=SRS,
            architecture_plan_json=ARCHITECTURE_PLAN,
            sequence_specification_json=sequence_specification_json,
            class_modeler=ArchitectureClassModeler(),
            class_validator=ClassDiagramValidator(),
        )

    def test_read_finalized_sequence_names(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = json.loads(by_name["read_finalized_sequence_names"].invoke({}))
        names = {item["name"] for item in result}
        assert names == {"Registered User", "TaskSearchBoundary", "TaskSearchController"}

    def test_read_finalized_sequence_names_handles_empty_sequence(self):
        tools, _ = self._build(sequence_specification_json={})
        by_name = {t.name: t for t in tools}
        result = json.loads(by_name["read_finalized_sequence_names"].invoke({}))
        assert result == []

    def test_validate_class_draft_reports_valid(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_class_draft"].invoke({"specification_json": json.dumps(VALID_CLASS_DRAFT)})
        assert result == "VALID"

    def test_validate_class_draft_reports_real_errors(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_class_draft"].invoke({"specification_json": json.dumps(INVALID_CLASS_DRAFT)})
        assert result != "VALID"
        assert "placeholder attributes" in result

    def test_validate_class_draft_handles_malformed_json(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_class_draft"].invoke({"specification_json": "not json"})
        assert "Invalid JSON" in result

    def test_validate_class_draft_nudges_after_three_failed_attempts(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        results = [
            by_name["validate_class_draft"].invoke({"specification_json": json.dumps(INVALID_CLASS_DRAFT)})
            for _ in range(3)
        ]
        assert "unlikely to help" not in results[0]
        assert "unlikely to help" not in results[1]
        assert "unlikely to help" in results[2]

    def test_submit_class_specification_captures_argument(self):
        tools, captured = self._build()
        by_name = {t.name: t for t in tools}
        draft_json = json.dumps(VALID_CLASS_DRAFT)
        result = by_name["submit_class_specification"].invoke({"specification_json": draft_json})
        assert "submitted" in result.lower()
        assert captured["class_json"] == draft_json
