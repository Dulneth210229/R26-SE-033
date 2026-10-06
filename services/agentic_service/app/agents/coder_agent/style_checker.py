"""
Coder Agent component-styling checker.

Purpose:
Best-effort, regex-based signal for the agentic revision planner
(planner.py's generate_via_exploration): which existing page/component .tsx
files under app/ and components/ appear to have ZERO Tailwind utility-class
usage (no `className=` at all), or use raw inline `style={{...}}` instead --
the concrete, checkable signal behind a vague human revision request like
"styles are missing, add tailwind css."

Confirmed necessary directly, not speculatively: a real end-to-end
exploration run correctly discovered Tailwind was already fully configured
project-wide (tailwind.config.js, postcss.config.js, index.css's @tailwind
directives all already present), but still concluded the fix was to modify
index.css -- missing the one actual unstyled page (TaskflowHomePage.jsx,
using raw inline styles throughout, zero className usage). Finding files
that do NOT match a pattern is a much harder "inverse search" for a model to
carry out reliably via manual list_dir/read_file/search_code calls than
finding files that DO match one -- this tool answers it directly instead.

Like nav_checker.py/route_checker.py, this is explicitly a heuristic, not a
real JSX/AST analysis or a judgment of visual quality: a file with a single
className is reported "styled" even if the rest of its markup is bare. It is
a starting-point signal for the planner to investigate further, not a
verdict.
"""

from __future__ import annotations

from pathlib import Path

_COMPONENT_DIRS = ("app", "components")
_EXCLUDED_DIRS = {"node_modules", ".git", ".next"}


def check_component_styling(workspace_root: Path) -> list[dict[str, str]]:
    """
    Returns [{"path": "...", "status": "styled"|"inline_styles"|"unstyled"}]
    for every .tsx file under app/ and components/.

    "styled": contains at least one `className=`.
    "inline_styles": no `className=`, but uses `style={{` or `style={` --
        i.e. actively styled, just not with Tailwind.
    "unstyled": neither -- no styling signal found at all.
    """
    results: list[dict[str, str]] = []

    for rel_dir in _COMPONENT_DIRS:
        directory = workspace_root / rel_dir
        if not directory.is_dir():
            continue

        for file_path in sorted(directory.rglob("*.tsx")):
            if any(part in _EXCLUDED_DIRS for part in file_path.parts):
                continue
            try:
                text = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue

            relative_path = file_path.relative_to(workspace_root).as_posix()

            if "className=" in text:
                status = "styled"
            elif "style={{" in text or "style={" in text:
                status = "inline_styles"
            else:
                status = "unstyled"

            results.append({"path": relative_path, "status": status})

    return results
