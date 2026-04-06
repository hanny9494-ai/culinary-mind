#!/bin/bash
# agent-select.sh — tmux popup menu to select which agent to run in current pane
#
# Usage:
#   agent-select.sh              — show menu, start selected agent in current pane
#   agent-select.sh <agent>      — start agent directly (no menu)
#   agent-select.sh --list       — list available agents

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-engine}"
CE_HUB_API="${CE_HUB_API:-http://localhost:8750}"
AGENTS_DIR="${CE_HUB_CWD}/.claude/agents"
SESSION="cehub"

# Colors
RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
CYAN='\033[36m'
BOLD='\033[1m'
DIM='\033[2m'
RST='\033[0m'

get_agents() {
  # Get agent list from .claude/agents/*.md (skip _ prefixed)
  local agents=()
  for f in "$AGENTS_DIR"/*.md; do
    [ -f "$f" ] || continue
    name=$(basename "$f" .md)
    [[ "$name" == _* ]] && continue
    agents+=("$name")
  done
  echo "${agents[@]}"
}

get_alive_agents() {
  # Check which agents have tmux windows
  tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null
}

start_agent_here() {
  local name="$1"
  local agent_file="$AGENTS_DIR/${name}.md"

  # Parse model from frontmatter
  local model="sonnet"
  if [ -f "$agent_file" ]; then
    model=$(grep '^model:' "$agent_file" | head -1 | sed 's/^model: *//')
    model="${model:-sonnet}"
  fi

  # Resolve claude model flag
  local model_flag="sonnet"
  case "$model" in
    opus) model_flag="opus" ;;
    haiku) model_flag="haiku" ;;
    *) model_flag="sonnet" ;;
  esac

  # Build command
  local cmd="cd $CE_HUB_CWD && claude --model $model_flag --dangerously-skip-permissions"

  # Add --agent flag if definition exists
  if [ -f "$agent_file" ]; then
    cmd="$cmd --agent $name"
  fi

  echo -e "${GREEN}Starting ${BOLD}$name${RST}${GREEN} ($model_flag)...${RST}"
  echo -e "${DIM}$cmd${RST}"
  echo ""

  # Execute in current shell (replaces this script's process)
  exec bash -c "$cmd"
}

show_menu() {
  local agents=($(get_agents))
  local alive=$(get_alive_agents)

  echo -e "${BOLD}${CYAN}  SELECT AGENT${RST}"
  echo -e "${DIM}  ─────────────────${RST}"
  echo ""

  local i=1
  for name in "${agents[@]}"; do
    local status="${DIM}off${RST}"
    if echo "$alive" | grep -qx "$name"; then
      status="${GREEN}LIVE${RST}"
    fi

    # Get description from frontmatter
    local desc=""
    local agent_file="$AGENTS_DIR/${name}.md"
    if [ -f "$agent_file" ]; then
      desc=$(grep '^description:' "$agent_file" | head -1 | sed 's/^description: *//')
    fi
    desc="${desc:0:40}"

    printf "  ${BOLD}%2d${RST}) %-20s %s  ${DIM}%s${RST}\n" "$i" "$name" "$status" "$desc"
    i=$((i + 1))
  done

  echo ""
  printf "  ${BOLD} 0${RST}) ${DIM}[cancel]${RST}\n"
  echo ""
  echo -ne "  ${YELLOW}Choice: ${RST}"

  read -r choice

  if [[ "$choice" == "0" || -z "$choice" ]]; then
    echo -e "${DIM}Cancelled.${RST}"
    exit 0
  fi

  # Accept number or name
  if [[ "$choice" =~ ^[0-9]+$ ]]; then
    local idx=$((choice - 1))
    if [ "$idx" -ge 0 ] && [ "$idx" -lt "${#agents[@]}" ]; then
      start_agent_here "${agents[$idx]}"
    else
      echo -e "${RED}Invalid choice.${RST}"
      exit 1
    fi
  else
    # Try as agent name
    for name in "${agents[@]}"; do
      if [[ "$name" == "$choice" ]]; then
        start_agent_here "$name"
      fi
    done
    echo -e "${RED}Agent not found: $choice${RST}"
    exit 1
  fi
}

case "${1:-}" in
  --list)
    get_agents | tr ' ' '\n'
    ;;
  "")
    show_menu
    ;;
  *)
    start_agent_here "$1"
    ;;
esac
