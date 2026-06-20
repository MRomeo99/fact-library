# CLAUDE.md — Client Fact Library

This file is the source of truth for AI assistants working on this project.
Read it fully before writing any code, creating any file, or suggesting any
change. Every architectural decision, stack choice, integration pattern, and
quality bar is captured here.

---

## What this project is

**Client Fact Library** is a production-grade AI data pipeline that crawls
client websites, extracts structured facts using an LLM, and stores them in a
vector database — purpose-built for retrieval by AI chat and voice agents.

The core problem it solves: an AI agent answering questions on behalf of a
local business ("What are your prices?", "Do you serve the Dallas area?",
"What awards have you won?") needs fast, reliable, typed facts about that
business. This pipeline is the data layer that makes that possible.

**What makes it different from a generic RAG pipeline:**
- Pages are ranked by business importance before crawling — not all pages are
  equal
- Facts are extracted as typed, structured objects — not raw text chunks
- Each fact carries metadata: `fact_type`, `confidence`, `source_url`,
  `page_type`, `content_hash`, `extracted_at`
- Retrieval is filtered by fact type, enabling precise agent queries
- The pipeline is incremental — only re-crawls pages whose content changed
- LLM routing is handled by Portkey — model selection happens in the gateway,
  not in code

**Resume signal:** This project demonstrates AI data engineering at its most
current — RAG pipeline design, vector DB operations, LLM gateway integration,
incremental crawling, structured extraction, agent-ready API design, and
production observability. It maps directly to "AI-powered experiences",
"data access patterns for AI agents", and "trusted data layer" language in
senior AI data engineering JDs.

---

## Domain

**Local-business marketing analytics** — same fictional platform as
beacon-lakehouse. Clients are local businesses (law firms, dental practices,
home services, med spas, auto shops). Their websites are the data source.

The Fact Library is the **unstructured complement** to beacon-lakehouse's
structured analytical layer. Together they form a complete AI data platform:
- beacon-lakehouse: structured operational data (leads, spend, appointments)
- client-fact-library: unstructured website facts (what they do, where, prices)

All demo/test crawls use publicly accessible websites or a local mock server
(`seeds/mock_site_server.py`) that generates realistic local business pages.
Never crawl real client websites in tests or CI.

---

## Stack — every choice is deliberate

### Vector database — Qdrant (native, primary)
- **Why:** Purpose-built vector DB, Docker-native, excellent Python client,
  payload filtering enables fact-type queries that pgvector can't match
  ergonomically. Named collections per entity type. Strong resume keyword in
  AI engineering.
- **Configuration:** Runs as a Docker service. All operations use the official
  `qdrant-client` Python library. Named collection: `client_facts`.
- **Collection schema:**
  ```python
  vectors_config=VectorParams(size=384, distance=Distance.COSINE)
  # payload fields indexed for filtering:
  # client_id (keyword), fact_type (keyword), page_type (keyword),
  # confidence (float), extracted_at (datetime), content_hash (keyword)
  ```
- **Swap path to prod:** Qdrant Cloud (managed). Change one env var
  (`QDRANT_URL`). Client code is identical.
- **Do not** suggest pgvector or Chroma as defaults. Qdrant is the primary.

### LLM gateway — Portkey (required, not optional)
- **Why:** Portkey sits between this pipeline and any LLM provider. Model
  selection, routing, fallbacks, and cost tracking are configured in Portkey —
  not hardcoded in application code. This is the correct production pattern
  and a strong differentiator in the portfolio.
- **Two operating modes** (see `SETUP.md` for full instructions):
  1. **Portkey mode (default, recommended):** User creates a Portkey account,
     stores their provider API keys as Portkey virtual keys, creates a Config
     slug that routes to their chosen model. The application only ever sees a
     `PORTKEY_API_KEY` and a `PORTKEY_CONFIG` slug. Model choice lives in
     Portkey's dashboard.
  2. **Direct mode (no Portkey account):** User sets `LLM_MODE=direct` and
     provides a provider API key directly (`OPENAI_API_KEY` or
     `GOOGLE_API_KEY`). Code routes through a thin adapter that mirrors the
     Portkey SDK interface. Less observability, but zero account requirements.
