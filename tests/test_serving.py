"""Tests for the FastAPI serving layer."""
import sys
import types
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


def _stub_module(name: str, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


# Stub heavy optional dependencies before importing serving modules
_qdrant = _stub_module("qdrant_client")
_qdrant.QdrantClient = MagicMock  # type: ignore
_qdrant_models = _stub_module("qdrant_client.models")
for _n in ["Distance", "FieldCondition", "Filter", "MatchValue", "PointStruct", "VectorParams", "PayloadSchemaType"]:
    setattr(_qdrant_models, _n, MagicMock())

_st_stub = _stub_module("sentence_transformers")
_st_stub.SentenceTransformer = MagicMock  # type: ignore

_prefect = _stub_module("prefect")
_prefect.task = lambda *a, **kw: (lambda fn: fn)  # type: ignore
_prefect.flow = lambda *a, **kw: (lambda fn: fn)  # type: ignore
_prefect_schedules = _stub_module("prefect.schedules")
_prefect_schedules.CronSchedule = MagicMock  # type: ignore

from fastapi.testclient import TestClient


@pytest.fixture
def mock_store():
    store = MagicMock()
    store.search.return_value = [
        {
            "fact_id": "abc123",
            "fact_type": "pricing",
            "content": "Initial consultation is $150.",
            "confidence": 0.92,
            "source_url": "http://localhost:8888/dental/pricing",
            "page_type": "pricing",
            "extracted_at": datetime(2025, 6, 1, 3, 0, 0, tzinfo=timezone.utc).isoformat(),
            "score": 0.87,
            "page_score": 4,
            "raw_evidence": "Initial consultation: $150",
        }
    ]
    store.get_fact_counts_by_type.return_value = {"pricing": 3, "service": 5}
    return store


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.embed.return_value = [0.1] * 384
    return embedder


@pytest.fixture
def client(mock_store, mock_embedder):
    from serving.main import app
    from serving.routers import facts, status, crawl

    app.dependency_overrides[facts.get_store] = lambda: mock_store
    app.dependency_overrides[facts.get_embedder] = lambda: mock_embedder
    app.dependency_overrides[status.get_store] = lambda: mock_store
    app.dependency_overrides[crawl.get_store] = lambda: mock_store

    yield TestClient(app)

    app.dependency_overrides.clear()


class TestFactsEndpoint:
    def test_get_facts_returns_200(self, client):
        response = client.get("/facts/client_abc?q=what+are+your+prices")
        assert response.status_code == 200

    def test_get_facts_response_shape(self, client):
        response = client.get("/facts/client_abc?q=what+are+your+prices")
        data = response.json()
        assert "client_id" in data
        assert "query" in data
        assert "results" in data
        assert "total" in data

    def test_get_facts_client_id_in_response(self, client):
        response = client.get("/facts/client_abc?q=prices")
        data = response.json()
        assert data["client_id"] == "client_abc"

    def test_get_facts_result_has_required_fields(self, client):
        response = client.get("/facts/client_abc?q=prices")
        data = response.json()
        result = data["results"][0]
        required_fields = [
            "fact_id", "fact_type", "content", "confidence",
            "source_url", "source_type", "page_type", "extracted_at", "score", "fact_age_days",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_get_facts_with_source_type_filter(self, client):
        response = client.get("/facts/client_abc?q=prices&source_type=knowledge_base")
        assert response.status_code == 200

    def test_get_facts_fact_age_days_is_int(self, client):
        response = client.get("/facts/client_abc?q=prices")
        data = response.json()
        assert isinstance(data["results"][0]["fact_age_days"], int)

    def test_get_facts_with_fact_type_filter(self, client):
        response = client.get("/facts/client_abc?q=prices&fact_type=pricing")
        assert response.status_code == 200

    def test_get_facts_missing_query_returns_422(self, client):
        response = client.get("/facts/client_abc")
        assert response.status_code == 422


class TestStatusEndpoint:
    def test_status_returns_200(self, client):
        response = client.get("/facts/client_abc/status")
        assert response.status_code == 200

    def test_status_response_has_fact_counts(self, client):
        response = client.get("/facts/client_abc/status")
        data = response.json()
        assert "fact_counts" in data or "client_id" in data


class TestTypesEndpoint:
    def test_types_returns_200(self, client):
        response = client.get("/facts/client_abc/types")
        assert response.status_code == 200
