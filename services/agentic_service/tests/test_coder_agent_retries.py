"""
Unit tests for CoderAgent._code_with_retries's control flow. No LLM, no
Docker, no git -- build_coder_react_agent/workspace_service/coder_verifier
are all mocked so this exercises pure control flow: does a GraphRecursionError
get treated as a failed attempt (committed, retried with a targeted message)
instead of crashing the whole run; does a plan-gap correctly skip the
expensive verify() call; does a passing verify() short-circuit further
attempts.
"""

from unittest.mock import AsyncMock, patch

import pytest
from langgraph.errors import GraphRecursionError

from app.agents.coder_agent.agent import CoderAgent

CODE_PLAN = {
    "files": [
        {"path": "server/src/routes/widget.routes.js", "action": "create", "rationale": "r", "maps_to": []},
    ]
}


@pytest.fixture
def agent():
    return CoderAgent()


def _touched(paths):
    return {"added": list(paths), "modified": [], "deleted": []}


@pytest.mark.asyncio
async def test_graph_recursion_error_is_treated_as_failed_attempt_not_a_crash(agent):
    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.side_effect = GraphRecursionError("Recursion limit of 100 reached")

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.return_value = _touched([])

        verify_result, attempts = await agent._code_with_retries("proj_x", "feature_x", CODE_PLAN)

    assert attempts == 3
    assert verify_result["passed"] is False
    assert mock_react_agent.ainvoke.call_count == 3
    # commit_changes still runs even when the loop raised -- partial progress isn't lost.
    assert mock_workspace.commit_changes.call_count == 3


@pytest.mark.asyncio
async def test_graph_recursion_error_feedback_asks_for_efficiency_on_next_attempt(agent):
    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.side_effect = [
        GraphRecursionError("Recursion limit reached"),
        None,
    ]

    captured_messages = []

    def _fake_build_task_message(
        code_plan_json, prior_failure_output=None, already_touched=None, original_request=None,
        implementation_spec_section=None,
    ):
        captured_messages.append(prior_failure_output)
        return "task message"

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.build_task_message", side_effect=_fake_build_task_message),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.side_effect = [
            _touched([]),  # attempt 1: recursion error, nothing touched
            _touched(["server/src/routes/widget.routes.js"]),  # attempt 2: file done
        ]

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}) as mock_verify:
            verify_result, attempts = await agent._code_with_retries("proj_x", "feature_x", CODE_PLAN)

    assert attempts == 2
    assert verify_result["passed"] is True
    assert mock_verify.call_count == 1
    # Second attempt's task message must have received feedback mentioning the
    # recursion limit and asking the model to work efficiently.
    assert captured_messages[1] is not None
    assert "ran out of turns" in captured_messages[1]
    assert "work efficiently" in captured_messages[1]


@pytest.mark.asyncio
async def test_plan_gap_skips_expensive_verify_call(agent):
    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.return_value = None

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        # Planned file never touched -- should trigger the gap gate, not verify().
        mock_workspace.get_touched_files.return_value = _touched([])

        with patch.object(agent.verifier, "verify") as mock_verify:
            verify_result, attempts = await agent._code_with_retries("proj_x", "feature_x", CODE_PLAN)

            assert mock_verify.call_count == 0

    assert attempts == 3
    assert verify_result["passed"] is False


