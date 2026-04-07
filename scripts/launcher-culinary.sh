#!/bin/bash
# launcher-culinary.sh — Smart launcher for Culinary Mind
# Called by "Culinary Mind.app" double-click
# Smart: attach if running, cold-start if not

# Ensure Homebrew bins are in PATH (needed when launched from Finder .app)
export PATH="/opt/homebrew/bin:/opt/homebrew/opt/node/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

CE_HUB_CWD="$HOME/culinary-mind"

daemon_running() {
  lsof -t -iTCP:8750 -sTCP:LISTEN 2>/dev/null | grep -q .
}

tmux_session_exists() {
  /opt/homebrew/bin/tmux has-session -t cehub 2>/dev/null
}

# Determine what needs to be done
if daemon_running && tmux_session_exists; then
  # Everything running — just attach
  CMD="exec /opt/homebrew/bin/tmux attach -t cehub"
elif daemon_running && ! tmux_session_exists; then
  # Daemon running but TUI missing — recreate TUI and attach
  CMD="export CE_HUB_CWD='$CE_HUB_CWD' PATH='/opt/homebrew/bin:/opt/homebrew/opt/node/bin:/usr/local/bin:/usr/bin:/bin'; bash '$CE_HUB_CWD/ce-hub/scripts/tui-layout.sh' --reset && exec /opt/homebrew/bin/tmux attach -t cehub"
else
  # Cold start — run start.sh which handles daemon + TUI + attach
  CMD="export PATH='/opt/homebrew/bin:/opt/homebrew/opt/node/bin:/usr/local/bin:/usr/bin:/bin:\$PATH'; bash '$CE_HUB_CWD/start.sh'"
fi

# Open Terminal window and run the command
osascript <<SCRIPT
tell application "Terminal"
  activate
  do script "$CMD"
end tell
SCRIPT
