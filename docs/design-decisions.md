# Design Decisions — Senior AI Data Engineer Perspective

This document explains the architectural choices in the Client Fact Library at a level deeper
than the ADRs. Each section covers what we chose, what we seriously considered, and the real
tradeoffs — including where the current design could fail at scale and what you'd change if it did.

---

## 1. Chunking Strategy: Typed Fact Objects vs Raw Text Segments

### What we chose
One Pydantic fact object = one Qdrant point. The LLM extracts structured objects; each
object is embedded and stored independently. Retrieval is vector similarity filtered by
`fact_type`.

### Alternatives considered

**Character-count chunking (512 tokens, 50-token overlap)**  
The default in most RAG tutorials. Trivially simple. Works for open-ended Q&A where any
chunk might contain the answer.

_Why we rejected it:_ When an agent asks "what are your prices?", character-count chunks
might return a chunk that contains one price buried in three paragraphs of marketing copy,
or a chunk that contains the service description but not the price list (it was in the next
chunk). Fact-typed retrieval makes "find all pricing facts" a first-class, precise operation.
Character-count chunking can only approximate this with post-filtering.

**Semantic chunking (split at embedding similarity drops)**  
More sophisticated than character-count. Groups semantically coherent text. Libraries like
LangChain's `SemanticChunker` implement this.

_Why we rejected it:_ Semantic chunking still produces raw text blobs without structured
metadata. You can't filter on "confidence" or "fact_type" in a vector database using raw
chunks. It also requires a second pass of embeddings just to split the text, adding cost
and latency before any extraction happens.

**LLM function calling / tool use (JSON schema enforcement)**  
Instead of "return JSON that looks like this schema", use the LLM's native function-calling
to guarantee schema conformance — OpenAI's structured outputs, Gemini's response_schema, etc.

_Why we didn't use it here:_ Portkey mode abstracts away provider-specific capabilities.
Gemini and GPT-4o-mini have different function-calling APIs. Supporting schema enforcement
across both providers via Portkey would require provider-specific routing logic, which
defeats the gateway pattern. Our Pydantic validation layer serves the same purpose and is
provider-agnostic — a bad LLM response is caught and logged, never raised.

_When you'd add it:_ Single-provider deployment, or once Portkey exposes a unified
structured output API. At that point, replace `parse_facts()` with a tool-call response
handler. The rest of the pipeline is unchanged.

**DSPy (programmatic prompt optimization)**  
DSPy treats prompts as modules and optimizes them against a metric (e.g., F1 on extracted
facts). The extraction prompt becomes a learned artifact rather than a hand-written one.

_Why we didn't use it here:_ DSPy optimization requires labeled examples and a defined
metric. For a portfolio project without labeled ground truth, the overhead isn't justified.
For a production system processing millions of pages across many client industries, DSPy
would likely produce significantly better extraction quality than a hand-written prompt.
The architecture supports swapping in DSPy: `FactExtractor` is already a class, and the
prompt is already externalized in files.

### The real tradeoff
Typed extraction is strictly more powerful and more expensive than character-count chunking.
The cost is one LLM call per page. For a dental practice with 20 pages at ~$0.001/page
with Gemini Flash, that's $0.02 per full crawl. At 10,000 clients with monthly recrawls,
that's $200/month in LLM extraction costs. At that scale, DSPy-optimized prompts and
aggressive page scoring (crawl top 10 pages only) become important levers.

---

## 2. Vector Database: Qdrant vs the Field

### What we chose
Qdrant: purpose-built vector DB, Docker-native, first-class payload filtering.

### Alternatives considered

**pgvector (Postgres extension)**  
The most common choice in production today. Runs alongside your operational database.
No extra service. IVFFlat and HNSW indexes are solid for mid-scale deployments.

_Where pgvector wins:_
- Zero additional infrastructure: if you already have Postgres, you have a vector store
- Transactional consistency: a fact upsert and its audit log are in the same ACID transaction
- SQL expressiveness: `WHERE fact_type = 'pricing' AND confidence > 0.7 ORDER BY created_at DESC` is elegant

