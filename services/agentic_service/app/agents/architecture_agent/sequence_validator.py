"""
Architecture Agent Sequence Diagram Validator.

Purpose:
Validate generated UML Sequence Diagram JSON before PlantUML rendering.

Feature-independent rules:
- A sequence diagram must have participants and ordered interactions.
- At least one actor and one system boundary/control participant should exist.
- Message endpoints must reference existing participants.
- Combined fragments must be balanced.
- NFRs, constraints, risks, and architecture decisions should not appear as messages.
- Out-of-scope behaviour from SRS must not appear in executable messages.
"""

from __future__ import annotations

import re
from typing import Any

from app.agents.architecture_agent.sequence_fragment_kinds import FRAGMENT_OPENER_KINDS


class SequenceDiagramValidationError(Exception):
    """Raised when the generated sequence diagram model is invalid."""


class SequenceDiagramValidator:
    """
    Pass/fail validator for sequence_diagram_json.
    """

    NON_MESSAGE_TERMS = [
        "performance", "response time", "responsive ui", "mern stack", "mvc",
        "architecture style", "design tradeoff", "risk mitigation", "nfr",
        "next.js", "nextjs", "typescript", "server component", "route handler",
        "app router",
    ]

    STOPWORDS = {
        "the", "a", "an", "and", "or", "to", "via", "by", "for", "of", "in",
        "on", "with", "only", "is", "are", "be", "this", "that", "flow",
        "feature", "scope", "out", "from", "as", "at", "using",
        # Generic requirement-phrasing filler nouns -- see the matching
        # comment in usecase_validator.py's STOPWORDS for why these add no
        # distinguishing signal to an out-of-scope phrase's stem set.
        "functionality", "capability", "capabilities", "support",
    }

    def validate(self, srs_json: dict[str, Any], sequence_json: dict[str, Any]) -> None:
        errors: list[str] = []
        errors.extend(self._validate_structure(sequence_json))
        errors.extend(self._validate_participants(sequence_json))
        errors.extend(self._validate_interactions(sequence_json))
        errors.extend(self._validate_message_quality(sequence_json))
        errors.extend(self._validate_traceability(srs_json, sequence_json))
        errors.extend(self._validate_out_of_scope(srs_json, sequence_json))

        if errors:
            raise SequenceDiagramValidationError("; ".join(errors))

    def _validate_structure(self, sequence_json: dict[str, Any]) -> list[str]:
        if not isinstance(sequence_json, dict):
            return ["sequence_diagram_json must be a JSON object."]

        errors: list[str] = []
        for key in ["diagram_title", "participants", "interactions"]:
            if key not in sequence_json:
                errors.append(f"sequence_diagram_json missing required key: {key}")

        if not isinstance(sequence_json.get("participants", []), list) or not sequence_json.get("participants", []):
            errors.append("Sequence diagram must have participants.")

        if not isinstance(sequence_json.get("interactions", []), list) or not sequence_json.get("interactions", []):
            errors.append("Sequence diagram must have interactions/messages.")

        return errors

    def _validate_participants(self, sequence_json: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        seen_ids: set[str] = set()
        participant_types: set[str] = set()

        for participant in sequence_json.get("participants", []):
            if not isinstance(participant, dict):
                errors.append("Each sequence participant must be a JSON object.")
                continue

            participant_id = str(participant.get("id", "")).strip()
            name = str(participant.get("name", "")).strip()
            ptype = str(participant.get("type", "")).strip().lower()

            if not participant_id or not name:
                errors.append("Each sequence participant must have id and name.")
                continue

            if participant_id in seen_ids:
                errors.append(f"Duplicate sequence participant id: {participant_id}")
            seen_ids.add(participant_id)
            participant_types.add(ptype)

        if "actor" not in participant_types:
            errors.append("Sequence diagram must include at least one actor lifeline.")

        if "boundary" not in participant_types and "control" not in participant_types:
            errors.append("Sequence diagram must include a system boundary or control lifeline.")

        return errors

    def _validate_interactions(self, sequence_json: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        participants = {
            str(item.get("id"))
            for item in sequence_json.get("participants", [])
            if isinstance(item, dict) and item.get("id")
        }

        fragment_stack: list[str] = []
        message_count = 0

        for interaction in sequence_json.get("interactions", []):
            if not isinstance(interaction, dict):
                errors.append("Each sequence interaction must be a JSON object.")
                continue

            kind = str(interaction.get("kind", "message"))

            if kind in FRAGMENT_OPENER_KINDS:
                fragment_stack.append(kind)
                continue

            if kind == "else":
                if not fragment_stack or fragment_stack[-1] != "alt_start":
                    errors.append("Sequence diagram has else without matching alt fragment.")
                continue

            if kind == "end":
                if not fragment_stack:
                    errors.append("Sequence diagram has end without matching fragment start.")
                else:
                    fragment_stack.pop()
                continue

            if kind != "message":
                errors.append(f"Invalid sequence interaction kind: {kind}")
                continue

            source = str(interaction.get("from", "")).strip()
            target = str(interaction.get("to", "")).strip()
            message = str(interaction.get("message", "")).strip()
            message_count += 1

            if source not in participants:
                errors.append(f"Sequence message source is not a participant: {source}")
            if target not in participants:
                errors.append(f"Sequence message target is not a participant: {target}")
            if not message:
                errors.append("Sequence message must have text.")
            if self._contains_any(self._normalize(message), self.NON_MESSAGE_TERMS):
                errors.append(f"Non-behavioural design detail used as sequence message: {message}")

        if fragment_stack:
            errors.append("Sequence diagram has unclosed combined fragment.")

        if message_count < 3:
            errors.append("Sequence diagram is too weak; it must contain at least three messages.")

        return errors

    def _validate_message_quality(self, sequence_json: dict[str, Any]) -> list[str]:
        """
        Flags a message repeated verbatim (same from/to pair + normalized
        text) outside a loop fragment -- inside a loop, repeating the same
        message each iteration is the whole point, so duplicate-checking is
        suspended for anything nested inside a loop_start/end block
        (including nested alt/opt fragments), not just a bare loop body.
        """
        errors: list[str] = []
        seen: set[tuple[str, str, str]] = set()
        fragment_stack: list[str] = []

        for interaction in sequence_json.get("interactions", []):
            if not isinstance(interaction, dict):
                continue

            kind = str(interaction.get("kind", "message"))

            if kind in FRAGMENT_OPENER_KINDS:
                fragment_stack.append(kind)
                continue

            if kind == "end":
                if fragment_stack:
                    fragment_stack.pop()
                continue

            if kind != "message" or "loop_start" in fragment_stack:
                continue

            source = str(interaction.get("from", "")).strip()
            target = str(interaction.get("to", "")).strip()
            message_text = str(interaction.get("message", "")).strip()
            key = (source, target, self._normalize(message_text))

            if key in seen:
                errors.append(
                    f"Duplicate sequence message found outside a loop: '{message_text}' "
                    f"from {source} to {target}."
                )
            seen.add(key)

        return errors

    def _validate_traceability(self, srs_json: dict[str, Any], sequence_json: dict[str, Any]) -> list[str]:
        fr_ids = self._collect_ids(srs_json.get("functional_requirements", []))
        if not fr_ids:
            return []

        covered: set[str] = set()
        for interaction in sequence_json.get("interactions", []):
            if isinstance(interaction, dict):
                covered.update(map(str, interaction.get("related_requirements", []) or []))
        for trace in sequence_json.get("traceability", []):
            if isinstance(trace, dict) and trace.get("source_id"):
                covered.add(str(trace["source_id"]))

        missing = [req_id for req_id in fr_ids if req_id not in covered]
        if missing:
            return [f"Sequence diagram missing traceability for FR IDs: {missing}"]
        return []

    def _validate_out_of_scope(self, srs_json: dict[str, Any], sequence_json: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        executable_texts = [
            str(item.get("message", ""))
            for item in sequence_json.get("interactions", [])
            if isinstance(item, dict) and item.get("kind") == "message"
        ]

        for item in srs_json.get("out_of_scope", []) or []:
            forbidden, allowed = self._split_out_of_scope_item(self._item_text(item))
            forbidden_stems = self._important_stems(forbidden)
            allowed_sets = [self._important_stems(text) for text in allowed]
            if not forbidden_stems:
                continue

            for text in executable_texts:
                text_stems = self._important_stems(text)
                if self._matches_allowed(text_stems, allowed_sets):
                    continue
                # Require ALL forbidden stems to be present, not just any 2 -- see the
                # matching comment in usecase_validator.py's _validate_out_of_scope for why a
                # flat 2-stem threshold false-positives on generic shared domain vocabulary.
                if len(forbidden_stems.intersection(text_stems)) >= len(forbidden_stems):
                    errors.append(f"Sequence diagram appears to include out-of-scope item '{self._item_text(item)}' in message '{text}'.")

        return errors

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _split_out_of_scope_item(self, text: str) -> tuple[str, list[str]]:
        raw = str(text)
        allowed: list[str] = []
        for part in re.findall(r"\(([^)]*)\)", raw):
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

    def _matches_allowed(self, stems: set[str], allowed_sets: list[set[str]]) -> bool:
        return any(stems.intersection(allowed_set) for allowed_set in allowed_sets if allowed_set)

    def _important_stems(self, text: str) -> set[str]:
        words = re.findall(r"[a-zA-Z0-9]+", str(text).lower())
        result: set[str] = set()
        for word in words:
            if len(word) < 3 or word in self.STOPWORDS:
                continue
            result.add(self._stem(word))
        return result

    def _stem(self, word: str) -> str:
        if word.startswith("verif"):
            return "verif"
        if word.startswith("initiat"):
            return "initiat"
        for suffix in ["ations", "ation", "itions", "ition", "ments", "ment", "ing", "ed", "es", "s"]:
            if word.endswith(suffix) and len(word) > len(suffix) + 3:
                return word[: -len(suffix)]
        return word

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
        return re.sub(r"\s+", " ", text).strip()

    def _contains_any(self, text: str, keywords: list[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    def _unique(self, items: list[str]) -> list[str]:
        result: list[str] = []
        for item in items:
            value = str(item).strip()
            if value and value not in result:
                result.append(value)
        return result
