#!/bin/bash
# Culinary Mind — One-click launch
# Starts ce-hub daemon + tmux TUI

# Lock Node to Homebrew current (node@25.9) — avoids better-sqlite3 ABI mismatch
# when both node and node@20 are installed (PATH would otherwise pull node@20 v20 → ABI v115)
export PATH="/opt/homebrew/opt/node/bin:$PATH"

export CE_HUB_CWD="$HOME/culinary-mind"
export CE_HUB_D68_SESSIONS=1
export CE_HUB_D68_QUARANTINE=1
export CE_HUB_D68_ACKS=1

# Kill old daemon if running
lsof -t -iTCP:8750 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null

# Start daemon
cd "$CE_HUB_CWD/ce-hub"
CE_HUB_CWD="$CE_HUB_CWD" npx tsx src/index.ts > "$CE_HUB_CWD/ce-hub/logs/daemon.log" 2>&1 &

sleep 3

# Launch tmux TUI
bash "$CE_HUB_CWD/ce-hub/scripts/tui-layout.sh" --reset

# Attach
if [ -n "$TMUX" ]; then
  tmux switch-client -t cehub
else
  tmux attach -t cehub
fi