_Where pgvector loses:_
- Payload indexing is awkward. Filtered vector search in pgvector requires pre-filtering
  rows (which can eliminate HNSW's benefits), or post-filtering results (less precise recall).
  Qdrant's filter API was designed for this from day one.
- At high vector dimension counts (1536 for OpenAI embeddings) and large collection sizes
  (millions of facts), Qdrant's HNSW implementation consistently outperforms pgvector on
  QPS benchmarks. This matters at 10k+ clients.
- Named collections and schema isolation per entity type are native in Qdrant; in pgvector
  you're managing multiple tables and views.

_Verdict:_ If you're building a product that already has Postgres and has under 1M vectors,
pgvector is a completely reasonable choice. The operational simplicity is real. For a
dedicated AI data service where vector retrieval is the primary workload, Qdrant's design
is better-fit.

**Chroma**  
Designed for ease of use. Great for notebooks and prototypes. Embedded mode (in-process,
no server) makes getting started trivially easy.

_Where Chroma loses for this use case:_
- No production-grade payload indexing. Metadata filters work, but performance at scale is
  not Chroma's primary concern.
- Chroma's Python-first design means it's awkward to run as a shared service with multiple
  writers (the Prefect pipeline) and readers (the FastAPI serving layer) concurrently.
- Smaller community around production deployments; fewer examples of multi-client,
  multi-collection architectures.

**Pinecone (managed)**  
Fully managed, serverless, zero ops. Strong production track record.

_Why not here:_
- Always-on cost even when idle. For a portfolio project or small SaaS, the billing model
  doesn't fit.
- No self-hosted option: CI can't use an in-memory Pinecone. Our CI uses `qdrant_client`'s
  in-memory mode for zero-infrastructure testing.
- The Qdrant → Qdrant Cloud swap path (one env var) gives us the same managed option at
  comparable cost without vendor lock-in.

**Weaviate**  
Strong multi-tenancy support (native per-client data isolation). Hybrid search (BM25 +
vector) built in. GraphQL API.

_Why not here:_
- More complex to operate than Qdrant for the MVP use case.
- The GraphQL API is expressive but adds another query language to the stack.
- Multi-tenancy is excellent, but our per-client isolation via Qdrant's `client_id` payload
  filter is sufficient until we're operating at enterprise scale where Weaviate's native
  tenancy isolation would matter for compliance.

_When to reconsider Weaviate:_ If regulatory requirements demand hard data isolation between
clients (HIPAA for dental/medical clients), Weaviate's tenant isolation (separate storage
per tenant) is architecturally stronger than our payload-filter approach.

---

## 3. LLM Gateway: Portkey vs Alternatives

### What we chose
Portkey: model selection in the dashboard, automatic fallback, centralized observability.

### Alternatives considered

**Direct provider SDK calls (no gateway)**  
The simplest possible implementation. One model hardcoded, one API key.

_The real cost:_
- Changing from GPT-4o-mini to Gemini Flash requires a code change and redeployment.
  For a running SaaS, that's friction. Portkey makes it a dashboard click.
- No automatic fallback. If OpenAI has an incident, your entire extraction pipeline halts.
  With Portkey's fallback config, it silently routes to Google with zero code changes.
- Zero observability out of the box. You have to instrument every LLM call yourself to
  see token counts, latencies, and error rates. Portkey gives this for free.

**LiteLLM (self-hosted gateway)**  
Open-source, self-hostable, OpenAI-compatible API in front of 100+ LLM providers.
Near-identical architecture to Portkey.

_LiteLLM vs Portkey:_
- LiteLLM is free and self-hosted. Portkey's observability dashboard requires a paid plan
  above the free tier's limits.
- LiteLLM requires you to operate the proxy as infrastructure (Docker container, scaling,
  HA). Portkey is managed.
- For a portfolio project where the goal is demonstrating production patterns, Portkey's
  managed dashboard makes the observability story more concrete and visual than LiteLLM.
- For a real startup where you want zero external SaaS dependencies, LiteLLM is the right
  call. The code swap: replace `Portkey(api_key=..., config=...)` with
  `OpenAI(base_url="http://litellm:4000", api_key="...")`. One line.

