"""Prefect @flow definitions for the client fact pipeline."""
import logging
import os
from urllib.parse import urlparse

from prefect import flow
from prefect.schedules import CronSchedule

from embedder.local_embedder import LocalEmbedder
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
    """End-to-end pipeline: discover → score → crawl → extract → embed → upsert."""
    store = QdrantStore()
    embedder = LocalEmbedder()

    print(f"[{client_id}] Starting pipeline for {base_url}")

    # Stage 1: Discover internal pages
    all_urls = discover_pages(base_url, max_pages=max_pages)
    print(f"[{client_id}] Discovered {len(all_urls)} pages")

    # Stage 2: Score and filter
    scored = score_pages(all_urls, scorer_config=scorer_config)
    print(f"[{client_id}] {len(scored)} pages scored > 0")

    stats = {"pages_checked": 0, "pages_crawled": 0, "facts_upserted": 0, "pages_unchanged": 0}

    for item in scored:
        url = item["url"]
        page_score = item["score"]
        path = urlparse(url).path or "/"

        # Stage 3: Crawl
        page = crawl_page(url)
        stats["pages_checked"] += 1
        if page is None:
            continue

        # Stage 4: Incremental check
        content_hash = check_incremental(
            client_id=client_id, url=url, page=page, store=store
        )
        if content_hash is None:
            stats["pages_unchanged"] += 1
            print(f"[{client_id}] SKIP (unchanged): {url}")
            continue

        stats["pages_crawled"] += 1
        print(f"[{client_id}] CRAWL: {url}")

        # Stage 5: Determine page_type from path
        page_type = _path_to_page_type(path)

        # Stage 6: Extract facts
        facts = extract_facts(
            page=page,
            page_type=page_type,
            page_score=page_score,
            industry=industry,
        )
        print(f"[{client_id}]   {len(facts)} facts extracted from {url}")

        # Stage 7: Embed + upsert
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


@flow(
    name="nightly-recrawl",
    log_prints=True,
)
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
    # Demo: run against mock server
    mock_url = os.environ.get("MOCK_SERVER_URL", "http://localhost:8888")
    run_client_pipeline(
        client_id="demo-dental",
        base_url=f"{mock_url}/dental/",
        industry="dental",
    )
