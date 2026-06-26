"""All Qdrant vector store operations."""

import hashlib
import logging
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from extractor.schemas import AnyFact
from store.collection_config import COLLECTION_NAME, get_collection_config

logger = logging.getLogger(__name__)

# Source type confidence multipliers for re-ranking
SOURCE_MULTIPLIERS: dict[str, float] = {
    "knowledge_base": 1.0,
    "website": 0.9,
    "document": 0.85,
}


class QdrantStore:
    def __init__(self, url: str | None = None, api_key: str | None = None):
        resolved_url = url or os.environ.get("QDRANT_URL", "http://localhost:6333")
        resolved_key = api_key or os.environ.get("QDRANT_API_KEY") or None
        if resolved_url == "memory":
            self._client = QdrantClient(":memory:")
        else:
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
        source_type: str = "website",
        extra_payload: dict | None = None,
    ) -> None:
        fact_id = self._compute_fact_id(client_id, fact)
        point_id = str(UUID(fact_id[:32]))

        payload: dict[str, Any] = {
            "client_id": client_id,
            "fact_id": fact_id,
            "fact_type": fact.fact_type,
            "content": fact.content,
            "confidence": fact.confidence,
            "source_url": source_url,
            "page_type": page_type,
            "page_score": page_score,
            "content_hash": content_hash,
            "extracted_at": datetime.now(tz=UTC).isoformat(),
            "raw_evidence": fact.raw_evidence,
        }
        # Include type-specific fields from the model
        for k, v in fact.model_dump().items():
            if k not in payload:
                payload[k] = v

        # source_type parameter always wins (overrides any model field)
        payload["source_type"] = source_type

        # Merge caller-supplied extra fields (document_name, kb_record_id, etc.)
        if extra_payload:
            payload.update(extra_payload)

        self._client.upsert(
            collection_name=COLLECTION_NAME,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def delete_facts_for_url(self, client_id: str, source_url: str) -> None:
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=FilterSelector(
                filter=Filter(
                    must=[
                        FieldCondition(key="client_id", match=MatchValue(value=client_id)),
                        FieldCondition(key="source_url", match=MatchValue(value=source_url)),
                    ]
                )
            ),
        )

    def delete_by_payload(self, client_id: str, **filter_fields) -> None:
        """Delete points matching client_id plus any additional payload field values."""
        must = [FieldCondition(key="client_id", match=MatchValue(value=client_id))]
        for field, value in filter_fields.items():
            must.append(FieldCondition(key=field, match=MatchValue(value=value)))
        self._client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=FilterSelector(filter=Filter(must=must)),
        )

    def search(
        self,
        client_id: str,
        query_vector: list[float],
        limit: int = 5,
        fact_type: str | None = None,
        source_type: str | None = None,
    ) -> list[dict]:
        must = [FieldCondition(key="client_id", match=MatchValue(value=client_id))]
        if fact_type:
            must.append(FieldCondition(key="fact_type", match=MatchValue(value=fact_type)))
        if source_type:
            must.append(FieldCondition(key="source_type", match=MatchValue(value=source_type)))

        # Over-fetch so re-ranking doesn't deplete the result set
        fetch_limit = max(limit * 3, 15)
        hits = self._client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=Filter(must=must),
            limit=fetch_limit,
            with_payload=True,
        ).points

        # Apply source-type confidence multiplier and re-rank
        ranked = []
        for h in hits:
            st = h.payload.get("source_type", "website")
            multiplier = SOURCE_MULTIPLIERS.get(st, 0.9)
            confidence = h.payload.get("confidence", 1.0)
            final_score = h.score * confidence * multiplier
            ranked.append({"_final_score": final_score, "score": h.score, **h.payload})

        ranked.sort(key=lambda x: -x["_final_score"])
        for r in ranked:
            r["score"] = r.pop("_final_score")

        return ranked[:limit]

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
