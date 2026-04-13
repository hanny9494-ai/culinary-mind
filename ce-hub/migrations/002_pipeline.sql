-- Migration 002: pipeline_runs + resource_locks tables
-- For MCP Server: pipeline heartbeat tracking + concurrency control

CREATE TABLE IF NOT EXISTS pipeline_runs (
  id TEXT PRIMARY KEY,
  book_id TEXT NOT NULL,
  track TEXT DEFAULT 'A',
  step INTEGER NOT NULL,
  progress_pct REAL DEFAULT 0,
  current_chunk TEXT,
  eta_minutes REAL,
  status TEXT NOT NULL DEFAULT 'running', -- running/done/failed/stale
  started_at INTEGER NOT NULL,
  last_heartbeat INTEGER NOT NULL,
  completed_at INTEGER,
  metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pipeline_book ON pipeline_runs(book_id, step);
CREATE INDEX IF NOT EXISTS idx_pipeline_status ON pipeline_runs(status, last_heartbeat);

CREATE TABLE IF NOT EXISTS resource_locks (
  resource TEXT NOT NULL,    -- 'ollama', 'gemini_flash', 'gemini_pro', 'lingya_opus'
  slot_id TEXT NOT NULL,     -- unique slot identifier
  holder TEXT NOT NULL,      -- who holds the lock (pipeline_id or agent_name)
  acquired_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,  -- TTL-based expiry to prevent deadlock
  PRIMARY KEY (resource, slot_id)
);
CREATE INDEX IF NOT EXISTS idx_locks_resource ON resource_locks(resource, expires_at);

CREATE TABLE IF NOT EXISTS book_queue (
  book_id TEXT PRIMARY KEY,
  track TEXT NOT NULL DEFAULT 'A',
  priority INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'pending',  -- pending/assigned/prep_done/extract_done/qc_done
  assigned_to TEXT,   -- pipeline_id that claimed this book
  assigned_at INTEGER,
  prep_done_at INTEGER,
  extract_done_at INTEGER,
  qc_done_at INTEGER,
  error TEXT,
  metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON book_queue(status, priority);
