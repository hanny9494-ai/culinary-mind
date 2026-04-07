#!/bin/bash
# tui-layout.sh — ce-hub TUI v2: 9-window layout (Dashboard + Agent per window)
#
# Layout per window:
#   ┌──────────────────────────────────────────────────────────┐
#   │                 dashboard (~20 rows)                     │
#   ├──────────────────────────────────────────────────────────┤
#   │                  agent pane (~96 rows)                   │
#   └──────────────────────────────────────────────────────────┘
#   [cc-lead][coder][research][arch][pipeline][reviewer][ops][datacol][wiki]
#
# Usage:
#   tui-layout.sh                    — create layout, start all agents
#   tui-layout.sh --reset            — kill session and recreate
#   tui-layout.sh --attach           — create + attach
#   tui-layout.sh --no-agents        — layout only, no agent processes

SESSION="cehub"
CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
SCREEN_W=149
SCREEN_H=117
DASH_H=20   # dashboard pane height (rows)

# Agent windows in order
WINDOWS=(
  "cc-lead"
  "coder"
  "researcher"
  "architect"
  "pipeline-runner"
  "code-reviewer"
  "ops"
  "open-data-collector"
  "wiki-curator"
)

# ── Helpers ────────────────────────────────────────────────────────────────

get_agent_model() {
  local agent="$1"
  local agent_file="$CE_HUB_CWD/.claude/agents/${agent}.md"
  if [ -f "$agent_file" ]; then
    local m
    m=$(grep '^model:' "$agent_file" | head -1 | sed 's/^model: *//')
    case "$m" in opus|haiku) echo "$m"; return ;; esac
  fi
  echo "sonnet"
}

start_agent_pane() {
  local pane_target="$1"
  local agent="$2"
  local model
  model=$(get_agent_model "$agent")
  local agent_file="$CE_HUB_CWD/.claude/agents/${agent}.md"
  local cmd="cd $CE_HUB_CWD && claude --model $model --dangerously-skip-permissions"
  [ -f "$agent_file" ] && cmd="$cmd --agent $agent"
  tmux send-keys -t "$pane_target" "export no_proxy=localhost,127.0.0.1 CE_HUB_CWD=$CE_HUB_CWD" Enter
  tmux send-keys -t "$pane_target" "$cmd" Enter
}

# ── Setup ──────────────────────────────────────────────────────────────────

setup_window() {
  local agent="$1"
  local is_first="$2"

  local win_ref="$SESSION:$agent"

  if [[ "$is_first" == "true" ]]; then
    # First window: already created by new-session
    :
  else
    # Kill existing window if present, then create fresh
    tmux kill-window -t "$win_ref" 2>/dev/null
    tmux new-window -d -t "$SESSION" -n "$agent" -c "$CE_HUB_CWD"
  fi

  # Split: pane 0 = top (dashboard), pane 1 = bottom (agent)
  # We want dashboard at top ~20 rows, agent gets the rest
  tmux split-window -d -t "${win_ref}.0" -v -l $((SCREEN_H - DASH_H - 2)) -c "$CE_HUB_CWD"

  # Dashboard pane (top, pane 0)
  tmux select-pane -t "${win_ref}.0" -T "dashboard"
  tmux send-keys -t "${win_ref}.0" \
    "export CE_HUB_CWD=$CE_HUB_CWD no_proxy=localhost,127.0.0.1" Enter
  tmux send-keys -t "${win_ref}.0" \
    "watch -n 5 -t bash $SCRIPTS/dashboard.sh $agent" Enter

  # Agent pane (bottom, pane 1)
  tmux select-pane -t "${win_ref}.1" -T "$agent"

  if [[ "$NO_AGENTS" != "true" ]]; then
    start_agent_pane "${win_ref}.1" "$agent"
  fi

  # Focus agent pane by default
  tmux select-pane -t "${win_ref}.1"
}

# ── Main ───────────────────────────────────────────────────────────────────

DO_ATTACH=false
DO_RESET=false
NO_AGENTS=false

for arg in "$@"; do
  case "$arg" in
    --reset)     DO_RESET=true ;;
    --attach)    DO_ATTACH=true ;;
    --no-agents) NO_AGENTS=true ;;
    --help|-h)
      cat <<'HELP'
tui-layout.sh — ce-hub TUI v2

Creates 9 tmux windows, each with:
  pane 0 (top, 20 rows)  : dashboard (watch -n5 dashboard.sh)
  pane 1 (bottom, 96 rows): agent (claude --agent NAME)

Window nav bar (bottom) shows all 9 windows as colored blocks.
Active = orange, attention = red flash, inactive = grey.

Usage:
  tui-layout.sh              Setup + start all agents
  tui-layout.sh --reset      Kill session and recreate
  tui-layout.sh --attach     Setup + attach to session
  tui-layout.sh --no-agents  Layout only, no claude processes
HELP
      exit 0 ;;
  esac
done

if $DO_RESET; then
  echo "Killing session $SESSION..."
  tmux kill-session -t "$SESSION" 2>/dev/null
  sleep 0.5
fi

echo "Setting up ce-hub TUI v2 (9 windows)..."

# Ensure session exists
if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux new-session -d -s "$SESSION" -n "${WINDOWS[0]}" \
    -x $SCREEN_W -y $SCREEN_H -c "$CE_HUB_CWD"
  echo "  Created session $SESSION"
else
  echo "  Session $SESSION already exists"
  # Kill first window to recreate it cleanly
  tmux kill-window -t "$SESSION:${WINDOWS[0]}" 2>/dev/null
  tmux new-window -d -t "$SESSION" -n "${WINDOWS[0]}" -c "$CE_HUB_CWD"
fi

# Setup each window
for i in "${!WINDOWS[@]}"; do
  agent="${WINDOWS[$i]}"
  if [[ $i -eq 0 ]]; then
    setup_window "$agent" "true"
  else
    setup_window "$agent" "false"
  fi
  echo "  [$((i+1))/${#WINDOWS[@]}] $agent"
  sleep 0.2  # avoid tmux race conditions
done

# Ensure state dir exists
mkdir -p "$CE_HUB_CWD/.ce-hub/state"
# Initialize attention.json if not exists
ATTN="$CE_HUB_CWD/.ce-hub/state/attention.json"
if [ ! -f "$ATTN" ]; then
  python3 -c "
import json
agents = ${WINDOWS@Q}
" 2>/dev/null
  echo '{"cc-lead":false,"coder":false,"researcher":false,"architect":false,"pipeline-runner":false,"code-reviewer":false,"ops":false,"open-data-collector":false,"wiki-curator":false}' > "$ATTN"
fi

# Apply status bar + mouse bindings
echo "  Applying statusbar and mouse bindings..."
bash "$SCRIPTS/statusbar.sh"
bash "$SCRIPTS/mouse-bindings.sh"

# Focus cc-lead window
tmux select-window -t "$SESSION:cc-lead"
tmux select-pane -t "$SESSION:cc-lead.1"

echo ""
echo "Ready! 9 windows created."
echo "  Switch windows: click nav bar / prefix+0-8 / prefix+n/p"
echo "  Pane 0 (top): dashboard | Pane 1 (bottom): agent"

if $DO_ATTACH; then
  if [ -n "$TMUX" ]; then
    tmux switch-client -t "$SESSION:cc-lead"
  else
    tmux attach -t "$SESSION:cc-lead"
  fi
fi