@pytest.mark.asyncio
async def test_revision_start_sha_prevents_a_no_op_attempt_from_falsely_passing(agent):
    """
    Reproduces the real, confirmed bug directly: a file was already touched by
    an EARLIER revision (so it permanently differs from `main`), but THIS
    attempt's coding loop makes zero real changes. Without revision_start_sha,
    get_touched_files(since=main) would still report the file as "touched"
    (since it's never reverted), the plan-gap check would see no gaps, and
    verify() would run and pass against the PRIOR revision's already-working
    code -- a false "verification: PASSED" for an attempt that did nothing.
    With revision_start_sha threaded through, get_touched_files is asked
    "touched since THIS attempt started," correctly reports nothing touched,
    and the loop must retry/exhaust instead of silently succeeding.
    """
    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.return_value = None  # the loop runs but writes nothing new

    revision_start_sha = "deadbeef"

    def _fake_get_touched_files(project_id, feature_id, since="main"):
        if since == revision_start_sha:
            # Nothing touched since THIS attempt actually started.
            return _touched([])
        # Relative to main, the file still looks touched -- it was modified
        # by an earlier, already-committed revision and never reverted.
        return _touched(["server/src/routes/widget.routes.js"])

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.side_effect = _fake_get_touched_files

        with patch.object(agent.verifier, "verify") as mock_verify:
            verify_result, attempts = await agent._code_with_retries(
                "proj_x", "feature_x", CODE_PLAN, revision_start_sha=revision_start_sha
            )

            # The expensive verify() gate must never be reached for a genuinely
            # no-op attempt -- the plan-gap check must catch it first.
            assert mock_verify.call_count == 0

    assert attempts == 3
    assert verify_result["passed"] is False


@pytest.mark.asyncio
async def test_passing_verify_short_circuits_remaining_attempts(agent):
    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.return_value = None

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.return_value = _touched(["server/src/routes/widget.routes.js"])

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}) as mock_verify:
            verify_result, attempts = await agent._code_with_retries("proj_x", "feature_x", CODE_PLAN)

    assert attempts == 1
    assert verify_result["passed"] is True
    assert mock_react_agent.ainvoke.call_count == 1
    assert mock_verify.call_count == 1


@pytest.mark.asyncio
async def test_unexpected_exception_is_treated_as_a_failed_attempt_not_a_crash(agent):
    """A real, confirmed bug: previously only GraphRecursionError was caught around
    react_agent.ainvoke(...) -- any other exception (malformed tool-call JSON, a transport
    hiccup against the local model) propagated straight out, skipping commit_changes/verify/
    _save_artifacts entirely. Confirms it's now treated like any other failed attempt:
    committed, retried, and an honest failed result returned instead of the whole run() call
    crashing with zero saved artifact."""
    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.side_effect = RuntimeError("Ollama connection reset")

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.return_value = _touched([])

        with patch.object(agent.verifier, "verify") as mock_verify:
            verify_result, attempts = await agent._code_with_retries("proj_x", "feature_x", CODE_PLAN)
            assert mock_verify.call_count == 0

    assert attempts == 3
    assert verify_result["passed"] is False
    assert mock_workspace.commit_changes.call_count == 3
    assert "Ollama connection reset" in verify_result["steps"][0]["output"]


UI_MANIFEST = {
    "pages": [
        {"page_id": "item-listing", "route": "/item-listing", "components": [{"name": "ItemTable"}]}
    ]
}


def test_find_unread_ui_design_gap_no_manifest_returns_none(agent):
    assert agent._find_unread_ui_design_gap(None, _touched(["app/page.tsx"]), {}) is None
    assert agent._find_unread_ui_design_gap({}, _touched(["app/page.tsx"]), {}) is None
    assert agent._find_unread_ui_design_gap({"pages": []}, _touched(["app/page.tsx"]), {}) is None


def test_find_unread_ui_design_gap_only_backend_touched_returns_none(agent):
    tracker = {"components": set(), "pages": set()}
    gap = agent._find_unread_ui_design_gap(
        UI_MANIFEST, _touched(["app/api/items/route.ts"]), tracker
    )
    assert gap is None


def test_find_unread_ui_design_gap_frontend_touched_nothing_read_returns_gap(agent):
    tracker = {"components": set(), "pages": set()}
    gap = agent._find_unread_ui_design_gap(
        UI_MANIFEST, _touched(["app/item-listing/page.tsx"]), tracker
    )
    assert gap is not None
    assert "read_ui_component_design" in gap
    assert "read_ui_page_design" in gap


def test_find_unread_ui_design_gap_frontend_touched_something_read_returns_none(agent):
    tracker = {"components": {"itemtable"}, "pages": set()}
    gap = agent._find_unread_ui_design_gap(
        UI_MANIFEST, _touched(["app/item-listing/page.tsx"]), tracker
    )
    assert gap is None  # coarse check: ANY read this attempt clears the gate


