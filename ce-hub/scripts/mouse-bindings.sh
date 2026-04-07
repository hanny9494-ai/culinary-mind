#!/bin/bash
# mouse-bindings.sh — tmux mouse bindings + status bar for ce-hub TUI

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
AGENTS_DIR="${CE_HUB_CWD}/.claude/agents"
SESSION="cehub"
CONF_FILE="/tmp/cehub-mouse.conf"

apply_bindings() {
  echo "Applying mouse bindings to session: $SESSION"

  cat > "$CONF_FILE" <<TMUXCONF
# ce-hub mouse bindings (auto-generated)
set-option -g mouse on

# === Copy/Paste ===
# Drag-select: copy to system clipboard, keep selection visible
bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe "pbcopy"
bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe "pbcopy"
# Click in copy-mode: clear selection but STAY in copy-mode (don't cancel)
bind-key -T copy-mode MouseDown1Pane select-pane \; send-keys -X clear-selection
bind-key -T copy-mode-vi MouseDown1Pane select-pane \; send-keys -X clear-selection
# Double-click: select word + copy
bind-key -T root DoubleClick1Pane select-pane -t= \; copy-mode \; send-keys -X select-word \; send-keys -X copy-pipe "pbcopy"

# === Right-click menus ===
bind-key -T root MouseDown3Pane {
  select-pane -t=
  run-shell -b "bash ${SCRIPTS}/right-click-handler.sh '#{pane_title}' '#{pane_id}'"
}

# Click status bar right → agent menu
bind-key -T root MouseDown1StatusRight run-shell -b "bash ${SCRIPTS}/right-click-handler.sh 'agent-slot' ''"

# === Pane borders ===
set-option pane-border-status top
set-option pane-border-format " #{?pane_active,#[fg=colour214 bold],#[fg=colour245 dim]}#{pane_title}#[default] "
set-option pane-border-style "fg=colour238"
set-option pane-active-border-style "fg=colour214"

# === Status bar ===
set-option status-style "bg=colour235,fg=colour245"
set-option status-interval 8
set-option status-left-length 12
set-option status-right-length 100
set-option status-left "#[fg=colour214,bold] cehub #[default]"
TMUXCONF

  tmux source-file "$CONF_FILE" 2>&1

  # Status-right: compact dashboard in one line
  local sr
  sr="#[fg=colour245]#(bash ${SCRIPTS}/statusbar.sh) "
  sr+="#[fg=colour250]| #[fg=colour245]%H:%M"

  tmux set-option status-right "$sr" 2>/dev/null

  echo "Mouse bindings applied."
}

case "${1:-}" in
  *) apply_bindings ;;
esac
