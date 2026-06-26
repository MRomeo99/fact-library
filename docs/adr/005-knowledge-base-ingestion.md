# ADR 005 — Knowledge Base as a First-Class Ingestion Source

**Status:** Accepted  
**Date:** 2025-06-01

## Context

Website crawling captures the business's public-facing content. But it misses facts the business
explicitly curates and controls — call scripts, pricing exceptions, conditional handling rules,
and edge case responses that never appear on the website. A voice or chat agent relying only on
crawled content will give the wrong answer when a caller asks about the cancellation policy or
payment plan exceptions.

## Decision

Add a Postgres table (`client_knowledge_base`) as a second ingestion source. Human-authored KB
records are synced into Qdrant alongside crawled facts. Key properties:

- **Source type:** `knowledge_base`
- **Confidence:** defaults to 1.0 (human-authored = full confidence)
- **Ingestion pattern:** CDC-style `updated_at` polling — no content hash needed
- **LLM cost:** zero — no LLM extraction step; the `response` field is embedded directly
- **Ranking:** `source_multiplier = 1.0` (highest) — KB facts rank above website and document facts

New fact types added to `extractor/schemas.py`:
- `ConditionalFact` — explicit if/then business rule (condition, response, exception_note)
- `QAFact` — curated question/answer pair; also covers talking_point and pricing_override records

## Tradeoffs

**For:** Zero LLM cost per sync. Human-curated facts are authoritative. Override mechanism is
explicit and controllable. The `ConditionalFact` schema captures business logic that no crawler
could extract — cancellation rules, escalation paths, pricing exceptions.

**Against:** Requires an admin UI or DB access for the business to manage records — higher
operational overhead than pure crawling. The pipeline now has a Postgres dependency alongside
Qdrant.

## Swap Path

Any CMS or headless CMS with an `updated_at` field can replace the Postgres KB table.
The `fetch_kb_rows_since()` function in `ingestion/kb_ingestion.py` is the only place
that touches the DB schema — replace that function to swap the source.