- **Supported models (document both in SETUP.md):**
  - `gemini-2.5-flash` via Google AI Studio key (recommended default —
    fast, cheap, excellent at structured extraction)
  - `gpt-4o-mini` via OpenAI key (well-known, reliable fallback)
- **Portkey SDK pattern:**
  ```python
  from portkey_ai import Portkey

  client = Portkey(
      api_key=os.environ["PORTKEY_API_KEY"],
      config=os.environ["PORTKEY_CONFIG"],  # slug like "cf-abc123"
  )
  response = client.chat.completions.create(
      messages=[{"role": "user", "content": prompt}],
      model="gemini-2.5-flash",  # overridden by Portkey Config if set
  )
  ```
- **Direct mode pattern** (same interface, different client):
  ```python
  # extractor/llm_client.py resolves to the right client based on LLM_MODE
  client = build_llm_client()  # returns Portkey or DirectLLMClient
  # rest of code is identical regardless of mode
  ```
- **Do not** hardcode model names anywhere outside `extractor/llm_client.py`.
  Model selection belongs in Portkey config or the env var `LLM_MODEL_DIRECT`.

### Embedding model — sentence-transformers (local, zero-cost)
- **Why:** No API key required. Runs locally. `all-MiniLM-L6-v2` produces
  384-dim vectors, fast enough for a pipeline, good retrieval quality for
  business facts.
- **Model:** `sentence-transformers/all-MiniLM-L6-v2`
- **Swap path to prod:** Set `EMBEDDING_MODE=openai` and `OPENAI_API_KEY` to
  use `text-embedding-3-small` (1536-dim). The Qdrant collection must be
  recreated when switching embedding models — document this clearly.
- **Do not** use the OpenAI embeddings API as the default. Local embeddings
  keep the project free to run end-to-end.

### Crawler — httpx + BeautifulSoup + Playwright
- **Why:** Two-tier approach. `httpx` handles the 90% of local business sites
  that are static HTML — fast, lightweight, no browser overhead. Playwright
  handles JS-rendered SPAs as an opt-in fallback, controlled by per-client
  config.
- **robots.txt:** ALWAYS fetch and respect `robots.txt` before crawling any
  domain. This is non-negotiable for a public repo. Use `robotparser` from
  the Python standard library.
- **Rate limiting:** Configurable delay between requests (default: 1.5s).
  User-agent string: `ClientFactLibrary/1.0 (+https://github.com/{REPO})`.
- **Swap path to prod:** Scrapy for large-scale multi-client crawls. The
  crawler interface is abstracted behind `crawler/base.py` — swap the
  implementation, not the API.

### Orchestration — Prefect
- **Why:** Lighter than Dagster for a task-based pipeline. Flow → tasks maps
  naturally onto: discover → score → crawl → extract → embed → upsert. Built-
  in scheduling, retries, and observability. Runs locally with `prefect server
  start`. Consistent with the portfolio's Python-native tooling direction.
- **Required Prefect features to use:**
  - `@flow` for the top-level pipeline per client
  - `@task` for each pipeline stage with `retries=2`
  - `@flow(schedule=CronSchedule("0 3 * * *"))` for nightly re-crawl
  - Prefect UI screenshot in README showing a completed flow run
- **Swap path to prod:** Prefect Cloud (managed). Same code, different server.
  Or Dagster for portfolio consistency with beacon-lakehouse — note in ADR.

### Serving — FastAPI
- **Why:** AI-agent-ready retrieval endpoint. Semantic search over Qdrant with
  optional `fact_type` filter. Returns ranked facts with full metadata.
- **Required endpoints:**
  ```
  GET  /facts/{client_id}?q=...&fact_type=...&limit=5
  POST /facts/{client_id}/crawl           # trigger on-demand crawl
  GET  /facts/{client_id}/status          # crawl status, fact counts, staleness
  GET  /facts/{client_id}/types           # list fact types with counts
  ```
- **Response shape for** `GET /facts/{client_id}`:
  ```json
  {
    "client_id": "abc123",
    "query": "what are your prices",
    "results": [
      {
        "fact_id": "uuid",
        "fact_type": "pricing",
        "content": "Initial consultation is $150. Monthly retainers start at $500.",
        "confidence": 0.92,
        "source_url": "https://example.com/pricing",
        "page_type": "pricing",
        "extracted_at": "2025-06-01T03:00:00Z",
        "fact_age_days": 17,
        "score": 0.87
      }
    ],
    "total": 1
  }
  ```
