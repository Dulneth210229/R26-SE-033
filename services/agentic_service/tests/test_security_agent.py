"""
Tests for the Security Agent's severity taxonomy, the LLM review layer's parse/merge/fallback
behavior (a real, confirmed gap this session closed -- the layer used to compute a response and
then discard it entirely), and the graph node's artifact_ids propagation (previously always `[]`
regardless of what the agent actually produced).
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.security_agent import severity
from app.agents.security_agent.agent import SecurityAgent
from app.agents.security_agent.schemas import SecurityAgentOutput
from app.services.in_memory_store import store
from app.utils.id_generator import generate_id


class TestSeverityTaxonomy:
    @pytest.mark.parametrize(
        "raw_severity,expected_tier",
        [
            ("critical", "critical"),
            ("high", "moderate"),
            ("medium", "moderate"),
            ("moderate", "moderate"),  # npm audit's own vocabulary, distinct from "medium"
            ("low", "warning"),
            ("info", "warning"),  # npm audit's own vocabulary
            ("unknown", "warning"),
            ("something-unrecognized", "warning"),  # never raises, degrades to least alarming
            ("CRITICAL", "critical"),  # case-insensitive
        ],
    )
    def test_to_display_tier(self, raw_severity, expected_tier):
        assert severity.to_display_tier(raw_severity) == expected_tier

    def test_count_by_tier(self):
        findings = [
            {"severity": "critical"}, {"severity": "critical"},
            {"severity": "high"}, {"severity": "moderate"},
            {"severity": "low"},
        ]
        counts = severity.count_by_tier(findings)
        assert counts == {"critical": 2, "moderate": 2, "warning": 1}

    def test_count_by_tier_missing_severity_key_defaults_to_unknown_not_a_crash(self):
        counts = severity.count_by_tier([{}])
        assert counts == {"critical": 0, "moderate": 0, "warning": 1}

    @pytest.mark.parametrize(
        "findings,expected_gate",
        [
            ([], "pass"),
            ([{"severity": "low"}], "pass"),
            ([{"severity": "high"}], "review"),
            ([{"severity": "medium"}], "review"),
            ([{"severity": "critical"}], "fail"),
            ([{"severity": "low"}, {"severity": "critical"}], "fail"),
        ],
    )
    def test_gate_decision(self, findings, expected_gate):
        assert severity.gate_decision(findings) == expected_gate


class TestLLMReviewLayer:
    """No real LLM/HTTP -- llm_provider_service.get_provider is mocked to return a fake provider
    whose invoke_agent() is fully controlled, isolating the parse/merge/fallback logic itself."""

    def _make_agent_with_mocked_provider(self, raw_llm_output=None, raises=None):
        agent = SecurityAgent()
        fake_provider = AsyncMock()
        if raises is not None:
            fake_provider.invoke_agent.side_effect = raises
        else:
            fake_provider.invoke_agent.return_value = raw_llm_output
        return agent, fake_provider

    @pytest.mark.asyncio
    async def test_well_formed_response_is_parsed_and_merged(self):
        raw_output = """{
            "additional_findings": [
                {"title": "Missing rate limiting", "description": "No rate limit on login.",
                 "severity": "high", "file": "app/api/login/route.ts", "line": 12,
                 "cwe": "CWE-307", "root_cause": "No rate-limit middleware wraps this route.",
                 "recommendation": "Add rate limiting.", "confidence": "medium"}
            ],
            "notes": "Reviewed the deterministic findings."
        }"""
        agent, fake_provider = self._make_agent_with_mocked_provider(raw_llm_output=raw_output)

        with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=fake_provider):
            status, findings = await agent._run_llm_review_layer([])

        assert len(findings) == 1
        assert findings[0]["severity"] == "high"
        assert findings[0]["file"] == "app/api/login/route.ts"
        assert findings[0]["line"] == 12
        assert findings[0]["layer"] == "llm"
        assert "Missing rate limiting" in findings[0]["message"]
        # Real, confirmed fix in this pass: recommendation used to be squashed into `message`
        # (discarded as a distinct field) -- it and root_cause must now be their own fields, and
        # message must NOT contain the recommendation text anymore.
        assert findings[0]["root_cause"] == "No rate-limit middleware wraps this route."
        assert findings[0]["recommendation"] == "Add rate limiting."
        assert "Add rate limiting" not in findings[0]["message"]
        assert "1 additional finding" in status
        assert "Reviewed the deterministic findings." in status

    @pytest.mark.asyncio
    async def test_response_wrapped_in_markdown_fences_still_parses(self):
        raw_output = '```json\n{"additional_findings": [], "notes": ""}\n```'
        agent, fake_provider = self._make_agent_with_mocked_provider(raw_llm_output=raw_output)

        with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=fake_provider):
            status, findings = await agent._run_llm_review_layer([])

        assert findings == []
        assert "ran successfully" in status

    @pytest.mark.asyncio
    async def test_malformed_json_falls_back_to_empty_findings_not_a_crash(self):
        agent, fake_provider = self._make_agent_with_mocked_provider(raw_llm_output="not json at all")

        with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=fake_provider):
            status, findings = await agent._run_llm_review_layer([])

        assert findings == []
        assert "could not be parsed" in status

    @pytest.mark.asyncio
    async def test_response_missing_required_shape_falls_back_gracefully(self):
        # Valid JSON, but not the expected shape at all (e.g. a plain list instead of an object).
        agent, fake_provider = self._make_agent_with_mocked_provider(raw_llm_output="[1, 2, 3]")

        with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=fake_provider):
            status, findings = await agent._run_llm_review_layer([])

        assert findings == []
        assert "could not be parsed" in status

    @pytest.mark.asyncio
    async def test_unreachable_provider_falls_back_gracefully(self):
        agent, fake_provider = self._make_agent_with_mocked_provider(raises=ConnectionError("no route to host"))

        with patch("app.services.llm_provider_service.llm_provider_service.get_provider", return_value=fake_provider):
            status, findings = await agent._run_llm_review_layer([])

        assert findings == []
        assert "unreachable" in status

    @pytest.mark.asyncio
    async def test_get_provider_itself_raising_falls_back_gracefully(self):
        agent = SecurityAgent()

        with patch(
            "app.services.llm_provider_service.llm_provider_service.get_provider",
            side_effect=RuntimeError("provider not configured"),
        ):
            status, findings = await agent._run_llm_review_layer([])

        assert findings == []
        assert "unreachable" in status


class TestSecurityNodeArtifactIds:
    def test_security_node_returns_real_artifact_ids_not_empty(self):
        from app.services.graph_orchestrator_service import _security_node

        fake_output = SecurityAgentOutput(
            status="completed",
            gate_decision="fail",
            findings_count=2,
            critical_count=1,
            moderate_count=1,
            warning_count=0,
            artifact_ids=["artifact_json_1", "artifact_md_1"],
            message="2 finding(s), gate=fail.",
        )

        with patch(
            "app.services.graph_orchestrator_service.security_agent.run",
            new=AsyncMock(return_value=fake_output),
        ):
            result = _security_node({"feature_id": "fake_feature", "human_comment": "prior"})

        assert result == {
            "last_agent": "security",
            "last_artifact_ids": ["artifact_json_1", "artifact_md_1"],
            "human_comment": None,
        }


class TestSecurityReportRequiresApproval:
    """Real, confirmed reversal: the report used to be auto-approved (ApprovalStatus.APPROVED,
    a soft-gate design) -- direct user request now requires genuine human approval before the
    proceed-or-send-to-Coder-Agent popup can ever appear. Regression guard so this doesn't
    silently revert to auto-approved later."""

    @pytest.fixture
    def feature_id(self, tmp_path):
        project_id = generate_id("project")
        fid = generate_id("feature")
        store.projects[project_id] = {"project_id": project_id, "project_name": "Approval Test"}
        store.features[fid] = {
            "feature_id": fid,
            "project_id": project_id,
            "feature_name": "Approval Test Feature",
        }
        # A real, existing (but otherwise empty) directory is all `run()` needs past its
        # early-return check -- the three scanners themselves are mocked below, so no real repo
        # content is required.
        (tmp_path / "repo").mkdir()

        yield fid

        store.database["features"].delete_one({"feature_id": fid})
        store.database["projects"].delete_one({"project_id": project_id})

    @pytest.mark.asyncio
    async def test_run_saves_the_report_as_pending_not_approved(self, feature_id, tmp_path):
        agent = SecurityAgent()

        with (
            patch("app.agents.security_agent.agent.workspace_service.get_repo_path", return_value=tmp_path / "repo"),
            patch("app.agents.security_agent.agent.scan_dangerous_patterns", return_value=[]),
            patch("app.agents.security_agent.agent.scan_secrets", return_value=[]),
            patch(
                "app.agents.security_agent.agent.scan_dependencies",
                return_value={
                    "findings": [],
                    "audit_exit_code": 0,
                    "audit_ran_offline": True,
                    "dependency_summary": {},
                },
            ),
            patch(
                "app.services.llm_provider_service.llm_provider_service.get_provider",
                side_effect=RuntimeError("no provider needed for this test"),
            ),
        ):
            output = await agent.run(feature_id=feature_id)

        assert output.status == "completed"
        assert len(output.artifact_ids) == 2

        for artifact_id in output.artifact_ids:
            saved = store.artifacts[artifact_id]
            assert saved["approval_status"] == "pending", (
                f"artifact {artifact_id} was saved as {saved['approval_status']!r} -- "
                "the Security Report must require real human approval, not auto-approve."
            )


class TestScannerRootCauseAndRecommendation:
    """Every deterministic layer must populate root_cause/recommendation on every finding it
    produces, not just the LLM-driven ones -- a direct part of this pass's own request."""

    def test_pattern_finding_has_root_cause_and_recommendation(self, tmp_path):
        from app.agents.security_agent.scanners import scan_dangerous_patterns

        (tmp_path / "danger.ts").write_text("eval(userInput);\n", encoding="utf-8")

        with patch(
            "app.agents.security_agent.scanners._run_node",
            return_value=[{"nodeType": "CallExpression", "name": "eval", "line": 1, "extra": None}],
        ):
            findings = scan_dangerous_patterns(tmp_path)

        assert len(findings) == 1
        assert "danger.ts:1" in findings[0]["root_cause"]
        assert "eval" in findings[0]["root_cause"]
        assert findings[0]["recommendation"]

    def test_secret_finding_has_root_cause_and_recommendation(self, tmp_path):
        from app.agents.security_agent.scanners import scan_secrets

        (tmp_path / "lib").mkdir()
        (tmp_path / "lib" / "mongodb.ts").write_text(
            'const uri = "mongodb+srv://user:pass@cluster.mongodb.net/db";\n', encoding="utf-8"
        )

        findings = scan_secrets(tmp_path)

        assert len(findings) == 1
        assert "hardcoded secret" in findings[0]["root_cause"].lower()
        assert ".env.local" in findings[0]["recommendation"]

    def test_dependency_finding_has_root_cause_and_recommendation(self, tmp_path):
        from app.agents.security_agent.scanners import scan_dependencies

        fake_audit_json = (
            '{"vulnerabilities": {"lodash": {"severity": "high", "via": ["Prototype Pollution"]}}, '
            '"metadata": {"vulnerabilities": {}}}'
        )
        fake_run = lambda pid, cmd, cwd, timeout: {"stdout": fake_audit_json, "exit_code": 0, "stderr": ""}

        result = scan_dependencies("proj_1", tmp_path, run_command_fn=fake_run)

        assert len(result["findings"]) == 1
        assert "lodash" in result["findings"][0]["root_cause"]
        assert "npm audit fix" in result["findings"][0]["recommendation"]


