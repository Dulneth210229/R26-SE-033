"""
QA Agent.

Turns a Coder-Agent-generated feature into real, executable evidence of whether it works: writes
Unit tests (one module in isolation), Integration tests (a Route Handler together with the real
model/lib files it imports, exercising the real request -> handler -> data flow), and Regression
tests (one per the feature's own approved acceptance criteria) -- see discovery.py/generator.py
for how each category is discovered and generated, and prompt.py for the exact structured
response shape every generation call returns (test_cases metadata + real test_code, parsed the
same resilient way Security Agent's LLM review layer already established: extract, validate,
degrade to a fallback on anything malformed, never fail the whole run over one bad response).

Runs the real suite through Jest inside the same sandboxed execution path every other agent uses
(see executor.py for why Jest replaced the earlier zero-dependency `node:test` runner: its
built-in `--json` output already contains real per-test structured results), then matches each
execution result back to the QaTestCase that planned it (by test_file + name) so the saved report
carries BOTH halves for every test: what it was written to verify (target file/function, inputs,
expected behavior) and what actually happened when it ran (status, duration, the real failure
message).

Auto-approved stage (`ApprovalStatus.APPROVED`), matching QA's continued membership in
`AUTO_APPROVED_STAGES` (graph_orchestrator_service.py) -- unlike Security Agent, this was not
part of the direct request to change; a human reviews the report after the fact rather than
gating on it.
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from app.agents.qa_agent import discovery, executor, generator
from app.agents.qa_agent.prompt import QA_CHAT_SYSTEM_PROMPT
from app.agents.qa_agent.schemas import QAAgentOutput, QaTestCase
from app.core.enums import AgentName, ApprovalStatus, ArtifactFormat, ArtifactType
from app.services.artifact_service import artifact_service
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.file_manager import read_json_file
from app.utils.logger import get_logger

logger = get_logger(__name__)

GENERATED_TESTS_DIRNAME = "generated_tests"
CATEGORIES = ("unit", "integration", "regression")


def _build_markdown_report(report: dict) -> str:
    lines = [
        f"# QA Report -- {report['project_name']} / {report['feature_name']}",
        "",
        f"Generated: {report['generated_at']}",
        f"Framework: {report['framework_used']}",
        f"Tests written: {report['tests_generated']} "
        f"(unit {report['tests_by_category']['unit']['total']}, "
        f"integration {report['tests_by_category']['integration']['total']}, "
        f"regression {report['tests_by_category']['regression']['total']})",
        f"Result: {report['tests_passed']} passed, {report['tests_failed']} failed",
        "",
    ]
    if report.get("environment_failure"):
        lines += [
            "> **The test run itself could not execute** -- this is an infrastructure problem, "
            "not necessarily a defect in the generated code:",
            f"> {report['environment_failure']['reason']}",
            "",
        ]
    lines += [
        "## Test cases",
        "",
    ]
    if not report["test_cases"]:
        lines.append("No test cases were generated.")
    for tc in report["test_cases"]:
        status = tc["status"].upper()
        loc = f"{tc['target_file']}::{tc['target_function']}" if tc["target_function"] else tc["target_file"]
        lines.append(f"- **[{status}]** ({tc['category']}) {tc['name']} -- targets `{loc}`")
        if tc.get("failure_message"):
            lines.append(f"  - {tc['failure_message'].splitlines()[0]}")
        if tc.get("root_cause"):
            lines.append(f"  - Root cause: {tc['root_cause']}")
        if tc.get("recommendation"):
            lines.append(f"  - Recommendation: {tc['recommendation']}")
    lines += [
        "",
        "## Out of scope for this pass",
        "",
    ]
    for path in report["out_of_scope_modules"]:
        lines.append(f"- `{path}`")
    if report["raw_stderr"]:
        lines += ["", "## Test runner stderr (tail)", "", "```", report["raw_stderr"][-2000:], "```"]
    return "\n".join(lines)


class QAAgent:
    async def run(self, **kwargs) -> QAAgentOutput:
        feature_id = kwargs["feature_id"]
        feature = store.features.get(feature_id)
        project = store.projects.get(feature["project_id"])

        repo_path = workspace_service.get_repo_path(project["project_id"])

        if not repo_path.exists():
            logger.warning("QA Agent: repo path %s does not exist, skipping", repo_path)
            return QAAgentOutput(status="skipped", message=f"No workspace found at {repo_path} yet.")

        unit_targets = discovery.discover_unit_test_targets(repo_path)
        integration_targets = discovery.discover_integration_test_targets(repo_path)
        out_of_scope = discovery.discover_out_of_scope_modules(repo_path)
        acceptance_criteria = self._load_approved_acceptance_criteria(feature_id)

        generated_dir = repo_path / GENERATED_TESTS_DIRNAME
        generated_dir.mkdir(exist_ok=True)
        # A fresh run must not accumulate stale test files from a previous run (a since-renamed/
        # deleted module's old test would otherwise keep being executed and reported forever).
        for stale in generated_dir.glob("*.test.ts"):
            stale.unlink()

        all_test_cases: list[QaTestCase] = []

        for target in unit_targets:
            result = await generator.generate_unit_tests(target)
            if result is None:
                continue
            filename = self._write_test_file(generated_dir, Path(target["rel"]).stem, "unit", result.test_code)
            for tc in result.test_cases:
                tc.test_file = filename
                all_test_cases.append(tc)

        for target in integration_targets:
            result = await generator.generate_integration_tests(target)
            if result is None:
                continue
            filename = self._write_test_file(
                generated_dir, Path(target["route_rel"]).parent.name, "integration", result.test_code
            )
            for tc in result.test_cases:
                tc.test_file = filename
                tc.category = "integration"
                all_test_cases.append(tc)

        regression_result = await generator.generate_regression_tests(
            acceptance_criteria, integration_targets[0] if integration_targets else None
        )
        if regression_result is not None:
            filename = self._write_test_file(generated_dir, feature["feature_name"], "regression", regression_result.test_code)
            for tc in regression_result.test_cases:
                tc.test_file = filename
                tc.category = "regression"
                all_test_cases.append(tc)

        if all_test_cases:
            run_result = executor.run_tests(repo_path, project["project_id"])
        else:
            run_result = {"results": [], "passed": 0, "failed": 0, "exit_code": None, "raw_stderr": ""}

        return await self._finalize_report(
            feature_id, feature, project, all_test_cases, run_result, unit_targets, integration_targets, out_of_scope,
        )

    async def run_stream(self, feature_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """
        Streaming sibling of run() -- direct user request, mirrors Architecture Agent's own
        run/run_stream split (a parallel, narrower method sharing only the deterministic tail, not
        a thin wrapper around run()). Generation is SEQUENTIAL, unlike Security Agent's read-only
        concurrent deep-scan batches -- each pass writes a real file to disk and they all share one
        `ensure_jest_setup()` before execution, so concurrent writes here would be a real, new
        correctness risk Security's pure-read scanning never had. Progress is therefore reported
        per-target as generation genuinely proceeds, not via concurrent batch events.
        """
        feature = store.features.get(feature_id)
        project = store.projects.get(feature["project_id"])

        repo_path = workspace_service.get_repo_path(project["project_id"])
        if not repo_path.exists():
            yield {"type": "error", "message": f"No workspace found at {repo_path} yet."}
            return

        yield {"type": "phase", "phase": "discovery", "label": "Scanning the codebase for testable files..."}

        unit_targets = discovery.discover_unit_test_targets(repo_path)
        integration_targets = discovery.discover_integration_test_targets(repo_path)
        out_of_scope = discovery.discover_out_of_scope_modules(repo_path)
        acceptance_criteria = self._load_approved_acceptance_criteria(feature_id)

        generated_dir = repo_path / GENERATED_TESTS_DIRNAME
        generated_dir.mkdir(exist_ok=True)
        for stale in generated_dir.glob("*.test.ts"):
            stale.unlink()

        all_test_cases: list[QaTestCase] = []
        total_targets = len(unit_targets) + len(integration_targets) + (1 if acceptance_criteria else 0)
        completed = 0

        for target in unit_targets:
            completed += 1
            yield {
                "type": "generation_progress", "category": "unit", "target": target["rel"],
                "index": completed, "total": total_targets,
                "label": f"Writing unit tests for {target['rel']} ({completed}/{total_targets})...",
            }
            result = await generator.generate_unit_tests(target)
            if result is None:
                continue
            filename = self._write_test_file(generated_dir, Path(target["rel"]).stem, "unit", result.test_code)
            for tc in result.test_cases:
                tc.test_file = filename
                all_test_cases.append(tc)

        for target in integration_targets:
            completed += 1
            yield {
                "type": "generation_progress", "category": "integration", "target": target["route_rel"],
                "index": completed, "total": total_targets,
                "label": f"Writing integration tests for {target['route_rel']} ({completed}/{total_targets})...",
            }
            result = await generator.generate_integration_tests(target)
            if result is None:
                continue
            filename = self._write_test_file(
                generated_dir, Path(target["route_rel"]).parent.name, "integration", result.test_code
            )
            for tc in result.test_cases:
                tc.test_file = filename
                tc.category = "integration"
                all_test_cases.append(tc)

        if acceptance_criteria:
            completed += 1
            yield {
                "type": "generation_progress", "category": "regression", "target": feature["feature_name"],
                "index": completed, "total": total_targets,
                "label": f"Writing regression tests from acceptance criteria ({completed}/{total_targets})...",
            }
            regression_result = await generator.generate_regression_tests(
                acceptance_criteria, integration_targets[0] if integration_targets else None
            )
            if regression_result is not None:
                filename = self._write_test_file(
                    generated_dir, feature["feature_name"], "regression", regression_result.test_code
                )
                for tc in regression_result.test_cases:
                    tc.test_file = filename
                    tc.category = "regression"
                    all_test_cases.append(tc)

        if all_test_cases:
            yield {"type": "phase", "phase": "execution", "label": "Running the generated tests..."}
            run_result = executor.run_tests(repo_path, project["project_id"])
        else:
            run_result = {"results": [], "passed": 0, "failed": 0, "exit_code": None, "raw_stderr": ""}

        if run_result["failed"] > 0:
            yield {"type": "phase", "phase": "root_cause", "label": "Analyzing failures..."}

        yield {"type": "phase", "phase": "saving", "label": "Saving the QA report..."}
        output = await self._finalize_report(
            feature_id, feature, project, all_test_cases, run_result, unit_targets, integration_targets, out_of_scope,
        )

        yield {
            "type": "done",
            "artifact_ids": output.artifact_ids,
            "message": output.message,
            "tests_generated": output.tests_generated,
            "tests_passed": output.tests_passed,
            "tests_failed": output.tests_failed,
        }

    async def _finalize_report(
        self, feature_id: str, feature: dict, project: dict, all_test_cases: list[QaTestCase],
        run_result: dict, unit_targets: list[dict], integration_targets: list[dict], out_of_scope: list[str],
    ) -> QAAgentOutput:
        """Shared tail for run()/run_stream(): merge real results, synthesize root causes for any
        failures, build and save the report (JSON + Markdown), same for both entry points."""
        merged_test_cases = self._merge_results(all_test_cases, run_result["results"])

        # A real, whole-environment failure (Jest itself never produced ANY results, despite
        # tests genuinely having been planned -- e.g. the sandbox was unreachable, or a broken
        # node_modules install) is a distinct, honest signal from "these specific tests have real
        # defects." Every individual test case above still resolves to "failed" (never "skipped"
        # -- direct user requirement), but reclassifying every one of them as an independent
        # defect would (a) read as "N real bugs" when it's actually one infrastructure problem,
        # and (b) -- a real risk a Plan-agent design review caught -- silently trigger
        # _apply_root_cause_analysis's real LLM call to fabricate plausible-sounding root causes
        # for tests that never ran at all. Both are avoided by surfacing this as its own field and
        # skipping root-cause analysis entirely when it's set.
        environment_failure = None
        if all_test_cases and not run_result["results"]:
            environment_failure = {
                "reason": run_result.get("raw_stderr")
                or "The test runner produced no results and no error output.",
            }

        if environment_failure is None:
            merged_test_cases = await self._apply_root_cause_analysis(
                merged_test_cases, unit_targets, integration_targets
            )
        tests_by_category = self._count_by_category(merged_test_cases)

        # Real, confirmed inconsistency found during live verification: run_result's own
        # passed/failed counts are Jest's raw reported totals, which stay 0/0 whenever Jest never
        # actually produced a result for a test case (e.g. the sandbox was unavailable) --
        # while _merge_results/_count_by_category correctly resolve each unmatched case locally.
        # Deriving the top-level counts from the SAME merged_test_cases the per-category
        # breakdown already uses keeps both numbers honest and in agreement.
        tests_passed = sum(bucket["passed"] for bucket in tests_by_category.values())
        tests_failed = sum(bucket["failed"] for bucket in tests_by_category.values())

        report = {
            "project_name": project["project_name"],
            "feature_name": feature["feature_name"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "framework_used": "jest",
            "tests_generated": len(all_test_cases),
            "tests_passed": tests_passed,
            "tests_failed": tests_failed,
            "tests_by_category": tests_by_category,
            "test_cases": merged_test_cases,
            "out_of_scope_modules": out_of_scope,
            "raw_stderr": run_result["raw_stderr"],
            "environment_failure": environment_failure,
        }
        markdown = _build_markdown_report(report)

        json_artifact = artifact_service.save_json_artifact(
            project=project, feature=feature,
            agent_name=AgentName.QA, artifact_type=ArtifactType.QA_REPORT,
            filename="qa_report_v{version}.json", data=report,
            approval_status=ApprovalStatus.APPROVED,
        )
        md_artifact = artifact_service.save_text_artifact(
            project=project, feature=feature,
            agent_name=AgentName.QA, artifact_type=ArtifactType.QA_REPORT,
            artifact_format=ArtifactFormat.MARKDOWN,
            filename="qa_report_v{version}.md", content=markdown,
            version_override=json_artifact.version,
            approval_status=ApprovalStatus.APPROVED,
        )

        logger.info(
            "QA Agent finished for feature_id=%s: %d generated, %d passed, %d failed%s",
            feature_id, len(all_test_cases), tests_passed, tests_failed,
            " (environment failure)" if environment_failure else "",
        )

        return QAAgentOutput(
            qa_report_json=report,
            status="completed",
            framework_used="jest",
            tests_generated=len(all_test_cases),
            tests_passed=tests_passed,
            tests_failed=tests_failed,
            artifact_ids=[json_artifact.artifact_id, md_artifact.artifact_id],
            message=f"{tests_passed} passed, {tests_failed} failed.",
        )

    def _write_test_file(self, generated_dir: Path, stem: str, category: str, test_code: str) -> str:
        import re
        safe_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-") or category
        filename = f"{safe_stem}.{category}.test.ts"
        (generated_dir / filename).write_text(test_code, encoding="utf-8")
        return filename

    def _merge_results(self, test_cases: list[QaTestCase], results: list[dict]) -> list[dict]:
        """Matches each planned QaTestCase to its real execution result in two tiers.

        Tier 1: exact (test_file, name) match -- the pairing prompt.py's own testing-conventions
        section instructs the LLM to preserve (every test_cases[].name must appear verbatim as
        the real test's title). Preferred whenever available.

        Tier 2: for a planned case left unmatched after tier 1, if its test_file has real Jest
        results that are themselves unclaimed by any exact match, pair it positionally (in
        encounter order) with one of those leftover results. test_file is assigned
        deterministically by _write_test_file (never LLM-authored) and is therefore reliable;
        name is the only unreliable half of the match key, since it depends on the LLM writing
        the identical string twice (once in its metadata JSON, once as the real Jest test title).
        This compensates for minor title-wording drift without ever inventing a result that
        doesn't exist. (A Plan-agent design review confirmed this two-tier design should stay
        exactly as-is, not be replaced with pure positional matching -- Tier 1 is what correctly
        disambiguates two same-file results when only ONE test's name actually drifted; reducing
        how often Tier 2 is even needed is handled instead by generator.py's forbidden-construct
        scan, which keeps test.each/describe.each/test.concurrent -- the real cardinality-mismatch
        risk -- out of generated code entirely.)

        A planned case still unmatched after both tiers (genuinely fewer real results than
        planned in that file -- e.g. the file crashed partway through) is reported as "failed"
        (never "skipped" -- direct user requirement: every test case resolves to passed or failed
        only), with an explicit note explaining it never produced a matching result.
        """
        results_by_key = {(r["test_file"], r["name"]): r for r in results}

        claimed_result_ids: set[int] = set()
        for tc in test_cases:
            match = results_by_key.get((tc.test_file, tc.name))
            if match is not None:
                claimed_result_ids.add(id(match))

        leftover_results_by_file: dict[str, list[dict]] = {}
        for r in results:
            if id(r) not in claimed_result_ids:
                leftover_results_by_file.setdefault(r["test_file"], []).append(r)

        merged = []
        for tc in test_cases:
            match = results_by_key.get((tc.test_file, tc.name))
            if match is None:
                leftovers = leftover_results_by_file.get(tc.test_file)
                if leftovers:
                    match = leftovers.pop(0)
            merged.append({
                "name": tc.name,
                "category": tc.category,
                "target_file": tc.target_file,
                "target_function": tc.target_function,
                "inputs": tc.inputs,
                "expected_behavior": tc.expected_behavior,
                "test_file": tc.test_file,
                "method": tc.method,
                "status": match["status"] if match else "failed",
                "duration_ms": match.get("duration_ms") if match else None,
                "failure_message": (match.get("failure_message") if match
                                     else ("This test file did not produce a matching result -- "
                                           "it may have failed to load/parse; see stderr below.")),
                # Filled in by _apply_root_cause_analysis for failed tests only -- stays None for
                # everything else (never blocks the report if that analysis call fails/is
                # unreachable, see generator.analyze_failures's own resilience contract).
                "root_cause": None,
                "recommendation": None,
            })
        return merged

    async def _apply_root_cause_analysis(
        self, merged_test_cases: list[dict], unit_targets: list[dict], integration_targets: list[dict]
    ) -> list[dict]:
        """
        Direct user request: explain WHY a test actually failed, not just show Jest's raw
        assertion text. One batched LLM call (generator.analyze_failures) covering every failed
        test at once -- never one call per failure. Source lookup is built from targets already
        read during discovery (no re-reading from disk). A no-op (returns merged_test_cases
        unchanged) when there are no failures or the analysis call fails -- root_cause/
        recommendation simply stay None, matching this codebase's established "an LLM enrichment
        step must never block the underlying report" convention.
        """
        failures = [tc for tc in merged_test_cases if tc["status"] == "failed"]
        if not failures:
            return merged_test_cases

        source_by_target_file = {t["rel"]: t["source"] for t in unit_targets}
        source_by_target_file.update({t["route_rel"]: t["route_source"] for t in integration_targets})

        root_causes = await generator.analyze_failures(failures, source_by_target_file)
        if not root_causes:
            return merged_test_cases

        for tc in merged_test_cases:
            entry = root_causes.get((tc["test_file"], tc["name"]))
            if entry:
                tc["root_cause"] = entry["root_cause"]
                tc["recommendation"] = entry["recommendation"]
        return merged_test_cases

    def _count_by_category(self, merged_test_cases: list[dict]) -> dict:
        counts = {cat: {"total": 0, "passed": 0, "failed": 0} for cat in CATEGORIES}
        for tc in merged_test_cases:
            bucket = counts.setdefault(tc["category"], {"total": 0, "passed": 0, "failed": 0})
            bucket["total"] += 1
            bucket[tc["status"]] = bucket.get(tc["status"], 0) + 1
        return counts

    def _load_approved_acceptance_criteria(self, feature_id: str) -> list[dict]:
        artifact = self._find_latest_approved_artifact(
            feature_id=feature_id,
            agent_name=AgentName.REQUIREMENT,
            artifact_type=ArtifactType.SRS,
            artifact_format=ArtifactFormat.JSON,
        )
        if not artifact:
            return []
        srs = read_json_file(artifact["file_path"])
        return srs.get("acceptance_criteria", []) if srs else []

    def _find_latest_approved_artifact(self, feature_id: str, agent_name: AgentName,
                                        artifact_type: ArtifactType, artifact_format: ArtifactFormat) -> dict | None:
        matching_artifacts = []
        for artifact in store.artifacts.values():
            if artifact.get("feature_id") != feature_id:
                continue
            if artifact.get("agent_name") not in [agent_name, agent_name.value]:
                continue
            if artifact.get("artifact_type") not in [artifact_type, artifact_type.value]:
                continue
            if artifact.get("artifact_format") not in [artifact_format, artifact_format.value]:
                continue
            if artifact.get("approval_status") not in [ApprovalStatus.APPROVED, ApprovalStatus.APPROVED.value]:
                continue
            matching_artifacts.append(artifact)

        if not matching_artifacts:
            return None
        return max(matching_artifacts, key=lambda item: item.get("version", 1))

    def _load_latest_qa_report(self, feature_id: str) -> dict | None:
        artifact = self._find_latest_approved_artifact(
            feature_id=feature_id, agent_name=AgentName.QA,
            artifact_type=ArtifactType.QA_REPORT, artifact_format=ArtifactFormat.JSON,
        )
        if not artifact:
            return None
        return read_json_file(artifact["file_path"])

    def _summarize_report_for_chat(self, report: dict) -> str:
        lines = [
            f"QA report for {report['feature_name']} (generated {report['generated_at']}): "
            f"{report['tests_passed']} passed, {report['tests_failed']} failed.",
        ]
        if report.get("environment_failure"):
            lines.append(
                f"Note: the test run itself could not execute -- {report['environment_failure']['reason']}"
            )
        for tc in report.get("test_cases", []):
            loc = f"{tc['target_file']}::{tc['target_function']}" if tc.get("target_function") else tc["target_file"]
            line = f"- [{tc['status'].upper()}] ({tc['category']}) {tc['name']} -- targets {loc}"
            if tc.get("failure_message"):
                line += f" -- failure: {tc['failure_message'][:300]}"
            if tc.get("root_cause"):
                line += f" -- root cause: {tc['root_cause']}"
            if tc.get("recommendation"):
                line += f" -- recommendation: {tc['recommendation']}"
            lines.append(line)
        return "\n".join(lines)

    def _get_chat_history(self, feature_id: str) -> list[dict]:
        document = store.qa_conversations.get(feature_id)
        return document.get("turns", []) if document else []

    def _append_chat_turns(self, feature_id: str, new_turns: list[dict]) -> None:
        """Assigns a real, stable `turn_index` (1-based) to every turn in `new_turns` -- the same
        value to BOTH the user turn and its assistant reply in a pair, so a later edit can address
        "this exchange" by one number. Direct user request: let a human edit a past message --
        mirrors security_agent.agent.SecurityAgent's own identical addition."""
        existing = self._get_chat_history(feature_id)
        next_index = max((turn.get("turn_index", 0) for turn in existing), default=0) + 1
        for turn in new_turns:
            turn["turn_index"] = next_index
        store.qa_conversations[feature_id] = {"feature_id": feature_id, "turns": existing + new_turns}

    async def chat_stream(self, feature_id: str, message: str) -> AsyncGenerator[dict[str, Any], None]:
        """Pure Q&A -- see prompt.py's QA_CHAT_SYSTEM_PROMPT for the explicit "discuss, never
        edit code" boundary (an explicit, separate frontend action re-uses the Coder Agent's own
        real revise() flow for actually fixing something -- see
        qaReportToRevisionComment.js). Streams real tokens via the configured provider's own
        `.stream()` (Ollama or Anthropic, whichever this agent is currently set to --
        llm_provider_service.get_provider, the exact one-shot/no-tool-calling call shape Security
        Agent's LLM review layer already established, so either provider family works with no
        tool-calling requirement), then persists both the human's message and the full reply to
        store.qa_conversations so a reload doesn't lose the conversation."""
        async for event in self._chat_stream_core(feature_id, message):
            yield event

    async def edit_chat_turn_stream(
        self, feature_id: str, turn_index: int, new_message: str
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Direct user request: edit a past message and regenerate from that point forward --
        mirrors security_agent.agent.SecurityAgent.edit_chat_turn_stream exactly. Discards the
        edited turn (and its reply) and everything after it, then continues as a fresh chat_stream
        call from the truncated history."""
        history = self._get_chat_history(feature_id)
        if not any(turn.get("turn_index") == turn_index for turn in history):
            yield {"type": "error", "message": f"No turn {turn_index} found to edit."}
            return

        kept = [turn for turn in history if turn.get("turn_index", 0) < turn_index]
        store.qa_conversations[feature_id] = {"feature_id": feature_id, "turns": kept}

        async for event in self._chat_stream_core(feature_id, new_message):
            yield event

    async def _chat_stream_core(self, feature_id: str, message: str) -> AsyncGenerator[dict[str, Any], None]:
        """Shared by chat_stream/edit_chat_turn_stream -- always re-reads history fresh via
        _get_chat_history, so a caller that already truncated it (edit_chat_turn_stream) sees the
        truncated transcript with no other code path needed."""
        from app.services.llm_provider_service import llm_provider_service

        report = self._load_latest_qa_report(feature_id)
        report_context = (
            self._summarize_report_for_chat(report) if report
            else "No QA report has been generated for this feature yet."
        )

        history = self._get_chat_history(feature_id)
        transcript_lines = [f"{turn['role'].capitalize()}: {turn['content']}" for turn in history]
        transcript_lines.append(f"User: {message}")
        prompt = "\n\n".join(transcript_lines)
        system_prompt = f"{QA_CHAT_SYSTEM_PROMPT}\n\nCurrent QA report:\n{report_context}"

        try:
            provider = llm_provider_service.get_provider(agent_name=AgentName.QA.value)
        except Exception as error:  # noqa: BLE001 -- surface as a real error event, don't crash the route
            yield {"type": "error", "message": f"QA chat could not reach a configured provider: {error}"}
            return

        full_reply = ""
        try:
            async for chunk in provider.stream(prompt, system_prompt=system_prompt):
                full_reply += chunk
                yield {"type": "token", "text": chunk}
        except Exception as error:  # noqa: BLE001 -- surface as a real error event, don't crash the route
            yield {"type": "error", "message": f"QA chat failed: {error}"}
            return

        now = datetime.now(timezone.utc).isoformat()
        self._append_chat_turns(feature_id, [
            {"role": "user", "content": message, "created_at": now},
            {"role": "assistant", "content": full_reply, "created_at": now},
        ])

        yield {"type": "done", "message": full_reply}


qa_agent = QAAgent()
