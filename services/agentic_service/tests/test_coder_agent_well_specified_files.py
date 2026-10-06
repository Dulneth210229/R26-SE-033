"""
Unit tests for CoderAgent._find_well_specified_target_files -- the heuristic
that decides whether a revision comment already names a real file this
feature has previously touched, letting _plan_with_retries skip the slow
agentic exploration planner on attempt 1 (see agent.py's docstring for the
full rationale). Pure function, no LLM/Docker/git.
"""

import pytest

from app.agents.coder_agent.agent import CoderAgent

KNOWN_FILES = [
    {"path": "client/src/components/CommentList.jsx"},
    {"path": "client/src/components/Footer.tsx"},
    {"path": "server/src/routes/task-comments.routes.js"},
    # Two different "page.tsx" files under different feature directories --
    # a bare "page.tsx" reference must be treated as ambiguous.
    {"path": "app/item-notes/page.tsx"},
    {"path": "app/task-search/page.tsx"},
]


@pytest.fixture
def agent():
    return CoderAgent()


def test_exact_full_path_match_is_trusted(agent):
    matched = agent._find_well_specified_target_files(
        "Fix the typo in client/src/components/Footer.tsx", KNOWN_FILES
    )
    assert matched == {"client/src/components/Footer.tsx"}


def test_unique_basename_match_is_trusted(agent):
    matched = agent._find_well_specified_target_files(
        "Add a loading spinner to CommentList.jsx", KNOWN_FILES
    )
    assert matched == {"client/src/components/CommentList.jsx"}


def test_ambiguous_basename_falls_through_to_no_match(agent):
    # "page.tsx" exists under two different feature directories -- must not
    # guess either one.
    matched = agent._find_well_specified_target_files(
        "The styling on page.tsx looks off", KNOWN_FILES
    )
    assert matched == set()


def test_qualified_but_not_exact_path_is_not_guessed_further(agent):
    # Contains "/" but doesn't match any real known path exactly -- must not
    # fall back to a basename guess for a qualified token.
    matched = agent._find_well_specified_target_files(
        "Fix client/src/components/Footer.jsx", KNOWN_FILES
    )
    assert matched == set()


def test_bare_word_with_no_extension_never_matches(agent):
    matched = agent._find_well_specified_target_files(
        "The footer looks broken on mobile", KNOWN_FILES
    )
    assert matched == set()


def test_no_known_files_never_matches(agent):
    matched = agent._find_well_specified_target_files(
        "Fix client/src/components/Footer.tsx", []
    )
    assert matched == set()


def test_no_comment_never_matches(agent):
    matched = agent._find_well_specified_target_files(None, KNOWN_FILES)
    assert matched == set()


def test_multiple_real_files_named_are_all_matched(agent):
    matched = agent._find_well_specified_target_files(
        "Update both CommentList.jsx and server/src/routes/task-comments.routes.js",
        KNOWN_FILES,
    )
    assert matched == {
        "client/src/components/CommentList.jsx",
        "server/src/routes/task-comments.routes.js",
    }


def test_real_reported_vague_tailwind_comment_stays_on_exploration(agent):
    # The actual comment from this project's own history (item 22) --
    # deliberately vague, names no file at all.
    matched = agent._find_well_specified_target_files(
        "Styles are missing in the generated code so add styles using tailwind css",
        KNOWN_FILES,
    )
    assert matched == set()


def test_real_reported_vague_edit_delete_comment_stays_on_exploration(agent):
    matched = agent._find_well_specified_target_files(
        "Item notes can be edit and delete as well. Once the user type some item and clicks on "
        "the add note button the input bar must be clear once the item added",
        KNOWN_FILES,
    )
    assert matched == set()
