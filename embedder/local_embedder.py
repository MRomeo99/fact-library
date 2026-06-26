"""Local embedding using sentence-transformers (zero cost, no API key)."""

from embedder.base import AbstractEmbedder

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class LocalEmbedder(AbstractEmbedder):
    dimension = 384

    def __init__(self):
        from sentence_transformers import SentenceTransformer  # lazy import

        self._model = SentenceTransformer(MODEL_NAME)

    def embed(self, text: str) -> list[float]:
        vector = self._model.encode([text])[0]
        return vector.tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(texts)
        return [v.tolist() for v in vectors]
