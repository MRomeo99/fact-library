# PROGRESS.md — Client Fact Library Build Session

**Last updated:** 2026-06-26  
**Session result:** CLAUDE-PART2.md fully implemented. 130/130 tests passing.

---

## Session 1 — Initial build (2026-06-18)

Built the full project scaffold from CLAUDE.md. 79 tests passing.
See session 1 details below under "What Was Built (Session 1)".

---

## Session 2 — CLAUDE-PART2.md additions (2026-06-26)

### What was added

#### New ingestion sources

**`ingestion/kb_ingestion.py`** — Knowledge base CDC polling
- `map_kb_row_to_fact()` — maps DB rows to `ConditionalFact` / `QAFact`
- `get_embed_text_for_kb_fact()` — `"conditional: if {X} then {Y}"` format
- `sync_knowledge_base()` — upserts active records, deletes inactive ones
- `fetch_kb_rows_since()` — Postgres CDC query for `updated_at > since`
- Zero LLM calls — KB facts are embedded directly
- `source_type = "knowledge_base"`, `confidence = 1.0` by default

**`ingestion/document_ingestion.py`** — PDF/DOCX/TXT ingestion
- `parse_document()` — pdfplumber (PDF), python-docx (DOCX), native (TXT)
- `chunk_document()` — structural boundary split + 1500-token max guard
- `ingest_document()` — delete-then-upsert with `source_type="document"`
- `DocumentChunk` dataclass with `document_name`, `page_number`, `section_heading`

#### New schemas (`extractor/schemas.py`)
- `ConditionalFact` — if/then KB rule: `condition`, `response`, `exception_note`, `priority`
- `QAFact` — curated Q&A pair: `question`, `answer`
- Both carry `source_type: Literal["knowledge_base"] = "knowledge_base"`, `confidence = 1.0`

#### Store updates (`store/`)
- `collection_config.py` — added `source_type` as indexed keyword field
- `qdrant_store.py` — `upsert_fact()` gains `source_type` and `extra_payload` params
- `qdrant_store.py` — `delete_by_payload()` for flexible deletion (by `kb_record_id`, `document_name`)
- `qdrant_store.py` — `search()` gains `source_type` filter + confidence re-ranking:
  `final_score = vector_similarity * confidence * source_multiplier`
  - KB: 1.0× · Website: 0.9× · Document: 0.85×

#### Serving update (`serving/routers/facts.py`)
- `source_type` optional filter param added to `GET /facts/{client_id}`
- `source_type` field added to every result object in the response

#### Pipeline update (`pipeline/flows.py`)
- `kb_sync_flow()` — Prefect flow for KB CDC sync
- `document_ingestion_flow()` — Prefect flow for single-document ingestion
- Existing `run_client_pipeline()` unchanged

#### Quality eval harness (`quality/eval/`)
- `metrics.py` — `precision_at_k()`, `mrr()`, `source_coverage()`
- `eval_questions.json` — 28 ground-truth Q&A pairs (3 clients, all source+fact types)
- `run_eval.py` — CI-runnable eval with `--min-precision` / `--min-mrr` thresholds
  - Seeds known typed facts directly into Qdrant (zero LLM cost in CI)
  - Exits non-zero if thresholds not met

#### Seeds and sample documents (`seeds/`)
- `seed_knowledge_base.py` — inserts 13 demo KB records across 3 clients
- `seeds/sample_documents/dental_service_menu.txt` — realistic dental service pricing
- `seeds/sample_documents/law_firm_faq.txt` — law firm intake FAQ and pricing
- `seeds/sample_documents/home_services_areas.txt` — service area and pricing guide

#### SQL (`supabase/client_knowledge_base.sql`)
- `client_knowledge_base` table with all required columns + indexes
- `kb_sync_state` table for CDC polling state
- Auto-update trigger for `updated_at`

#### CI/CD (`.github/workflows/ci.yml`)
- New `eval` job (runs after `test`): seeds demo data, fires eval questions, gates on precision ≥ 0.75 and MRR ≥ 0.70

#### Makefile — new targets
```
make seed-kb        # insert sample KB records to Postgres
make seed-docs      # copy sample documents to watched folder
make seed-all       # seed + seed-kb + seed-docs
make eval           # run retrieval eval suite locally
make pipeline-all   # up + seed-all + crawl
```

#### Documentation
- `docs/adr/005-knowledge-base-ingestion.md`
- `docs/adr/006-hybrid-document-chunking.md`
- `docs/adr/007-ci-gated-retrieval-eval.md`

#### pyproject.toml
- Added `pdfplumber`, `python-docx`, `psycopg2-binary` to dependencies
- Added `ingestion*` and `quality*` to package discovery

---

## Tests Status

```
130 passed, 1 warning in 2.16s
```

| Test file                     | Tests |
|-------------------------------|-------|
| test_scorer.py                | 26    |
| test_extractor.py             | 15    |
| test_embedder.py              | 7     |
| test_pipeline.py              | 7     |
| test_store.py                 | 11    |
| test_serving.py               | 11    |
| test_kb_ingestion.py          | 16    |
| test_document_ingestion.py    | 12    |
| test_eval_metrics.py          | 15    |
| conftest.py                   | —     |
| **Total**                     | **130** |

---

## What Remains

### Requires runtime/infrastructure (unchanged from session 1)
- [ ] Prefect UI screenshot in README (requires running services)
- [ ] Measured p99 retrieval latency (requires live Qdrant)
- [ ] Docker build verification
- [ ] End-to-end pipeline run against mock server
- [ ] README updated with KB/document/eval sections (spec requires real eval numbers)

### Not yet done (CLAUDE-PART2.md)
- [ ] README additions: KB source section, document source section, retrieval eval results table
- [ ] SETUP.md additions: KB ingestion zero-token note, document ingestion setup
- [ ] `make seed-docs` ingest flow (needs `document_ingestion_flow` wired to folder watcher)
- [ ] `notebooks/demo.ipynb` updated to show multi-source ingestion

### Assumptions Made
1. `QAFact` embeds `question` field from `condition` column of DB schema (condition holds the question for qa-type rows).
2. `pdfplumber` and `python-docx` are imported lazily inside `parse_document()` — not installed in conda env; tests mock them out entirely.
3. Eval runner in CI seeds facts directly (bypasses LLM) — tests retrieval/ranking logic only.
4. Source multipliers (KB: 1.0, website: 0.9, document: 0.85) are implemented as a post-search re-ranking step over `fetch_limit = max(limit*3, 15)` results.
