"""
Security Agent scanners.

Three independent, composable scan layers, matching the design already
described in the paper before this file existed for real:

1. scan_dangerous_patterns -- deterministic static analysis over JS/TS/JSX/TSX
   source, using the TypeScript compiler's own parser (via a small Node
   helper script, ast_scan.js) to walk a real AST rather than grep -- so a
   flagged call like eval(...) is a real CallExpression node, not a
   coincidental substring match inside a comment or string literal.
2. scan_secrets -- regex-based credential/secret scanning over raw file text
   (deliberately NOT AST-based: a leaked key can appear in a .env.example,
   a YAML file, or a comment, none of which have a JS/TS AST).
3. scan_dependencies -- wraps `npm audit --json` against the generated
   project's own lockfile.

All three return a flat list of Finding dicts with the same shape, so
gate.py and report.py never need to know which layer produced a finding.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

SCANNABLE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx"}
EXCLUDED_DIR_NAMES = {"node_modules", ".next", ".git", "dist", "build", "__pycache__", ".turbo"}

# Node helper invoked once per file: parses it with the TypeScript compiler
# (which superset-parses plain JS/JSX too) and prints one JSON object per
# line for every CallExpression / JSXAttribute / AssignmentExpression /
# ElementAccessExpression node, so the Python side can pattern-match on
# real syntax nodes instead of raw text.
AST_SCAN_JS = r"""
const ts = require("typescript");
const fs = require("fs");
const path = process.argv[2];
const src = fs.readFileSync(path, "utf8");
const kind = path.endsWith(".tsx") || path.endsWith(".jsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
const sf = ts.createSourceFile(path, src, ts.ScriptTarget.Latest, true, kind);

function lineOf(node) {
  const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
  return line + 1;
}

function emit(nodeType, name, line, extra) {
  process.stdout.write(JSON.stringify({ nodeType, name, line, extra: extra || null }) + "\n");
}

function visit(node) {
  if (ts.isCallExpression(node)) {
    const callee = node.expression;
    let name = null;
    if (ts.isIdentifier(callee)) name = callee.text;
    else if (ts.isPropertyAccessExpression(callee)) name = callee.name.text;
    if (name) emit("CallExpression", name, lineOf(node));
  } else if (ts.isJsxAttribute(node)) {
    emit("JsxAttribute", node.name.getText(sf), lineOf(node));
  } else if (ts.isElementAccessExpression(node)) {
    // a[sort]-style dynamic property access -- only interesting when the
    // index expression is itself an identifier (i.e. not a[0] on an array).
    if (ts.isIdentifier(node.argumentExpression)) {
      emit("ElementAccessExpression", node.argumentExpression.text, lineOf(node));
    }
  } else if (ts.isNewExpression(node)) {
    const callee = node.expression;
    if (ts.isIdentifier(callee)) emit("NewExpression", callee.text, lineOf(node));
  } else if (ts.isPropertyAssignment(node) && ts.isIdentifier(node.name)) {
    if (/^(Access-Control-Allow-Origin)$/i.test(node.name.text) || /^(Access-Control-Allow-Origin)$/i.test(node.name.text.replace(/['"]/g, ""))) {
      emit("PropertyAssignment", node.name.text, lineOf(node), node.initializer.getText(sf));
    }
  }
  ts.forEachChild(node, visit);
}

visit(sf);
"""

# (rule_id, node_type, name_pattern, severity, cwe, message, root_cause_template, recommendation)
# root_cause_template is formatted with {file}/{line} once the real location is known, at the
# point each finding dict is constructed below.
PATTERN_RULES: list[tuple[str, str, str, str, str, str, str, str]] = [
    ("SEC-JS-001", "CallExpression", r"^eval$", "critical", "CWE-95",
     "eval() executes a string as code; any tainted input reaching it is arbitrary code execution.",
     "A direct eval() call was found at {file}:{line}, executing a runtime string as JavaScript code.",
     "Remove eval() entirely; parse or validate the input explicitly (e.g. JSON.parse for data) "
     "instead of executing it as code."),
    ("SEC-JS-002", "NewExpression", r"^Function$", "high", "CWE-95",
     "new Function(...) constructs and executes code from a string, the same risk class as eval().",
     "A `new Function(...)` constructor call was found at {file}:{line}, compiling a runtime "
     "string into an executable function.",
     "Remove the dynamic Function constructor; replace it with a fixed, statically-defined "
     "function or a safe data-only structure."),
    ("SEC-JS-003", "CallExpression", r"^(exec|execSync)$", "high", "CWE-78",
     "child_process.exec/execSync runs a string through a shell; unsanitized input is OS command injection.",
     "A child_process exec()/execSync() call was found at {file}:{line}, running a string through "
     "an OS shell.",
     "Use execFile()/execFileSync() with an explicit argument array instead of a shell string, and "
     "never interpolate user input into the command."),
    ("SEC-JS-004", "CallExpression", r"^write$", "medium", "CWE-79",
     "document.write() with dynamic content is a classic DOM-based XSS sink.",
     "A document.write() call was found at {file}:{line}, injecting content directly into the "
     "document without escaping.",
     "Avoid document.write(); use safe DOM APIs (textContent, or a templating layer that escapes "
     "by default) to insert content."),
    ("SEC-JS-005", "JsxAttribute", r"^dangerouslySetInnerHTML$", "high", "CWE-79",
     "dangerouslySetInnerHTML bypasses React's default escaping; unsanitized HTML here is stored/DOM XSS.",
     "A dangerouslySetInnerHTML attribute was found at {file}:{line}, rendering raw HTML without "
     "React's default escaping.",
     "Remove dangerouslySetInnerHTML and render the content as plain text/JSX, or sanitize the "
     "HTML through a trusted library (e.g. DOMPurify) before rendering it."),
    ("SEC-JS-006", "ElementAccessExpression", r"^(sort|order|field|key|column)$", "medium", "CWE-915",
     "Dynamic bracket property access keyed directly by a request-controlled parameter name "
     "(e.g. obj[req.query.sort]) is an object-injection / prototype-pollution-adjacent pattern; "
     "the accessor should be validated against an explicit allow-list of field names.",
     "A dynamic bracket property access (obj[{name}]) was found at {file}:{line}, using a "
     "request-controlled value as the property name.",
     "Validate the property name against an explicit allow-list of known-safe field names before "
     "using it to index the object."),
    # AST_SCAN_JS's own emit() only ever captures the CALLEE's final segment for a property-access
    # call (callee.name.text, see PropertyAccessExpression handling below) -- for `Math.random()`
    # that's "random", never "Math". A real, confirmed bug found via live testing: the rule
    # originally matched `^(Math)$`, which the emitted name for this exact call can never equal,
    # so it silently never fired. Matches on "random" instead, consistent with every OTHER
    # property-access rule in this list (SEC-JS-003/004/005 all match the method/property name,
    # never the receiver) -- not a qualified "Math.random" match, since AST_SCAN_JS doesn't emit
    # the receiver at all; accepted the same way those other rules accept matching on method name
    # alone.
    ("SEC-JS-007", "CallExpression", r"^(random)$", "low", "CWE-338",
     "Math.random() is not cryptographically secure; do not use it to generate tokens, IDs used "
     "as secrets, or password-reset codes.",
     "A Math.random() call was found at {file}:{line}, likely used to generate a token/ID/code.",
     "Use a cryptographically secure generator instead (e.g. Node's crypto.randomBytes/"
     "crypto.randomUUID) for anything used as a token, ID, or reset code."),
]


def _run_node(script_path: Path, target_file: Path, repo_path: Path) -> list[dict[str, Any]]:
    import os

    # The AST-walking helper script lives outside the scanned repo (a fixed
    # temp path), so its own `require("typescript")` would otherwise resolve
    # against *this service's* node_modules, not the target project's. Every
    # generated project already has its own "typescript" installed (it is a
    # declared devDependency of the Next.js scaffold -- see IMPL_P2), so
    # pointing NODE_PATH at the target repo's node_modules reuses that
    # install directly instead of vendoring a second copy of the TypeScript
    # compiler into this service.
    env = {**os.environ, "NODE_PATH": str(repo_path / "node_modules")}
    proc = subprocess.run(
        ["node", str(script_path), str(target_file)],
        capture_output=True, text=True, timeout=30, env=env,
    )
    events = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _walk_files(repo_path: Path):
    """
    os.walk with in-place dirname pruning, so a huge excluded directory
    (node_modules routinely has tens of thousands of files once a Next.js
    project's dependencies are installed) is never descended into at all --
    Path.rglob("*") filtered after the fact still pays the cost of walking
    every excluded subtree first, which made an early version of this
    function take minutes against a real installed node_modules.
    """
    import os

    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
        for filename in filenames:
            yield Path(dirpath) / filename


def _iter_source_files(repo_path: Path):
    for path in _walk_files(repo_path):
        if path.suffix in SCANNABLE_EXTENSIONS:
            yield path


def list_scannable_files(repo_path: Path) -> list[Path]:
    """Public wrapper around _iter_source_files -- lets deep_scan.py (the new AI-model deep-code-
    read scan layer) reuse the exact same file-discovery scope (SCANNABLE_EXTENSIONS,
    EXCLUDED_DIR_NAMES) the deterministic pattern scanner already uses, without reaching into a
    private name from another module."""
    return list(_iter_source_files(repo_path))


def scan_dangerous_patterns(repo_path: Path) -> list[dict[str, Any]]:
    """
    AST-based scan (real TypeScript-compiler parse, not text matching) for a
    curated rule set of dangerous JS/TS patterns. Returns Finding dicts.
    """
    script_path = Path("/tmp/_ast_scan.js")
    script_path.write_text(AST_SCAN_JS, encoding="utf-8")

    findings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for source_file in _iter_source_files(repo_path):
        try:
            events = _run_node(script_path, source_file, repo_path)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
        rel = str(source_file.relative_to(repo_path))
        for event in events:
            for rule_id, node_type, name_pattern, severity, cwe, message, root_cause_template, recommendation in PATTERN_RULES:
                if event["nodeType"] != node_type:
                    continue
                if event["name"] is None or not re.match(name_pattern, event["name"]):
                    continue
                key = (rule_id, rel, event["line"])
                if key in seen:
                    continue
                seen.add(key)
                findings.append({
                    "id": f"{rule_id}:{rel}:{event['line']}",
                    "rule_id": rule_id,
                    "layer": "pattern",
                    "severity": severity,
                    "cwe": cwe,
                    "file": rel,
                    "line": event["line"],
                    "message": message,
                    "root_cause": root_cause_template.format(file=rel, line=event["line"], name=event["name"]),
                    "recommendation": recommendation,
                })
    return findings


RECOMMENDATION_MOVE_TO_ENV = (
    "Move this value to `.env.local` (gitignored) and read it via `process.env.X` at runtime; "
    "rotate the exposed credential/key immediately, since it may already be compromised."
)

# (rule_id, pattern, message, recommendation) -- root_cause is templated uniformly at finding-
# construction time below (every secret rule has the identical "hardcoded literal in source"
# root cause shape, so no per-rule template is needed the way PATTERN_RULES needs one).
SECRET_RULES: list[tuple[str, str, str, str]] = [
    ("SEC-SECRET-AWS-KEY", r"AKIA[0-9A-Z]{16}", "AWS access key ID literal", RECOMMENDATION_MOVE_TO_ENV),
    ("SEC-SECRET-GENERIC-KEY", r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
     "Hardcoded API key / secret / access token literal", RECOMMENDATION_MOVE_TO_ENV),
    ("SEC-SECRET-PRIVATE-KEY", r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----", "Embedded private key block",
     "Remove the private key from source entirely; store it in a secrets manager or an untracked "
     "file outside the repo, and rotate the key since it may already be compromised."),
    ("SEC-SECRET-MONGO-URI", r"mongodb(\+srv)?://[^:\s\"']+:[^@\s\"']+@", "MongoDB connection string with an embedded, hardcoded credential",
     RECOMMENDATION_MOVE_TO_ENV),
    ("SEC-SECRET-JWT", r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "Literal JWT token embedded in source",
     "Remove the hardcoded JWT; issue tokens dynamically at runtime instead of embedding one in "
     "source, and invalidate this token if it grants any real access."),
]

SECRET_SCAN_EXTENSIONS = SCANNABLE_EXTENSIONS | {".env", ".json", ".yml", ".yaml", ".md"}

# Matches the exact glob every generated project's own .gitignore already uses for this file
# family (".env*.local" -- .env.local, .env.production.local, etc.). These are the SANCTIONED,
# gitignored place a real local secret belongs in this app's own architecture (this is precisely
# what the Database Connection feature writes MONGODB_URI into, see workspace_service.py) --
# scanning them for "hardcoded credentials" is a confirmed false positive in this specific
# codebase, not a general secret-scanning best practice being relaxed: the file can never reach
# version control in the first place, so the "risk of exposing credentials if committed" the
# scanner's own message describes cannot actually happen here. `.env`/`.env.example` are still
# scanned -- only the `*.local` family is this app's own designated real-secret store.
_LOCAL_ENV_FILE_PATTERN = re.compile(r"^\.env.*\.local$")


def scan_secrets(repo_path: Path) -> list[dict[str, Any]]:
    """
    Regex-based credential scan across all text-like files (not just JS/TS,
    since secrets leak just as often into .env.example or config files).
    """
    findings: list[dict[str, Any]] = []
    for path in _walk_files(repo_path):
        if _LOCAL_ENV_FILE_PATTERN.match(path.name):
            continue
        if path.suffix not in SECRET_SCAN_EXTENSIONS and path.name not in {".env", ".env.example"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(path.relative_to(repo_path))
        for i, line in enumerate(text.splitlines(), start=1):
            for rule_id, pattern, message, recommendation in SECRET_RULES:
                if re.search(pattern, line):
                    findings.append({
                        "id": f"{rule_id}:{rel}:{i}",
                        "rule_id": rule_id,
                        "layer": "secret",
                        "severity": "critical",
                        "cwe": "CWE-798",
                        "file": rel,
                        "line": i,
                        "message": message,
                        "root_cause": f"A hardcoded secret literal ({message.lower()}) was found directly in source at {rel}:{i}.",
                        "recommendation": recommendation,
                    })
    return findings


def scan_dependencies(
    project_id: str,
    repo_path: Path,
    run_command_fn: Callable[[str, str, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Runs `npm audit --json` against the generated project's own lockfile.

    run_command_fn defaults to sandbox_service.run_command (the Docker-based
    execution path every other agentic tool call in this codebase uses,
    documented in sandbox_service.py). It is dependency-injected here so this
    function is unit-testable, and so an operator running without Docker
    available can still execute this scan directly against the host.
    """
    if run_command_fn is None:
        from app.services.sandbox_service import sandbox_service
        run_command_fn = lambda pid, cmd, cwd, timeout: sandbox_service.run_command(
            project_id=pid, command=cmd, cwd=cwd, timeout=timeout
        )

    result = run_command_fn(project_id, "npm audit --json --offline", ".", 60)
    raw_stdout = result.get("stdout", "") or "{}"
    try:
        audit_data = json.loads(raw_stdout)
    except json.JSONDecodeError:
        audit_data = {}

    findings: list[dict[str, Any]] = []
    for pkg_name, vuln in (audit_data.get("vulnerabilities") or {}).items():
        severity = vuln.get("severity", "unknown")
        findings.append({
            "id": f"SEC-DEP:{pkg_name}",
            "rule_id": "SEC-DEP-NPM-AUDIT",
            "layer": "dependency",
            "severity": severity,
            "cwe": "CWE-1104",
            "file": "package-lock.json",
            "line": None,
            "message": f"npm audit flagged '{pkg_name}': {vuln.get('via', [''])[0] if isinstance(vuln.get('via'), list) else ''}".strip(),
            "root_cause": (
                f"npm audit reports package '{pkg_name}' has a known vulnerability in the "
                f"currently installed version (see package-lock.json)."
            ),
            "recommendation": f"Run `npm audit fix`, or upgrade '{pkg_name}' to a patched version.",
        })

    metadata = audit_data.get("metadata", {}).get("vulnerabilities", {})
    return {
        "findings": findings,
        "audit_exit_code": result.get("exit_code"),
        "audit_ran_offline": "--offline" in "npm audit --json --offline",
        "dependency_summary": metadata,
        "raw_stderr": (result.get("stderr") or "")[:2000],
    }
