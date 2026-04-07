#!/bin/bash
# launcher-infra-up.sh — Start Docker + Ollama infrastructure
# Called by "Infra Up.app" double-click
# Manages Studio local infra only (not Mac Mini)

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

LOG=$(mktemp /tmp/infra-up-XXXX.log)

notify() {
  osascript -e "display notification \"$1\" with title \"Infra Up\"" 2>/dev/null
}

log() {
  echo "[$(date '+%H:%M:%S')] $1" | tee -a "$LOG"
}

log "Starting infrastructure..."

# ─── Docker ───────────────────────────────────────────────────────────────────
docker_running() {
  docker info &>/dev/null
}

if docker_running; then
  log "Docker: already running ✓"
else
  log "Docker: launching Docker.app..."
  open -a Docker
  notify "Docker launching..."

  # Wait up to 60s for Docker daemon to be ready
  wait_secs=0
  while ! docker_running; do
    sleep 2
    wait_secs=$((wait_secs + 2))
    if [ $wait_secs -ge 60 ]; then
      log "Docker: timeout after 60s ✗"
      notify "Docker failed to start after 60s"
      exit 1
    fi
  done
  log "Docker: ready (${wait_secs}s) ✓"
fi

# ─── Ollama ───────────────────────────────────────────────────────────────────
ollama_running() {
  curl -s --noproxy localhost --max-time 2 http://localhost:11434/api/tags &>/dev/null
}

if ollama_running; then
  log "Ollama: already running ✓"
else
  log "Ollama: starting ollama serve..."
  # Use nohup so it survives after this script exits
  nohup /opt/homebrew/bin/ollama serve >> /tmp/ollama.log 2>&1 &
  OLLAMA_PID=$!

  # Wait up to 20s for Ollama to be ready
  wait_secs=0
  while ! ollama_running; do
    sleep 1
    wait_secs=$((wait_secs + 1))
    if [ $wait_secs -ge 20 ]; then
      log "Ollama: timeout after 20s ✗"
      notify "Ollama failed to start — check /tmp/ollama.log"
      exit 1
    fi
  done
  log "Ollama: ready (${wait_secs}s) ✓"
fi

# ─── Summary ──────────────────────────────────────────────────────────────────
log "All infrastructure up ✓"
notify "Docker + Ollama ready ✓"

# Show brief summary in Terminal if running interactively
if [ -t 1 ]; then
  echo ""
  echo "Infrastructure status:"
  echo "  Docker:  $(docker info 2>/dev/null | grep 'Server Version' | awk '{print $NF}' || echo 'running')"
  echo "  Ollama:  $(curl -s --noproxy localhost http://localhost:11434/api/tags 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(str(len(d.get("models",[])))+" models loaded")' 2>/dev/null || echo 'running')"
fi
