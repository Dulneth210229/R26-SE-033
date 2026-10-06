"""
Architecture Agent Use Case Validator.

Purpose:
Validate generated UML Use Case model before PlantUML rendering.

Important:
- Feature-independent pass/fail validation.
- No quality score file.
- No hardcoded feature names such as Login, Cart, Payment, LMS.
- No domain-specific exception such as password reset special cases.
"""

from __future__ import annotations

import re
from typing import Any


class UseCaseValidationError(Exception):
    """
    Raised when the generated use case model is invalid or outside feature scope.
    """


class UseCaseQualityValidator:
    """
    Feature-independent validator for UML Use Case Diagram JSON.
    """

    TECHNICAL_ACTOR_TERMS = [
        "database", "mongodb", "mysql", "postgres", "collection", "table",
        "api", "endpoint", "controller", "service", "repository", "model",
        "schema", "server", "backend", "frontend", "react", "node",
        "express", "mongoose", "jwt", "token", "library", "middleware",
        "component", "page", "form", "next.js", "nextjs", "typescript",
        "server component", "route handler", "app router",
    ]

    GENERIC_USE_CASE_NAMES = [
        "use feature", "use system", "manage feature", "access feature",
        "perform feature", "do feature", "feature action",
    ]

    NON_UML_USE_CASE_TERMS = [
        "response time", "performance", "responsive ui", "mern stack", "mvc",
        "architecture style", "database collection", "api endpoint",
        "next.js", "nextjs", "typescript", "server component", "route handler",
        "app router",
    ]

    # Articles/determiners/possessive-pronouns/Given-When-Then leftovers only
    # -- these are the exact tokens observed in real, confirmed-garbled use
    # case names produced by cutting an SRS sentence mid-phrase instead of
    # naming a real goal (e.g. "A Task The Can", "A Comment The Authored",
    # "A Enters A Keyword"). Deliberately excludes generic auxiliary verbs
    # like do/is/are/does -- a name like "Do Something" is generic but not a
    # cut sentence fragment, and must not be flagged by this check.
    FRAGMENT_WORDS = {
        "a", "an", "the", "this", "that", "these", "those", "their", "its",
        "his", "her", "our", "your", "my", "can", "could", "would", "should",
        "given", "when", "then",
    }

    # Verbs that describe an internal implementation step (validation,
    # confirmation) rather than a distinct, user-observable goal -- seeing
    # 2+ included/extension use cases under the same main use case all start
    # with one of these is the confirmed real "Validate Email"/"Validate
    # Password"/"Validate Credentials" over-fragmentation anti-pattern.
    INTERNAL_STEP_VERBS = {"validate", "verify", "check", "confirm"}

    # Short, curated CRUD-shaped verb set for _validate_no_conjoined_capabilities below (kept as
    # a separate copy from usecase_modeler.py's own DISTINCT_CAPABILITY_VERBS, per this
    # codebase's convention of not sharing files between these deterministic agent modules).
    # Deliberately short -- a broader list (search/filter/export/approve/etc.) is more likely to
    # legitimately co-occur in one real use case name (e.g. "Export Filtered Report") and would
    # false-positive.
    DISTINCT_CAPABILITY_VERBS = {
        "add": "add", "create": "add",
        "list": "list", "view": "list", "browse": "list",
        "update": "update", "edit": "update",
        "delete": "delete", "remove": "delete",
    }

    STOPWORDS = {
        "the", "a", "an", "and", "or", "to", "via", "by", "for", "of",
        "in", "on", "with", "only", "is", "are", "be", "this", "that",
        "flow", "feature", "scope", "out", "from", "as", "at", "using",
        # Generic requirement-phrasing filler nouns -- these describe *that*
        # something is a capability, not *which* capability, so they add no
        # distinguishing signal to an out-of-scope phrase's stem set (e.g.
        # "Password recovery functionality" is distinguished by "password"/
        # "recovery", not by "functionality"). Domain-agnostic (applies to
        # any feature), not feature-specific hardcoding.
        "functionality", "capability", "capabilities", "support",
    }

    def validate(
        self,
        srs_json: dict[str, Any],
        sds_json: dict[str, Any],
        usecase_analysis_json: dict[str, Any],
        usecase_json: dict[str, Any],
    ) -> None:
        errors: list[str] = []

        errors.extend(self._validate_basic_structure(usecase_json))
        errors.extend(self._validate_actors(usecase_json))
        errors.extend(self._validate_actor_name_quality(usecase_json))
        errors.extend(self._validate_use_cases(usecase_json))
        errors.extend(self._validate_use_case_name_quality(usecase_json))
        errors.extend(self._validate_use_case_fragmentation(usecase_json))
        errors.extend(self._validate_no_conjoined_capabilities(usecase_json))
        errors.extend(self._validate_relationships(usecase_json))
        errors.extend(self._validate_traceability(srs_json, usecase_analysis_json, usecase_json))
        errors.extend(self._validate_out_of_scope(srs_json, usecase_json))

        if errors:
            raise UseCaseValidationError("; ".join(errors))

    def _validate_basic_structure(self, usecase_json: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        if not isinstance(usecase_json, dict):
            return ["usecase_json must be a JSON object."]

        required_keys = ["system_boundary", "diagram_title", "actors", "use_cases", "relationships", "notes"]

        for key in required_keys:
            if key not in usecase_json:
                errors.append(f"usecase_json missing required key: {key}")

        if not str(usecase_json.get("system_boundary", "")).strip():
            errors.append("Use case diagram must have a clear system boundary.")

        if not isinstance(usecase_json.get("actors", []), list) or not usecase_json.get("actors", []):
            errors.append("Use case diagram must have at least one actor.")

        if not isinstance(usecase_json.get("use_cases", []), list) or not usecase_json.get("use_cases", []):
            errors.append("Use case diagram must have at least one use case.")

        if not isinstance(usecase_json.get("relationships", []), list) or not usecase_json.get("relationships", []):
            errors.append("Use case diagram must have at least one relationship.")

        if not isinstance(usecase_json.get("notes", []), list):
            errors.append("usecase_json.notes must be a list.")

        return errors

    def _validate_actors(self, usecase_json: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        seen_actor_names: set[str] = set()

        for actor in usecase_json.get("actors", []):
            if not isinstance(actor, dict):
                errors.append("Each actor must be a JSON object.")
                continue

            actor_id = str(actor.get("id", "")).strip()
            actor_name = str(actor.get("name", "")).strip()

            if not actor_id or not actor_name:
                errors.append("Each actor must have id and name.")
                continue

            normalized_name = self._normalize(actor_name)

            if normalized_name in seen_actor_names:
                errors.append(f"Duplicate actor name found: {actor_name}")
            seen_actor_names.add(normalized_name)

            if self._contains_any(normalized_name, self.TECHNICAL_ACTOR_TERMS):
                errors.append(f"Technical component used as actor: {actor_name}")

        return errors

    def _validate_actor_name_quality(self, usecase_json: dict[str, Any]) -> list[str]:
        """
        Reject an actor name that reads as a sentence/description rather than a real role or
        system name -- confirmed real example: "An Image Hosting Solution To Store Uploaded
        Images." Mirrors _validate_use_case_name_quality's FRAGMENT_WORDS check (reused, not
        duplicated), plus two actor-specific signals: an actor name is expected to be a short
        (<=5 word) noun phrase per the schema's own "1-4 word noun phrase" framing, and a name
        ending in sentence punctuation is a cheap, zero-false-positive sign of a cut/pasted
        sentence rather than a name.
        """
        errors: list[str] = []

        for actor in usecase_json.get("actors", []):
            if not isinstance(actor, dict):
                continue

            name = str(actor.get("name", "")).strip()
            if not name:
                continue

            if name.rstrip()[-1:] in (".", "!", "?"):
                errors.append(
                    f"Actor name ends with sentence punctuation, not a name: '{name}'"
                )

            words = [word.lower() for word in re.findall(r"[a-zA-Z0-9']+", name)]
            fragment_hits = sorted({word for word in words if word in self.FRAGMENT_WORDS})

            if fragment_hits:
                errors.append(
                    f"Actor name looks like a cut sentence fragment, not a role/system name: "
                    f"'{name}' (contains: {', '.join(fragment_hits)})"
                )

            if len(words) > 5:
                errors.append(
                    f"Actor name reads like a description, not a name (too many words): '{name}'"
                )

        return errors

    def _validate_use_cases(self, usecase_json: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        seen_usecase_names: set[str] = set()

        for use_case in usecase_json.get("use_cases", []):
            if not isinstance(use_case, dict):
                errors.append("Each use case must be a JSON object.")
                continue

            use_case_id = str(use_case.get("id", "")).strip()
            use_case_name = str(use_case.get("name", "")).strip()

            if not use_case_id or not use_case_name:
                errors.append("Each use case must have id and name.")
                continue

            normalized_name = self._normalize(use_case_name)

            if normalized_name in seen_usecase_names:
                errors.append(f"Duplicate use case name found: {use_case_name}")
            seen_usecase_names.add(normalized_name)

            if normalized_name in self.GENERIC_USE_CASE_NAMES or re.fullmatch(r"use .+ feature", normalized_name):
                errors.append(f"Use case name is too generic: {use_case_name}")

            if self._contains_any(normalized_name, self.NON_UML_USE_CASE_TERMS):
                errors.append(
                    f"Non-functional requirement or technical constraint used as a normal use case: {use_case_name}"
                )

            if len(use_case_name.split()) > 6:
                errors.append(f"Use case name is too long for a standard diagram: {use_case_name}")

        return errors

    def _validate_use_case_name_quality(self, usecase_json: dict[str, Any]) -> list[str]:
        """
        Reject names that read as a cut sentence fragment rather than a real
        use-case goal -- confirmed real examples: "A Task The Can", "A
        Comment The Authored", "A Enters A Keyword". A name containing a
        standalone article/determiner/possessive-pronoun/Given-When-Then
        token is a strong, evidence-derived signal of this failure mode.
        """
        errors: list[str] = []

        for use_case in usecase_json.get("use_cases", []):
            if not isinstance(use_case, dict):
                continue

            name = str(use_case.get("name", "")).strip()
            if not name:
                continue

            words = [word.lower() for word in re.findall(r"[a-zA-Z0-9']+", name)]
            fragment_hits = sorted({word for word in words if word in self.FRAGMENT_WORDS})

            if fragment_hits:
                errors.append(
                    f"Use case name looks like a cut sentence fragment, not a clean action "
                    f"phrase: '{name}' (contains: {', '.join(fragment_hits)})"
                )

        return errors

    def _validate_use_case_fragmentation(self, usecase_json: dict[str, Any]) -> list[str]:
        """
        Catch the confirmed real CRUD/step-decomposition anti-pattern: one
        action split into several parallel included/extension use cases
        under the same main use case (e.g. "Validate Email"/"Validate
        Password"/"Validate Credentials" for one login attempt). Two
        signals, both scoped to use cases relating to the SAME main use case:
        (a) 2+ share a leading INTERNAL_STEP_VERBS word, (b) 2+ cite the
        exact same non-empty related_requirements set (duplicate regardless
        of naming).
        """
        errors: list[str] = []

        use_cases_by_id = {
            str(use_case.get("id")): use_case
            for use_case in usecase_json.get("use_cases", [])
            if isinstance(use_case, dict) and use_case.get("id")
        }

        children_by_main: dict[str, list[dict[str, Any]]] = {}

        for relationship in usecase_json.get("relationships", []):
            if not isinstance(relationship, dict):
                continue

            relation_type = relationship.get("type")
            if relation_type == "include":
                main_id, child_id = relationship.get("from"), relationship.get("to")
            elif relation_type == "extend":
                child_id, main_id = relationship.get("from"), relationship.get("to")
            else:
                continue

            child = use_cases_by_id.get(str(child_id))
            if child is not None:
                children_by_main.setdefault(str(main_id), []).append(child)

        for children in children_by_main.values():
            verb_groups: dict[str, list[str]] = {}
            for child in children:
                name = str(child.get("name", "")).strip()
                first_word = name.split()[0].lower() if name else ""
                if first_word in self.INTERNAL_STEP_VERBS:
                    verb_groups.setdefault(first_word, []).append(name)

            for verb, names in verb_groups.items():
                if len(names) >= 2:
                    errors.append(
                        f"Use cases {names} look like decomposed internal steps of one action "
                        f"(all start with '{verb.title()}') -- combine into a single use case "
                        "unless each is genuinely an independent, reusable, user-observable goal."
                    )

            requirement_groups: dict[frozenset, list[str]] = {}
            for child in children:
                related = frozenset(
                    str(item) for item in child.get("related_requirements", []) or [] if item
                )
                if related:
                    requirement_groups.setdefault(related, []).append(str(child.get("name", "")))

            for related, names in requirement_groups.items():
                if len(names) >= 2:
                    errors.append(
                        f"Use cases {names} cite the exact same requirements {sorted(related)} -- "
                        "likely duplicate entries for the same real behaviour; merge them."
                    )

        return errors

    def _validate_no_conjoined_capabilities(self, usecase_json: dict[str, Any]) -> list[str]:
        """
        Catch the OPPOSITE failure from _validate_use_case_fragmentation above: one use case name
        conjoining 2+ genuinely distinct top-level capabilities instead of being split into
        separate use cases -- confirmed real example: "Add List Items" for a feature that both
        adds and lists items. Flags a single name containing 2+ DIFFERENT verbs from the short
        curated DISTINCT_CAPABILITY_VERBS set (see that constant's own comment for why it's kept
        short).
        """
        errors: list[str] = []

        for use_case in usecase_json.get("use_cases", []):
            if not isinstance(use_case, dict):
                continue

            name = str(use_case.get("name", "")).strip()
            if not name:
                continue

            words = [word.lower() for word in re.findall(r"[a-zA-Z0-9']+", name)]
            capabilities_hit = {
                self.DISTINCT_CAPABILITY_VERBS[word] for word in words if word in self.DISTINCT_CAPABILITY_VERBS
            }

            if len(capabilities_hit) >= 2:
                errors.append(
                    f"Use case name conjoins multiple distinct capabilities into one entry: "
                    f"'{name}' -- split into separate use cases, one per capability "
                    f"({', '.join(sorted(capabilities_hit))})."
                )

        return errors

    def _validate_relationships(self, usecase_json: dict[str, Any]) -> list[str]:
        errors: list[str] = []

        actors = usecase_json.get("actors", [])
        use_cases = usecase_json.get("use_cases", [])
        relationships = usecase_json.get("relationships", [])

        actor_ids = {
            str(actor.get("id"))
            for actor in actors
            if isinstance(actor, dict) and actor.get("id")
        }

        use_case_ids = {
            str(use_case.get("id"))
            for use_case in use_cases
            if isinstance(use_case, dict) and use_case.get("id")
        }

        allowed_types = {"association", "include", "extend", "generalization"}

        for relationship in relationships:
            if not isinstance(relationship, dict):
                errors.append("Each relationship must be a JSON object.")
                continue

            source = str(relationship.get("from", "")).strip()
            target = str(relationship.get("to", "")).strip()
            relation_type = str(relationship.get("type", "")).strip()

            if not source or not target:
                errors.append("Each relationship must have from and to.")
                continue

            if relation_type not in allowed_types:
                errors.append(f"Invalid use case relationship type: {relation_type}")
                continue

            if relation_type == "association" and (source not in actor_ids or target not in use_case_ids):
                errors.append("Association relationship must be actor -> use case.")

            if relation_type == "include" and (source not in use_case_ids or target not in use_case_ids):
                errors.append("Include relationship must be base use case -> included use case.")

            if relation_type == "extend" and (source not in use_case_ids or target not in use_case_ids):
                errors.append("Extend relationship must be extension use case -> base use case.")

            if relation_type == "generalization":
                both_use_cases = source in use_case_ids and target in use_case_ids
                both_actors = source in actor_ids and target in actor_ids
                if not (both_use_cases or both_actors):
                    errors.append(
                        "Generalization relationship must connect two use cases or two actors, "
                        "not a mix."
                    )

        return errors

    def _validate_traceability(
        self,
        srs_json: dict[str, Any],
        usecase_analysis_json: dict[str, Any],
        usecase_json: dict[str, Any],
    ) -> list[str]:
        """
        Every functional requirement, acceptance criterion, AND validation rule should be
        traceable to at least one use case/relationship -- previously only functional_requirements
        (FR) coverage was checked here, even though the prompt already asks the LLM to cite FR/
        AC/VR ids in related_requirements. Reported separately per requirement kind so a human
        reviewer sees exactly which category has a real gap.
        """
        errors: list[str] = []

        required_by_kind = {
            "FR": self._collect_ids(srs_json.get("functional_requirements", [])),
            "AC": self._collect_ids(srs_json.get("acceptance_criteria", [])),
            "VR": self._collect_ids(srs_json.get("validation_rules", [])),
        }

        if not any(required_by_kind.values()):
            return errors

        covered_ids: set[str] = set()

        for use_case in usecase_json.get("use_cases", []):
            if isinstance(use_case, dict):
                covered_ids.update(map(str, use_case.get("related_requirements", []) or []))

        for relationship in usecase_json.get("relationships", []):
            if isinstance(relationship, dict):
                covered_ids.update(map(str, relationship.get("related_requirements", []) or []))

        for trace in usecase_analysis_json.get("traceability", []):
            if isinstance(trace, dict) and trace.get("source_id"):
                covered_ids.add(str(trace["source_id"]))

        for kind, required_ids in required_by_kind.items():
            missing_ids = [req_id for req_id in required_ids if req_id not in covered_ids]
            if missing_ids:
                errors.append(f"Use case diagram missing traceability for {kind} IDs: {missing_ids}")

        return errors

    def _validate_out_of_scope(self, srs_json: dict[str, Any], usecase_json: dict[str, Any]) -> list[str]:
        """
        Generic out-of-scope validation.

        It does not contain password/login-specific logic. It compares executable
        use case elements against SRS out_of_scope items using meaningful token
        overlap. If the SRS says "Only X is in scope", elements matching X are
        allowed while the broader forbidden item is still blocked.
        """

        errors: list[str] = []
        out_of_scope_items = srs_json.get("out_of_scope", []) or []

        if not out_of_scope_items:
            return errors

        executable_elements = self._diagram_executable_elements(usecase_json)

        for item in out_of_scope_items:
            item_text = self._item_text(item)
            forbidden_text, allowed_texts = self._split_out_of_scope_item(item_text)

            forbidden_stems = self._important_stems(forbidden_text)
            if not forbidden_stems:
                continue

            allowed_stem_sets = [self._important_stems(text) for text in allowed_texts if text]

            for element in executable_elements:
                element_text = element["text"]
                element_stems = self._important_stems(element_text)

                if not element_stems:
                    continue

                if self._matches_allowed_clause(element_stems, allowed_stem_sets):
                    continue

                # Require the element to restate the ENTIRE forbidden concept (all of its
                # stems), not just any 2 -- a flat "2 stems overlap" threshold means any
                # out-of-scope phrase sharing 2 generic domain words with the feature (e.g.
                # "account"/"email" for an "Account verification via email" item, on a feature
                # that is itself about accounts and email) false-positives on nearly every
                # legitimate in-scope element, since those words are common to the whole
                # feature, not distinctive of the forbidden concept. Requiring the full set
                # means the single word that actually DEFINES the forbidden concept (e.g.
                # "verif") must be present, not just incidental shared vocabulary.
                overlap = forbidden_stems.intersection(element_stems)
                required_overlap = len(forbidden_stems)

                if len(overlap) >= required_overlap:
                    errors.append(
                        f"Use case diagram appears to include out-of-scope item '{item_text}' in '{element_text}'."
                    )

        return errors

    # ------------------------------------------------------------------
    # Out-of-scope helper methods
    # ------------------------------------------------------------------

    def _diagram_executable_elements(self, usecase_json: dict[str, Any]) -> list[dict[str, str]]:
        elements: list[dict[str, str]] = []

        for use_case in usecase_json.get("use_cases", []):
            if isinstance(use_case, dict):
                elements.append({
                    "type": "use_case",
                    "text": f"{use_case.get('name', '')} {use_case.get('description', '')}",
                })

        for relationship in usecase_json.get("relationships", []):
            if isinstance(relationship, dict):
                label = str(relationship.get("label", "")).strip()
                if label:
                    elements.append({"type": "relationship", "text": label})

        return elements

    def _split_out_of_scope_item(self, text: str) -> tuple[str, list[str]]:
        raw = str(text)
        allowed: list[str] = []

        parenthetical_parts = re.findall(r"\(([^)]*)\)", raw)
        for part in parenthetical_parts:
            allowed.extend(self._extract_allowed_clauses(part))

        allowed.extend(self._extract_allowed_clauses(raw))

        forbidden = re.sub(r"\([^)]*\)", " ", raw)
        forbidden = re.sub(r"\bonly\b.+?\bin\s+scope\b", " ", forbidden, flags=re.IGNORECASE)
        forbidden = re.sub(r"\bexcept\b.+", " ", forbidden, flags=re.IGNORECASE)
        forbidden = re.sub(r"\ballowed\s*:\s*.+", " ", forbidden, flags=re.IGNORECASE)
        forbidden = re.sub(r"\s+", " ", forbidden).strip()

        return forbidden or raw, self._unique(allowed)

    def _extract_allowed_clauses(self, text: str) -> list[str]:
        allowed: list[str] = []

        patterns = [
            r"only\s+(.+?)\s+is\s+in\s+scope",
            r"only\s+(.+?)\s+are\s+in\s+scope",
            r"only\s+(.+?)\s+in\s+scope",
            r"except\s+(.+)$",
            r"allowed\s*:\s*(.+)$",
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = match.group(1).strip(" .;:")
                if value:
                    allowed.append(value)

        return allowed

    def _matches_allowed_clause(self, element_stems: set[str], allowed_stem_sets: list[set[str]]) -> bool:
        for allowed_stems in allowed_stem_sets:
            if not allowed_stems:
                continue
            # One strong allowed token is enough for phrases such as "initiation flow".
            if element_stems.intersection(allowed_stems):
                return True
        return False

    def _important_stems(self, text: str) -> set[str]:
        words = re.findall(r"[a-zA-Z0-9]+", str(text).lower())
        stems = set()

        for word in words:
            if word in self.STOPWORDS or len(word) < 3:
                continue
            stems.add(self._stem(word))

        return stems

    def _stem(self, word: str) -> str:
        word = word.lower()

        # Very small generic stemmer to match verify/verification and initiate/initiation.
        if word.startswith("verif"):
            return "verif"
        if word.startswith("initiat"):
            return "initiat"

        for suffix in ["ations", "ation", "itions", "ition", "ments", "ment", "ing", "ed", "es", "s"]:
            if word.endswith(suffix) and len(word) > len(suffix) + 3:
                return word[: -len(suffix)]

        return word

    # ------------------------------------------------------------------
    # General helpers
    # ------------------------------------------------------------------

    def _collect_ids(self, items: Any) -> list[str]:
        ids: list[str] = []
        if not isinstance(items, list):
            return ids
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.append(str(item["id"]))
        return ids

    def _item_text(self, item: Any) -> str:
        if isinstance(item, dict):
            for key in ["description", "name", "title", "text", "value", "risk", "mitigation"]:
                if item.get(key):
                    return str(item[key])
            return str(item)
        return str(item)

    def _normalize(self, text: str) -> str:
        text = str(text).lower()
        text = re.sub(r"[^a-z0-9]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _unique(self, items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            value = str(item).strip()
            if value and value not in result:
                result.append(value)
        return result
