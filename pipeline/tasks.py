"""Prefect @task definitions for each pipeline stage."""
import logging
import os
from typing import Optional
from urllib.parse import urlparse

from prefect import task
from bs4 import BeautifulSoup

from crawler.base import CrawledPage
from crawler.httpx_crawler import HttpxCrawler
from crawler.page_scorer import PageScorer
from crawler.robots import get_robots_parser, is_allowed
from embedder.base import AbstractEmbedder
from embedder.local_embedder import LocalEmbedder
from extractor.fact_extractor import FactExtractor
from extractor.llm_client import build_llm_client
from extractor.schemas import AnyFact
from pipeline.incremental import ContentHashChecker, compute_content_hash
from store.qdrant_store import QdrantStore

logger = logging.getLogger(__name__)


@task(retries=2, retry_delay_seconds=5)
def discover_pages(base_url: str, max_pages: int = 30) -> list[str]:
    """Crawl the sitemap/homepage and return internal page URLs."""
    crawler = HttpxCrawler(rate_limit_seconds=0.5)
    robots = get_robots_parser(base_url)
    page = crawler.fetch(base_url)
    if page.error:
        return []
    links = crawler.discover_links(base_url, page.html)
    allowed = [l for l in links if is_allowed(l, robots)]
    return allowed[:max_pages]


@task(retries=2, retry_delay_seconds=5)
def score_pages(urls: list[str], scorer_config: Optional[dict] = None) -> list[dict]:
    """Score each URL and return sorted list of {url, score} dicts."""
    scorer = PageScorer(config=scorer_config)
    scored = []
    for url in urls:
        path = urlparse(url).path or "/"
        score = scorer.score_url(path)
        if score > 0:  # skip score-0 pages (legal/privacy)
            scored.append({"url": url, "score": score})
    return sorted(scored, key=lambda x: -x["score"])


@task(retries=2, retry_delay_seconds=10)
def crawl_page(url: str) -> Optional[CrawledPage]:
    """Fetch a single page. Returns None if fetch fails or robots disallows."""
    crawler = HttpxCrawler(rate_limit_seconds=1.5)
    page = crawler.fetch(url)
    if page.error or page.status_code == 0:
        logger.warning("Failed to crawl %s: %s", url, page.error)
        return None
    return page


@task
def check_incremental(
    client_id: str,
    url: str,
    page: CrawledPage,
    store: QdrantStore,
) -> Optional[str]:
    """Return content_hash if page needs re-extraction; None if unchanged."""
    content_hash = compute_content_hash(
        url=url,
        content=page.html,
        etag=page.etag,
        last_modified=page.last_modified,
    )
    checker = ContentHashChecker(store=store)
    if checker.should_crawl(client_id=client_id, url=url, content_hash=content_hash):
        return content_hash
    return None


@task(retries=1)
def extract_facts(
    page: CrawledPage,
    page_type: str,
    page_score: int,
    industry: str,
) -> list[AnyFact]:
    """Extract typed facts from a crawled page via the LLM."""
    soup = BeautifulSoup(page.html, "lxml")
    page_text = soup.get_text(separator="\n", strip=True)
    llm_client = build_llm_client()
    extractor = FactExtractor(llm_client=llm_client)
    return extractor.extract(
        page_text=page_text,
        page_url=page.url,
        page_type=page_type,
        page_score=page_score,
        industry=industry,
    )


@task
def embed_and_upsert(
    client_id: str,
    facts: list[AnyFact],
    page: CrawledPage,
    page_type: str,
    page_score: int,
    content_hash: str,
    store: QdrantStore,
    embedder: AbstractEmbedder,
) -> int:
    """Embed facts and upsert into Qdrant. Returns count of upserted facts."""
    if not facts:
        return 0
    # Delete stale facts for this URL first
    store.delete_facts_for_url(client_id=client_id, source_url=page.url)
    count = 0
    for fact in facts:
        embed_text = f"{fact.fact_type}: {fact.content}"
        vector = embedder.embed(embed_text)
        store.upsert_fact(
            client_id=client_id,
            fact=fact,
            vector=vector,
            source_url=page.url,
            page_type=page_type,
            page_score=page_score,
            content_hash=content_hash,
        )
        count += 1
    return count
