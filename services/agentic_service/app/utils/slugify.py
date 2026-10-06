"""
Slug utility.

A slug is a clean folder-safe name.

Example:
    "E-commerce Platform" -> "e-commerce-platform"
    "Login Feature" -> "login-feature"

We use slugs when creating artifact folders.
"""

import re


def slugify(value: str) -> str:
    """
    Convert text into a safe folder/file name.
    """
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "untitled"