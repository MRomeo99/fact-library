"""Shared pytest configuration and fixtures."""

import pytest


@pytest.fixture(autouse=True)
def set_test_env(monkeypatch):
    """Set safe default env vars for all tests."""
    monkeypatch.setenv("LLM_MODE", "direct")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_MODEL_DIRECT", "gpt-4o-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-for-tests")
    monkeypatch.setenv("EMBEDDING_MODE", "local")
    monkeypatch.setenv("QDRANT_URL", "http://localhost:6333")
    monkeypatch.setenv("QDRANT_API_KEY", "")