- **Target retrieval latency:** p99 < 100ms (Qdrant local + MiniLM).
  Document measured latency in README.

### CI/CD — GitHub Actions
- **Required workflow steps:**
  1. `ruff` lint + `black` check
  2. `pytest` unit tests (mock crawler, mock LLM, Qdrant test collection)
  3. Docker build
  4. Integration smoke test against mock site server
- Mock all external services in CI — no real crawls, no real LLM calls, no
  real Qdrant in CI (use `qdrant-client` in-memory mode).

---

## File structure — do not deviate

```
client-fact-library/
├── crawler/
│   ├── base.py                   # AbstractCrawler interface
│   ├── httpx_crawler.py          # default static crawler
│   ├── playwright_crawler.py     # JS-rendered fallback
│   ├── robots.py                 # robots.txt enforcement
│   └── page_scorer.py            # importance scoring logic
├── extractor/
│   ├── llm_client.py             # Portkey/direct client factory
│   ├── fact_extractor.py         # LLM-based structured extraction
│   ├── prompts/
│   │   ├── extraction_system.txt # system prompt for fact extraction
│   │   └── extraction_user.jinja # user prompt template (Jinja2)
│   └── schemas.py                # Pydantic models for each fact type
├── embedder/
│   ├── base.py                   # AbstractEmbedder interface
│   ├── local_embedder.py         # sentence-transformers
│   └── openai_embedder.py        # OpenAI swap
├── store/
│   ├── qdrant_store.py           # all Qdrant operations
│   └── collection_config.py      # collection schema definition
├── pipeline/
│   ├── flows.py                  # Prefect @flow definitions
│   ├── tasks.py                  # Prefect @task definitions
│   └── incremental.py            # content hash comparison logic
├── serving/
│   ├── main.py                   # FastAPI app
│   └── routers/
│       ├── facts.py              # GET /facts/{client_id}
│       ├── crawl.py              # POST /facts/{client_id}/crawl
│       └── status.py             # GET /facts/{client_id}/status
├── seeds/
│   ├── mock_site_server.py       # FastAPI server serving fake business pages
│   └── mock_sites/               # HTML templates per business type
│       ├── law_firm.html
│       ├── dental_practice.html
│       └── home_services.html
├── tests/
│   ├── test_scorer.py
│   ├── test_extractor.py
│   ├── test_embedder.py
│   ├── test_store.py
│   ├── test_pipeline.py
│   └── test_serving.py
├── docs/
│   ├── architecture.md
│   ├── page_scoring_spec.md      # full scoring model documentation
│   └── adr/
│       ├── 001-qdrant-over-pgvector.md
│       ├── 002-portkey-for-llm-routing.md
│       ├── 003-fact-typed-chunks.md
│       └── 004-prefect-over-dagster.md
├── notebooks/
│   └── demo.ipynb                # Colab-runnable end-to-end demo
├── .github/
│   └── workflows/
│       └── ci.yml
├── docker-compose.yml
├── Makefile
├── pyproject.toml
├── .env.example
├── SETUP.md                      # critical — Portkey setup instructions
├── CLAUDE.md                     # this file
└── README.md
```

---

## Page importance scoring model

This is the IP of the project. It is documented fully in
`docs/page_scoring_spec.md` and summarized here. All scores are integers 0–5.

### Page type scores (by URL pattern)

| Page type         | Score | URL patterns                                    |
|-------------------|-------|-------------------------------------------------|
| Service / product | 5     | `/services/`, `/treatments/`, `/solutions/`     |
| Homepage          | 4     | `/`, `/index`                                   |
| About / team      | 4     | `/about`, `/team`, `/our-story`                 |
| Pricing           | 4     | `/pricing`, `/packages`, `/rates`               |
| Locations         | 3     | `/locations`, `/service-area`, city names in URL|
| FAQ               | 3     | `/faq`, `/help`, `/questions`                   |
| Blog / articles   | 2     | `/blog`, `/news`, date in URL                   |
| Testimonials      | 2     | `/reviews`, `/testimonials`                     |
| Contact           | 1     | `/contact`, `/get-in-touch`                     |
| Legal / privacy   | 0     | `/privacy`, `/terms`, `/legal` — skip entirely  |

