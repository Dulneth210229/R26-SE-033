"""
Top-level LangGraph orchestrator.

This replaces "call each agent endpoint manually, in order" with one LangGraph
StateGraph per feature, checkpointed in MongoDB, that pauses on interrupt() at
every human approval gate and resumes exactly where it left off -- even across
backend restarts -- via Command(resume=...).

Milestone 6: uiux_node and coder_node now call the real, complete
UIUXAgent.run()/CoderAgent.run() pipelines (built in M1-M5) instead of the
Milestone 0 pass-through no-ops. requirement_node and architecture_node stay
pass-through -- those two agents predate this whole build and are still
driven by their existing, unchanged
POST /features/{id}/agents/{requirement,architecture}/run endpoints; approving
the resulting artifact (unchanged approval flow) is what resumes the graph
past their gates, exactly as it always has.

domain_node moved back to a real gated stage once Domain Agent shipped its real
RAG-based Enhanced SRS implementation (see app/agents/domain_agent/agent.py):
it now produces a real, human-reviewable artifact triple (Enhanced SRS
Markdown/JSON + Domain Improvements JSON), so a human approval gate is both
possible and required -- Architecture Agent's use_enhanced_srs_if_available
lookup only ever finds an artifact if one was actually approved, so leaving
Domain auto-approved would silently defeat that feature.

Milestone 7: security_node and qa_node now call the real (still placeholder)
SecurityAgent/QAAgent classes instead of the generic Milestone 0 pass-through
-- same auto-approved, non-blocking behavior, but the graph now has real
node targets per the doc's Milestone 7 instruction, ready to become real
gates the moment those agents produce real output worth reviewing.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langgraph.checkpoint.mongodb import MongoDBSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from app.agents.coder_agent.agent import coder_agent
from app.agents.domain_agent.agent import domain_agent
from app.agents.qa_agent.agent import qa_agent
from app.agents.security_agent.agent import security_agent
from app.agents.uiux_agent.agent import uiux_agent
from app.core.config import settings
from app.schemas.coder_schema import CoderAgentRunRequest
from app.schemas.domain_schema import DomainAgentRunRequest
from app.schemas.uiux_schema import UIUXAgentRunRequest
from app.services.in_memory_store import store
from app.utils.logger import get_logger

logger = get_logger(__name__)

# The full pipeline order (used for edge-wiring), independent of which stages
# get a real human approval gate.
STAGE_SEQUENCE = ["requirement", "domain", "architecture", "uiux", "coder", "security", "qa"]

# Stages that stop for a human approval gate. "uiux" is back here per direct user request:
# human approval is required again for the UI/UX stage's output (only the Preview Screenshot is
# the human's approval surface -- see approval_service.py's UI/UX cascade). uiux_node itself is
# unchanged -- it just gets a real approve_uiux interrupt node built for it again.
GATED_STAGES = ["requirement", "domain", "architecture", "uiux", "coder"]

# Stages that run automatically with no human gate -- security/qa only: no agent implementation
# yet, nothing for a human to review.
AUTO_APPROVED_STAGES = ["security", "qa"]


class FeaturePipelineState(TypedDict, total=False):
    project_id: str
    feature_id: str
    human_comment: str | None
    last_agent: str
    last_artifact_ids: list[str]
    approval_decision: str | None


class GraphNotRunningError(Exception):
    """Raised when resume() is called for a feature with no paused graph run."""


def _make_stage_node(stage_name: str):
    def _node(state: FeaturePipelineState) -> dict[str, Any]:
        logger.info(
            "Pass-through node running: stage=%s feature_id=%s",
            stage_name,
            state.get("feature_id"),
        )
        return {
            "last_agent": stage_name,
            "last_artifact_ids": [],
            "human_comment": None,
        }

    return _node


def _domain_node(state: FeaturePipelineState) -> dict[str, Any]:
    """
    Real Domain Agent call. See _uiux_node for the asyncio.run() safety note.
    """
    feature_id = state["feature_id"]
    logger.info("Running real DomainAgent for feature_id=%s", feature_id)

    request = DomainAgentRunRequest(human_comment=state.get("human_comment"))
    output = asyncio.run(domain_agent.run(feature_id, request))

    return {
        "last_agent": "domain",
        "last_artifact_ids": output.artifact_ids,
        "human_comment": None,
    }


def _uiux_node(state: FeaturePipelineState) -> dict[str, Any]:
    """
    Real UI/UX Agent call.

    asyncio.run() is safe here specifically because every current caller of
    graph.invoke()/resume() is a sync FastAPI route handler (`def`, not
    `async def`) that FastAPI runs in a worker thread with no event loop
    already active. If this graph is ever invoked from a context that already
    has a running event loop, this must change to a threadsafe bridge
    (e.g. asyncio.run_coroutine_threadsafe).
    """
    feature_id = state["feature_id"]
    logger.info("Running real UIUXAgent for feature_id=%s", feature_id)

    request = UIUXAgentRunRequest(human_comment=state.get("human_comment"))
    output = asyncio.run(uiux_agent.run(feature_id, request))

    return {
        "last_agent": "uiux",
        "last_artifact_ids": output.artifact_ids,
        "human_comment": None,
    }


def _coder_node(state: FeaturePipelineState) -> dict[str, Any]:
    """
    Real Coder Agent call. See _uiux_node for the asyncio.run() safety note.
    """
    feature_id = state["feature_id"]
    logger.info("Running real CoderAgent for feature_id=%s", feature_id)

    request = CoderAgentRunRequest(human_comment=state.get("human_comment"))
    output = asyncio.run(coder_agent.run(feature_id, request))

    return {
        "last_agent": "coder",
        "last_artifact_ids": output.artifact_ids,
        "human_comment": None,
    }


def _security_node(state: FeaturePipelineState) -> dict[str, Any]:
    """
    Security Agent call -- runs the real scan (pattern/secret/dependency + LLM review layers,
    see app/agents/security_agent/agent.py) and saves a versioned Critical/Moderate/Warning
    report. Deliberately stays auto-approved (no interrupt() gate): this is a soft gate by
    design -- a Critical finding is clearly surfaced on the report for a human to act on (e.g.
    via the frontend's "Send to Coder Agent" action), never used to block pipeline advancement.
    """
    feature_id = state["feature_id"]
    logger.info("Running Security Agent for feature_id=%s", feature_id)

    output = asyncio.run(security_agent.run(feature_id=feature_id))

    return {
        "last_agent": "security",
        "last_artifact_ids": output.artifact_ids,
        "human_comment": None,
    }


def _qa_node(state: FeaturePipelineState) -> dict[str, Any]:
    """
    QA Agent call -- writes and executes real Unit/Integration/Regression tests (see
    app/agents/qa_agent/agent.py) and saves a versioned report. Auto-approved (no interrupt()
    gate): stays in AUTO_APPROVED_STAGES, a human reviews the report after the fact.
    """
    feature_id = state["feature_id"]
    logger.info("Running QA Agent for feature_id=%s", feature_id)

    output = asyncio.run(qa_agent.run(feature_id=feature_id))

    return {
        "last_agent": "qa",
        "last_artifact_ids": output.artifact_ids,
        "human_comment": None,
    }


REAL_NODE_FUNCTIONS = {
    "domain": _domain_node,
    "uiux": _uiux_node,
    "coder": _coder_node,
    "security": _security_node,
    "qa": _qa_node,
}


def _make_approval_gate(stage_name: str):
    def _gate(state: FeaturePipelineState) -> dict[str, Any]:
        decision = interrupt(
            {
                "feature_id": state["feature_id"],
                "agent_name": stage_name,
                "artifact_ids": state.get("last_artifact_ids", []),
                "message": f"Review {stage_name} output before continuing.",
            }
        )
        return {"approval_decision": decision}

    return _gate


def _make_router(stage_name: str, next_node: str):
    def _route(state: FeaturePipelineState) -> str:
        if state.get("approval_decision") == "approved":
            return next_node
        # rejected / revision_requested -> loop back into the same stage's node
        return f"{stage_name}_node"

    return _route


def _build_checkpointer() -> MongoDBSaver:
    """
    Reuse the app's existing MongoDB connection (store.client) rather than
    opening a second one. Checkpoints/writes go into their own collections so
    they never collide with the app's projects/features/artifacts/approvals.
    """
    return MongoDBSaver(
        client=store.client,
        db_name=settings.MONGODB_DATABASE,
        checkpoint_collection_name="langgraph_checkpoints",
        writes_collection_name="langgraph_checkpoint_writes",
    )


def _build_graph():
    builder = StateGraph(FeaturePipelineState)

    for stage in STAGE_SEQUENCE:
        node_fn = REAL_NODE_FUNCTIONS.get(stage) or _make_stage_node(stage)
        builder.add_node(f"{stage}_node", node_fn)

    for stage in GATED_STAGES:
        builder.add_node(f"approve_{stage}", _make_approval_gate(stage))
        builder.add_edge(f"{stage}_node", f"approve_{stage}")

    builder.add_edge(START, f"{STAGE_SEQUENCE[0]}_node")

    for index, stage in enumerate(STAGE_SEQUENCE):
        is_last = index == len(STAGE_SEQUENCE) - 1
        next_node = END if is_last else f"{STAGE_SEQUENCE[index + 1]}_node"

        if stage in GATED_STAGES:
            same_stage_node = f"{stage}_node"
            builder.add_conditional_edges(
                f"approve_{stage}",
                _make_router(stage, next_node),
                {next_node: next_node, same_stage_node: same_stage_node},
            )
        else:
            builder.add_edge(f"{stage}_node", next_node)

    return builder.compile(checkpointer=_build_checkpointer())


class GraphOrchestratorService:
    """
    Drives the per-feature pipeline graph. thread_id = feature_id for every
    invoke/resume call, so a human can approve a stage hours or days later and
    the graph picks up exactly where it paused, even after a backend restart.
    """

    def __init__(self):
        self._graph = _build_graph()

    def _config(self, feature_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": feature_id}}

    def start(self, project_id: str, feature_id: str) -> dict[str, Any]:
        """
        Start a feature's pipeline run for the first time.
        """
        logger.info("Starting graph run for feature_id=%s", feature_id)

        return self._graph.invoke(
            {"project_id": project_id, "feature_id": feature_id},
            config=self._config(feature_id),
        )

    def resume(self, feature_id: str, resume_value: str) -> dict[str, Any]:
        """
        Resume a paused feature pipeline after a human approval decision.

        Raises GraphNotRunningError if this feature has no paused graph run
        (e.g. the artifact was approved through the legacy manual flow rather
        than a graph run started via start()).
        """
        config = self._config(feature_id)
        state = self._graph.get_state(config)

        if not state.next:
            raise GraphNotRunningError(
                f"No paused graph run found for feature_id={feature_id}"
            )

        logger.info(
            "Resuming graph run for feature_id=%s with decision=%s",
            feature_id,
            resume_value,
        )

        return self._graph.invoke(Command(resume=resume_value), config=config)

    def get_status(self, feature_id: str) -> dict[str, Any]:
        """
        Return the current pending node(s) and state values for a feature's run.
        """
        state = self._graph.get_state(self._config(feature_id))

        return {
            "next": list(state.next),
            "values": dict(state.values),
        }


graph_orchestrator_service = GraphOrchestratorService()
