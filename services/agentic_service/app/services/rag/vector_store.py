"""
Domain knowledge vector store.

Purpose:
Wrap ChromaDB so the rest of the Domain Agent RAG pipeline never touches
the ChromaDB client API directly.

Why Chroma over MongoDB Atlas Vector Search:
langchain-mongodb is present in this project's environment, but Atlas
Vector Search requires a separately-configured Atlas Search index on a
real Atlas cluster -- extra infra for no capability gain at this project's
scale (a single local knowledge base). settings.CHROMA_PERSIST_DIR already
names Chroma explicitly, so this is the zero-new-infra path.
"""

from app.core.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

COLLECTION_NAME = "domain_knowledge"


class ChromaDomainVectorStore:
    """
    Thin wrapper around one persistent ChromaDB collection.
    """

    def __init__(self):
        self._client = None
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            import chromadb

            self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
            self._collection = self._client.get_or_create_collection(name=COLLECTION_NAME)

        return self._collection

    def upsert(self, chunks: list[dict], embeddings: list[list[float]]) -> None:
        """
        Insert or overwrite vectors for the given chunks.

        chunks: [{"chunk_id", "source_document", "text", "document_id"?, "project_id"?}, ...]
        embeddings: parallel list of embedding vectors.

        project_id/document_id are only added to a chunk's metadata when present on the input
        dict -- legacy globally-ingested chunks (no project_id/document_id) keep exactly their
        current metadata shape.
        """

        if not chunks:
            return

        collection = self._get_collection()

        metadatas = []
        for chunk in chunks:
            metadata = {"source_document": chunk["source_document"]}
            if chunk.get("project_id"):
                metadata["project_id"] = chunk["project_id"]
            if chunk.get("document_id"):
                metadata["document_id"] = chunk["document_id"]
            metadatas.append(metadata)

        collection.upsert(
            ids=[chunk["chunk_id"] for chunk in chunks],
            embeddings=embeddings,
            documents=[chunk["text"] for chunk in chunks],
            metadatas=metadatas,
        )

    def query(self, embedding: list[float], top_k: int, where: dict | None = None) -> list[dict]:
        """
        Return the top_k most similar chunks to the given query embedding, optionally filtered
        by a Chroma `where` metadata filter (e.g. {"project_id": "proj_123"}).

        Returns: [{"chunk_id", "source_document", "text", "distance", "project_id", "document_id"}, ...]
        (project_id/document_id are None when the matched chunk predates this feature.)

        Empty collection or any query error -> propagates to the caller, which is expected to
        catch it (domain_knowledge_service.retrieve never raises).
        """

        collection = self._get_collection()

        if collection.count() == 0:
            return []

        query_kwargs = {
            "query_embeddings": [embedding],
            "n_results": min(top_k, collection.count()),
        }
        if where:
            query_kwargs["where"] = where

        result = collection.query(**query_kwargs)

        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        chunks = []

        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            chunks.append({
                "chunk_id": chunk_id,
                "source_document": (metadata or {}).get("source_document", "unknown"),
                "text": documents[index] if index < len(documents) else "",
                "distance": distances[index] if index < len(distances) else None,
                "project_id": (metadata or {}).get("project_id"),
                "document_id": (metadata or {}).get("document_id"),
            })

        return chunks

    def get_chunks_by_document(self, document_id: str) -> list[dict]:
        """
        Fetch every chunk of one uploaded document, unranked (no query embedding needed) -- used
        for a "/" pinned-document reference, where the whole document should be guaranteed
        context rather than whatever a similarity search happens to surface.

        Never raises: any Chroma error just means "no chunks available for this document",
        matching this store's existing reliability contract.
        """

        try:
            collection = self._get_collection()
            result = collection.get(where={"document_id": document_id})
        except Exception:
            return []

        ids = result.get("ids", [])
        documents = result.get("documents", [])
        metadatas = result.get("metadatas", [])

        chunks = []
        for index, chunk_id in enumerate(ids):
            metadata = metadatas[index] if index < len(metadatas) else {}
            chunks.append({
                "chunk_id": chunk_id,
                "source_document": (metadata or {}).get("source_document", "unknown"),
                "text": documents[index] if index < len(documents) else "",
                "distance": None,
                "project_id": (metadata or {}).get("project_id"),
                "document_id": (metadata or {}).get("document_id"),
            })

        return chunks

    def delete_by_document(self, document_id: str) -> None:
        """
        Delete every chunk belonging to one document. Never raises -- a failed delete just
        leaves stale chunks behind rather than crashing the caller (e.g. a document-delete API
        request should still remove the Mongo record/raw file even if this step fails).
        """

        try:
            self._get_collection().delete(where={"document_id": document_id})
        except Exception as error:
            logger.warning("Failed to delete chunks for document_id=%s: %s", document_id, error)


chroma_domain_vector_store = ChromaDomainVectorStore()
