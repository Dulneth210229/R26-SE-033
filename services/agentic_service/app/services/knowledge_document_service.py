"""
Knowledge document service.

Purpose:
Owns everything domain_knowledge_service.py deliberately doesn't -- per-project document
bookkeeping (Mongo metadata) and raw-file storage -- and orchestrates calls into
domain_knowledge_service for the actual RAG ingestion/deletion. Mirrors this codebase's existing
project_memory_service vs. RAG-service separation (project_memory_service owns cross-feature
project files; this owns uploaded knowledge documents).

Storage convention (mirrors project_memory_service.py's outputs/{project_slug}/_project/ root):
    outputs/{project_slug}/_project/knowledge/{document_id}__{original_filename}
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.domain_knowledge_service import domain_knowledge_service
from app.services.in_memory_store import store
from app.services.rag.loaders import SUPPORTED_EXTENSIONS
from app.utils.file_manager import ensure_directory
from app.utils.id_generator import generate_id
from app.utils.logger import get_logger
from app.utils.slugify import slugify

logger = get_logger(__name__)


class KnowledgeDocumentService:
    """
    CRUD + storage for per-project uploaded domain knowledge documents.
    """

    def _project_slug(self, project_id: str) -> str:
        project = store.projects.get(project_id)

        if not project:
            raise ValueError(f"Project not found: {project_id}")

        return slugify(project.get("project_name") or project_id)

    def _documents_root(self, project_id: str) -> Path:
        return Path(settings.OUTPUT_DIR) / self._project_slug(project_id) / "_project" / "knowledge"

    def upload_document(
        self, project_id: str, file_bytes: bytes, filename: str, uploaded_by: str = "human_user"
    ) -> dict[str, Any]:
        """
        Validate, store the raw file, ingest it into the vector store, and record its metadata.

        Raises ValueError for: unknown project, unsupported extension, oversized file. A failure
        during ingestion (bad/unreadable content) is NOT raised -- it's recorded as
        status="failed" on the document so it stays visible/diagnosable rather than vanishing,
        matching this service's "never silently lose a human's upload" intent.
        """

        if not store.projects.get(project_id):
            raise ValueError(f"Project not found: {project_id}")

        extension = Path(filename).suffix.lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file type '{extension}'. Supported types: {sorted(SUPPORTED_EXTENSIONS)}"
            )

        if len(file_bytes) > settings.DOMAIN_MAX_UPLOAD_BYTES:
            raise ValueError(
                f"File is too large ({len(file_bytes)} bytes). "
                f"Maximum allowed is {settings.DOMAIN_MAX_UPLOAD_BYTES} bytes."
            )

        document_id = generate_id("doc")
        file_path = self._documents_root(project_id) / f"{document_id}__{filename}"
        ensure_directory(file_path.parent)
        file_path.write_bytes(file_bytes)

        record = {
            "document_id": document_id,
            "project_id": project_id,
            "original_filename": filename,
            "file_extension": extension,
            "file_size_bytes": len(file_bytes),
            "chunk_count": 0,
            "status": "processing",
            "failure_reason": None,
            "uploaded_at": datetime.now(timezone.utc),
            "uploaded_by": uploaded_by,
        }
        store.knowledge_documents[document_id] = record

        try:
            result = domain_knowledge_service.ingest_upload(
                project_id=project_id,
                document_id=document_id,
                file_path=file_path,
                source_document=filename,
            )
            record["status"] = "ready"
            record["chunk_count"] = result["chunks_created"]

        except Exception as error:
            logger.warning("Knowledge document ingestion failed for %s: %s", document_id, error)
            record["status"] = "failed"
            record["failure_reason"] = str(error)

        store.knowledge_documents[document_id] = record
        return record

    def list_documents(self, project_id: str) -> list[dict[str, Any]]:
        documents = [doc for doc in store.knowledge_documents.values() if doc.get("project_id") == project_id]
        return sorted(documents, key=lambda doc: doc.get("uploaded_at") or datetime.min, reverse=True)

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        return store.knowledge_documents.get(document_id)

    def read_document_bytes(self, document_id: str) -> bytes:
        document = self.get_document(document_id)

        if not document:
            raise ValueError(f"Knowledge document not found: {document_id}")

        file_path = (
            self._documents_root(document["project_id"])
            / f"{document_id}__{document['original_filename']}"
        )
        return file_path.read_bytes()

    def delete_document(self, document_id: str) -> None:
        """
        Delete the vector chunks, the raw file, and the Mongo record -- each step independent
        (there is no cross-store transaction to roll back, so a failure in one step still lets
        the others proceed rather than leaving everything stuck).
        """

        document = self.get_document(document_id)

        if not document:
            return

        try:
            domain_knowledge_service.delete_document(document_id)
        except Exception as error:
            logger.warning("Failed to delete vector chunks for document %s: %s", document_id, error)

        try:
            file_path = (
                self._documents_root(document["project_id"])
                / f"{document_id}__{document['original_filename']}"
            )
            file_path.unlink(missing_ok=True)
        except Exception as error:
            logger.warning("Failed to delete raw file for document %s: %s", document_id, error)

        store.knowledge_documents.collection.delete_one({"document_id": document_id})


knowledge_document_service = KnowledgeDocumentService()
