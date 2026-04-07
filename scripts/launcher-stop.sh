#!/bin/bash
# launcher-stop.sh — Stop Culinary Mind daemon + tmux session
# Called by "Stop Culinary.app" double-click

# Ensure Homebrew bins in PATH
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/node/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

CE_HUB_CWD="$HOME/culinary-mind"

# Kill daemon (port 8750)
pids=$(lsof -t -iTCP:8750 -sTCP:LISTEN 2>/dev/null)
if [ -n "$pids" ]; then
  echo "$pids" | xargs kill 2>/dev/null
  echo "Daemon stopped."
else
  echo "Daemon was not running."
fi

# Kill tmux session
if /opt/homebrew/bin/tmux has-session -t cehub 2>/dev/null; then
  /opt/homebrew/bin/tmux kill-session -t cehub 2>/dev/null
  echo "Tmux session 'cehub' killed."
else
  echo "No tmux session 'cehub' found."
fi

# macOS notification
osascript -e 'display notification "Culinary Mind stopped." with title "Culinary Mind"' 2>/dev/null

echo "Done."
