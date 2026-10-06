"""
Architecture Agent Use Case Modeler.

Purpose:
Build a standard UML Use Case model from approved SRS/SDS data.

Design principle:
This file is feature-independent. It does not hardcode Login, Cart, Payment,
LMS, or any other feature. It uses generic UML rules:
- actors come from external roles/systems
- main use case represents the feature goal
- mandatory supporting behaviour becomes <<include>>
- optional/alternative/error/recovery behaviour becomes <<extend>>
- constraints, NFRs, risks, and architecture decisions stay in the SDS, not as
  visible notes in the use case diagram
"""

from __future__ import annotations

import re
from typing import Any


class ArchitectureUseCaseModeler:
    """
    Builds usecase_analysis_json and final usecase_json.

    The LLM may provide an intermediate usecase_specification_json, but the final
    UML model is normalized here using deterministic, feature-independent rules.
    """

    TECHNICAL_ACTOR_WORDS = [
        "database", "mongodb", "mysql", "postgres", "collection", "table",
        "api", "endpoint", "controller", "server", "backend", "frontend",
        "react", "node", "express", "jwt", "token", "library", "middleware",
        "component", "page", "form", "repository", "schema", "model",
        "service layer", "next.js", "nextjs", "typescript", "server component",
        "route handler", "app router",
    ]

    ERROR_WORDS = [
        "invalid", "error", "failed", "failure", "fail", "prevent", "denied",
        "unauthorized", "forbidden", "not found", "incorrect", "exception",
        "timeout", "unavailable",
    ]

    def build(
        self,
        srs_json: dict[str, Any],
        sds_json: dict[str, Any],
        usecase_specification_json: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Build usecase_analysis_json and usecase_json.
        """

        specification = self._normalize_specification(
            srs_json=srs_json,
            sds_json=sds_json,
            specification=usecase_specification_json or {},
        )

        actors = self._build_actors(specification, srs_json, sds_json)

        if specification["use_cases"]:
            # Primary path: the LLM supplied a real use_cases[] list -- trust
            # its naming/categorization directly rather than re-deriving use
            # cases from raw SRS sentences via regex (the confirmed source of
            # garbled/fragmented names).
            main_use_cases, included_use_cases, extension_use_cases = (
                self._build_use_cases_from_specification(specification, srs_json)
            )
        else:
            # Last-resort fallback: no usable specification at all (every
            # generation rung including repair failed). See the fallback
            # naming helpers below for how this stays honest/minimal instead
            # of aggressively fabricating names from raw requirement text.
            main_use_cases = self._build_main_use_cases(specification, srs_json)
            included_use_cases = self._build_included_use_cases(specification, srs_json)
            extension_use_cases = self._build_extension_use_cases(specification, srs_json)

        # Dedup across included+extension together, not each list separately
        # -- a real run surfaced two differently-categorized entries (one
        # included, one extension) that both named the same underlying
        # behaviour (confirmed: both truncated to the identical fallback
        # name "Find Specific Tasks Quickly Using" for a Task Search
        # feature). Per-list dedup alone cannot catch a duplicate that
        # spans a category boundary.
        included_use_cases, extension_use_cases = self._merge_near_duplicates_across_categories(
            included_use_cases, extension_use_cases
        )

        main_use_cases, included_use_cases, extension_use_cases = self._renumber_use_cases(
            main_use_cases=main_use_cases,
            included_use_cases=included_use_cases,
            extension_use_cases=extension_use_cases,
        )

        relationships = self._build_relationships(
            actors=actors,
            main_use_cases=main_use_cases,
            included_use_cases=included_use_cases,
            extension_use_cases=extension_use_cases,
        )

        use_cases: list[dict[str, Any]] = []
        use_cases.extend(main_use_cases)
        use_cases.extend(included_use_cases)
        use_cases.extend(extension_use_cases)

        # Standard project decision: no visual UML notes.
        # NFRs/constraints/risks are documented in the SDS design views.
        notes: list[dict[str, Any]] = []

        usecase_json = {
            "system_boundary": specification["system_boundary"],
            "diagram_title": specification["diagram_title"],
            "actors": actors,
            "use_cases": use_cases,
            "relationships": relationships,
            "notes": notes,
            "standards_notes": [
                "Actors are external roles or external systems outside the system boundary.",
                "Use cases are user-goal behaviours inside the system boundary.",
                "<<include>> is used only for mandatory supporting behaviour.",
                "<<extend>> is used only for optional, alternative, recovery, or exception behaviour.",
                "Constraints, NFRs, risks, and architecture decisions are kept in the SDS, not rendered as UML notes.",
            ],
        }

        usecase_analysis_json = self._build_analysis(
            specification=specification,
            actors=actors,
            main_use_cases=main_use_cases,
            included_use_cases=included_use_cases,
            extension_use_cases=extension_use_cases,
            relationships=relationships,
        )

        return usecase_analysis_json, usecase_json

    # ------------------------------------------------------------------
    # Model building
    # ------------------------------------------------------------------

    def _normalize_specification(
        self,
        srs_json: dict[str, Any],
        sds_json: dict[str, Any],
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Normalize LLM specification and fill missing boilerplate from SRS/SDS.

        `use_cases` (the current, trusted schema -- see build()) is passed
        through as-is when the LLM supplied one. The legacy
        `primary_use_cases`/`included_behaviours`/`extension_behaviours`/
        `exception_flows` keys are kept only as a defensive secondary read
        (for an older-shaped specification) -- deliberately NOT populated
        with synthesized defaults here anymore, so a genuinely empty
        specification is never silently disguised as "the LLM already
        provided something usable." That synthesis now lives only in the
        deterministic fallback path in build().
        """

        feature_name = self._get_feature_name(srs_json, sds_json)

        use_cases_raw = specification.get("use_cases")
        if not isinstance(use_cases_raw, list):
            use_cases_raw = []

        return {
            "system_boundary": specification.get("system_boundary") or f"{feature_name} Feature",
            "diagram_title": specification.get("diagram_title") or f"{feature_name} Use Case Diagram",
            "actors": specification.get("actors") or specification.get("primary_actors") or srs_json.get("user_roles", []),
            "use_cases": use_cases_raw,
            "primary_use_cases": specification.get("primary_use_cases") or specification.get("main_use_cases") or [],
            "included_behaviours": specification.get("included_behaviours") or specification.get("mandatory_included_behaviours") or [],
            "extension_behaviours": specification.get("extension_behaviours") or specification.get("alternative_flows") or [],
            "exception_flows": specification.get("exception_flows") or [],
        }

    def _build_actors(
        self,
        specification: dict[str, Any],
        srs_json: dict[str, Any],
        sds_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build actors from SRS roles and SDS context.

        Each candidate carries a stereotype ("human" | "system" -- the internal field value;
        renders as the clearer <<external system>> tag, see usecase_builder.py) and an optional
        `generalizes` (parent actor name, for a real "Admin is-a User"-style actor
        generalization -- resolved to a real relationship in _build_relationships). The LLM's
        own `specification["actors"]` entries (dicts, may carry an explicit stereotype/
        generalizes) are considered first, so an explicit LLM choice wins on a name collision
        with an auto-inferred candidate below; SRS user_roles / SDS context_view.actors default
        to "human"; SDS context_view.external_systems default to "system" (an external system a
        feature integrates with is exactly the non-human-actor case this stereotype exists for).
        """

        actor_records: list[dict[str, str]] = []

        for candidate in self._as_list(specification.get("actors")):
            name = self._extract_name(candidate)
            if not name or self._is_technical_actor(name):
                continue
            stereotype = "human"
            generalizes = ""
            if isinstance(candidate, dict):
                if str(candidate.get("stereotype", "")).strip().lower() == "system":
                    stereotype = "system"
                generalizes = str(candidate.get("generalizes", "")).strip()
            actor_records.append({"name": self._clean_actor_name(name), "stereotype": stereotype, "generalizes": generalizes})

        for candidate in self._as_list(srs_json.get("user_roles")):
            name = self._extract_name(candidate)
            if not name or self._is_technical_actor(name):
                continue
            actor_records.append({"name": self._clean_actor_name(name), "stereotype": "human", "generalizes": ""})

        context_view = self._get_design_view(sds_json, "context_view")

        for candidate in self._as_list(context_view.get("actors")):
            name = self._extract_name(candidate)
            if not name or self._is_technical_actor(name):
                continue
            actor_records.append({"name": self._clean_actor_name(name), "stereotype": "human", "generalizes": ""})

        for candidate in self._as_list(context_view.get("external_systems")):
            name = self._extract_name(candidate)
            if not name or self._is_technical_actor(name):
                continue
            actor_records.append({"name": self._clean_actor_name(name), "stereotype": "system", "generalizes": ""})

        seen_names_lower: set[str] = set()
        deduped: list[dict[str, str]] = []
        for record in actor_records:
            key = record["name"].lower()
            if key in seen_names_lower:
                continue
            seen_names_lower.add(key)
            deduped.append(record)

        if not deduped:
            deduped = [{"name": "User", "stereotype": "human", "generalizes": ""}]

        actors = []
        for index, record in enumerate(deduped, start=1):
            actors.append({
                "id": f"ACT-{index:03d}",
                "name": record["name"],
                "type": "primary" if index == 1 else "secondary",
                "stereotype": record["stereotype"],
                "generalizes": record["generalizes"],
                "description": f"{record['name']} interacts with the feature to achieve a user goal.",
            })

        return actors

    def _build_use_cases_from_specification(
        self,
        specification: dict[str, Any],
        srs_json: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Build main/included/extension use-case lists directly from the LLM's
        own use_cases[] list -- trusted as-is (only light name cleanup via
        _new_use_case), no regex-based sentence-mining. This is the primary
        path whenever the LLM supplied a real use_cases list;
        _build_main_use_cases/_build_included_use_cases/_build_extension_use_cases
        remain only as the last-resort fallback for a genuinely empty
        specification.
        """

        main: list[dict[str, Any]] = []
        included: list[dict[str, Any]] = []
        extension: list[dict[str, Any]] = []

        for item in specification.get("use_cases", []):
            if not isinstance(item, dict):
                continue

            name = self._extract_name(item)
            if not name:
                continue

            description = self._extract_description(item) or name
            related = self._extract_related_ids(item)
            category = str(item.get("type") or item.get("category") or "included").strip().lower()
            if category not in {"main", "included", "extension"}:
                category = "included"

            participating_actors_raw = item.get("participating_actors", [])
            if not isinstance(participating_actors_raw, list):
                participating_actors_raw = [participating_actors_raw] if participating_actors_raw else []
            participating_actors = [str(v).strip() for v in participating_actors_raw if str(v).strip()]
            generalizes = str(item.get("generalizes", "")).strip()

            use_case = self._new_use_case(name, description, category, related, participating_actors, generalizes)

            if category == "main":
                main.append(use_case)
            elif category == "extension":
                extension.append(use_case)
            else:
                included.append(use_case)

        # Guarantee exactly one main use case even if the LLM mis-categorized
        # -- promote the first available entry rather than silently
        # producing a diagram with no main goal at all. Update the
        # "category" field itself, not just which list it lives in, so
        # downstream category filters (validator, tests, PlantUML builder)
        # see it consistently.
        if not main and included:
            promoted = included.pop(0)
            promoted["category"] = "main"
            main.append(promoted)
        elif not main and extension:
            promoted = extension.pop(0)
            promoted["category"] = "main"
            main.append(promoted)
        elif not main:
            feature_name = self._get_feature_name(srs_json, {})
            main.append(self._new_use_case(
                feature_name,
                f"Main user goal for the {feature_name} feature.",
                "main",
                self._all_requirement_ids(srs_json),
            ))

        # A feature-level diagram normally has exactly one main goal, but if
        # the LLM produced more than one "main" entry, only collapse the
        # ones that are actually the SAME goal sloppily double-marked
        # (overlapping or empty related_requirements) -- a second main entry
        # whose related_requirements are genuinely DISJOINT from every
        # already-kept main is a real, confirmed case of two independent
        # top-level capabilities (e.g. "Add Item" and "List Items") and is
        # kept as an independent sibling instead. Forcing it into
        # "included" would make _build_relationships draw a false
        # <<include>> edge claiming one always happens as part of the
        # other -- exactly the "not the clearest way to represent" class of
        # modeling problem this whole pass exists to avoid.
        if len(main) > 1:
            kept_main: list[dict[str, Any]] = [main[0]]
            for candidate in main[1:]:
                candidate_related = set(candidate.get("related_requirements", []))
                collides_with_kept = any(
                    not candidate_related
                    or not set(kept.get("related_requirements", []))
                    or candidate_related & set(kept.get("related_requirements", []))
                    for kept in kept_main
                )
                if collides_with_kept:
                    candidate["category"] = "included"
                    included.insert(0, candidate)
                else:
                    kept_main.append(candidate)
            main = kept_main

        return main, included, extension

    def _build_main_use_cases(
        self,
        specification: dict[str, Any],
        srs_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build the main use case (fallback path only -- see
        _build_use_cases_from_specification for the primary, LLM-trusting
        path).

        Named cleanly from feature_name only -- no business-goal regex
        mangling. A feature name (e.g. "Login", "Task Search") is already a
        reasonable, human-authored use case name; synthesizing something
        "better" from a raw business_goal sentence via regex phrase-surgery
        is exactly the failure mode this last-resort path exists to avoid.
        """

        feature_name = self._get_feature_name(srs_json, {})
        primary_items = self._as_list(specification.get("primary_use_cases"))

        if primary_items:
            item = primary_items[0]
            name = self._extract_name(item) or feature_name
            description = self._extract_description(item) or f"Main user goal for the {feature_name} feature."
            related = self._extract_related_ids(item) or self._all_requirement_ids(srs_json)
        else:
            name = feature_name
            description = self._get_text(srs_json, "business_goal") or f"Main user goal for the {feature_name} feature."
            related = self._all_requirement_ids(srs_json)

        return [{
            "id": "UC-001",
            "name": self._clean_use_case_name(name),
            "description": description,
            "category": "main",
            "related_requirements": related,
        }]

    def _build_included_use_cases(
        self,
        specification: dict[str, Any],
        srs_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build included use cases from mandatory behaviours the specification
        itself named (fallback path only). Names come from
        _build_fallback_supporting_use_case -- a user-story goal match, or
        one gentle truncation -- no multi-pass regex verb/topic extraction.

        Deliberately does NOT mechanically mint one included use case per raw
        validation_rules/functional_requirements SRS item anymore -- a real,
        confirmed bug (a genuine "Login and Signup" run produced 6 <<include>>
        relationships to garbled fragments like "Email Must Be In Valid" and
        "System Validates Input Both Fields," none of which are real,
        separate, user-observable use cases; a validation rule like "Email
        must be in a valid format" is a business rule, never a UML use case
        under any real modeling convention). _build_main_use_cases already
        seeds the main use case's own related_requirements with every FR/AC/
        VR id via _all_requirement_ids specifically so traceability coverage
        holds with zero use cases here -- this loop existed only to make the
        fallback diagram look "richer," at the direct cost of the user's own
        "keep it simple, accurate, and grounded" requirement.
        """

        result: list[dict[str, Any]] = []

        for item in self._as_list(specification.get("included_behaviours")):
            description = self._extract_description(item) or self._extract_name(item)
            if not description:
                continue
            related = self._extract_related_ids(item)
            name = self._extract_name(item) or self._build_fallback_supporting_use_case(item, srs_json)
            if name:
                result.append(self._new_use_case(name, description, "included", related))

        return result

    def _build_extension_use_cases(
        self,
        specification: dict[str, Any],
        srs_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """
        Build extension use cases from optional, alternative, recovery, and
        error flows the specification itself named (fallback path only).
        Names come from _build_fallback_supporting_use_case -- a user-story
        goal match, or one gentle truncation -- no multi-pass regex verb/
        topic extraction.

        Deliberately does NOT mechanically mint one extension use case per
        raw functional_requirement/acceptance_criterion SRS item anymore --
        see _build_included_use_cases' own docstring for the real, confirmed
        bug this mirrors (garbled fragments like "Invalid Login Credentials
        Wrong Email" turned into spurious <<extend>> relationships off a
        keyword match, not a real distinct behaviour). _build_main_use_cases
        already seeds the main use case's own related_requirements with
        every FR/AC/VR id via _all_requirement_ids, so traceability coverage
        holds with zero extension use cases here.
        """

        result: list[dict[str, Any]] = []

        extension_sources = []
        extension_sources.extend(self._as_list(specification.get("extension_behaviours")))
        extension_sources.extend(self._as_list(specification.get("exception_flows")))

        for item in extension_sources:
            description = self._extract_description(item) or self._extract_name(item)
            if not description:
                continue
            related = self._extract_related_ids(item)
            name = self._extract_name(item) or self._build_fallback_supporting_use_case(item, srs_json)
            if name:
                result.append(self._new_use_case(name, description, "extension", related))

        return result

    def _build_relationships(
        self,
        actors: list[dict[str, Any]],
        main_use_cases: list[dict[str, Any]],
        included_use_cases: list[dict[str, Any]],
        extension_use_cases: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Build UML relationships with correct direction.

        Actor-to-use-case associations are built per use case's own `participating_actors`
        (see _new_use_case) -- an actor is only associated with a use case it genuinely appears
        in, per agilemodeling.com's "indicate an association between an actor and a use case if
        the actor appears within the use case logic" rule, rather than the old behavior of
        hardwiring every actor to only the single main use case regardless of which sub-flow it
        actually participates in. A use case with no explicit participating_actors falls back to
        "every actor" ONLY if it's the main use case -- this preserves the exact prior behavior
        for the deterministic fallback path (which never sets participating_actors) and for any
        LLM output that omits the field, while an included/extension use case with no explicit
        actors simply gets no direct association (still reachable via its include/extend edge
        from the main use case, which is itself associated with every actor).

        Use-case-to-use-case and actor-to-actor generalization relationships are built from each
        record's own `generalizes` field (previously a structurally dead code path -- the
        renderer/validator already supported "generalization" as a relationship type, but nothing
        upstream ever produced one).

        When there is more than one main use case (two genuinely independent top-level
        capabilities -- see _build_use_cases_from_specification's own relaxed demotion logic), an
        included/extension use case's include/extend edge connects to whichever main use case it
        shares the most related_requirements overlap with (via _closest_main_use_case), not
        blindly to the first main -- falling back to the first main only when an item shares no
        requirement id with any of them.
        """

        if not main_use_cases:
            return []

        base_uc_id = main_use_cases[0]["id"]
        all_use_cases = main_use_cases + included_use_cases + extension_use_cases
        actor_name_to_id = {self._normalize_words(actor["name"]): actor["id"] for actor in actors}
        use_case_name_to_id = {self._normalize_words(uc["name"]): uc["id"] for uc in all_use_cases}

        relationships: list[dict[str, Any]] = []
        associated_pairs: set[tuple[str, str]] = set()

        def add_association(actor_id: str, use_case_id: str) -> None:
            key = (actor_id, use_case_id)
            if key in associated_pairs:
                return
            associated_pairs.add(key)
            relationships.append({
                "from": actor_id,
                "to": use_case_id,
                "type": "association",
                "label": "",
                "related_requirements": [],
            })

        for use_case in all_use_cases:
            matched_any = False
            for actor_name in use_case.get("participating_actors", []):
                actor_id = actor_name_to_id.get(self._normalize_words(actor_name))
                if actor_id:
                    add_association(actor_id, use_case["id"])
                    matched_any = True

            if not matched_any and use_case.get("category") == "main":
                for actor in actors:
                    add_association(actor["id"], use_case["id"])

        # Defensive: if nothing was associated at all (should not happen given the main-use-case
        # fallback above, but a real main_use_cases[0] always exists per the guard clause), fall
        # back to the original unconditional behavior rather than shipping a diagram with no
        # actor edges at all.
        if not relationships:
            for actor in actors:
                add_association(actor["id"], base_uc_id)

        for included in included_use_cases:
            relationships.append({
                "from": self._closest_main_use_case(included, main_use_cases) or base_uc_id,
                "to": included["id"],
                "type": "include",
                "label": "",
                "related_requirements": included.get("related_requirements", []),
            })

        for extension in extension_use_cases:
            relationships.append({
                "from": extension["id"],
                "to": self._closest_main_use_case(extension, main_use_cases) or base_uc_id,
                "type": "extend",
                "label": "",
                "related_requirements": extension.get("related_requirements", []),
            })

        for use_case in all_use_cases:
            parent_name = use_case.get("generalizes", "")
            if not parent_name:
                continue
            parent_id = use_case_name_to_id.get(self._normalize_words(parent_name))
            if parent_id and parent_id != use_case["id"]:
                relationships.append({
                    "from": use_case["id"],
                    "to": parent_id,
                    "type": "generalization",
                    "label": "",
                    "related_requirements": [],
                })

        for actor in actors:
            parent_name = actor.get("generalizes", "")
            if not parent_name:
                continue
            parent_id = actor_name_to_id.get(self._normalize_words(parent_name))
            if parent_id and parent_id != actor["id"]:
                relationships.append({
                    "from": actor["id"],
                    "to": parent_id,
                    "type": "generalization",
                    "label": "",
                    "related_requirements": [],
                })

        return relationships

    def _closest_main_use_case(
        self,
        use_case: dict[str, Any],
        main_use_cases: list[dict[str, Any]],
    ) -> str | None:
        """
        Which main use case's id an included/extension use case's include/extend edge should
        point at, when there is more than one main use case. Picks the main use case with the
        largest related_requirements overlap (a real, cheap signal of which top-level capability
        this item actually supports); returns None (caller falls back to the first main) when the
        item shares no requirement id with any main use case at all. With exactly one main use
        case (the overwhelmingly common case), this always resolves to that one main's id.
        """

        if len(main_use_cases) <= 1:
            return main_use_cases[0]["id"] if main_use_cases else None

        item_related = set(str(r) for r in use_case.get("related_requirements", []) if r)
        if not item_related:
            return main_use_cases[0]["id"]

        best_id = None
        best_overlap = 0
        for main_use_case in main_use_cases:
            overlap = len(item_related & set(main_use_case.get("related_requirements", [])))
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = main_use_case["id"]

        return best_id or main_use_cases[0]["id"]

    def _build_analysis(
        self,
        specification: dict[str, Any],
        actors: list[dict[str, Any]],
        main_use_cases: list[dict[str, Any]],
        included_use_cases: list[dict[str, Any]],
        extension_use_cases: list[dict[str, Any]],
        relationships: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build analysis JSON compatible with the existing agent output.
        """

        traceability: list[dict[str, Any]] = []

        for use_case in main_use_cases + included_use_cases + extension_use_cases:
            for req_id in use_case.get("related_requirements", []):
                traceability.append({
                    "source_id": req_id,
                    "source_type": self._guess_source_type(req_id),
                    "mapped_to": use_case.get("name", use_case.get("id")),
                    "mapping_type": "use_case",
                })

        for relationship in relationships:
            for req_id in relationship.get("related_requirements", []):
                traceability.append({
                    "source_id": req_id,
                    "source_type": self._guess_source_type(req_id),
                    "mapped_to": f"{relationship.get('from')} -> {relationship.get('to')}",
                    "mapping_type": relationship.get("type", "relationship"),
                })

        return {
            "feature_goal": main_use_cases[0].get("description", "") if main_use_cases else "",
            "primary_actors": [actor["name"] for actor in actors if actor.get("type") == "primary"],
            "secondary_actors": [actor["name"] for actor in actors if actor.get("type") != "primary"],
            "main_success_scenario": [uc.get("description", uc.get("name")) for uc in main_use_cases],
            "mandatory_included_behaviours": [
                {
                    "name": uc.get("name"),
                    "reason": uc.get("description"),
                    "related_requirements": uc.get("related_requirements", []),
                }
                for uc in included_use_cases
            ],
            "alternative_flows": [
                {
                    "name": uc.get("name"),
                    "condition": uc.get("description"),
                    "related_requirements": uc.get("related_requirements", []),
                }
                for uc in extension_use_cases
                if not self._has_any(self._normalize_words(uc.get("description", "")), self.ERROR_WORDS)
            ],
            "exception_flows": [
                {
                    "name": uc.get("name"),
                    "condition": uc.get("description"),
                    "related_requirements": uc.get("related_requirements", []),
                }
                for uc in extension_use_cases
                if self._has_any(self._normalize_words(uc.get("description", "")), self.ERROR_WORDS)
            ],
            "validation_flows": [
                {
                    "name": uc.get("name"),
                    "rule": uc.get("description"),
                    "related_requirements": uc.get("related_requirements", []),
                }
                for uc in included_use_cases
                if any(str(req).startswith("VR") for req in uc.get("related_requirements", []))
            ],
            "security_flows": [],
            "diagram_notes": [],
            "traceability": traceability,
        }

    # ------------------------------------------------------------------
    # Naming helpers
    # ------------------------------------------------------------------

    def _build_fallback_supporting_use_case(self, requirement: Any, srs_json: dict[str, Any]) -> str:
        """
        Name one fallback supporting (included/extension) use case for an
        SRS requirement/rule/criterion (fallback path only).

        Best-effort: look for a user story whose goal shares the most
        stemmed-token overlap with the requirement text, and use that
        already-clean, action-oriented `goal` phrase. When no story matches,
        fall back to one gentle pass over the requirement text itself via
        _clean_use_case_name (strip a common boilerplate lead-in, keep
        ~5 words, title-case) -- deliberately no multi-pass regex
        verb/topic extraction, which is what produced garbled names
        elsewhere in this module.
        """

        description = self._extract_description(requirement) or self._extract_name(requirement)
        if not description:
            return ""

        matched_goal = self._best_matching_user_story_goal(description, srs_json)
        return self._clean_use_case_name(matched_goal or description)

    def _best_matching_user_story_goal(self, requirement_text: str, srs_json: dict[str, Any]) -> str:
        requirement_stems = self._name_stems(requirement_text)
        if not requirement_stems:
            return ""

        best_goal = ""
        best_overlap = 0

        for story in self._as_list(srs_json.get("user_stories")):
            if not isinstance(story, dict):
                continue
            goal = str(story.get("goal", "")).strip()
            if not goal:
                continue
            goal_stems = self._name_stems(goal)
            if not goal_stems:
                continue
            overlap = len(requirement_stems & goal_stems)
            if overlap > best_overlap:
                best_overlap = overlap
                best_goal = goal

        return best_goal

    def _new_use_case(
        self,
        name: str,
        description: str,
        category: str,
        related: list[str],
        participating_actors: list[str] | None = None,
        generalizes: str = "",
    ) -> dict[str, Any]:
        return {
            "id": "",  # assigned later
            "name": self._clean_use_case_name(name),
            "description": description or name,
            "category": category,
            "related_requirements": self._unique([str(item) for item in related if item]),
            # Which actor(s) genuinely appear in THIS use case's own logic (see the
            # agilemodeling.com rule this satisfies) -- may be empty; _build_relationships
            # falls back to associating every actor with the main use case only, matching this
            # module's prior, always-safe default behavior.
            "participating_actors": self._unique([str(item) for item in (participating_actors or []) if item]),
            # Parent use case NAME for a real "significantly different business logic variant"
            # generalization relationship (resolved to a real relationship in
            # _build_relationships) -- empty string means no generalization.
            "generalizes": str(generalizes or "").strip(),
        }

    # Standalone filler words that would otherwise survive gentle truncation
    # as a leftover fragment (e.g. "Validate The User Credentials Against").
    # Mirrors usecase_validator.py's FRAGMENT_WORDS check -- kept as a
    # separate copy per this codebase's convention of not sharing files
    # between these deterministic agent modules.
    NAME_FILLER_WORDS = {
        "a", "an", "the", "this", "that", "these", "those", "their", "its",
        "his", "her", "our", "your", "my", "can", "could", "would", "should",
        "given", "when", "then",
    }

    def _clean_use_case_name(self, name: str) -> str:
        cleaned = self._remove_requirement_noise(name)
        cleaned = re.sub(r"[^a-zA-Z0-9 ]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        words = [word for word in cleaned.split() if word.lower() not in self.NAME_FILLER_WORDS]

        if not words:
            return "Perform Feature Action"

        # Keep visible UML labels short.
        cleaned = " ".join(words[:5])
        return self._title_case(cleaned)

    def _clean_actor_name(self, name: str) -> str:
        """
        Cleanup for an ACTOR name -- deliberately simpler than
        _clean_use_case_name above, since an actor is a noun phrase (a role
        or system), not an action, so there's no leading-verb convention to
        preserve. Strips trailing sentence punctuation (a real, confirmed bug:
        an LLM-authored actor name that reads as a full sentence, e.g. "An
        Image Hosting Solution To Store Uploaded Images."), strips leading
        filler words, and caps at 4 words to keep it a real name rather than
        a description.
        """

        cleaned = str(name).strip()
        cleaned = re.sub(r"[.!?]+$", "", cleaned).strip()
        cleaned = re.sub(r"[^a-zA-Z0-9 ]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        words = [word for word in cleaned.split() if word.lower() not in self.NAME_FILLER_WORDS]

        if not words:
            return "User"

        cleaned = " ".join(words[:4])
        return self._title_case(cleaned)

    # ------------------------------------------------------------------
    # Deduplication and IDs
    # ------------------------------------------------------------------

    # Small, purpose-scoped stopword set for name-similarity dedup only --
    # deliberately separate from usecase_validator.py's STOPWORDS (that one
    # is tuned for out-of-scope stem matching, a different job).
    DEDUP_STOPWORDS = {
        "the", "a", "an", "and", "or", "to", "via", "by", "for", "of", "in",
        "on", "with", "only", "is", "are", "be", "this", "that", "flow",
        "feature", "process", "scope", "out", "from", "as", "at", "using",
    }

    # Jaccard overlap threshold (on stemmed name tokens) above which two use
    # cases are treated as naming the same real behaviour.
    NAME_SIMILARITY_THRESHOLD = 0.6

    # Short, curated CRUD-shaped verb set for the two GENUINELY-DIFFERENT-
    # capability checks below (the merge guard here, and
    # usecase_validator.py's own _validate_no_conjoined_capabilities --
    # kept as a separate copy per this codebase's convention of not sharing
    # files between these deterministic agent modules). Deliberately short:
    # a broader list (search/filter/export/approve/etc.) is more likely to
    # legitimately co-occur in one real use case name (e.g. "Export Filtered
    # Report") and would false-positive.
    DISTINCT_CAPABILITY_VERBS = {
        "add": "add", "create": "add",
        "list": "list", "view": "list", "browse": "list",
        "update": "update", "edit": "update",
        "delete": "delete", "remove": "delete",
    }

    def _leading_capability_verb(self, name: str) -> str | None:
        words = re.findall(r"[a-zA-Z0-9]+", str(name).lower())
        if not words:
            return None
        return self.DISTINCT_CAPABILITY_VERBS.get(words[0])

    def _merge_near_duplicates(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Three passes, cheapest/most-certain first:
        1. Exact normalized-name match (today's original behaviour).
        2. Identical, non-empty related_requirements sets -- two use cases
           citing the exact same SRS requirement ids are almost certainly the
           same real behaviour regardless of wording (catches synonym-level
           duplicates like "Initiate Forgot Password Process" vs "Initiate
           Recovery Flow" citing the same FR, which no name-similarity
           metric would catch, since they share no meaningful stems).
        3. Stem/token Jaccard overlap on names above NAME_SIMILARITY_THRESHOLD
           (catches paraphrase-level near-duplicates the first two passes
           miss, e.g. differently-worded restatements of the same action).
        """
        merged = self._dedupe_by_exact_name(items)
        merged = self._dedupe_by_shared_requirements(merged)
        merged = self._dedupe_by_name_similarity(merged)
        return merged

    def _merge_near_duplicates_across_categories(
        self,
        included_use_cases: list[dict[str, Any]],
        extension_use_cases: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Run _merge_near_duplicates over included+extension combined, then
        split back by each surviving item's own "category" field -- a
        duplicate can span the include/extend boundary (two differently-
        categorized entries naming the same real behaviour), which per-list
        deduping alone cannot catch. When a duplicate does span the
        boundary, the first-seen item's category wins (included is listed
        first below, so an included/extension collision resolves to
        included -- the more conservative, mandatory-by-default choice).
        """

        combined = included_use_cases + extension_use_cases
        merged = self._merge_near_duplicates(combined)

        merged_included = [item for item in merged if item.get("category") != "extension"]
        merged_extension = [item for item in merged if item.get("category") == "extension"]

        return merged_included, merged_extension

    def _dedupe_by_exact_name(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        for item in items:
            name = self._clean_use_case_name(item.get("name", ""))
            if not name:
                continue
            key = self._normalize_words(name)

            if key not in merged:
                merged[key] = dict(item)
                merged[key]["name"] = name
                merged[key]["related_requirements"] = self._unique(item.get("related_requirements", []))
                continue

            merged[key] = self._merge_two_use_cases(merged[key], item)

        return list(merged.values())

    def _dedupe_by_shared_requirements(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Merge two entries citing the exact same related_requirements set --
        EXCEPT when their names each start with a DIFFERENT curated
        distinct-capability verb (see DISTINCT_CAPABILITY_VERBS), which is a
        real, confirmed sign they're two genuinely different capabilities
        (e.g. "Add Item" and "List Items") that just happen to share one
        broadly-worded SRS requirement id -- not the same behaviour. This
        guard is narrow on purpose: two entries sharing requirements with NO
        curated-verb mismatch (e.g. both start with "Initiate," the real
        password-reset/recovery-flow duplicate this pass exists to catch)
        still merge exactly as before.
        """
        result: list[dict[str, Any]] = []
        result_verbs: list[str | None] = []
        seen: list[tuple[frozenset, int]] = []

        for item in items:
            related = frozenset(str(r) for r in item.get("related_requirements", []) if r)
            item_verb = self._leading_capability_verb(item.get("name", ""))

            match_index = None
            if related:
                for existing, index in seen:
                    if existing != related:
                        continue
                    existing_verb = result_verbs[index]
                    if item_verb and existing_verb and item_verb != existing_verb:
                        continue
                    match_index = index
                    break

            if match_index is not None:
                result[match_index] = self._merge_two_use_cases(result[match_index], item)
                continue

            result.append(dict(item))
            result_verbs.append(item_verb)
            if related:
                seen.append((related, len(result) - 1))

        return result

    def _dedupe_by_name_similarity(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        result_stems: list[set[str]] = []

        for item in items:
            stems = self._name_stems(item.get("name", ""))

            match_index = None
            if stems:
                for index, existing_stems in enumerate(result_stems):
                    if not existing_stems:
                        continue
                    overlap = stems & existing_stems
                    union = stems | existing_stems
                    if union and len(overlap) / len(union) >= self.NAME_SIMILARITY_THRESHOLD:
                        match_index = index
                        break

            if match_index is not None:
                result[match_index] = self._merge_two_use_cases(result[match_index], item)
                continue

            result.append(dict(item))
            result_stems.append(stems)

        return result

    def _merge_two_use_cases(self, existing: dict[str, Any], new_item: dict[str, Any]) -> dict[str, Any]:
        existing = dict(existing)
        existing["related_requirements"] = self._unique(
            existing.get("related_requirements", []) + new_item.get("related_requirements", [])
        )
        existing["participating_actors"] = self._unique(
            existing.get("participating_actors", []) + new_item.get("participating_actors", [])
        )
        if not existing.get("generalizes") and new_item.get("generalizes"):
            existing["generalizes"] = new_item["generalizes"]

        existing_description = str(existing.get("description", ""))
        new_description = str(new_item.get("description", ""))
        if new_description and new_description not in existing_description:
            existing["description"] = (
                f"{existing_description} | {new_description}" if existing_description else new_description
            )

        return existing

    def _name_stems(self, name: str) -> set[str]:
        words = re.findall(r"[a-zA-Z0-9]+", str(name).lower())
        return {self._stem_word(word) for word in words if word not in self.DEDUP_STOPWORDS and len(word) >= 3}

    def _stem_word(self, word: str) -> str:
        word = word.lower()

        # Very small generic stemmer -- mirrors usecase_validator.py's own
        # _stem (kept as a separate copy per this codebase's convention of
        # not sharing files between these deterministic agent modules).
        if word.startswith("verif"):
            return "verif"
        if word.startswith("initiat"):
            return "initiat"

        for suffix in ["ations", "ation", "itions", "ition", "ments", "ment", "ing", "ed", "es", "s"]:
            if word.endswith(suffix) and len(word) > len(suffix) + 3:
                return word[: -len(suffix)]

        return word

    def _renumber_use_cases(
        self,
        main_use_cases: list[dict[str, Any]],
        included_use_cases: list[dict[str, Any]],
        extension_use_cases: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        counter = 1

        for collection in [main_use_cases, included_use_cases, extension_use_cases]:
            for use_case in collection:
                use_case["id"] = f"UC-{counter:03d}"
                counter += 1

        return main_use_cases, included_use_cases, extension_use_cases

    # ------------------------------------------------------------------
    # Generic helper methods
    # ------------------------------------------------------------------

    def _get_feature_name(self, srs_json: dict[str, Any], sds_json: dict[str, Any]) -> str:
        return (
            srs_json.get("feature_name")
            or sds_json.get("document_control", {}).get("feature_name")
            or sds_json.get("feature_name")
            or "Feature"
        )

    def _get_design_view(self, sds_json: dict[str, Any], view_name: str) -> dict[str, Any]:
        design_views = sds_json.get("design_views", {})
        view = design_views.get(view_name, {})
        return view if isinstance(view, dict) else {}

    def _get_text(self, data: dict[str, Any], key: str) -> str:
        value = data.get(key, "")
        if isinstance(value, str):
            return value.strip()
        return str(value).strip() if value is not None else ""

    def _as_list(self, value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _extract_name(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(
                item.get("name")
                or item.get("actor")
                or item.get("role")
                or item.get("title")
                or item.get("use_case")
                or ""
            ).strip()
        return str(item).strip()

    def _extract_description(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(
                item.get("description")
                or item.get("goal")
                or item.get("reason")
                or item.get("condition")
                or item.get("rule")
                or item.get("expectation")
                or item.get("payload")
                or item.get("risk")
                or item.get("mitigation")
                or ""
            ).strip()
        return str(item).strip()

    def _extract_id(self, item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("id", "")).strip()
        return ""

    def _extract_related_ids(self, item: Any) -> list[str]:
        if not isinstance(item, dict):
            return []
        related = item.get("related_requirements", [])
        if isinstance(related, list):
            return [str(value) for value in related if value]
        if related:
            return [str(related)]
        item_id = self._extract_id(item)
        return [item_id] if item_id else []

    def _collect_ids(self, items: list[Any]) -> list[str]:
        ids = []
        for item in self._as_list(items):
            item_id = self._extract_id(item)
            if item_id:
                ids.append(item_id)
        return self._unique(ids)

    def _all_requirement_ids(self, srs_json: dict[str, Any]) -> list[str]:
        """
        Every functional requirement, acceptance criterion, and validation
        rule id in this SRS -- used to seed the fallback main use case's own
        related_requirements so it alone can satisfy full FR/AC/VR
        traceability coverage (UseCaseQualityValidator._validate_traceability
        checks all three kinds unconditionally, but only functional
        requirements naturally become their own included/extension use
        cases in this deterministic fallback path -- an acceptance criterion
        with no error/optional wording, or a validation rule the LLM
        specification never echoed back, would otherwise never be cited
        anywhere and fail that check even though the fallback is supposed to
        always produce a passing model).
        """
        return self._unique(
            self._collect_ids(srs_json.get("functional_requirements", []))
            + self._collect_ids(srs_json.get("acceptance_criteria", []))
            + self._collect_ids(srs_json.get("validation_rules", []))
        )

    def _is_technical_actor(self, name: str) -> bool:
        lowered = self._normalize_words(name)
        return any(word in lowered for word in self.TECHNICAL_ACTOR_WORDS)

    def _remove_requirement_noise(self, text: str) -> str:
        cleaned = str(text).strip()
        cleaned = re.sub(r"^given\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^when\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^then\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(the system must|system must|system shall|the user must|user must|must|shall|should)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(allow|enable|let|provide|support)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("'", "")
        return cleaned.strip()

    def _normalize_words(self, text: str) -> str:
        text = str(text).lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _has_any(self, text: str, words: list[str]) -> bool:
        normalized = self._normalize_words(text)
        return any(word in normalized for word in words)

    def _unique(self, items: list[str]) -> list[str]:
        result = []
        for item in items:
            value = str(item).strip()
            if value and value not in result:
                result.append(value)
        return result

    def _title_case(self, text: str) -> str:
        return " ".join(word[:1].upper() + word[1:] for word in str(text).split())

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
