"""
Architecture Agent Class Diagram Modeler.

Purpose:
Build a standard UML Class Diagram model from approved SRS and SDS data.

Design principle:
- Feature-independent.
- Does not hardcode Login, Cart, Payment, LMS, or any specific feature.
- Builds classes from SDS logical, interface, and data views.
- Shows structure only, not behaviour flow.

UML class rules applied:
- Classes represent structural design elements: boundary/control/service/repository/entity/DTO/external provider.
- Attributes are fields from request/response/data models.
- Operations are derived from API endpoints and functional responsibilities.
- Relationships show dependency/association between design classes.
- NFRs, risks, constraints, and use case names are not created as classes.
"""

from __future__ import annotations

import re
from typing import Any

# Matches a single per-field SRS `data_requirements` string, e.g. "price (number, required,
# minimum value 0.01)" -> ("price", "number, required, minimum value 0.01"). Duplicated from
# architecture_agent/agent.py's identical DATA_FIELD_DEFINITION_PATTERN rather than imported --
# agent.py imports ArchitectureClassModeler from this module, so importing back would be
# circular. requirement_schema.py documents data_requirements as "the concrete fields of ONE
# coherent entity"; without this, raw SRS `data_requirements` used to be enumerated as one
# separate entity per item (the same real, confirmed bug fixed in agent.py's _build_data_view).
_DATA_FIELD_DEFINITION_PATTERN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)")