def test_find_unread_ui_design_gap_checks_modified_files_too(agent):
    tracker = {"components": set(), "pages": set()}
    touched = {"added": [], "modified": ["components/ItemTable.tsx"], "deleted": []}
    gap = agent._find_unread_ui_design_gap(UI_MANIFEST, touched, tracker)
    assert gap is not None


@pytest.mark.asyncio
async def test_design_gap_retries_the_attempt_that_touches_frontend_not_hardcoded_to_attempt_1(agent):
    """
    A real risk an independent design review flagged directly: the gate must apply on
    WHICHEVER attempt actually writes frontend code, not just attempt 1 -- a plan can
    naturally split backend-first. Simulates attempt 1 (backend only, no read) passing the
    gate cleanly, attempt 2 (frontend touched, no read) getting caught and retried, attempt 3
    (frontend touched, read recorded) finally passing.
    """
    code_plan = {
        "files": [
            {"path": "app/api/widgets/route.ts", "action": "create", "rationale": "r", "maps_to": []},
            {"path": "app/widgets/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
        ]
    }

    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.return_value = None

    # Attempt 1: only the backend file exists. Attempt 2 (retried): backend still there, frontend
    # STILL not there because the model wrote it but the mocked get_touched_files below only
    # tracks cumulative state via already_touched's own side_effect list, matched 1:1 with the
    # per-attempt "since=attempt_start_sha" call this test doesn't distinguish by identity (the
    # mock can't tell attempt_start_sha apart from revision_start_sha) -- so instead this uses a
    # side_effect FUNCTION keyed on call order, mirroring the existing
    # test_revision_start_sha_prevents_a_no_op_attempt_from_falsely_passing pattern.
    call_count = {"n": 0}

    def _fake_get_touched_files(project_id, feature_id, since="main"):
        call_count["n"] += 1
        # Calls alternate: cumulative (_find_plan_gaps), then per-attempt (design gap), per
        # attempt -- 2 calls/attempt until the plan is fully satisfied and passes verify.
        if call_count["n"] in (1, 2):
            # Attempt 1: backend file done, frontend not yet -- plan_gaps sees a real gap
            # (frontend file missing), so the design-gap branch is never reached this attempt
            # (both calls return the same thing since _find_plan_gaps already fails first).
            return _touched(["app/api/widgets/route.ts"])
        if call_count["n"] in (3, 4):
            # Attempt 2: frontend file now exists (plan complete) but was never READ.
            return _touched(["app/api/widgets/route.ts", "app/widgets/page.tsx"])
        # Attempt 3: frontend file exists, and this time the design was read (see
        # ui_design_read_tracker mutation below).
        return _touched(["app/api/widgets/route.ts", "app/widgets/page.tsx"])

    def _fake_build_coder_react_agent(
        project_id, feature_id, plan, ui_manifest=None, tracker=None
    ):
        # Simulate the model actually calling read_ui_component_design on attempt 3 only.
        if call_count["n"] >= 4 and tracker is not None:
            tracker["pages"].add("item_listing")
        return mock_react_agent

    with (
        patch(
            "app.agents.coder_agent.agent.build_coder_react_agent",
            side_effect=_fake_build_coder_react_agent,
        ),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.side_effect = _fake_get_touched_files

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            verify_result, attempts = await agent._code_with_retries(
                "proj_x",
                "feature_x",
                code_plan,
                ui_integration_manifest_json=UI_MANIFEST,
            )

    assert attempts == 3
    assert verify_result["passed"] is True


@pytest.mark.asyncio
async def test_ui_design_read_tracker_persists_across_attempts_within_one_call(agent):
    """
    Locks in the deliberate, documented coarsening: the tracker is created ONCE per
    _code_with_retries call, not reset per attempt -- once ANY attempt has read a relevant
    design, a LATER attempt is free to touch a DIFFERENT frontend file it never itself read
    (e.g. a nav-link patch made while fixing an unrelated bug) without tripping the gate again.
    A real, live run confirmed the per-attempt-reset alternative was actively harmful (consumed
    the run's last attempt on a redundant re-read requirement instead of a real fix reaching
    verify()) -- this test proves the fix without needing Docker/a real LLM.
    """
    code_plan = {
        "files": [
            {"path": "app/widgets/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
            {"path": "app/page.tsx", "action": "modify", "rationale": "nav link", "maps_to": []},
        ]
    }
    manifest = {"pages": [{"page_id": "widgets", "components": [{"name": "WidgetList"}]}]}

    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.return_value = None

    # Distinguish the CUMULATIVE call (since=MAIN_BRANCH, i.e. the literal "main") from the
    # PER-ATTEMPT call (since=attempt_start_sha -- some opaque mocked value, never equal to
    # "main") by the actual `since` value each call receives, mirroring the established pattern
    # in test_revision_start_sha_prevents_a_no_op_attempt_from_falsely_passing above.
    per_attempt_calls = {"n": 0}

    def _fake_get_touched_files(project_id, feature_id, since="main"):
        if since == "main":
            # Cumulative view for _find_plan_gaps: both planned files are done, relative to
            # main, throughout -- neither attempt ever un-does the other's work.
            return _touched(["app/widgets/page.tsx", "app/page.tsx"])
        per_attempt_calls["n"] += 1
        if per_attempt_calls["n"] == 1:
            # Attempt 1's own delta: both files newly created this attempt.
            return _touched(["app/widgets/page.tsx", "app/page.tsx"])
        # Attempt 2's own delta: ONLY the nav-link re-touch -- it never recreates the page.
        return _touched(["app/page.tsx"])

    build_calls = {"n": 0}

    def _fake_build_coder_react_agent(project_id, feature_id, plan, ui_manifest=None, tracker=None):
        build_calls["n"] += 1
        # Only attempt 1 (the very first build call) actually reads the design -- attempt 2
        # never calls a read tool at all, simulating exactly the real observed scenario.
        if build_calls["n"] == 1 and tracker is not None:
            tracker["pages"].add("widgets")
        return mock_react_agent

    verify_results = iter([{"passed": False, "steps": [{"name": "x", "status": "failed", "output": "boom"}]}, {"passed": True, "steps": []}])

    with (
        patch(
            "app.agents.coder_agent.agent.build_coder_react_agent",
            side_effect=_fake_build_coder_react_agent,
        ),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.return_value = True
        mock_workspace.get_touched_files.side_effect = _fake_get_touched_files

        with patch.object(agent.verifier, "verify", side_effect=lambda *a, **k: next(verify_results)) as mock_verify:
            verify_result, attempts = await agent._code_with_retries(
                "proj_x", "feature_x", code_plan, ui_integration_manifest_json=manifest
            )

    # Both attempts reached real verify() -- neither was blocked by the design gate, confirming
    # attempt 2's re-touch of the nav-link file (with zero reads of its own) was correctly
    # tolerated because attempt 1 already satisfied the gate for the whole run.
    assert mock_verify.call_count == 2
    assert attempts == 2
    assert verify_result["passed"] is True


@pytest.mark.asyncio
async def test_commit_changes_failure_is_treated_as_a_failed_attempt_not_a_crash(agent):
    """commit_changes() itself is called unguarded on the normal path -- a real GitPython
    error there (e.g. a stale index.lock) previously crashed the whole run() call the same way
    an ainvoke() exception did. Confirms it's caught too."""
    mock_react_agent = AsyncMock()
    mock_react_agent.ainvoke.return_value = None

    with (
        patch("app.agents.coder_agent.agent.build_coder_react_agent", return_value=mock_react_agent),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.commit_changes.side_effect = RuntimeError("index.lock exists")
        mock_workspace.get_touched_files.return_value = _touched([])

        with patch.object(agent.verifier, "verify") as mock_verify:
            verify_result, attempts = await agent._code_with_retries("proj_x", "feature_x", CODE_PLAN)
            assert mock_verify.call_count == 0

    assert verify_result["passed"] is False
    assert "index.lock exists" in verify_result["steps"][0]["output"]
