"""
Regression tests for a real, confirmed bug: the Architecture Agent's deterministic
last-resort fallback used to treat EACH item in an SRS's `data_requirements` list as its own
separate entity, and EACH item in `api_expectations` silently defaulted to a GET endpoint.

Root cause, confirmed against the real, live "Item Listing (CRUD)" feature
(`feature_94701501`): `data_requirements` is documented (requirement_agent/prompt.py, and
requirement_schema.py's own field description) as "the concrete fields of ONE coherent entity",
e.g. 9 plain strings like "price (number, required, minimum value 0.01)" describing the 9
fields of one "Item" entity -- but `_build_data_view` looped `enumerate(data_requirements,
start=1)` and created a SEPARATE entity per item, producing 9 disconnected one-field Mongoose
collections in the real generated code instead of one real Item model. `_build_interface_view`
had the identical shape of bug: `api_expectations` strings like "POST /api/items" were never
parsed for their HTTP method, so `item.get("method", "GET")` on a `{"description": ...}` record
(from `_as_record_list`'s flattening) always defaulted to GET -- 4 real CRUD endpoints collapsed
into 4 duplicate GETs in the real saved architecture plan.

`class_modeler.py`'s deterministic fallback (`_build_fallback_classes_and_relationships`) had
the exact same per-item-entity bug in its raw-`data_requirements` fallback branch
(`data_entities or data_requirements`).

No real LLM/HTTP calls -- these are direct, synchronous unit tests against the plain
data-transformation methods.
"""

from app.agents.architecture_agent.agent import ArchitectureAgent
from app.agents.architecture_agent.class_modeler import ArchitectureClassModeler

# The real 9 data_requirements strings from feature_94701501's actual enhanced SRS.
REAL_ITEM_DATA_REQUIREMENTS = [
    "id (string, auto-generated, unique identifier)",
    "name (string, required, non-empty)",
    "description (string, optional)",
    "price (number, required, minimum value 0.01)",
    "quantity (integer, required, minimum value 0)",
    "category (string, required, non-empty)",
    "imageUrl (string, optional, valid URL format)",
    "createdAt (timestamp, auto-generated on creation)",
    "updatedAt (timestamp, auto-updated on every edit)",
]

# The real 4 api_expectations strings from the same SRS.
REAL_ITEM_API_EXPECTATIONS = [
    "POST /api/items",
    "GET /api/items",
    "PUT /api/items/{id}",
    "DELETE /api/items/{id}",
]


class TestArchitectureAgentDataView:
    def test_multi_field_data_requirements_produce_exactly_one_entity(self):
        agent = ArchitectureAgent()
        data_requirements = [{"description": text} for text in REAL_ITEM_DATA_REQUIREMENTS]

        data_view = agent._build_data_view(
            feature_name="Item Listing (CRUD)",
            data_requirements=data_requirements,
            validation_rules=[],
            functional_requirements=[],
        )

        entities = data_view["data_entities"]
        assert len(entities) == 1, f"Expected exactly 1 entity, got {len(entities)}: {[e['name'] for e in entities]}"

    def test_the_one_entity_has_all_nine_real_fields_with_correct_types(self):
        agent = ArchitectureAgent()
        data_requirements = [{"description": text} for text in REAL_ITEM_DATA_REQUIREMENTS]

        data_view = agent._build_data_view(
            feature_name="Item Listing (CRUD)",
            data_requirements=data_requirements,
            validation_rules=[],
            functional_requirements=[],
        )

        fields = {field["name"]: field for field in data_view["data_entities"][0]["fields"]}
        assert set(fields.keys()) == {
            "id", "name", "description", "price", "quantity",
            "category", "imageUrl", "createdAt", "updatedAt",
        }
        assert fields["price"]["type"] == "Number"
        assert fields["quantity"]["type"] == "Number"
        assert fields["createdAt"]["type"] == "Date"
        assert fields["updatedAt"]["type"] == "Date"
        assert fields["name"]["type"] == "String"
        assert fields["price"]["required"] is True
        assert fields["description"]["required"] is False

    def test_empty_data_requirements_still_falls_back_to_one_named_entity(self):
        agent = ArchitectureAgent()

        data_view = agent._build_data_view(
            feature_name="Some Feature",
            data_requirements=[],
            validation_rules=[],
            functional_requirements=[],
        )

        assert len(data_view["data_entities"]) == 1
        assert data_view["data_entities"][0]["name"] == "SomeFeatureData"

    def test_unparseable_data_requirement_falls_back_to_inferred_fields_not_dropped(self):
        agent = ArchitectureAgent()
        data_requirements = [{"description": "Free-text note about storage with no parens shape"}]

        data_view = agent._build_data_view(
            feature_name="Notes",
            data_requirements=data_requirements,
            validation_rules=[],
            functional_requirements=[],
        )

        assert len(data_view["data_entities"]) == 1
        # _infer_fields_from_text is the existing fallback for non-matching text -- still
        # produces something, never an empty/dropped entity.
        assert isinstance(data_view["data_entities"][0]["fields"], list)

    def test_parse_field_definition_infers_boolean_and_required(self):
        agent = ArchitectureAgent()

        parsed = agent._parse_field_definition("isActive (boolean, required)")
        assert parsed == {"name": "isActive", "type": "Boolean", "required": True}

    def test_parse_field_definition_returns_none_for_non_matching_text(self):
        agent = ArchitectureAgent()
        assert agent._parse_field_definition("just a sentence with no parens") is None


