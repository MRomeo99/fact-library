"""GET /facts/{client_id} — semantic search with optional fact_type filter."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from embedder.base import AbstractEmbedder
from store.qdrant_store import QdrantStore

router = APIRouter()


def get_store() -> QdrantStore:
    return QdrantStore()


def get_embedder() -> AbstractEmbedder:
    import os
    mode = os.environ.get("EMBEDDING_MODE", "local")
    if mode == "openai":
        from embedder.openai_embedder import OpenAIEmbedder
        return OpenAIEmbedder()
    from embedder.local_embedder import LocalEmbedder
    return LocalEmbedder()


@router.get("/facts/{client_id}")
def search_facts(
    client_id: str,
    q: str = Query(..., description="Natural language query"),
    fact_type: Optional[str] = Query(None, description="Filter by fact type"),
    limit: int = Query(5, ge=1, le=50),
    store: QdrantStore = Depends(get_store),
    embedder: AbstractEmbedder = Depends(get_embedder),
):
    query_vector = embedder.embed(q)
    hits = store.search(
        client_id=client_id,
        query_vector=query_vector,
        limit=limit,
        fact_type=fact_type,
    )
    now = datetime.now(tz=timezone.utc)
    results = []
    for hit in hits:
        extracted_at_str = hit.get("extracted_at")
        try:
            extracted_dt = datetime.fromisoformat(extracted_at_str)
            if extracted_dt.tzinfo is None:
                extracted_dt = extracted_dt.replace(tzinfo=timezone.utc)
            fact_age_days = (now - extracted_dt).days
        except Exception:
            fact_age_days = -1

        results.append({
            "fact_id": hit.get("fact_id", ""),
            "fact_type": hit.get("fact_type", ""),
            "content": hit.get("content", ""),
            "confidence": hit.get("confidence", 0.0),
            "source_url": hit.get("source_url", ""),
            "page_type": hit.get("page_type", ""),
            "extracted_at": extracted_at_str,
            "fact_age_days": fact_age_days,
            "score": hit.get("score", 0.0),
        })

    return {
        "client_id": client_id,
        "query": q,
        "results": results,
        "total": len(results),
    }
