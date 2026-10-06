"""
Unit tests for ClassDiagramValidator's new quality checks added by the
Class Diagram rewrite (app/agents/architecture_agent/class_validator.py):
_validate_class_quality (anemic DTO/entity detection) and
_validate_multiplicity (UML cardinality notation). No LLM involved.

No pre-existing class validator test file existed before this rewrite.
"""

from app.agents.architecture_agent.class_validator import (
    ClassDiagramValidationError,
    ClassDiagramValidator,
)


def _base_class_json(classes: list[dict], relationships: list[dict]) -> dict:
    return {
        "diagram_title": "Test Class Diagram",
        "classes": classes,
        "relationships": relationships,
    }


class TestAnemicClassDetection:
    def test_entity_with_no_attributes_is_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{"id": "C1", "name": "Task", "stereotype": "entity", "attributes": [], "operations": []}],
            relationships=[],
        )

        try:
            validator.validate({}, class_json)
            assert False, "expected ClassDiagramValidationError for an anemic entity"
        except ClassDiagramValidationError as error:
            assert "no attributes" in str(error)

    def test_dto_with_only_placeholder_id_attribute_is_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "TaskResponse", "stereotype": "dto",
                "attributes": [{"name": "id", "type": "String", "visibility": "+"}],
                "operations": [],
            }],
            relationships=[],
        )

        try:
            validator.validate({}, class_json)
            assert False, "expected ClassDiagramValidationError for a placeholder-only dto"
        except ClassDiagramValidationError as error:
            assert "placeholder attributes" in str(error)

    def test_entity_with_real_attributes_is_not_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "Task", "stereotype": "entity",
                "attributes": [
                    {"name": "title", "type": "String", "visibility": "-"},
                    {"name": "description", "type": "String", "visibility": "-"},
                ],
                "operations": [],
            }],
            relationships=[],
        )

        validator.validate({}, class_json)

    def test_mixed_real_and_generic_attributes_is_not_flagged(self):
        """
        A genuine mix of a real field alongside an "id" field is fine -- only
        an ALL-placeholder attribute set is a real quality problem.
        """
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "Task", "stereotype": "entity",
                "attributes": [
                    {"name": "id", "type": "String", "visibility": "+"},
                    {"name": "title", "type": "String", "visibility": "-"},
                ],
                "operations": [],
            }],
            relationships=[],
        )

        validator.validate({}, class_json)

    def test_control_class_with_no_attributes_is_not_flagged(self):
        """
        Controllers/services legitimately have no attributes -- the anemic
        check is scoped to dto/entity only.
        """
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "TaskController", "stereotype": "control",
                "attributes": [],
                "operations": [{"name": "searchTasks", "parameters": [], "return_type": "Response", "visibility": "+"}],
            }],
            relationships=[],
        )

        validator.validate({}, class_json)


class TestOperationRequiredForBehavioralStereotypes:
    def test_control_class_with_no_operations_is_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{"id": "C1", "name": "TaskController", "stereotype": "control", "attributes": [], "operations": []}],
            relationships=[],
        )

        try:
            validator.validate({}, class_json)
            assert False, "expected ClassDiagramValidationError for a control class with no operations"
        except ClassDiagramValidationError as error:
            assert "no operations" in str(error)

    def test_dto_with_no_operations_is_not_flagged(self):
        # dto/entity classes legitimately have zero operations -- the operation-required check is
        # scoped to control/service/repository only, mirroring the anemic-attribute check's own
        # symmetric scoping (dto/entity only).
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "TaskDto", "stereotype": "dto",
                "attributes": [{"name": "title", "type": "String", "visibility": "+"}],
                "operations": [],
            }],
            relationships=[],
        )

        validator.validate({}, class_json)


