# ADR 004 — Prefect over Dagster

**Status:** Accepted  
**Date:** 2025-06-01

## Context

The Client Fact Library pipeline has 7 stages: discover → score → crawl → incremental check →
extract → embed → upsert. This pipeline needs:

1. Scheduling (nightly recrawl at 3 AM)
2. Retries on network failures
3. Observability (which pages were crawled, how many facts extracted)
4. Local development without cloud dependencies

Two orchestrators were evaluated:

- **Prefect** — Python-native, `@flow` / `@task` decorator pattern, lightweight local server
- **Dagster** — used in `beacon-lakehouse` (the companion portfolio project)

## Decision

**Prefect** is the orchestrator for this project.

## Rationale

### Fit for task-based pipelines

The crawl pipeline is a linear sequence of tasks, not a complex asset graph.
Prefect's `@flow` / `@task` decorator pattern maps naturally:

```python
@task(retries=2)
def crawl_page(url: str) -> CrawledPage: ...

@task(retries=1)
def extract_facts(page: CrawledPage, ...) -> list[AnyFact]: ...

@flow
def run_client_pipeline(client_id: str, base_url: str) -> dict: ...
```

Dagster's asset-based model is better suited for data warehouse pipelines (like
`beacon-lakehouse`) where assets have complex dependency graphs and incremental
materialization semantics.

### Local development simplicity

Prefect's local server starts with a single command:
```
prefect server start
```

The Prefect UI is available at `http://localhost:4200` with no additional configuration.
Dagster requires more setup for local development.

### Portfolio differentiation

The beacon-lakehouse project already demonstrates Dagster expertise. Using Prefect here:
1. Shows familiarity with multiple Python orchestration tools
2. Demonstrates the ability to choose the right tool for the context
3. The ADR explains the rationale — making the choice an active, reasoned decision

## Tradeoffs

- **Two orchestrators across the portfolio** — a visitor exploring both projects sees
  Dagster (beacon-lakehouse) and Prefect (client-fact-library). This is intentional and
  demonstrates breadth. The ADR is the explanation.
- **No asset lineage** — Prefect flows don't model data assets with the richness Dagster
  provides. For this pipeline's scope, this isn't needed.

## Swap Path

Prefect OSS → Prefect Cloud:
1. Run `prefect cloud login`
2. Set `PREFECT_API_URL` to the cloud endpoint
3. Zero code changes required

Prefect → Dagster (if portfolio consistency is prioritized):
- Replace `@flow` / `@task` with `@asset` / `@job` definitions
- The pipeline logic (crawl, extract, embed, upsert) is unchanged
- Note this in the ADR update as a future consideration
