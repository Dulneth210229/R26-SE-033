"""
Unit tests for the Coder Agent's style_checker module (best-effort static
"does this page/component use Tailwind classes" check), for the Next.js
App Router convention (app/, components/). No LLM, no git, no Docker --
these operate on a plain tmp_path directory tree, since
check_component_styling only ever takes a workspace_root Path.
"""

from app.agents.coder_agent.style_checker import check_component_styling


def _write(root, relative_path, content):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_no_component_dirs_returns_empty(tmp_path):
    assert check_component_styling(tmp_path) == []


def test_file_with_class_name_is_styled(tmp_path):
    _write(
        tmp_path,
        "app/tasks/[taskId]/page.tsx",
        'export default function TaskDetailPage() { return <div className="p-4">Hi</div>; }',
    )
    results = check_component_styling(tmp_path)

    assert results == [{"path": "app/tasks/[taskId]/page.tsx", "status": "styled"}]


def test_file_with_only_inline_style_is_flagged(tmp_path):
    # Reproduces the real, confirmed bug (pre-migration): a home page used
    # only raw inline styles, zero className usage, and was missed by a real
    # agentic exploration run relying on manual list_dir/read_file alone.
    _write(
        tmp_path,
        "app/page.tsx",
        'export default function HomePage() { '
        'return <div style={{ padding: "2rem" }}>Home</div>; }',
    )
    results = check_component_styling(tmp_path)

    assert results == [{"path": "app/page.tsx", "status": "inline_styles"}]


def test_file_with_neither_is_unstyled(tmp_path):
    _write(
        tmp_path,
        "components/Bare.tsx",
        "export default function Bare() { return <div>Hi</div>; }",
    )
    results = check_component_styling(tmp_path)

    assert results == [{"path": "components/Bare.tsx", "status": "unstyled"}]


def test_scans_both_app_and_components_dirs(tmp_path):
    _write(tmp_path, "app/a/page.tsx", "<div className='x'>A</div>")
    _write(tmp_path, "components/B.tsx", "<div>B</div>")

    results = check_component_styling(tmp_path)
    paths = {item["path"] for item in results}

    assert paths == {"app/a/page.tsx", "components/B.tsx"}


def test_non_tsx_files_are_ignored(tmp_path):
    _write(tmp_path, "app/a/page.tsx", "<div>A</div>")
    _write(tmp_path, "app/a/page.test.ts", "not a component")

    results = check_component_styling(tmp_path)

    assert len(results) == 1
    assert results[0]["path"] == "app/a/page.tsx"


def test_next_build_output_nested_under_a_component_dir_is_excluded(tmp_path):
    _write(tmp_path, "app/a/page.tsx", "<div>A</div>")
    _write(tmp_path, "components/.next/types/some-generated.tsx", "<div className='x'>Generated</div>")

    results = check_component_styling(tmp_path)

    assert len(results) == 1
    assert results[0]["path"] == "app/a/page.tsx"
