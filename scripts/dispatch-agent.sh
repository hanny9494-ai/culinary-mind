#!/usr/bin/env bash
# dispatch-agent.sh — dispatch agent to tmux window
SESSION="cehub"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "INFO:  $*"; }

check_session() {
  tmux has-session -t "$SESSION" 2>/dev/null || die "tmux session '$SESSION' not found."
}

case "${1:-}" in
  --list)
    check_session
    tmux list-windows -t "$SESSION" -F '  #{window_index}: #{window_name}'
    ;;
  --kill)
    check_session
    tmux kill-window -t "$SESSION:${2:?Usage: --kill NAME}" 2>/dev/null && info "Killed '$2'" || die "Window '$2' not found"
    ;;
  --help|"")
    echo "Usage:"
    echo "  dispatch-agent.sh AGENT_NAME TASK_DESC [COMMAND]"
    echo "  dispatch-agent.sh --list"
    echo "  dispatch-agent.sh --kill NAME"
    ;;
  *)
    AGENT="$1"; TASK="${2:?TASK required}"; CMD="${3:-}"
    check_session
    if tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | grep -qx "$AGENT"; then
      die "Window '$AGENT' already exists."
    fi
    tmux new-window -t "$SESSION" -n "$AGENT"
    if [ -n "$CMD" ]; then
      tmux send-keys -t "$SESSION:$AGENT" "$CMD" Enter
    else
      tmux send-keys -t "$SESSION:$AGENT" "claude --model sonnet -p '$TASK'" Enter
    fi
    info "Dispatched '$AGENT' → $SESSION:$AGENT"
    ;;
esac