class TestStereotypeNamingConsistency:
    def test_controller_named_class_labeled_entity_is_flagged(self):
        # The exact, already-documented real bug this check exists to catch: a class named
        # "*Controller" mislabeled as an entity.
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "TaskSearchController", "stereotype": "entity",
                "attributes": [{"name": "title", "type": "String", "visibility": "-"}],
                "operations": [],
            }],
            relationships=[],
        )

        try:
            validator.validate({}, class_json)
            assert False, "expected ClassDiagramValidationError for a Controller-named entity"
        except ClassDiagramValidationError as error:
            assert "named like a controller" in str(error)
            assert "expected control" in str(error)

    def test_controller_named_class_labeled_control_is_not_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "TaskSearchController", "stereotype": "control", "attributes": [],
                "operations": [{"name": "searchTasks", "parameters": [], "return_type": "Response", "visibility": "+"}],
            }],
            relationships=[],
        )

        validator.validate({}, class_json)

    def test_service_named_class_may_be_control_or_service(self):
        # Both "control" and "service" are legitimate, defensible stereotype choices for a
        # *Service-named class (a real architectural-style choice, not an error) -- only
        # "*Controller"/"*Handler" is narrowly restricted to "control" alone.
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "TaskSearchService", "stereotype": "control", "attributes": [],
                "operations": [{"name": "findTasks", "parameters": [], "return_type": "List", "visibility": "+"}],
            }],
            relationships=[],
        )

        validator.validate({}, class_json)

    def test_repository_named_class_labeled_dto_is_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "TaskRepository", "stereotype": "dto",
                "attributes": [{"name": "title", "type": "String", "visibility": "+"}],
                "operations": [],
            }],
            relationships=[],
        )

        try:
            validator.validate({}, class_json)
            assert False, "expected ClassDiagramValidationError for a Repository-named dto"
        except ClassDiagramValidationError as error:
            assert "named like a repository" in str(error)

    def test_class_name_with_no_recognized_suffix_is_never_flagged(self):
        # A genuine domain entity name (no role suffix at all) is never subject to this check --
        # it only fires when the name itself already claims a specific role.
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[{
                "id": "C1", "name": "Item", "stereotype": "control", "attributes": [],
                "operations": [{"name": "process", "parameters": [], "return_type": "void", "visibility": "+"}],
            }],
            relationships=[],
        )

        validator.validate({}, class_json)


class TestMultiplicityValidation:
    def test_association_missing_multiplicity_is_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[
                {"id": "C1", "name": "Repository", "stereotype": "repository", "attributes": [], "operations": []},
                {"id": "C2", "name": "Task", "stereotype": "entity", "attributes": [{"name": "title", "type": "String", "visibility": "-"}], "operations": []},
            ],
            relationships=[{"from": "C1", "to": "C2", "type": "association", "label": "manages"}],
        )

        try:
            validator.validate({}, class_json)
            assert False, "expected ClassDiagramValidationError for missing multiplicity"
        except ClassDiagramValidationError as error:
            assert "missing UML multiplicity" in str(error)

    def test_association_with_non_standard_multiplicity_is_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[
                {"id": "C1", "name": "Repository", "stereotype": "repository", "attributes": [], "operations": []},
                {"id": "C2", "name": "Task", "stereotype": "entity", "attributes": [{"name": "title", "type": "String", "visibility": "-"}], "operations": []},
            ],
            relationships=[{
                "from": "C1", "to": "C2", "type": "association", "label": "manages",
                "source_multiplicity": "many", "target_multiplicity": "some",
            }],
        )

        try:
            validator.validate({}, class_json)
            assert False, "expected ClassDiagramValidationError for non-standard multiplicity notation"
        except ClassDiagramValidationError as error:
            assert "non-standard multiplicity" in str(error)

    def test_association_with_valid_multiplicity_is_not_flagged(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[
                {
                    "id": "C1", "name": "Repository", "stereotype": "repository", "attributes": [],
                    "operations": [{"name": "save", "parameters": [], "return_type": "void", "visibility": "+"}],
                },
                {"id": "C2", "name": "Task", "stereotype": "entity", "attributes": [{"name": "title", "type": "String", "visibility": "-"}], "operations": []},
            ],
            relationships=[{
                "from": "C1", "to": "C2", "type": "association", "label": "manages",
                "source_multiplicity": "1", "target_multiplicity": "0..*",
            }],
        )

        validator.validate({}, class_json)

    def test_dependency_relationship_is_exempt_from_multiplicity(self):
        validator = ClassDiagramValidator()
        class_json = _base_class_json(
            classes=[
                {
                    "id": "C1", "name": "TaskController", "stereotype": "control", "attributes": [],
                    "operations": [{"name": "searchTasks", "parameters": [], "return_type": "Response", "visibility": "+"}],
                },
                {
                    "id": "C2", "name": "TaskService", "stereotype": "service", "attributes": [],
                    "operations": [{"name": "findTasks", "parameters": [], "return_type": "List", "visibility": "+"}],
                },
            ],
            relationships=[{"from": "C1", "to": "C2", "type": "dependency", "label": "uses"}],
        )

        validator.validate({}, class_json)
