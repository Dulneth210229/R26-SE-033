"""
Unit tests for the Coder Agent's nav_checker module (best-effort static
page-reachability check), for the Next.js App Router convention. No LLM, no
git, no Docker -- these operate on a plain tmp_path directory tree, since
check_page_reachability only ever takes a workspace_root Path.
"""

from app.agents.coder_agent.nav_checker import check_page_reachability


def _write(root, relative_path, content):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_no_app_dir_returns_empty(tmp_path):
    assert check_page_reachability(tmp_path) == []


def test_only_home_page_returns_empty(tmp_path):
    _write(tmp_path, "app/page.tsx", "export default function HomePage() { return <div />; }")
    assert check_page_reachability(tmp_path) == []


def test_layout_loading_error_and_route_files_never_count_as_pages(tmp_path):
    _write(tmp_path, "app/page.tsx", "export default function HomePage() { return <div />; }")
    _write(tmp_path, "app/layout.tsx", "export default function RootLayout() { return null; }")
    _write(tmp_path, "app/loading.tsx", "export default function Loading() { return null; }")
    _write(tmp_path, "app/error.tsx", "export default function Error() { return null; }")
    _write(tmp_path, "app/not-found.tsx", "export default function NotFound() { return null; }")
    _write(tmp_path, "app/api/health/route.ts", "export async function GET() { return Response.json({}); }")

    assert check_page_reachability(tmp_path) == []


def test_reproduces_the_real_bug_page_with_no_link_is_unreachable(tmp_path):
    # Exactly the real, confirmed shape: a feature added a page but nothing
    # links to it -- the bug this checker exists to catch.
    _write(tmp_path, "app/page.tsx", "export default function HomePage() { return <div />; }")
    _write(tmp_path, "app/login/page.tsx", "export default function LoginPage() { return <div />; }")

    results = check_page_reachability(tmp_path)
    assert results == [{"route": "/login", "status": "unreachable"}]


def test_direct_link_makes_route_reachable(tmp_path):
    _write(
        tmp_path,
        "app/page.tsx",
        'import Link from "next/link";\n'
        "export default function HomePage() {\n"
        '  return <Link href="/login">Login</Link>;\n'
        "}\n",
    )
    _write(tmp_path, "app/login/page.tsx", "export default function LoginPage() { return <div />; }")

    results = check_page_reachability(tmp_path)
    assert results == [{"route": "/login", "status": "reachable"}]


def test_link_in_a_different_file_still_counts(tmp_path):
    _write(tmp_path, "app/page.tsx", "export default function HomePage() { return <div />; }")
    _write(tmp_path, "app/login/page.tsx", "export default function LoginPage() { return <div />; }")
    _write(
        tmp_path,
        "components/Nav.tsx",
        'import Link from "next/link";\n'
        'export default function Nav() { return <Link href="/login">Login</Link>; }\n',
    )

    results = check_page_reachability(tmp_path)
    assert results == [{"route": "/login", "status": "reachable"}]


def test_anchor_href_also_counts(tmp_path):
    _write(tmp_path, "app/page.tsx", '<a href="/login">Login</a>')
    _write(tmp_path, "app/login/page.tsx", "export default function LoginPage() { return <div />; }")

    results = check_page_reachability(tmp_path)
    assert results == [{"route": "/login", "status": "reachable"}]


def test_parameterized_route_unreachable_without_a_linked_list_page(tmp_path):
    _write(tmp_path, "app/page.tsx", "export default function HomePage() { return <div />; }")
    _write(
        tmp_path,
        "app/tasks/[taskId]/page.tsx",
        "export default function TaskDetailPage() { return <div />; }",
    )

    results = check_page_reachability(tmp_path)
    assert results == [{"route": "/tasks/[taskId]", "status": "unreachable"}]


def test_parameterized_route_reachable_via_linked_list_page(tmp_path):
    _write(tmp_path, "app/page.tsx", '<Link href="/tasks">Tasks</Link>')
    _write(tmp_path, "app/tasks/page.tsx", "export default function TaskListPage() { return <div />; }")
    _write(
        tmp_path,
        "app/tasks/[taskId]/page.tsx",
        "export default function TaskDetailPage() { return <div />; }",
    )

    results = {item["route"]: item["status"] for item in check_page_reachability(tmp_path)}
    assert results["/tasks"] == "reachable"
    assert results["/tasks/[taskId]"] == "reachable"


def test_parameterized_route_unreachable_if_list_page_itself_unlinked(tmp_path):
    _write(tmp_path, "app/page.tsx", "export default function HomePage() { return <div />; }")
    _write(tmp_path, "app/tasks/page.tsx", "export default function TaskListPage() { return <div />; }")
    _write(
        tmp_path,
        "app/tasks/[taskId]/page.tsx",
        "export default function TaskDetailPage() { return <div />; }",
    )

    results = {item["route"]: item["status"] for item in check_page_reachability(tmp_path)}
    assert results["/tasks"] == "unreachable"
    assert results["/tasks/[taskId]"] == "unreachable"


def test_template_literal_link_with_interpolation_resolves_to_static_prefix(tmp_path):
    _write(tmp_path, "app/page.tsx", '<Link href="/tasks">Tasks</Link>')
    _write(tmp_path, "app/tasks/page.tsx", "export default function TaskListPage() { return <div />; }")
    _write(
        tmp_path,
        "app/tasks/[taskId]/page.tsx",
        "export default function TaskDetailPage() { return <div />; }",
    )
    _write(
        tmp_path,
        "components/TaskList.tsx",
        "tasks.map(task => <Link href={`/tasks/${task._id}`}>{task.title}</Link>)",
    )

    results = {item["route"]: item["status"] for item in check_page_reachability(tmp_path)}
    assert results["/tasks"] == "reachable"
    assert results["/tasks/[taskId]"] == "reachable"


def test_api_routes_are_never_mistaken_for_pages(tmp_path):
    _write(tmp_path, "app/page.tsx", "export default function HomePage() { return <div />; }")
    _write(tmp_path, "app/api/tasks/route.ts", "export async function GET() { return Response.json([]); }")

    assert check_page_reachability(tmp_path) == []