**OpenRouter**  
Another managed gateway with multi-provider routing. Lower price on some models due to
provider competition. Credit-based pricing model.

_Why Portkey over OpenRouter:_
- Portkey's observability dashboard (traces, cost per call, latency histograms) is more
  mature for production AI ops.
- Portkey's virtual key concept (store provider keys in Portkey, never in your env) is
  a cleaner security model for team environments.
- OpenRouter is excellent for model experimentation; Portkey is better for production pipelines.

**OpenAI Assistants API / Thread-based approaches**  
Not applicable here. The extraction task is stateless (one page → one set of facts).
Thread-based APIs are for conversational AI, not batch extraction pipelines.

---

## 4. Embedding Model: Local MiniLM vs APIs

### What we chose
`sentence-transformers/all-MiniLM-L6-v2` (384-dim, runs locally, zero cost).

### Alternatives considered

**OpenAI `text-embedding-3-small` (1536-dim)**  
Higher quality embeddings, especially for nuanced semantic similarity. The go-to for
production systems where retrieval quality is the primary concern.

_When to upgrade:_
If retrieval quality testing shows that `pricing: starts at $150` and `pricing: consultation
fee is $150` have low cosine similarity (they shouldn't, but domain-specific jargon might
cause issues), switching to `text-embedding-3-small` is the first lever to pull.

_The real cost math:_ At $0.02/1M tokens, embedding 50 facts per client per month across
10,000 clients: 500,000 facts × ~20 tokens each = 10M tokens = $0.20/month. Trivially cheap.
The friction is recreating the Qdrant collection (dimension changes from 384 to 1536 break
existing vectors). Document this clearly — we did in SETUP.md.

**Cohere Embed v3 (1024-dim with int8 compression)**  
Strong multilingual performance. Better than OpenAI on non-English text. Cohere's int8
quantization compresses 1024-dim float32 vectors to 1024 bytes (vs 6144 bytes for OpenAI's
1536-dim float32), reducing storage and memory costs significantly at scale.

_When it matters:_ If your clients serve non-English markets (Spanish-speaking dental
practices, law firms that operate in French), Cohere Embed v3 would be meaningfully better.
Local MiniLM has decent multilingual support but is not optimized for it.

