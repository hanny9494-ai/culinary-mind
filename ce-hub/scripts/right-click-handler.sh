#!/bin/bash
# right-click-handler.sh — Context-aware right-click menu

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-engine}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
AGENTS_DIR="${CE_HUB_CWD}/.claude/agents"
SESSION="cehub"

PANE_TITLE="$1"
PANE_ID="$2"
PANE_INDEX=""
[ -n "$PANE_ID" ] && PANE_INDEX=$(tmux display-message -p -t "$PANE_ID" '#{pane_index}' 2>/dev/null)

show_agent_menu() {
  local items=()

  # Zoom toggle (most useful for long output)
  local zoom_label="Zoom Fullscreen"
  local is_zoomed
  is_zoomed=$(tmux display-message -p -t "$PANE_ID" '#{window_zoomed_flag}' 2>/dev/null)
  [ "$is_zoomed" = "1" ] && zoom_label="Unzoom"
  items+=("#[fg=colour214,bold]${zoom_label}" "z" "resize-pane -Z")
  items+=("" "" "")

  # Switch agent list
  for f in "$AGENTS_DIR"/*.md; do
    [ -f "$f" ] || continue
    local name
    name=$(basename "$f" .md)
    [[ "$name" == _* ]] && continue
    [[ "$name" == "cc-lead" ]] && continue

    local tag=""
    if tmux list-panes -t "$SESSION:main" -F '#{pane_title}' 2>/dev/null | grep -q "$name"; then
      tag=" *"
    fi
    items+=("${name}${tag}" "" "run-shell -b 'bash $SCRIPTS/pane-manager.sh switch \"$PANE_ID\" \"$name\"'")
  done

  items+=("" "" "")
  items+=("#[fg=colour117]+ Add Pane" "a" "run-shell -b 'bash $SCRIPTS/pane-manager.sh add'")
  items+=("#[fg=colour196]x Close" "x" "run-shell -b 'bash $SCRIPTS/pane-manager.sh close \"$PANE_ID\"'")

  tmux display-menu -T "#[bold,fg=colour214] Agent" -x P -y P "${items[@]}"
}

show_cclead_menu() {
  local zoom_label="Zoom Fullscreen"
  local is_zoomed
  is_zoomed=$(tmux display-message -p -t "$PANE_ID" '#{window_zoomed_flag}' 2>/dev/null)
  [ "$is_zoomed" = "1" ] && zoom_label="Unzoom"

  tmux display-menu -T "#[bold,fg=colour214] CC Lead" -x P -y P \
    "#[fg=colour214,bold]${zoom_label}" z "resize-pane -Z" \
    "" "" "" \
    "#[fg=colour117]+ Add Agent Pane"  a  "run-shell -b 'bash $SCRIPTS/pane-manager.sh add'" \
    "" "" "" \
    "Restart"     r  "send-keys -t $SESSION:main.0 C-c ; run-shell -b 'sleep 1 && tmux send-keys -t $SESSION:main.0 \"cd $CE_HUB_CWD && claude --model opus --dangerously-skip-permissions --agent cc-lead\" Enter'"
}

# Route by pane title (more reliable than index after -fh splits)
case "$PANE_TITLE" in
  *cc-lead*|*"CC Lead"*|*"Claude Code"*|*"Clear session"*)
    show_cclead_menu ;;
  tasks)
    ;; # task board — read-only, no menu
  *)
    show_agent_menu ;;
esac
