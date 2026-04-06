#!/bin/bash
# switch-agent.sh — Switch agent in a specific pane (legacy wrapper)
# For new code, use pane-manager.sh switch instead.
#
# Usage:
#   switch-agent.sh <agent-name>              — switch in pane 2 (default slot)
#   switch-agent.sh <agent-name> <pane-id>    — switch in specific pane

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-engine}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
SESSION="cehub"

AGENT_NAME="$1"
PANE_TARGET="${2:-$SESSION:main.2}"

if [ -z "$AGENT_NAME" ]; then
  echo "Usage: switch-agent.sh <agent-name> [pane-id]"
  exit 1
fi

exec bash "$SCRIPTS/pane-manager.sh" switch "$PANE_TARGET" "$AGENT_NAME"