**BGE-M3 (local, multilingual, 1024-dim)**  
State-of-the-art open-source embedding model from Beijing Academy of AI. Outperforms
MiniLM significantly on MTEB benchmarks. Still runs locally (larger download — ~2GB vs
MiniLM's ~90MB).

_Why MiniLM over BGE-M3 here:_
- Pipeline latency: MiniLM embeds a fact in ~1ms on CPU. BGE-M3 is 3-5× slower.
  For a batch pipeline running nightly, this doesn't matter. For the serving layer's
  p99 < 100ms retrieval SLA, embedding the query at request time with BGE-M3 on CPU
  would likely blow the budget.
- Model download size for CI: 90MB vs 2GB. CI startup time matters.

**No embeddings (BM25 / keyword search only)**  
Elasticsearch or Qdrant's sparse vector support. No LLM embedding step.

_Why this fails for our use case:_ An AI agent asking "what's the fee for an initial
visit?" won't keyword-match "consultation: $150 per session" without semantic understanding
of "fee" ≈ "cost" ≈ "price" and "initial visit" ≈ "consultation". The entire value
proposition of this pipeline over a simple database is semantic retrieval.

_Hybrid search consideration:_ A hybrid of BM25 (keyword recall) + vector (semantic recall)
consistently outperforms either alone on MTEB. Qdrant supports sparse vectors for BM25.
At MVP, the complexity isn't warranted — local business facts use consistent language, so
pure vector retrieval quality is high. At scale with diverse client languages and jargon,
adding BM25 as a recall layer would improve retrieval meaningfully.

---

## 5. Crawler Architecture: Two-Tier vs Single-Tool

### What we chose
httpx for static HTML (the 90% case), Playwright as an opt-in fallback for JS-rendered SPAs.

### Alternatives considered

**Playwright-first (render everything in a headless browser)**  
Simplest interface: one crawler for all sites. No conditional logic.

_Why it's a bad default for local business sites:_
- Playwright spins up a Chromium instance per page: ~200-300ms startup, 200MB+ memory.
  A 30-page crawl at 1.5s rate limiting takes 45+ seconds without browser overhead.
  With Playwright-first, add 6-9 seconds of browser spin-up time per crawl run.
- 90% of local business sites are static WordPress, Squarespace, or Wix pages. httpx
  fetches them in 200ms with zero browser overhead.
- Playwright can't run in restricted CI environments without a full browser install
  (`playwright install chromium` downloads ~130MB). httpx has no such requirement.

**Scrapy (production-grade, async, multi-spider)**  
The industry standard for large-scale web crawling. Built-in request deduplication,
middleware pipeline, robots.txt handling, distributed crawling support.

_Why not here (yet):_
- Scrapy's learning curve and boilerplate are significant for a single-domain crawler.
  The cost-to-benefit ratio doesn't make sense until you're crawling hundreds of domains
  concurrently.
- Scrapy's spider model requires a full project structure (`scrapy startproject`). For a
  library that needs its crawler to be a simple, importable class, Scrapy's architecture
  is more friction than it's worth.
- When to upgrade: >100 concurrent client crawls, or if crawl speed becomes a bottleneck.
  At that point, swap `HttpxCrawler` for a Scrapy spider behind the same `AbstractCrawler`
  interface — no changes to the pipeline, extractor, or store.

**Sitemap-first discovery (parse sitemap.xml before crawling)**  
Many sites publish `sitemap.xml` with all URLs. Parsing the sitemap gives you the full URL
list without crawling the homepage to discover links.

_Why it's a useful enhancement, not a default:_
- Sitemaps are not universal. Many small local business sites (especially Wix/Squarespace
  templates) either don't have sitemaps or have incomplete ones.
- Sitemaps don't provide the inbound link count we need for the scoring modifier. You'd
  still need to crawl the HTML to compute scoring modifiers accurately.
- A production-grade enhancement: check for `sitemap.xml` first, fall back to link
  discovery if missing. This would meaningfully speed up the discovery phase.

**Crawl4AI / FireCrawl (managed crawling APIs)**  
Managed services that handle rendering, rate limiting, robots.txt, and return clean markdown.
Crawl4AI is open-source; FireCrawl is SaaS.

_The tradeoff:_ Managed crawlers eliminate all crawler code but add SaaS cost ($0.002-$0.01/page)
and a dependency. For 30 pages/client × 10,000 clients/month = 300,000 pages/month, that's
$300-$3,000/month just in crawling costs. Our httpx crawler has zero marginal cost per page.
The tradeoff inverts if crawl engineering becomes a maintenance burden (anti-bot measures,
rendering failures, IP blocks) — at that point, outsourcing crawling makes economic sense.

---

## 6. Incremental Strategy: Content Hash vs Alternatives

### What we chose
`sha256(url + etag)` → `sha256(url + last-modified)` → `sha256(url + content)`. Query
Qdrant before crawling.

### Alternatives considered

**Full recrawl every time**  
Simplest possible approach. Crawl everything, extract everything, overwrite Qdrant.

_Why it's wrong for production:_ At 10,000 clients × 30 pages × 1 LLM call per page,
a full nightly recrawl is 300,000 LLM calls per night. Most of those pages didn't change.
With incremental logic, pages that return a matching ETag incur zero LLM cost. At Gemini
Flash pricing (~$0.001/page), that's the difference between $300/night and ~$10/night
(assuming 97% of pages are unchanged between nightly runs — realistic for local business sites).

**Last-Modified header comparison**  
Store the `Last-Modified` header timestamp per page. On the next crawl, send
`If-Modified-Since: <last_timestamp>`. If the server returns 304, skip.

_The problem:_ Most local business sites (WordPress, Wix, Squarespace) don't correctly
implement `If-Modified-Since`. They return 200 with the full page regardless. ETags are
more widely implemented. Content hashing is the universal fallback.

**RSS/webhook-based change notification**  
Some sites publish RSS feeds or support WebSub. Subscribe to changes rather than polling.

_Why this doesn't scale to local businesses:_ RSS coverage on local business sites is
minimal (maybe 30-40% for WordPress sites with a blog, near-zero for Squarespace). WebSub
is even rarer. Polling remains the reliable approach.

**Differential extraction (re-extract only changed sections)**  
Instead of re-extracting the entire page when content changes, diff the old HTML against
the new HTML and only re-extract changed sections.

_Why it's overengineering for now:_ Page-level content hashing is sufficient. When a
pricing page changes, it's almost always better to re-extract the whole page than to
try to surgically update individual facts. The LLM extraction is cheap relative to the
complexity of maintaining a page-section diff system. Revisit at scale.

---

## 7. Confidence Threshold: Why 0.5?

### The choice
Facts below `confidence < 0.5` are discarded before upsert. The 0.5 threshold was chosen
deliberately.

### The reasoning

The confidence score is LLM self-assessment: "how clearly does this page state this fact?"
not "how likely is this fact to be accurate?"

- **0.9+:** Explicitly stated, specific. "Initial consultation is $150." The LLM has high
  confidence it's not inferring or paraphrasing.
- **0.7-0.89:** Clearly stated but requires some interpretation. "Starting at $150" (implies
  minimum, not exact).
- **0.5-0.69:** Inferred from context. "Competitive pricing" with no numbers. The fact
  still has some signal but should be treated as soft evidence.
- **< 0.5:** Too vague. "We offer affordable services." An AI agent using this fact would
  be giving misleading information.

**Why not 0.7?**  
A 0.7 threshold would discard location facts ("We serve the Dallas area" — unambiguous but
not hyper-specific) and operational facts ("We're open on weekends" — stated but without
exact hours). These are valuable even if imprecise.

**Why not 0.3?**  
At 0.3, we'd be storing "We offer competitive pricing" as a pricing fact. An agent citing
this would be embarrassing at best, misleading at worst.

**The calibration problem:**  
LLM self-assessed confidence is not well-calibrated. A model might consistently rate
everything between 0.7 and 0.95, making the threshold choice almost arbitrary.
A production system should measure empirical precision at different thresholds on a
labeled eval set. 0.5 is a defensible starting point for local business sites where
facts tend to be either clearly stated or clearly absent.

---

## 8. Pipeline Orchestration: Prefect vs Task Queues vs Cron

### What we chose
Prefect: `@flow` / `@task` decorators, built-in retries, local server for observability.

### Alternatives considered

**BullMQ (Redis-backed job queue)**  
The CLAUDE.md for the parent DeployFlow project mentions BullMQ as the MVP orchestrator.
For a pipeline that looks like a job queue (one pipeline run per client trigger), BullMQ
is simpler operationally.

_Why Prefect instead:_
- Prefect's flow decomposition (`@task` per stage) gives you granular retry logic:
  the crawl step retries on network errors; the extraction step retries on LLM errors;
  each independently. A job queue retries the entire job.
- Prefect's UI shows exactly which stage failed and why, with full logs. A Redis queue
  shows "job failed" with whatever was logged to stdout.
- For a pipeline with 7 distinct stages, Prefect's stage-level observability is worth
  the operational overhead of running the Prefect server.

**Apache Airflow**  
The industry standard for data pipelines. DAG-based, rich operator ecosystem, mature.

_Why not here:_
- Airflow's overhead (Postgres metadata DB, scheduler, webserver, workers as separate
  processes) is significant for a task that could run as a simple cron job at MVP scale.
