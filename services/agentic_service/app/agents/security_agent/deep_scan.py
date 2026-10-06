"""
Security Agent -- AI-model deep-code-read scan layer.

Distinct from agent.py's existing _run_llm_review_layer, which only ever shows the LLM a compact
findings SUMMARY (rule_id/severity/file/line/message strings), never real source. This module
shows the model REAL source file contents directly and asks it to identify genuine vulnerabilities
grounded in that code -- a genuinely new capability, not an extension of the summary-review layer.

Batches real file contents into a bounded number of LLM calls (one call per batch, capped by
MAX_DEEP_SCAN_BATCH_CHARS) -- mirrors this project's own established char-cap-batching precedent
(coder_agent/diff_builder.py's MAX_DIFF_TEXT_CHARS, coder_agent/prompt.py's
MAX_IMPLEMENTATION_SPEC_CHARS) so this never becomes one giant prompt (context-limit risk) nor one
call per file (excessive latency for a real generated project's file count).

Batches are scanned CONCURRENTLY (bounded by DEEP_SCAN_MAX_CONCURRENT_BATCHES), not one-at-a-time
-- direct user request for a "more comprehensive and intelligent" scan surfaced that the real
coverage gap wasn't which files get scanned (already every scannable file, no cap/sampling), it
was that a real multi-file project's scan could mean 10-30+ sequential LLM round-trips. Files are
also sorted by relative path before batching, so files from the same feature/directory reliably
cluster into the same or adjacent batch, giving the model a bit more real cross-file context per
batch for the same character budget.

Never raises -- mirrors _run_llm_review_layer's own resilience contract exactly: a single batch's
provider/parse failure is logged and skipped (that batch simply contributes zero findings), never
aborting the whole scan.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncGenerator

from app.agents.security_agent.prompt import SECURITY_DEEP_SCAN_SYSTEM_PROMPT
from app.agents.security_agent.scanners import list_scannable_files
from app.agents.security_agent.schemas import SecurityDeepScanResult
from app.core.enums import AgentName
from app.utils.json_utils import extract_json_object
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_DEEP_SCAN_BATCH_CHARS = 12_000

# How many batches (each one real LLM call) run at once. Confirmed safe to raise: every provider
# (app/providers/*.py) opens a fresh httpx.AsyncClient per call with no shared mutable state, so
# concurrent calls against one shared `provider` instance are safe. Kept conservative (not higher)
# because a local Ollama server has its own server-side concurrency ceiling (OLLAMA_NUM_PARALLEL,
# often 1 or a small number) -- requests beyond that just queue server-side rather than genuinely
# running in parallel, and a cloud provider (Anthropic/OpenAI) risks real per-minute rate limits at
# higher concurrency. A rate-limited/queued batch still degrades safely to zero findings via
# _scan_one_batch's own existing resilience contract, it just makes hitting that path more likely.
DEEP_SCAN_MAX_CONCURRENT_BATCHES = 3


def _batch_files(repo_path: Path) -> list[list[tuple[str, str]]]:
    """
    Reads every scannable file's real text (rel_path, content) and groups consecutive files into
    batches whose combined rendered text stays under MAX_DEEP_SCAN_BATCH_CHARS. A single file
    larger than the cap alone becomes its own batch (truncated at construction time, not skipped
    -- partial real code is still more useful than nothing).

    Files are sorted by relative path first -- list_scannable_files' own order follows os.walk,
    which is not guaranteed to keep a feature's own related files (e.g. everything under one
    route's directory) adjacent. Sorting is cheap and deterministic and reliably clusters
    same-directory files into the same or adjacent batch.
    """
    files = list_scannable_files(repo_path)
    entries: list[tuple[str, str]] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        entries.append((str(path.relative_to(repo_path)), content))
    entries.sort(key=lambda entry: entry[0])

    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    current_chars = 0

    for rel, content in entries:
        entry_chars = len(rel) + len(content) + 20  # rough overhead for the "# path\n```\n```" wrapper

        if current and current_chars + entry_chars > MAX_DEEP_SCAN_BATCH_CHARS:
            batches.append(current)
            current = []
            current_chars = 0

        current.append((rel, content))
        current_chars += entry_chars

    if current:
        batches.append(current)
    return batches


def _render_batch(batch: list[tuple[str, str]]) -> str:
    parts = []
    for rel, content in batch:
        parts.append(f"# {rel}\n\n```\n{content}\n```\n")
    return "\n".join(parts)


def _get_provider():
    from app.services.llm_provider_service import llm_provider_service

    return llm_provider_service.get_provider(agent_name=AgentName.SECURITY.value)


async def _scan_one_batch(provider, batch: list[tuple[str, str]]) -> tuple[list[dict[str, Any]], bool]:
    """
    Runs one real LLM call over one batch's real source code. Returns (findings without an `id`
    yet, whether the batch succeeded) -- IDs are assigned once, globally, by _assign_ids, so this
    function stays reusable by both the streaming and non-streaming callers without needing to
    share a mutable counter. Never raises -- a provider/parse failure degrades to ([], False),
    logged, never aborting the batches around it.
    """
    batch_text = _render_batch(batch)
    try:
        raw_output = await provider.invoke_agent([
            {"role": "system", "content": SECURITY_DEEP_SCAN_SYSTEM_PROMPT},
            {"role": "user", "content": f"Review this real source code:\n\n{batch_text}"},
        ])
        parsed = extract_json_object(raw_output)
        result = SecurityDeepScanResult.model_validate(parsed)
    except Exception as error:  # noqa: BLE001 -- one bad batch must not fail the whole scan
        logger.warning(
            "Security Agent AI-model deep scan: batch of %d file(s) failed, skipping: %s",
            len(batch), error,
        )
        return [], False

    findings = [
        {
            "rule_id": "SEC-AI-DEEPSCAN",
            "layer": "ai_model_deep_scan",
            "severity": item.severity,
            "cwe": item.cwe or "N/A",
            "file": item.file,
            "line": item.line,
            "message": f"{item.title} -- {item.description}".strip(" -"),
            "root_cause": item.root_cause,
            "recommendation": item.recommendation,
        }
        for item in result.findings
    ]
    return findings, True


def _assign_ids(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stamps a sequential SEC-AI-DEEPSCAN:{n} id onto every finding, in order -- called once,
    over the full flattened list from every batch, so IDs are globally sequential regardless of
    which batch a finding came from (matches this scan's pre-refactor behavior exactly)."""
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"SEC-AI-DEEPSCAN:{index}"
    return findings


