"""Tests for knowledge base ingestion — written first (TDD)."""

import sys
import types
from datetime import UTC, datetime
from unittest.mock import MagicMock


def _stub_module(name: str, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


# Stub qdrant_client before any imports that pull in qdrant_store
_qdrant = _stub_module("qdrant_client")
_qdrant.QdrantClient = MagicMock
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

from extractor.schemas import ConditionalFact, QAFact
from ingestion.kb_ingestion import (
    get_embed_text_for_kb_fact,
    map_kb_row_to_fact,
    sync_knowledge_base,
)

CONDITIONAL_ROW = {
    "id": "abc123",
    "client_id": "test_client",
    "fact_type": "conditional",
    "title": "Cancellation policy",
    "condition": "caller asks about cancellation",
    "response": "Inform them of the 48-hour cancellation window and $50 late fee",
    "exception_note": "Unless they are a platinum member",
    "priority": 8,
    "is_active": True,
    "updated_at": datetime(2025, 6, 1, tzinfo=UTC),
    "created_by": "admin",
}

QA_ROW = {
    "id": "def456",
    "client_id": "test_client",
    "fact_type": "qa",
    "title": "Payment plans",
    "condition": "Do you offer payment plans?",
    "response": "Yes, we offer 0% financing through CareCredit for treatments over $500.",
    "exception_note": None,
    "priority": 5,
    "is_active": True,
    "updated_at": datetime(2025, 6, 1, tzinfo=UTC),
    "created_by": "admin",
}


class TestMapKBRowToFact:
    def test_conditional_row_returns_conditional_fact(self):
        fact = map_kb_row_to_fact(CONDITIONAL_ROW)
        assert isinstance(fact, ConditionalFact)
        assert fact.fact_type == "conditional"
        assert fact.condition == CONDITIONAL_ROW["condition"]
        assert fact.response == CONDITIONAL_ROW["response"]
        assert fact.exception_note == CONDITIONAL_ROW["exception_note"]
        assert fact.priority == 8
        assert fact.confidence == 1.0
        assert fact.source_type == "knowledge_base"

    def test_qa_row_returns_qa_fact(self):
        fact = map_kb_row_to_fact(QA_ROW)
        assert isinstance(fact, QAFact)
        assert fact.fact_type == "qa"
        assert fact.question == QA_ROW["condition"]
        assert fact.answer == QA_ROW["response"]
        assert fact.confidence == 1.0
        assert fact.source_type == "knowledge_base"

    def test_talking_point_row_maps_to_qa_fact(self):
        row = {**CONDITIONAL_ROW, "fact_type": "talking_point", "condition": None}
        fact = map_kb_row_to_fact(row)
        assert isinstance(fact, QAFact)

    def test_pricing_override_row_maps_to_qa_fact(self):
        row = {**CONDITIONAL_ROW, "fact_type": "pricing_override", "condition": None}
        fact = map_kb_row_to_fact(row)
        assert isinstance(fact, QAFact)

    def test_unknown_fact_type_returns_none(self):
        row = {**CONDITIONAL_ROW, "fact_type": "unknown_type"}
        result = map_kb_row_to_fact(row)
        assert result is None

    def test_conditional_fact_content_includes_condition_and_response(self):
        fact = map_kb_row_to_fact(CONDITIONAL_ROW)
        assert CONDITIONAL_ROW["condition"] in fact.content
        assert CONDITIONAL_ROW["response"] in fact.content

    def test_qa_fact_content_is_answer(self):
        fact = map_kb_row_to_fact(QA_ROW)
        assert fact.content == QA_ROW["response"]


class TestGetEmbedTextForKBFact:
    def test_conditional_embed_includes_condition_and_response(self):
        fact = map_kb_row_to_fact(CONDITIONAL_ROW)
        text = get_embed_text_for_kb_fact(fact)
        assert "conditional" in text
        assert CONDITIONAL_ROW["condition"] in text
        assert CONDITIONAL_ROW["response"] in text

    def test_conditional_embed_uses_if_then_format(self):
        fact = map_kb_row_to_fact(CONDITIONAL_ROW)
        text = get_embed_text_for_kb_fact(fact)
        assert "if" in text.lower()
        assert "then" in text.lower()

    def test_qa_embed_includes_question_and_answer(self):
        fact = map_kb_row_to_fact(QA_ROW)
        text = get_embed_text_for_kb_fact(fact)
        assert QA_ROW["condition"] in text
        assert QA_ROW["response"] in text


class TestSyncKnowledgeBase:
    def test_upserts_active_records(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384

        result = sync_knowledge_base(
            client_id="test_client",
            rows=[CONDITIONAL_ROW],
            store=mock_store,
            embedder=mock_embedder,
        )
        assert result["updated"] == 1
        mock_store.upsert_fact.assert_called_once()

    def test_deletes_inactive_records(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()

        inactive_row = {**CONDITIONAL_ROW, "is_active": False}
        result = sync_knowledge_base(
            client_id="test_client",
            rows=[inactive_row],
            store=mock_store,
            embedder=mock_embedder,
        )
        assert result["deleted"] == 1
        mock_store.delete_by_payload.assert_called_with(
            client_id="test_client",
            kb_record_id="abc123",
        )
        mock_store.upsert_fact.assert_not_called()

    def test_skips_unmappable_rows(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384

        bad_row = {**CONDITIONAL_ROW, "fact_type": "unknown"}
        result = sync_knowledge_base(
            client_id="test_client",
            rows=[bad_row],
            store=mock_store,
            embedder=mock_embedder,
        )
        assert result["updated"] == 0
        assert result["skipped"] == 1

    def test_returns_correct_counts_for_mixed_rows(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384

        rows = [
            CONDITIONAL_ROW,
            QA_ROW,
            {**CONDITIONAL_ROW, "id": "del1", "is_active": False},
        ]
        result = sync_knowledge_base(
            client_id="test_client",
            rows=rows,
            store=mock_store,
            embedder=mock_embedder,
        )
        assert result["updated"] == 2
        assert result["deleted"] == 1
        assert result["total"] == 3

    def test_upsert_called_with_knowledge_base_source_type(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384

        sync_knowledge_base(
            client_id="test_client",
            rows=[CONDITIONAL_ROW],
            store=mock_store,
            embedder=mock_embedder,
        )
        call_kwargs = mock_store.upsert_fact.call_args.kwargs
        assert call_kwargs.get("source_type") == "knowledge_base"

    def test_upsert_includes_kb_record_id_in_extra_payload(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384

        sync_knowledge_base(
            client_id="test_client",
            rows=[CONDITIONAL_ROW],
            store=mock_store,
            embedder=mock_embedder,
        )
        call_kwargs = mock_store.upsert_fact.call_args.kwargs
        extra = call_kwargs.get("extra_payload", {})
        assert extra.get("kb_record_id") == "abc123"
