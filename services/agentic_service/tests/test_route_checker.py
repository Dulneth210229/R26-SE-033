"""
Unit tests for the Coder Agent's route_checker module (best-effort static
route-coverage + placeholder-stub scanning), for the Next.js App Router
convention. No LLM, no Docker, no git -- these operate on a plain tmp_path
directory tree, since check_route_coverage/scan_for_placeholder_stubs only
ever take a workspace_root Path.
"""

from app.agents.coder_agent.route_checker import check_route_coverage, scan_for_placeholder_stubs


def _write(root, relative_path, content):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_check_route_coverage_finds_collection_route_handler(tmp_path):
    _write(
        tmp_path,
        "app/api/tasks/route.ts",
        "export async function GET() { return Response.json([]); }\n",
    )

    code_plan_json = {
        "files": [
            {"path": "app/api/tasks/route.ts", "action": "create", "maps_to": ["/api/tasks"]},
        ]
    }

    results = check_route_coverage(tmp_path, code_plan_json)

    assert results == [{"endpoint": "/api/tasks", "file": "app/api/tasks/route.ts", "status": "found"}]


def test_check_route_coverage_translates_param_segment_to_bracket_folder(tmp_path):
    _write(
        tmp_path,
        "app/api/tasks/[id]/route.ts",
        "export async function GET(request, { params }) { return Response.json({}); }\n",
    )

    code_plan_json = {
        "files": [
            {"path": "app/api/tasks/[id]/route.ts", "action": "create", "maps_to": ["/api/tasks/:id"]},
        ]
    }

    results = check_route_coverage(tmp_path, code_plan_json)

    assert results == [
        {"endpoint": "/api/tasks/:id", "file": "app/api/tasks/[id]/route.ts", "status": "found"}
    ]


def test_check_route_coverage_flags_missing_route_file(tmp_path):
    code_plan_json = {
        "files": [
            {"path": "app/api/widgets/route.ts", "action": "create", "maps_to": ["/api/widgets"]},
        ]
    }

    results = check_route_coverage(tmp_path, code_plan_json)

    assert results == [{"endpoint": "/api/widgets", "file": "app/api/widgets/route.ts", "status": "missing"}]


def test_check_route_coverage_flags_route_file_with_no_handler_export(tmp_path):
    _write(tmp_path, "app/api/widgets/route.ts", "// TODO: implement\n")

    code_plan_json = {
        "files": [
            {"path": "app/api/widgets/route.ts", "action": "create", "maps_to": ["/api/widgets"]},
        ]
    }

    results = check_route_coverage(tmp_path, code_plan_json)

    assert results == [{"endpoint": "/api/widgets", "file": "app/api/widgets/route.ts", "status": "missing"}]


def test_check_route_coverage_accepts_all_three_legal_export_forms(tmp_path):
    _write(tmp_path, "app/api/a/route.ts", "export async function GET() { return Response.json({}); }\n")
    _write(tmp_path, "app/api/b/route.ts", "export function POST() { return Response.json({}); }\n")
    _write(
        tmp_path,
        "app/api/c/route.ts",
        "export const DELETE = async (request) => { return Response.json({}); };\n",
    )

    code_plan_json = {
        "files": [
            {"path": "app/api/a/route.ts", "action": "create", "maps_to": ["/api/a"]},
            {"path": "app/api/b/route.ts", "action": "create", "maps_to": ["/api/b"]},
            {"path": "app/api/c/route.ts", "action": "create", "maps_to": ["/api/c"]},
        ]
    }

    results = check_route_coverage(tmp_path, code_plan_json)

    assert all(item["status"] == "found" for item in results)


def test_check_route_coverage_ignores_deleted_files(tmp_path):
    code_plan_json = {
        "files": [
            {"path": "app/api/old/route.ts", "action": "delete", "maps_to": ["/api/old"]},
        ]
    }

    assert check_route_coverage(tmp_path, code_plan_json) == []


def test_check_route_coverage_ignores_files_with_no_endpoint_maps_to(tmp_path):
    _write(tmp_path, "models/Task.ts", "export {};")

    code_plan_json = {
        "files": [
            {"path": "models/Task.ts", "action": "create", "maps_to": ["Task"]},
        ]
    }

    assert check_route_coverage(tmp_path, code_plan_json) == []


def test_check_route_coverage_dedupes_the_same_endpoint_across_plan_entries(tmp_path):
    _write(
        tmp_path,
        "app/api/tasks/route.ts",
        "export async function GET() { return Response.json([]); }\n"
        "export async function POST() { return Response.json({}); }\n",
    )

    code_plan_json = {
        "files": [
            {"path": "app/api/tasks/route.ts", "action": "create", "maps_to": ["/api/tasks"]},
            {"path": "lib/api/tasksService.ts", "action": "create", "maps_to": ["/api/tasks"]},
        ]
    }

    results = check_route_coverage(tmp_path, code_plan_json)

    assert len(results) == 1
    assert results[0]["status"] == "found"


def test_scan_for_placeholder_stubs_finds_known_phrases(tmp_path):
    _write(
        tmp_path,
        "app/api/auth/route.ts",
        "// In a real app, you would generate a reset token and send an email\n"
        "export async function POST() { return Response.json({ message: 'ok' }); }\n",
    )

    findings = scan_for_placeholder_stubs(tmp_path, ["app/api/auth/route.ts"])

    assert len(findings) == 1
    assert findings[0]["file"] == "app/api/auth/route.ts"
    assert findings[0]["line"] == 1
    assert "In a real app" in findings[0]["snippet"]


def test_scan_for_placeholder_stubs_clean_file_reports_nothing(tmp_path):
    _write(
        tmp_path,
        "app/api/auth/route.ts",
        "export async function POST() { return Response.json({ token: 'x' }); }\n",
    )

    assert scan_for_placeholder_stubs(tmp_path, ["app/api/auth/route.ts"]) == []


def test_scan_for_placeholder_stubs_ignores_untouched_or_missing_files(tmp_path):
    assert scan_for_placeholder_stubs(tmp_path, ["app/api/does_not_exist/route.ts"]) == []
