"""
Unit tests for CoderVerifier._build_ui_expectations_coverage_step -- pure, tmp_path-based,
no git/Docker/LLM (mirrors test_coder_relevance_scan.py's own established precedent for this
class of cheap, deterministic heuristic check).

This step is informational-only by design (never affects `passed`) -- these tests only lock in
its own "status"/"output" content, not any gating behavior, since it isn't a gate.
"""

from app.agents.coder_agent.verify import CoderVerifier


def _verifier():
    return CoderVerifier()


def test_step_is_info_with_no_ui_expectations(tmp_path):
    step = _verifier()._build_ui_expectations_coverage_step(tmp_path, ["app/page.tsx"], None)
    assert step["status"] == "info"
    assert "No SRS ui_expectations available" in step["output"]


def test_step_is_info_with_empty_ui_expectations_list(tmp_path):
    step = _verifier()._build_ui_expectations_coverage_step(tmp_path, ["app/page.tsx"], [])
    assert step["status"] == "info"
    assert "No SRS ui_expectations available" in step["output"]


def test_step_reports_no_gaps_when_everything_has_a_trace(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        '<button onClick={handleOpenCreate}>Add Item</button>', encoding="utf-8"
    )

    step = _verifier()._build_ui_expectations_coverage_step(
        tmp_path,
        ["app/page.tsx"],
        ['An "Add Item" button that opens a form to create a new item'],
    )
    assert step["status"] == "info"
    assert "All 1 SRS ui_expectations bullet" in step["output"]


def test_step_lists_the_genuinely_missing_bullets(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        "export default function HomePage() { return <div>hello</div>; }", encoding="utf-8"
    )

    step = _verifier()._build_ui_expectations_coverage_step(
        tmp_path,
        ["app/page.tsx"],
        ["Pagination controls at the bottom of the list (previous/next, jump to page)"],
    )
    assert step["status"] == "info"
    assert "Pagination controls" in step["output"]
    assert "worth a human double-check" in step["output"]


def test_step_never_appears_as_a_hard_gate_status():
    # Guards against a future edit accidentally making this step's status anything other than
    # "info" -- it must never be able to flip `passed`.
    import inspect

    source = inspect.getsource(CoderVerifier._build_ui_expectations_coverage_step)
    assert '"status": "failed"' not in source
