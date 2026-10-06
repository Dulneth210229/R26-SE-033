"""
Unit tests for ArchitectureSequencePlantUMLBuilder (app/agents/architecture_agent/
sequence_builder.py). No LLM/Docker involved -- pure string-rendering logic.

First dedicated builder test file for this diagram -- nothing else in this codebase directly
exercises the actual PlantUML keyword output, which matters specifically for the new par/break
fragment support (item -- see this project's own working notes) and for confirming an
unrecognized interaction kind is now logged rather than silently vanishing with no trace.
"""

import logging

from app.agents.architecture_agent.sequence_builder import ArchitectureSequencePlantUMLBuilder


def _base_sequence_json(interactions: list[dict]) -> dict:
    return {
        "diagram_title": "Test Sequence",
        "participants": [
            {"id": "P1", "name": "Customer", "type": "actor"},
            {"id": "P2", "name": "Service", "type": "control"},
        ],
        "interactions": interactions,
    }


class TestParFragmentRendering:
    def test_par_start_renders_the_par_keyword_with_its_condition(self):
        builder = ArchitectureSequencePlantUMLBuilder()
        sequence_json = _base_sequence_json([
            {"kind": "par_start", "condition": "Notify and audit concurrently"},
            {"kind": "message", "from": "P1", "to": "P2", "message": "Send notification", "message_type": "async"},
            {"kind": "end"},
        ])

        output = builder.build(sequence_json)

        assert "par Notify and audit concurrently" in output
        assert "end" in output


class TestBreakFragmentRendering:
    def test_break_start_renders_the_break_keyword_with_its_condition(self):
        builder = ArchitectureSequencePlantUMLBuilder()
        sequence_json = _base_sequence_json([
            {"kind": "break_start", "condition": "Validation fails"},
            {"kind": "message", "from": "P2", "to": "P1", "message": "Return validation error", "message_type": "return"},
            {"kind": "end"},
        ])

        output = builder.build(sequence_json)

        assert "break Validation fails" in output


class TestUnrecognizedInteractionKind:
    def test_unrecognized_kind_is_skipped_and_logged_not_silently_dropped(self, caplog):
        builder = ArchitectureSequencePlantUMLBuilder()
        sequence_json = _base_sequence_json([
            {"kind": "critical_start", "condition": "Something"},
            {"kind": "message", "from": "P1", "to": "P2", "message": "Real message", "message_type": "sync"},
        ])

        with caplog.at_level(logging.WARNING):
            output = builder.build(sequence_json)

        assert "critical_start" not in output
        assert "Real message" in output
        assert any("unrecognized sequence interaction kind" in record.message.lower() for record in caplog.records)


class TestExistingFragmentsStillRenderCorrectly:
    def test_alt_opt_loop_still_render_their_own_keywords(self):
        builder = ArchitectureSequencePlantUMLBuilder()
        sequence_json = _base_sequence_json([
            {"kind": "alt_start", "condition": "Success"},
            {"kind": "message", "from": "P1", "to": "P2", "message": "Do thing", "message_type": "sync"},
            {"kind": "else", "condition": "Failure"},
            {"kind": "message", "from": "P2", "to": "P1", "message": "Return error", "message_type": "return"},
            {"kind": "end"},
            {"kind": "loop_start", "condition": "For each item"},
            {"kind": "message", "from": "P1", "to": "P2", "message": "Process item", "message_type": "sync"},
            {"kind": "end"},
        ])

        output = builder.build(sequence_json)

        assert "alt Success" in output
        assert "else Failure" in output
        assert "loop For each item" in output