- Airflow's Python 2-style DAG definitions (decorators are available but feel like
  retrofits) are more verbose than Prefect's clean `@task` pattern.
- Prefect 3's async-native architecture and simpler local setup make it a better
  developer experience for a Python-native team.
- _When to switch to Airflow:_ If the platform grows to need complex inter-pipeline
  dependencies, SLA monitoring, data-aware scheduling, or your data engineering team
  already runs Airflow for other pipelines.

**Temporal (workflow engine)**  
The most powerful option: durable execution, persistent workflow state, reliable long-running
workflows. DeployFlow uses Temporal for exactly this reason — complex multi-service
orchestration with compensation logic.

_Why overkill for a crawl pipeline:_
- Temporal's value is in long-running workflows with human approval steps, external
  wait states, and compensation logic. A crawl pipeline runs to completion in minutes.
- Temporal requires a cluster to run (or Temporal Cloud). Prefect runs with `prefect server
  start`. The ops cost difference is significant at MVP scale.

**Plain cron + Python script**  
`0 3 * * * python pipeline/flows.py` in a crontab or GitHub Actions scheduled workflow.

_Legitimate for MVP:_ This is not a joke. A well-structured Python script with logging,
retry decorators, and error reporting can replace an orchestrator at small scale. The
upgrade path to Prefect is straightforward.