class ArchitectureClassModeler:
    """
    Builds class_diagram_json from SRS and SDS.
    """

    COMMON_FIELDS = {
        "email": ("email", "String"),
        "password": ("password", "String"),
        "hashed password": ("passwordHash", "String"),
        "hash": ("passwordHash", "String"),
        "token": ("token", "String"),
        "jwt": ("token", "String"),
        "role": ("role", "String"),
        "status": ("status", "String"),
        "name": ("name", "String"),
        "username": ("username", "String"),
        "price": ("price", "Number"),
        "amount": ("amount", "Number"),
        "quantity": ("quantity", "Number"),
        "date": ("date", "Date"),
    }

    def build(
        self,
        srs_json: dict[str, Any],
        sds_json: dict[str, Any],
        class_specification_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        specification = class_specification_json or {}
        classes_spec = specification.get("classes")

        if isinstance(classes_spec, list) and classes_spec:
            # Primary path: the LLM supplied a real specification -- trust
            # its classes/attributes/operations/relationships directly
            # rather than re-deriving a generic fixed skeleton (the
            # confirmed source of today's placeholder "id: String"-only
            # DTOs/entities regardless of what the feature actually needs).
            classes, relationships = self._build_from_specification(specification, srs_json)
        else:
            # Last-resort fallback: no usable specification at all (every
            # generation rung including repair failed).
            classes, relationships = self._build_fallback_classes_and_relationships(srs_json, sds_json)

        classes = self._dedupe_classes(classes)
        relationships = self._filter_relationships(relationships, classes)

        feature_name = self._feature_name(srs_json, sds_json)
        return {
            "diagram_title": specification.get("diagram_title") or f"{feature_name} Class Diagram",
            "feature_name": feature_name,
            "classes": classes,
            "relationships": relationships,
            "traceability": self._build_traceability(classes, relationships),
            "rules_applied": [
                "Classes represent real, feature-specific structural design elements.",
                "DTO classes come from real request and response models.",
                "Entity classes come from real data entities and requirements.",
                "Controller, service, and repository classes represent feature-level layered responsibilities.",
                "Association/aggregation/composition relationships carry real UML multiplicities.",
                "NFRs, risks, constraints, and architecture notes are not generated as classes.",
            ],
        }

    def _build_from_specification(
        self,
        specification: dict[str, Any],
        srs_json: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Build classes/relationships directly from the LLM's own
        specification -- trusted as-is (only deterministic id assignment,
        name-to-id resolution, and light field/operation normalization), no
        regex/keyword derivation. This is the primary path whenever the LLM
        supplied a real specification; _build_fallback_classes_and_relationships
        remains only as the last-resort path for a genuinely empty specification.
        """

        allowed_stereotypes = {"control", "service", "repository", "dto", "entity", "external"}
        allowed_relationship_types = {
            "association", "dependency", "aggregation", "composition", "inheritance", "generalization"
        }

        classes: list[dict[str, Any]] = []
        name_to_id: dict[str, str] = {}
        stereotype_counters: dict[str, int] = {}

        for item in specification.get("classes", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue

            stereotype = str(item.get("stereotype", "")).strip().lower()
            if stereotype not in allowed_stereotypes:
                stereotype = "entity"

            stereotype_counters[stereotype] = stereotype_counters.get(stereotype, 0) + 1
            class_id = f"CLS_{stereotype.upper()}_{stereotype_counters[stereotype]:03d}"
            class_name = self._safe_class_name(name)

            attributes = [
                record for record in (
                    self._attribute_record(field) for field in self._as_list(item.get("attributes"))
                ) if record
            ]
            operations = [
                record for record in (
                    self._operation_record(operation) for operation in self._as_list(item.get("operations"))
                ) if record
            ]

            classes.append({
                "id": class_id,
                "name": class_name,
                "stereotype": stereotype,
                "attributes": attributes,
                "operations": operations,
                "related_requirements": [str(v) for v in item.get("related_requirements", []) or [] if v],
            })
            name_to_id[self._normalize(name)] = class_id

        relationships: list[dict[str, Any]] = []
        for item in specification.get("relationships", []):
            if not isinstance(item, dict):
                continue

            source_id = name_to_id.get(self._normalize(str(item.get("from", ""))))
            target_id = name_to_id.get(self._normalize(str(item.get("to", ""))))
            if not source_id or not target_id:
                continue

            relation_type = str(item.get("type", "")).strip().lower()
            if relation_type not in allowed_relationship_types:
                relation_type = "association"

            relationships.append({
                "from": source_id,
                "to": target_id,
                "type": relation_type,
                "label": str(item.get("label", "")).strip(),
                "source_multiplicity": str(item.get("source_multiplicity", "")).strip(),
                "target_multiplicity": str(item.get("target_multiplicity", "")).strip(),
            })

        return classes, relationships

    def _attribute_record(self, field: Any) -> dict[str, Any] | None:
        if not isinstance(field, dict):
            return None
        name = str(field.get("name", "")).strip()
        if not name:
            return None
        return {
            "name": self._camel(name),
            "type": self._normalize_type(field.get("type", "String")),
            "visibility": str(field.get("visibility", "+")).strip() or "+",
        }

    def _operation_record(self, operation: Any) -> dict[str, Any] | None:
        if not isinstance(operation, dict):
            return None
        name = str(operation.get("name", "")).strip()
        if not name:
            return None
        parameters = [
            text for text in (self._parameter_text(param) for param in self._as_list(operation.get("parameters")))
            if text
        ]
        return {
            "name": name,
            "parameters": parameters,
            "return_type": self._normalize_type(operation.get("return_type", "void")),
            "visibility": str(operation.get("visibility", "+")).strip() or "+",
        }

    def _parameter_text(self, parameter: Any) -> str:
        """
        A real agentic run showed the LLM sometimes authors a parameter as a
        rich {"name", "type"} object rather than a plain string -- render
        either shape as a clean "name: type" (or just "name"/"type" alone)
        instead of a raw Python dict repr like "{'name': 'x', 'type': 'Y'}".
        """
        if isinstance(parameter, dict):
            name = str(parameter.get("name", "")).strip()
            param_type = str(parameter.get("type", "")).strip()
            if name and param_type:
                return f"{name}: {param_type}"
            return name or param_type
        return str(parameter).strip()

    def _build_fallback_classes_and_relationships(
        self,
        srs_json: dict[str, Any],
        sds_json: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Build classes/relationships the old way (fallback path only -- see
        _build_from_specification for the primary, LLM-trusting path).

        Every feature gets the same fixed Controller/Service/Repository/DTO
        skeleton here, with keyword-guessed attributes when the SDS's
        request/response models or data entities arrive as free text -- this
        is exactly the "static/deterministic" limitation the LLM-driven path
        exists to fix, kept only as a last resort for when the specification
        is genuinely empty.
        """

        feature_name = self._feature_name(srs_json, sds_json)
        feature_pascal = self._pascal(feature_name)
        design_views = sds_json.get("design_views", {}) if isinstance(sds_json, dict) else {}
        interface_view = design_views.get("interface_view", {}) if isinstance(design_views, dict) else {}
        data_view = design_views.get("data_view", {}) if isinstance(design_views, dict) else {}

        api_endpoints = self._as_list(interface_view.get("api_endpoints"))
        request_models = self._as_list(interface_view.get("request_models"))
        response_models = self._as_list(interface_view.get("response_models"))
        data_entities = self._as_list(data_view.get("data_entities"))
        functional_requirements = self._as_list(srs_json.get("functional_requirements"))
        data_requirements = self._as_list(srs_json.get("data_requirements"))
        output_requirements = self._as_list(srs_json.get("output_requirements"))
        validation_rules = self._as_list(srs_json.get("validation_rules"))

        classes: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        controller_id = "CLS_CONTROLLER"
        service_id = "CLS_SERVICE"
        repository_id = "CLS_REPOSITORY"

        classes.append({
            "id": controller_id,
            "name": f"{feature_pascal}Controller",
            "stereotype": "control",
            "attributes": [],
            "operations": self._controller_operations(api_endpoints, feature_name),
            "related_requirements": self._ids(functional_requirements),
        })

        classes.append({
            "id": service_id,
            "name": f"{feature_pascal}Service",
            "stereotype": "service",
            "attributes": [],
            "operations": self._service_operations(functional_requirements, feature_name),
            "related_requirements": self._ids(functional_requirements),
        })

        relationships.append({
            "from": controller_id,
            "to": service_id,
            "type": "dependency",
            "label": "uses",
        })

        dto_class_ids = []
        for index, model in enumerate(request_models, start=1):
            class_id = f"CLS_REQUEST_{index:03d}"
            dto_class_ids.append(class_id)
            classes.append({
                "id": class_id,
                "name": self._safe_class_name(self._extract_name(model) or f"{feature_pascal}Request"),
                "stereotype": "dto",
                "attributes": self._fields_from_model(model),
                "operations": [],
                "related_requirements": self._related(model, self._ids(validation_rules) + self._ids(functional_requirements)),
            })
            relationships.append({
                "from": controller_id,
                "to": class_id,
                "type": "dependency",
                "label": "accepts",
            })

        for index, model in enumerate(response_models, start=1):
            class_id = f"CLS_RESPONSE_{index:03d}"
            dto_class_ids.append(class_id)
            classes.append({
                "id": class_id,
                "name": self._safe_class_name(self._extract_name(model) or f"{feature_pascal}Response"),
                "stereotype": "dto",
                "attributes": self._fields_from_model(model) or self._fields_from_requirements(output_requirements),
                "operations": [],
                "related_requirements": self._related(model, self._ids(output_requirements)),
            })
            relationships.append({
                "from": controller_id,
                "to": class_id,
                "type": "dependency",
                "label": "returns",
            })

        entity_ids = []
        # data_entities (from an already-built data_view) may legitimately contain multiple
        # real, distinct entities -- iterate those as-is. Only the raw-SRS data_requirements
        # fallback (used when data_view has no entities at all) needs consolidating: it's a
        # flat list of per-FIELD strings describing one entity, not a list of separate entities.
        entity_records = data_entities or self._consolidate_data_requirements(
            data_requirements, feature_pascal
        )
        for index, entity in enumerate(entity_records, start=1):
            class_id = f"CLS_ENTITY_{index:03d}"
            entity_ids.append(class_id)
            entity_name = self._extract_name(entity) or f"{feature_pascal}Data"
            entity_text = self._text(entity)
            classes.append({
                "id": class_id,
                "name": self._safe_class_name(entity_name),
                "stereotype": "entity",
                "attributes": self._fields_from_entity(entity) or self._infer_fields_from_text(entity_text),
                "operations": [],
                "related_requirements": self._related(entity, self._ids(data_requirements) + self._ids(functional_requirements)),
            })

        if entity_ids:
            classes.append({
                "id": repository_id,
                "name": f"{feature_pascal}Repository",
                "stereotype": "repository",
                "attributes": [],
                "operations": [
                    {"name": "findRequiredData", "parameters": [], "return_type": "Entity", "visibility": "+"},
                    {"name": "saveChanges", "parameters": [], "return_type": "void", "visibility": "+"},
                ],
                "related_requirements": self._ids(data_requirements) + self._ids(functional_requirements),
            })
            relationships.append({
                "from": service_id,
                "to": repository_id,
                "type": "dependency",
                "label": "uses",
            })
            for entity_id in entity_ids:
                relationships.append({
                    "from": repository_id,
                    "to": entity_id,
                    "type": "association",
                    "label": "manages",
                    # A repository manages zero or many records of an entity --
                    # a safe, standard default cardinality, not a guess.
                    "source_multiplicity": "1",
                    "target_multiplicity": "0..*",
                })

        if self._needs_security_provider(srs_json):
            provider_id = "CLS_EXTERNAL_SECURITY"
            classes.append({
                "id": provider_id,
                "name": "SecurityTokenProvider",
                "stereotype": "external",
                "attributes": [],
                "operations": [
                    {"name": "generateToken", "parameters": ["payload"], "return_type": "String", "visibility": "+"}
                ],
                "related_requirements": self._ids([item for item in functional_requirements if self._has_any(self._text(item), ["jwt", "token", "generate"])]),
            })
            relationships.append({
                "from": service_id,
                "to": provider_id,
                "type": "dependency",
                "label": "generates",
            })

        return classes, relationships

    # ------------------------------------------------------------------
    # Class construction helpers
    # ------------------------------------------------------------------

    def _controller_operations(self, endpoints: list[Any], feature_name: str) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        if not endpoints:
            return [{"name": self._operation_name(f"handle {feature_name}"), "parameters": ["request"], "return_type": "Response", "visibility": "+"}]

        for endpoint in endpoints:
            method = str(endpoint.get("method", "handle") if isinstance(endpoint, dict) else "handle")
            path = str(endpoint.get("endpoint", feature_name) if isinstance(endpoint, dict) else feature_name)
            operations.append({
                "name": self._operation_name(f"{method} {path}"),
                "parameters": ["request"],
                "return_type": "Response",
                "visibility": "+",
            })
        # A real run surfaced design_views.interface_view.api_endpoints
        # containing the exact same endpoint as two separate dict entries
        # (an upstream architecture-plan data-quality issue) -- dedupe here
        # the same way _service_operations already dedupes its own result,
        # so a duplicate endpoint entry doesn't produce a duplicate operation.
        return self._dedupe_operations(operations)

    def _service_operations(self, requirements: list[Any], feature_name: str) -> list[dict[str, Any]]:
        operations: list[dict[str, Any]] = []
        for item in requirements:
            text = self._text(item)
            name = self._operation_from_requirement(text)
            if name:
                operations.append({
                    "name": name,
                    "parameters": ["input"],
                    "return_type": "Result",
                    "visibility": "+",
                })
        if not operations:
            operations.append({"name": self._operation_name(f"process {feature_name}"), "parameters": ["input"], "return_type": "Result", "visibility": "+"})
        return self._dedupe_operations(operations)

    def _fields_from_model(self, model: Any) -> list[dict[str, Any]]:
        if not isinstance(model, dict):
            return []
        fields: list[dict[str, Any]] = []
        for field in self._as_list(model.get("fields")):
            fields.append(self._field_record(field))
        return self._dedupe_fields(fields)

    def _fields_from_entity(self, entity: Any) -> list[dict[str, Any]]:
        if not isinstance(entity, dict):
            return []
        fields: list[dict[str, Any]] = []
        for field in self._as_list(entity.get("fields")):
            record = self._field_record(field)
            if not self._looks_like_bad_inferred_field(record["name"]):
                fields.append(record)
        return self._dedupe_fields(fields)

    def _consolidate_data_requirements(
        self, data_requirements: list[Any], feature_pascal: str
    ) -> list[dict[str, Any]]:
        """
        Raw SRS `data_requirements` is a flat list of per-FIELD strings describing ONE entity
        (e.g. "price (number, required, minimum value 0.01)") -- aggregates them into a single
        entity record instead of one entity per item. Returns [] when data_requirements is
        empty, matching the "nothing to build" contract the caller already expects.
        """
        if not data_requirements:
            return []

        fields = []
        for item in data_requirements:
            text = self._text(item)
            parsed = self._parse_field_definition(text)
            fields.append(parsed or {"name": self._camel(text), "type": "String", "visibility": "+"})

        return [{"name": f"{feature_pascal}Data", "fields": fields}]

    def _parse_field_definition(self, description: str) -> dict[str, Any] | None:
        """
        Parses "name (details)" (e.g. "price (number, required, minimum value 0.01)") into a
        _field_record-compatible dict. Returns None when the text doesn't match this shape.
        """
        match = _DATA_FIELD_DEFINITION_PATTERN.match(description)
        if not match:
            return None

        field_name, detail = match.group(1), match.group(2).lower()

        if any(keyword in detail for keyword in ("number", "integer", "float", "decimal")):
            field_type = "Number"
        elif any(keyword in detail for keyword in ("timestamp", "date")):
            field_type = "Date"
        elif "boolean" in detail or re.search(r"\bbool\b", detail):
            field_type = "Boolean"
        else:
            field_type = "String"

        return {"name": self._camel(field_name), "type": field_type, "visibility": "+"}

    def _fields_from_requirements(self, requirements: list[Any]) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        for item in requirements:
            name = self._extract_name(item) or self._infer_field_name(self._text(item))
            if name:
                fields.append({
                    "name": self._camel(name),
                    "type": self._field_type(item),
                    "visibility": "+",
                })
        return self._dedupe_fields(fields)

    def _infer_fields_from_text(self, text: str) -> list[dict[str, Any]]:
        lowered = self._normalize(text)
        fields: list[dict[str, Any]] = []

        for keyword, (field_name, field_type) in self.COMMON_FIELDS.items():
            if keyword in lowered:
                fields.append({"name": field_name, "type": field_type, "visibility": "+"})

        if not fields:
            fields.append({"name": "id", "type": "String", "visibility": "+"})

        return self._dedupe_fields(fields)

    def _field_record(self, field: Any) -> dict[str, Any]:
        if isinstance(field, dict):
            name = field.get("name") or field.get("field") or field.get("data_point") or "field"
            return {
                "name": self._camel(str(name)),
                "type": self._normalize_type(field.get("type", "String")),
                "visibility": "+",
            }
        return {"name": self._camel(str(field)), "type": "String", "visibility": "+"}

    # ------------------------------------------------------------------
    # Traceability and filtering
    # ------------------------------------------------------------------

    def _build_traceability(self, classes: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> list[dict[str, str]]:
        traceability: list[dict[str, str]] = []
        for class_item in classes:
            for req_id in class_item.get("related_requirements", []):
                traceability.append({
                    "source_id": req_id,
                    "source_type": self._guess_source_type(req_id),
                    "mapped_to": class_item.get("name", class_item.get("id")),
                    "mapping_type": "class",
                })
        for relationship in relationships:
            for req_id in relationship.get("related_requirements", []):
                traceability.append({
                    "source_id": req_id,
                    "source_type": self._guess_source_type(req_id),
                    "mapped_to": f"{relationship.get('from')} -> {relationship.get('to')}",
                    "mapping_type": "relationship",
                })
        return traceability

    def _dedupe_classes(self, classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_name: dict[str, dict[str, Any]] = {}
        for class_item in classes:
            name = self._safe_class_name(class_item.get("name", "Class"))
            key = self._normalize(name)
            class_item["name"] = name
            if key not in by_name:
                by_name[key] = class_item
                continue
            by_name[key]["attributes"] = self._dedupe_fields(by_name[key].get("attributes", []) + class_item.get("attributes", []))
            by_name[key]["operations"] = self._dedupe_operations(by_name[key].get("operations", []) + class_item.get("operations", []))
            by_name[key]["related_requirements"] = self._unique(by_name[key].get("related_requirements", []) + class_item.get("related_requirements", []))
        return list(by_name.values())

    def _filter_relationships(self, relationships: list[dict[str, Any]], classes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        class_ids = {item.get("id") for item in classes}
        result = []
        seen = set()
        for relationship in relationships:
            if relationship.get("from") not in class_ids or relationship.get("to") not in class_ids:
                continue
            key = (relationship.get("from"), relationship.get("to"), relationship.get("type"), relationship.get("label"))
            if key in seen:
                continue
            seen.add(key)
            result.append(relationship)
        return result

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------

    def _feature_name(self, srs_json: dict[str, Any], sds_json: dict[str, Any]) -> str:
        return srs_json.get("feature_name") or sds_json.get("document_control", {}).get("feature_name") or "Feature"

    def _needs_security_provider(self, srs_json: dict[str, Any]) -> bool:
        return self._has_any(str(srs_json), ["jwt", "token", "otp", "secret", "credential"])

    def _operation_from_requirement(self, text: str) -> str:
        cleaned = self._remove_noise(text)
        match = re.search(r"\b(authenticate|validate|generate|return|create|update|delete|calculate|process|initiate|provide|retrieve|store|save)\b\s+(.+)", cleaned, flags=re.IGNORECASE)
        if match:
            return self._operation_name(f"{match.group(1)} {self._short_topic(match.group(2))}")
        return self._operation_name(cleaned)

    def _operation_name(self, text: str) -> str:
        words = re.findall(r"[a-zA-Z0-9]+", str(text))[:5]
        if not words:
            return "performAction"
        first = words[0].lower()
        rest = "".join(word[:1].upper() + word[1:] for word in words[1:])
        return first + rest

    def _safe_class_name(self, text: str) -> str:
        parts = re.findall(r"[a-zA-Z0-9]+", str(text))
        if not parts:
            return "DesignClass"
        return "".join(part[:1].upper() + part[1:] for part in parts[:5])

    def _camel(self, text: str) -> str:
        class_name = self._safe_class_name(text)
        return class_name[:1].lower() + class_name[1:]

    def _pascal(self, text: str) -> str:
        return self._safe_class_name(text)

    def _short_topic(self, text: str) -> str:
        cleaned = self._remove_noise(text)
        words = re.findall(r"[a-zA-Z0-9]+", cleaned)[:4]
        return " ".join(words) if words else "result"

    def _remove_noise(self, text: str) -> str:
        cleaned = str(text).strip()
        cleaned = re.sub(r"^(the system must|system must|the user must|user must|must|shall|should)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(allow|enable|let|provide|support)\s+", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip(" .")

    def _normalize(self, text: str) -> str:
        text = str(text).lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _has_any(self, text: str, words: list[str]) -> bool:
        normalized = self._normalize(text)
        return any(word in normalized for word in words)

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        return value if isinstance(value, list) else [value]

    def _extract_name(self, item: Any) -> str:
        if isinstance(item, dict):
            for key in ["name", "field", "data_point", "endpoint", "title"]:
                if item.get(key):
                    return str(item[key]).strip()
            return ""
        return str(item).strip()

    def _text(self, item: Any) -> str:
        if isinstance(item, dict):
            for key in ["description", "payload", "purpose", "expectation", "risk", "mitigation", "name", "field", "endpoint"]:
                if item.get(key):
                    return str(item[key])
            return str(item)
        return str(item)

    def _ids(self, items: Any) -> list[str]:
        ids: list[str] = []
        for item in self._as_list(items):
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
        return self._unique(ids)

    def _related(self, item: Any, fallback: list[str]) -> list[str]:
        if isinstance(item, dict):
            related = item.get("related_requirements")
            if isinstance(related, list) and related:
                return [str(value) for value in related]
            if item.get("id"):
                return [str(item["id"])]
        return fallback

    def _field_type(self, item: Any) -> str:
        if isinstance(item, dict):
            return self._normalize_type(item.get("type", "String"))
        return "String"

    def _normalize_type(self, value: Any) -> str:
        text = str(value or "String")
        lowered = text.lower()
        if "jwt" in lowered or "string" in lowered or "email" in lowered or "password" in lowered:
            return "String"
        if "number" in lowered or "int" in lowered or "decimal" in lowered:
            return "Number"
        if "bool" in lowered:
            return "Boolean"
        if "date" in lowered:
            return "Date"
        return text[:1].upper() + text[1:]

    def _infer_field_name(self, text: str) -> str:
        lowered = self._normalize(text)
        for keyword, (field_name, _field_type) in self.COMMON_FIELDS.items():
            if keyword in lowered:
                return field_name
        return ""

    def _looks_like_bad_inferred_field(self, name: str) -> bool:
        normalized = self._normalize(name)
        bad_fragments = ["requires secure storage", "rieval of hashed", "retrieval of hashed"]
        return any(fragment in normalized for fragment in bad_fragments) or len(name) > 35

    def _dedupe_fields(self, fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for field in fields:
            name = str(field.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(field)
        return result

    def _dedupe_operations(self, operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for operation in operations:
            name = str(operation.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(operation)
        return result

    def _unique(self, items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            value = str(item).strip()
            if value and value not in result:
                result.append(value)
        return result

    def _guess_source_type(self, requirement_id: str) -> str:
        requirement_id = str(requirement_id)
        if requirement_id.startswith("FR"):
            return "FR"
        if requirement_id.startswith("AC"):
            return "AC"
        if requirement_id.startswith("VR"):
            return "VR"
        if requirement_id.startswith("NFR"):
            return "NFR"
        return "Requirement"
