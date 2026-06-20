"""GET /facts/{client_id}/status and /types endpoints."""
from fastapi import APIRouter, Depends

from store.qdrant_store import QdrantStore

router = APIRouter()


def get_store() -> QdrantStore:
    return QdrantStore()


@router.get("/facts/{client_id}/status")
def get_status(client_id: str, store: QdrantStore = Depends(get_store)):
    counts = store.get_fact_counts_by_type(client_id=client_id)
    total = sum(counts.values())
    return {
        "client_id": client_id,
        "total_facts": total,
        "fact_counts": counts,
    }


@router.get("/facts/{client_id}/types")
def get_types(client_id: str, store: QdrantStore = Depends(get_store)):
    counts = store.get_fact_counts_by_type(client_id=client_id)
    return {
        "client_id": client_id,
        "fact_types": [{"fact_type": k, "count": v} for k, v in counts.items()],
    }
