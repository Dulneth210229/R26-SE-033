"""
Unit tests for CoderAgent.revise()'s control flow -- the new capability
letting a human iterate on an existing Coder Agent run by prompt, the same
way Requirement/Architecture Agent's .revise() already work. No LLM, no
Docker, no git: the planner, coding loop, and verifier are all mocked; only
`store` (real Mongo-backed, matching this repo's established test
convention for feature/project/artifact seeding) is real.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.coder_agent.agent import CoderAgent
from app.agents.coder_agent.planner import CodePlanGenerationError
from app.core.enums import AgentName, ArtifactFormat, ArtifactType
from app.schemas.coder_schema import CoderAgentReviseRequest
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id

EXISTING_PLAN = {
    "files": [
        {"path": "server/src/routes/widget.routes.js", "action": "create", "rationale": "r", "maps_to": []}
    ],
    "new_dependencies": [],
    "env_vars_needed": [],
    "summary": "s",
}


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
    """These pre-existing tests exercise the agentic revision-planning/coding path specifically
    (mocking generate_via_exploration/_code_with_retries directly). Without this, the real,
    unmocked model_capabilities.supports_tool_calling() probe runs against whatever Ollama server
    happens to be configured in this environment -- unreachable in CI/local dev without a running
    Ollama -- and its designed-safe default (False on any probe failure) silently routes these
    tests into the new non-agentic batch coding path instead, which they never mock for."""
    with patch("app.services.model_capabilities.supports_tool_calling", AsyncMock(return_value=True)):
        yield


@pytest.fixture
def feature_with_prior_run(tmp_path):
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Revise Test Project"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Revise Test Feature",
    }

    srs_path = tmp_path / "srs.json"
    srs_path.write_text('{"functional_requirements": []}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.REQUIREMENT.value, ArtifactType.SRS.value, srs_path)

    arch_path = tmp_path / "arch.json"
    arch_path.write_text('{"design_views": {}}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.ARCHITECTURE.value, ArtifactType.ARCHITECTURE_PLAN.value, arch_path)

    plan_path = tmp_path / "code_plan_v1.json"
    plan_path.write_text(json.dumps(EXISTING_PLAN), encoding="utf-8")
    _seed_artifact(feature_id, AgentName.CODER.value, ArtifactType.CODE_PLAN.value, plan_path)

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


ARCHITECTURE_PLAN_WITH_COVERAGE = {
    "design_views": {
        "interface_view": {"api_endpoints": [{"endpoint": "/api/task-comments"}]},
        "data_view": {"data_entities": [{"name": "Comment"}]},
    }
}

PRIOR_PLAN_COVERING_EVERYTHING = {
    "files": [
        {
            "path": "server/src/routes/task-comments.routes.js",
            "action": "create",
            "rationale": "r",
            "maps_to": ["/api/task-comments", "Comment"],
        },
        {
            "path": "client/src/components/CommentList.jsx",
            "action": "create",
            "rationale": "r",
            "maps_to": [],
        },
    ],
    "new_dependencies": [],
    "env_vars_needed": [],
    "summary": "s",
}


@pytest.fixture
def feature_with_two_prior_revisions(tmp_path):
    """
    Reproduces a real bug found only after a *second* revise() call against
    a live feature: v1 is the original, full plan (covers every endpoint/
    entity); v2 is a prior revision's own saved plan, which -- correctly,
    by design -- only lists the delta that revision touched. If coverage
    were checked against only the *latest* version's files, a third
    revision would lose everything v1 covers, since v2 alone doesn't
    restate it.
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Two Revisions Project"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Two Revisions Feature",
    }

    srs_path = tmp_path / "srs.json"
    srs_path.write_text('{"functional_requirements": []}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.REQUIREMENT.value, ArtifactType.SRS.value, srs_path)

    arch_path = tmp_path / "arch.json"
    arch_path.write_text(json.dumps(ARCHITECTURE_PLAN_WITH_COVERAGE), encoding="utf-8")
    _seed_artifact(feature_id, AgentName.ARCHITECTURE.value, ArtifactType.ARCHITECTURE_PLAN.value, arch_path)

    v1_path = tmp_path / "code_plan_v1.json"
    v1_path.write_text(json.dumps(PRIOR_PLAN_COVERING_EVERYTHING), encoding="utf-8")
    _seed_artifact(feature_id, AgentName.CODER.value, ArtifactType.CODE_PLAN.value, v1_path, version=1)

    v2_delta_plan = {
        "files": [
            {
                "path": "client/src/components/CommentList.jsx",
                "action": "modify",
                "rationale": "A prior revision's own delta.",
                "maps_to": [],
            }
        ],
        "new_dependencies": [],
        "env_vars_needed": [],
        "summary": "A prior revision.",
    }
    v2_path = tmp_path / "code_plan_v2.json"
    v2_path.write_text(json.dumps(v2_delta_plan), encoding="utf-8")
    _seed_artifact(feature_id, AgentName.CODER.value, ArtifactType.CODE_PLAN.value, v2_path, version=2)

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


@pytest.fixture
def feature_with_full_coverage_prior_run(tmp_path):
    """
    Prior plan that fully covers a real architecture plan's endpoints/
    entities -- for testing that a revision's own (necessarily partial) new
    plan doesn't get rejected for "missing" things the prior plan, still in
    place, already implements.
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": "Coverage Revise Project"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Coverage Revise Feature",
    }

    srs_path = tmp_path / "srs.json"
    srs_path.write_text('{"functional_requirements": []}', encoding="utf-8")
    _seed_artifact(feature_id, AgentName.REQUIREMENT.value, ArtifactType.SRS.value, srs_path)

    arch_path = tmp_path / "arch.json"
    arch_path.write_text(json.dumps(ARCHITECTURE_PLAN_WITH_COVERAGE), encoding="utf-8")
    _seed_artifact(feature_id, AgentName.ARCHITECTURE.value, ArtifactType.ARCHITECTURE_PLAN.value, arch_path)

    plan_path = tmp_path / "code_plan_v1.json"
    plan_path.write_text(json.dumps(PRIOR_PLAN_COVERING_EVERYTHING), encoding="utf-8")
    _seed_artifact(feature_id, AgentName.CODER.value, ArtifactType.CODE_PLAN.value, plan_path)

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    store.database["artifacts"].delete_many({"feature_id": feature_id})


@pytest.fixture
def feature_with_no_prior_run():
    project_id = generate_id("project")
    feature_id = generate_id("feature")

    store.projects[project_id] = {"project_id": project_id, "project_name": "No Prior Run Project"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "No Prior Run Feature",
    }

    yield {"project_id": project_id, "feature_id": feature_id}

    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})


@pytest.fixture
def agent():
    return CoderAgent()


@pytest.mark.asyncio
async def test_revise_raises_when_no_prior_code_plan_exists(agent, feature_with_no_prior_run):
    request = CoderAgentReviseRequest(revision_comment="Add a loading spinner.")

    with pytest.raises(ValueError, match="No existing Coder Agent output"):
        await agent.revise(feature_with_no_prior_run["feature_id"], request)


@pytest.mark.asyncio
async def test_revise_resumes_existing_branch_not_start_fresh(agent, feature_with_prior_run):
    project_id = feature_with_prior_run["project_id"]
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Add a loading spinner.")

    with (
        patch.object(agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))),
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    mock_workspace.resume_feature_branch.assert_called_once_with(project_id, feature_id)
    mock_workspace.start_feature_branch.assert_not_called()
    assert output.verification_passed is True
    assert output.artifact_ids == ["artifact_new"]


@pytest.mark.asyncio
async def test_revise_resumes_the_branch_before_planning_not_after(agent, feature_with_prior_run):
    """
    Required ordering for the agentic revision planner: its read-only tools
    (list_dir/read_file/search_code) read whatever is currently checked out
    in the workspace, so the feature branch must already be checked out
    before planning starts -- not after, which is how run()'s
    start_feature_branch/planning order works (there, planning happens
    before any branch exists at all).
    """
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Add a loading spinner.")

    call_order = []

    async def _fake_generate_via_exploration(**kwargs):
        call_order.append("generate_via_exploration")
        return EXISTING_PLAN, "raw"

    with (
        patch.object(agent.planner, "generate_via_exploration", new=_fake_generate_via_exploration),
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }
        mock_workspace.resume_feature_branch.side_effect = lambda *a, **k: call_order.append(
            "resume_feature_branch"
        )

        await agent.revise(feature_id, request)

    assert call_order == ["resume_feature_branch", "generate_via_exploration"]


@pytest.mark.asyncio
async def test_revise_frames_the_existing_plan_as_a_revision_not_a_rejection(agent, feature_with_prior_run):
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Add a loading spinner while comments load.")

    captured = {}

    async def _fake_generate_via_exploration(**kwargs):
        captured["previous_plan_json"] = kwargs.get("previous_plan_json")
        captured["validation_feedback"] = kwargs.get("validation_feedback")
        captured["human_comment"] = kwargs.get("human_comment")
        return EXISTING_PLAN, "raw"

    with (
        patch.object(agent.planner, "generate_via_exploration", new=_fake_generate_via_exploration),
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        await agent.revise(feature_id, request)

    assert captured["previous_plan_json"] == EXISTING_PLAN
    assert captured["human_comment"] == request.revision_comment
    # Must NOT claim the existing (already-good) plan was rejected -- that
    # would be false and would confuse the model about what to change.
    assert "REJECTED" not in captured["validation_feedback"]
    assert "HUMAN-REQUESTED REVISION" in captured["validation_feedback"]


@pytest.mark.asyncio
async def test_revise_validates_coverage_against_prior_plan_union_not_delta_alone(
    agent, feature_with_full_coverage_prior_run
):
    """
    Reproduces a real bug found running revise() end-to-end against a live
    feature: the model's new plan for a small, targeted revision (e.g. "add
    a loading spinner") only lists the file(s) that change, not every
    endpoint/entity the *prior* plan already covers -- and the real
    plan_validator (not mocked here) rejected that as incomplete coverage,
    even though the prior plan (still in place, untouched by this revision)
    already implements everything else. Coverage must be checked against the
    union of the prior plan's files and this delta, not the delta alone.
    """
    project_id = feature_with_full_coverage_prior_run["project_id"]
    feature_id = feature_with_full_coverage_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Add a loading spinner while comments load.")

    delta_only_plan = {
        "files": [
            {
                "path": "client/src/components/CommentList.jsx",
                "action": "modify",
                "rationale": "Add loading spinner",
                "maps_to": [],
            }
        ],
        "new_dependencies": [],
        "env_vars_needed": [],
        "summary": "Add a loading state to CommentList.",
    }

    with (
        patch.object(agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(delta_only_plan, "raw"))),
        # plan_validator is intentionally NOT mocked here -- the real coverage
        # check is exactly what this test is verifying.
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    # The delta plan actually coded is still just the delta, not a merged plan.
    assert output.code_plan_json == delta_only_plan
    assert output.verification_passed is True


@pytest.mark.asyncio
async def test_revise_coverage_baseline_spans_every_prior_version_not_just_the_latest(
    agent, feature_with_two_prior_revisions
):
    """
    Reproduces a real bug found running a SECOND revise() against a live
    feature: v1 (the original plan) covers everything; v2 (a prior
    revision's own saved plan) only lists its own delta, by design. A THIRD
    revision's coverage baseline, if built from only the *latest* saved
    plan (v2), would lose everything v1 covers -- exactly the false
    "does not cover these API endpoints" rejection a real user hit through
    the /coder/revise endpoint. The baseline must span every version ever
    saved for this feature, not just the most recent one.
    """
    project_id = feature_with_two_prior_revisions["project_id"]
    feature_id = feature_with_two_prior_revisions["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Now also add a delete confirmation dialog.")

    third_delta_plan = {
        "files": [
            {
                "path": "client/src/components/CommentList.jsx",
                "action": "modify",
                "rationale": "Add delete confirmation dialog",
                "maps_to": [],
            }
        ],
        "new_dependencies": [],
        "env_vars_needed": [],
        "summary": "Add a confirmation dialog before deleting a comment.",
    }

    with (
        patch.object(agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(third_delta_plan, "raw"))),
        # plan_validator is intentionally NOT mocked here -- the real coverage
        # check is exactly what this test is verifying.
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    assert output.code_plan_json == third_delta_plan
    assert output.verification_passed is True


@pytest.mark.asyncio
async def test_revise_retries_exploration_planning_after_it_runs_out_of_turns(
    agent, feature_with_full_coverage_prior_run
):
    """
    Reproduces a real bug found running a genuinely vague revision request
    ("styles are missing, add tailwind css") against a live feature: the
    agentic exploration planner used 16 real tool-calling turns and still
    hadn't called submit_code_plan when its turn budget ran out, raising
    CodePlanGenerationError uncaught -- crashing the whole revise() call
    instead of being treated as a recoverable attempt, the same way
    _code_with_retries already treats a GraphRecursionError from the coding
    loop. This confirms the fix: a CodePlanGenerationError from the
    exploration path is now caught and retried with an efficiency-focused
    hint, not left to crash the request.
    """
    feature_id = feature_with_full_coverage_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Styles are missing, add tailwind css.")

    delta_plan = {
        "files": [
            {
                "path": "client/src/components/CommentList.jsx",
                "action": "modify",
                "rationale": "Add tailwind styling",
                "maps_to": [],
            }
        ],
        "new_dependencies": [],
        "env_vars_needed": [],
        "summary": "Add tailwind styling.",
    }

    captured_feedback = []

    async def _fake_generate_via_exploration(**kwargs):
        captured_feedback.append(kwargs.get("validation_feedback"))
        if len(captured_feedback) == 1:
            raise CodePlanGenerationError(
                "Coder Agent's agentic revision planner ended without calling "
                "submit_code_plan (either it stopped early or hit the exploration turn limit of 50)."
            )
        return delta_plan, "raw"

    with (
        patch.object(agent.planner, "generate_via_exploration", new=_fake_generate_via_exploration),
        # plan_validator is intentionally NOT mocked -- confirms the real coverage
        # union check still passes for the eventual successful attempt.
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    assert len(captured_feedback) == 2
    assert "HUMAN-REQUESTED REVISION" in captured_feedback[0]  # first attempt: normal revision framing
    assert "summarizing tool" in captured_feedback[1]  # second attempt: strategy-change hint fed back
    assert output.code_plan_json == delta_plan
    assert output.verification_passed is True


@pytest.mark.asyncio
async def test_revise_retries_exploration_planning_after_an_unexpected_exception(
    agent, feature_with_full_coverage_prior_run
):
    """
    A real, confirmed bug: revise()'s planning call previously only caught
    CodePlanGenerationError (turn-limit exhaustion) around the exploration planner -- any OTHER
    exception (a transient Ollama/langchain-ollama transport error, a real, plausible occurrence
    against a local model -- already documented elsewhere in this project's history) propagated
    straight out of _plan_with_retries uncaught, crashing the whole revise() call before it ever
    reached the coding loop, let alone _save_artifacts. This is one of the confirmed real
    mechanisms behind a genuine user report: a revision request that appeared to run but
    produced zero changes and no saved artifact. Confirms it's now caught and retried, the same
    way a CodePlanGenerationError already is.
    """
    feature_id = feature_with_full_coverage_prior_run["feature_id"]
    request = CoderAgentReviseRequest(revision_comment="Add edit and delete to item notes.")

    delta_plan = {
        "files": [
            {
                "path": "app/item-notes/page.tsx",
                "action": "modify",
                "rationale": "Add edit/delete actions and clear the input after adding",
                "maps_to": [],
            }
        ],
        "new_dependencies": [],
        "env_vars_needed": [],
        "summary": "Add edit/delete and clear the input field on add.",
    }

    attempts = []

    async def _fake_generate_via_exploration(**kwargs):
        attempts.append(kwargs.get("validation_feedback"))
        if len(attempts) == 1:
            raise RuntimeError("Ollama connection reset")
        return delta_plan, "raw"

    with (
        patch.object(agent.planner, "generate_via_exploration", new=_fake_generate_via_exploration),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    assert len(attempts) == 2
    assert "unexpected error" in attempts[1]
    assert output.code_plan_json == delta_plan
    assert output.verification_passed is True


# ---------------------------------------------------------------------------
# _plan_with_retries' prefer_single_shot fast path (see
# CoderAgent._find_well_specified_target_files) -- a well-specified revision
# comment should skip exploration on attempt 1 and use the single-shot
# planner instead; any failure there must correctly fall through to full
# exploration on attempt 2, never crash the whole call.
# ---------------------------------------------------------------------------

from app.agents.coder_agent.schemas import CoderAgentInput  # noqa: E402

BASE_AGENT_INPUT = CoderAgentInput(
    project={"project_id": "proj_x"},
    feature={"feature_id": "feature_x", "feature_name": "Feature X"},
    srs_json={"functional_requirements": []},
    architecture_plan_json={"design_views": {}},
    project_manifest_json={},
    human_comment="Fix the typo in client/src/components/Footer.tsx",
)


@pytest.mark.asyncio
async def test_prefer_single_shot_uses_single_shot_planner_on_first_attempt(agent):
    """
    The well-specified fast path: attempt 1 must call planner.generate()
    (single-shot, no tool-calling turns), never
    planner.generate_via_exploration(), when prefer_single_shot is True.
    """
    with (
        patch.object(
            agent.planner, "generate", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))
        ) as mock_single_shot,
        patch.object(agent.planner, "generate_via_exploration", new=AsyncMock()) as mock_exploration,
        patch.object(agent.plan_validator, "validate", return_value=None),
    ):
        result = await agent._plan_with_retries(
            BASE_AGENT_INPUT,
            srs_for_planning=BASE_AGENT_INPUT.srs_json,
            exploration_context=("proj_x", "feature_x"),
            prefer_single_shot=True,
        )

        assert result == EXISTING_PLAN
        mock_single_shot.assert_awaited_once()
        mock_exploration.assert_not_called()


@pytest.mark.asyncio
async def test_prefer_single_shot_false_always_uses_exploration(agent):
    """Without prefer_single_shot, exploration_context alone still routes every attempt
    through generate_via_exploration, exactly as before this fast path existed."""
    with (
        patch.object(agent.planner, "generate", new=AsyncMock()) as mock_single_shot,
        patch.object(
            agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))
        ) as mock_exploration,
        patch.object(agent.plan_validator, "validate", return_value=None),
    ):
        result = await agent._plan_with_retries(
            BASE_AGENT_INPUT,
            srs_for_planning=BASE_AGENT_INPUT.srs_json,
            exploration_context=("proj_x", "feature_x"),
            prefer_single_shot=False,
        )

        assert result == EXISTING_PLAN
        mock_single_shot.assert_not_called()
        mock_exploration.assert_awaited_once()


@pytest.mark.asyncio
async def test_prefer_single_shot_falls_back_to_exploration_after_an_exception(agent):
    """
    A real, confirmed design gap this fast path had to close: an uncaught
    exception from the single-shot planner call must not crash the whole
    revision -- attempt 2 must fall through to full exploration and succeed.
    """
    with (
        patch.object(
            agent.planner, "generate", new=AsyncMock(side_effect=RuntimeError("Ollama connection reset"))
        ) as mock_single_shot,
        patch.object(
            agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))
        ) as mock_exploration,
        patch.object(agent.plan_validator, "validate", return_value=None),
    ):
        result = await agent._plan_with_retries(
            BASE_AGENT_INPUT,
            srs_for_planning=BASE_AGENT_INPUT.srs_json,
            exploration_context=("proj_x", "feature_x"),
            prefer_single_shot=True,
        )

    assert result == EXISTING_PLAN
    mock_single_shot.assert_awaited_once()
    mock_exploration.assert_awaited_once()


@pytest.mark.asyncio
async def test_prefer_single_shot_falls_back_to_exploration_after_validation_rejection(agent):
    """The fast path's own guess can be structurally valid JSON but still fail
    plan_validator (e.g. a wrong scope) -- attempt 2 must still fall through to
    exploration and succeed, not exhaust every remaining attempt on single-shot."""
    from app.agents.coder_agent.plan_validator import CodePlanValidationError

    validate_calls = []

    def _fake_validate(*args, **kwargs):
        validate_calls.append(args)
        if len(validate_calls) == 1:
            raise CodePlanValidationError("code_plan_json does not cover these API endpoints: [...]")
        return None

    with (
        patch.object(agent.planner, "generate", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))) as mock_single_shot,
        patch.object(
            agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))
        ) as mock_exploration,
        patch.object(agent.plan_validator, "validate", side_effect=_fake_validate),
    ):
        result = await agent._plan_with_retries(
            BASE_AGENT_INPUT,
            srs_for_planning=BASE_AGENT_INPUT.srs_json,
            exploration_context=("proj_x", "feature_x"),
            prefer_single_shot=True,
        )

    assert result == EXISTING_PLAN
    mock_single_shot.assert_awaited_once()
    mock_exploration.assert_awaited_once()
    assert len(validate_calls) == 2


@pytest.mark.asyncio
async def test_revise_end_to_end_uses_single_shot_planner_for_a_well_specified_comment(
    agent, feature_with_prior_run
):
    """
    revise() itself, not just _plan_with_retries directly: a comment naming a
    real file this feature has already touched (server/src/routes/widget.routes.js,
    seeded by feature_with_prior_run's own EXISTING_PLAN) must compute
    prefer_single_shot=True and route through planner.generate(), never
    planner.generate_via_exploration().
    """
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(
        revision_comment="Fix the typo in server/src/routes/widget.routes.js"
    )

    with (
        patch.object(agent.planner, "generate", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))),
        patch.object(agent.planner, "generate_via_exploration", new=AsyncMock()) as mock_exploration,
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    mock_exploration.assert_not_called()
    assert output.code_plan_json == EXISTING_PLAN


@pytest.mark.asyncio
async def test_revise_end_to_end_uses_single_shot_planner_for_a_plain_english_comment(
    agent, feature_with_prior_run
):
    """
    Tier 1a end-to-end: a comment that never names widget.routes.js by path or basename,
    but describes it in plain English closely enough to fuzzy-match
    (_find_keyword_matched_known_files), must ALSO route through planner.generate() and
    skip planner.generate_via_exploration() -- the whole point of this session's fix (the
    user's own reported workflow is plain English, not exact filenames).
    """
    feature_id = feature_with_prior_run["feature_id"]
    # "widget" + "route" (from "routing") both overlap with widget.routes.js's own basename
    # stems {"widget", "route"} -- no exact path or extension named anywhere.
    request = CoderAgentReviseRequest(
        revision_comment="The widget routing endpoint returns the wrong status code"
    )

    with (
        patch.object(agent.planner, "generate", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))),
        patch.object(agent.planner, "generate_via_exploration", new=AsyncMock()) as mock_exploration,
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    mock_exploration.assert_not_called()
    assert output.code_plan_json == EXISTING_PLAN


@pytest.mark.asyncio
async def test_revise_keeps_exploration_for_a_genuinely_vague_comment_with_no_name_match(
    agent, feature_with_prior_run
):
    """
    Regression guard: a comment with no real name-shaped signal at all (neither Tier 0 nor
    Tier 1a) must still route through the unchanged full exploration path -- confirms the
    new tiers don't accidentally widen what counts as "well-specified."
    """
    feature_id = feature_with_prior_run["feature_id"]
    request = CoderAgentReviseRequest(
        revision_comment="Styles are missing, add tailwind css"
    )

    with (
        patch.object(agent.planner, "generate", new=AsyncMock()) as mock_single_shot,
        patch.object(
            agent.planner, "generate_via_exploration", new=AsyncMock(return_value=(EXISTING_PLAN, "raw"))
        ) as mock_exploration,
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }

        output = await agent.revise(feature_id, request)

    mock_single_shot.assert_not_called()
    mock_exploration.assert_awaited_once()
    assert output.code_plan_json == EXISTING_PLAN


# ---------------------------------------------------------------------------
# MongoDB URI short-circuit (env_uri.py) -- a revision comment that's JUST a
# MongoDB URI skips the whole plan/code/verify cycle entirely.
# ---------------------------------------------------------------------------

from app.agents.coder_agent.schemas import CoderAgentEnvSaveResult  # noqa: E402


@pytest.mark.asyncio
async def test_revise_short_circuits_on_uri_only_comment(agent, feature_with_prior_run):
    project_id = feature_with_prior_run["project_id"]
    feature_id = feature_with_prior_run["feature_id"]
    uri = "mongodb+srv://user:pass@cluster.mongodb.net/mydb"
    request = CoderAgentReviseRequest(revision_comment=uri)

    with (
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
        patch.object(agent.planner, "generate_via_exploration") as mock_generate,
    ):
        # restart_if_running (relocated onto preview_service itself -- see that module's own
        # restart_if_running docstring) is the ONE call CoderAgent makes now; its own no-op-when-
        # stopped/restart-when-running logic is covered directly by test_preview_service.py.
        mock_preview.restart_if_running.return_value = False

        output = await agent.revise(feature_id, request)

    assert isinstance(output, CoderAgentEnvSaveResult)
    assert output.saved is True
    assert output.preview_restarted is False
    mock_preview.restart_if_running.assert_called_once_with(feature_id)
    mock_workspace.write_env_local.assert_called_once_with(project_id, {"MONGODB_URI": uri})
    # The whole point: no planning, no coding loop, nothing touched the workspace.
    mock_generate.assert_not_called()
    mock_workspace.resume_feature_branch.assert_not_called()


@pytest.mark.asyncio
async def test_revise_short_circuit_restarts_a_running_preview(agent, feature_with_prior_run):
    feature_id = feature_with_prior_run["feature_id"]
    uri = "mongodb://localhost:27017/mydb"
    request = CoderAgentReviseRequest(revision_comment=uri)

    with (
        patch("app.agents.coder_agent.agent.workspace_service"),
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
    ):
        mock_preview.restart_if_running.return_value = True

        output = await agent.revise(feature_id, request)

    assert output.preview_restarted is True
    mock_preview.restart_if_running.assert_called_once_with(feature_id)
    assert "Restarting the live preview" in output.message


@pytest.mark.asyncio
async def test_revise_with_uri_and_other_instructions_does_not_short_circuit(agent, feature_with_prior_run):
    feature_id = feature_with_prior_run["feature_id"]
    uri = "mongodb://localhost:27017/mydb"
    request = CoderAgentReviseRequest(revision_comment=f"{uri} also add a loading spinner")

    captured_human_comment = {}

    async def _fake_generate_via_exploration(**kwargs):
        captured_human_comment["value"] = kwargs.get("human_comment")
        return EXISTING_PLAN, "raw"

    with (
        patch.object(agent.planner, "generate_via_exploration", new=_fake_generate_via_exploration),
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }
        mock_workspace.read_env_local.return_value = {}

        output = await agent.revise(feature_id, request)

    # The URI is still saved as a side effect...
    mock_workspace.write_env_local.assert_called_once_with(
        feature_with_prior_run["project_id"], {"MONGODB_URI": uri}
    )
    # ...but the credential never reaches the planner, and the real instructions do.
    assert uri not in captured_human_comment["value"]
    assert "loading spinner" in captured_human_comment["value"]
    # ...and the normal revise() flow ran to completion (a real CoderAgentOutput, not a short-circuit).
    assert output.code_plan_json == EXISTING_PLAN


@pytest.mark.asyncio
async def test_revise_never_saves_a_uri_from_a_machine_generated_revision_comment(agent, feature_with_prior_run):
    # Real, confirmed bug this closes: a Security Agent finding's own root_cause text quoted the
    # exact offending source line containing a fake, LLM-invented MongoDB URI -- extract_mongodb_uri
    # matched it and silently overwrote the human's real .env.local value. revised_by="security_agent_report"
    # (already set correctly by the real frontend trigger, SecurityDecisionDialog.jsx/ResultTab.jsx)
    # is what this fix uses to recognize the comment isn't genuinely human-typed.
    feature_id = feature_with_prior_run["feature_id"]
    fake_uri = "mongodb+srv://finodil_admin:Sup3rSecretPass!@cluster0.abcde.mongodb.net/finodil"
    revision_comment = (
        "Fix the following security findings reported by the Security Agent:\n\n"
        "[CRITICAL] lib/mongodb.ts:6 -- MongoDB connection string with an embedded, hardcoded "
        "credential (CWE-798)\n"
        f'  Root cause: The hardcoded MongoDB URI with credentials: `const FALLBACK_MONGODB_URI = "{fake_uri}";`'
    )
    request = CoderAgentReviseRequest(revision_comment=revision_comment, revised_by="security_agent_report")

    # Mock BOTH real planning paths (this comment names a real file, "lib/mongodb.ts:6," so it
    # may route through either the fast well-specified-file path or full exploration -- which one
    # is irrelevant to what this test verifies) and capture whichever actually gets called.
    captured_human_comment = {}

    async def _fake_generate(**kwargs):
        captured_human_comment["value"] = kwargs.get("human_comment")
        return EXISTING_PLAN, "raw"

    async def _fake_generate_via_exploration(**kwargs):
        captured_human_comment["value"] = kwargs.get("human_comment")
        return EXISTING_PLAN, "raw"

    with (
        patch.object(agent.planner, "generate", new=_fake_generate),
        patch.object(agent.planner, "generate_via_exploration", new=_fake_generate_via_exploration),
        patch.object(agent.plan_validator, "validate", return_value=None),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
        patch("app.agents.coder_agent.agent.preview_service") as mock_preview,
        patch.object(
            agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))
        ),
        patch.object(agent, "_save_artifacts", return_value=["artifact_new"]),
    ):
        mock_workspace.diff_against_main.return_value = {
            "added": [], "modified": [], "deleted": [], "diff_text": ""
        }
        mock_workspace.read_env_local.return_value = {}

        output = await agent.revise(feature_id, request)

    # The fake URI must NEVER be written to .env.local.
    mock_workspace.write_env_local.assert_not_called()
    mock_preview.restart_if_running.assert_not_called()
    # The full finding text -- fake URI included -- must reach the planner untouched: it's
    # necessary vulnerability-description context, not a real secret to strip.
    assert fake_uri in captured_human_comment["value"]
    assert "CWE-798" in captured_human_comment["value"]
    assert output.code_plan_json == EXISTING_PLAN