async def _run_batches_concurrently(
    provider, batches: list[list[tuple[str, str]]]
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Runs every batch's LLM call concurrently (bounded by DEEP_SCAN_MAX_CONCURRENT_BATCHES),
    yielding real-time events as each batch genuinely starts and finishes -- shared by both
    run_ai_model_deep_scan (consumes silently, just accumulating) and
    run_ai_model_deep_scan_stream (turns each event into an NDJSON line), so the concurrency and
    cancellation-cleanup logic exists in exactly one place.

    Yields, in real time as work actually happens (never held until every batch is done):
        {"type": "batch_started",  "batch_index": i, "total": N, "files": [rel, rel, ...]}
        {"type": "batch_finished", "batch_index": i, "total": N, "completed_count": c,
         "findings": [...], "ok": bool}

    Real, necessary cancellation handling: if this generator is closed before every batch
    finishes (a human clicking "Stop Scan" mid-scan, which relies on Starlette cancelling the
    consuming route's async generator on client disconnect -- see CLAUDE.md item 44), every batch
    task already scheduled via asyncio.create_task is explicitly cancelled in the `finally` block.
    Without this, a scheduled task keeps running to completion in the background even after the
    stream itself has stopped -- the old sequential loop never had to handle this, since only one
    `_scan_one_batch` call was ever in flight at a time and stopping the generator mid-await
    already interrupted it directly.
    """
    total = len(batches)
    semaphore = asyncio.Semaphore(DEEP_SCAN_MAX_CONCURRENT_BATCHES)
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def _worker(index: int, batch: list[tuple[str, str]]) -> None:
        async with semaphore:
            await queue.put({
                "type": "batch_started",
                "batch_index": index,
                "total": total,
                "files": [rel for rel, _ in batch],
            })
            findings, ok = await _scan_one_batch(provider, batch)
            await queue.put({
                "type": "batch_finished",
                "batch_index": index,
                "total": total,
                "findings": findings,
                "ok": ok,
            })

    tasks = [
        asyncio.create_task(_worker(index, batch))
        for index, batch in enumerate(batches, start=1)
    ]

    try:
        completed_count = 0
        finished = 0
        while finished < total:
            event = await queue.get()
            if event["type"] == "batch_finished":
                completed_count += 1
                finished += 1
                event = {**event, "completed_count": completed_count}
            yield event
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        # Deliberate cleanup, not a real failure -- swallow the resulting CancelledErrors rather
        # than letting them surface as unhandled task exceptions.
        await asyncio.gather(*tasks, return_exceptions=True)


async def run_ai_model_deep_scan(repo_path: Path) -> tuple[str, list[dict[str, Any]]]:
    """
    Returns (status message, list of SecurityFinding-shaped dicts). Never raises -- an unreachable
    provider or a malformed/unparseable response for any one batch degrades that batch to zero
    findings, so the deterministic findings this layer is combined with are always unaffected.
    """
    batches = _batch_files(repo_path)
    if not batches:
        return "No scannable source files found for the AI model to review.", []

    try:
        provider = _get_provider()
    except Exception as error:  # noqa: BLE001 -- an unreachable provider must not fail the whole scan
        logger.warning("Security Agent AI-model deep scan: no provider available, skipping: %s", error)
        return (
            f"Skipped -- LLM provider unreachable in this run ({type(error).__name__}). "
            f"The deterministic layers in this report are unaffected and are its evidence.",
            [],
        )

    all_findings: list[dict[str, Any]] = []
    batches_ok = 0
    batches_failed = 0

    async for event in _run_batches_concurrently(provider, batches):
        if event["type"] != "batch_finished":
            continue
        all_findings.extend(event["findings"])
        if event["ok"]:
            batches_ok += 1
        else:
            batches_failed += 1

    findings = _assign_ids(all_findings)
    status = (
        f"AI model deep scan ran over {len(batches)} batch(es) of real source code "
        f"({batches_ok} succeeded, {batches_failed} failed): {len(findings)} finding(s)."
    )
    return status, findings


async def run_ai_model_deep_scan_stream(repo_path: Path) -> AsyncGenerator[dict[str, Any], None]:
    """
    Streaming sibling of run_ai_model_deep_scan -- same batching/provider-resolution/concurrency,
    real per-batch progress instead of a single blocking return. Never yields a "done" event
    itself (the caller, SecurityAgent.run_ai_model_scan_stream, still has deterministic-layer and
    report-saving work around this) -- its last event is always "deep_scan_result", carrying the
    same (status, findings) shape run_ai_model_deep_scan returns as a tuple.

    Events:
        {"type": "phase", "phase": "ai_scan", "label": "..."}
        {"type": "batch_started", "batch_index": i, "total": N, "files": [rel, rel, ...]}
        {"type": "batch_finished", "batch_index": i, "total": N, "completed_count": c,
         "label": "..."}
        {"type": "deep_scan_result", "status": "...", "findings": [...]}

    "batch_started"/"batch_finished" replace the old single "progress" event -- deliberately, not
    cosmetically: the old event's "current" field conflated "how many batches have completed" with
    "which specific batch just finished," which only worked because completion order == submission
    order in the previous strictly-sequential loop. Under real concurrency that equivalence no
    longer holds (batches can and do finish out of order), so "which batch" (batch_index) and "how
    many are done so far" (completed_count) are now reported as two separate, explicit fields.
    """
    batches = _batch_files(repo_path)
    if not batches:
        yield {
            "type": "deep_scan_result",
            "status": "No scannable source files found for the AI model to review.",
            "findings": [],
        }
        return

    try:
        provider = _get_provider()
    except Exception as error:  # noqa: BLE001
        logger.warning("Security Agent AI-model deep scan: no provider available, skipping: %s", error)
        yield {
            "type": "deep_scan_result",
            "status": (
                f"Skipped -- LLM provider unreachable in this run ({type(error).__name__}). "
                f"The deterministic layers in this report are unaffected and are its evidence."
            ),
            "findings": [],
        }
        return

    total = len(batches)
    yield {
        "type": "phase", "phase": "ai_scan",
        "label": f"Starting AI model scan across {total} batch(es) of real source code "
        f"(up to {DEEP_SCAN_MAX_CONCURRENT_BATCHES} at a time)...",
    }

    all_findings: list[dict[str, Any]] = []
    batches_ok = 0
    batches_failed = 0

    async for event in _run_batches_concurrently(provider, batches):
        if event["type"] == "batch_started":
            yield event
            continue

        all_findings.extend(event["findings"])
        if event["ok"]:
            batches_ok += 1
        else:
            batches_failed += 1
        yield {
            "type": "batch_finished",
            "batch_index": event["batch_index"],
            "total": total,
            "completed_count": event["completed_count"],
            "label": f"Scanned batch {event['batch_index']} of {total}...",
        }

    findings = _assign_ids(all_findings)
    status = (
        f"AI model deep scan ran over {total} batch(es) of real source code "
        f"({batches_ok} succeeded, {batches_failed} failed): {len(findings)} finding(s)."
    )
    yield {"type": "deep_scan_result", "status": status, "findings": findings}
