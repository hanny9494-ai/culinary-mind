#!/bin/bash
# pane-manager.sh — Dynamic agent pane management for ce-hub TUI
#
# Usage:
#   pane-manager.sh add [agent-name]    — add a new agent pane (split from bottom-right)
#   pane-manager.sh close [pane-id]     — close an agent pane (Ctrl-C + kill)
#   pane-manager.sh list                — list current agent panes
#   pane-manager.sh switch <pane-id> <agent-name> — switch agent in a pane

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-engine}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
AGENTS_DIR="${CE_HUB_CWD}/.claude/agents"
SESSION="cehub"

add_agent_pane() {
  local agent_name="$1"

  # Find a non-dashboard, non-cc-lead pane to split from
  # Prefer splitting from the last pane in the bottom row
  local last_pane
  last_pane=$(tmux list-panes -t "$SESSION:main" -F '#{pane_index}' 2>/dev/null | tail -1)

  # Split horizontally from the last pane
  tmux split-window -t "$SESSION:main.${last_pane}" -h -p 50 -c "$CE_HUB_CWD"

  # The new pane is now the last one
  local new_pane
  new_pane=$(tmux list-panes -t "$SESSION:main" -F '#{pane_index}' 2>/dev/null | tail -1)

  tmux send-keys -t "$SESSION:main.${new_pane}" "export no_proxy=localhost,127.0.0.1" Enter

  if [ -n "$agent_name" ]; then
    # Start the agent directly
    tmux select-pane -t "$SESSION:main.${new_pane}" -T "$agent_name"
    start_agent_in_pane "$new_pane" "$agent_name"
  else
    # Show agent selection menu
    tmux select-pane -t "$SESSION:main.${new_pane}" -T "agent-slot"
    tmux send-keys -t "$SESSION:main.${new_pane}" "bash $SCRIPTS/agent-select.sh" Enter
  fi

  # Rebalance the bottom panes (keep pane 0 = cc-lead untouched)
  # Select tiled layout for bottom panes only isn't possible,
  # so just let tmux auto-adjust
  echo "Added agent pane ${new_pane}"
}

close_agent_pane() {
  local pane_id="$1"

  if [ -z "$pane_id" ]; then
    # Close the currently focused pane
    pane_id=$(tmux display-message -t "$SESSION:main" -p '#{pane_id}')
  fi

  # Don't allow closing CC Lead or Task Board (check by title, not index)
  local pane_title
  pane_title=$(tmux display-message -t "$pane_id" -p '#{pane_title}' 2>/dev/null)

  if echo "$pane_title" | grep -qi "cc-lead\|Claude Code"; then
    echo "Cannot close CC Lead pane"
    return 1
  fi
  if [ "$pane_title" = "tasks" ]; then
    echo "Cannot close Task Board pane"
    return 1
  fi

  # Send Ctrl-C to stop the agent, then kill the pane
  tmux send-keys -t "$pane_id" C-c 2>/dev/null
  sleep 0.5
  tmux send-keys -t "$pane_id" C-c 2>/dev/null
  sleep 0.3
  tmux kill-pane -t "$pane_id" 2>/dev/null
  echo "Closed pane $pane_id"
}

switch_agent_in_pane() {
  local pane_id="$1"
  local agent_name="$2"

  if [ -z "$pane_id" ] || [ -z "$agent_name" ]; then
    echo "Usage: pane-manager.sh switch <pane-id> <agent-name>"
    return 1
  fi

  local pane_index
  pane_index=$(tmux display-message -t "$pane_id" -p '#{pane_index}' 2>/dev/null)

  # Don't switch CC Lead or Task Board
  local pane_title
  pane_title=$(tmux display-message -t "$pane_id" -p '#{pane_title}' 2>/dev/null)
  if echo "$pane_title" | grep -qi "cc-lead\|Claude Code"; then
    echo "Cannot switch CC Lead pane"
    return 1
  fi
  if [ "$pane_title" = "tasks" ]; then
    echo "Cannot switch Task Board pane"
    return 1
  fi

  # Kill current process
  tmux send-keys -t "$pane_id" C-c 2>/dev/null
  sleep 0.5
  tmux send-keys -t "$pane_id" C-c 2>/dev/null
  sleep 0.3

  # Update title and start new agent
  tmux select-pane -t "$pane_id" -T "$agent_name"
  local pane_idx
  pane_idx=$(tmux display-message -t "$pane_id" -p '#{pane_index}' 2>/dev/null)
  start_agent_in_pane "$pane_idx" "$agent_name"
}

start_agent_in_pane() {
  local pane_idx="$1"
  local agent_name="$2"
  local agent_file="$AGENTS_DIR/${agent_name}.md"

  local model="sonnet"
  if [ -f "$agent_file" ]; then
    model=$(grep '^model:' "$agent_file" | head -1 | sed 's/^model: *//')
    model="${model:-sonnet}"
  fi
  case "$model" in
    opus) model="opus" ;;
    haiku) model="haiku" ;;
    *) model="sonnet" ;;
  esac

  local cmd="cd $CE_HUB_CWD && claude --model $model --dangerously-skip-permissions"
  [ -f "$agent_file" ] && cmd="$cmd --agent $agent_name"

  tmux send-keys -t "$SESSION:main.${pane_idx}" "clear" Enter
  sleep 0.2
  tmux send-keys -t "$SESSION:main.${pane_idx}" "$cmd" Enter
}

list_agent_panes() {
  echo "Agent panes in $SESSION:main:"
  tmux list-panes -t "$SESSION:main" -F '  pane #{pane_index} (#{pane_id}): #{pane_title} #{pane_width}x#{pane_height} #{pane_current_command}' 2>/dev/null
}

case "${1:-list}" in
  add)
    add_agent_pane "$2"
    ;;
  close)
    close_agent_pane "$2"
    ;;
  switch)
    switch_agent_in_pane "$2" "$3"
    ;;
  list)
    list_agent_panes
    ;;
  *)
    echo "Usage: pane-manager.sh {add|close|switch|list} [args]"
    ;;
esac
