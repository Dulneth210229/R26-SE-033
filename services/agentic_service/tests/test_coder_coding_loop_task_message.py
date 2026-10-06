"""
Unit tests for coding_loop.build_task_message's original_request and
implementation_spec_section parameters -- pure string-formatting, no LLM/git/Docker.
"""

from app.agents.coder_agent.coding_loop import build_task_message


def test_build_task_message_without_original_request_is_unchanged():
    message = build_task_message({"files": []})
    assert "Original human request" not in message
    assert "Implement the following pre-approved" in message


def test_build_task_message_includes_original_request_ahead_of_the_plan():
    message = build_task_message({"files": []}, original_request="Add the footer back")

    request_index = message.index("Add the footer back")
    plan_index = message.index('"files"')
    assert request_index < plan_index
    assert "Original human request" in message
    assert "trust the original request" in message


def test_build_task_message_original_request_composes_with_already_touched_and_failure():
    message = build_task_message(
        {"files": []},
        prior_failure_output="Something failed",
        already_touched={"added": ["app/page.tsx"], "modified": [], "deleted": []},
        original_request="Restore the footer",
    )

    assert "Restore the footer" in message
    assert "app/page.tsx" in message
    assert "Something failed" in message


def test_build_task_message_without_implementation_spec_section_is_unchanged():
    message = build_task_message({"files": []})
    assert "Real spec detail for the planned files above" not in message


def test_build_task_message_includes_implementation_spec_section_after_the_plan():
    message = build_task_message(
        {"files": [{"path": "app/api/items/route.ts"}]},
        implementation_spec_section='{"endpoints": [{"method": "POST", "path": "/api/items"}]}',
    )

    plan_index = message.index('"files"')
    spec_index = message.index('"endpoints"')
    assert plan_index < spec_index
    assert "Real spec detail for the planned files above" in message
    assert '{"endpoints": [{"method": "POST", "path": "/api/items"}]}' in message


def test_build_task_message_empty_implementation_spec_section_omits_the_block():
    message = build_task_message({"files": []}, implementation_spec_section="")
    assert "Real spec detail for the planned files above" not in message
