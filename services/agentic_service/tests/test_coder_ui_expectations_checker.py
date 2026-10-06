"""
Unit tests for ui_expectations_checker.scan_ui_expectations_coverage -- pure, tmp_path-based, no
git/Docker/LLM (mirrors test_coder_functional_checker.py's/test_route_checker.py's own
established precedent for this class of cheap, deterministic heuristic check).

This is a best-effort, informational-only signal (see the module's own docstring for why) -- these
tests lock in its own matching/gap-detection logic, not any gating behavior, since it never gates.
"""

from app.agents.coder_agent.ui_expectations_checker import scan_ui_expectations_coverage


def test_no_ui_expectations_returns_no_gaps(tmp_path):
    gaps = scan_ui_expectations_coverage(tmp_path, ["app/page.tsx"], [])
    assert gaps == []


def test_expectation_with_a_real_trace_is_not_flagged(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        '<button onClick={handleOpenCreate}>Add Item</button>', encoding="utf-8"
    )

    gaps = scan_ui_expectations_coverage(
        tmp_path,
        ["app/page.tsx"],
        ['An "Add Item" button that opens a form to create a new item'],
    )
    assert gaps == []


def test_expectation_with_zero_trace_is_flagged(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        "export default function HomePage() { return <div>hello</div>; }", encoding="utf-8"
    )

    gaps = scan_ui_expectations_coverage(
        tmp_path,
        ["app/page.tsx"],
        ["Pagination controls at the bottom of the list (previous/next, jump to page)"],
    )
    assert len(gaps) == 1
    assert "Pagination controls" in gaps[0]["expectation"]


def test_only_frontend_files_are_scanned_not_backend_routes(tmp_path):
    (tmp_path / "app" / "api" / "items").mkdir(parents=True)
    (tmp_path / "app" / "api" / "items" / "route.ts").write_text(
        'export async function GET() { return NextResponse.json({ pagination: true }); }',
        encoding="utf-8",
    )

    gaps = scan_ui_expectations_coverage(
        tmp_path,
        ["app/api/items/route.ts"],
        ["Pagination controls at the bottom of the list"],
    )
    # "pagination" only appears in a .ts (backend) file, never scanned -- still flagged.
    assert len(gaps) == 1


def test_missing_touched_file_is_skipped_not_an_error(tmp_path):
    gaps = scan_ui_expectations_coverage(
        tmp_path,
        ["app/page.tsx"],  # never created
        ["A main page showing all items in a list/table/grid layout"],
    )
    assert len(gaps) == 1


def test_too_short_generic_expectation_is_never_flagged(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export default function Page() { return null; }", encoding="utf-8")

    gaps = scan_ui_expectations_coverage(tmp_path, ["app/page.tsx"], ["Show items"])
    assert gaps == []


def test_non_string_expectation_entries_are_skipped_not_raised(tmp_path):
    gaps = scan_ui_expectations_coverage(tmp_path, [], [{"not": "a string"}, None, ""])
    assert gaps == []


def test_multiple_expectations_only_flags_the_genuinely_missing_ones(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text(
        '<input placeholder="Search items..." onChange={handleSearch} />', encoding="utf-8"
    )

    gaps = scan_ui_expectations_coverage(
        tmp_path,
        ["app/page.tsx"],
        [
            "Live search input with debouncing, plus filter dropdowns for category and price range",
            'Each item has "Edit" and "Delete" actions',
        ],
    )
    # "search" matches the search bullet (present); "edit"/"delete"/"actions" never appear.
    assert len(gaps) == 1
    assert "Edit" in gaps[0]["expectation"] or "Delete" in gaps[0]["expectation"]