### Scoring modifiers (additive, capped at 5)

| Signal                          | Modifier |
|---------------------------------|----------|
| JSON-LD structured data present | +1       |
| Word count > 300                | +0.5     |
| H2/H3 count > 3                 | +0.5     |
| Internal inbound link count > 5 | +0.5     |
| Contains price signals ($, fee) | +0.5     |

### Configuration

The scoring table is defined in `crawler/page_scorer.py` and is overridable
per-client via a YAML config file. Industry-specific overrides are supported:
a dental practice might score `/treatments/` at 5 while a law firm scores
`/practice-areas/` at 5. The config format:

```yaml
# config/scorers/dental_practice.yml
page_type_overrides:
  - pattern: "/treatments/"
    score: 5
  - pattern: "/new-patients/"
    score: 4
top_x_pages: 15
```

---

## Fact taxonomy — Pydantic schemas required

Every fact type has a Pydantic model in `extractor/schemas.py`. The LLM
extraction prompt instructs the model to return a list of these objects as JSON.

```python
class FactBase(BaseModel):
    fact_type: str
    content: str                  # human-readable fact statement
    confidence: float             # 0.0–1.0, LLM self-assessed
    raw_evidence: str             # verbatim text from page that supports this fact

class IdentityFact(FactBase):
    fact_type: Literal["identity"]
    # business_name, tagline, founded_year, ownership_type

class ServiceFact(FactBase):
    fact_type: Literal["service"]
    service_name: str
    # description, target_customer, industry

class PricingFact(FactBase):
    fact_type: Literal["pricing"]
    price_min: float | None
    price_max: float | None
    price_unit: str | None        # "per session", "per month", "starting at"

class LocationFact(FactBase):
    fact_type: Literal["location"]
    address: str | None
    city: str | None
    state: str | None
    service_area: list[str]

class CredibilityFact(FactBase):
    fact_type: Literal["credibility"]
    # awards, certifications, years_experience, associations

class OperationalFact(FactBase):
    fact_type: Literal["operational"]
    # hours, booking_method, languages, emergency_available
```

### Chunking strategy — fact-based, not character-based

**One fact object = one Qdrant point.** This is the core architectural
differentiator. Do not chunk by character count.

Each Qdrant point payload:
```python
{
    "client_id": str,
    "fact_id": str,               # deterministic: sha256(client_id + fact_type + content)
    "fact_type": str,             # indexed keyword field
    "content": str,               # the text that gets embedded
    "confidence": float,          # indexed float field
    "source_url": str,
    "page_type": str,             # indexed keyword field
    "page_score": int,
    "content_hash": str,          # hash of source page — used for incremental updates
    "extracted_at": datetime,
    "raw_evidence": str,
}
```

The embedded text is: `f"{fact_type}: {content}"` — the type prefix improves
retrieval accuracy for typed queries significantly.

---

## Portkey integration — complete specification

### How Portkey works in this project

Portkey acts as a gateway between this pipeline and the LLM provider. The
application code never calls OpenAI or Google directly — it calls Portkey,
which routes to the configured model. This means:

1. Model selection is a Portkey dashboard concern, not a code concern
2. Users can switch between Gemini 2.5 Flash and GPT-4o-mini by changing a
   Portkey config — no code changes, no redeployment
3. All LLM calls are logged, traced, and cost-tracked in Portkey's dashboard
4. Fallback logic (e.g. fall back to GPT-4o-mini if Gemini is slow) is
   configured in Portkey, not in application code

### Required env vars

