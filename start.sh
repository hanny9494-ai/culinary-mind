#!/bin/bash
# Culinary Mind — One-click launch
# Starts ce-hub daemon + tmux TUI

export CE_HUB_CWD="$HOME/culinary-mind"

# Kill old daemon if running
lsof -t -iTCP:8750 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null

# Start daemon
cd "$CE_HUB_CWD/ce-hub"
CE_HUB_CWD="$CE_HUB_CWD" npx tsx src/index.ts > "$CE_HUB_CWD/ce-hub/logs/daemon.log" 2>&1 &

sleep 3

# Launch tmux TUI
bash "$CE_HUB_CWD/ce-hub/scripts/layout.sh" --reset

# Attach
if [ -n "$TMUX" ]; then
  tmux switch-client -t cehub
else
  tmux attach -t cehub
fi
