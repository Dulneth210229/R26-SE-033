"""
Unit tests for CoderVerifier._build_relevance_scan_step -- pure, tmp_path-based,
no git/Docker/LLM (mirrors test_route_checker.py/test_style_checker.py's own
precedent for this class of cheap, deterministic heuristic check).

This step is informational-only by design (never affects `passed`) -- these
tests only lock in its own "status"/"output" content, not any gating
behavior, since it isn't a gate.
"""

from app.agents.coder_agent.verify import CoderVerifier


def _verifier():
    return CoderVerifier()


def test_relevance_scan_is_info_with_no_original_request(tmp_path):
    step = _verifier()._build_relevance_scan_step(tmp_path, ["app/page.tsx"], None)
    assert step["status"] == "info"
    assert "No original request" in step["output"]


def test_relevance_scan_flags_low_overlap(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        "export default function HomePage() { return <div>hello</div>; }", encoding="utf-8"
    )

    step = _verifier()._build_relevance_scan_step(
        tmp_path,
        ["app/page.tsx"],
        "Add styles using tailwind css and restore the missing footer component",
    )

    assert step["status"] == "info"
    assert "shares few or no words" in step["output"]


def test_relevance_scan_passes_quietly_on_high_overlap(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        "export function Footer() { return <footer className='bg-blue-600'>Site Footer</footer>; }",
        encoding="utf-8",
    )

    step = _verifier()._build_relevance_scan_step(
        tmp_path,
        ["app/page.tsx"],
        "Add the footer back, the footer has been removed",
    )

    assert step["status"] == "info"
    assert "shares few or no words" not in step["output"]


def test_relevance_scan_is_info_when_nothing_was_touched(tmp_path):
    step = _verifier()._build_relevance_scan_step(tmp_path, [], "Add tailwind styling")
    assert step["status"] == "info"
    assert "No files were touched" in step["output"]


def test_relevance_scan_never_appears_as_a_hard_gate_status():
    # Guards against a future edit accidentally making this step's status
    # anything other than "info" -- it must never be able to flip `passed`.
    import inspect

    source = inspect.getsource(CoderVerifier._build_relevance_scan_step)
    assert '"status": "failed"' not in source
