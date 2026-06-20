<!-- Badges -->
![CI](https://github.com/your-org/client-fact-library/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Qdrant](https://img.shields.io/badge/vector_db-Qdrant-red)
![Portkey](https://img.shields.io/badge/llm_gateway-Portkey-purple)

# Client Fact Library

> Website crawler + LLM fact extractor for local businesses — Qdrant · Portkey · Gemini · FastAPI · Prefect

An AI data pipeline that crawls local business websites, extracts **typed, structured facts**
via LLM (routed through Portkey), and stores them in Qdrant for retrieval by AI chat and voice agents.

---

## Architecture

```
Website
  ↓
[Crawler]  httpx (static) / Playwright (JS-rendered)
  ↓        robots.txt enforcement · 1.5s rate limit
[Page Scorer]  URL patterns + HTML signals → importance 0–5
  ↓
[Incremental Check]  sha256(url + etag) → skip unchanged pages
  ↓
[LLM Extractor]  Portkey → Gemini 2.5 Flash / GPT-4o-mini
  ↓              Returns typed Pydantic fact objects
[Embedder]  sentence-transformers/all-MiniLM-L6-v2 (384-dim, local)
  ↓
[Qdrant]  1 fact = 1 vector point · fact_type indexed for filtering
  ↓
[FastAPI]  GET /facts/{client_id}?q=...&fact_type=pricing
  ↓
[AI Agent]  precise, typed answers about any local business
```

---

## What This Demonstrates

- **RAG pipeline design** — typed fact extraction vs raw text chunking; incremental re-crawl
- **LLM gateway integration** — Portkey for model routing, fallback, and cost observability
- **Typed vector retrieval** — `fact_type` payload filter on Qdrant for structured agent queries
- **Agent context serving** — FastAPI retrieval API with `fact_age_days` for freshness checks
- **Incremental data pipelines** — content hash comparison to skip unchanged pages
- **Structured LLM output** — Pydantic validation layer, confidence threshold filtering
- **Production observability** — Prefect flow UI, Portkey LLM traces, Qdrant payload indexing

For a deep-dive on every choice — alternatives considered, real tradeoffs, and what changes at scale — see **[docs/design-decisions.md](./docs/design-decisions.md)**.

---

## Quick Start

```bash
# 1. Clone and install
git clone https://github.com/your-org/client-fact-library
cd client-fact-library
pip install -e ".[dev]"

# 2. Configure (see SETUP.md for both Portkey and direct mode)
cp .env.example .env
# edit .env with your API keys

# 3. Start infrastructure
make up            # Qdrant on :6333, Prefect server on :4200

# 4. Start mock site server (new terminal)
make mock-server   # local business sites on :8888

# 5. Run the pipeline
make crawl         # crawls dental mock site, extracts facts

# 6. Start the serving API
make serve         # FastAPI on :8000

# 7. Query the facts
curl "http://localhost:8000/facts/demo-dental?q=what+are+your+prices&fact_type=pricing&limit=3"
```

**Sample response:**

```json
{
  "client_id": "demo-dental",
  "query": "what are your prices",
  "results": [
    {
      "fact_id": "a3f1c2d4...",
      "fact_type": "pricing",
      "content": "Professional teeth whitening: $299 per session. Take-home kit: $199.",
      "confidence": 0.94,
      "source_url": "http://localhost:8888/dental/pricing/",
      "page_type": "pricing",
      "extracted_at": "2025-06-18T03:00:00Z",
      "fact_age_days": 0,
      "score": 0.91
    }
  ],
  "total": 1
}
```

---

## Page Importance Scoring

The pipeline scores each URL before crawling — not all pages are worth extracting.

| Page Type         | Score | URL Patterns                                |
|-------------------|-------|---------------------------------------------|
| Service / product | 5     | `/services/`, `/treatments/`, `/solutions/` |
| Homepage          | 4     | `/`, `/index`                               |
| About / team      | 4     | `/about`, `/team`, `/our-story`             |
| Pricing           | 4     | `/pricing`, `/packages`, `/rates`           |
| Locations         | 3     | `/locations`, `/service-area`               |
| FAQ               | 3     | `/faq`, `/help`, `/questions`               |
| Blog / articles   | 2     | `/blog`, `/news`, date in URL               |
| Testimonials      | 2     | `/reviews`, `/testimonials`                 |
| Contact           | 1     | `/contact`, `/get-in-touch`                 |
| Legal / privacy   | 0     | `/privacy`, `/terms` — **skip entirely**    |

**Scoring modifiers** (additive, capped at 5):

| Signal                          | +Score |
|---------------------------------|--------|
| JSON-LD structured data present | +1.0   |
| Word count > 300                | +0.5   |
| H2/H3 count > 3                 | +0.5   |
| Internal inbound links > 5      | +0.5   |
| Contains price signals ($, fee) | +0.5   |

Configurable per client via YAML: `config/scorers/dental_practice.yml`. See `docs/page_scoring_spec.md`.

---

## Fact Taxonomy

| Fact Type     | What It Captures                                   | Example                                          |
|---------------|----------------------------------------------------|--------------------------------------------------|
| `identity`    | Business name, tagline, founding year              | "Sunrise Dental, family practice since 2005"     |
| `service`     | Services/products with descriptions                | "Invisalign, from $3,800 for minor cases"        |
| `pricing`     | Prices, rates, fees with numeric values            | "$299/session, $150 consultation fee"            |
| `location`    | Address, city, state, service area                 | "Serving Austin, Round Rock, Cedar Park"         |
| `credibility` | Awards, certifications, years of experience        | "Board Certified, Super Lawyers 2024"            |
| `operational` | Hours, booking methods, languages, emergency       | "Mon–Fri 8am–6pm, same-day emergency available"  |

---

## Portkey Setup

See [SETUP.md](./SETUP.md) for complete step-by-step instructions for both modes.

**Why Portkey?** Model selection lives in the Portkey dashboard — not in code. Switching
from Gemini 2.5 Flash to GPT-4o-mini requires zero code changes. All LLM calls are
logged with latency, token count, and cost in Portkey's observability dashboard.
Automatic fallback: if Gemini is slow, Portkey routes to GPT-4o-mini automatically.

---

## Retrieval API

```
GET  /facts/{client_id}?q=...&fact_type=pricing&limit=5
POST /facts/{client_id}/crawl
GET  /facts/{client_id}/status
GET  /facts/{client_id}/types
GET  /health
```

**Target latency:** p99 < 100ms (Qdrant local + MiniLM local embedder)

---

## Incremental Re-crawl

The pipeline is incremental — it only re-processes pages whose content changed.

1. Before crawling, compute: `sha256(url + etag)` (or `sha256(url + content)` as fallback)
2. Query Qdrant: does any fact for this client + URL have this content hash?
3. If yes → skip. If no → crawl, extract, delete stale facts, upsert fresh facts.
4. API responses include `fact_age_days`: `(now - extracted_at).days`

The Prefect nightly flow (3 AM) logs: pages checked, pages re-crawled, facts updated, facts unchanged.

---

## Production Swap Path

| Component | Development | Production (zero code changes) |
|-----------|-------------|-------------------------------|
| Qdrant | Local Docker | Qdrant Cloud (change `QDRANT_URL`) |
| Prefect | Local server | Prefect Cloud (`prefect cloud login`) |
| Embedder | Local (free) | OpenAI `text-embedding-3-small` (`EMBEDDING_MODE=openai`) |
| LLM | Portkey/direct | Portkey with fallback config |

---

## Project Structure

```
client-fact-library/
├── crawler/          httpx + Playwright crawlers, robots.txt, page scorer
├── extractor/        LLM client factory, Pydantic schemas, fact extractor
├── embedder/         Local (MiniLM) and OpenAI embedder implementations
├── store/            Qdrant collection config and store operations
├── pipeline/         Prefect flows, tasks, incremental hash logic
├── serving/          FastAPI app + routers (facts, crawl, status)
├── seeds/            Mock site server + HTML templates (dental, home services, law)
├── tests/            pytest test suite (unit + integration)
├── docs/             Architecture, page scoring spec, 4 ADRs, design-decisions
├── .github/          CI workflow (lint, test, Docker build, smoke test)
├── docker-compose.yml
├── Makefile
├── SETUP.md          Complete Portkey + direct mode setup guide
├── docs/design-decisions.md  Senior ADE perspective: alternatives, tradeoffs, what changes at scale
└── pyproject.toml
```

---

## License

MIT — see [LICENSE](./LICENSE)
