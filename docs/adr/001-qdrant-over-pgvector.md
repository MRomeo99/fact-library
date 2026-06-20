# ADR 001 — Qdrant over pgvector

**Status:** Accepted  
**Date:** 2025-06-01

## Context

The Client Fact Library needs a vector database that enables typed, filtered fact retrieval.
The primary use case is: "find all `pricing` facts for client ABC that semantically match
the query `what are your consultation fees`."

This requires vector similarity search combined with a structured filter on `fact_type`.

Two candidates were evaluated:

- **Qdrant** — purpose-built vector DB, Docker-native, first-class payload filtering
- **pgvector** — Postgres extension, runs in the same Postgres instance as operational data

## Decision

**Qdrant** is the primary vector store for this project.

## Rationale

| Criterion | Qdrant | pgvector |
|-----------|--------|----------|
| `fact_type` filtering | Native payload filter (`must: [{key: "fact_type", match: {value: "pricing"}}]`) | Requires `WHERE` clause or JSONB operator — works but feels bolted on |
| Indexing keyword fields | `create_payload_index(field_name, PayloadSchemaType.KEYWORD)` — first-class | No equivalent — rely on Postgres indexes |
| Resume keyword signal | Strong ("Qdrant experience" is listed in AI engineering JDs) | Weaker (pgvector is ubiquitous but not distinctive) |
| Portfolio differentiation | High — demonstrates purpose-built vector DB expertise | Low — pgvector is a safe default, not a differentiator |
| Operational simplicity | Single Docker container | Requires Postgres with pgvector extension enabled |

## Tradeoffs

- **Extra service:** pgvector runs inside the same Postgres instance already needed for operational
  data. Qdrant is a separate Docker container, adding one service to `docker-compose.yml`.
- **Data duplication:** If the project later adds an operational Postgres database, facts and
  structured data will live in separate stores. This is acceptable for a portfolio project and
  mirrors production AI platforms where the vector store is purpose-built.

## Swap Path

Qdrant OSS → Qdrant Cloud:
1. Create a Qdrant Cloud cluster
2. Update `QDRANT_URL` and `QDRANT_API_KEY` in `.env`
3. Zero code changes required

The `QdrantClient` constructor already reads these from env vars.
