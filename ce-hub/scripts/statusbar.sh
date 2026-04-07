#!/bin/bash
# statusbar.sh — ce-hub TUI v2: Window nav bar + attention state from attention.json
#
# Colors:
#   active window    -> orange (#[bg=colour214,fg=colour234,bold])
#   attention window -> red    (#[bg=colour196,fg=colour231,bold])
#   inactive window  -> dark grey (#[bg=colour237,fg=colour245])
#
# Attention is driven by .ce-hub/state/attention.json — NOT tmux monitor-activity.
# window-label.sh reads attention.json per call to pick the right color style.

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
SESSION="cehub"
CONF_FILE="/tmp/cehub-statusbar.conf"

cat > "$CONF_FILE" << TMUXCONF
# ce-hub statusbar v2 -- auto-generated $(date '+%H:%M:%S')
set-option -g status on
set-option -g status-position bottom
set-option -g status-style "bg=colour234,fg=colour245"
set-option -g status-justify left

# Window status blocks
# window-label.sh reads attention.json and chooses the color prefix accordingly.
# Inactive windows use a default dark-grey style; window-label.sh can override to red.
set-option -g window-status-format "#(bash ${SCRIPTS}/window-label.sh #{window_name} inactive)"
set-option -g window-status-current-format "#(bash ${SCRIPTS}/window-label.sh #{window_name} active)"

# Disable monitor-activity to avoid false positives (we use attention.json instead)
set-option -g monitor-activity off
set-option -g visual-activity off
set-option -g activity-action none

set-option -g window-status-separator ""

# Status left: session indicator
set-option -g status-left-length 10
set-option -g status-left "#[fg=colour214,bold] # #[default]"

# Status right: compact info + time
set-option -g status-right-length 60
set-option -g status-right "#[fg=colour245]#(bash ${SCRIPTS}/statusbar-right.sh) #[fg=colour239]| #[fg=colour245]%H:%M"

# Refresh frequently so attention changes appear quickly
set-option -g status-interval 3

# Pane borders (minimal -- dashboard pane needs clean space)
set-option -g pane-border-style "fg=colour238"
set-option -g pane-active-border-style "fg=colour214"
set-option -g pane-border-status top
set-option -g pane-border-format " #{?pane_active,#[fg=colour214 bold],#[fg=colour245 dim]}#{pane_title}#[default] "

# After-select-window hook: clear attention state for the window we just entered
set-hook -g after-select-window 'run-shell -b "CE_HUB_CWD=${CE_HUB_CWD} bash ${SCRIPTS}/clear-attention.sh #{window_name} 2>/dev/null"'
TMUXCONF

tmux source-file "$CONF_FILE" 2>/dev/null && echo "Statusbar v2 applied." || echo "Statusbar: apply failed (session may not exist yet)"
