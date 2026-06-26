-- Client Knowledge Base schema
-- Human-curated facts that override or supplement website-crawled facts.
-- Rows are polled via updated_at CDC pattern and synced into Qdrant.

CREATE TABLE IF NOT EXISTS client_knowledge_base (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    client_id       VARCHAR NOT NULL,
    fact_type       VARCHAR NOT NULL,  -- 'qa', 'conditional', 'talking_point', 'pricing_override'
    title           VARCHAR,           -- short label for the admin UI
    condition       TEXT,              -- for conditional facts: the IF clause / question
    response        TEXT NOT NULL,     -- the answer / THEN clause / talking point
    exception_note  TEXT,              -- for conditional facts: the UNLESS clause
    priority        INTEGER DEFAULT 5, -- 1-10, higher = ranks first in retrieval
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now(),
    created_by      VARCHAR            -- admin user who authored it
);

CREATE INDEX IF NOT EXISTS idx_kb_client_id  ON client_knowledge_base(client_id);
CREATE INDEX IF NOT EXISTS idx_kb_updated_at ON client_knowledge_base(updated_at);
CREATE INDEX IF NOT EXISTS idx_kb_fact_type  ON client_knowledge_base(fact_type);
CREATE INDEX IF NOT EXISTS idx_kb_is_active  ON client_knowledge_base(is_active);

-- Auto-update updated_at on row changes
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_kb_updated_at ON client_knowledge_base;
CREATE TRIGGER trg_kb_updated_at
    BEFORE UPDATE ON client_knowledge_base
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Pipeline state table: tracks last_synced_at per client for CDC polling
CREATE TABLE IF NOT EXISTS kb_sync_state (
    client_id       VARCHAR PRIMARY KEY,
    last_synced_at  TIMESTAMPTZ DEFAULT '1970-01-01T00:00:00Z',
    updated_at      TIMESTAMPTZ DEFAULT now()
);