_What you lose:_ Retry granularity, visual progress in a UI, historical run records,
parallel execution across clients, schedule management without editing cron files.

---

## 9. API Design: REST vs GraphQL vs gRPC for Agent Retrieval

### What we chose
REST with FastAPI. Simple, predictable, compatible with every AI agent framework.

### Alternatives considered

**GraphQL**  
Would allow agents to specify exactly which fact fields they need. Useful if different
agent implementations want different payload shapes (one wants just `content`, another
wants `raw_evidence` for citation).

_Why REST wins for an AI agent API:_
- AI agents calling this API are typically doing so via an LLM-generated function call.
  LLMs generate correct REST (`GET /facts/client_abc?q=...`) more reliably than GraphQL
  queries. The cognitive load of generating valid GraphQL in an LLM output is non-trivial.
- The response shape is stable and agent-optimized: include `fact_age_days` and `score`
  at the top level so agents don't have to compute them. GraphQL's flexibility is only
  useful if different consumers genuinely need different shapes.

**gRPC**  
Binary protocol, strongly typed, lower latency for high-throughput scenarios.

_Why not here:_ AI agents call retrieval APIs occasionally (one call per user query,
not millions per second). The latency advantage of gRPC over REST is irrelevant at
this call rate. REST's universality and JSON output are worth more for agent compatibility.

**OpenAI Plugin / Tool spec format**  
Expose the API as an OpenAI tool or MCP (Model Context Protocol) server.

_Strong future consideration:_ If the target use case is "plug this into a Claude or
GPT-4 agent and have the agent retrieve facts automatically", implementing an MCP server
on top of the FastAPI layer would dramatically lower the integration barrier. The
`GET /facts/{client_id}` endpoint maps cleanly to a single MCP tool.

---

## 10. Fact ID Strategy: Deterministic Hash vs UUID

### What we chose
`fact_id = sha256(client_id + fact_type + content)` — a deterministic, content-addressed ID.

### Why this matters
If the same fact is extracted twice (e.g., a second crawl of an unchanged page slips past
the content hash check), a deterministic ID means the Qdrant upsert is idempotent — it
overwrites the same point rather than creating a duplicate. With a random UUID, two
extraction runs of the same page create two duplicate facts. At scale, duplicates degrade
retrieval quality (the same fact appears twice in results) and waste storage.

### The tradeoff
Deterministic IDs mean two genuinely different facts with identical content would map to
the same ID and the second would overwrite the first. In practice, this is extremely rare
for facts (`"pricing: $150 consultation"` is the same fact regardless of which page
stated it), but it's a subtle assumption. A more robust ID would be
`sha256(client_id + source_url + fact_type + content)`, which would allow the same fact
text from two different source URLs to coexist — worth considering for large multi-page sites
where the same pricing information appears on both the homepage and the pricing page.

---

## 11. What I'd Change in Production (Ordered by Impact)

1. **Add hybrid search (BM25 + vector).** Qdrant supports sparse vectors. A hybrid retrieval
   function with `alpha=0.5` (50% BM25, 50% vector) consistently outperforms pure vector on
   short, domain-specific queries. This is the single highest-leverage retrieval improvement
   available without changing the rest of the architecture.

2. **Add a re-ranking step.** After retrieving top-20 candidates from Qdrant, run them through
   a cross-encoder re-ranker (Cohere Rerank, or a local `cross-encoder/ms-marco-MiniLM-L-6-v2`)
   to get the actual top-5. Cross-encoders see the query and document together, dramatically
   improving precision on ambiguous queries.

