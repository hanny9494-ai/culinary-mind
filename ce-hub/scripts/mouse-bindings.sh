#!/bin/bash
# mouse-bindings.sh — tmux mouse bindings for ce-hub TUI v2
#
# Design principles:
#   1. Pane clicks: select-pane ONLY, no send-keys -M (prevents Claude Code TUI deadlock)
#   2. Scroll wheels: always forward to application, never auto-enter copy-mode
#      (prevents vi-mode key hijacking — 'f' triggering jump-forward prompt)
#   3. Drag-select: enters copy-mode for text selection + clipboard copy
#   4. Status bar: click to switch windows

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
SESSION="cehub"
CONF_FILE="/tmp/cehub-mouse.conf"

apply_bindings() {
  cat > "$CONF_FILE" << TMUXCONF
# ce-hub mouse bindings v2 (auto-generated)
set-option -g mouse on

# === Pane click: select only, NO send-keys -M ===
# Fix: removed send-keys -M to prevent mouse click being forwarded to Claude Code TUI.
# Without this fix: click selects pane AND sends click event → Claude Code TUI enters
# text-selection state → input box becomes unresponsive until Ctrl+C.
bind-key -T root MouseDown1Pane select-pane -t=

# === Scroll: always forward to application, never auto-enter copy-mode ===
# Fix: the default conditional (alternate_on || pane_in_mode || mouse_any_flag) is
# unreliable — Claude Code's pane may not set alternate_on consistently.
# When condition is false, tmux ran copy-mode -e → user typed 'f' → vi jump-forward prompt.
# Solution: always send-keys -M (forward scroll to app). Claude Code handles it; dashboard
# (watch) silently ignores unhandled mouse events.
bind-key -T root WheelUpPane   send-keys -M
bind-key -T root WheelDownPane send-keys -M

# === Copy/Paste ===
# Drag-select: enters copy-mode and copies to system clipboard
bind-key -T root MouseDrag1Pane copy-mode -M
bind-key -T copy-mode MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy"
bind-key -T copy-mode-vi MouseDragEnd1Pane send-keys -X copy-pipe-and-cancel "pbcopy"
# Click in copy-mode: clear selection but STAY in copy-mode (don't cancel)
bind-key -T copy-mode MouseDown1Pane select-pane \; send-keys -X clear-selection
bind-key -T copy-mode-vi MouseDown1Pane select-pane \; send-keys -X clear-selection
# Double-click: select word + copy
bind-key -T root DoubleClick1Pane select-pane -t= \; copy-mode \; send-keys -X select-word \; send-keys -X copy-pipe-and-cancel "pbcopy"

# === Status bar click: switch windows ===
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
  [ -n "$VERBOSE" ] && echo "Mouse bindings v2 applied." >&2 || true
}

apply_bindings
