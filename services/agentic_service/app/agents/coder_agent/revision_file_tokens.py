"""
Shared file-token extraction/resolution for a human-written revision comment --
originally lived inline in agent.py (used only by _find_well_specified_target_files),
relocated to its own leaf module so security_finding_coverage_checker.py (imported by
verify.py) can reuse the exact same logic without a circular import (agent.py already
imports from verify.py).
"""

import re

# Deliberately requires a real extension so a bare word (e.g. "footer") never counts as a file
# reference, only something the human actually typed as a file-shaped token (e.g.
# "components/Footer.tsx" or "Footer.tsx"). Does NOT match a backslash-separated token's
# directory portion (no "\\" in the character class) -- a Windows-style path like
# "lib\\mongodb.ts" only yields the bare basename "mongodb.ts" from this regex; callers must
# resolve that through the basename fallback below, never assume it's already a full path.
REVISION_FILE_TOKEN_RE = re.compile(r"[\w][\w\-./]*\.(?:tsx|ts|jsx|js|css|json|mjs)\b", re.IGNORECASE)


def extract_file_tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {match.group(0) for match in REVISION_FILE_TOKEN_RE.finditer(text)}


def resolve_tokens_against_known_paths(tokens: set[str], known_paths: set[str]) -> set[str]:
    """
    Resolves file-shaped tokens (from extract_file_tokens) against a set of real, known file
    paths (forward-slash-normalized, matching workspace_service/code_plan conventions).

    Deliberately conservative -- never guesses:
    - A token that already looks like a qualified path (contains "/") is only trusted on an
      EXACT match against a real path -- a qualified-but-not-exact token isn't guessed at
      further.
    - A bare filename (no "/") -- including the basename-only result of a backslash-separated
      token, since the regex above never captures the directory portion of one -- is only
      trusted if it's the ONE file among known_paths with that basename; 0 or 2+ basename
      matches leave the token unresolved rather than picking one at random.
    """
    if not tokens or not known_paths:
        return set()

    matched: set[str] = set()
    for token in tokens:
        token_lower = token.lower()

        exact = {path for path in known_paths if path.lower() == token_lower}
        if exact:
            matched |= exact
            continue

        if "/" in token:
            continue

        basename_matches = {path for path in known_paths if path.rsplit("/", 1)[-1].lower() == token_lower}
        if len(basename_matches) == 1:
            matched |= basename_matches
        # 0 or 2+ basename matches: no match, or genuinely ambiguous -- leave unresolved.

    return matched
