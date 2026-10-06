"""
QA Agent workspace discovery.

Scope, stated plainly (see agent.py's own module docstring for the full reasoning): this targets
business logic that's testable without a DOM -- `lib/`/`models/` modules (unit tests) and
`app/api/**/route.ts` Route Handlers together with the model/lib files they actually import
(integration tests). React components/pages (`.tsx` under `app/`/`components/`) are discovered
too, but only to be reported as an honest, named out-of-scope gap -- this codebase's own
established convention (see security_agent's own honest-scope-limit precedent) rather than
silently claiming coverage a DOM-less test runner can't actually provide.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

UNIT_TEST_DIR_NAMES = {"lib", "models"}
EXCLUDED_DIR_NAMES = {"node_modules", ".next", ".git", "dist", "build", "__pycache__", "generated_tests"}
EXPORT_PATTERN = re.compile(
    r"export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class)\s+([A-Za-z0-9_]+)"
)
# Every generated Mongoose model file uses `export default mongoose.models.X || mongoose.model(
# "X", schema)` (a guard this codebase's own Coder Agent prompt mandates -- see coder_agent/
# prompt.py) -- an `export default <expression>` shape EXPORT_PATTERN above deliberately doesn't
# match (it only matches a declaration keyword right after `default`). Without this, every real
# Mongoose model file in a generated project would be silently invisible to unit-test discovery.
MONGOOSE_MODEL_EXPORT_PATTERN = re.compile(
    r'export\s+default\s+mongoose\.models\.([A-Za-z0-9_]+)\s*\|\|\s*mongoose\.model\('
)
# Matches `import { X, Y } from "@/models/Item"` / `import X from "@/lib/mongodb"` -- the only
# import shape generated code actually uses for local models/lib modules (confirmed: every
# generated Route Handler imports its model/lib dependencies through the "@/" path alias, never a
# relative "../" path, for files at this depth).
LOCAL_IMPORT_PATTERN = re.compile(
    r'import\s+(?:\{[^}]*\}|[A-Za-z0-9_]+)\s+from\s+["\'](@/(?:models|lib)/[A-Za-z0-9_/-]+)["\']'
)


def _walk_files(repo_path: Path):
    import os

    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIR_NAMES]
        for filename in filenames:
            yield Path(dirpath) / filename


def _strip_comments(text: str) -> str:
    # Same reasoning as the pre-existing implementation: a comment that merely mentions an export
    # name in prose (e.g. a docstring describing a naming convention) must not be mistaken for a
    # real export.
    return re.sub(r"//.*", "", text)


def discover_unit_test_targets(repo_path: Path) -> list[dict[str, Any]]:
    """One entry per lib/models .ts file with at least one real export: {file, rel, source,
    exports}. `source` is the real file content -- unlike the earlier regex-shape-only discovery,
    the LLM generation pass needs the real code to write meaningful tests against, not just a
    list of detected export names."""
    targets: list[dict[str, Any]] = []
    for dir_name in UNIT_TEST_DIR_NAMES:
        base = repo_path / dir_name
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.ts")):
            if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            code_only = _strip_comments(text)
            exports = EXPORT_PATTERN.findall(code_only) + MONGOOSE_MODEL_EXPORT_PATTERN.findall(code_only)
            if not exports:
                continue
            targets.append({
                "file": path,
                "rel": str(path.relative_to(repo_path)).replace("\\", "/"),
                "source": text,
                "exports": exports,
            })
    return targets


def _resolve_local_import(repo_path: Path, alias_path: str) -> Path | None:
    """"@/models/Item" -> <repo>/models/Item.ts, trying both a direct .ts file and an index.ts
    inside a directory of that name (the two real shapes a local module can take here)."""
    relative = alias_path.removeprefix("@/")
    direct = repo_path / f"{relative}.ts"
    if direct.exists():
        return direct
    index = repo_path / relative / "index.ts"
    if index.exists():
        return index
    return None


def discover_integration_test_targets(repo_path: Path) -> list[dict[str, Any]]:
    """One entry per app/api/**/route.ts with at least one local models/lib import it actually
    resolves to: {route_file, route_rel, route_source, related_files: [{rel, source}]}. A route
    with no resolvable local dependency is skipped -- nothing meaningful to integrate."""
    targets: list[dict[str, Any]] = []
    api_root = repo_path / "app" / "api"
    if not api_root.exists():
        return targets

    for path in sorted(api_root.rglob("route.ts")):
        if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        related_files: list[dict[str, str]] = []
        seen_rel: set[str] = set()
        for alias_path in LOCAL_IMPORT_PATTERN.findall(text):
            resolved = _resolve_local_import(repo_path, alias_path)
            if not resolved:
                continue
            rel = str(resolved.relative_to(repo_path)).replace("\\", "/")
            if rel in seen_rel:
                continue
            seen_rel.add(rel)
            related_files.append({
                "rel": rel,
                "source": resolved.read_text(encoding="utf-8", errors="ignore"),
            })

        if not related_files:
            continue

        targets.append({
            "route_file": path,
            "route_rel": str(path.relative_to(repo_path)).replace("\\", "/"),
            "route_source": text,
            "related_files": related_files,
        })
    return targets


def discover_out_of_scope_modules(repo_path: Path) -> list[str]:
    """Every .tsx component/page -- reported explicitly (see module docstring) rather than
    silently omitted."""
    out_of_scope = []
    for path in _walk_files(repo_path):
        if path.suffix == ".tsx":
            out_of_scope.append(str(path.relative_to(repo_path)).replace("\\", "/"))
    return sorted(out_of_scope)
