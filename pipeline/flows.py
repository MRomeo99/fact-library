"""Prefect @flow definitions for the client fact pipeline."""

import logging
import os
from urllib.parse import urlparse

from prefect import flow

from embedder.local_embedder import LocalEmbedder
from ingestion.document_ingestion import ingest_document
from ingestion.kb_ingestion import sync_knowledge_base
from pipeline.tasks import (
    check_incremental,
    crawl_page,
    discover_pages,
    embed_and_upsert,
    extract_facts,
    score_pages,
)
from store.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


@flow(name="client-fact-pipeline", log_prints=True)
def run_client_pipeline(
    client_id: str,
    base_url: str,
    industry: str = "general",
    max_pages: int = 30,
    scorer_config: dict | None = None,
) -> dict:
    """End-to-end website crawl pipeline: discover → score → crawl → extract → embed → upsert."""
    store = QdrantStore()
    embedder = LocalEmbedder()

    print(f"[{client_id}] Starting pipeline for {base_url}")

    all_urls = discover_pages(base_url, max_pages=max_pages)
    print(f"[{client_id}] Discovered {len(all_urls)} pages")

    scored = score_pages(all_urls, scorer_config=scorer_config)
    print(f"[{client_id}] {len(scored)} pages scored > 0")

    stats = {"pages_checked": 0, "pages_crawled": 0, "facts_upserted": 0, "pages_unchanged": 0}

    for item in scored:
        url = item["url"]
        page_score = item["score"]
        path = urlparse(url).path or "/"

        page = crawl_page(url)
        stats["pages_checked"] += 1
        if page is None:
            continue

        content_hash = check_incremental(client_id=client_id, url=url, page=page, store=store)
        if content_hash is None:
            stats["pages_unchanged"] += 1
            print(f"[{client_id}] SKIP (unchanged): {url}")
            continue

        stats["pages_crawled"] += 1
        print(f"[{client_id}] CRAWL: {url}")

        page_type = _path_to_page_type(path)

        facts = extract_facts(
            page=page,
            page_type=page_type,
            page_score=page_score,
            industry=industry,
        )
        print(f"[{client_id}]   {len(facts)} facts extracted from {url}")

        count = embed_and_upsert(
            client_id=client_id,
            facts=facts,
            page=page,
            page_type=page_type,
            page_score=page_score,
            content_hash=content_hash,
            store=store,
            embedder=embedder,
        )
        stats["facts_upserted"] += count

    print(f"[{client_id}] Pipeline complete: {stats}")
    return stats


@flow(name="kb-sync", log_prints=True)
def kb_sync_flow(
    client_id: str,
    rows: list[dict],
) -> dict:
    """Sync knowledge base records into Qdrant.

    In production: fetch rows from Postgres using fetch_kb_rows_since(),
    then pass them here. KB ingestion makes zero LLM calls.

    Args:
        client_id: The client whose KB records to sync.
        rows: Raw DB rows from client_knowledge_base.
    """
    store = QdrantStore()
    embedder = LocalEmbedder()

    print(f"[{client_id}] Syncing {len(rows)} KB records")
    result = sync_knowledge_base(
        client_id=client_id,
        rows=rows,
        store=store,
        embedder=embedder,
    )
    print(f"[{client_id}] KB sync complete: {result}")
    return result


@flow(name="document-ingestion", log_prints=True)
def document_ingestion_flow(
    client_id: str,
    file_path: str,
    document_name: str | None = None,
) -> dict:
    """Ingest a single document (PDF, DOCX, or TXT) into Qdrant.

    Args:
        client_id: Client this document belongs to.
        file_path: Absolute path to the file.
        document_name: Display name; defaults to the file's basename.
    """
    import os

    store = QdrantStore()
    embedder = LocalEmbedder()

    if document_name is None:
        document_name = os.path.basename(file_path)

    print(f"[{client_id}] Ingesting document: {document_name}")
    result = ingest_document(
        client_id=client_id,
        file_path=file_path,
        document_name=document_name,
        store=store,
        embedder=embedder,
    )
    print(f"[{client_id}] Document ingestion complete: {result}")
    return result


@flow(name="nightly-recrawl", log_prints=True)
def nightly_recrawl(clients: list[dict]) -> None:
    """Nightly scheduled recrawl for all registered clients."""
    for client in clients:
        run_client_pipeline(
            client_id=client["client_id"],
            base_url=client["base_url"],
            industry=client.get("industry", "general"),
        )


def _path_to_page_type(path: str) -> str:
    path = path.lower()
    if path in ("/", "/index"):
        return "homepage"
    for segment, ptype in [
        ("service", "service"),
        ("treatment", "service"),
        ("solution", "service"),
        ("pricing", "pricing"),
        ("package", "pricing"),
        ("rate", "pricing"),
        ("about", "about"),
        ("team", "about"),
        ("location", "location"),
        ("service-area", "location"),
        ("faq", "faq"),
        ("help", "faq"),
        ("blog", "blog"),
        ("news", "blog"),
        ("review", "testimonial"),
        ("testimonial", "testimonial"),
        ("contact", "contact"),
    ]:
        if segment in path:
            return ptype
    return "general"


if __name__ == "__main__":
    mock_url = os.environ.get("MOCK_SERVER_URL", "http://localhost:8888")
    run_client_pipeline(
        client_id="demo-dental",
        base_url=f"{mock_url}/dental/",
        industry="dental",
    )