class TestRunAiModelScan:
    """SecurityAgent.run_ai_model_scan -- the new, separate AI-model deep-code-read scan trigger.
    deep_scan.run_ai_model_deep_scan itself is mocked here (its own unit tests live in
    test_security_deep_scan.py); this covers the agent-level wiring: deterministic layers still
    run, scan_type is stamped correctly, and both reports save as the same artifact type."""

    @pytest.fixture
    def feature_id(self, tmp_path):
        project_id = generate_id("project")
        fid = generate_id("feature")
        store.projects[project_id] = {"project_id": project_id, "project_name": "Deep Scan Test"}
        store.features[fid] = {
            "feature_id": fid, "project_id": project_id, "feature_name": "Deep Scan Test Feature",
        }
        (tmp_path / "repo").mkdir()

        yield fid

        store.database["features"].delete_one({"feature_id": fid})
        store.database["projects"].delete_one({"project_id": project_id})

    @pytest.mark.asyncio
    async def test_run_ai_model_scan_uses_deep_scan_layer_and_stamps_scan_type(self, feature_id, tmp_path):
        agent = SecurityAgent()
        fake_deep_finding = {
            "id": "SEC-AI-DEEPSCAN:1", "rule_id": "SEC-AI-DEEPSCAN", "layer": "ai_model_deep_scan",
            "severity": "critical", "cwe": "CWE-943", "file": "app/api/auth/login/route.ts", "line": 20,
            "message": "NoSQL injection -- client filter merged into query.",
            "root_cause": "req.body fields are spread directly into the Mongoose query filter.",
            "recommendation": "Only allow a fixed set of known-safe query fields.",
        }

        with (
            patch("app.agents.security_agent.agent.workspace_service.get_repo_path", return_value=tmp_path / "repo"),
            patch("app.agents.security_agent.agent.scan_dangerous_patterns", return_value=[]),
            patch("app.agents.security_agent.agent.scan_secrets", return_value=[]),
            patch(
                "app.agents.security_agent.agent.scan_dependencies",
                return_value={"findings": [], "audit_exit_code": 0, "audit_ran_offline": True, "dependency_summary": {}},
            ),
            patch(
                "app.agents.security_agent.agent.run_ai_model_deep_scan",
                new=AsyncMock(return_value=("AI model deep scan ran over 1 batch(es)...", [fake_deep_finding])),
            ),
        ):
            output = await agent.run_ai_model_scan(feature_id=feature_id)

        assert output.status == "completed"
        assert output.scan_type == "ai_model_deep_scan"
        assert output.findings_count == 1
        assert output.critical_count == 1
        assert output.gate_decision == "fail"
        assert len(output.artifact_ids) == 2

        from app.utils.file_manager import read_json_file

        saved = store.artifacts[output.artifact_ids[0]]
        report = read_json_file(saved["file_path"])
        assert report["scan_type"] == "ai_model_deep_scan"
        assert report["findings"][0]["root_cause"] == fake_deep_finding["root_cause"]
        assert report["findings"][0]["recommendation"] == fake_deep_finding["recommendation"]

    @pytest.mark.asyncio
    async def test_run_ai_model_scan_skips_cleanly_when_no_workspace(self, feature_id):
        agent = SecurityAgent()

        with patch(
            "app.agents.security_agent.agent.workspace_service.get_repo_path",
            return_value=Path("/definitely/does/not/exist"),
        ):
            output = await agent.run_ai_model_scan(feature_id=feature_id)

        assert output.status == "skipped"
        assert output.scan_type == "ai_model_deep_scan"


