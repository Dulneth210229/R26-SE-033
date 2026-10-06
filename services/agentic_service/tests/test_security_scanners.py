"""
Tests for the Security Agent's `scan_secrets` file-selection logic -- specifically the
`.env*.local` exclusion (direct user decision after this session's live run found a real false
positive: the secret scanner flagged the user's own real, working MongoDB credential in
`.env.local`, which every generated project's own `.gitignore` already excludes from version
control -- the "risk of exposing credentials if committed" the scanner's own finding message
describes cannot actually happen for this specific file family in this app's architecture).

Real filesystem (pytest's tmp_path), no mocks -- scan_secrets reads real files.
"""

from app.agents.security_agent.scanners import scan_secrets

REAL_MONGO_LINE = 'MONGODB_URI=mongodb://someuser:somepassword@cluster0.mongodb.net/mydb\n'


def test_env_local_is_excluded_from_secret_scanning(tmp_path):
    (tmp_path / ".env.local").write_text(REAL_MONGO_LINE, encoding="utf-8")

    findings = scan_secrets(tmp_path)

    assert findings == []


def test_env_production_local_is_also_excluded(tmp_path):
    (tmp_path / ".env.production.local").write_text(REAL_MONGO_LINE, encoding="utf-8")

    findings = scan_secrets(tmp_path)

    assert findings == []


def test_plain_env_file_is_still_scanned(tmp_path):
    (tmp_path / ".env").write_text(REAL_MONGO_LINE, encoding="utf-8")

    findings = scan_secrets(tmp_path)

    assert len(findings) == 1
    assert findings[0]["rule_id"] == "SEC-SECRET-MONGO-URI"
    assert findings[0]["file"] == ".env"


def test_a_real_source_file_is_still_scanned(tmp_path):
    (tmp_path / "route.ts").write_text(f'const uri = "{REAL_MONGO_LINE.split("=", 1)[1].strip()}";\n', encoding="utf-8")

    findings = scan_secrets(tmp_path)

    assert len(findings) == 1
    assert findings[0]["file"] == "route.ts"


def test_no_secrets_anywhere_returns_empty(tmp_path):
    (tmp_path / ".env.local").write_text("MONGODB_URI=\n", encoding="utf-8")
    (tmp_path / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")

    assert scan_secrets(tmp_path) == []
