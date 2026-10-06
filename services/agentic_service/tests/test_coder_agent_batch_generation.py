"""
Unit tests for CoderAgent._code_with_batch_generation and _run_coding_phase's dispatch logic. No
LLM, no Docker, no real git -- batch_coder.generate_file_content/workspace_service/coder_verifier
are all mocked, matching test_coder_agent_retries.py's own established idiom. File writes/deletes
happen against a real tmp_path directory (workspace_service.get_repo_path is mocked to point at
it) so the actual filesystem logic is exercised for real, not mocked away.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.coder_agent.agent import CoderAgent

CODE_PLAN = {
    "files": [
        {"path": "models/Item.ts", "action": "create", "rationale": "r", "maps_to": ["Item"]},
        {"path": "app/item-listing-crud/page.tsx", "action": "create", "rationale": "r", "maps_to": []},
    ]
}


@pytest.fixture
def agent():
    return CoderAgent()


@pytest.mark.asyncio
async def test_batch_generation_writes_all_planned_files_and_passes(agent, tmp_path):
    generated_content = {
        "models/Item.ts": "export default {};",
        "app/item-listing-crud/page.tsx": "export default function Page() { return null; }",
    }

    async def _fake_generate(feature_id, file_entry, current_content, sibling_files, prior_failure, implementation_spec=None):
        return generated_content[file_entry["path"]]

    with (
        patch("app.agents.coder_agent.agent.batch_coder.generate_file_content", side_effect=_fake_generate),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.get_repo_path.return_value = tmp_path
        mock_workspace.commit_changes.return_value = True

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}) as mock_verify:
            verify_result, attempts = await agent._code_with_batch_generation("proj_x", "feature_x", CODE_PLAN)

    assert attempts == 1
    assert verify_result["passed"] is True
    assert (tmp_path / "models/Item.ts").read_text(encoding="utf-8") == generated_content["models/Item.ts"]
    assert (tmp_path / "app/item-listing-crud/page.tsx").read_text(
        encoding="utf-8"
    ) == generated_content["app/item-listing-crud/page.tsx"]
    assert mock_verify.call_count == 1


@pytest.mark.asyncio
async def test_batch_generation_retries_and_feeds_real_failure_back(agent, tmp_path):
    calls = []

    async def _fake_generate(feature_id, file_entry, current_content, sibling_files, prior_failure, implementation_spec=None):
        calls.append((file_entry["path"], prior_failure))
        if file_entry["path"] == "app/item-listing-crud/page.tsx" and len(calls) <= 2:
            return None  # fails on attempt 1
        return "real content"

    with (
        patch("app.agents.coder_agent.agent.batch_coder.generate_file_content", side_effect=_fake_generate),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.get_repo_path.return_value = tmp_path
        mock_workspace.commit_changes.return_value = True

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            verify_result, attempts = await agent._code_with_batch_generation("proj_x", "feature_x", CODE_PLAN)

    assert attempts == 2
    assert verify_result["passed"] is True
    # Attempt 2's calls must have received real feedback naming the file that failed.
    attempt_2_calls = calls[2:]
    assert all(prior_failure is not None for _, prior_failure in attempt_2_calls)
    assert any("app/item-listing-crud/page.tsx" in prior_failure for _, prior_failure in attempt_2_calls)


@pytest.mark.asyncio
async def test_batch_generation_delete_action_removes_the_file_without_calling_generator(agent, tmp_path):
    plan = {"files": [{"path": "models/Old.ts", "action": "delete", "rationale": "r", "maps_to": []}]}
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "Old.ts").write_text("stale", encoding="utf-8")

    with (
        patch("app.agents.coder_agent.agent.batch_coder.generate_file_content") as mock_generate,
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.get_repo_path.return_value = tmp_path
        mock_workspace.commit_changes.return_value = True

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            verify_result, attempts = await agent._code_with_batch_generation("proj_x", "feature_x", plan)

    assert attempts == 1
    assert verify_result["passed"] is True
    assert not (tmp_path / "models" / "Old.ts").exists()
    mock_generate.assert_not_called()


@pytest.mark.asyncio
async def test_batch_generation_modify_action_passes_current_content_to_generator(agent, tmp_path):
    plan = {"files": [{"path": "models/Item.ts", "action": "modify", "rationale": "r", "maps_to": []}]}
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "Item.ts").write_text("old content", encoding="utf-8")

    captured = {}

    async def _fake_generate(feature_id, file_entry, current_content, sibling_files, prior_failure, implementation_spec=None):
        captured["current_content"] = current_content
        return "new content"

    with (
        patch("app.agents.coder_agent.agent.batch_coder.generate_file_content", side_effect=_fake_generate),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.get_repo_path.return_value = tmp_path
        mock_workspace.commit_changes.return_value = True

        with patch.object(agent.verifier, "verify", return_value={"passed": True, "steps": []}):
            await agent._code_with_batch_generation("proj_x", "feature_x", plan)

    assert captured["current_content"] == "old content"
    assert (tmp_path / "models" / "Item.ts").read_text(encoding="utf-8") == "new content"


@pytest.mark.asyncio
async def test_batch_generation_exhausts_attempts_when_verify_never_passes(agent, tmp_path):
    async def _fake_generate(feature_id, file_entry, current_content, sibling_files, prior_failure, implementation_spec=None):
        return "content"

    with (
        patch("app.agents.coder_agent.agent.batch_coder.generate_file_content", side_effect=_fake_generate),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.get_repo_path.return_value = tmp_path
        mock_workspace.commit_changes.return_value = True

        with patch.object(
            agent.verifier, "verify",
            return_value={"passed": False, "steps": [{"name": "next build", "status": "failed", "output": "err"}]},
        ) as mock_verify:
            verify_result, attempts = await agent._code_with_batch_generation("proj_x", "feature_x", CODE_PLAN)

    assert attempts == 3
    assert verify_result["passed"] is False
    assert mock_verify.call_count == 3


@pytest.mark.asyncio
async def test_batch_generation_commit_failure_is_treated_as_a_failed_attempt_not_a_crash(agent, tmp_path):
    async def _fake_generate(feature_id, file_entry, current_content, sibling_files, prior_failure, implementation_spec=None):
        return "content"

    with (
        patch("app.agents.coder_agent.agent.batch_coder.generate_file_content", side_effect=_fake_generate),
        patch("app.agents.coder_agent.agent.workspace_service") as mock_workspace,
    ):
        mock_workspace.get_repo_path.return_value = tmp_path
        mock_workspace.commit_changes.side_effect = RuntimeError("git error")

        with patch.object(agent.verifier, "verify") as mock_verify:
            verify_result, attempts = await agent._code_with_batch_generation("proj_x", "feature_x", CODE_PLAN)

    assert attempts == 3
    assert verify_result["passed"] is False
    mock_verify.assert_not_called()  # never even reaches verify() when commit itself fails every time


@pytest.mark.asyncio
async def test_run_coding_phase_dispatches_to_agentic_when_tool_calling_supported(agent):
    with (
        patch("app.agents.coder_agent.agent.model_capabilities.supports_tool_calling", new=AsyncMock(return_value=True)),
        patch.object(agent, "_code_with_retries", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))) as mock_agentic,
        patch.object(agent, "_code_with_batch_generation", new=AsyncMock()) as mock_batch,
    ):
        result = await agent._run_coding_phase("proj_x", "feature_x", CODE_PLAN, None, None, None)

    assert result == ({"passed": True, "steps": []}, 1)
    mock_agentic.assert_called_once()
    mock_batch.assert_not_called()


@pytest.mark.asyncio
async def test_run_coding_phase_dispatches_to_batch_when_tool_calling_not_supported(agent):
    with (
        patch("app.agents.coder_agent.agent.model_capabilities.supports_tool_calling", new=AsyncMock(return_value=False)),
        patch.object(agent, "_code_with_retries", new=AsyncMock()) as mock_agentic,
        patch.object(agent, "_code_with_batch_generation", new=AsyncMock(return_value=({"passed": True, "steps": []}, 1))) as mock_batch,
    ):
        result = await agent._run_coding_phase("proj_x", "feature_x", CODE_PLAN, None, None, None)

    assert result == ({"passed": True, "steps": []}, 1)
    mock_batch.assert_called_once()
    mock_agentic.assert_not_called()