class TestRunAiModelScanStream:
    """SecurityAgent.run_ai_model_scan_stream -- the live-progress sibling of run_ai_model_scan.
    deep_scan.run_ai_model_deep_scan_stream itself is mocked here (its own unit tests live in
    test_security_deep_scan.py); this covers the agent-level orchestration: a deterministic-layer
    phase event fires first, batch_started/batch_finished/phase events from the deep-scan layer
    are forwarded, a saving phase fires before the report is actually saved, and the final done
    event carries real
    artifact_ids -- the exact same report a human would see from the non-streaming run_ai_model_scan."""

    @pytest.fixture
    def feature_id(self, tmp_path):
        project_id = generate_id("project")
        fid = generate_id("feature")
        store.projects[project_id] = {"project_id": project_id, "project_name": "Deep Scan Stream Test"}
        store.features[fid] = {
            "feature_id": fid, "project_id": project_id, "feature_name": "Deep Scan Stream Test Feature",
        }
        (tmp_path / "repo").mkdir()

        yield fid

        store.database["features"].delete_one({"feature_id": fid})
        store.database["projects"].delete_one({"project_id": project_id})

    @pytest.mark.asyncio
    async def test_forwards_progress_and_ends_with_a_real_done_event(self, feature_id, tmp_path):
        agent = SecurityAgent()

        async def fake_deep_scan_stream(repo_path):
            yield {"type": "phase", "phase": "ai_scan", "label": "Starting AI model scan across 2 batch(es)..."}
            yield {"type": "batch_started", "batch_index": 1, "total": 2, "files": ["app/api/auth/login/route.ts"]}
            yield {"type": "batch_finished", "batch_index": 1, "total": 2, "completed_count": 1, "label": "Scanned batch 1 of 2..."}
            yield {"type": "batch_started", "batch_index": 2, "total": 2, "files": ["app/api/auth/signup/route.ts"]}
            yield {"type": "batch_finished", "batch_index": 2, "total": 2, "completed_count": 2, "label": "Scanned batch 2 of 2..."}
            yield {
                "type": "deep_scan_result",
                "status": "AI model deep scan ran over 2 batch(es)... (2 succeeded, 0 failed): 1 finding(s).",
                "findings": [{
                    "id": "SEC-AI-DEEPSCAN:1", "rule_id": "SEC-AI-DEEPSCAN", "layer": "ai_model_deep_scan",
                    "severity": "critical", "cwe": "CWE-943", "file": "app/api/auth/login/route.ts", "line": 20,
                    "message": "NoSQL injection.", "root_cause": "...", "recommendation": "...",
                }],
            }

        with (
            patch("app.agents.security_agent.agent.workspace_service.get_repo_path", return_value=tmp_path / "repo"),
            patch("app.agents.security_agent.agent.scan_dangerous_patterns", return_value=[]),
            patch("app.agents.security_agent.agent.scan_secrets", return_value=[]),
            patch(
                "app.agents.security_agent.agent.scan_dependencies",
                return_value={"findings": [], "audit_exit_code": 0, "audit_ran_offline": True, "dependency_summary": {}},
            ),
            patch("app.agents.security_agent.agent.run_ai_model_deep_scan_stream", new=fake_deep_scan_stream),
        ):
            events = [event async for event in agent.run_ai_model_scan_stream(feature_id=feature_id)]

        types_in_order = [e["type"] for e in events]
        assert types_in_order == [
            "phase", "phase", "batch_started", "batch_finished",
            "batch_started", "batch_finished", "phase", "done",
        ]
        assert events[0] == {
            "type": "phase", "phase": "deterministic",
            "label": "Running pattern, secret, and dependency scans...",
        }
        assert events[-2] == {"type": "phase", "phase": "saving", "label": "Saving the security report..."}

        done = events[-1]
        assert done["type"] == "done"
        assert len(done["artifact_ids"]) == 2
        assert done["gate_decision"] == "fail"
        assert done["findings_count"] == 1

        from app.utils.file_manager import read_json_file

        saved = store.artifacts[done["artifact_ids"][0]]
        report = read_json_file(saved["file_path"])
        assert report["scan_type"] == "ai_model_deep_scan"
        assert report["findings"][0]["file"] == "app/api/auth/login/route.ts"

    @pytest.mark.asyncio
    async def test_yields_an_error_event_and_saves_nothing_when_no_workspace(self, feature_id):
        agent = SecurityAgent()

        with patch(
            "app.agents.security_agent.agent.workspace_service.get_repo_path",
            return_value=Path("/definitely/does/not/exist"),
        ):
            events = [event async for event in agent.run_ai_model_scan_stream(feature_id=feature_id)]

        assert len(events) == 1
        assert events[0]["type"] == "error"


