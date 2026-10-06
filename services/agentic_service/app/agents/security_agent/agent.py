"""
Security Agent.

Runs three deterministic scan layers against the generated project's own workspace --
pattern-based static analysis (real TypeScript-compiler AST, not text matching),
secret/credential scanning, and `npm audit` dependency scanning -- reduces the combined findings
(plus whatever the optional LLM review layer adds, see below) to a Critical/Moderate/Warning
gate decision (severity.py), and saves a JSON + Markdown security report as a versioned artifact
through the same artifact_service path every other agent uses. The report groups findings under
those same three headings for a human (and, via the "send this report to the Coder Agent"
frontend action, for the Coder Agent) to act on.

The optional fourth layer asks the configured LLM to review the deterministic findings summary
and propose additional, clearly-grounded findings; its JSON response is parsed against
SecurityLLMReviewResult and merged into the combined findings BEFORE the gate/counts are
computed. If the LLM provider is unreachable or returns something unparseable, that layer
degrades to an empty findings list and a status note explaining why -- it never fails the whole
scan, and the deterministic findings (this stage's actual evidence) are unaffected either way.

Requires real human approval, like every other gated stage: the saved report is PENDING, not
auto-approved -- a human must explicitly approve it (ApprovalPanel/GovernancePanel, generic
machinery every other stage already uses, needs no security-specific changes). Approving opens a
frontend popup (SecurityDecisionDialog.jsx) offering "proceed anyway" or "send this report to the
Coder Agent to fix" -- the latter triggers a real Coder Agent revision and then automatically
re-runs this agent once that revision completes, producing a new PENDING report that must be
approved again, naturally looping until the human proceeds or a re-scan comes back clean (gate
decision "pass", nothing left to send). This still runs without a LangGraph interrupt() gate (see
graph_orchestrator_service._security_node, in AUTO_APPROVED_STAGES) -- that only affects the
graph's own start()/resume() flow, not this artifact-level approval requirement.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from pydantic import ValidationError

from app.agents.security_agent import severity
from app.agents.security_agent.deep_scan import run_ai_model_deep_scan, run_ai_model_deep_scan_stream
from app.agents.security_agent.prompt import SECURITY_AGENT_SYSTEM_PROMPT, SECURITY_CHAT_SYSTEM_PROMPT
from app.agents.security_agent.schemas import SecurityAgentOutput, SecurityLLMReviewResult
from app.agents.security_agent.scanners import (
    scan_dangerous_patterns,
    scan_dependencies,
    scan_secrets,
)
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.file_manager import read_json_file
from app.utils.json_utils import extract_json_object
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _build_markdown_report(report: dict) -> str:
    scan_type_label = "AI model deep scan" if report.get("scan_type") == "ai_model_deep_scan" else "Standard scan"
    lines = [
        f"# Security Report -- {report['project_name']} / {report['feature_name']}",
        "",
        f"Generated: {report['generated_at']}",
        f"Scan type: **{scan_type_label}**",
        f"Gate decision: **{report['gate_decision'].upper()}**",
        f"Total findings: {report['findings_count']} "
        f"({report['critical_count']} critical, {report['moderate_count']} moderate, "
        f"{report['warning_count']} warning)",
        "",
    ]
    if not report["findings"]:
        lines += ["## Findings", "", "No findings from any scan layer."]
    else:
        findings_by_tier: dict[str, list[dict]] = {tier: [] for tier in severity.DISPLAY_TIERS}
        for finding in report["findings"]:
            findings_by_tier[severity.to_display_tier(finding.get("severity", "unknown"))].append(finding)

        for tier in severity.DISPLAY_TIERS:
            tier_findings = findings_by_tier[tier]
            if not tier_findings:
                continue
            lines += [f"## {tier.capitalize()}", ""]
            for finding in tier_findings:
                loc = f"{finding['file']}:{finding['line']}" if finding.get("line") else finding["file"]
                lines.append(
                    f"- **[{finding['severity'].upper()}]** `{finding['rule_id']}` "
                    f"({finding['cwe']}) -- {loc} -- {finding['message']}"
                )
                if finding.get("root_cause"):
                    lines.append(f"  - Root cause: {finding['root_cause']}")
                if finding.get("recommendation"):
                    lines.append(f"  - Suggested fix: {finding['recommendation']}")
            lines.append("")

    lines += [
        "## Dependency scan",
        "",
        f"npm audit exit code: {report['dependency_scan']['audit_exit_code']}",
        f"Ran offline (sandbox has no outbound network to the npm advisory "
        f"endpoint): {report['dependency_scan']['audit_ran_offline']}",
        f"Dependency summary: {report['dependency_scan']['dependency_summary']}",
        "",
        "## LLM review layer",
        "",
        report["llm_review_status"],
    ]
    return "\n".join(lines)


class SecurityAgent:
    async def run(self, **kwargs) -> SecurityAgentOutput:
        """Standard scan: 3 deterministic layers (pattern/secret/dependency) plus the summary-only
        LLM review layer (_run_llm_review_layer -- sees only a findings summary, never real
        source). See run_ai_model_scan for the deeper, source-reading alternative."""
        feature_id = kwargs["feature_id"]
        feature = store.features.get(feature_id)
        project = store.projects.get(feature["project_id"])

        repo_path = workspace_service.get_repo_path(project["project_id"])

        if not repo_path.exists():
            logger.warning("Security Agent: repo path %s does not exist, skipping scan", repo_path)
            return SecurityAgentOutput(
                status="skipped",
                message=f"No workspace found at {repo_path} for this feature yet.",
            )

        pattern_findings = scan_dangerous_patterns(repo_path)
        secret_findings = scan_secrets(repo_path)
        dependency_result = scan_dependencies(project["project_id"], repo_path)
        deterministic_findings = pattern_findings + secret_findings + dependency_result["findings"]

        llm_review_status, llm_findings = await self._run_llm_review_layer(deterministic_findings)

        return self._build_and_save_report(
            feature_id=feature_id, feature=feature, project=project,
            deterministic_findings=deterministic_findings, dependency_result=dependency_result,
            llm_review_status=llm_review_status, llm_findings=llm_findings,
            scan_type="standard",
        )

    async def run_ai_model_scan(self, feature_id: str) -> SecurityAgentOutput:
        """AI-model deep-code-read scan: the same 3 deterministic layers as run() (so this scan is
        never LESS complete than a standard one) PLUS deep_scan.run_ai_model_deep_scan in place of
        the summary-only LLM review layer -- that layer is shown REAL source file contents
        directly, not just a findings summary, and is strictly more informative, so running both
        layers for one "scan by the model" request would only double LLM cost for no benefit."""
        feature = store.features.get(feature_id)
        project = store.projects.get(feature["project_id"])

        repo_path = workspace_service.get_repo_path(project["project_id"])

        if not repo_path.exists():
            logger.warning("Security Agent: repo path %s does not exist, skipping scan", repo_path)
            return SecurityAgentOutput(
                status="skipped",
                message=f"No workspace found at {repo_path} for this feature yet.",
                scan_type="ai_model_deep_scan",
            )

        pattern_findings = scan_dangerous_patterns(repo_path)
        secret_findings = scan_secrets(repo_path)
        dependency_result = scan_dependencies(project["project_id"], repo_path)
        deterministic_findings = pattern_findings + secret_findings + dependency_result["findings"]

        deep_scan_status, deep_scan_findings = await run_ai_model_deep_scan(repo_path)

        return self._build_and_save_report(
            feature_id=feature_id, feature=feature, project=project,
            deterministic_findings=deterministic_findings, dependency_result=dependency_result,
            llm_review_status=deep_scan_status, llm_findings=deep_scan_findings,
            scan_type="ai_model_deep_scan",
        )

    async def run_ai_model_scan_stream(self, feature_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming sibling of run_ai_model_scan -- real, live progress instead of one blocking
        response, so a human watching the Result panel sees a genuine percentage instead of a bare
        "Scanning with model..." label. Stopping mid-scan needs no special handling here: FastAPI/
        Starlette cancels this generator when the client disconnects (already proven elsewhere in
        this codebase, see item 44 in CLAUDE.md), and _build_and_save_report is only ever reached
        at the very end -- a stopped scan simply never saves a report.

        Events:
            {"type": "phase", "phase": "...", "label": "..."}
            {"type": "batch_started", "batch_index": i, "total": N, "files": [rel, rel, ...]}
            {"type": "batch_finished", "batch_index": i, "total": N, "completed_count": c, "label": "..."}
            {"type": "error", "message": "..."}
            {"type": "done", "artifact_ids": [...], "message": "...", "gate_decision": "...", "findings_count": N}

        "batch_started"/"batch_finished" (deep_scan.py's own events, passed through verbatim by the
        `else: yield event` below -- this method never inspects their shape) replace what used to
        be a single "progress" event once deep_scan.py's batches started running CONCURRENTLY
        (bounded by DEEP_SCAN_MAX_CONCURRENT_BATCHES) instead of one at a time -- see that module's
        own docstring for why a single overloaded "current" field stopped being meaningful once
        batches can finish out of submission order.
        """
        feature = store.features.get(feature_id)
        project = store.projects.get(feature["project_id"])

        repo_path = workspace_service.get_repo_path(project["project_id"])

        if not repo_path.exists():
            logger.warning("Security Agent: repo path %s does not exist, skipping scan", repo_path)
            yield {"type": "error", "message": f"No workspace found at {repo_path} for this feature yet."}
            return

        yield {
            "type": "phase", "phase": "deterministic",
            "label": "Running pattern, secret, and dependency scans...",
        }
        pattern_findings = scan_dangerous_patterns(repo_path)
        secret_findings = scan_secrets(repo_path)
        dependency_result = scan_dependencies(project["project_id"], repo_path)
        deterministic_findings = pattern_findings + secret_findings + dependency_result["findings"]

        deep_scan_status = "AI model deep scan did not run."
        deep_scan_findings: list[dict[str, Any]] = []
        async for event in run_ai_model_deep_scan_stream(repo_path):
            if event["type"] == "deep_scan_result":
                deep_scan_status = event["status"]
                deep_scan_findings = event["findings"]
            else:
                yield event

        yield {"type": "phase", "phase": "saving", "label": "Saving the security report..."}

        output = self._build_and_save_report(
            feature_id=feature_id, feature=feature, project=project,
            deterministic_findings=deterministic_findings, dependency_result=dependency_result,
            llm_review_status=deep_scan_status, llm_findings=deep_scan_findings,
            scan_type="ai_model_deep_scan",
        )

        yield {
            "type": "done",
            "artifact_ids": output.artifact_ids,
            "message": output.message,
            "gate_decision": output.gate_decision,
            "findings_count": output.findings_count,
        }

    def _build_and_save_report(
        self, *, feature_id: str, feature: dict, project: dict,
        deterministic_findings: list[dict], dependency_result: dict,
        llm_review_status: str, llm_findings: list[dict], scan_type: str,
    ) -> SecurityAgentOutput:
        """Shared tail for both run() and run_ai_model_scan() -- computes the gate/tier counts via
        the unchanged severity.py functions, builds and saves the JSON+Markdown report pair (same
        ArtifactType.SECURITY_REPORT, same PENDING/soft-gate flow either way), differing only in
        which findings/status feed in and the scan_type label carried on the saved report."""
        all_findings = deterministic_findings + llm_findings
        tier_counts = severity.count_by_tier(all_findings)
        gate = severity.gate_decision(all_findings)

        report = {
            "project_name": project["project_name"],
            "feature_name": feature["feature_name"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scan_type": scan_type,
            "gate_decision": gate,
            "findings_count": len(all_findings),
            "critical_count": tier_counts["critical"],
            "moderate_count": tier_counts["moderate"],
            "warning_count": tier_counts["warning"],
            "findings": all_findings,
            "dependency_scan": {
                "audit_exit_code": dependency_result["audit_exit_code"],
                "audit_ran_offline": dependency_result["audit_ran_offline"],
                "dependency_summary": dependency_result["dependency_summary"],
            },
            "llm_review_status": llm_review_status,
        }

        markdown = _build_markdown_report(report)

        json_artifact = artifact_service.save_json_artifact(
            project=project, feature=feature,
            agent_name=AgentName.SECURITY, artifact_type=ArtifactType.SECURITY_REPORT,
            filename="security_report_v{version}.json", data=report,
            approval_status=ApprovalStatus.PENDING,
        )
        md_artifact = artifact_service.save_text_artifact(
            project=project, feature=feature,
            agent_name=AgentName.SECURITY, artifact_type=ArtifactType.SECURITY_REPORT,
            artifact_format=ArtifactFormat.MARKDOWN,
            filename="security_report_v{version}.md", content=markdown,
            version_override=json_artifact.version,
            approval_status=ApprovalStatus.PENDING,
        )

        logger.info(
            "Security Agent finished for feature_id=%s: %d findings, gate=%s, scan_type=%s",
            feature_id, len(all_findings), gate, scan_type,
        )

        return SecurityAgentOutput(
            security_report_json=report,
            status="completed",
            gate_decision=gate,
            findings_count=len(all_findings),
            critical_count=tier_counts["critical"],
            moderate_count=tier_counts["moderate"],
            warning_count=tier_counts["warning"],
            artifact_ids=[json_artifact.artifact_id, md_artifact.artifact_id],
            message=f"{len(all_findings)} finding(s), gate={gate}.",
            scan_type=scan_type,
        )

    async def _run_llm_review_layer(self, findings: list[dict]) -> tuple[str, list[dict]]:
        """Returns (status message, list of new SecurityFinding-shaped dicts). Never raises --
        an unreachable provider or a malformed/unparseable response both degrade to an empty
        findings list with an explanatory status, so the deterministic findings (this stage's
        actual evidence) are always unaffected."""
        try:
            from app.services.llm_provider_service import llm_provider_service

            provider = llm_provider_service.get_provider(agent_name=AgentName.SECURITY.value)
            summary = "\n".join(
                f"- {f['rule_id']} ({f['severity']}) {f['file']}:{f.get('line')}: {f['message']}"
                for f in findings
            ) or "No deterministic findings."
            raw_output = await provider.invoke_agent([
                {"role": "system", "content": SECURITY_AGENT_SYSTEM_PROMPT},
                {"role": "user", "content": f"Deterministic findings so far:\n{summary}"},
            ])

            try:
                parsed = extract_json_object(raw_output)
                review = SecurityLLMReviewResult.model_validate(parsed)
            except (ValueError, ValidationError) as parse_error:
                logger.warning(
                    "Security Agent LLM review layer returned unparseable output, skipping: %s",
                    parse_error,
                )
                return (
                    f"Skipped -- LLM response could not be parsed as the expected findings JSON "
                    f"({type(parse_error).__name__}). The deterministic layers above are "
                    f"unaffected and are this report's evidence.",
                    [],
                )

            llm_findings = [
                {
                    "id": f"SEC-LLM:{index}",
                    "rule_id": "SEC-LLM-REVIEW",
                    "layer": "llm",
                    "severity": item.severity,
                    "cwe": item.cwe or "N/A",
                    "file": item.file,
                    "line": item.line,
                    "message": f"{item.title} -- {item.description}".strip(" -"),
                    "root_cause": item.root_cause,
                    "recommendation": item.recommendation,
                }
                for index, item in enumerate(review.additional_findings, start=1)
            ]

            status = f"LLM review layer ran successfully: {len(llm_findings)} additional finding(s)."
            if review.notes:
                status += f" Notes: {review.notes}"
            return status, llm_findings
        except Exception as error:  # noqa: BLE001 -- an unreachable LLM must not fail the whole scan
            logger.warning("Security Agent LLM review layer unavailable, skipping: %s", error)
            return (
                f"Skipped -- LLM provider unreachable in this run ({type(error).__name__}). "
                f"The three deterministic layers above (pattern, secret, dependency) are "
                f"unaffected and are this report's evidence.",
                [],
            )

    def _load_latest_security_report(self, feature_id: str) -> dict | None:
        # Reuses the generic, already-existing artifact_service helper (item 36 in this project's
        # own CLAUDE.md) rather than a private per-agent duplicate -- Security Agent has never had
        # one of its own (run() always generates a fresh report, it never looks a prior one up).
        artifact = artifact_service.get_selected_or_latest_approved_artifact(
            feature_id, ArtifactType.SECURITY_REPORT.value, ArtifactFormat.JSON.value,
        )
        if not artifact:
            return None
        return read_json_file(artifact["file_path"])

    def _summarize_report_for_chat(self, report: dict) -> str:
        lines = [
            f"Security report for {report.get('feature_name', 'this feature')} "
            f"(generated {report.get('generated_at')}): {report.get('findings_count', 0)} finding(s) -- "
            f"{report.get('critical_count', 0)} critical, {report.get('moderate_count', 0)} moderate, "
            f"{report.get('warning_count', 0)} warning. Gate decision: {report.get('gate_decision', 'unknown')}.",
        ]
        for finding in report.get("findings", []):
            loc = f"{finding.get('file')}:{finding.get('line')}" if finding.get("line") else finding.get("file", "")
            line = (
                f"- [{(finding.get('severity') or '').upper()}] {finding.get('rule_id', '')} "
                f"({finding.get('cwe', 'N/A')}) -- {loc} -- {finding.get('message', '')}"
            )
            if finding.get("root_cause"):
                line += f" | Root cause: {finding['root_cause']}"
            if finding.get("recommendation"):
                line += f" | Fix: {finding['recommendation']}"
            lines.append(line)
        dependency_scan = report.get("dependency_scan") or {}
        lines.append(
            f"Dependency scan: npm audit exit code {dependency_scan.get('audit_exit_code')} "
            f"({'offline' if dependency_scan.get('audit_ran_offline') else 'online'})."
        )
        lines.append(f"LLM review layer: {report.get('llm_review_status', 'unknown')}.")
        return "\n".join(lines)

    def _get_chat_history(self, feature_id: str) -> list[dict]:
        document = store.security_conversations.get(feature_id)
        return document.get("turns", []) if document else []

    def _append_chat_turns(self, feature_id: str, new_turns: list[dict]) -> None:
        """Assigns a real, stable `turn_index` (1-based) to every turn in `new_turns` -- the same
        value to BOTH the user turn and its assistant reply in a pair, so a later edit can address
        "this exchange" by one number. Direct user request: let a human edit a past message --
        needs a stable identifier, since array position alone shifts once edits start
        truncating/replacing history (mirrors requirement_agent's own turn_index precedent, though
        Requirement assigns it per-reply rather than per-pair since its conversation model
        differs)."""
        existing = self._get_chat_history(feature_id)
        next_index = max((turn.get("turn_index", 0) for turn in existing), default=0) + 1
        for turn in new_turns:
            turn["turn_index"] = next_index
        store.security_conversations[feature_id] = {"feature_id": feature_id, "turns": existing + new_turns}

    async def chat_stream(self, feature_id: str, message: str) -> AsyncGenerator[dict[str, Any], None]:
        """
        Pure Q&A about this feature's latest security report -- see prompt.py's
        SECURITY_CHAT_SYSTEM_PROMPT for the explicit "discuss, never edit code" boundary (a
        separate, already-existing frontend action -- SecurityReportView.jsx's "Send to Coder
        Agent" button, via securityReportToRevisionComment.js -- re-uses the Coder Agent's own
        real revise() flow for actually fixing something). Streams real tokens via the configured
        provider's own `.stream()` (Ollama or Anthropic, whichever this agent is currently set to
        -- llm_provider_service.get_provider, the same one-shot/no-tool-calling call shape this
        agent's own LLM review layer already uses), then persists both the human's message and
        the full reply to store.security_conversations so a reload doesn't lose the conversation.

        Mirrors qa_agent.agent.QAAgent.chat_stream exactly -- same NDJSON event shape
        ({"type": "token"|"done"|"error", ...}), same never-block-on-a-missing-report behavior.
        """
        async for event in self._chat_stream_core(feature_id, message):
            yield event

    async def edit_chat_turn_stream(
        self, feature_id: str, turn_index: int, new_message: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Direct user request: edit a past message and regenerate the conversation from that point
        forward, mirroring requirement_agent.edit_turn_reply_stream's own rewind semantics --
        discards the edited turn (and its reply) and everything after it, then continues as a
        fresh chat_stream call from the truncated history. Simpler than Requirement's version:
        Security chat has no gap-analysis/assumptions state to rebuild, just a transcript.
        """
        history = self._get_chat_history(feature_id)
        if not any(turn.get("turn_index") == turn_index for turn in history):
            yield {"type": "error", "message": f"No turn {turn_index} found to edit."}
            return

        kept = [turn for turn in history if turn.get("turn_index", 0) < turn_index]
        store.security_conversations[feature_id] = {"feature_id": feature_id, "turns": kept}

        async for event in self._chat_stream_core(feature_id, new_message):
            yield event

    async def _chat_stream_core(self, feature_id: str, message: str) -> AsyncGenerator[dict[str, Any], None]:
        """Shared by chat_stream/edit_chat_turn_stream -- always re-reads history fresh via
        _get_chat_history, so a caller that already truncated it (edit_chat_turn_stream) sees the
        truncated transcript with no other code path needed."""
        from app.services.llm_provider_service import llm_provider_service

        report = self._load_latest_security_report(feature_id)
        report_context = (
            self._summarize_report_for_chat(report) if report
            else "No security report has been generated for this feature yet."
        )

        history = self._get_chat_history(feature_id)
        transcript_lines = [f"{turn['role'].capitalize()}: {turn['content']}" for turn in history]
        transcript_lines.append(f"User: {message}")
        prompt = "\n\n".join(transcript_lines)
        system_prompt = f"{SECURITY_CHAT_SYSTEM_PROMPT}\n\nCurrent security report:\n{report_context}"

        try:
            provider = llm_provider_service.get_provider(agent_name=AgentName.SECURITY.value)
        except Exception as error:  # noqa: BLE001
            yield {"type": "error", "message": f"Security chat could not reach a configured provider: {error}"}
            return

        full_reply = ""
        try:
            async for chunk in provider.stream(prompt, system_prompt=system_prompt):
                full_reply += chunk
                yield {"type": "token", "text": chunk}
        except Exception as error:  # noqa: BLE001
            yield {"type": "error", "message": f"Security chat failed: {error}"}
            return

        now = datetime.now(timezone.utc).isoformat()
        self._append_chat_turns(feature_id, [
            {"role": "user", "content": message, "created_at": now},
            {"role": "assistant", "content": full_reply, "created_at": now},
        ])
        yield {"type": "done", "message": full_reply}


security_agent = SecurityAgent()
