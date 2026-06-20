# Architecture — Client Fact Library

## Overview

Client Fact Library is a production-grade AI data pipeline that transforms local business
websites into a typed, queryable fact store for AI agents.

```
Website
  │
  ▼
[Crawler] (httpx / Playwright)
  │   robots.txt enforcement
  │   rate limiting (1.5s default)
  │
  ▼
[Page Scorer] (page_scorer.py)
  │   Assigns importance 0–5
  │   Skips score-0 pages (legal/privacy)
  │
  ▼
[Incremental Check] (incremental.py)
  │   sha256(url + etag/content)
  │   Skips unchanged pages
  │
  ▼
[LLM Extractor] (fact_extractor.py)
  │   Portkey gateway → Gemini 2.5 Flash / GPT-4o-mini
  │   Returns typed Pydantic fact objects
  │   Filters confidence < 0.5
  │
  ▼
[Embedder] (local_embedder.py)
  │   sentence-transformers/all-MiniLM-L6-v2
  │   384-dim vectors
  │   Text: "fact_type: content"
  │
  ▼
[Qdrant Store] (qdrant_store.py)
  │   Upserts one point per fact
  │   Indexed payload: client_id, fact_type, source_url, confidence
  │
  ▼
[FastAPI Serving] (serving/main.py)
  │   GET /facts/{client_id}?q=...&fact_type=...
  │   POST /facts/{client_id}/crawl
  │   GET /facts/{client_id}/status
  │
  ▼
[AI Agent]
```

## Component Responsibilities

### Crawler (`crawler/`)

Two implementations behind a common `AbstractCrawler` interface:

- `HttpxCrawler` — default. Uses `httpx` for static HTML pages (90% of local business sites).
- `PlaywrightCrawler` — opt-in for JS-rendered SPAs. Controlled by per-client config.

Both crawlers:
1. Fetch `robots.txt` before any crawl and cache it per domain
2. Respect `Disallow` directives
3. Enforce rate limiting (default: 1.5s between requests)
4. Return `CrawledPage` with `etag` and `last-modified` headers for incremental checks

### Page Scorer (`crawler/page_scorer.py`)

Assigns an importance score (0–5) to each URL using:
1. URL path pattern matching (base score)
2. HTML content analysis (modifiers: JSON-LD, word count, headings, price signals)
3. Link graph analysis (inbound link count modifier)

Full specification in `docs/page_scoring_spec.md`.

### Incremental Logic (`pipeline/incremental.py`)

Before re-crawling a page, compute:
```
content_hash = sha256(url + etag)  # if etag available
             = sha256(url + last-modified)  # if last-modified available
             = sha256(url + page_content)  # fallback
```

Query Qdrant for any existing fact with matching `client_id`, `source_url`, and
`content_hash`. If found: skip extraction. If not found: re-extract, delete stale facts
for this URL, upsert fresh facts.

### LLM Extractor (`extractor/`)

1. Renders the Jinja2 user prompt with page context
2. Calls LLM via Portkey (or direct mode)
3. Parses JSON response into typed Pydantic fact objects
4. Discards facts with `confidence < 0.5`
5. Returns up to N facts per page

### Qdrant Store (`store/`)

One Qdrant collection: `client_facts`. Each point:
- **Vector:** 384-dim cosine embedding of `"fact_type: content"`
- **Payload:** full fact metadata (client_id, fact_type, content, confidence, source_url, ...)

Payload fields indexed for filtering: `client_id`, `fact_type`, `page_type`, `confidence`,
`content_hash`, `source_url`.

### FastAPI Serving (`serving/`)

Three router groups:
- `facts.py` — semantic search with optional `fact_type` filter
- `crawl.py` — trigger on-demand crawl (runs in background task)
- `status.py` — fact counts, crawl status, fact type distribution

## Data Flow (incremental recrawl)

1. Prefect nightly flow runs at 3 AM
2. For each registered client: `discover_pages → score_pages`
3. For each page above score threshold:
   a. Fetch page headers (HEAD request to get etag/last-modified)
   b. Compute `content_hash`
   c. Query Qdrant: does this hash exist?
   d. If yes → skip (update `checked_at` only)
   e. If no → full crawl → extract → embed → upsert
4. Log stats: pages checked, pages recrawled, facts updated, facts unchanged
