# CLAUDE-PART2.md — Client Fact Library: Knowledge Base & Document Ingestion

This file extends `CLAUDE.md`. Read `CLAUDE.md` fully before reading this file.
The website crawler described in `CLAUDE.md` is **complete and working**. This
file covers everything being added on top of it: two new ingestion sources
(curated knowledge base records and document uploads), a unified source priority
model, a new `ConditionalFact` schema type, and the CI eval harness.

Do not modify the crawler, the Qdrant collection schema, or the existing
`extractor/` code unless explicitly instructed. All additions are additive.

---

## What this part adds

The completed project ingests facts from one source: crawled website pages.
This extension adds two more:

| Source | Type | Input | Ingestion pattern |
|---|---|---|---|
| Website crawler | Unstructured | Public web pages | Completed — see CLAUDE.md |
| Knowledge base | Structured | Postgres DB rows | CDC-style: watch `updated_at` |
| Documents | Unstructured | PDFs, DOCX, TXT | File watcher: S3 or local folder |

All three sources write to the **same Qdrant collection** (`client_facts`) using
the **same fact schema** with one new field: `source_type`. The retrieval API
is unchanged — agents query one endpoint and get facts ranked across all sources.

---

## The architecture this enables

The production pattern this mirrors: no single source ever has complete
knowledge about a business. The website has public-facing facts. The knowledge
base has curated, human-verified facts the business explicitly controls — scripts,
overrides, if/then handling, pricing exceptions. Documents have structured
information that was never put on the website — contracts, menus, spec sheets,
onboarding guides.

Unifying all three under one retrieval layer is the data engineering story.
The agent doesn't know or care which source a fact came from. The data layer
handles provenance, staleness, and priority — that's the job.

---

## New Qdrant payload field: `source_type`

Add `source_type` as an indexed keyword field to all existing and new Qdrant
points. Backfill existing crawled facts with `source_type: "website"` on next
re-crawl.

```python
source_type: Literal["website", "knowledge_base", "document"]
```

This field enables filtered retrieval by source and drives the confidence
ranking model described below.

---

## Source priority & confidence ranking model

When multiple facts answer the same query, source type determines ranking
weight alongside vector similarity score. The model:

| Source type | Base confidence multiplier | Rationale |
|---|---|---|
| `knowledge_base` | 1.0 (no discount) | Human-curated, explicitly authored |
| `website` | 0.9 | Crawled + LLM-extracted, high quality |
| `document` | 0.85 | Parsed + LLM-extracted, format variance |

The final retrieval score:
```python
final_score = vector_similarity * confidence * source_multiplier
```

A `knowledge_base` fact with `confidence: 0.95` will outrank a `website` fact
with `confidence: 0.95` for the same query. This is the override mechanism:
when the business explicitly curates a fact, it should win.

Document this ranking model in the README and in the `/facts/{client_id}/types`
endpoint response so agents can understand what they're getting.

---

## Source 2: Knowledge base ingestion

### What the knowledge base contains

The knowledge base is a Postgres table (`client_knowledge_base`) managed by an
admin UI or direct DB insert. It stores facts the business explicitly curates —
things that either don't appear on the website or need to override what the
website says.

Key record types:

**Standard Q&A pairs**
A question the AI agent might be asked and the exact answer the business wants
given. Not LLM-extracted — human-authored.
```
Q: Do you offer payment plans?
A: Yes, we offer 0% financing through CareCredit for treatments over $500.
```

**Conditional / if-then facts**
Business logic for handling specific situations. If a caller asks about X,
the agent should respond with Y. These are the most sensitive facts — they
encode escalation paths, pricing exceptions, and edge case handling.
```
IF: caller asks about cancellation policy
THEN: inform them of the 48-hour cancellation window and $50 late fee
UNLESS: they are a platinum member (check membership status first)
```

**Talking points / scripts**
Free-form guidance for specific topics. Not a strict Q&A — more like a
briefing the agent should internalize.

**Pricing overrides**
Explicit, current pricing that may differ from or not appear on the website.
These records have the highest business impact and should rank highest.

### Postgres schema

```sql
CREATE TABLE client_knowledge_base (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       VARCHAR NOT NULL,
    fact_type       VARCHAR NOT NULL,  -- 'qa', 'conditional', 'talking_point', 'pricing_override'
    title           VARCHAR,           -- short label for the admin UI
    condition       TEXT,              -- for conditional facts: the IF clause
    response        TEXT NOT NULL,     -- the answer / THEN clause / talking point
    exception_note  TEXT,              -- for conditional facts: the UNLESS clause
    priority        INTEGER DEFAULT 5, -- 1-10, higher = ranks first in retrieval
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_by      VARCHAR            -- admin user who authored it
);

CREATE INDEX idx_kb_client_id ON client_knowledge_base(client_id);
CREATE INDEX idx_kb_updated_at ON client_knowledge_base(updated_at);
CREATE INDEX idx_kb_fact_type ON client_knowledge_base(fact_type);
```