class TestArchitectureAgentInterfaceView:
    def test_all_four_crud_endpoints_get_their_real_method_and_path(self):
        agent = ArchitectureAgent()
        api_expectations = [{"description": text} for text in REAL_ITEM_API_EXPECTATIONS]

        interface_view = agent._build_interface_view(
            feature_name="Item Listing (CRUD)",
            api_expectations=api_expectations,
            input_requirements=[],
            output_requirements=[],
            functional_requirements=[],
        )

        endpoints = {(e["method"], e["endpoint"]) for e in interface_view["api_endpoints"]}
        assert endpoints == {
            ("POST", "/api/items"),
            ("GET", "/api/items"),
            ("PUT", "/api/items/{id}"),
            ("DELETE", "/api/items/{id}"),
        }

    def test_already_structured_method_and_endpoint_keys_are_not_overridden(self):
        agent = ArchitectureAgent()
        api_expectations = [
            {"endpoint": "/api/custom", "method": "PATCH", "description": "POST /api/items"},
        ]

        interface_view = agent._build_interface_view(
            feature_name="X",
            api_expectations=api_expectations,
            input_requirements=[],
            output_requirements=[],
            functional_requirements=[],
        )

        assert interface_view["api_endpoints"][0]["method"] == "PATCH"
        assert interface_view["api_endpoints"][0]["endpoint"] == "/api/custom"

    def test_unparseable_description_still_defaults_to_get(self):
        agent = ArchitectureAgent()
        api_expectations = [{"description": "Support searching items"}]

        interface_view = agent._build_interface_view(
            feature_name="X",
            api_expectations=api_expectations,
            input_requirements=[],
            output_requirements=[],
            functional_requirements=[],
        )

        assert interface_view["api_endpoints"][0]["method"] == "GET"

    def test_parse_endpoint_definition_is_case_insensitive_on_method(self):
        agent = ArchitectureAgent()
        assert agent._parse_endpoint_definition("delete /api/items/{id}") == ("DELETE", "/api/items/{id}")

    def test_parse_endpoint_definition_returns_none_without_a_leading_method(self):
        agent = ArchitectureAgent()
        assert agent._parse_endpoint_definition("Fetches all items") is None


class TestClassModelerDataRequirementsConsolidation:
    def test_consolidate_data_requirements_produces_one_entity_with_all_fields(self):
        modeler = ArchitectureClassModeler()

        entities = modeler._consolidate_data_requirements(REAL_ITEM_DATA_REQUIREMENTS, "ItemListingCRUD")

        assert len(entities) == 1
        assert entities[0]["name"] == "ItemListingCRUDData"
        field_names = {f["name"] for f in entities[0]["fields"]}
        assert field_names == {
            "id", "name", "description", "price", "quantity",
            "category", "imageUrl", "createdAt", "updatedAt",
        }

    def test_consolidate_data_requirements_returns_empty_for_empty_input(self):
        modeler = ArchitectureClassModeler()
        assert modeler._consolidate_data_requirements([], "Feature") == []

    def test_build_fallback_end_to_end_produces_one_entity_class_not_nine(self):
        """Full build() call through the real fallback path (no class_specification_json),
        the same call shape used when every LLM generation/repair rung has failed."""
        modeler = ArchitectureClassModeler()
        srs_json = {
            "feature_name": "Item Listing (CRUD)",
            "data_requirements": REAL_ITEM_DATA_REQUIREMENTS,
            "functional_requirements": [],
            "output_requirements": [],
            "validation_rules": [],
        }
        sds_json = {"design_views": {}}

        result = modeler.build(srs_json, sds_json, class_specification_json=None)

        entity_classes = [c for c in result["classes"] if c["stereotype"] == "entity"]
        assert len(entity_classes) == 1, (
            f"Expected exactly 1 entity class, got {len(entity_classes)}: "
            f"{[c['name'] for c in entity_classes]}"
        )
        assert len(entity_classes[0]["attributes"]) == 9

    def test_data_entities_from_data_view_are_never_collapsed(self):
        """When data_view.data_entities already has real, distinct entities (the normal,
        non-fallback shape), the loop must NOT run them through the raw-string consolidation --
        multiple genuinely separate entities stay separate."""
        modeler = ArchitectureClassModeler()
        srs_json = {
            "feature_name": "Orders",
            "data_requirements": ["should be ignored since data_entities is populated"],
            "functional_requirements": [],
            "output_requirements": [],
            "validation_rules": [],
        }
        sds_json = {
            "design_views": {
                "data_view": {
                    "data_entities": [
                        {"name": "Order", "fields": [{"name": "id", "type": "String"}]},
                        {"name": "OrderItem", "fields": [{"name": "id", "type": "String"}]},
                    ]
                }
            }
        }

        result = modeler.build(srs_json, sds_json, class_specification_json=None)

        entity_classes = [c for c in result["classes"] if c["stereotype"] == "entity"]
        assert len(entity_classes) == 2
        assert {c["name"] for c in entity_classes} == {"Order", "OrderItem"}
