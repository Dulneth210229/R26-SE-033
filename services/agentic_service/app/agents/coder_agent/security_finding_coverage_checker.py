"""
Deterministic, informational-only backstop for a security-driven revision: does every file
named in the Security Agent's revision comment actually show up among the files this attempt
touched? Direct user report -- confirmed via real, live data that in the one instance
investigated the Coder Agent DID correctly touch every file it was asked to (the "still showing
vulnerabilities" symptom was actually the AI-deep-scan layer's own run-to-run sampling variance,
not a fixing failure) -- but nothing deterministically GUARANTEES that going forward, since the
planner is still an LLM call that could, in principle, drop a named file from its own plan.
Mirrors verify.py's existing _build_relevance_scan_step/_build_ui_expectations_coverage_step
pattern exactly: never a hard gate, since a human reviewer -- or the model itself, on
inspection -- may legitimately determine a named file doesn't actually need changes.

Format-triggered, not gated on revised_by (mirrors coder_agent/prompt.py's own security-rule
addition): a revision_comment is only treated as security-driven if it actually contains
`[TIER] file:line -- ...`-shaped lines built by buildSecurityRevisionComment.js. A comment with
no such lines produces no step at all (this checker is silent for a normal, non-security
revision).
"""

from app.agents.coder_agent.revision_file_tokens import (
    extract_file_tokens,
    resolve_tokens_against_known_paths,
)

_SEVERITY_TIER_MARKERS = ("[CRITICAL]", "[MODERATE]", "[WARNING]")


def check_security_finding_file_coverage(
    revision_comment: str | None, touched_paths: list[str]
) -> dict[str, str] | None:
    """
    Returns an info-only verify() step dict, or None if `revision_comment` doesn't look like a
    Security Agent-built revision comment at all (nothing to check).
    """
    if not revision_comment or not any(marker in revision_comment for marker in _SEVERITY_TIER_MARKERS):
        return None

    named_tokens = extract_file_tokens(revision_comment)
    if not named_tokens:
        return {
            "name": "security finding file coverage",
            "status": "info",
            "output": "This looks like a security-driven revision, but no file names could be "
            "extracted from the report text.",
        }

    known_paths = set(touched_paths or [])
    resolved = resolve_tokens_against_known_paths(named_tokens, known_paths)

    # A token resolves to a real touched path exactly when the file it names was genuinely
    # touched this attempt -- resolve_tokens_against_known_paths already handles the
    # backslash-basename/forward-slash-exact matching real revision comments actually contain.
    covered_tokens = set()
    for token in named_tokens:
        token_lower = token.lower()
        if any(
            path.lower() == token_lower or path.rsplit("/", 1)[-1].lower() == token_lower
            for path in resolved
        ):
            covered_tokens.add(token)

    missing_tokens = sorted(named_tokens - covered_tokens)

    if not missing_tokens:
        return {
            "name": "security finding file coverage",
            "status": "info",
            "output": f"All {len(named_tokens)} file(s) named in the security report were touched "
            "by this attempt.",
        }

    return {
        "name": "security finding file coverage",
        "status": "info",
        "output": "The security report named file(s) this attempt never touched -- double-check "
        "these findings were actually addressed (or determine they didn't need code changes): "
        + ", ".join(missing_tokens),
    }
