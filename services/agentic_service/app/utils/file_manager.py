"""
File manager utility.

This file contains reusable file operations.

Why this exists:
- Agents will generate many artifacts.
- We should not repeat file writing logic in every agent.
- This keeps artifact saving clean and consistent.
"""

import json
from pathlib import Path
from typing import Any


def ensure_directory(path: str | Path) -> Path:
    """
    Create a directory if it does not already exist.
    """
    directory = Path(path)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def write_text_file(file_path: str | Path, content: str) -> str:
    """
    Write plain text or markdown content into a file.
    """
    path = Path(file_path)
    ensure_directory(path.parent)

    path.write_text(content, encoding="utf-8")
    return str(path)


def write_json_file(file_path: str | Path, data: dict[str, Any]) -> str:
    """
    Write JSON content into a file with readable indentation.
    """
    path = Path(file_path)
    ensure_directory(path.parent)

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    return str(path)


def read_text_file(file_path: str | Path) -> str:
    """
    Read text content from a file.
    """
    return Path(file_path).read_text(encoding="utf-8")


def read_json_file(file_path: str | Path) -> dict[str, Any]:
    """
    Read JSON content from a file.
    """
    return json.loads(Path(file_path).read_text(encoding="utf-8"))