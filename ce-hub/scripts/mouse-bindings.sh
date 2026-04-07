#!/bin/bash
# mouse-bindings.sh — tmux mouse bindings for ce-hub TUI v2

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
SESSION="cehub"
CONF_FILE="/tmp/cehub-mouse.conf"

apply_bindings() {
  cat > "$CONF_FILE" << TMUXCONF
# ce-hub mouse bindings v2 (auto-generated)
set-option -g mouse on

# === Pane click: select only, NO send-keys -M ===
# The default tmux binding (select-pane + send-keys -M) forwards the click
# event to the running application. For Claude Code TUI this causes the input
# box to lock up (mouse escape sequence enters selection sub-state).
# Fix: just select the pane, let the user type — no click forwarding.
bind-key -T root MouseDown1Pane select-pane -t=

# === Copy/Paste ===
# Drag-select: copy to system clipboard, keep selection visible
bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe "pbcopy"
bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe "pbcopy"
# Click in copy-mode: clear selection but STAY in copy-mode (don't cancel)
bind-key -T copy-mode MouseDown1Pane select-pane \; send-keys -X clear-selection
bind-key -T copy-mode-vi MouseDown1Pane select-pane \; send-keys -X clear-selection
# Double-click: select word + copy
bind-key -T root DoubleClick1Pane select-pane -t= \; copy-mode \; send-keys -X select-word \; send-keys -X copy-pipe "pbcopy"

# === Status bar click: switch windows ===
# Click on a window tab in the status bar to switch to it
bind-key -T root MouseDown1Status select-window -t =
bind-key -T root MouseDown1StatusLeft select-window -t =

# === Right-click pane menu ===
bind-key -T root MouseDown3Pane {
  select-pane -t=
  run-shell -b "bash ${SCRIPTS}/right-click-handler.sh '#{pane_title}' '#{pane_id}'"
}

# === Keyboard window navigation ===
# prefix + 0-8: switch to window by index
bind-key 0 select-window -t :0
bind-key 1 select-window -t :1
bind-key 2 select-window -t :2
bind-key 3 select-window -t :3
bind-key 4 select-window -t :4
bind-key 5 select-window -t :5
bind-key 6 select-window -t :6
bind-key 7 select-window -t :7
bind-key 8 select-window -t :8

# prefix + n/p: next/previous window
bind-key n next-window
bind-key p previous-window

# prefix + Tab: switch between panes within window (dashboard vs agent)
bind-key Tab select-pane -t :.+

TMUXCONF

  tmux source-file "$CONF_FILE" 2>&1
  echo "Mouse bindings v2 applied (input deadlock fix: no send-keys -M on pane click)."
}

apply_bindings
