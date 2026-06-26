"""POST /facts/{client_id}/crawl — trigger an on-demand crawl."""

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from store.qdrant_store import QdrantStore

router = APIRouter()


def get_store() -> QdrantStore:
    return QdrantStore()


class CrawlRequest(BaseModel):
    base_url: str
    industry: str = "general"
    max_pages: int = 30


@router.post("/facts/{client_id}/crawl")
def trigger_crawl(
    client_id: str,
    body: CrawlRequest,
    background_tasks: BackgroundTasks,
    store: QdrantStore = Depends(get_store),
):
    background_tasks.add_task(
        _run_crawl,
        client_id=client_id,
        base_url=body.base_url,
        industry=body.industry,
        max_pages=body.max_pages,
    )
    return {"status": "accepted", "client_id": client_id, "base_url": body.base_url}


def _run_crawl(client_id: str, base_url: str, industry: str, max_pages: int) -> None:
    from pipeline.flows import run_client_pipeline

    run_client_pipeline(
        client_id=client_id,
        base_url=base_url,
        industry=industry,
        max_pages=max_pages,
    )
