#!/bin/bash
# statusbar.sh — ce-hub TUI v2: Window nav bar + attention flashing
#
# Generates tmux window-status-format and status bar settings.
# Window nav: each agent window gets a large colored block (>=14 cols).
#
# Colors:
#   active window    -> orange (#[bg=colour214,fg=colour234,bold])
#   attention window -> red/orange flashing (via monitor-activity)
#   inactive window  -> dark grey (#[bg=colour237,fg=colour245])

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

# Window status blocks (inactive) -- >= 14 cols per cell
set-option -g window-status-format "#[bg=colour237,fg=colour245,nobold]  #(bash ${SCRIPTS}/window-label.sh #{window_name})  #[bg=colour234]#[default]"

# Active window -- orange
set-option -g window-status-current-format "#[bg=colour214,fg=colour234,bold]  #(bash ${SCRIPTS}/window-label.sh #{window_name})  #[bg=colour234,fg=colour214]#[default]"

# Attention window (monitor-activity flag) -- red/alert
set-option -g window-status-activity-format "#[bg=colour196,fg=colour231,bold]  #(bash ${SCRIPTS}/window-label.sh #{window_name})  #[bg=colour234,fg=colour196]#[default]"

set-option -g window-status-separator ""

# Activity monitoring: triggers window-status-activity-format
set-option -g monitor-activity on
set-option -g visual-activity off
set-option -g activity-action none

# Status left: session indicator
set-option -g status-left-length 10
set-option -g status-left "#[fg=colour214,bold] # #[default]"

# Status right: compact info + time
set-option -g status-right-length 60
set-option -g status-right "#[fg=colour245]#(bash ${SCRIPTS}/statusbar-right.sh) #[fg=colour239]| #[fg=colour245]%H:%M"

# Status interval
set-option -g status-interval 5

# Pane borders (minimal -- dashboard pane needs clean space)
set-option -g pane-border-style "fg=colour238"
set-option -g pane-active-border-style "fg=colour214"
set-option -g pane-border-status top
set-option -g pane-border-format " #{?pane_active,#[fg=colour214 bold],#[fg=colour245 dim]}#{pane_title}#[default] "

# After-select-window hook: clear attention state for the window we just entered
set-hook -g after-select-window 'run-shell -b "CE_HUB_CWD=${CE_HUB_CWD} bash ${SCRIPTS}/clear-attention.sh #{window_name} 2>/dev/null"'
TMUXCONF

tmux source-file "$CONF_FILE" 2>/dev/null && echo "Statusbar v2 applied." || echo "Statusbar: apply failed (session may not exist yet)"
