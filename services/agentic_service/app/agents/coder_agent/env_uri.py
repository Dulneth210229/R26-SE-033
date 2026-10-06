"""
MongoDB URI detection in a human's chat message.

Purpose:
A human can switch a generated app from serving seed data (see
db_fallback_checker.py / prompt.py's "Database availability fallback" rule)
to a real database by pasting a MongoDB connection string into the Coder
Agent chat -- there is no other realistic mechanism, since sandbox/preview
containers never see host env vars and Docker has no way to inject one into
an already-running container (confirmed directly: neither
sandbox_service.run_command nor start_background_service passes
`environment=`). The only real path is writing the URI into `.env.local`
(workspace_service.write_env_local) and restarting whatever container next
starts. This module is the deterministic, regex-based first step: pull the
URI (if any) out of the human's free-text comment before it ever reaches an
LLM prompt -- there is no reason to show a credential to a planner once it's
handled here.
"""

from __future__ import annotations

import re

MONGODB_URI_PATTERN = re.compile(r"mongodb(?:\+srv)?://\S+", re.IGNORECASE)
_TRAILING_PUNCTUATION = ")]}>.,;:!?'\"`"

# revised_by values the frontend already stamps on a machine-built revision_comment (e.g. the
# "Fix Vulnerabilities" flow quoting a Security/QA finding's own root-cause/recommendation text
# verbatim -- see SecurityDecisionDialog.jsx, ResultTab.jsx's handleConfirmedFixVulnerabilities,
# QaReportView.jsx's handleSendToCoder, all of which already set this correctly). A finding that
# describes a hardcoded-credential vulnerability routinely quotes the offending source line,
# which can itself contain a real mongodb:// URI-shaped substring -- confirmed to have happened
# for real: a fake, LLM-invented FALLBACK_MONGODB_URI credential quoted in a CWE-798 finding's
# root_cause text was matched here and silently overwrote a human's real, correctly-provided
# .env.local value. A comment carrying one of these sentinels is NOT a human typing their real
# database URI -- it's evidence the planner needs to see in full, not a credential to extract.
MACHINE_GENERATED_REVISION_SOURCES = {"security_agent_report", "qa_agent_report"}


def is_machine_generated_revision(revised_by: str | None) -> bool:
    return (revised_by or "").strip() in MACHINE_GENERATED_REVISION_SOURCES


def extract_mongodb_uri(text: str | None) -> str | None:
    """First `mongodb(+srv)://` URI substring in `text`, with trailing sentence
    punctuation stripped, or None if no match."""
    if not text:
        return None

    match = MONGODB_URI_PATTERN.search(text)
    if not match:
        return None

    return match.group(0).rstrip(_TRAILING_PUNCTUATION) or None


def strip_uri_from_comment(text: str, uri: str) -> str | None:
    """`text` with the first occurrence of `uri` removed and surrounding
    whitespace/punctuation trimmed. Returns None if nothing meaningful
    remains -- i.e. the message WAS the URI -- which callers use as the
    "URI-only" signal."""
    remainder = text.replace(uri, "", 1).strip(" \t\n\r.,;:!?-")
    return remainder or None


def is_uri_only(text: str, uri: str) -> bool:
    return strip_uri_from_comment(text, uri) is None


_URI_CREDENTIALS_PATTERN = re.compile(r"^(mongodb(?:\+srv)?://)([^@/]+)@")


def mask_mongodb_uri(uri: str) -> str:
    """
    Redact a MongoDB URI's username/password (if present) for display -- the read side of the
    database-connection feature must never echo a raw credential back over the API, mirroring
    this module's own stated philosophy above ("there is no reason to show a credential to a
    planner once it's handled here") applied to a human reviewer instead. A URI with no
    credentials (e.g. a bare local `mongodb://localhost:27017/mydb`) is returned unchanged --
    there's nothing to redact.
    """
    return _URI_CREDENTIALS_PATTERN.sub(r"\1***:***@", uri)
