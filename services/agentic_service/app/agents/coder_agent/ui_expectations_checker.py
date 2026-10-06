"""
Coder Agent SRS ui_expectations coverage scan.

Purpose: a best-effort, deterministic signal that each bullet in the approved SRS's
ui_expectations list has SOME plausible textual/structural trace somewhere in the frontend files
this attempt actually touched -- e.g. an "Add Item" button expectation should show up as
recognizable text/identifiers in a page/component file, not just be silently absent from the
generated app entirely. Confirmed real motivation: this project's own history has repeatedly
found generated apps quietly missing whole UI expectations (a nav bar, a search filter) with no
mechanism surfacing the gap to a human reviewer until they noticed by eye.

Deliberately informational-only (never gates verification_passed), mirroring
functional_checker.py's own stated reasoning: a word-overlap heuristic will correctly miss a
genuinely-implemented expectation phrased in different words (e.g. "Live search input with
debouncing" implemented as a component named `SearchBar` with a `useDebounce` hook shares no
literal words at all), and a confident-but-wrong heuristic strong enough to gate on would be a
real regression risk for something this approximate. Its value is a cheap nudge for a human
reviewer, not a correctness proof -- reuses the exact same word-overlap/stopword-filter idiom
already proven for verify.py's own "request relevance scan" step, applied to SRS ui_expectations
instead of a human's revision comment.
"""

from __future__ import annotations

import re
from pathlib import Path

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "also",
    "have", "has", "was", "were", "are", "you", "your", "please", "make",
    "makes", "should", "would", "could", "add", "adds", "added", "remove",
    "removes", "removed", "change", "changes", "changed", "update",
    "updates", "updated", "fix", "fixes", "fixed", "code", "page", "app",
    "application", "feature", "does", "not", "did", "will", "some",
    "these", "those", "them", "they", "which", "when", "then", "than",
    "each", "item", "items", "shows", "show", "shown", "display",
    "displays", "displayed", "user", "users", "allow", "allows",
}

_FRONTEND_TOUCHED_PATTERN = re.compile(r"\.(tsx|jsx)$")


def _meaningful_words(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zA-Z]{4,}", text.lower())
        if token not in _STOPWORDS
    }


def scan_ui_expectations_coverage(
    workspace_root: Path, touched_paths: list[str], ui_expectations: list[str]
) -> list[dict[str, str]]:
    """
    For each ui_expectations bullet, extracts its distinctive words and checks whether any of
    them appear anywhere in this attempt's own touched frontend (.tsx/.jsx) files. Returns one
    entry per bullet with near-zero overlap -- an empty list means every bullet had at least some
    plausible trace (or there was nothing to check). Never raises; a missing/unreadable file is
    silently skipped, matching functional_checker.py's own tolerance for a best-effort scan.
    """
    if not ui_expectations:
        return []

    frontend_paths = [p for p in touched_paths if _FRONTEND_TOUCHED_PATTERN.search(p)]
    content_parts: list[str] = []
    for relative_path in frontend_paths:
        file_path = workspace_root / relative_path
        if not file_path.is_file():
            continue
        try:
            content_parts.append(file_path.read_text(encoding="utf-8", errors="ignore").lower())
        except OSError:
            continue
    combined_content = "\n".join(content_parts)

    gaps: list[dict[str, str]] = []
    for expectation in ui_expectations:
        if not isinstance(expectation, str) or not expectation.strip():
            continue
        words = _meaningful_words(expectation)
        if len(words) < 2:
            # Too short/generic a bullet to say anything meaningful about -- skip rather than
            # risk a noisy false positive on a near-empty word set.
            continue
        matched = {word for word in words if word in combined_content}
        if not matched:
            gaps.append({"expectation": expectation, "matched_words": ""})

    return gaps
