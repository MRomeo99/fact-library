"""Abstract base class for all embedders."""

from abc import ABC, abstractmethod


class AbstractEmbedder(ABC):
    dimension: int

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed a single text string and return a float vector."""
        ...

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts and return a list of float vectors."""
        ...
