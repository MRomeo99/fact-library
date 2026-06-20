# ADR 003 — Fact-typed chunks over character-count chunks

**Status:** Accepted  
**Date:** 2025-06-01

## Context

Most RAG pipelines chunk source documents by character count (e.g., 512 characters with
overlap). This is simple, model-agnostic, and works well for open-ended Q&A.

The Client Fact Library has a different retrieval requirement: AI agents need to ask
structured questions like:

- "What are the prices for this business?" → retrieve `pricing` facts only
- "Where is this business located?" → retrieve `location` facts only
- "What awards has this business won?" → retrieve `credibility` facts only

Character-count chunks cannot answer these questions with precision — a chunk might contain
pricing information, service information, and contact details all mixed together.

## Decision

**One Pydantic fact object = one Qdrant point.** Facts are typed, structured objects
extracted by an LLM, not raw text segments.

## Rationale

### The typed retrieval advantage

Each Qdrant point carries a `fact_type` payload field indexed as a keyword. A query for
pricing facts filters on `fact_type = "pricing"` before applying vector similarity search.
This means:

```python
store.search(client_id="abc", query_vector=..., fact_type="pricing")
```

returns only pricing facts, ranked by semantic relevance to the query. Character-count
chunks cannot provide this precision without additional post-processing.

### The embed-text strategy

The embedded text is `f"{fact_type}: {content}"` — the type prefix improves retrieval
accuracy for typed queries. When a user asks "what are your prices?", the query embeds
close to `"pricing: consultation is $150 per session"` rather than a generic chunk
that happens to contain a price.

### Structured metadata

Each fact carries `confidence`, `source_url`, `extracted_at`, and `raw_evidence` fields.
Agents can filter by confidence threshold, surface source URLs for citations, and compute
`fact_age_days` for freshness checks. Character-count chunks have no equivalent structure.

## Tradeoffs

- **LLM extraction required** — character-count chunking is simpler and model-agnostic.
  Fact extraction adds latency (one LLM call per page) and cost.
- **Quality dependency** — if LLM extraction quality is low (hallucinated facts, missed
  facts), retrieval quality suffers. Mitigated by the `raw_evidence` field (enables human
  review), the `confidence` threshold filter (< 0.5 discarded), and the Pydantic
  validation layer (rejects malformed responses).
- **Sparse results** — a page with no clear pricing information will produce zero pricing
  facts. The agent should handle empty results gracefully; this is architecturally correct
  behavior, not a bug.

## Swap Path

If LLM extraction proves too expensive or unreliable for a specific client:
- Fall back to character-count chunking at the `CrawledPage` level
- Upsert raw text chunks as `fact_type = "general"` with `confidence = 0.5`
- The same Qdrant collection and retrieval API work without any changes
