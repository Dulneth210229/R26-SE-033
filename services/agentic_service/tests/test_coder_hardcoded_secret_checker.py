"""
Unit tests for hardcoded_secret_checker.py -- pure, tmp_path-only, no LLM/Docker/git,
mirrors test_coder_db_fallback_checker.py's established idiom.
"""

from app.agents.coder_agent.hardcoded_secret_checker import scan_for_hardcoded_mongodb_uri

MONGODB_TS = """\
import mongoose from "mongoose";

const MONGODB_URI = process.env.MONGODB_URI;

export async function connectToDatabase() {
  if (!MONGODB_URI) {
    return null;
  }
  return mongoose.connect(MONGODB_URI);
}
"""

# The real, confirmed incident this checker exists to catch.
ROUTE_WITH_HARDCODED_FALLBACK = """\
import { NextResponse } from "next/server";

const FALLBACK_MONGODB_URI = "mongodb+srv://finodil_admin:Sup3rSecretPass!@cluster0.abcde.mongodb.net/finodil";

export async function GET() {
  return NextResponse.json({ ok: true });
}
"""

CLEAN_ROUTE = """\
import { NextResponse } from "next/server";
import { connectToDatabase } from "@/lib/mongodb";

export async function GET() {
  const db = await connectToDatabase();
  return NextResponse.json({ ok: !!db });
}
"""

ENV_EXAMPLE_WITH_PLACEHOLDER = """\
MONGODB_URI=mongodb://localhost:27017/mydb
"""


def _write(tmp_path, relative_path, content):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_catches_the_real_confirmed_fallback_uri_shape(tmp_path):
    _write(tmp_path, "app/api/auth/login/route.ts", ROUTE_WITH_HARDCODED_FALLBACK)
    plan = {"files": [{"path": "app/api/auth/login/route.ts", "action": "create"}]}

    findings = scan_for_hardcoded_mongodb_uri(tmp_path, plan)

    assert len(findings) == 1
    assert findings[0]["file"] == "app/api/auth/login/route.ts"
    assert "FALLBACK_MONGODB_URI" in findings[0]["snippet"]


def test_the_real_scaffold_lib_mongodb_ts_never_flags(tmp_path):
    _write(tmp_path, "lib/mongodb.ts", MONGODB_TS)
    plan = {"files": [{"path": "lib/mongodb.ts", "action": "create"}]}

    assert scan_for_hardcoded_mongodb_uri(tmp_path, plan) == []


def test_a_clean_route_using_the_real_connect_helper_does_not_flag(tmp_path):
    _write(tmp_path, "app/api/items/route.ts", CLEAN_ROUTE)
    plan = {"files": [{"path": "app/api/items/route.ts", "action": "create"}]}

    assert scan_for_hardcoded_mongodb_uri(tmp_path, plan) == []


def test_env_example_placeholder_is_excluded(tmp_path):
    # The real scaffold's .env.example legitimately contains a placeholder mongodb:// URI --
    # this is the one, deliberate exception, excluded by basename, not path substring.
    _write(tmp_path, ".env.example", ENV_EXAMPLE_WITH_PLACEHOLDER)
    _write(tmp_path, ".env.local", "MONGODB_URI=mongodb+srv://real:creds@cluster0.real.mongodb.net/db\n")
    plan = {
        "files": [
            {"path": ".env.example", "action": "create"},
            {"path": ".env.local", "action": "create"},
        ]
    }

    assert scan_for_hardcoded_mongodb_uri(tmp_path, plan) == []


def test_deleted_files_are_not_scanned(tmp_path):
    _write(tmp_path, "app/api/old/route.ts", ROUTE_WITH_HARDCODED_FALLBACK)
    plan = {"files": [{"path": "app/api/old/route.ts", "action": "delete"}]}

    assert scan_for_hardcoded_mongodb_uri(tmp_path, plan) == []


def test_unplanned_files_on_disk_are_not_scanned(tmp_path):
    # Only files the current attempt actually planned are in scope -- matches every sibling
    # checker's own "scoped to planned files only" convention.
    _write(tmp_path, "app/api/unrelated/route.ts", ROUTE_WITH_HARDCODED_FALLBACK)
    plan = {"files": [{"path": "app/api/items/route.ts", "action": "create"}]}

    assert scan_for_hardcoded_mongodb_uri(tmp_path, plan) == []
