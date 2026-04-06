#!/bin/bash
# daemon-ctl.sh — Install/manage ce-hub daemon as launchd service
#
# Usage:
#   daemon-ctl.sh install    — install + start launchd service
#   daemon-ctl.sh uninstall  — stop + remove service
#   daemon-ctl.sh start      — start service
#   daemon-ctl.sh stop       — stop service
#   daemon-ctl.sh restart    — restart service
#   daemon-ctl.sh status     — check if running
#   daemon-ctl.sh logs       — tail daemon logs

LABEL="com.cehub.daemon"
PLIST_SRC="$(cd "$(dirname "$0")" && pwd)/com.cehub.daemon.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/culinary-engine/ce-hub/logs"

case "${1:-status}" in
  install)
    mkdir -p "$LOG_DIR"
    cp "$PLIST_SRC" "$PLIST_DST"
    launchctl load "$PLIST_DST"
    echo "Installed and started $LABEL"
    echo "Logs: $LOG_DIR/"
    ;;
  uninstall)
    launchctl unload "$PLIST_DST" 2>/dev/null
    rm -f "$PLIST_DST"
    echo "Uninstalled $LABEL"
    ;;
  start)
    launchctl start "$LABEL"
    echo "Started $LABEL"
    ;;
  stop)
    launchctl stop "$LABEL"
    echo "Stopped $LABEL"
    ;;
  restart)
    launchctl stop "$LABEL" 2>/dev/null
    sleep 2
    launchctl start "$LABEL"
    echo "Restarted $LABEL"
    ;;
  status)
    if launchctl list "$LABEL" >/dev/null 2>&1; then
      PID=$(launchctl list "$LABEL" 2>/dev/null | grep PID | awk '{print $3}')
      echo "$LABEL: running (PID: $PID)"
      # Quick health check
      curl -s --noproxy localhost --max-time 2 http://localhost:8750/api/health 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f\"  uptime: {d['uptime']}s, tasks: {d['taskCount']}, agents alive: {sum(1 for a in d['agents'] if a['alive'])}\")
" 2>/dev/null || echo "  (API not responding yet)"
    else
      echo "$LABEL: not running"
    fi
    ;;
  logs)
    tail -f "$LOG_DIR/daemon.log" "$LOG_DIR/daemon.err"
    ;;
  *)
    echo "Usage: daemon-ctl.sh {install|uninstall|start|stop|restart|status|logs}"
    ;;
esac
