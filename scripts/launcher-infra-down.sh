#!/bin/bash
# launcher-infra-down.sh — Stop Docker + Ollama infrastructure
# Called by "Infra Down.app" double-click

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

notify() {
  osascript -e "display notification \"$1\" with title \"Infra Down\"" 2>/dev/null
}

log() {
  echo "[$(date '+%H:%M:%S')] $1"
}

log "Stopping infrastructure..."

# ─── Ollama ───────────────────────────────────────────────────────────────────
ollama_pids=$(pgrep -x ollama 2>/dev/null)
if [ -n "$ollama_pids" ]; then
  echo "$ollama_pids" | xargs kill 2>/dev/null
  log "Ollama: stopped ✓"
else
  log "Ollama: not running"
fi

# ─── Docker ───────────────────────────────────────────────────────────────────
if osascript -e 'tell application "System Events" to (name of processes) contains "Docker"' 2>/dev/null | grep -q true; then
  osascript -e 'tell application "Docker" to quit' 2>/dev/null
  log "Docker: quit requested ✓"
else
  log "Docker: not running"
fi

log "Infrastructure down ✓"
notify "Docker + Ollama stopped ✓"
