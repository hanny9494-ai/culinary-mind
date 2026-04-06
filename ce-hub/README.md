# ce-hub

Multi-agent orchestration dashboard for [Claude Code](https://claude.ai/claude-code). Manage multiple Claude agent sessions from a single web UI with real-time streaming, cross-agent messaging, and task tracking.

![Terminal-style UI](https://img.shields.io/badge/UI-Terminal_Style-green) ![TypeScript](https://img.shields.io/badge/TypeScript-5.5-blue) ![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

- **Multi-agent tile dashboard** — See all agent conversations simultaneously in a terminal-style grid layout
- **Hot sessions** — Persistent `claude` processes with `stream-json` for fast responses (no cold start per message)
- **Cross-agent dispatch** — Type `@agent: message` in any tile to route messages between agents
- **Task DAG engine** — Create tasks with dependencies, automatic downstream triggering, retry with backoff
- **Resource queues** — Concurrent limits per model tier (opus×3, flash×3, ollama×1)
- **WebSocket streaming** — Real-time message updates via WebSocket
- **Light/dark theme** — Toggle with one click
- **API key management** — Settings panel for managing API keys at runtime
- **Session resume** — ContextBuilder generates resume prompts when agent context fills up

## Quick Start

```bash
git clone https://github.com/hanny9494-ai/ce-hub.git
cd ce-hub

# Install backend
npm install

# Install frontend
cd frontend && npm install && cd ..

# Start both (backend :8750 + frontend :5173)
npm run dev
```

Open **http://localhost:5173**

## Requirements

- Node.js 20+
- [Claude Code CLI](https://claude.ai/claude-code) installed and authenticated (`claude` in PATH)

## Architecture

```
Browser (React, :5173)
  ↕ WebSocket
ce-hub (Node.js, :8750)
  ├── AgentManager    → persistent claude processes (stream-json)
  ├── TaskEngine      → DAG + toposort + p-queue
  ├── MessageRouter   → EventEmitter2 + WebSocket
  ├── Bridge          → @agent: cross-agent dispatch
  ├── StateStore      → SQLite (better-sqlite3)
  └── ContextBuilder  → session resume prompt generation
```

## Environment Variables

All optional — defaults work for local development:

| Variable | Default | Description |
|----------|---------|-------------|
| `CE_HUB_DB_PATH` | `./ce-hub.db` | SQLite database path |
| `CE_HUB_AGENTS_DIR` | `.claude/agents` | Agent definition files |
| `CE_HUB_CWD` | `process.cwd()` | Working directory for claude processes |
| `CE_HUB_STATUS_PATH` | `STATUS.md` | Path to STATUS.md for context builder |
| `CE_HUB_CLAUDE_MD_PATH` | `CLAUDE.md` | Path to CLAUDE.md for context builder |
| `CE_HUB_MOCK` | — | Set to `1` for mock mode (no real claude calls) |

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check + queue stats |
| GET | `/api/agents` | List all agents |
| POST | `/api/agents/:name/message` | Send message to agent |
| GET | `/api/agents/:name/resume-prompt` | Generate resume prompt |
| GET | `/api/tasks` | List tasks (filter: `?status=`, `?toAgent=`) |
| POST | `/api/tasks` | Create task |
| GET | `/api/tasks/:id` | Get task |
| PATCH | `/api/tasks/:id` | Update task |
| DELETE | `/api/tasks/:id` | Cancel task |
| POST | `/api/tasks/:id/retry` | Retry failed task |
| GET | `/api/events` | Recent events |
| POST | `/api/settings/keys` | Save API keys |

## Agent Definitions

Place `.md` files in `.claude/agents/` with YAML frontmatter:

```markdown
---
name: researcher
description: Searches external resources and evaluates their value
tools: Read, Bash, WebSearch
model: sonnet
---

You are a researcher agent. Your job is to...
```

## Cross-Agent Dispatch

Type `@agent: message` in any tile:

```
@researcher: find papers about food pairing algorithms
@coder: write a script to parse FlavorDB2 data
```

The message appears in both the source and target agent tiles, with results auto-reported back.

## License

MIT
