CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  session_id TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_conv_agent ON conversations(agent_name);
CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'text',
  token_count INTEGER,
  created_at INTEGER NOT NULL,
  metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  depends_on TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending',
  priority INTEGER NOT NULL DEFAULT 1,
  model_tier TEXT NOT NULL DEFAULT 'opus',
  payload TEXT NOT NULL DEFAULT '{}',
  result TEXT,
  error TEXT,
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retries INTEGER NOT NULL DEFAULT 3,
  created_at INTEGER NOT NULL,
  started_at INTEGER,
  completed_at INTEGER,
  metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_to ON tasks(to_agent, status);

CREATE TABLE IF NOT EXISTS agent_sessions (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  agent_name TEXT NOT NULL,
  sdk_session_id TEXT,
  pid INTEGER,
  status TEXT NOT NULL DEFAULT 'stopped',
  context_tokens INTEGER DEFAULT 0,
  context_limit INTEGER DEFAULT 180000,
  started_at INTEGER,
  stopped_at INTEGER,
  last_heartbeat INTEGER,
  metadata TEXT DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_as_name ON agent_sessions(agent_name, status);

CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  source TEXT NOT NULL,
  target TEXT,
  payload TEXT DEFAULT '{}',
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, created_at);

CREATE TABLE IF NOT EXISTS cost_log (
  id TEXT PRIMARY KEY,
  agent_name TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cost_usd REAL DEFAULT 0,
  task_id TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cost_agent ON cost_log(agent_name, created_at);
CREATE INDEX IF NOT EXISTS idx_cost_time ON cost_log(created_at);
