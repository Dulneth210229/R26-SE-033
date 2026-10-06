"""
Unit tests for revision_file_tokens.py -- relocated out of agent.py so
security_finding_coverage_checker.py (imported by verify.py) can share the exact same
extraction/resolution logic without a circular import.
"""

from app.agents.coder_agent.revision_file_tokens import (
    extract_file_tokens,
    resolve_tokens_against_known_paths,
)


def test_extract_file_tokens_captures_forward_slash_paths_in_full():
    tokens = extract_file_tokens("Fix a bug in app/api/auth/login/route.ts:35 please")
    assert tokens == {"app/api/auth/login/route.ts"}


def test_extract_file_tokens_captures_only_the_basename_for_backslash_paths():
    # Real, confirmed behavior: the regex's character class has no backslash, so a Windows-style
    # token like "lib\\mongodb.ts" only ever yields the bare basename "mongodb.ts" -- the
    # directory portion is silently dropped by the regex itself, not by any later logic.
    tokens = extract_file_tokens(r"[CRITICAL] lib\mongodb.ts:6 -- hardcoded credential")
    assert tokens == {"mongodb.ts"}


def test_extract_file_tokens_ignores_bare_words_with_no_extension():
    assert extract_file_tokens("fix the footer component please") == set()


def test_extract_file_tokens_empty_or_none_input():
    assert extract_file_tokens(None) == set()
    assert extract_file_tokens("") == set()


def test_resolve_exact_forward_slash_match():
    known = {"app/api/auth/login/route.ts", "app/page.tsx"}
    assert resolve_tokens_against_known_paths({"app/api/auth/login/route.ts"}, known) == {
        "app/api/auth/login/route.ts"
    }


def test_resolve_qualified_but_not_exact_path_is_never_guessed():
    known = {"app/api/auth/login/route.ts"}
    assert resolve_tokens_against_known_paths({"app/api/auth/signup/route.ts"}, known) == set()


def test_resolve_unique_basename_fallback():
    known = {"lib/mongodb.ts", "app/page.tsx"}
    assert resolve_tokens_against_known_paths({"mongodb.ts"}, known) == {"lib/mongodb.ts"}


def test_resolve_ambiguous_basename_is_never_guessed():
    known = {"app/api/items/route.ts", "app/api/users/route.ts"}
    assert resolve_tokens_against_known_paths({"route.ts"}, known) == set()


def test_resolve_no_matches_returns_empty():
    known = {"app/page.tsx"}
    assert resolve_tokens_against_known_paths({"missing.ts"}, known) == set()


def test_resolve_empty_tokens_or_known_paths():
    assert resolve_tokens_against_known_paths(set(), {"app/page.tsx"}) == set()
    assert resolve_tokens_against_known_paths({"app/page.tsx"}, set()) == set()
