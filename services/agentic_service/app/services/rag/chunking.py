"""
Domain knowledge chunking.

Purpose:
Split one document's plain text into overlapping chunks small enough to
embed meaningfully, each tagged with a deterministic chunk_id and its
source document name.

Why deterministic chunk_id:
Re-running ingestion on the same file must upsert the same vector IDs
instead of duplicating them in the vector store.
"""

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings


def chunk_text(
    text: str,
    source_document: str,
    document_id: str | None = None,
    project_id: str | None = None,
) -> list[dict]:
    """
    Split text into chunks.

    Returns a list of:
        {"chunk_id": ..., "source_document": ..., "text": ..., "document_id"?, "project_id"?}

    document_id/project_id are additive: omitted from each chunk dict entirely when not
    provided, so the existing CLI ingestion call site (chunk_text(text,
    source_document=file_path.name)) is completely unaffected.

    When document_id IS provided (a per-project uploaded file), chunk_id is namespaced by
    document_id instead of source_document -- source_document is just the human-readable
    filename, which could collide across projects (or across two uploads of the same filename)
    if used directly as the vector ID prefix in the one shared Chroma collection.
    """

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.DOMAIN_CHUNK_SIZE,
        chunk_overlap=settings.DOMAIN_CHUNK_OVERLAP,
    )

    pieces = splitter.split_text(text)
    id_prefix = document_id or source_document

    chunks = []
    for index, piece in enumerate(pieces):
        if not piece.strip():
            continue

        chunk = {
            "chunk_id": f"{id_prefix}#{index}",
            "source_document": source_document,
            "text": piece,
        }

        if document_id:
            chunk["document_id"] = document_id
        if project_id:
            chunk["project_id"] = project_id

        chunks.append(chunk)

    return chunks