class TestSecurityChat:
    """Real Security Agent chat -- mirrors QA Agent's own chat_stream shape exactly (no dedicated
    agent-level test file exists for QA's own chat either, per this project's established
    convention -- the streaming loop itself is only meaningfully verified live against a real
    provider; these tests cover the deterministic, non-LLM pieces: report summarization and turn
    persistence)."""

    @pytest.fixture
    def feature_id(self):
        fid = generate_id("feature")
        yield fid
        store.database["security_conversations"].delete_one({"feature_id": fid})

    def test_summarize_report_for_chat_includes_gate_and_every_finding(self):
        agent = SecurityAgent()
        report = {
            "feature_name": "Login and Signup",
            "generated_at": "2026-08-22T00:00:00+00:00",
            "gate_decision": "fail",
            "findings_count": 2,
            "critical_count": 1,
            "moderate_count": 1,
            "warning_count": 0,
            "findings": [
                {
                    "severity": "critical", "rule_id": "SEC-SECRET-001", "cwe": "CWE-798",
                    "file": ".env.local", "line": 3, "message": "Hardcoded MongoDB credential.",
                },
                {
                    "severity": "moderate", "rule_id": "SEC-PATTERN-002", "cwe": "CWE-79",
                    "file": "app/page.tsx", "line": None, "message": "Possible XSS sink.",
                },
            ],
            "dependency_scan": {"audit_exit_code": 0, "audit_ran_offline": True},
            "llm_review_status": "Skipped -- LLM provider unreachable in this run.",
        }

        summary = agent._summarize_report_for_chat(report)

        assert "Login and Signup" in summary
        assert "fail" in summary
        assert "1 critical" in summary
        assert "CWE-798" in summary and ".env.local:3" in summary
        assert "CWE-79" in summary and "app/page.tsx" in summary
        assert "npm audit exit code 0" in summary
        assert "offline" in summary
        assert "LLM provider unreachable" in summary

    def test_summarize_report_for_chat_never_raises_on_missing_optional_fields(self):
        # A real report always has these keys (agent.py's own run() always fills them), but the
        # summarizer should degrade gracefully rather than KeyError if that ever drifts.
        agent = SecurityAgent()
        summary = agent._summarize_report_for_chat({"findings": []})
        assert isinstance(summary, str)

    def test_get_chat_history_is_empty_for_a_feature_with_no_conversation_yet(self, feature_id):
        agent = SecurityAgent()
        assert agent._get_chat_history(feature_id) == []

    def test_append_chat_turns_persists_and_accumulates(self, feature_id):
        agent = SecurityAgent()

        agent._append_chat_turns(feature_id, [
            {"role": "user", "content": "Why is this Critical?", "created_at": "2026-08-22T00:00:00+00:00"},
            {"role": "assistant", "content": "Because it's a real hardcoded secret.", "created_at": "2026-08-22T00:00:01+00:00"},
        ])
        agent._append_chat_turns(feature_id, [
            {"role": "user", "content": "How do I fix it?", "created_at": "2026-08-22T00:00:02+00:00"},
        ])

        history = agent._get_chat_history(feature_id)
        assert len(history) == 3
        assert history[0]["content"] == "Why is this Critical?"
        assert history[2]["content"] == "How do I fix it?"

    @pytest.mark.asyncio
    async def test_chat_stream_yields_tokens_then_done_and_persists_the_turn(self, feature_id):
        agent = SecurityAgent()

        async def _fake_stream(prompt, system_prompt=None):
            yield "Real "
            yield "answer."

        fake_provider = type("FakeProvider", (), {"stream": staticmethod(_fake_stream)})()

        with (
            patch.object(agent, "_load_latest_security_report", return_value=None),
            patch(
                "app.services.llm_provider_service.llm_provider_service.get_provider",
                return_value=fake_provider,
            ),
        ):
            events = [event async for event in agent.chat_stream(feature_id=feature_id, message="hi")]

        assert events[0] == {"type": "token", "text": "Real "}
        assert events[1] == {"type": "token", "text": "answer."}
        assert events[-1] == {"type": "done", "message": "Real answer."}

        history = agent._get_chat_history(feature_id)
        assert len(history) == 2
        assert history[0] == {
            "role": "user", "content": "hi", "created_at": history[0]["created_at"], "turn_index": 1,
        }
        assert history[1]["content"] == "Real answer."
        # The user turn and its reply share ONE turn_index -- direct user request, lets a later
        # edit address "this exchange" by one number.
        assert history[1]["turn_index"] == 1

    @pytest.mark.asyncio
    async def test_chat_stream_yields_error_event_and_persists_nothing_when_provider_unreachable(self, feature_id):
        agent = SecurityAgent()

        with (
            patch.object(agent, "_load_latest_security_report", return_value=None),
            patch(
                "app.services.llm_provider_service.llm_provider_service.get_provider",
                side_effect=RuntimeError("no provider configured"),
            ),
        ):
            events = [event async for event in agent.chat_stream(feature_id=feature_id, message="hi")]

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert agent._get_chat_history(feature_id) == []

    @pytest.mark.asyncio
    async def test_edit_chat_turn_stream_truncates_and_regenerates_from_the_edited_turn(self, feature_id):
        """Direct user request: editing turn N discards it and everything after, then continues
        as a fresh exchange -- mirrors requirement_agent's own rewind semantics."""
        agent = SecurityAgent()

        async def _fake_stream_1(prompt, system_prompt=None):
            yield "first answer"

        async def _fake_stream_2(prompt, system_prompt=None):
            yield "second answer"

        async def _fake_stream_3(prompt, system_prompt=None):
            yield "edited answer"

        with patch.object(agent, "_load_latest_security_report", return_value=None):
            for fake_stream in (_fake_stream_1, _fake_stream_2):
                fake_provider = type("FakeProvider", (), {"stream": staticmethod(fake_stream)})()
                with patch(
                    "app.services.llm_provider_service.llm_provider_service.get_provider",
                    return_value=fake_provider,
                ):
                    async for _ in agent.chat_stream(feature_id=feature_id, message="q"):
                        pass

            # Two real exchanges exist now (turn_index 1 and 2). Editing turn 1 must discard BOTH
            # its own reply and the entire second exchange, not just the one turn.
            history_before_edit = agent._get_chat_history(feature_id)
            assert len(history_before_edit) == 4

            fake_provider = type("FakeProvider", (), {"stream": staticmethod(_fake_stream_3)})()
            with patch(
                "app.services.llm_provider_service.llm_provider_service.get_provider",
                return_value=fake_provider,
            ):
                events = [
                    event async for event in
                    agent.edit_chat_turn_stream(feature_id=feature_id, turn_index=1, new_message="edited q")
                ]

        assert events[-1] == {"type": "done", "message": "edited answer"}
        history_after_edit = agent._get_chat_history(feature_id)
        assert len(history_after_edit) == 2
        assert history_after_edit[0]["content"] == "edited q"
        assert history_after_edit[1]["content"] == "edited answer"
        # The regenerated exchange gets a fresh turn_index, not a reused stale one.
        assert history_after_edit[0]["turn_index"] == 1
        assert history_after_edit[1]["turn_index"] == 1

    @pytest.mark.asyncio
    async def test_edit_chat_turn_stream_yields_an_error_for_an_unknown_turn_index(self, feature_id):
        agent = SecurityAgent()

        events = [
            event async for event in
            agent.edit_chat_turn_stream(feature_id=feature_id, turn_index=99, new_message="edited q")
        ]

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "99" in events[0]["message"]
        assert agent._get_chat_history(feature_id) == []