```bash
# Portkey mode (LLM_MODE=portkey, default)
PORTKEY_API_KEY=pk-...            # from portkey.ai dashboard
PORTKEY_CONFIG=cf-...             # config slug from portkey.ai dashboard

# Direct mode (LLM_MODE=direct)
LLM_MODE=direct
LLM_PROVIDER=google               # or "openai"
LLM_MODEL_DIRECT=gemini-2.5-flash # or "gpt-4o-mini"
GOOGLE_API_KEY=AIza...            # if LLM_PROVIDER=google
OPENAI_API_KEY=sk-...             # if LLM_PROVIDER=openai

# Embeddings (always local unless overridden)
EMBEDDING_MODE=local              # or "openai"
OPENAI_API_KEY=sk-...             # only needed if EMBEDDING_MODE=openai

# Qdrant
QDRANT_URL=http://localhost:6333  # local Docker default
QDRANT_API_KEY=                   # empty for local, set for Qdrant Cloud
```

### `extractor/llm_client.py` — the factory pattern

```python
def build_llm_client():
    """
    Returns a client with a .chat.completions.create() interface
    regardless of LLM_MODE. All extraction code calls this function
    and never constructs a client directly.
    """
    mode = os.environ.get("LLM_MODE", "portkey")
    if mode == "portkey":
        return Portkey(
            api_key=os.environ["PORTKEY_API_KEY"],
            config=os.environ["PORTKEY_CONFIG"],
        )
    elif mode == "direct":
        return _build_direct_client()
    else:
        raise ValueError(f"Unknown LLM_MODE: {mode}")
```

The direct client wraps the provider SDK in an OpenAI-compatible interface so
the rest of the codebase is unaware of which mode is active.

### Portkey Config slug setup (documented in SETUP.md)

Users create a Config in the Portkey dashboard that looks like this:

```json
{
  "strategy": { "mode": "fallback" },
  "targets": [
    {
      "virtual_key": "google-virtual-key-slug",
      "override_params": { "model": "gemini-2.5-flash" }
    },
    {
      "virtual_key": "openai-virtual-key-slug",
      "override_params": { "model": "gpt-4o-mini" }
    }
  ]
}
```

This config: tries Gemini 2.5 Flash first, falls back to GPT-4o-mini
automatically. Users paste the resulting config slug into their `.env` as
`PORTKEY_CONFIG=cf-abc123`. The application never knows which model ran.

---

## Incremental crawl logic

This is what makes the pipeline production-grade rather than a one-shot script.

1. Before crawling a page, compute `content_hash = sha256(url + etag_or_last_modified)`
2. Check if this hash exists in Qdrant payload for this client's facts
3. If hash matches: skip extraction, update `checked_at` timestamp only
4. If hash differs or no record: crawl, extract, embed, upsert all facts for
   this page (delete old facts for the page first by filtering on `source_url`)
5. Surface `fact_age_days` in API responses: `(now - extracted_at).days`

The Prefect flow logs: pages checked, pages re-crawled, facts updated, facts
unchanged. This data appears in the Prefect UI and in the `/status` endpoint.

---

## LLM extraction prompt design

The system prompt lives in `extractor/prompts/extraction_system.txt`. It must:

1. Instruct the model to return **only valid JSON** — no preamble, no
   markdown fences, no explanation
2. Define the exact output schema (list of fact objects)
3. Instruct the model to set `confidence` between 0.0–1.0 based on how
   clearly the page states the fact (not how accurate the fact seems)
4. Instruct the model to include `raw_evidence` — the verbatim text that
   supports each fact (critical for debugging and human review)
5. Tell the model to skip facts it cannot find — an empty list is valid
6. Tell the model to prefer specific facts over vague ones — "prices start at
   $150" is better than "competitive pricing"

The user prompt template (`extraction_user.jinja`) includes:
- The page URL and page type (sets context)
- The page importance score (instructs the model to be more thorough on
  high-scoring pages)
- The cleaned page text (stripped HTML, markdown format)
- The client's industry (from client config — helps the model know what
  "service" means for this business type)

After the LLM call, the response is parsed with Pydantic. Facts below
`confidence < 0.5` are discarded. Pydantic validation errors are logged and
the fact is skipped — never raise on a bad LLM response.

---

## Mock site server (for tests and demos)

`seeds/mock_site_server.py` is a FastAPI server that serves realistic fake
local business websites at `http://localhost:8888`. It generates:

- A dental practice site with services, pricing, about, FAQ pages
- A home services company site with service areas, testimonials, contact
- A law firm site with practice areas, team bios, case results

