# CE-Hub System Entry Point

You are a new LLM session connecting to the culinary-engine project. Read these files in order:

## Project Context
1. `wiki/STATUS.md` — Current project status (auto-compiled daily)
2. `wiki/ARCHITECTURE.md` — 7-layer knowledge architecture
3. `wiki/DECISIONS.md` — Numbered technical decisions (#22-#42+)
4. `wiki/CHANGELOG.md` — Recent daily changes

## Operating Manual
5. `~/culinary-engine/CLAUDE.md` — Full project handbook (agent roles, protocols, constraints)

## System Maintenance
- ce-hub code: `~/culinary-engine/ce-hub/`
- TUI layout: `ce-hub/scripts/layout.sh`
- Wiki compiler: `ce-hub/scripts/compile-wiki.py`
- Task board: `ce-hub/scripts/task-board.py`
- Handover doc: `ce-hub/docs/handover-v2-tmux-tui.md`

## API Access
- REST API: `http://localhost:8750/api/`
- Context: `GET /api/context` — compiled onboarding prompt
- Wiki page: `GET /api/wiki/:filename` — read any wiki page
- Wiki browser: `http://localhost:8750/wiki/` — web UI
- Health: `GET /api/health` — daemon status
- Tasks: `GET /api/tasks` — task queue
- Agents: `GET /api/agents` — agent status

## Principles (Karpathy + Gstack)
- **wiki is compiled, never manually edited** — raw/ → LLM → wiki/
- **memory is compass** — points to wiki, doesn't store content
- **User Sovereignty** — AI recommends, Jeff decides
- **CC Lead orchestrates, doesn't execute** — coding → coder, pipeline → pipeline-runner
