"""All Qdrant vector store operations."""
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from extractor.schemas import AnyFact
from store.collection_config import COLLECTION_NAME, get_collection_config

logger = logging.getLogger(__name__)


class QdrantStore:
    def __init__(self, url: Optional[str] = None, api_key: Optional[str] = None):
        resolved_url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        resolved_key = api_key or os.environ.get("QDRANT_API_KEY") or None
        self._client = QdrantClient(url=resolved_url, api_key=resolved_key)
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        existing = [c.name for c in self._client.get_collections().collections]
        if COLLECTION_NAME not in existing:
            cfg = get_collection_config()
            self._client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=cfg["vector_size"],
                    distance=Distance.COSINE,
                ),
            )
            for field_name, field_type in cfg["indexed_fields"].items():
                from qdrant_client.models import PayloadSchemaType
                schema_type = (
                    PayloadSchemaType.KEYWORD
                    if field_type == "keyword"
                    else PayloadSchemaType.FLOAT
                )
                self._client.create_payload_index(
                    collection_name=COLLECTION_NAME,
                    field_name=field_name,
                    field_schema=schema_type,
                )

    def _compute_fact_id(self, client_id: str, fact: AnyFact) -> str:
        raw = f"{client_id}:{fact.fact_type}:{fact.content}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def upsert_fact(
        self,
        client_id: str,
        fact: AnyFact,
        vector: list[float],
        source_url: str,
        page_type: str,
        page_score: int,
        content_hash: str,
    ) -> None:
        fact_id = self._compute_fact_id(client_id, fact)
        # Use first 32 hex chars as a UUID-compatible id (128-bit)
        point_id = str(UUID(fact_id[:32]))

        payload = {
            "client_id": client_id,
            "fact_id": fact_id,
            "fact_type": fact.fact_type,
            "content": fact.content,
            "confidence": fact.confidence,
            "source_url": source_url,
            "page_type": page_type,
            "page_score": page_score,
            "content_hash": content_hash,
            "extracted_at": datetime.now(tz=timezone.utc).isoformat(),
            "raw_evidence": fact.raw_evidence,
        }
        # Include type-specific fields
        for k, v in fact.model_dump().items():
            if k not in payload:
                payload[k] = v

        self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def delete_facts_for_url(self, client_id: str, source_url: str) -> None:
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=Filter(
                must=[
                    FieldCondition(key="client_id", match=MatchValue(value=client_id)),
                    FieldCondition(key="source_url", match=MatchValue(value=source_url)),
                ]
            ),
        )

    def search(
        self,
        client_id: str,
        query_vector: list[float],
        limit: int = 5,
        fact_type: Optional[str] = None,
    ) -> list[dict]:
        must = [FieldCondition(key="client_id", match=MatchValue(value=client_id))]
        if fact_type:
            must.append(FieldCondition(key="fact_type", match=MatchValue(value=fact_type)))

        hits = self._client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector,
            query_filter=Filter(must=must),
            limit=limit,
            with_payload=True,
        )
        return [{"score": h.score, **h.payload} for h in hits]

    def content_hash_exists(self, client_id: str, source_url: str, content_hash: str) -> bool:
        results, _ = self._client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(key="client_id", match=MatchValue(value=client_id)),
                    FieldCondition(key="source_url", match=MatchValue(value=source_url)),
                    FieldCondition(key="content_hash", match=MatchValue(value=content_hash)),
                ]
            ),
            limit=1,
        )
        return len(results) > 0

    def get_fact_counts_by_type(self, client_id: str) -> dict[str, int]:
        results, _ = self._client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[FieldCondition(key="client_id", match=MatchValue(value=client_id))]
            ),
            with_payload=["fact_type"],
            limit=10_000,
        )
        counts: dict[str, int] = {}
        for point in results:
            ft = point.payload.get("fact_type", "unknown")
            counts[ft] = counts.get(ft, 0) + 1
        return counts
