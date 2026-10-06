"""
Unit tests for ArchitectureUseCasePlantUMLBuilder (app/agents/architecture_agent/
usecase_builder.py). No LLM involved -- pure string-rendering logic.

First dedicated builder test file for this diagram -- nothing else in this codebase directly
exercised the actual PlantUML keyword output before this, which matters specifically for the new
actor <<system>> stereotype rendering and for confirming generalization rendering (already
implemented in this builder, but previously a structurally dead code path since nothing upstream
ever produced a "generalization"-typed relationship for it to render -- see usecase_modeler.py's
own _build_relationships).
"""

from app.agents.architecture_agent.usecase_builder import ArchitectureUseCasePlantUMLBuilder


def _base_usecase_json(actors: list[dict], use_cases: list[dict], relationships: list[dict]) -> dict:
    return {
        "diagram_title": "Test Use Case Diagram",
        "system_boundary": "Test Feature",
        "actors": actors,
        "use_cases": use_cases,
        "relationships": relationships,
        "notes": [],
    }


class TestActorStereotypeRendering:
    def test_system_actor_gets_the_system_stereotype_suffix(self):
        builder = ArchitectureUseCasePlantUMLBuilder()
        usecase_json = _base_usecase_json(
            actors=[{"id": "ACT-001", "name": "Payment Gateway", "type": "secondary", "stereotype": "system"}],
            use_cases=[{"id": "UC-001", "name": "Process Payment", "category": "main"}],
            relationships=[],
        )

        output = builder.build(usecase_json)

        assert 'actor "Payment Gateway" as ACT_001 <<external system>>' in output

    def test_human_actor_gets_no_stereotype_suffix(self):
        builder = ArchitectureUseCasePlantUMLBuilder()
        usecase_json = _base_usecase_json(
            actors=[{"id": "ACT-001", "name": "Customer", "type": "primary", "stereotype": "human"}],
            use_cases=[{"id": "UC-001", "name": "Process Payment", "category": "main"}],
            relationships=[],
        )

        output = builder.build(usecase_json)

        assert 'actor "Customer" as ACT_001' in output
        assert "<<system>>" not in output

    def test_actor_with_no_stereotype_field_at_all_gets_no_suffix(self):
        # Backward compatible with any real diagram saved before this field existed.
        builder = ArchitectureUseCasePlantUMLBuilder()
        usecase_json = _base_usecase_json(
            actors=[{"id": "ACT-001", "name": "Customer", "type": "primary"}],
            use_cases=[{"id": "UC-001", "name": "Process Payment", "category": "main"}],
            relationships=[],
        )

        output = builder.build(usecase_json)

        assert 'actor "Customer" as ACT_001' in output
        assert "<<system>>" not in output


class TestGeneralizationRendering:
    def test_use_case_generalization_renders_the_hollow_triangle_arrow(self):
        builder = ArchitectureUseCasePlantUMLBuilder()
        usecase_json = _base_usecase_json(
            actors=[],
            use_cases=[
                {"id": "UC-001", "name": "Pay By Card", "category": "main"},
                {"id": "UC-002", "name": "Make Payment", "category": "main"},
            ],
            relationships=[{"from": "UC-001", "to": "UC-002", "type": "generalization", "label": ""}],
        )

        output = builder.build(usecase_json)

        assert "UC_001 --|> UC_002" in output

    def test_actor_generalization_renders_the_hollow_triangle_arrow(self):
        builder = ArchitectureUseCasePlantUMLBuilder()
        usecase_json = _base_usecase_json(
            actors=[
                {"id": "ACT-001", "name": "Admin", "type": "secondary", "stereotype": "human"},
                {"id": "ACT-002", "name": "User", "type": "primary", "stereotype": "human"},
            ],
            use_cases=[{"id": "UC-001", "name": "Manage Account", "category": "main"}],
            relationships=[{"from": "ACT-001", "to": "ACT-002", "type": "generalization", "label": ""}],
        )

        output = builder.build(usecase_json)

        assert "ACT_001 --|> ACT_002" in output


class TestExistingRelationshipRenderingStillCorrect:
    def test_association_include_extend_still_render_correctly(self):
        builder = ArchitectureUseCasePlantUMLBuilder()
        usecase_json = _base_usecase_json(
            actors=[{"id": "ACT-001", "name": "Customer", "type": "primary", "stereotype": "human"}],
            use_cases=[
                {"id": "UC-001", "name": "Search Tasks", "category": "main"},
                {"id": "UC-002", "name": "Validate Query", "category": "included"},
                {"id": "UC-003", "name": "Save Recent Search", "category": "extension"},
            ],
            relationships=[
                {"from": "ACT-001", "to": "UC-001", "type": "association", "label": ""},
                {"from": "UC-001", "to": "UC-002", "type": "include", "label": ""},
                {"from": "UC-003", "to": "UC-001", "type": "extend", "label": ""},
            ],
        )

        output = builder.build(usecase_json)

        assert "ACT_001 -- UC_001" in output
        assert "UC_001 .> UC_002 : <<include>>" in output
        assert "UC_003 .> UC_001 : <<extend>>" in output

    def test_system_boundary_box_contains_use_cases_with_actors_outside(self):
        builder = ArchitectureUseCasePlantUMLBuilder()
        usecase_json = _base_usecase_json(
            actors=[{"id": "ACT-001", "name": "Customer", "type": "primary", "stereotype": "human"}],
            use_cases=[{"id": "UC-001", "name": "Search Tasks", "category": "main"}],
            relationships=[],
        )

        output = builder.build(usecase_json)
        lines = output.splitlines()

        actor_index = next(i for i, line in enumerate(lines) if line.startswith("actor "))
        boundary_index = next(i for i, line in enumerate(lines) if line.startswith('rectangle "'))
        usecase_index = next(i for i, line in enumerate(lines) if "usecase " in line)

        assert actor_index < boundary_index < usecase_index
