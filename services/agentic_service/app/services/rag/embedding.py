"""
Domain knowledge embedder.

Purpose:
Convert text into vector embeddings using a local sentence-transformers
model, so the Domain Agent's retrieval step never depends on the chat LLM
provider (Ollama/OpenAI have no embedding endpoint wired up in this repo).

Why lazy-loaded:
Loading a sentence-transformers model takes real time (and disk/network on
first use). Doing this at import time would slow down every backend
startup, even when no Domain Agent run is in progress. Loading it on first
use means normal API requests are unaffected until retrieval is actually
needed.
"""

from app.core.config import settings


class DomainEmbedder:
    """
    Thin wrapper around a single sentence-transformers model instance.
    """

    def __init__(self):
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(settings.DOMAIN_EMBEDDING_MODEL)

        return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a batch of texts into normalized vectors.

        Normalization lets ChromaDB's default cosine-style distance behave
        consistently regardless of text length.
        """

        if not texts:
            return []

        model = self._get_model()
        vectors = model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()


domain_embedder = DomainEmbedder()
