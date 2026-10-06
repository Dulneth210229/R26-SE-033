"""
Per-project domain knowledge document schemas.

A "knowledge document" is a user-uploaded file (PDF/DOCX/TXT/MD) scoped to one project, ingested
into the Domain Agent's RAG pipeline so it can either surface via normal similarity search or be
pinned by document_id when a human references it directly (see domain_schema.py's
referenced_document_ids).
"""

from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeDocumentResponse(BaseModel):
    """
    Metadata for one uploaded knowledge document -- never includes the raw file content itself
    (see the dedicated .../download route for that).
    """

    document_id: str = Field(..., example="doc_ab12cd34ef56")
    project_id: str
    original_filename: str = Field(..., example="database_schema.pdf")
    file_extension: str = Field(..., example=".pdf")
    file_size_bytes: int
    chunk_count: int = Field(default=0, description="Number of vector chunks created from this document.")
    status: str = Field(..., description="processing | ready | failed", example="ready")
    failure_reason: str | None = Field(default=None)
    uploaded_at: datetime
    uploaded_by: str = Field(default="human_user")
