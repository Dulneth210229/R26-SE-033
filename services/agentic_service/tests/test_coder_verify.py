"""
Unit tests for CoderVerifier -- exercised against a real throwaway git repo
(built via the real workspace_service scaffold, so the repo root is a real
Next.js App Router + TypeScript project) and the real sandbox_service
(Docker), no LLM involved.

Confirms: a single root npm install runs (one package.json now, not a
server/client split) regardless of code_plan_json, the `next build` and
server-boot smoke tests are hard failures/passes (not skippable), the
next.config.mjs anti-cheat check passes on the untouched scaffold, and `test`
remains skip-if-absent since no such tooling is scaffolded.
"""

import os
import shutil
import stat

import pytest

from app.agents.coder_agent.verify import CoderVerifier
from app.services.in_memory_store import store
from app.services.workspace_service import workspace_service
from app.utils.id_generator import generate_id


def _remove_readonly(func, path, _exc_info):
    """
    shutil.rmtree onerror handler: git marks its object files read-only on
    Windows, which makes plain rmtree fail with PermissionError. Clear the
    read-only bit and retry once.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)


@pytest.fixture
def project():
    """
    Yields (project_id, feature_id) with a real feature branch already
    checked out -- verify() now also computes touched files via
    workspace_service.get_touched_files, which requires a real feature
    branch to exist (mirrors CoderAgent.run()'s actual call order: plan ->
    start_feature_branch -> code -> verify).
    """
    project_id = generate_id("project")
    feature_id = generate_id("feature")
    store.projects[project_id] = {"project_id": project_id, "project_name": f"Verify Test {project_id}"}
    store.features[feature_id] = {
        "project_id": project_id,
        "feature_id": feature_id,
        "feature_name": "Verify Test Feature",
    }
    workspace_service.start_feature_branch(project_id, feature_id)

    yield project_id, feature_id

    repo_path = workspace_service.get_repo_path(project_id)
    workspace_service.ensure_project_repo(project_id).close()  # release Windows file handles
    store.database["projects"].delete_one({"project_id": project_id})
    store.database["features"].delete_one({"feature_id": feature_id})
    shutil.rmtree(repo_path.parent, onerror=_remove_readonly)


@pytest.fixture
def verifier():
    return CoderVerifier()


def test_verify_runs_a_single_root_npm_install(verifier, project):
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["npm install"] == "passed"


def test_verify_next_build_succeeds(verifier, project):
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["next build"] == "passed"


def test_verify_server_boots_and_responds_to_health_check(verifier, project):
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["server boot (next start + /api/health)"] == "passed"


def test_verify_passes_end_to_end_on_untouched_scaffold(verifier, project):
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    assert result["passed"] is True


def test_next_config_integrity_passes_on_untouched_scaffold(verifier, project):
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["next.config.mjs integrity"] == "passed"


def test_next_config_integrity_fails_on_build_error_suppression(verifier, project):
    project_id, feature_id = project
    next_config_path = workspace_service.get_repo_path(project_id) / "next.config.mjs"
    next_config_path.write_text(
        "/** @type {import('next').NextConfig} */\n"
        "const nextConfig = {\n"
        "  typescript: { ignoreBuildErrors: true },\n"
        "};\n\n"
        "export default nextConfig;\n",
        encoding="utf-8",
    )

    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["next.config.mjs integrity"] == "failed"
    assert result["passed"] is False


def test_missing_root_test_script_is_skipped_not_failed(verifier, project):
    # The scaffold's root package.json has no test script configured.
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})

    statuses = {s["name"]: s["status"] for s in result["steps"]}
    assert statuses["npm run test (root)"] == "skipped"


def test_broken_server_boot_is_a_hard_failure(verifier, project):
    # Keeps `export const dynamic = "force-dynamic"` (dropping it was a real,
    # confirmed mistake in an earlier version of this fixture): a Route
    # Handler with no dynamic marker is eligible for Next.js's static
    # route optimization, which can invoke it AT BUILD TIME to cache its
    # response -- so a broken handler without this line fails `next build`
    # itself, not just the real running server, defeating this test's own
    # purpose (proving a *runtime* boot failure is a hard gate).
    project_id, feature_id = project
    health_route_path = workspace_service.get_repo_path(project_id) / "app" / "api" / "health" / "route.ts"
    health_route_path.write_text(
        'export const dynamic = "force-dynamic";\n\n'
        "export async function GET() {\n"
        "  throw new Error('intentionally broken for this test');\n"
        "}\n",
        encoding="utf-8",
    )

    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["next build"] == "passed"
    assert statuses["server boot (next start + /api/health)"] == "failed"
    assert result["passed"] is False


def test_endpoint_route_coverage_passes_with_no_endpoint_plan(verifier, project):
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["endpoint route coverage"] == "passed"


def test_endpoint_route_coverage_fails_on_missing_route(verifier, project):
    project_id, feature_id = project
    code_plan_json = {
        "files": [
            {
                "path": "app/api/widgets/route.ts",
                "action": "create",
                "maps_to": ["/api/widgets"],
            }
        ]
    }

    result = verifier.verify(project_id, feature_id, code_plan_json)
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["endpoint route coverage"] == "failed"
    assert result["passed"] is False


def test_placeholder_stub_scan_is_informational_and_never_fails(verifier, project):
    project_id, feature_id = project
    stub_path = workspace_service.get_repo_path(project_id) / "app" / "api" / "stub" / "route.ts"
    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_path.write_text(
        "// In a real app, you would send an email here\n"
        "export async function GET() { return Response.json({}); }\n",
        encoding="utf-8",
    )

    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["placeholder-stub scan"] == "info"
    assert result["passed"] is True


def test_page_reachability_passes_on_untouched_scaffold(verifier, project):
    # The fresh scaffold only has the home page -- nothing else to check.
    project_id, feature_id = project
    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["page reachability"] == "passed"
    assert statuses["home page render"] == "passed"
    assert statuses["feature page render"] == "info"


def test_page_reachability_fails_on_a_page_with_no_link(verifier, project):
    # Reproduces the real, confirmed bug: a feature added a page under app/
    # but never a <Link> to it.
    project_id, feature_id = project
    login_page_path = workspace_service.get_repo_path(project_id) / "app" / "login" / "page.tsx"
    login_page_path.parent.mkdir(parents=True, exist_ok=True)
    login_page_path.write_text(
        "export default function LoginPage() { return <div>Login</div>; }\n",
        encoding="utf-8",
    )

    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["page reachability"] == "failed"
    assert result["passed"] is False


def test_page_reachability_passes_when_page_is_linked(verifier, project):
    project_id, feature_id = project
    repo_path = workspace_service.get_repo_path(project_id)

    login_page_path = repo_path / "app" / "login" / "page.tsx"
    login_page_path.parent.mkdir(parents=True, exist_ok=True)
    login_page_path.write_text(
        "export default function LoginPage() { return <div>Login</div>; }\n",
        encoding="utf-8",
    )

    home_page_path = repo_path / "app" / "page.tsx"
    home_page_path.write_text(
        'import Link from "next/link";\n\n'
        "export default function HomePage() {\n"
        "  return (\n"
        "    <div>\n"
        '      <Link href="/login">Login</Link>\n'
        "    </div>\n"
        "  );\n"
        "}\n",
        encoding="utf-8",
    )

    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["page reachability"] == "passed"
    assert statuses["home page render"] == "passed"
    # The reachable "/login" page is checked too, and reported informationally.
    assert statuses["feature page render"] == "info"


def test_home_page_render_fails_on_a_real_runtime_crash(verifier, project):
    # Reachable and compiles cleanly (the `as any` cast bypasses TypeScript's
    # type-checking, exactly like a real, careless cast a struggling model
    # might reach for), but throws only once actually executed in a real
    # browser -- exactly the class of bug nav_checker/route_checker/
    # `next build` all cannot catch, and the reason this check exists.
    # Deliberately inside a useEffect, not the component body: Next.js
    # statically prerenders a plain Server Component page AT BUILD TIME by
    # default, so a crash in the render body itself would (correctly) fail
    # `next build` too, not just this check -- confirmed directly. A crash
    # inside useEffect never runs during that server-side prerender pass
    # (effects are client-only), matching every real generated page anyway
    # (the Coder Agent's own prompt mandates "use client" on every feature
    # page), so this is the realistic shape of a runtime-only bug.
    project_id, feature_id = project
    home_page_path = workspace_service.get_repo_path(project_id) / "app" / "page.tsx"
    home_page_path.write_text(
        '"use client";\n\n'
        'import { useEffect } from "react";\n\n'
        "export default function HomePage() {\n"
        "  useEffect(() => {\n"
        "    const crash = (null as any).someProperty;\n"
        "    console.log(crash);\n"
        "  }, []);\n"
        "  return <div>Home</div>;\n"
        "}\n",
        encoding="utf-8",
    )

    result = verifier.verify(project_id, feature_id, {"new_dependencies": []})
    statuses = {s["name"]: s["status"] for s in result["steps"]}

    assert statuses["next build"] == "passed"  # compiles fine -- the bug is only at runtime
    assert statuses["home page render"] == "failed"
    assert result["passed"] is False
