"""
Tests for `scan_dangerous_patterns`'s PATTERN_RULES matching logic -- previously had zero test
coverage (test_security_scanners.py only covers `scan_secrets`). Written after live-testing every
one of the 7 rules against real, syntactically valid TS/TSX source (via a real `node`/`typescript`
subprocess against the real sample-e-commerce workspace) and finding a real, confirmed bug:
SEC-JS-007 (`Math.random()`) never actually fired, because AST_SCAN_JS's emit() only ever
captures a property-access call's final segment (`callee.name.text`) -- for `Math.random()`
that's `"random"`, never `"Math"`, which the rule's original pattern (`^(Math)$`) could never
match. Fixed by matching `^(random)$` instead, consistent with how every other property-access
rule here already matches on the method/property name, not the receiver.

`_run_node` (the real Node/TypeScript subprocess call) is mocked with canned AST events matching
exactly what AST_SCAN_JS would really emit for each pattern -- this is what actually needs
testing (the rule-matching logic that had the real bug), not the Node subprocess plumbing itself,
which requires a real `typescript` install this test environment doesn't guarantee. One real
(empty) file per test is still written to `tmp_path` so `_iter_source_files` has something to
iterate.
"""

from unittest.mock import patch

from app.agents.security_agent.scanners import scan_dangerous_patterns


def _scan_with_events(tmp_path, events, filename="a.ts"):
    (tmp_path / filename).write_text("", encoding="utf-8")
    with patch("app.agents.security_agent.scanners._run_node", return_value=events):
        return scan_dangerous_patterns(tmp_path)


def test_eval_call_is_detected(tmp_path):
    findings = _scan_with_events(tmp_path, [{"nodeType": "CallExpression", "name": "eval", "line": 3, "extra": None}])
    assert any(f["rule_id"] == "SEC-JS-001" and f["severity"] == "critical" for f in findings)


def test_new_function_is_detected(tmp_path):
    findings = _scan_with_events(tmp_path, [{"nodeType": "NewExpression", "name": "Function", "line": 4, "extra": None}])
    assert any(f["rule_id"] == "SEC-JS-002" and f["severity"] == "high" for f in findings)


def test_exec_sync_call_is_detected(tmp_path):
    findings = _scan_with_events(tmp_path, [{"nodeType": "CallExpression", "name": "execSync", "line": 5, "extra": None}])
    assert any(f["rule_id"] == "SEC-JS-003" and f["severity"] == "high" for f in findings)


def test_document_write_call_is_detected(tmp_path):
    findings = _scan_with_events(tmp_path, [{"nodeType": "CallExpression", "name": "write", "line": 6, "extra": None}])
    assert any(f["rule_id"] == "SEC-JS-004" and f["severity"] == "medium" for f in findings)


def test_dangerously_set_inner_html_attribute_is_detected(tmp_path):
    findings = _scan_with_events(
        tmp_path,
        [{"nodeType": "JsxAttribute", "name": "dangerouslySetInnerHTML", "line": 7, "extra": None}],
        filename="a.tsx",
    )
    assert any(f["rule_id"] == "SEC-JS-005" and f["severity"] == "high" for f in findings)


def test_dynamic_bracket_sort_access_is_detected(tmp_path):
    findings = _scan_with_events(
        tmp_path, [{"nodeType": "ElementAccessExpression", "name": "sort", "line": 8, "extra": None}]
    )
    assert any(f["rule_id"] == "SEC-JS-006" and f["severity"] == "medium" for f in findings)


def test_math_random_call_is_detected_the_real_confirmed_bug_fix(tmp_path):
    # The real, confirmed emit shape for `Math.random()` -- PropertyAccessExpression callee, so
    # name is "random" (the property), never "Math" (the receiver). Before the fix, this exact
    # event never matched any rule.
    findings = _scan_with_events(tmp_path, [{"nodeType": "CallExpression", "name": "random", "line": 9, "extra": None}])
    assert any(f["rule_id"] == "SEC-JS-007" and f["severity"] == "low" for f in findings), (
        "SEC-JS-007 should fire for the real Math.random() emit shape -- if this fails, the rule "
        "regressed back to matching on the receiver name instead of the method name."
    )


def test_unrelated_call_produces_no_findings(tmp_path):
    findings = _scan_with_events(tmp_path, [{"nodeType": "CallExpression", "name": "console", "line": 1, "extra": None}])
    assert findings == []


def test_duplicate_events_for_the_same_rule_and_line_are_deduped(tmp_path):
    events = [
        {"nodeType": "CallExpression", "name": "eval", "line": 3, "extra": None},
        {"nodeType": "CallExpression", "name": "eval", "line": 3, "extra": None},
    ]
    findings = _scan_with_events(tmp_path, events)
    assert len(findings) == 1
