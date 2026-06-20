"""Tests for the pipeline — incremental logic and Prefect tasks."""
import hashlib
import pytest
from unittest.mock import MagicMock, patch

from pipeline.incremental import compute_content_hash, ContentHashChecker


class TestComputeContentHash:
    def test_hash_is_hex_string(self):
        h = compute_content_hash("http://example.com/page", content="Hello world")
        assert isinstance(h, str)
        assert len(h) == 64  # sha256 hex

    def test_same_inputs_same_hash(self):
        h1 = compute_content_hash("http://example.com/page", content="Hello world")
        h2 = compute_content_hash("http://example.com/page", content="Hello world")
        assert h1 == h2

    def test_different_url_different_hash(self):
        h1 = compute_content_hash("http://example.com/page1", content="Hello world")
        h2 = compute_content_hash("http://example.com/page2", content="Hello world")
        assert h1 != h2

    def test_different_content_different_hash(self):
        h1 = compute_content_hash("http://example.com/page", content="Hello world")
        h2 = compute_content_hash("http://example.com/page", content="Goodbye world")
        assert h1 != h2

    def test_etag_included_in_hash(self):
        h1 = compute_content_hash("http://example.com/page", etag="etag-v1")
        h2 = compute_content_hash("http://example.com/page", etag="etag-v2")
        assert h1 != h2


class TestContentHashChecker:
    def test_should_crawl_returns_true_when_no_existing_hash(self):
        mock_store = MagicMock()
        mock_store.content_hash_exists.return_value = False
        checker = ContentHashChecker(store=mock_store)
        result = checker.should_crawl(
            client_id="client_abc",
            url="http://localhost:8888/dental/",
            content_hash="newhash",
        )
        assert result is True

    def test_should_crawl_returns_false_when_hash_matches(self):
        mock_store = MagicMock()
        mock_store.content_hash_exists.return_value = True
        checker = ContentHashChecker(store=mock_store)
        result = checker.should_crawl(
            client_id="client_abc",
            url="http://localhost:8888/dental/",
            content_hash="existinghash",
        )
        assert result is False