This server is the only crawl target used in tests and CI. All test fixtures
use `http://localhost:8888/dental/` etc. Never use real URLs in tests.

The mock server starts with `make mock-server`. CI starts it as a background
service before running integration tests.

---

## Architecture Decision Records

**ADR 001 — Qdrant over pgvector**
Context: needed a vector DB that enables typed, filtered fact retrieval.
Decision: Qdrant. Named collections, payload indexing, and the filter API make
`fact_type` queries first-class operations. pgvector requires full-text or
JSON operator workarounds for the same result.
Tradeoff: pgvector runs in the same Postgres instance as other data (no extra
service). Qdrant is a separate Docker container.
Swap path: Qdrant Cloud — change `QDRANT_URL` and `QDRANT_API_KEY`. Zero code
changes.

**ADR 002 — Portkey for LLM routing**
Context: needed model selection to be a configuration concern, not a code
concern. Two target models (Gemini 2.5 Flash, GPT-4o-mini) with fallback.
Decision: Portkey gateway with virtual keys and a Config slug. Application code
calls Portkey; Portkey calls the provider.
Tradeoff: adds a Portkey account dependency in production mode. Direct mode
removes this but loses observability and fallback routing.
Swap path: replace `Portkey(config=slug)` with `Portkey(provider=...,
Authorization=...)` for headerless direct calls. Or use LiteLLM for a
self-hosted gateway equivalent.

**ADR 003 — Fact-typed chunks over character-count chunks**
Context: needed retrieval that supports "find all pricing facts" or "find all
location facts" — not just semantic similarity alone.
Decision: one Pydantic fact object = one Qdrant point with `fact_type` as an
indexed payload field. Retrieval uses vector similarity + payload filter.
Tradeoff: requires a structured LLM extraction step. Character-count chunking
is simpler and model-agnostic. Fact-typed chunking can produce sparse results
if the LLM extraction quality is low — mitigated by the `raw_evidence` field
enabling human review.

**ADR 004 — Prefect over Dagster**
Context: needed an orchestrator for a task-based crawl pipeline.
Decision: Prefect. `@flow` / `@task` decorator pattern maps naturally onto the
pipeline stages. Lighter than Dagster for this use case. Local server starts
with one command.
Tradeoff: beacon-lakehouse uses Dagster — a visitor exploring both portfolio
projects sees two different orchestrators. This is intentional: it demonstrates
familiarity with both, and the ADR explains the choice rationale per use case.

---

## Makefile — required targets

```makefile
make up           # docker compose up -d (Qdrant, Prefect server)
make down         # docker compose down
make mock-server  # start mock site server on :8888
make crawl        # run pipeline for a single mock client (demo)
make serve        # start FastAPI serving layer
make test         # pytest (mocked, no real crawls)
make lint         # ruff + black check
make pipeline     # up + mock-server + crawl (full demo end-to-end)
make reset        # tear down volumes and start fresh
```

---

## README structure — required sections in order

1. **Badge row** — CI, Python version, license, Qdrant, Portkey
2. **One-sentence description** — what it is and what agent use case it solves
3. **Architecture diagram** — crawl → score → extract (via Portkey) → embed →
   Qdrant → FastAPI → agent. Label every tool.
4. **"What this demonstrates"** — bullet list mapping to JD language: RAG
   pipeline design, LLM gateway integration, typed vector retrieval, agent
   context serving, incremental data pipelines
5. **Quick start** — `make up`, `make mock-server`, `make crawl`, then a
   sample `curl` to the retrieval API
6. **Page importance model** — the scoring table with rationale. This is IP.
7. **Fact taxonomy** — table of fact types with examples
8. **Portkey setup** — link to SETUP.md, brief explanation of why Portkey
9. **Retrieval API** — example request/response JSON, p99 latency
10. **Incremental re-crawl** — explain the content hash logic, show
    `fact_age_days` in a sample response
11. **Production swap path** — Qdrant OSS → Qdrant Cloud, Prefect OSS →
    Prefect Cloud, local embedder → OpenAI embeddings
12. **Project structure** — file tree
13. **License** — MIT

---

## SETUP.md — required content (critical for public usability)

`SETUP.md` is the document users read before running anything. It must cover
both paths completely.

### Path A: Portkey mode (recommended)

