"""
Unit tests for the dedicated use case diagram generation tools
(app/agents/architecture_agent/diagram_tools.py:build_usecase_diagram_tools). No LLM involved --
these exercise the read/validate/submit tools directly, including the real modeler+validator
pipeline that validate_usecase_draft calls into. Mirrors test_architecture_diagram_tools.py's
existing structure/coverage for the sequence/class tool builders.
"""

import json

from app.agents.architecture_agent.diagram_tools import build_usecase_diagram_tools
from app.agents.architecture_agent.usecase_modeler import ArchitectureUseCaseModeler
from app.agents.architecture_agent.usecase_validator import UseCaseQualityValidator

SRS = {
    "feature_name": "Task Search",
    "user_roles": ["Registered User"],
    "user_stories": [{"role": "Registered User", "goal": "search for tasks by keyword", "benefit": "find work quickly"}],
    "functional_requirements": [{"id": "FR-001", "description": "Search tasks by keyword."}],
    "acceptance_criteria": [{"id": "AC-001", "description": "Matching tasks are displayed."}],
}
ARCHITECTURE_PLAN = {
    "design_views": {
        "interface_view": {"api_endpoints": [{"method": "GET", "endpoint": "/api/task-search"}]},
        "data_view": {"data_entities": [{"name": "Task"}]},
    }
}

VALID_USECASE_DRAFT = {
    "system_boundary": "Task Search",
    "diagram_title": "Task Search Use Case Diagram",
    "actors": [{"name": "Registered User", "type": "primary"}],
    "use_cases": [
        {
            "name": "Search Tasks",
            "type": "main",
            "description": "A registered user searches for tasks by keyword.",
            "related_requirements": ["FR-001", "AC-001"],
        },
    ],
}

# No related_requirements anywhere -- fails real-requirement traceability.
INVALID_USECASE_DRAFT = {
    "system_boundary": "Task Search",
    "diagram_title": "Task Search Use Case Diagram",
    "actors": [{"name": "Registered User", "type": "primary"}],
    "use_cases": [
        {
            "name": "Search Tasks",
            "type": "main",
            "description": "A registered user searches for tasks by keyword.",
            "related_requirements": [],
        },
    ],
}


class TestUseCaseDiagramTools:
    def _build(self):
        return build_usecase_diagram_tools(
            srs_json=SRS,
            architecture_plan_json=ARCHITECTURE_PLAN,
            usecase_modeler=ArchitectureUseCaseModeler(),
            usecase_validator=UseCaseQualityValidator(),
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

    def test_read_user_roles_and_stories(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = json.loads(by_name["read_user_roles_and_stories"].invoke({}))
        assert result["user_roles"] == SRS["user_roles"]
        assert result["user_stories"] == SRS["user_stories"]

    def test_validate_usecase_draft_reports_valid(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_usecase_draft"].invoke({"specification_json": json.dumps(VALID_USECASE_DRAFT)})
        assert result == "VALID"

    def test_validate_usecase_draft_reports_real_errors(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_usecase_draft"].invoke({"specification_json": json.dumps(INVALID_USECASE_DRAFT)})
        assert result != "VALID"
        assert "traceability" in result

    def test_validate_usecase_draft_handles_malformed_json(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        result = by_name["validate_usecase_draft"].invoke({"specification_json": "{not json"})
        assert "Invalid JSON" in result

    def test_validate_usecase_draft_nudges_after_three_failed_attempts(self):
        tools, _ = self._build()
        by_name = {t.name: t for t in tools}
        results = [
            by_name["validate_usecase_draft"].invoke({"specification_json": json.dumps(INVALID_USECASE_DRAFT)})
            for _ in range(3)
        ]
        assert "unlikely to help" not in results[0]
        assert "unlikely to help" not in results[1]
        assert "unlikely to help" in results[2]

    def test_submit_usecase_specification_captures_argument(self):
        tools, captured = self._build()
        by_name = {t.name: t for t in tools}
        draft_json = json.dumps(VALID_USECASE_DRAFT)
        result = by_name["submit_usecase_specification"].invoke({"specification_json": draft_json})
        assert "submitted" in result.lower()
        assert captured["usecase_json"] == draft_json
