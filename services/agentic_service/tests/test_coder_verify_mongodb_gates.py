"""
Unit tests for CoderVerifier's two new MongoDB-related gates -- pure logic, no Docker/git/LLM:
- _build_crud_functional_step's conditional hard-gate (real URI configured + "not_persisted").
- _build_hardcoded_secret_step's unconditional hard-gate wrapper around
  hardcoded_secret_checker.scan_for_hardcoded_mongodb_uri (already unit-tested directly in
  test_coder_hardcoded_secret_checker.py -- this file only covers the step-builder's own
  status/output wiring).
"""

from app.agents.coder_agent.verify import CoderVerifier

verifier = CoderVerifier()


def _crud_check(results):
    return {"results": results}


class TestCrudFunctionalStepGating:
    def test_no_real_uri_configured_stays_informational_even_on_not_persisted(self):
        crud_check = _crud_check([
            {"endpoint": "/api/items", "status": "failed", "reason": "not_persisted", "output": "x"}
        ])

        step = verifier._build_crud_functional_step(crud_check, real_uri_configured=False)

        assert step["status"] == "info"

    def test_real_uri_configured_hard_gates_on_not_persisted(self):
        # The exact real bug class this gate exists for: a real URI is configured, but the route
        # never actually persisted to it.
        crud_check = _crud_check([
            {"endpoint": "/api/items", "status": "failed", "reason": "not_persisted", "output": "x"}
        ])

        step = verifier._build_crud_functional_step(crud_check, real_uri_configured=True)

        assert step["status"] == "failed"
        assert "not using the real database" in step["output"]

    def test_real_uri_configured_does_not_hard_gate_on_post_rejected(self):
        # A real, correct validation rule rejecting this check's own heuristically-guessed
        # payload is a plausible non-bug outcome -- must never hard-gate, even with a real URI.
        crud_check = _crud_check([
            {"endpoint": "/api/items", "status": "failed", "reason": "post_rejected", "output": "x"}
        ])

        step = verifier._build_crud_functional_step(crud_check, real_uri_configured=True)

        assert step["status"] == "info"

    def test_real_uri_configured_with_a_passing_result_stays_passed_info(self):
        crud_check = _crud_check([
            {"endpoint": "/api/items", "status": "passed", "output": "x"}
        ])

        step = verifier._build_crud_functional_step(crud_check, real_uri_configured=True)

        assert step["status"] == "info"

    def test_no_results_at_all_stays_informational_regardless_of_uri(self):
        step = verifier._build_crud_functional_step(None, real_uri_configured=True)
        assert step["status"] == "info"

    def test_default_real_uri_configured_is_false(self):
        # Defensive: every existing call site that doesn't yet know about real_uri_configured
        # (should not exist after this change, but a default matters for safety) must not
        # accidentally hard-gate.
        crud_check = _crud_check([
            {"endpoint": "/api/items", "status": "failed", "reason": "not_persisted", "output": "x"}
        ])

        step = verifier._build_crud_functional_step(crud_check)

        assert step["status"] == "info"


class TestHardcodedSecretStep:
    def test_no_findings_passes(self, tmp_path):
        plan = {"files": [{"path": "app/api/items/route.ts", "action": "create"}]}
        (tmp_path / "app" / "api" / "items").mkdir(parents=True)
        (tmp_path / "app" / "api" / "items" / "route.ts").write_text(
            "export async function GET() { return Response.json({}); }", encoding="utf-8"
        )

        step = verifier._build_hardcoded_secret_step(tmp_path, plan)

        assert step["status"] == "passed"

    def test_a_hardcoded_uri_hard_fails(self, tmp_path):
        plan = {"files": [{"path": "lib/db-fallback.ts", "action": "create"}]}
        (tmp_path / "lib").mkdir(parents=True)
        (tmp_path / "lib" / "db-fallback.ts").write_text(
            'const FALLBACK_MONGODB_URI = "mongodb+srv://user:pass@cluster0.example.mongodb.net/db";',
            encoding="utf-8",
        )

        step = verifier._build_hardcoded_secret_step(tmp_path, plan)

        assert step["status"] == "failed"
        assert "lib/db-fallback.ts" in step["output"]