### New Pydantic schema: `ConditionalFact`

Add to `extractor/schemas.py`:

```python
class ConditionalFact(FactBase):
    """
    An explicit if/then business rule authored in the knowledge base.
    Unlike other fact types, these are not LLM-extracted — they are
    human-authored and carry confidence: 1.0 by default.
    """
    fact_type: Literal["conditional"]
    condition: str        # the IF clause — what triggers this fact
    response: str         # the THEN clause — what the agent should say/do
    exception_note: str | None = None  # the UNLESS clause if present
    priority: int         # 1-10 from the DB record
    source_type: Literal["knowledge_base"] = "knowledge_base"
    confidence: float = 1.0  # human-authored = full confidence by default
```

The embedded text for `ConditionalFact` (what gets vectorized):
```python
f"conditional: if {condition} then {response}"
```
Including both the condition and response in the embedded text enables the
agent to retrieve this fact when asking about either the trigger scenario or
the expected outcome.

### Ingestion pattern: CDC-style `updated_at` polling

Knowledge base ingestion does not use the crawler or the LLM extraction prompt.
It reads directly from Postgres and maps DB rows to Pydantic fact objects.

Change detection uses `updated_at` polling — not content hashing:
1. On each pipeline run, query for rows where `updated_at > last_synced_at`
2. For each changed/new row: delete existing Qdrant points for that `id`,
   re-embed and upsert
3. For deactivated rows (`is_active = false`): delete from Qdrant by payload
   filter `{kb_record_id: id}`
4. Store `last_synced_at` in a pipeline state table

This is deliberately simpler than the crawler's content hash approach because
the source is structured and change detection is trivial.

No LLM call is made during KB ingestion. The `response` field is embedded
directly. `confidence` defaults to 1.0 unless the admin explicitly sets it lower.

### New file: `ingestion/kb_ingestion.py`

```python
@task(retries=2)
def sync_knowledge_base(client_id: str, since: datetime) -> KBSyncResult:
    """
    Poll client_knowledge_base for changes since `since`.
    Map rows to ConditionalFact / QAFact objects.
    Delete stale Qdrant points. Embed and upsert new/changed records.
    Returns counts: checked, updated, deleted.
    """
```

No new Portkey prompt is needed for KB ingestion — there is no LLM extraction
step. This is a direct structured → vector pipeline.

---

## Source 3: Document ingestion

### What documents cover

PDFs, DOCX, and TXT files that contain business facts not captured on the
website or in the KB. Examples:
- Service menu PDFs (med spas, dental practices)
- Intake forms (what info the business collects)
- Insurance accepted lists
- Franchise / territory agreements
- Employee-facing onboarding guides (agent should know this context)

### File watching pattern

Documents are dropped into a watched location — either:
- A local folder: `documents/{client_id}/` (for the portfolio/local demo)
- An S3 bucket prefix: `s3://client-docs/{client_id}/` (production swap path)

A Prefect sensor polls for new or modified files. Change detection uses file
content hash (same pattern as the crawler).

### Document processing pipeline

Unlike website pages, documents need a parsing step before extraction:

```
File (PDF/DOCX/TXT)
  → parse_document()        # extract raw text, preserve structure
  → chunk_document()        # split into page-sized or section-sized chunks
  → for each chunk:
      extract_facts()       # Portkey prompt call (same extraction prompt)
      embed_facts()
      upsert_to_qdrant()
```

**Parsing:**
- PDF: `pdfplumber` (handles tables and multi-column layouts better than pypdf)
- DOCX: `python-docx`
- TXT: read directly

**Chunking strategy for documents:**
Documents are longer than web pages. Use a hybrid approach:
- First split by structural boundaries (page breaks, heading levels)
- Then apply a max-token guard (1500 tokens per chunk) for very long sections
- Each chunk carries metadata: `document_name`, `page_number`, `section_heading`

This is the one place in the project where character/page-based chunking is
used alongside fact-based chunking — document structure doesn't always align
with fact boundaries. Document this explicitly in the README.

**Extraction prompt:**
Use the same `PORTKEY_PROMPT_EXTRACTION_ID` as the crawler. The variables are
slightly different — pass `page_type: "document"` and `page_score: "3"` as
defaults, and pass `section_heading` instead of `page_url` for context.

Add `PORTKEY_PROMPT_DOCUMENT_ID` as an optional override env var for users
who want a separate, tuned document extraction prompt in Portkey.

