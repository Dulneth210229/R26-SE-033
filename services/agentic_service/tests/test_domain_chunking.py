"""
Unit tests for the Domain Agent RAG chunking step.

Pure Python, no embedding/LLM calls.
"""

from app.core.config import settings
from app.services.rag.chunking import chunk_text


def test_chunk_ids_are_deterministic_and_source_tagged():
    chunks = chunk_text("Hello world. " * 5, source_document="doc.txt")

    assert chunks[0]["chunk_id"] == "doc.txt#0"
    assert all(chunk["source_document"] == "doc.txt" for chunk in chunks)


def test_long_text_is_split_into_multiple_chunks_within_size_limit():
    long_text = "word " * 2000  # much longer than DOMAIN_CHUNK_SIZE

    chunks = chunk_text(long_text, source_document="long.txt")

    assert len(chunks) > 1
    assert all(len(chunk["text"]) <= settings.DOMAIN_CHUNK_SIZE for chunk in chunks)
    assert [chunk["chunk_id"] for chunk in chunks] == [f"long.txt#{i}" for i in range(len(chunks))]


def test_empty_text_produces_no_chunks():
    assert chunk_text("", source_document="empty.txt") == []


def test_whitespace_only_text_produces_no_chunks():
    assert chunk_text("   \n\n   ", source_document="ws.txt") == []


def test_short_text_produces_a_single_chunk():
    chunks = chunk_text("A short domain note.", source_document="short.txt")

    assert len(chunks) == 1
    assert chunks[0]["text"] == "A short domain note."
