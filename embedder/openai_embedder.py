"""OpenAI embedding swap — use when EMBEDDING_MODE=openai."""

import os

from embedder.base import AbstractEmbedder

OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_DIMENSION = 1536


class OpenAIEmbedder(AbstractEmbedder):
    dimension = OPENAI_DIMENSION

    def __init__(self):
        from openai import OpenAI

        self._client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    def embed(self, text: str) -> list[float]:
        response = self._client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]
