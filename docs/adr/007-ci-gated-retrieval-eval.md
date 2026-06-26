# ADR 007 — CI-Gated Retrieval Evaluation

**Status:** Accepted  
**Date:** 2025-06-01

## Context

Prompt changes, fact schema changes, chunking strategy changes, and source-type multiplier
adjustments can all silently degrade retrieval quality. Without a regression gate, a PR that
improves document parsing but accidentally de-ranks KB facts for the same query can merge
undetected. Manual spot-checking is insufficient at pipeline scale.

## Decision

A 28-question ground-truth evaluation suite runs in CI as a required gate before merge.

**Dataset (`quality/eval/eval_questions.json`):**
- 28 manually authored question/expected-answer-type pairs
- Covers all three source types (website, knowledge_base, document)
- Covers all major fact types (pricing, service, location, operational, conditional, qa)
- Includes 8 questions where a KB fact *must* appear in the top-3 results (KB override check)

**Metrics (`quality/eval/metrics.py`):**
- **Precision@3:** fraction of top-3 results containing the expected fact type
- **MRR (Mean Reciprocal Rank):** where does the first relevant result appear?
- **KB override rate:** fraction of KB-expected queries where a KB fact appears in top-3

**CI thresholds:**
- Precision@3 ≥ 0.75
- MRR ≥ 0.70
- (KB override rate is reported but not gated — it's a diagnostic metric)

**Eval runner (`quality/eval/run_eval.py`):**
- Seeds known typed facts directly into Qdrant (in-memory, zero LLM cost)
- Fires all 28 questions against the retrieval layer
- Computes metrics, prints a results table, exits non-zero if thresholds not met

## Tradeoffs

**For:** Catches retrieval regressions automatically. The 28-question dataset is small enough
to run in <60 seconds in CI. The KB override rate metric specifically validates the source-type
ranking model — if a PR accidentally flattens KB vs. website confidence weights, this catches it.

**Against:** 28 questions won't catch every possible regression. The eval dataset is manually
authored — it won't self-update as the product evolves. Accepted — targeted coverage of the
most business-critical retrieval scenarios provides meaningful signal without becoming a
maintenance burden.

**Versus integration tests with real LLM calls:** real LLM calls are non-deterministic and
expensive in CI. The eval seeds known facts directly, making results deterministic and free.
This is intentional — the eval tests the retrieval and ranking logic, not the extraction quality.

## Swap Path

Grow the dataset to 100–200 questions for production. Use an LLM-as-judge approach to
auto-generate ground-truth labels from new content. The `run_eval.py` runner and metrics
functions are unchanged — only the question dataset grows.