### New Qdrant payload fields for documents

Documents add two extra payload fields not present on crawled facts:

```python
document_name: str        # filename, e.g. "service_menu_2025.pdf"
page_number: int | None   # page the chunk came from
section_heading: str | None  # nearest heading above the chunk
```

These fields surface in the API response and enable the agent to cite the
source document and page, not just the URL.

### New file: `ingestion/document_ingestion.py`

```python
@task(retries=2)
def ingest_document(
    client_id: str,
    file_path: str,
    document_name: str,
) -> DocumentIngestResult:
    """
    Parse, chunk, extract facts, embed, and upsert a single document.
    Idempotent: deletes existing Qdrant points for this document before
    upserting, keyed by (client_id, document_name, content_hash).
    """
```

---

## Updated file structure (additions only)

```
client-fact-library/
├── ingestion/
│   ├── kb_ingestion.py           # NEW: knowledge base CDC polling
│   └── document_ingestion.py     # NEW: document parse → extract → embed
├── extractor/
│   └── schemas.py                # MODIFIED: add ConditionalFact, QAFact
├── pipeline/
│   ├── flows.py                  # MODIFIED: add kb_sync_flow, document_flow
│   └── tasks.py                  # MODIFIED: add kb and document tasks
├── serving/
│   └── routers/
│       └── facts.py              # MODIFIED: source_type filter param added
├── seeds/
│   ├── seed_knowledge_base.py    # NEW: insert sample KB records to Postgres
│   └── sample_documents/         # NEW: sample PDFs/DOCX for demo
│       ├── dental_service_menu.pdf
│       ├── law_firm_faq.docx
│       └── home_services_areas.txt
├── quality/
│   └── eval/                     # NEW: retrieval eval harness
│       ├── eval_questions.json   # ground truth Q&A pairs
│       ├── run_eval.py           # eval runner
│       └── metrics.py            # precision@k, MRR calculation
└── .github/
    └── workflows/
        └── ci.yml                # MODIFIED: add eval gate step
```

---

## CI eval harness (the #2 differentiator)

This is the single feature that most clearly signals senior AI data engineering
vs. junior RAG tutorial work. Almost no portfolio project includes it.

### What it does

A small evaluation suite runs in CI against a fixed set of ground-truth
question/answer pairs. If retrieval quality drops below a threshold, CI fails.
This means you can't merge a prompt change, chunking strategy change, or schema
change that silently degrades what the agent gets back.

### Ground truth dataset: `quality/eval/eval_questions.json`

```json
[
  {
    "client_id": "demo_dental",
    "question": "Do you offer payment plans?",
    "expected_fact_types": ["pricing", "conditional"],
    "expected_source_types": ["knowledge_base", "website"],
    "min_score": 0.75
  },
  {
    "client_id": "demo_dental",
    "question": "What teeth whitening services do you offer?",
    "expected_fact_types": ["service"],
    "expected_source_types": ["website", "document"],
    "min_score": 0.75
  },
  {
    "client_id": "demo_legal",
    "question": "What happens if I need to cancel my appointment?",
    "expected_fact_types": ["conditional"],
    "expected_source_types": ["knowledge_base"],
    "min_score": 0.80
  }
]
```

20–30 questions is enough. They cover all three source types and all major fact
types. They are authored manually — not generated by an LLM.

### Metrics: `quality/eval/metrics.py`

**Precision@3:** For each question, retrieve top 3 facts. What fraction contain
the expected `fact_type`?

**MRR (Mean Reciprocal Rank):** Where does the first relevant fact appear in
the ranked results? MRR of 1.0 means the best fact is always #1.

**Source coverage:** For questions that expect a `knowledge_base` fact, does
a KB fact appear in the top 3? This specifically validates that KB facts are
ranking above crawled facts when they should.

### CI gate: `.github/workflows/ci.yml`

Add an eval step after `dbt test` and before Docker build:

```yaml
- name: Run retrieval eval
  run: |
    python quality/eval/run_eval.py \
      --questions quality/eval/eval_questions.json \
      --min-precision 0.75 \
      --min-mrr 0.70
```

The eval runner:
1. Starts the mock site server and seeds demo data (website + KB + documents)
2. Runs the full pipeline for demo clients
3. Fires all eval questions against the retrieval API
4. Computes precision@3 and MRR
5. Exits non-zero if either metric falls below threshold

CI fails = PR cannot merge. This is the gate.

### Document eval metrics in the README

After running the eval locally on the final project, paste actual numbers:
```
Retrieval eval results (demo dataset, 28 questions):
  Precision@3:  0.84
  MRR:          0.79
  KB override rate: 94%  (KB facts ranked #1 when present)
```

