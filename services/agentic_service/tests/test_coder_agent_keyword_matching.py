"""
Unit tests for the Coder Agent's plain-English revision file discovery --
Tier 1a (_find_keyword_matched_known_files, a safe fuzzy name match that can
skip exploration like the exact-match fast path) and Tier 1b
(_find_keyword_hint_files, a real-workspace keyword search that only ever
feeds exploration a hint, never trusted to skip it). See agent.py's own
docstrings for the full rationale behind the asymmetric trust between the two.

No LLM, no Docker, no git -- Tier 1a is pure metadata matching; Tier 1b
touches a real tmp_path directory tree (no sandbox needed, it's a plain
filesystem walk).
"""

import pytest

from app.agents.coder_agent.agent import CoderAgent, _meaningful_stems, _split_into_words
from app.agents.coder_agent.prompt import (
    _build_keyword_hint_files_section,
    build_agentic_revision_planner_user_prompt,
)

KNOWN_FILES = [
    {"path": "app/login/LoginForm.tsx", "action": "modify"},
    {"path": "app/notes/NotesList.tsx", "action": "create"},
    {"path": "components/Footer.tsx", "action": "create"},
    # Two components sharing a stem, deliberately, to test the ambiguous-tie case.
    {"path": "components/UserCard.tsx", "action": "create"},
    {"path": "components/UserBadge.tsx", "action": "create"},
    # A stale, deleted entry, deliberately named so it WOULD match a >=2-stem comment if
    # the delete-skip guard didn't work -- must never be matchable.
    {"path": "app/legacy/UserSettingsPanel.tsx", "action": "delete"},
]


@pytest.fixture
def agent():
    return CoderAgent()


# ---------------------------------------------------------------------------
# _split_into_words / _meaningful_stems
# ---------------------------------------------------------------------------


def test_split_into_words_handles_camel_case():
    assert _split_into_words("CommentList") == ["comment", "list"]


def test_split_into_words_handles_plain_prose():
    assert _split_into_words("the login form") == ["the", "login", "form"]


def test_split_into_words_expands_contractions_cleanly():
    words = _split_into_words("the button doesn't work")
    assert "not" in words
    assert "doesn" not in words
    assert "t" not in words


def test_meaningful_stems_drops_stopwords_and_short_words():
    stems = _meaningful_stems("the login form doesn't clear after submit")
    assert "login" in stems
    assert "form" in stems
    assert "the" not in stems  # stopword
    assert "not" not in stems  # stopword (from the expanded contraction)


def test_meaningful_stems_drops_domain_generic_words():
    stems = _meaningful_stems("update the page component")
    assert stems == set()


# ---------------------------------------------------------------------------
# Tier 1a: _find_keyword_matched_known_files
# ---------------------------------------------------------------------------


def test_tier1a_matches_a_component_named_in_plain_english(agent):
    matched = agent._find_keyword_matched_known_files(
        "the login form doesn't clear after submit", KNOWN_FILES
    )
    assert matched == {"app/login/LoginForm.tsx"}


def test_tier1a_matches_camel_case_name_typed_without_extension(agent):
    matched = agent._find_keyword_matched_known_files(
        "add a loading spinner to NotesList", KNOWN_FILES
    )
    assert matched == {"app/notes/NotesList.tsx"}


def test_tier1a_ambiguous_tie_returns_nothing(agent):
    # Both UserCard.tsx and UserBadge.tsx share the "user" stem, but neither shares
    # a SECOND stem with "user" alone -- so this actually resolves to zero matches
    # (each only has 1 shared stem), not a tie. Use a comment that ties on 2 stems
    # each to construct a real ambiguous case.
    known_files_with_tie = KNOWN_FILES + [
        {"path": "components/UserProfileCard.tsx", "action": "create"},
        {"path": "components/UserProfileBadge.tsx", "action": "create"},
    ]
    matched = agent._find_keyword_matched_known_files(
        "fix the user profile display", known_files_with_tie
    )
    assert matched == set()


def test_tier1a_requires_at_least_two_shared_stems(agent):
    # "user" alone is one stem -- a single generic shared word is not enough signal.
    matched = agent._find_keyword_matched_known_files("fix the user issue", KNOWN_FILES)
    assert matched == set()


def test_tier1a_never_matches_a_deleted_file(agent):
    # "UserSettingsPanel.tsx" (deleted) shares 2 real stems ("user", "setting") with this
    # comment -- would match if the delete-skip guard weren't applied.
    matched = agent._find_keyword_matched_known_files(
        "fix the user settings panel display", KNOWN_FILES
    )
    assert matched == set()


