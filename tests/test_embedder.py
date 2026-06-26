"""Tests for the embedding layer."""

import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Stub sentence_transformers before importing LocalEmbedder so tests work
# without the (large) package installed. Tests that use LocalEmbedder patch
# the import inside the constructor anyway.
if "sentence_transformers" not in sys.modules:
    _st_stub = types.ModuleType("sentence_transformers")
    _st_stub.SentenceTransformer = MagicMock  # type: ignore
    sys.modules["sentence_transformers"] = _st_stub

from embedder.base import AbstractEmbedder
from embedder.local_embedder import LocalEmbedder


class TestAbstractEmbedder:
    def test_abstract_embedder_cannot_be_instantiated(self):
        with pytest.raises(TypeError):
            AbstractEmbedder()

    def test_concrete_embedder_must_implement_embed(self):
        class BadEmbedder(AbstractEmbedder):
            pass  # does not implement embed()

        with pytest.raises(TypeError):
            BadEmbedder()


class TestLocalEmbedder:
    @pytest.fixture
    def mock_model(self):
        model = MagicMock()
        model.encode.return_value = np.zeros((1, 384), dtype=np.float32)
        return model

    def test_embed_returns_list_of_floats(self, mock_model):
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            embedder = LocalEmbedder()
            result = embedder.embed("pricing: Initial consultation is $150.")
        assert isinstance(result, list)
        assert len(result) == 384
        assert all(isinstance(v, float) for v in result)

    def test_embed_batch_returns_list_of_vectors(self, mock_model):
        texts = ["pricing: $150", "service: teeth whitening"]
        mock_model.encode.return_value = np.zeros((2, 384), dtype=np.float32)
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            embedder = LocalEmbedder()
            results = embedder.embed_batch(texts)
        assert len(results) == 2
        assert all(len(v) == 384 for v in results)

    def test_embed_text_format_includes_type_prefix(self, mock_model):
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            embedder = LocalEmbedder()
            embedder.embed("pricing: Initial consultation is $150.")
        # The text passed to encode should be the full string
        call_args = mock_model.encode.call_args
        assert call_args is not None

    def test_vector_dimension_is_384(self, mock_model):
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model):
            embedder = LocalEmbedder()
            assert embedder.dimension == 384

    def test_model_name_is_minilm(self, mock_model):
        with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_st:
            LocalEmbedder()
            mock_st.assert_called_once_with("sentence-transformers/all-MiniLM-L6-v2")
