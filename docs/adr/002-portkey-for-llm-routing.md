# ADR 002 — Portkey for LLM routing

**Status:** Accepted  
**Date:** 2025-06-01

## Context

The fact extraction step requires calling an LLM (either Gemini 2.5 Flash or GPT-4o-mini).
Two design questions arise:

1. **Where does model selection live?** In code (`model="gemini-2.5-flash"`) or in configuration?
2. **How do we handle failover** if one provider is slow or returns errors?

Hardcoding model names in application code creates fragility: changing models requires
code changes and redeployments.

## Decision

**Portkey** is the LLM gateway for this project. All LLM calls route through Portkey;
the application code never calls OpenAI or Google directly.

## Rationale

Portkey provides:

1. **Model selection as configuration** — users set model choice in the Portkey dashboard,
   not in source code. The application receives a `PORTKEY_CONFIG` slug and forwards all
   calls through the Portkey API. Switching from Gemini to GPT-4o-mini is a dashboard change.

2. **Automatic fallback** — the Portkey Config defines a fallback strategy. If Gemini returns
   an error or exceeds latency, Portkey automatically routes to GPT-4o-mini. No retry logic
   needed in application code.

3. **Observability** — every LLM call is logged in the Portkey dashboard with latency,
   token count, cost, and success/failure. This is production-grade observability with zero
   additional instrumentation.

4. **Portfolio differentiation** — Portkey is a strong resume signal for AI engineering roles.
   It demonstrates familiarity with LLM gateway patterns, a production best practice that
   simple "call the API directly" approaches miss.

## Direct mode

A `direct` mode (`LLM_MODE=direct`) is provided for users who don't want to create a
Portkey account. In direct mode, the application calls the provider SDK directly via a
thin OpenAI-compatible adapter. The same `FactExtractor` code runs in both modes —
the switch is encapsulated in `extractor/llm_client.py`.

## Tradeoffs

- **Portkey account required** (in default mode) — adds a setup step. Mitigated by direct mode.
- **External dependency** — if Portkey is unavailable, all extraction fails. Mitigated by direct
  mode as a fallback and by Portkey's SLA for production plans.
- **Cost** — Portkey's free tier covers development volume; production usage may require a paid plan.

## Swap Path

To replace Portkey with a self-hosted alternative:
- Use **LiteLLM** as a self-hosted proxy — it exposes an OpenAI-compatible API and supports
  the same multi-provider routing as Portkey.
- Change `PORTKEY_API_KEY` and `PORTKEY_CONFIG` to point to the LiteLLM endpoint.
- No application code changes required.
