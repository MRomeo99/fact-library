"""Tests for document ingestion — written first (TDD)."""

import sys
import types
from unittest.mock import MagicMock

import pytest


def _stub_module(name: str, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]


# Stub qdrant_client
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

# Stub portkey_ai and google for llm_client imports
_pk_stub = _stub_module("portkey_ai")
_pk_stub.Portkey = MagicMock
_gai_parent = _stub_module("google")
_gai_stub = _stub_module("google.generativeai")
_gai_stub.configure = MagicMock()
_gai_stub.GenerativeModel = MagicMock()
if not hasattr(_gai_parent, "generativeai"):
    _gai_parent.generativeai = _gai_stub

from extractor.schemas import LocationFact, ServiceFact
from ingestion.document_ingestion import (
    chunk_document,
    ingest_document,
    parse_document,
)


class TestParseDocument:
    def test_parse_txt_file(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello world\nThis is a test document.")
        result = parse_document(str(txt_file))
        assert "Hello world" in result
        assert "This is a test document" in result

    def test_parse_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            parse_document(str(tmp_path / "nonexistent.txt"))

    def test_parse_unsupported_extension_raises(self, tmp_path):
        bad_file = tmp_path / "test.xyz"
        bad_file.write_text("content")
        with pytest.raises(ValueError, match="Unsupported"):
            parse_document(str(bad_file))

    def test_parse_txt_strips_extra_whitespace(self, tmp_path):
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("  Hello   world  \n\n  Second line  ")
        result = parse_document(str(txt_file))
        assert result.strip() != ""
        assert "Hello" in result
        assert "Second line" in result


class TestChunkDocument:
    def test_short_text_returns_one_chunk(self):
        text = "This is a short document."
        chunks = chunk_document(text, document_name="test.txt")
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].document_name == "test.txt"
        assert chunks[0].page_number == 1

    def test_long_text_splits_into_multiple_chunks(self):
        # ~3000 words — should split at ~1500 token limit
        word = "word "
        long_text = word * 3000
        chunks = chunk_document(long_text, document_name="long.txt")
        assert len(chunks) > 1

    def test_each_chunk_within_token_limit(self):
        word = "word "
        long_text = word * 3000
        chunks = chunk_document(long_text, document_name="long.txt")
        for chunk in chunks:
            # Rough guard: 1 word ≈ 1 token; allow a 10% buffer
            assert len(chunk.text.split()) <= 1650

    def test_chunk_preserves_document_name(self):
        chunks = chunk_document("Some text here.", document_name="service_menu.pdf")
        assert all(c.document_name == "service_menu.pdf" for c in chunks)

    def test_chunk_assigns_sequential_page_numbers(self):
        word = "word "
        long_text = word * 3000
        chunks = chunk_document(long_text, document_name="test.txt")
        for i, chunk in enumerate(chunks):
            assert chunk.page_number == i + 1

    def test_chunk_has_section_heading_field(self):
        chunks = chunk_document("# Introduction\nSome content here.", document_name="doc.txt")
        assert hasattr(chunks[0], "section_heading")

    def test_empty_text_returns_empty_list(self):
        chunks = chunk_document("", document_name="empty.txt")
        assert chunks == []


class TestIngestDocument:
    def _make_mocks(self):
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = [
            ServiceFact(
                fact_type="service",
                service_name="Teeth Whitening",
                content="Teeth whitening for $200 per session",
                confidence=0.9,
                raw_evidence="Teeth whitening $200 per session",
            )
        ]
        return mock_store, mock_embedder, mock_extractor

    def test_ingest_calls_delete_then_upsert(self, tmp_path):
        txt_file = tmp_path / "menu.txt"
        txt_file.write_text("We offer teeth whitening for $200 per session.")

        mock_store, mock_embedder, mock_extractor = self._make_mocks()
        result = ingest_document(
            client_id="test_client",
            file_path=str(txt_file),
            document_name="menu.txt",
            store=mock_store,
            embedder=mock_embedder,
            extractor=mock_extractor,
        )
        mock_store.delete_by_payload.assert_called_once_with(
            client_id="test_client",
            document_name="menu.txt",
        )
        assert mock_store.upsert_fact.call_count >= 1
        assert result["facts_upserted"] >= 1

    def test_ingest_passes_source_type_document(self, tmp_path):
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("Service area includes Dallas and Fort Worth.")

        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = [
            LocationFact(
                fact_type="location",
                content="Dallas and Fort Worth service area",
                confidence=0.85,
                raw_evidence="Service area includes Dallas and Fort Worth",
                service_area=["Dallas", "Fort Worth"],
            )
        ]

        ingest_document(
            client_id="test_client",
            file_path=str(txt_file),
            document_name="doc.txt",
            store=mock_store,
            embedder=mock_embedder,
            extractor=mock_extractor,
        )
        call_kwargs = mock_store.upsert_fact.call_args.kwargs
        assert call_kwargs.get("source_type") == "document"

    def test_ingest_includes_document_metadata_in_extra_payload(self, tmp_path):
        txt_file = tmp_path / "menu.txt"
        txt_file.write_text("Dental services starting at $100.")

        mock_store, mock_embedder, mock_extractor = self._make_mocks()
        ingest_document(
            client_id="test_client",
            file_path=str(txt_file),
            document_name="menu.txt",
            store=mock_store,
            embedder=mock_embedder,
            extractor=mock_extractor,
        )
        call_kwargs = mock_store.upsert_fact.call_args.kwargs
        extra = call_kwargs.get("extra_payload", {})
        assert extra.get("document_name") == "menu.txt"
        assert "page_number" in extra

    def test_ingest_skips_low_confidence_facts(self, tmp_path):
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("Some content.")

        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [0.1] * 384
        mock_extractor = MagicMock()
        # All facts below confidence threshold
        mock_extractor.extract.return_value = []

        result = ingest_document(
            client_id="test_client",
            file_path=str(txt_file),
            document_name="doc.txt",
            store=mock_store,
            embedder=mock_embedder,
            extractor=mock_extractor,
        )
        assert result["facts_upserted"] == 0
        mock_store.upsert_fact.assert_not_called()

    def test_ingest_returns_chunk_count(self, tmp_path):
        txt_file = tmp_path / "doc.txt"
        txt_file.write_text("Short content.")

        mock_store, mock_embedder, mock_extractor = self._make_mocks()
        result = ingest_document(
            client_id="test_client",
            file_path=str(txt_file),
            document_name="doc.txt",
            store=mock_store,
            embedder=mock_embedder,
            extractor=mock_extractor,
        )
        assert result["chunks_processed"] >= 1
