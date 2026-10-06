"""
Unit tests for CoderAgent.run_stream()/revise_stream()/_code_with_retries_stream() --
the new NDJSON-streaming chat parity feature (composer clears instantly, tokens/phase
events surface live, revise() reachable through the same chat). No LLM, no Docker, no
git: the planner/coding-loop/verifier/workspace_service layers are all mocked, matching
this repo's established idiom (see test_coder_agent_retries.py/test_coder_agent_revise.py).
Only `store` (real Mongo-backed) is real, for seeding approved-artifact fixtures.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.coder_agent.agent import CoderAgent
from app.agents.coder_agent.plan_validator import CodePlanValidationError
from app.agents.coder_agent.planner import CodePlanGenerationError
from app.core.enums import AgentName, ArtifactFormat, ArtifactType
from app.schemas.coder_schema import CoderAgentReviseRequest, CoderAgentRunRequest
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

CODE_PLAN = {
    "files": [
        {"path": "app/api/widgets/route.ts", "action": "create", "rationale": "r", "maps_to": []},
    ],
    "new_dependencies": [],
    "env_vars_needed": [],
    "summary": "A plan.",
}


class _FakeProvider:
    """Minimal stand-in for BaseLLMProvider -- .stream() is a sync method returning an
    async generator (never awaited itself, matching provider.stream's real signature),
    .invoke_agent() is a plain awaited coroutine."""

    def __init__(self, chunks: list[str], invoke_agent_return: str = ""):
        self._chunks = chunks
        self.invoke_agent = AsyncMock(return_value=invoke_agent_return)

    def stream(self, prompt, system_prompt=None, **kwargs):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()


def _touched(paths):
    return {"added": list(paths), "modified": [], "deleted": []}


def _make_react_agent(states=None, raise_exc=None):
    """
    Build a react_agent test double for _code_with_retries_stream's real usage:
    `async for state in react_agent.astream(..., stream_mode="values")` -- .astream(...) is a
    plain (sync) callable returning an async generator, never awaited itself, unlike the old
    .ainvoke(...) it replaced. `states` is a list of {"messages": [...]} dicts (mimicking
    stream_mode="values"' cumulative-state shape); if raise_exc is given, it's raised from
    inside the generator after yielding every state, matching where a real GraphRecursionError/
    CancelledError/other exception would actually surface.
    """
    mock_agent = MagicMock()

    def _astream(*args, **kwargs):
        async def _gen():
            for state in states or []:
                yield state
            if raise_exc is not None:
                raise raise_exc

        return _gen()

    mock_agent.astream = _astream
    return mock_agent


def _seed_artifact(feature_id: str, agent_name: str, artifact_type: str, file_path, version: int = 1) -> str:
    artifact_id = generate_id("artifact")
    store.artifacts[artifact_id] = {
        "artifact_id": artifact_id,
        "feature_id": feature_id,
        "agent_name": agent_name,
        "artifact_type": artifact_type,
        "artifact_format": ArtifactFormat.JSON.value,
        "approval_status": "approved",
        "file_path": str(file_path),
        "version": version,
    }
    return artifact_id


@pytest.fixture(autouse=True)
def _assume_tool_calling_supported():
    """These pre-existing tests exercise the agentic coding path specifically (they assert on
    "coding_attempt_N_of_3" phase events / mock build_coder_react_agent). Without this, the
    real, unmocked model_capabilities.supports_tool_calling() probe runs against whatever Ollama
    server happens to be configured in this environment -- unreachable in CI/local dev without a
    running Ollama -- and its designed-safe default (False on any probe failure) silently routes
    these tests into the new non-agentic batch path instead, which they never mock for."""
    with patch("app.services.model_capabilities.supports_tool_calling", AsyncMock(return_value=True)):
        yield


@pytest.fixture
def agent():
    return CoderAgent()


@pytest.fixture
def feature_ready_for_run(tmp_path):
    """Approved SRS + approved Architecture Plan, no prior Coder Agent run -- run_stream's
    precondition."""
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Stream Test Project"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Stream Test Feature",
    }

    srs_path = tmp_path / "srs.json"
    srs_path.write_text('{"functional_requirements": []}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.REQUIREMENT.value, ArtifactType.SRS.value, srs_path)

    arch_path = tmp_path / "arch.json"
    arch_path.write_text('{"design_views": {}}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.ARCHITECTURE.value, ArtifactType.ARCHITECTURE_PLAN.value, arch_path)

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


@pytest.fixture
def feature_with_prior_run(tmp_path):
    """Approved SRS + approved Architecture Plan + an existing CODE_PLAN -- revise_stream's
    precondition."""
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Revise Stream Project"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Revise Stream Feature",
    }

    srs_path = tmp_path / "srs.json"
    srs_path.write_text('{"functional_requirements": []}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.REQUIREMENT.value, ArtifactType.SRS.value, srs_path)

    arch_path = tmp_path / "arch.json"
    arch_path.write_text('{"design_views": {}}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.ARCHITECTURE.value, ArtifactType.ARCHITECTURE_PLAN.value, arch_path)

    plan_path = tmp_path / "code_plan_v1.json"
    plan_path.write_text(json.dumps(CODE_PLAN), encoding="utf-8")
    _seed_artifact(feature_id, AgentName.CODER.value, ArtifactType.CODE_PLAN.value, plan_path)

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


async def _collect(agen):
    return [event async for event in agen]


# ---------------------------------------------------------------------------
# run_stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_stream_yields_tokens_during_planning_and_a_final_done_on_clean_pass(
    agent, feature_ready_for_run
):
    feature_id = feature_ready_for_run["feature_id"]
    request = CoderAgentRunRequest()

    chunks = [json.dumps(CODE_PLAN)[i : i + 5] for i in range(0, len(json.dumps(CODE_PLAN)), 5)]
    fake_provider = _FakeProvider(chunks)

    with (
        patch("app.agents.coder_agent.agent.llm_provider_service") as mock_llm_service,
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.build_coder_react_agent") as mock_build_react_agent,
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_llm_service.get_provider.return_value = fake_provider
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }
        mock_workspace.get_touched_files.return_value = _touched(["app/api/widgets/route.ts"])
        mock_build_react_agent.return_value = _make_react_agent()

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            events = await _collect(agent.run_stream(feature_id, request))

    token_events = [e for e in events if e["type"] == "token"]
    phase_events = [e for e in events if e["type"] == "phase"]
    done_events = [e for e in events if e["type"] == "done"]

    assert len(token_events) == len(chunks)
    assert "".join(e["text"] for e in token_events) == json.dumps(CODE_PLAN)
    assert any(e["phase"] == "planning_attempt_1_of_4" for e in phase_events)
    assert any(e["phase"] == "preparing_workspace" for e in phase_events)
    assert any(e["phase"] == "coding_attempt_1_of_3" for e in phase_events)
    assert any(e["phase"] == "verifying_attempt_1" for e in phase_events)
    assert any(e["phase"] == "diffing" for e in phase_events)

    assert len(done_events) == 1
    assert done_events[0]["verification_passed"] is True
    assert done_events[0]["status"] == "completed"
    assert done_events[0]["artifact_ids"] == ["artifact_new"]

    mock_preview.stop_preview_if_running.assert_called_once_with(feature_id)
    mock_workspace.start_feature_branch.assert_called_once()


@pytest.mark.asyncio
async def test_run_stream_planning_retries_on_validator_rejection(agent, feature_ready_for_run):
    feature_id = feature_ready_for_run["feature_id"]
    request = CoderAgentRunRequest()

    plan_text = json.dumps(CODE_PLAN)
    fake_provider = _FakeProvider([plan_text])

    with (
        patch("app.agents.coder_agent.agent.llm_provider_service") as mock_llm_service,
        patch.object(
            agent.plan_validator,
            "validate",
            side_effect=[CodePlanValidationError("missing endpoint coverage"), None],
        ) as mock_validate,
        patch("app.agents.coder_agent.agent.preview_service"),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.build_coder_react_agent") as mock_build_react_agent,
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_llm_service.get_provider.return_value = fake_provider
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }
        mock_workspace.get_touched_files.return_value = _touched(["app/api/widgets/route.ts"])
        mock_build_react_agent.return_value = _make_react_agent()

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            events = await _collect(agent.run_stream(feature_id, request))

        validate_call_count = mock_validate.call_count

    phase_events = [e for e in events if e["type"] == "phase"]
    assert any(e["phase"] == "planning_attempt_1_of_4" for e in phase_events)
    assert any(e["phase"] == "planning_attempt_2_of_4" for e in phase_events)
    assert validate_call_count == 2

    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["verification_passed"] is True


@pytest.mark.asyncio
async def test_run_stream_yields_error_event_when_plan_json_is_unparseable(agent, feature_ready_for_run):
    feature_id = feature_ready_for_run["feature_id"]
    request = CoderAgentRunRequest()

    fake_provider = _FakeProvider(["not valid json at all"], invoke_agent_return="still not valid json")

    with patch("app.agents.coder_agent.agent.llm_provider_service") as mock_llm_service:
        mock_llm_service.get_provider.return_value = fake_provider

        events = await _collect(agent.run_stream(feature_id, request))

    assert events[-1]["type"] == "error"
    assert "could not produce valid code_plan_json" in events[-1]["message"]
    # A parse failure is terminal (matches generate()'s own behavior) -- never retried
    # across planning attempts, unlike a validator rejection.
    assert len([e for e in events if e["type"] == "phase" and e["phase"].startswith("planning_attempt")]) == 1


@pytest.mark.asyncio
async def test_run_stream_yields_error_event_for_missing_srs(agent):
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": "No SRS Project"}
    store.features[feature_id] = {
        "project_id": project_id, "feature_id": feature_id, "feature_name": "No SRS Feature"
    }

    try:
        events = await _collect(agent.run_stream(feature_id, CoderAgentRunRequest()))
    finally:
        store.database["projects"].delete_one({"project_id": project_id})
        store.database["features"].delete_one({"feature_id": feature_id})

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert "No approved SRS" in events[0]["message"]


# ---------------------------------------------------------------------------
# revise_stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_stream_never_yields_a_token_event(agent, feature_with_prior_run):
    """Planning for revise() is the agentic exploration loop -- there is nothing to
    token-stream, only phase events with an elapsed-time counter on the frontend side."""
    project_id = feature_with_prior_run["project_id"]
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Add a loading spinner.")

    with (
        patch.object(agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(CODE_PLAN, "raw"))),
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.build_coder_react_agent") as mock_build_react_agent,
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }
        mock_workspace.get_touched_files.return_value = _touched(["app/api/widgets/route.ts"])
        mock_build_react_agent.return_value = _make_react_agent()

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            events = await _collect(agent.revise_stream(feature_id, request))

    assert not any(e["type"] == "token" for e in events)
    assert any(e["type"] == "phase" and e["phase"] == "planning" for e in events)
    assert events[-1]["type"] == "done"
    assert events[-1]["status"] == "revised"

    mock_preview.stop_preview_if_running.assert_called_once_with(feature_id)
    mock_workspace.resume_feature_branch.assert_called_once_with(project_id, feature_id)
    mock_workspace.start_feature_branch.assert_not_called()


@pytest.mark.asyncio
async def test_revise_stream_resumes_branch_before_planning_not_after(agent, feature_with_prior_run):
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Add a loading spinner.")

    call_order = []

    async def _fake_generate_via_exploration(**kwargs):
        call_order.append("generate_via_exploration")
        return CODE_PLAN, "raw"

    with (
        patch.object(agent.planner, "generate_via_exploration", new=_fake_generate_via_exploration),
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.preview_service"),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.build_coder_react_agent") as mock_build_react_agent,
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }
        mock_workspace.get_touched_files.return_value = _touched(["app/api/widgets/route.ts"])
        mock_workspace.resume_feature_branch.side_effect = lambda *a, **k: call_order.append(
            "resume_feature_branch"
        )
        mock_build_react_agent.return_value = _make_react_agent()

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            await _collect(agent.revise_stream(feature_id, request))

    assert call_order == ["resume_feature_branch", "generate_via_exploration"]


@pytest.mark.asyncio
async def test_revise_stream_yields_error_event_when_planning_ultimately_fails(agent, feature_with_prior_run):
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Do something vague.")

    with (
        patch.object(
            agent.planner,
            "generate_via_exploration",
            new=AsyncMock(side_effect=CodePlanGenerationError("never called submit_code_plan")),
        ),
        patch("app.agents.coder_agent.agent.preview_service"),
        patch("app.agents.coder_agent.agent.workspace_service"),
    ):
        events = await _collect(agent.revise_stream(feature_id, request))

    assert events[-1]["type"] == "error"
    assert "could not produce a valid revision plan" in events[-1]["message"]


# ---------------------------------------------------------------------------
# _code_with_retries_stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stopping_mid_coding_attempt_commits_partial_progress_before_propagating(agent):
    """The single most important new test: a genuine Stop (client disconnect) raises
    asyncio.CancelledError from inside react_agent.ainvoke -- confirms commit_changes runs
    before the exception propagates, so Stop's guarantee matches the existing
    GraphRecursionError case rather than silently leaving uncommitted working-tree changes."""
    mock_react_agent = _make_react_agent(raise_exc=asyncio.CancelledError())

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        result_holder = {}
        with pytest.raises(asyncio.CancelledError):
            await _collect(
                agent._code_with_retries_stream("proj_x", "feature_x", CODE_PLAN, result_holder)
            )

    mock_workspace.commit_changes.assert_called_once()
    call_kwargs = mock_workspace.commit_changes.call_args
    assert "(stopped)" in call_kwargs.kwargs.get("message", "") or "(stopped)" in str(call_kwargs)
    # Nothing was ever saved -- the stream tore down mid-attempt.
    assert "verify_result" not in result_holder


@pytest.mark.asyncio
async def test_code_with_retries_stream_verify_runs_off_the_event_loop(agent):
    """verify() is a blocking, synchronous, multi-minute call -- confirms it's invoked via
    asyncio.to_thread on the streaming path (unlike the non-streaming path, which is
    already insulated from this by FastAPI's automatic sync-route threadpool)."""
    mock_react_agent = _make_react_agent()

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.asyncio.to_thread", new=AsyncMock()) as mock_to_thread,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.return_value = _touched(["app/api/widgets/route.ts"])
        mock_to_thread.return_value = {"passed": True, "steps": []}

        result_holder = {}
        events = await _collect(
            agent._code_with_retries_stream("proj_x", "feature_x", CODE_PLAN, result_holder)
        )

    mock_to_thread.assert_called_once_with(
        agent.verifier.verify, "proj_x", "feature_x", CODE_PLAN, None
    )
    assert result_holder["verify_result"]["passed"] is True
    assert result_holder["coding_attempts"] == 1
    assert any(e["phase"] == "verifying_attempt_1" for e in events if e["type"] == "phase")


@pytest.mark.asyncio
async def test_code_with_retries_stream_done_reflects_failing_verify(agent):
    mock_react_agent = _make_react_agent()

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.return_value = _touched(["app/api/widgets/route.ts"])

        with patch.object(
            agent.verifier, "verify", return_value={"passed": False, "steps": [{"name": "build", "status": "failed", "output": "boom"}]}
        ):
            result_holder = {}
            await _collect(agent._code_with_retries_stream("proj_x", "feature_x", CODE_PLAN, result_holder))

    assert result_holder["verify_result"]["passed"] is False
    assert result_holder["coding_attempts"] == 3


@pytest.mark.asyncio
async def test_code_with_retries_stream_yields_tool_activity_events_live(agent):
    """The direct fix for 'must dynamically interact... in live': real tool calls/results
    from the coding loop surface as {"type": "tool_activity"} events as they happen, not just
    a static phase label for the whole attempt."""
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    states = [
        {"messages": [HumanMessage(content="task")]},
        {
            "messages": [
                HumanMessage(content="task"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "read_file", "args": {"path": "app/item-notes/page.tsx"}, "id": "1", "type": "tool_call"},
                    ],
                ),
            ]
        },
        {
            "messages": [
                HumanMessage(content="task"),
                AIMessage(content="", tool_calls=[{"name": "read_file", "args": {"path": "app/item-notes/page.tsx"}, "id": "1", "type": "tool_call"}]),
                ToolMessage(content="file contents here", name="read_file", tool_call_id="1"),
            ]
        },
    ]
    mock_react_agent = _make_react_agent(states=states)

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.return_value = _touched(["app/api/widgets/route.ts"])

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            result_holder = {}
            events = await _collect(
                agent._code_with_retries_stream("proj_x", "feature_x", CODE_PLAN, result_holder)
            )

    tool_events = [e for e in events if e["type"] == "tool_activity"]
    assert len(tool_events) == 2
    assert tool_events[0]["tool"] == "read_file"
    assert "app/item-notes/page.tsx" in tool_events[0]["label"]
    assert tool_events[1]["tool"] == "read_file"
    assert "file contents here" in tool_events[1]["label"]


@pytest.mark.asyncio
async def test_code_with_retries_stream_recovers_from_an_unexpected_exception(agent):
    """A real, confirmed bug: an uncaught exception mid-attempt (not GraphRecursionError, not
    a Stop) previously propagated straight out, skipping commit_changes/verify/_save_artifacts
    entirely and leaving zero trace -- indistinguishable from 'the agent did nothing'. Confirms
    it's now treated like any other failed attempt: committed, retried, and an honest failed
    result is eventually returned instead of the whole stream crashing silently."""
    mock_react_agent = _make_react_agent(raise_exc=RuntimeError("Ollama connection reset"))

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.return_value = _touched([])

        with patch.object(agent.verifier, "verify") as mock_verify:
            result_holder = {}
            events = await _collect(
                agent._code_with_retries_stream("proj_x", "feature_x", CODE_PLAN, result_holder)
            )

            # The expensive verify() gate must never be reached for an attempt that crashed --
            # the plan-gap check (fed by the honest empty touched-files result) catches it first.
            assert mock_verify.call_count == 0

    assert result_holder["coding_attempts"] == 3
    assert result_holder["verify_result"]["passed"] is False
    # commit_changes must still have been attempted on every failed attempt -- partial progress
    # from before the crash is never silently discarded.
    assert mock_workspace.commit_changes.call_count == 3
    failure_output = result_holder["verify_result"]["steps"][0]["output"]
    assert "Ollama connection reset" in failure_output
    # A real "done" event must still be reachable by the caller (run_stream/revise_stream) --
    # this generator itself doesn't yield "done" (that's the caller's job), but it must return
    # normally rather than raising, which _collect() completing above already proves.
    assert any(e["type"] == "phase" for e in events)


@pytest.mark.asyncio
async def test_code_with_retries_stream_recovers_from_commit_changes_failure(agent):
    """A less common but real failure mode: commit_changes() itself raises (e.g. a stale git
    index.lock). Must not crash the whole stream -- treated as a failed attempt, same as any
    other unexpected error."""
    mock_react_agent = _make_react_agent(states=[])

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.side_effect = RuntimeError("index.lock exists")
        mock_workspace.get_touched_files.return_value = _touched([])

        with patch.object(agent.verifier, "verify") as mock_verify:
            result_holder = {}
            await _collect(
                agent._code_with_retries_stream("proj_x", "feature_x", CODE_PLAN, result_holder)
            )
            assert mock_verify.call_count == 0

    assert result_holder["verify_result"]["passed"] is False
    failure_output = result_holder["verify_result"]["steps"][0]["output"]
    assert "index.lock exists" in failure_output


# ---------------------------------------------------------------------------
# revise_stream: MongoDB URI short-circuit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revise_stream_short_circuits_on_uri_only_comment(agent, feature_with_prior_run):
    project_id = feature_with_prior_run["project_id"]
    feature_id = feature_with_prior_run["feature_id"]
    uri = "mongodb+srv://user:pass@cluster.mongodb.net/mydb"
    request = CoderAgentReviseRequest(revision_comment=uri)

    with (
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
        patch.object(agent.planner, "generate_via_exploration") as mock_generate,
    ):
        # restart_if_running (relocated onto preview_service itself) is the ONE call CoderAgent
        # makes now -- its own no-op-when-stopped/restart-when-running logic is covered directly
        # by test_preview_service.py.
        mock_preview.restart_if_running.return_value = False

        events = await _collect(agent.revise_stream(feature_id, request))

    mock_preview.restart_if_running.assert_called_once_with(feature_id)
    mock_workspace.write_env_local.assert_called_once_with(project_id, {"MONGODB_URI": uri})
    mock_generate.assert_not_called()
    mock_workspace.resume_feature_branch.assert_not_called()

    assert not any(e["type"] == "token" for e in events)
    phase_events = [e for e in events if e["type"] == "phase"]
    assert any(e["phase"] == "database_connection_saved" for e in phase_events)
    assert not any(e["phase"] == "restarting_preview" for e in phase_events)

    done_events = [e for e in events if e["type"] == "done"]
    assert len(done_events) == 1
    assert done_events[0]["status"] == "database_connection_saved"
    assert done_events[0]["artifact_ids"] == []
    assert done_events[0]["verification_passed"] is None


@pytest.mark.asyncio
async def test_revise_stream_short_circuit_restarts_running_preview(agent, feature_with_prior_run):
    feature_id = feature_with_prior_run["feature_id"]
    uri = "mongodb://localhost:27017/mydb"
    request = CoderAgentReviseRequest(revision_comment=uri)

    with (
        patch("app.agents.coder_agent.agent.workspace_service"),
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
    ):
        mock_preview.restart_if_running.return_value = True

        events = await _collect(agent.revise_stream(feature_id, request))

    mock_preview.restart_if_running.assert_called_once_with(feature_id)
    phase_events = [e for e in events if e["type"] == "phase"]
    assert any(e["phase"] == "restarting_preview" for e in phase_events)
    assert "Restarting the live preview" in events[-1]["message"]
