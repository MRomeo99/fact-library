"""Tests for Qdrant store operations."""

import sys
import types
from unittest.mock import MagicMock, patch

import pytest


def _stub_module(name: str, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


# Stub qdrant_client and all sub-modules before importing store
_qdrant = _stub_module("qdrant_client")
_qdrant.QdrantClient = MagicMock  # type: ignore
_qdrant_models = _stub_module("qdrant_client.models")
for _name in [
    "Distance",
    "FieldCondition",
    "Filter",
    "FilterSelector",
    "MatchValue",
    "PointStruct",
    "VectorParams",
    "PayloadSchemaType",
]:
    setattr(_qdrant_models, _name, MagicMock())

from extractor.schemas import IdentityFact, ServiceFact
from store.collection_config import COLLECTION_NAME, get_collection_config
from store.qdrant_store import QdrantStore


def _make_identity_fact() -> IdentityFact:
    return IdentityFact(
        fact_type="identity",
        content="Sunrise Dental is a family dental practice.",
        confidence=0.95,
        raw_evidence="Sunrise Dental — family practice since 2005.",
    )


def _make_service_fact() -> ServiceFact:
    return ServiceFact(
        fact_type="service",
        content="We offer professional teeth whitening.",
        confidence=0.88,
        raw_evidence="Professional teeth whitening — $199/session.",
        service_name="Teeth Whitening",
    )


class TestCollectionConfig:
    def test_collection_name_is_client_facts(self):
        assert COLLECTION_NAME == "client_facts"

    def test_collection_config_vector_size_384(self):
        config = get_collection_config()
        assert config["vector_size"] == 384

    def test_collection_config_cosine_distance(self):
        config = get_collection_config()
        assert config["distance"] == "Cosine"


class TestQdrantStore:
    @pytest.fixture
    def mock_qdrant(self):
        with patch("store.qdrant_store.QdrantClient") as mock_cls:
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            yield mock_instance

    def test_upsert_fact_calls_qdrant_upsert(self, mock_qdrant):
        store = QdrantStore()
        fact = _make_identity_fact()
        vector = [0.1] * 384
        store.upsert_fact(
            client_id="client_abc",
            fact=fact,
            vector=vector,
            source_url="http://localhost:8888/dental/",
            page_type="homepage",
            page_score=4,
            content_hash="abc123",
        )
        mock_qdrant.upsert.assert_called_once()

    def test_fact_id_is_deterministic(self, mock_qdrant):
        store = QdrantStore()
        fact = _make_identity_fact()
        fact_id_1 = store._compute_fact_id("client_abc", fact)
        fact_id_2 = store._compute_fact_id("client_abc", fact)
        assert fact_id_1 == fact_id_2

    def test_fact_id_changes_with_different_client(self, mock_qdrant):
        store = QdrantStore()
        fact = _make_identity_fact()
        fact_id_1 = store._compute_fact_id("client_abc", fact)
        fact_id_2 = store._compute_fact_id("client_xyz", fact)
        assert fact_id_1 != fact_id_2

    def test_delete_facts_for_url_calls_delete(self, mock_qdrant):
        store = QdrantStore()
        store.delete_facts_for_url(
            client_id="client_abc",
            source_url="http://localhost:8888/dental/old-page",
        )
        mock_qdrant.delete.assert_called_once()

    def test_search_returns_list(self, mock_qdrant):
        mock_result = MagicMock()
        mock_result.points = []
        mock_qdrant.query_points.return_value = mock_result
        store = QdrantStore()
        results = store.search(
            client_id="client_abc",
            query_vector=[0.1] * 384,
            limit=5,
        )
        assert isinstance(results, list)

    def test_search_with_fact_type_filter(self, mock_qdrant):
        mock_result = MagicMock()
        mock_result.points = []
        mock_qdrant.query_points.return_value = mock_result
        store = QdrantStore()
        store.search(
            client_id="client_abc",
            query_vector=[0.1] * 384,
            limit=5,
            fact_type="pricing",
        )
        call_kwargs = mock_qdrant.query_points.call_args
        assert call_kwargs is not None

    def test_content_hash_check_returns_bool(self, mock_qdrant):
        mock_qdrant.scroll.return_value = ([], None)
        store = QdrantStore()
        result = store.content_hash_exists(
            client_id="client_abc",
            source_url="http://localhost:8888/dental/",
            content_hash="abc123",
        )
        assert isinstance(result, bool)

    def test_get_fact_counts_by_type(self, mock_qdrant):
        mock_qdrant.scroll.return_value = ([], None)
        store = QdrantStore()
        counts = store.get_fact_counts_by_type(client_id="client_abc")
        assert isinstance(counts, dict)
