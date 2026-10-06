"""
Domain knowledge document loaders.

Purpose:
Convert one on-disk document (PDF, DOCX, TXT, or MD) into plain text so it
can be chunked and embedded by the rest of the RAG pipeline.

Why this exists:
- Domain Agent must retrieve real domain knowledge from files the user
  provides (PDF, DOC, TXT), not from the LLM's own pretraining.
- Keeping format-specific parsing here means chunking.py and
  domain_knowledge_service.py never need to know about file formats.
"""

import tempfile
from pathlib import Path

from pypdf import PdfReader
from docx import Document

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def load_text_from_file(path: Path) -> str:
    """
    Load plain text content from a single domain knowledge file.

    Raises ValueError for an unsupported extension -- the caller
    (domain_knowledge_service.ingest_path) is expected to catch this per
    file and skip it, never aborting the whole ingestion run.
    """

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _load_pdf(path)

    if suffix == ".docx":
        return _load_docx(path)

    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8")

    raise ValueError(f"Unsupported domain knowledge file type: {suffix}")


def load_text_from_bytes(file_bytes: bytes, filename: str) -> str:
    """
    Same extraction as load_text_from_file, but for bytes that were never written to a permanent
    location -- e.g. a document attached directly to a Requirement Agent chat message, scraped
    once for its text and then discarded, rather than a Domain Agent knowledge upload that's
    stored and re-queried later. pypdf/python-docx both require a real file path, so this writes
    to a throwaway temp file and always cleans it up (success or failure) via `finally`.
    """

    suffix = Path(filename).suffix.lower()

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
        handle.write(file_bytes)
        temp_path = Path(handle.name)

    try:
        return load_text_from_file(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _load_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(pages)


def _load_docx(path: Path) -> str:
    document = Document(str(path))
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    return "\n".join(paragraphs)