Step 1 — Create a free Portkey account at portkey.ai

Step 2 — Add your LLM provider keys as virtual keys:
- Go to Virtual Keys in the Portkey dashboard
- Add your Google AI Studio key (for Gemini 2.5 Flash)
  OR your OpenAI key (for GPT-4o-mini)
- Copy the virtual key slug (looks like `google-abc123`)

Step 3 — Create a Portkey Config:
- Go to Configs in the dashboard
- Paste this JSON (edit virtual key slugs to match yours):
  ```json
  {
    "strategy": { "mode": "fallback" },
    "targets": [
      {
        "virtual_key": "YOUR_GOOGLE_VIRTUAL_KEY",
        "override_params": { "model": "gemini-2.5-flash" }
      },
      {
        "virtual_key": "YOUR_OPENAI_VIRTUAL_KEY",
        "override_params": { "model": "gpt-4o-mini" }
      }
    ]
  }
  ```
- Copy the Config slug (looks like `cf-abc123`)

Step 4 — Add to `.env`:
```bash
LLM_MODE=portkey
PORTKEY_API_KEY=pk-...       # from Portkey dashboard → API Keys
PORTKEY_CONFIG=cf-...        # the config slug from step 3
```

Step 5 — Run `make up && make crawl`

### Path B: Direct mode (no Portkey account)

Add to `.env`:
```bash
LLM_MODE=direct
LLM_PROVIDER=google           # or "openai"
LLM_MODEL_DIRECT=gemini-2.5-flash
GOOGLE_API_KEY=AIza...        # from aistudio.google.com
# OR
# LLM_PROVIDER=openai
# LLM_MODEL_DIRECT=gpt-4o-mini
# OPENAI_API_KEY=sk-...
```

Note: In direct mode, you lose Portkey's observability dashboard, automatic
fallbacks, and cost tracking. Recommended only for quick local testing.

---

## Shine checklist — before considering this project "done"

- [ ] `make up && make mock-server && make crawl` runs clean on a fresh clone
- [ ] Both Portkey mode and direct mode work end-to-end
- [ ] SETUP.md has been tested by following it on a clean machine
- [ ] README has an architecture diagram (not a placeholder)
- [ ] README has the page importance scoring table
- [ ] README has a sample API response with `fact_age_days` field visible
- [ ] README has measured p99 retrieval latency from Qdrant
- [ ] Prefect UI screenshot in README showing a completed crawl flow
- [ ] CI badge is green and visible at top of README
- [ ] All 4 ADRs exist in `docs/adr/` with all required sections
- [ ] `docs/page_scoring_spec.md` is complete
- [ ] `notebooks/demo.ipynb` runs in Colab with a Google API key
- [ ] `extractor/prompts/extraction_system.txt` is committed (not gitignored)
- [ ] Pydantic schemas cover all 6 fact types
- [ ] Facts below `confidence < 0.5` are filtered before upsert
- [ ] Incremental re-crawl skips unchanged pages (verified in test)
- [ ] `robots.txt` is fetched and respected (verified in test)
- [ ] Mock site server covers at least 3 business types
- [ ] `.env.example` committed; real `.env` gitignored
- [ ] No hardcoded API keys, model names, or URLs outside config files
- [ ] MIT license file present

---

## GitHub profile framing

Repo description (shown on GitHub profile):
> Website crawler + LLM fact extractor for local businesses — Qdrant · Portkey · Gemini · FastAPI · Prefect

Profile README framing:
> **Client Fact Library** — AI data pipeline that crawls client websites,
> extracts typed business facts via LLM (routed through Portkey), and stores
> them in Qdrant for retrieval by AI chat and voice agents.

Pin this repo alongside beacon-lakehouse. Together they tell a complete AI
data engineering story: structured analytical data (beacon-lakehouse) +
unstructured website knowledge (client-fact-library).

---

## Questions an AI should ask before writing any code

1. Which specific file or component are we building right now?
2. Are we implementing Portkey mode, direct mode, or the shared interface?
3. Are we targeting the mock site server or a real URL?
4. Should extraction return all fact types or a specific subset?
5. Is this a new file or a modification to an existing one?

Do not make scope assumptions. Confirm before proceeding.