3. **Use DSPy for extraction prompt optimization.** Build a labeled evaluation set (100 pages,
   human-verified facts) and run DSPy's BootstrapFewShot optimizer against a precision metric.
   Optimized prompts typically recover 10-15% more facts at the same confidence threshold.

4. **Implement per-client scoring calibration.** A law firm's `/case-results/` page should score
   like a `/services/` page. Currently this requires a YAML config per client. In production,
   an ML classifier trained on page text → importance score would handle novel URL patterns
   without per-client configuration.

5. **Add staleness-aware retrieval.** Facts extracted 180 days ago should be down-ranked
   relative to facts extracted yesterday, even if their semantic similarity score is identical.
   Implement via score adjustment: `final_score = semantic_score * (1 - decay_rate * age_days)`.
   A dental practice's pricing changes; a 6-month-old pricing fact is potentially wrong.

6. **Shard Qdrant by industry.** At 10k+ clients, a single `client_facts` collection with
   a `client_id` filter becomes the query hot path. Sharding by industry (`dental_facts`,
   `legal_facts`, `home_services_facts`) improves index locality and allows industry-specific
   payload schema evolution without migrating a monolithic collection.

---

## 12. Multi-Source Ingestion: Why Three Sources Are Better Than One

### What we chose
Three ingestion sources writing to the same Qdrant collection: website crawler (existing),
knowledge base (Postgres CDC), and documents (file watcher). A single `source_type` payload
field distinguishes them at retrieval time.

### The problem with crawler-only ingestion
Website crawling captures public-facing facts. It misses two important categories:

**Facts the business controls but doesn't publish.** An AI agent answering calls needs to
know: "If a caller wants to cancel, waive the fee for platinum members." That's never on the
website. It's in the cancellation policy script the receptionist follows. Without a KB source,
the agent either makes something up or gives the wrong answer.

**Facts in structured documents that never made it to the website.** A dental practice's
full service menu lives in a PDF given to patients. The website has a high-level services
page; the PDF has actual prices and procedure codes. The agent needs the PDF.

### Why not just put everything in the website?
For local businesses, the website is typically managed by a marketing agency or a self-serve
platform like Wix. The business doesn't control it directly. Adding a pricing override or
a cancellation policy means filing a change request with the agency. The knowledge base gives
the business direct, immediate control over what the agent says — without touching the website.

### Alternatives considered

**Single source with manual override flags**
Mark certain facts as "overrides" in Qdrant. A flag in the payload deprioritizes or
removes conflicting crawled facts.

_Why it doesn't work:_ You can't flag crawled facts until after extraction. Extraction
is non-deterministic — the same page might produce slightly different facts on two runs,
and you'd have to re-apply override flags after every crawl. A separate KB source with
guaranteed `confidence=1.0` is cleaner and more reliable.

**Fine-tune the LLM to extract KB-style facts from the website**
If the business puts their scripts on a hidden `/internal-scripts` page, the crawler
extracts them as facts.

_Why it doesn't scale:_ Requires website access and cooperation. Creates a security risk
(agent scripts visible to public crawlers). Breaks the clean separation between public
content and internal business logic.

---

## 13. Source Confidence Ranking: Why Knowledge Base Facts Must Win

### What we chose
A source multiplier applied post-search:
```python
final_score = vector_similarity * confidence * source_multiplier
# KB: 1.0x · Website: 0.9x · Document: 0.85x
```

### The override requirement
When a business explicitly curates a fact ("our cancellation fee is $50"), it should
always outrank what the crawler found ("cancellation fees may apply"). This is not a
semantic similarity question — it's a governance question. The business is saying:
"This is the authoritative version." The data layer must respect that.

Without a source multiplier, a website fact with vector similarity 0.95 would outrank
a KB fact with similarity 0.88 for the same query. That's the wrong answer.

### Why these specific multipliers?

**KB at 1.0× (no discount):** Human-authored facts are already set to `confidence=1.0`
by definition. No further discounting is appropriate — the business explicitly wrote this.

