#!/bin/bash
# clear-attention.sh — Clear attention flag for a window when user selects it
# Usage: clear-attention.sh <window_name>
# Called by: tmux after-select-window hook

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
WINDOW="${1:-}"
ATTN_FILE="$CE_HUB_CWD/.ce-hub/state/attention.json"

[ -z "$WINDOW" ] && exit 0
[ ! -f "$ATTN_FILE" ] && exit 0

python3 -c "
import json, sys
attn_file = '$ATTN_FILE'
window = '$WINDOW'
try:
    with open(attn_file) as f:
        d = json.load(f)
    if d.get(window):
        d[window] = False
        with open(attn_file, 'w') as f:
            json.dump(d, f, indent=2)
except Exception as e:
    sys.exit(0)
" 2>/dev/null
