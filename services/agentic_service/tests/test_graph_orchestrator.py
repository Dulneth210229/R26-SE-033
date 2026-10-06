"""
Graph orchestrator mechanics test (interrupt/resume/checkpoint survival).

Domain Agent update: domain_node now calls the real DomainAgent RAG pipeline
(same class as uiux_node/coder_node -- requires a real approved SRS artifact
and makes a real LLM call), so it moved out of the "auto-approved pass-
through" set into GATED_STAGES. That means these throwaway-feature mechanics
tests can no longer cheaply advance past the requirement gate the way they
used to (there is nothing beyond it left that's still a no-op pass-through --
requirement_node itself is the only stage before a real agent runs). These
tests exercise interrupt/resume/reject-loop/restart-survival entirely at the
requirement gate, which is representative of the generic
_make_approval_gate/_make_router mechanics regardless of which stage they're
applied to. The real, full run-to-completion proof (through the real
domain_node/uiux_node/coder_node) is exercised manually against the real,
approved Login feature -- see CLAUDE.md for that verification.

Requires a reachable MongoDB (the same one configured in .env / MONGODB_URI).
Every project/feature this test creates is deleted in a fixture teardown, and
the collections it writes checkpoints into are LangGraph-owned
(langgraph_checkpoints / langgraph_checkpoint_writes), never the app's own
projects/features/artifacts collections.
"""

import pytest

from app.services.graph_orchestrator_service import (
    GraphNotRunningError,
    GraphOrchestratorService,
)
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


@pytest.fixture
def feature():
    """
    Create a throwaway project + feature in the real store, and clean up
    (including its LangGraph checkpoint documents) after the test.
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {
        "project_id": project_id,
        "project_name": f"Test Project {project_id}",
    }
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": f"Test Feature {feature_id}",
    }

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["langgraph_checkpoints"].delete_many({"thread_id": feature_id})
    store.database["langgraph_checkpoint_writes"].delete_many({"thread_id": feature_id})


def test_start_pauses_at_first_approval_gate(feature):
    orchestrator = GraphOrchestratorService()

    result = orchestrator.start(feature["project_id"], feature["feature_id"])

    assert "__interrupt__" in result
    status = orchestrator.get_status(feature["feature_id"])
    assert status["next"] == ["approve_requirement"]


def test_domain_is_a_real_gated_stage_requiring_an_approved_srs(feature):
    """
    Domain Agent is no longer an auto-approved pass-through: approving
    requirement now advances into the real domain_node, which enforces its
    own precondition (an approved SRS JSON artifact must exist) exactly like
    Architecture Agent's own precondition -- there is no approved SRS for
    this throwaway feature, so the real DomainAgent.run() raises, proving
    the gate is real rather than a no-op.
    """
    orchestrator = GraphOrchestratorService()
    orchestrator.start(feature["project_id"], feature["feature_id"])

    with pytest.raises(ValueError, match="No approved SRS JSON artifact found"):
        orchestrator.resume(feature["feature_id"], "approved")


def test_rejection_loops_back_to_same_stage(feature):
    orchestrator = GraphOrchestratorService()
    orchestrator.start(feature["project_id"], feature["feature_id"])

    orchestrator.resume(feature["feature_id"], "revision_requested")

    status = orchestrator.get_status(feature["feature_id"])
    # Still paused at the requirement gate, not advanced into domain.
    assert status["next"] == ["approve_requirement"]


def test_resume_without_a_paused_run_raises(feature):
    orchestrator = GraphOrchestratorService()
    # Never started -- there is no paused run for this feature_id.
    with pytest.raises(GraphNotRunningError):
        orchestrator.resume(feature["feature_id"], "approved")


def test_resume_survives_a_fresh_orchestrator_instance(feature):
    """
    Simulates a backend restart: a brand-new GraphOrchestratorService (fresh
    graph build, fresh checkpointer handle) must be able to resume a run
    started by a different instance, reading state from MongoDB only.
    """
    first_instance = GraphOrchestratorService()
    first_instance.start(feature["project_id"], feature["feature_id"])
    first_instance.resume(feature["feature_id"], "revision_requested")  # loops back to requirement

    second_instance = GraphOrchestratorService()
    status_before = second_instance.get_status(feature["feature_id"])
    assert status_before["next"] == ["approve_requirement"]

    # Prove routing still works correctly post-restart (reject -> loop back again).
    second_instance.resume(feature["feature_id"], "revision_requested")

    final_status = second_instance.get_status(feature["feature_id"])
    assert final_status["next"] == ["approve_requirement"]
    assert final_status["values"]["last_agent"] == "requirement"
