# ADR 006 — Hybrid Chunking for Document Ingestion

**Status:** Accepted  
**Date:** 2025-06-01

## Context

The core fact-based chunking strategy (one Pydantic fact object = one Qdrant point) works
well for web pages: pages are short, focused, and the LLM can extract 5–15 facts from a
single page in one call. Documents are different — a dental service menu may be 2,000 words;
a franchise agreement, 20,000 words. Sending an entire document to the LLM in one call
hits token limits and produces lower-quality extraction because context is diluted.

## Decision

Use a hybrid two-pass strategy for documents:

1. **Structural split first:** divide the document on paragraph/section boundaries
   (double newlines, heading markers). This mirrors how a human would read the document
   section by section.

2. **Max-token guard:** if any section exceeds ~1,500 tokens (≈1,125 words using a
   0.75 words/token ratio), split it further by word count.

3. **Fact extraction per chunk:** run the same Portkey/LLM extraction prompt on each
   chunk independently. Each chunk is treated as a mini-page with `page_type="document"`
   and `page_score=3`.

4. **Document metadata in payload:** each resulting Qdrant point carries `document_name`,
   `page_number` (sequential chunk index), and `section_heading` (nearest heading above
   the chunk). This enables citation in the API response.

Implementation: `ingestion/document_ingestion.py` — `chunk_document()` + `ingest_document()`.

## Tradeoffs

**For:** Handles real-world document sizes without hitting LLM context limits. Structural
boundaries (headings, paragraphs) produce more coherent chunks than character-count slicing.
`document_name` + `page_number` in the API response lets the agent cite sources precisely.

**Against:** Some document sections will contain multiple facts that could be more precisely
separated with dedicated schemas. Accepted — the extraction prompt handles multi-fact sections
adequately, and the `raw_evidence` field enables human review when needed.

**Versus pure fact extraction on the whole document:** token limits make this infeasible for
real documents. The hybrid approach is the pragmatic production choice.

## Swap Path

For larger document corpora: replace `chunk_document()` with a proper text splitter
(LangChain `RecursiveCharacterTextSplitter` or `unstructured.io` for richer structure
detection). The `ingest_document()` function interface is unchanged — only the chunking
implementation swaps.
