"""
Unit tests for ArchitectureClassModeler (app/agents/architecture_agent/class_modeler.py).
No LLM involved -- these exercise the deterministic modeling logic directly.

Covers the two build() paths:
- LLM-specification path (specification["classes"] non-empty): the modeler
  must trust the LLM's classes/attributes/operations/relationships directly
  (deterministic id assignment + name resolution + light normalization
  only, no regex/keyword field inference).
- Fallback path (specification empty): the last-resort deterministic
  builder -- unchanged in behavior from before this rewrite, just demoted
  to a private method.
"""

from app.agents.architecture_agent.class_modeler import ArchitectureClassModeler


class TestLlmSpecificationPath:
    def test_trusts_llm_classes_and_attributes_directly(self):
        modeler = ArchitectureClassModeler()

        srs_json = {"feature_name": "Task Search", "functional_requirements": [{"id": "FR-001", "description": "x"}]}
        sds_json = {"design_views": {}}
        specification = {
            "diagram_title": "Task Search Class Diagram",
            "classes": [
                {
                    "name": "TaskSearchController", "stereotype": "control",
                    "operations": [{"name": "searchTasks", "parameters": ["request"], "return_type": "TaskSearchResponse", "visibility": "+"}],
                    "related_requirements": ["FR-001"],
                },
                {
                    "name": "Task", "stereotype": "entity",
                    "attributes": [
                        {"name": "title", "type": "String", "visibility": "-"},
                        {"name": "description", "type": "String", "visibility": "-"},
                    ],
                    "related_requirements": ["FR-001"],
                },
            ],
            "relationships": [
                {"from": "TaskSearchController", "to": "Task", "type": "dependency", "label": "reads"},
            ],
        }

        result = modeler.build(srs_json=srs_json, sds_json=sds_json, class_specification_json=specification)

        assert result["diagram_title"] == "Task Search Class Diagram"
        names = {c["name"] for c in result["classes"]}
        assert names == {"TaskSearchController", "Task"}

        task_class = next(c for c in result["classes"] if c["name"] == "Task")
        attribute_names = {a["name"] for a in task_class["attributes"]}
        assert attribute_names == {"title", "description"}
        # No placeholder single "id" field when the LLM provided real fields.
        assert "id" not in attribute_names

    def test_resolves_relationship_names_to_deterministic_ids(self):
        modeler = ArchitectureClassModeler()
        specification = {
            "classes": [
                {"name": "Repository", "stereotype": "repository"},
                {"name": "Task", "stereotype": "entity", "attributes": [{"name": "title", "type": "String"}]},
            ],
            "relationships": [
                {"from": "Repository", "to": "Task", "type": "association", "source_multiplicity": "1", "target_multiplicity": "0..*"},
            ],
        }

        result = modeler.build(srs_json={"feature_name": "X"}, sds_json={"design_views": {}}, class_specification_json=specification)

        repository = next(c for c in result["classes"] if c["name"] == "Repository")
        task = next(c for c in result["classes"] if c["name"] == "Task")
        relationship = result["relationships"][0]

        assert relationship["from"] == repository["id"]
        assert relationship["to"] == task["id"]
        assert relationship["source_multiplicity"] == "1"
        assert relationship["target_multiplicity"] == "0..*"

    def test_relationship_referencing_unknown_class_is_skipped_not_crashed(self):
        modeler = ArchitectureClassModeler()
        specification = {
            "classes": [{"name": "Controller", "stereotype": "control"}],
            "relationships": [
                {"from": "Controller", "to": "GhostClass", "type": "dependency"},
            ],
        }

        result = modeler.build(srs_json={"feature_name": "X"}, sds_json={"design_views": {}}, class_specification_json=specification)

        assert result["relationships"] == []

    def test_preserves_llm_provided_visibility(self):
        modeler = ArchitectureClassModeler()
        specification = {
            "classes": [{
                "name": "Task", "stereotype": "entity",
                "attributes": [{"name": "password", "type": "String", "visibility": "-"}],
            }],
        }

        result = modeler.build(srs_json={"feature_name": "X"}, sds_json={"design_views": {}}, class_specification_json=specification)

        attribute = result["classes"][0]["attributes"][0]
        assert attribute["visibility"] == "-"

    def test_invalid_stereotype_defaults_to_entity(self):
        modeler = ArchitectureClassModeler()
        specification = {"classes": [{"name": "Weird", "stereotype": "not_a_real_stereotype"}]}

        result = modeler.build(srs_json={"feature_name": "X"}, sds_json={"design_views": {}}, class_specification_json=specification)

        assert result["classes"][0]["stereotype"] == "entity"


class TestFallbackPath:
    def test_fallback_produces_a_complete_diagram(self):
        modeler = ArchitectureClassModeler()
        srs_json = {
            "feature_name": "Login",
            "functional_requirements": [{"id": "FR-001", "description": "The system must authenticate a user."}],
        }
        sds_json = {"design_views": {}}

        result = modeler.build(srs_json=srs_json, sds_json=sds_json, class_specification_json={})

        assert result["diagram_title"] == "Login Class Diagram"
        names = {c["name"] for c in result["classes"]}
        assert "LoginController" in names
        assert "LoginService" in names

    def test_fallback_association_relationship_carries_default_multiplicity(self):
        """
        The fallback path's Repository -> Entity association must carry a
        default UML multiplicity (closing the confirmed multiplicity gap
        for the last-resort path too, not just the LLM-driven path).
        """
        modeler = ArchitectureClassModeler()
        srs_json = {
            "feature_name": "Login",
            "functional_requirements": [{"id": "FR-001", "description": "x"}],
            "data_requirements": [{"data_point": "Session", "description": "Stores session token and expiry"}],
        }
        sds_json = {"design_views": {}}

        result = modeler.build(srs_json=srs_json, sds_json=sds_json, class_specification_json={})

        associations = [r for r in result["relationships"] if r["type"] == "association"]
        assert associations
        for relationship in associations:
            assert relationship["source_multiplicity"]
            assert relationship["target_multiplicity"]
