#!/bin/bash
# prompt-detector-install.sh — Install/uninstall prompt detector as launchd agent
# Usage:
#   bash scripts/prompt-detector-install.sh install    # install + start
#   bash scripts/prompt-detector-install.sh uninstall  # stop + remove
#   bash scripts/prompt-detector-install.sh status     # show status
#   bash scripts/prompt-detector-install.sh restart    # reload

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_SRC="$SCRIPT_DIR/prompt-detector.plist"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST_DEST="$LAUNCH_AGENTS/com.culinary-mind.prompt-detector.plist"
LABEL="com.culinary-mind.prompt-detector"
LOG="$HOME/culinary-mind/ce-hub/logs/prompt-detector.log"

case "${1:-status}" in
  install)
    mkdir -p "$LAUNCH_AGENTS"
    cp "$PLIST_SRC" "$PLIST_DEST"
    # Fix path in plist to use actual $HOME (plist can't expand vars)
    sed -i '' "s|/Users/jeff|$HOME|g" "$PLIST_DEST"
    chmod 644 "$PLIST_DEST"
    chmod +x "$SCRIPT_DIR/prompt-detector.sh"
    launchctl load "$PLIST_DEST" 2>/dev/null || launchctl bootstrap gui/$UID "$PLIST_DEST" 2>/dev/null
    echo "✓ prompt-detector installed and started"
    echo "  Logs: $LOG"
    echo "  Status: launchctl list | grep prompt-detector"
    ;;
  uninstall)
    launchctl unload "$PLIST_DEST" 2>/dev/null || launchctl bootout gui/$UID "$PLIST_DEST" 2>/dev/null
    rm -f "$PLIST_DEST"
    echo "✓ prompt-detector uninstalled"
    ;;
  restart)
    launchctl unload "$PLIST_DEST" 2>/dev/null
    sleep 1
    launchctl load "$PLIST_DEST" 2>/dev/null
    echo "✓ prompt-detector restarted"
    ;;
  status)
    echo "=== prompt-detector status ==="
    launchctl list | grep "prompt-detector" || echo "  (not loaded)"
    echo ""
    echo "=== Recent logs (last 20 lines) ==="
    [ -f "$LOG" ] && tail -20 "$LOG" || echo "  (no log file yet)"
    ;;
  *)
    echo "Usage: $0 {install|uninstall|restart|status}"
    exit 1
    ;;
esac