**Website at 0.9×:** Crawled + LLM-extracted. High quality but not authoritative. The 10%
discount is enough to ensure a clear KB fact beats a website fact on the same topic, while
keeping strong website facts above weak or tangential KB facts.

**Document at 0.85×:** Parsed + LLM-extracted from unstructured documents. Higher variance
than web pages (documents may have headers, tables, and boilerplate that reduce extraction
precision). The additional 5% discount versus website reflects this.

### Why post-search re-ranking rather than pre-filtering?

Two alternatives:
1. **Index-time boosting:** Multiply the embedding vector by the multiplier at upsert time.
   This bakes the ranking decision into the vector space permanently. Changing the multiplier
   requires re-embedding all vectors.
2. **Pre-filter by source_type:** Search KB first, then website, merge results.
   This breaks the unified semantic search — you'd need to run 3 queries and merge, losing
   cross-source ranking.

Post-search re-ranking (`final_score = similarity * confidence * multiplier`) is clean,
adjustable without re-embedding, and preserves the single-query interface. The cost is
over-fetching (`limit * 3` results) and sorting in Python, which is negligible at our scale.

### The tradeoff
The multipliers are currently constants. In production, they should be:
- Configurable per client (a client who updates their KB daily gets a higher KB multiplier)
- Adaptive over time (a KB fact that hasn't been updated in 6 months should be discounted)
- Monitored via the CI eval gate to ensure the KB override rate stays above 90%

---

## 14. CI-Gated Retrieval Eval: Why This Is the Most Important Engineering Decision

### What we chose
A 28-question ground-truth evaluation suite that runs in CI. Precision@3 < 0.75 or
MRR < 0.70 fails the build and blocks merges.

### Why this is different from unit tests
Unit tests verify that code does what it says. They confirm `precision_at_k()` returns the
right number, `chunk_document()` splits correctly, `upsert_fact()` calls the Qdrant client.

What they can't verify: whether the agent actually gets back the right facts when it asks
a real question. A prompt change that improves structure but moves pricing facts from position
1 to position 3 in retrieval results is invisible to unit tests. The eval gate catches it.

### The silent regression problem
Consider three changes that each pass all unit tests and break retrieval quality:

1. **Prompt change:** "Return facts as a JSON array" → "Return facts in structured format."
   Extraction quality drops. Fewer facts per page. Precision@3 falls from 0.84 to 0.61.
   Unit tests: all green (parse_facts still works on the reduced output).

2. **Source multiplier bug:** KB multiplier accidentally set to 0.85 instead of 1.0 in
   a refactor. Website facts now outrank KB facts on the same topic.
   Unit tests: all green (search returns results, multiplier math is technically valid).

3. **Chunking change:** Max tokens reduced from 1500 to 500 to "improve focus." Document
   facts fragment. A pricing table that spanned one chunk now spans three, each too small
   to extract a complete fact.
   Unit tests: all green (chunk_document works, smaller chunks are valid).

All three scenarios degrade the agent's answer quality in ways a user would immediately notice.
None are caught by any test that doesn't measure end-to-end retrieval.

### Why 28 questions and not 200?
28 questions is the minimum viable eval set that covers:
- All three source types (website, knowledge_base, document)
- All major fact types (pricing, service, location, operational, conditional, qa)
- All three demo clients (dental, legal, home services)
- The KB override scenario (8 questions where a KB fact must rank #1)

Adding more questions improves precision of the metric but increases the risk of eval
brittleness (a small, targeted dataset is easier to reason about when a threshold trips).
The upgrade path: grow to 100-200 questions as the product matures and add LLM-as-judge
for automated ground truth generation on new content.

### Why seed facts directly rather than run the full pipeline in CI?
The full pipeline requires real LLM calls. In CI:
- Real LLM calls are non-deterministic (the eval score would vary between runs)
- Real LLM calls have cost (CI runs dozens of times per day)
- The eval would be testing LLM extraction quality, not retrieval ranking — and we don't
  control the LLM's output in CI

By seeding known typed facts directly into Qdrant, the CI eval tests exactly what it should:
does the retrieval and ranking layer surface the right facts for the right queries? That's
the job. LLM extraction quality is a separate concern measured with DSPy or a human eval set.
