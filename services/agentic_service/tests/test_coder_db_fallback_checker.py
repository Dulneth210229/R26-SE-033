"""
Unit tests for db_fallback_checker.py -- pure, tmp_path-only, no LLM/Docker/git,
mirrors test_route_checker.py's established idiom.
"""

from app.agents.coder_agent.db_fallback_checker import (
    check_db_null_guard_coverage,
    scan_for_db_fallback_quality,
)

GUARDED_ROUTE = """\
import { NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";
import { seedItems } from "@/lib/seedData";

export const dynamic = "force-dynamic";

export async function GET() {
  const db = await connectToDatabase();
  if (!db) {
    return NextResponse.json(seedItems);
  }
  const items = await db.models.Item.find();
  return NextResponse.json(items);
}
"""

UNGUARDED_ROUTE = """\
import { NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export const dynamic = "force-dynamic";

export async function GET() {
  const db = await connectToDatabase();
  const items = await db.models.Item.find();
  return NextResponse.json(items);
}
"""

NO_DB_ROUTE = """\
import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json({ status: "ok" });
}
"""

BARE_EMPTY_FALLBACK_ROUTE = """\
import { NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export async function GET() {
  const conn = await connectToDatabase();
  if (!conn) {
    return NextResponse.json([]);
  }
  const items = await conn.models.Item.find();
  return NextResponse.json(items);
}
"""

CODE_PLAN = {
    "files": [
        {"path": "app/api/items/route.ts", "action": "create", "rationale": "r", "maps_to": []},
    ]
}


def test_check_db_null_guard_coverage_passes_when_guard_present(tmp_path):
    route_path = tmp_path / "app" / "api" / "items" / "route.ts"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(GUARDED_ROUTE, encoding="utf-8")

    results = check_db_null_guard_coverage(tmp_path, CODE_PLAN)
    assert results == []


def test_check_db_null_guard_coverage_flags_missing_guard(tmp_path):
    route_path = tmp_path / "app" / "api" / "items" / "route.ts"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(UNGUARDED_ROUTE, encoding="utf-8")

    results = check_db_null_guard_coverage(tmp_path, CODE_PLAN)
    assert results == [{"file": "app/api/items/route.ts", "status": "missing"}]


def test_check_db_null_guard_coverage_ignores_routes_with_no_db_call(tmp_path):
    route_path = tmp_path / "app" / "api" / "items" / "route.ts"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(NO_DB_ROUTE, encoding="utf-8")

    results = check_db_null_guard_coverage(tmp_path, CODE_PLAN)
    assert results == []


def test_check_db_null_guard_coverage_ignores_deleted_files(tmp_path):
    plan = {
        "files": [
            {"path": "app/api/items/route.ts", "action": "delete", "rationale": "r", "maps_to": []},
        ]
    }
    results = check_db_null_guard_coverage(tmp_path, plan)
    assert results == []


def test_check_db_null_guard_coverage_ignores_non_route_files(tmp_path):
    plan = {
        "files": [
            {"path": "lib/seedData.ts", "action": "modify", "rationale": "r", "maps_to": []},
        ]
    }
    results = check_db_null_guard_coverage(tmp_path, plan)
    assert results == []


def test_scan_for_db_fallback_quality_flags_bare_empty_array(tmp_path):
    route_path = tmp_path / "app" / "api" / "items" / "route.ts"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(BARE_EMPTY_FALLBACK_ROUTE, encoding="utf-8")

    findings = scan_for_db_fallback_quality(tmp_path, ["app/api/items/route.ts"])
    assert len(findings) == 1
    assert findings[0]["file"] == "app/api/items/route.ts"


def test_scan_for_db_fallback_quality_no_findings_for_real_seed_data(tmp_path):
    route_path = tmp_path / "app" / "api" / "items" / "route.ts"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(GUARDED_ROUTE, encoding="utf-8")

    findings = scan_for_db_fallback_quality(tmp_path, ["app/api/items/route.ts"])
    assert findings == []


def test_scan_for_db_fallback_quality_skips_files_with_no_guard_at_all(tmp_path):
    # Not this scanner's job -- check_db_null_guard_coverage (a hard gate) already covers
    # "no guard at all"; this is informational-only for the "guard exists but looks weak" case.
    route_path = tmp_path / "app" / "api" / "items" / "route.ts"
    route_path.parent.mkdir(parents=True)
    route_path.write_text(UNGUARDED_ROUTE, encoding="utf-8")

    findings = scan_for_db_fallback_quality(tmp_path, ["app/api/items/route.ts"])
    assert findings == []