def test_tier1a_no_comment_never_matches(agent):
    assert agent._find_keyword_matched_known_files(None, KNOWN_FILES) == set()


def test_tier1a_no_known_files_never_matches(agent):
    assert agent._find_keyword_matched_known_files("the login form", []) == set()


def test_tier1a_real_reported_vague_comment_has_no_exact_named_component(agent):
    # This project's own history: a real, previously-reported vague comment with
    # no component name at all -- must correctly stay unmatched (falls through to
    # Tier 1b / full exploration), not guess.
    matched = agent._find_keyword_matched_known_files(
        "Styles are missing in the generated code so add styles using tailwind css",
        KNOWN_FILES,
    )
    assert matched == set()


# ---------------------------------------------------------------------------
# Tier 1b: _find_keyword_hint_files
# ---------------------------------------------------------------------------


@pytest.fixture
def real_workspace(tmp_path):
    login_dir = tmp_path / "app" / "login"
    login_dir.mkdir(parents=True)
    (login_dir / "LoginForm.tsx").write_text(
        '"use client";\nexport default function LoginForm() {\n  return <form>login form</form>;\n}\n',
        encoding="utf-8",
    )

    notes_dir = tmp_path / "app" / "notes"
    notes_dir.mkdir(parents=True)
    (notes_dir / "NotesList.tsx").write_text(
        "export default function NotesList() {\n  return <ul>notes</ul>;\n}\n", encoding="utf-8"
    )

    (tmp_path / "app" / "page.tsx").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "app" / "page.tsx").write_text(
        "export default function HomePage() {\n  return <div>home</div>;\n}\n", encoding="utf-8"
    )

    return tmp_path


def test_tier1b_finds_real_content_matches(agent, real_workspace):
    hints = agent._find_keyword_hint_files("the login form doesn't clear after submit", real_workspace)
    assert "app/login/LoginForm.tsx" in [h.replace("\\", "/") for h in hints]


def test_tier1b_empty_on_too_few_stems(agent, real_workspace):
    assert agent._find_keyword_hint_files("fix it", real_workspace) == []


def test_tier1b_empty_on_no_comment(agent, real_workspace):
    assert agent._find_keyword_hint_files(None, real_workspace) == []


def test_tier1b_capped_at_max_hints(agent, tmp_path):
    for i in range(20):
        file_path = tmp_path / f"widget_{i}.tsx"
        file_path.write_text("export function Widget() { return <div>widget content</div>; }\n", encoding="utf-8")

    hints = agent._find_keyword_hint_files("fix the widget content", tmp_path, max_hints=5)
    assert len(hints) <= 5


# ---------------------------------------------------------------------------
# prompt.py: rendering Tier 1b's hint list into the exploration prompt
# ---------------------------------------------------------------------------


def test_keyword_hint_section_is_empty_for_no_hints():
    assert _build_keyword_hint_files_section([]) == []


def test_keyword_hint_section_lists_paths_and_frames_them_as_unverified():
    section = _build_keyword_hint_files_section(["app/login/LoginForm.tsx", "components/Footer.tsx"])
    rendered = "\n".join(section)
    assert "app/login/LoginForm.tsx" in rendered
    assert "components/Footer.tsx" in rendered
    assert "NOT a guarantee" in rendered


def test_keyword_hint_files_appear_in_the_full_agentic_revision_prompt():
    prompt = build_agentic_revision_planner_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Task Comments"},
        srs_json={"functional_requirements": []},
        architecture_plan_json={"design_views": {}},
        ui_integration_manifest_json=None,
        project_manifest_json={},
        human_comment="the login form doesn't clear after submit",
        previous_plan_json=None,
        validation_feedback=None,
        coverage_baseline_files=[],
        keyword_hint_files=["app/login/LoginForm.tsx"],
    )
    assert "app/login/LoginForm.tsx" in prompt


def test_no_keyword_hint_files_omits_the_section_from_the_prompt():
    prompt = build_agentic_revision_planner_user_prompt(
        project={"project_name": "TaskFlow"},
        feature={"feature_name": "Task Comments"},
        srs_json={"functional_requirements": []},
        architecture_plan_json={"design_views": {}},
        ui_integration_manifest_json=None,
        project_manifest_json={},
        human_comment="the login form doesn't clear after submit",
        previous_plan_json=None,
        validation_feedback=None,
        coverage_baseline_files=[],
        keyword_hint_files=None,
    )
    assert "keyword search" not in prompt.lower()
