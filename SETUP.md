# Setup Guide — Client Fact Library

Choose **Path A** (Portkey, recommended) for production-quality observability and automatic
model fallback, or **Path B** (direct mode) for the fastest path to running with no extra accounts.

---

## Prerequisites

- Python 3.11+
- Docker + Docker Compose
- `pip install -e ".[dev]"` (run from the repo root)
- `playwright install chromium` (for JS-rendered sites)

---

## Path A: Portkey Mode (Recommended)

Portkey acts as a gateway between the pipeline and your LLM provider. You never expose
raw provider API keys to the application — Portkey handles routing, fallback, and logging.

### Step 1 — Create a free Portkey account

Go to [portkey.ai](https://portkey.ai) and sign up (free tier available).

### Step 2 — Add your LLM provider key as a Virtual Key

1. In the Portkey dashboard, go to **Virtual Keys**
2. Click **Add Virtual Key**
3. Choose your provider:
   - **Google AI Studio** (for Gemini 2.5 Flash) — get your key at [aistudio.google.com](https://aistudio.google.com)
   - **OpenAI** (for GPT-4o-mini) — get your key at [platform.openai.com](https://platform.openai.com)
4. Paste your provider API key and save
5. Copy the **virtual key slug** (looks like `google-abc123`)

### Step 3 — Create a Portkey Config

1. In the Portkey dashboard, go to **Configs**
2. Click **Create Config** and paste this JSON (replacing the slugs):

```json
{
  "strategy": { "mode": "fallback" },
  "targets": [
    {
      "virtual_key": "YOUR_GOOGLE_VIRTUAL_KEY",
      "override_params": { "model": "gemini-2.5-flash" }
    },
    {
      "virtual_key": "YOUR_OPENAI_VIRTUAL_KEY",
      "override_params": { "model": "gpt-4o-mini" }
    }
  ]
}
```

This config tries Gemini 2.5 Flash first and automatically falls back to GPT-4o-mini.

3. Copy the **Config slug** (looks like `cf-abc123`)

### Step 4 — Configure your `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```bash
LLM_MODE=portkey
PORTKEY_API_KEY=pk-...       # from Portkey dashboard → API Keys
PORTKEY_CONFIG=cf-...        # the config slug from Step 3

EMBEDDING_MODE=local
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

### Step 5 — Run the pipeline

```bash
make up            # start Qdrant and Prefect server
make mock-server   # start mock site server (separate terminal)
make crawl         # run the pipeline against the dental mock site
```

Then query the results:

```bash
curl "http://localhost:8000/facts/demo-dental?q=what+are+your+prices&fact_type=pricing"
```

---

## Path B: Direct Mode (No Portkey Account)

In direct mode, the application calls the LLM provider SDK directly. You lose Portkey's
observability dashboard and automatic fallbacks, but there are zero account requirements
beyond the provider API key.

### Google AI Studio (Gemini 2.5 Flash — recommended)

Get a free API key at [aistudio.google.com](https://aistudio.google.com).

```bash
# In .env:
LLM_MODE=direct
LLM_PROVIDER=google
LLM_MODEL_DIRECT=gemini-2.5-flash
GOOGLE_API_KEY=AIza...

EMBEDDING_MODE=local
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

### OpenAI (GPT-4o-mini)

```bash
# In .env:
LLM_MODE=direct
LLM_PROVIDER=openai
LLM_MODEL_DIRECT=gpt-4o-mini
OPENAI_API_KEY=sk-...

EMBEDDING_MODE=local
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

Then run exactly as in Path A: `make up && make mock-server && make crawl`

---

## Switching Embedding Models

The default local embedder (`sentence-transformers/all-MiniLM-L6-v2`) runs fully offline
and produces 384-dim vectors. To switch to OpenAI's `text-embedding-3-small` (1536-dim):

```bash
EMBEDDING_MODE=openai
OPENAI_API_KEY=sk-...
```

**Important:** Switching embedding models requires recreating the Qdrant collection
because vector dimensions change. Run `make reset` before re-crawling.

---

## Production Swap Paths

| Component | Development | Production |
|-----------|-------------|------------|
| Qdrant | Local Docker | Qdrant Cloud (`QDRANT_URL` + `QDRANT_API_KEY`) |
| Prefect | Local server | Prefect Cloud (`prefect cloud login`) |
| Embeddings | Local (free) | OpenAI `text-embedding-3-small` (`EMBEDDING_MODE=openai`) |
| LLM | Portkey (direct) | Portkey with fallback config |

All swaps require only environment variable changes — no code modifications.