These numbers make the README feel like a real system, not a tutorial.

---

## Updated Makefile targets

```makefile
make seed-kb        # insert sample knowledge base records to Postgres
make seed-docs      # copy sample documents to watched folder
make seed-all       # seed + seed-kb + seed-docs (full demo data)
make eval           # run retrieval eval suite locally
make pipeline-all   # up + seed-all + ingest all three sources
```

---

## Updated Portkey prompt considerations

The existing `PORTKEY_PROMPT_EXTRACTION_ID` prompt works for documents with
minor variable changes. However, document extraction has different
characteristics than web page extraction:

- Documents are longer and more dense
- Documents often have tables, lists, and structured data
- Documents may have headers/footers with irrelevant content

Consider creating a second prompt in Portkey specifically for documents:
`PORTKEY_PROMPT_DOCUMENT_EXTRACTION_ID`. If not set, falls back to
`PORTKEY_PROMPT_EXTRACTION_ID`. Document this in SETUP.md.

The KB ingestion makes **no LLM calls** — document this clearly in README and
SETUP.md. KB facts cost zero LLM tokens to ingest. This is a meaningful cost
advantage worth calling out.

---

## Updated README sections (additions to existing README)

Add after the existing "Fact taxonomy" section:

**Knowledge base source**
Explain curated facts, ConditionalFact schema, the admin-controlled nature,
and why KB facts rank above crawled facts. Show an example `ConditionalFact`
JSON in the API response.

**Document source**
Explain the file watcher pattern, supported formats, the hybrid chunking
approach, and how `document_name` + `page_number` appear in API responses
for citation.

**Retrieval eval**
Show the eval results table (precision@3, MRR, KB override rate). Explain
that this runs in CI and gates merges. This section is the portfolio
differentiator — write it prominently.

---

## Updated shine checklist (additions to CLAUDE.md checklist)

- [ ] `make seed-kb` inserts ConditionalFact records covering all demo clients
- [ ] `make seed-docs` copies at least 3 sample documents per demo client
- [ ] KB facts rank above website facts in retrieval for the same query (verify manually)
- [ ] `ConditionalFact` with condition + response embeds and retrieves correctly
- [ ] Document facts include `document_name` and `page_number` in API response
- [ ] `make eval` runs clean and produces precision@3 ≥ 0.75
- [ ] CI eval gate is present in `.github/workflows/ci.yml`
- [ ] README eval results table has real numbers (not placeholders)
- [ ] SETUP.md documents that KB ingestion costs zero LLM tokens
- [ ] `pdfplumber` and `python-docx` both tested against sample files
- [ ] Source priority ranking documented in README with example showing KB override

---

## ADRs to add in `docs/adr/`

**ADR 005 — Knowledge base as a first-class ingestion source**
Context: website crawling misses facts the business explicitly curates —
scripts, pricing exceptions, conditional handling logic.
Decision: Postgres KB table as a second ingestion source. Human-authored
facts carry `confidence: 1.0` and a source multiplier that ranks them above
crawled facts.
Tradeoff: requires an admin UI or DB access for the business to manage KB
records — higher operational overhead than pure crawling.
Swap path: any CMS or headless CMS table with an `updated_at` field works as
a drop-in replacement for the Postgres KB table.

**ADR 006 — Hybrid chunking for documents**
Context: fact-based chunking (one fact = one vector) works well for web pages
but documents are too long and structurally varied for pure fact extraction.
Decision: split by structural boundaries first (pages, headings), then apply
fact extraction to each chunk. Max 1500 tokens per chunk.
Tradeoff: some document chunks will contain multiple facts that could be more
precisely separated. Accepted — the alternative (extracting facts from entire
documents in one LLM call) produces worse results and hits token limits.

**ADR 007 — CI-gated retrieval eval**
Context: prompt changes, schema changes, and re-chunking decisions can silently
degrade retrieval quality. Needed a way to catch regressions automatically.
Decision: a 28-question ground truth eval runs in CI. Precision@3 < 0.75 or
MRR < 0.70 fails the build.
Tradeoff: the eval dataset is small and manually authored — it won't catch
every regression. Accepted — 28 targeted questions covering all source types
and fact types provides meaningful signal without becoming a maintenance burden.

---

## Questions an AI should ask before writing any code (additions)

1. Are we working on KB ingestion, document ingestion, or the eval harness?
2. For KB: are we modifying the schema, the ingestion task, or the seed data?
3. For documents: which file format are we targeting first (PDF, DOCX, or TXT)?
4. For the eval harness: are we writing questions, the runner, or the CI step?
5. Should the new code be tested against the mock server or real demo data?
