"""Knowledge base ingestion — CDC-style polling from Postgres client_knowledge_base."""

import logging
from datetime import UTC, datetime

from embedder.base import AbstractEmbedder
from extractor.schemas import ConditionalFact, QAFact
from store.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)

KBAnyFact = ConditionalFact | QAFact


def map_kb_row_to_fact(row: dict) -> KBAnyFact | None:
    """Map a client_knowledge_base DB row to a typed fact object.

    Returns None for unknown fact_type values so callers can skip them.
    """
    fact_type = row.get("fact_type", "")
    condition = row.get("condition") or ""
    response = row.get("response", "")

    if fact_type == "conditional":
        return ConditionalFact(
            fact_type="conditional",
            content=f"If {condition}, then {response}",
            raw_evidence="",
            confidence=1.0,
            condition=condition,
            response=response,
            exception_note=row.get("exception_note"),
            priority=row.get("priority", 5),
        )

    if fact_type in ("qa", "talking_point", "pricing_override"):
        question = condition if condition else (row.get("title") or "")
        return QAFact(
            fact_type="qa",
            content=response,
            raw_evidence="",
            confidence=1.0,
            question=question,
            answer=response,
        )

    logger.debug("Unknown KB fact_type '%s' for record id=%s; skipping", fact_type, row.get("id"))
    return None


def get_embed_text_for_kb_fact(fact: KBAnyFact) -> str:
    """Return the text to embed for a knowledge-base fact.

    ConditionalFact uses the if/then format to capture both the trigger
    scenario and expected response in one vector, enabling retrieval
    on either end of the condition.
    """
    if isinstance(fact, ConditionalFact):
        return f"conditional: if {fact.condition} then {fact.response}"
    # QAFact: include both question and answer
    return f"qa: {fact.question} {fact.answer}"


def sync_knowledge_base(
    client_id: str,
    rows: list[dict],
    store: QdrantStore,
    embedder: AbstractEmbedder,
) -> dict:
    """Sync a list of KB rows into Qdrant.

    Handles active records (upsert) and inactive records (delete).
    No LLM call is made — rows are embedded directly. KB ingestion
    costs zero LLM tokens.

    Args:
        client_id: The client whose KB records are being synced.
        rows: Raw DB rows from client_knowledge_base.
        store: Qdrant store instance.
        embedder: Embedder for vectorising KB fact text.

    Returns:
        dict with keys: total, updated, deleted, skipped.
    """
    stats = {"total": len(rows), "updated": 0, "deleted": 0, "skipped": 0}

    for row in rows:
        record_id = str(row.get("id", ""))
        is_active = row.get("is_active", True)

        if not is_active:
            store.delete_by_payload(client_id=client_id, kb_record_id=record_id)
            stats["deleted"] += 1
            logger.debug("[%s] Deleted KB record %s", client_id, record_id)
            continue

        fact = map_kb_row_to_fact(row)
        if fact is None:
            stats["skipped"] += 1
            continue

        embed_text = get_embed_text_for_kb_fact(fact)
        vector = embedder.embed(embed_text)

        updated_at: datetime = row.get("updated_at") or datetime.now(tz=UTC)
        content_hash = f"kb:{record_id}:{updated_at.isoformat()}"

        store.upsert_fact(
            client_id=client_id,
            fact=fact,
            vector=vector,
            source_url=f"kb://{client_id}/{record_id}",
            page_type="knowledge_base",
            page_score=5,
            content_hash=content_hash,
            source_type="knowledge_base",
            extra_payload={
                "kb_record_id": record_id,
                "kb_fact_type": row.get("fact_type"),
                "priority": row.get("priority", 5),
            },
        )
        stats["updated"] += 1
        logger.debug("[%s] Upserted KB record %s", client_id, record_id)

    return stats


def fetch_kb_rows_since(
    client_id: str,
    since: datetime,
    db_conn,
) -> list[dict]:
    """Fetch changed KB rows from Postgres using updated_at polling.

    Args:
        client_id: Client to fetch records for.
        since: Fetch rows updated after this timestamp.
        db_conn: psycopg2 connection object.

    Returns:
        List of raw row dicts including inactive records (caller handles deletion).
    """
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, client_id, fact_type, title, condition, response,
                   exception_note, priority, is_active, updated_at, created_by
            FROM client_knowledge_base
            WHERE client_id = %s AND updated_at > %s
            ORDER BY updated_at ASC
            """,
            (client_id, since),
        )
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
