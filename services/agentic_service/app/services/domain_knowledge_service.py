"""
Domain knowledge service.

Purpose:
Public entry point for the Domain Agent's RAG pipeline -- ingest domain
documents (PDF/DOCX/TXT/MD) into the vector store, and retrieve the most
relevant chunks for a given query.

Why this is a standalone service and not agent-internal:
Ingestion is a general concern (a CLI script populates the knowledge base
independently of any single agent run), even though DomainAgent is its
only consumer today.

Reliability contract:
retrieve() NEVER raises. A missing Chroma directory, an empty collection,
or a model load failure all just mean "no domain knowledge available yet"
-- it logs a warning and returns []. DomainAgent's reliability ladder
depends on this: retrieval failure must never be the reason a Domain
Agent run fails.
"""

from pathlib import Path
from typing import Any

from app.core.config import settings
from app.services.rag.chunking import chunk_text
from app.services.rag.embedding import domain_embedder
from app.services.rag.loaders import SUPPORTED_EXTENSIONS, load_text_from_file
from app.services.rag.vector_store import chroma_domain_vector_store
from app.utils.logger import get_logger

logger = get_logger(__name__)


class DomainKnowledgeService:
    """
    Ingests domain knowledge files and retrieves relevant chunks for a query.
    """

    def ingest_path(self, path: str | Path | None = None) -> dict[str, Any]:
        """
        Ingest one file, or every supported file under a directory
        (recursively), into the vector store.

        Never raises for a single bad file -- that file is counted in
        files_skipped and ingestion continues with the rest.
        """

        target = Path(path) if path else Path(settings.DOMAIN_KNOWLEDGE_BASE_DIR)

        if not target.exists():
            logger.warning("Domain knowledge path does not exist: %s", target)
            return {"files_ingested": 0, "chunks_created": 0, "files_skipped": 0}

        if target.is_file():
            files = [target]
        else:
            files = sorted(
                file for file in target.rglob("*")
                if file.is_file() and file.suffix.lower() in SUPPORTED_EXTENSIONS
            )

        files_ingested = 0
        chunks_created = 0
        files_skipped = 0

        for file_path in files:
            try:
                text = load_text_from_file(file_path)
                chunks = chunk_text(text, source_document=file_path.name)

                if not chunks:
                    logger.warning("No extractable text in domain knowledge file: %s", file_path)
                    files_skipped += 1
                    continue

                embeddings = domain_embedder.embed_texts([chunk["text"] for chunk in chunks])
                chroma_domain_vector_store.upsert(chunks, embeddings)

                files_ingested += 1
                chunks_created += len(chunks)

            except Exception as error:
                logger.warning("Skipping domain knowledge file %s: %s", file_path, error)
                files_skipped += 1

        return {
            "files_ingested": files_ingested,
            "chunks_created": chunks_created,
            "files_skipped": files_skipped,
        }

    # How much wider than top_k the unfiltered/global query casts its net, so that after
    # discarding any OTHER project's chunks (see retrieve()) there's still a good chance of
    # ending up with close to top_k legacy/global + this-project chunks, not a starved result.
    RETRIEVE_OVERFETCH_MULTIPLIER = 3

    def retrieve(self, query_text: str, project_id: str | None = None, top_k: int | None = None) -> list[dict]:
        """
        Retrieve the most relevant domain knowledge chunks for a query.

        Never raises. Returns [] if the vector store is empty/missing, the
        embedding model fails to load, or any other retrieval error occurs.

        project_id (optional): when given, also searches this project's own uploaded documents
        (chunks stamped with this project_id) alongside the legacy global/seed corpus (chunks
        with no project_id at all) -- and, critically, discards any chunk stamped with a
        DIFFERENT project's ID. The one shared Chroma collection means an unfiltered query could
        otherwise leak another project's uploaded content into this retrieval; this chromadb
        version's `where` can't express "key absent OR equals X" in a single server-side filter,
        so the exclusion is done here in Python. project_id=None (every caller before this
        feature existed) hits none of this new logic -- identical behavior to before.
        """

        if not query_text or not query_text.strip():
            return []

        try:
            k = top_k or settings.DOMAIN_TOP_K
            embedding = domain_embedder.embed_texts([query_text])[0]
            results_by_id: dict[str, dict] = {}

            if project_id:
                for chunk in chroma_domain_vector_store.query(
                    embedding=embedding, top_k=k, where={"project_id": project_id}
                ):
                    results_by_id[chunk["chunk_id"]] = chunk

            for chunk in chroma_domain_vector_store.query(
                embedding=embedding, top_k=k * self.RETRIEVE_OVERFETCH_MULTIPLIER
            ):
                owner = chunk.get("project_id")
                if owner is not None and owner != project_id:
                    continue
                results_by_id.setdefault(chunk["chunk_id"], chunk)

            merged = sorted(results_by_id.values(), key=lambda chunk: chunk.get("distance") or 0.0)
            return merged[:k]

        except Exception as error:
            logger.warning("Domain knowledge retrieval failed, returning no chunks: %s", error)
            return []

    def get_document_chunks(self, document_id: str) -> list[dict]:
        """
        Fetch every chunk of one uploaded document, unranked -- for a "/" pinned-document
        reference, where the whole document is meant to be guaranteed context rather than
        whatever a similarity search happens to surface. Never raises (see
        ChromaDomainVectorStore.get_chunks_by_document).
        """

        return chroma_domain_vector_store.get_chunks_by_document(document_id)

    def rank_chunks_by_relevance(self, chunks: list[dict], query_text: str) -> list[dict]:
        """
        Re-rank an already-fetched chunk list by similarity to query_text -- used to cap an
        oversized pinned document to its most relevant excerpts rather than an arbitrary
        front-of-document slice. Embeds only these chunks' texts plus the query (cheap: local
        model, small N). Never raises -- returns the original order on any embedding failure.
        """

        if not chunks or not query_text or not query_text.strip():
            return chunks

        try:
            texts = [chunk.get("text", "") for chunk in chunks]
            embeddings = domain_embedder.embed_texts(texts + [query_text])
            chunk_embeddings, query_embedding = embeddings[:-1], embeddings[-1]

            def cosine_similarity(a: list[float], b: list[float]) -> float:
                dot = sum(x * y for x, y in zip(a, b))
                norm_a = sum(x * x for x in a) ** 0.5
                norm_b = sum(y * y for y in b) ** 0.5
                if norm_a == 0 or norm_b == 0:
                    return 0.0
                return dot / (norm_a * norm_b)

            scored = list(zip(chunks, chunk_embeddings))
            scored.sort(key=lambda pair: cosine_similarity(pair[1], query_embedding), reverse=True)
            return [chunk for chunk, _ in scored]

        except Exception as error:
            logger.warning("Chunk relevance ranking failed, keeping original order: %s", error)
            return chunks

    def ingest_upload(
        self, project_id: str, document_id: str, file_path: Path, source_document: str
    ) -> dict[str, Any]:
        """
        Extract, chunk, embed, and upsert one already-on-disk uploaded file for one project.

        Unlike ingest_path (a CLI batch job that catches and skips a bad file so the rest of the
        directory still ingests), this raises ValueError on an unsupported extension or empty
        extracted text -- a single human upload's failure must surface back to the API caller as
        an actionable error, not be silently dropped.
        """

        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {file_path.suffix}")

        text = load_text_from_file(file_path)
        chunks = chunk_text(text, source_document=source_document, document_id=document_id, project_id=project_id)

        if not chunks:
            raise ValueError("No extractable text was found in this file.")

        embeddings = domain_embedder.embed_texts([chunk["text"] for chunk in chunks])
        chroma_domain_vector_store.upsert(chunks, embeddings)

        return {"chunks_created": len(chunks)}

    def delete_document(self, document_id: str) -> None:
        """
        Delete every chunk belonging to one uploaded document from the vector store.
        """

        chroma_domain_vector_store.delete_by_document(document_id)


domain_knowledge_service = DomainKnowledgeService()
