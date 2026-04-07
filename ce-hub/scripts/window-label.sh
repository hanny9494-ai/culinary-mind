#!/bin/bash
# window-label.sh — Return colored label block for tmux status bar
#
# Usage: window-label.sh <window_name> [active|inactive]
#
# Reads .ce-hub/state/attention.json to check if window has pending attention.
#
# Colors:
#   active   → orange  bg=colour214 fg=colour234 bold
#   attention → red    bg=colour196 fg=colour231 bold
#   inactive  → grey   bg=colour237 fg=colour245
#
# Output: full tmux #[...] format string including padding and separator reset.

WINDOW="${1:-?}"
STATE="${2:-inactive}"  # "active" or "inactive"

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
ATTN_FILE="$CE_HUB_CWD/.ce-hub/state/attention.json"

# Map agent name → 9-char padded display label
case "$WINDOW" in
  cc-lead)              LABEL="cc-lead  " ;;
  coder)                LABEL="coder    " ;;
  researcher)           LABEL="research " ;;
  architect)            LABEL="arch     " ;;
  pipeline-runner)      LABEL="pipeline " ;;
  code-reviewer)        LABEL="reviewer " ;;
  ops)                  LABEL="ops      " ;;
  open-data-collector)  LABEL="datacol  " ;;
  wiki-curator)         LABEL="wiki-cur " ;;
  *)                    LABEL="$(printf '%-9s' "$WINDOW")" ;;
esac

# Check attention flag (fast: single python3 call, cached file read)
has_attention=false
if [ -f "$ATTN_FILE" ]; then
  val=$(python3 -c "
import json, sys
try:
  d = json.load(open('$ATTN_FILE'))
  print('true' if d.get('$WINDOW') else 'false')
except:
  print('false')
" 2>/dev/null)
  [ "$val" = "true" ] && has_attention=true
fi

if [ "$STATE" = "active" ]; then
  # Active window: orange
  echo "#[bg=colour214,fg=colour234,bold]  ${LABEL}  #[bg=colour234,fg=colour214]#[default]"
elif $has_attention; then
  # Attention: red (flash via low status-interval)
  echo "#[bg=colour196,fg=colour231,bold]  ${LABEL}  #[bg=colour234,fg=colour196]#[default]"
else
  # Normal inactive: dark grey
  echo "#[bg=colour237,fg=colour245,nobold]  ${LABEL}  #[bg=colour234]#[default]"
fi
