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
#   tui-layout.sh                    — create layout (idempotent: skip existing windows)
#   tui-layout.sh --reset            — kill session and recreate
#   tui-layout.sh --force            — recreate all windows even if they exist
#   tui-layout.sh --attach           — create + attach
#   tui-layout.sh --no-agents        — layout only, no agent processes
#   tui-layout.sh --statusbar-only   — just (re)apply statusbar + mouse bindings

SESSION="cehub"
CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
SCRIPTS="$CE_HUB_CWD/ce-hub/scripts"
SCREEN_W=149
SCREEN_H=117
DASH_H=28   # dashboard pane height (rows) — enriched dashboard for 27" screen

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
  if [ "$agent" = "cc-lead" ] && [ "${CE_HUB_D68_SESSIONS:-0}" = "1" ]; then
    cmd="cd $CE_HUB_CWD && $CE_HUB_CWD/ce-hub/scripts/cehub-cc-lead-wrapper.sh -- claude --model $model --dangerously-skip-permissions"
    [ -f "$agent_file" ] && cmd="$cmd --agent $agent"
  fi
  tmux send-keys -t "$pane_target" "export no_proxy=localhost,127.0.0.1 CE_HUB_CWD=$CE_HUB_CWD" Enter
  tmux send-keys -t "$pane_target" "$cmd" Enter
}

# Return 0 if window exists, 1 otherwise
window_exists() {
  local agent="$1"
  tmux list-windows -t "$SESSION" -F "#{window_name}" 2>/dev/null | grep -qx "$agent"
}

# Return number of panes in a window
window_pane_count() {
  local agent="$1"
  tmux list-panes -t "$SESSION:$agent" 2>/dev/null | wc -l | tr -d ' '
}

# ── Setup ──────────────────────────────────────────────────────────────────

setup_window() {
  local agent="$1"
  local force="$2"     # "true" = always recreate
  local win_ref="$SESSION:$agent"

  # Check if window already has correct structure (2 panes)
  if window_exists "$agent" && [ "$(window_pane_count "$agent")" -eq 2 ] && [ "$force" != "true" ]; then
    echo "  [skip] $agent (already set up, 2 panes present — use --force to rebuild)"
    return 0
  fi

  # Recreate window
  if window_exists "$agent"; then
    tmux kill-window -t "$win_ref" 2>/dev/null
  fi
  tmux new-window -d -t "$SESSION" -n "$agent" -c "$CE_HUB_CWD"

  # Split: pane 0 = top (dashboard), pane 1 = bottom (agent)
  # new-window creates pane 0; split creates pane 1 below pane 0
  tmux split-window -d -t "${win_ref}.0" -v -l $((SCREEN_H - DASH_H - 2)) -c "$CE_HUB_CWD"

  # Dashboard pane (top, pane 0)
  tmux select-pane -t "${win_ref}.0" -T "dashboard"
  tmux send-keys -t "${win_ref}.0" \
    "export CE_HUB_CWD=$CE_HUB_CWD no_proxy=localhost,127.0.0.1" Enter
  local dashboard_cmd="/Users/jeff/miniforge3/bin/python3 $CE_HUB_CWD/src/dashboard/app.py --agent=$agent"
  if [ "$agent" = "cc-lead" ]; then
    dashboard_cmd="$dashboard_cmd --global"
  fi
  tmux send-keys -t "${win_ref}.0" "$dashboard_cmd" Enter

  # Agent pane (bottom, pane 1)
  tmux select-pane -t "${win_ref}.1" -T "$agent"

  if [[ "$NO_AGENTS" != "true" ]]; then
    start_agent_pane "${win_ref}.1" "$agent"
  fi

  # Focus agent pane by default
  tmux select-pane -t "${win_ref}.1"
  return 0
}

# ── Argument Parsing ───────────────────────────────────────────────────────

DO_ATTACH=false
DO_RESET=false
DO_FORCE=false
NO_AGENTS=false
STATUSBAR_ONLY=false

for arg in "$@"; do
  case "$arg" in
    --reset)          DO_RESET=true ;;
    --force)          DO_FORCE=true ;;
    --attach)         DO_ATTACH=true ;;
    --no-agents)      NO_AGENTS=true ;;
    --statusbar-only) STATUSBAR_ONLY=true ;;
    --help|-h)
      cat <<'HELP'
tui-layout.sh — ce-hub TUI v2

Creates 9 tmux windows, each with:
  pane 0 (top, 20 rows)   : dashboard (Textual app)
  pane 1 (bottom, 96 rows): agent (claude --agent NAME)

Idempotent: windows with correct 2-pane structure are skipped unless --force.

Usage:
  tui-layout.sh                  Setup (idempotent: skip existing windows)
  tui-layout.sh --reset          Kill session and recreate from scratch
  tui-layout.sh --force          Recreate all windows even if they exist
  tui-layout.sh --attach         Setup + attach to session
  tui-layout.sh --no-agents      Layout only, no claude processes
  tui-layout.sh --statusbar-only Reapply statusbar + mouse bindings only

Window nav bar shows all 9 windows as colored blocks.
Active = orange, attention = red, inactive = grey.
HELP
      exit 0 ;;
  esac
done

# ── Statusbar only mode ────────────────────────────────────────────────────

if $STATUSBAR_ONLY; then
  echo "Applying statusbar and mouse bindings..."
  bash "$SCRIPTS/statusbar.sh"
  bash "$SCRIPTS/mouse-bindings.sh"
  exit 0
fi

# ── Reset ──────────────────────────────────────────────────────────────────

if $DO_RESET; then
  echo "Killing session $SESSION..."
  tmux kill-session -t "$SESSION" 2>/dev/null
  sleep 0.5
fi

echo "Setting up ce-hub TUI v2 (9 windows)..."

# ── Session ────────────────────────────────────────────────────────────────

if ! tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux new-session -d -s "$SESSION" -n "${WINDOWS[0]}" \
    -x $SCREEN_W -y $SCREEN_H -c "$CE_HUB_CWD"
  echo "  Created session $SESSION"
else
  echo "  Session $SESSION already exists"
fi

# ── Windows ────────────────────────────────────────────────────────────────

created=0
skipped=0
for i in "${!WINDOWS[@]}"; do
  agent="${WINDOWS[$i]}"
  if setup_window "$agent" "$DO_FORCE"; then
    result=$?
    if [ $result -eq 0 ]; then
      # Check if it was skipped (message contains "skip")
      :
    fi
  fi
  if ! (window_exists "$agent" && [ "$(window_pane_count "$agent")" -eq 2 ] && [ "$DO_FORCE" != "true" ]); then
    created=$((created+1))
  else
    skipped=$((skipped+1))
  fi
  echo "  [$((i+1))/${#WINDOWS[@]}] $agent"
  sleep 0.1  # avoid tmux race conditions
done

# ── State / Attention ──────────────────────────────────────────────────────

mkdir -p "$CE_HUB_CWD/.ce-hub/state" "$CE_HUB_CWD/.ce-hub/tmp"

ATTN="$CE_HUB_CWD/.ce-hub/state/attention.json"
if [ ! -f "$ATTN" ]; then
  cat > "$ATTN" << 'ATTN_EOF'
{
  "cc-lead": false,
  "coder": false,
  "researcher": false,
  "architect": false,
  "pipeline-runner": false,
  "code-reviewer": false,
  "ops": false,
  "open-data-collector": false,
  "wiki-curator": false
}
ATTN_EOF
  echo "  Created attention.json"
fi

# ── Statusbar + Bindings ───────────────────────────────────────────────────

echo "  Applying statusbar and mouse bindings..."
bash "$SCRIPTS/statusbar.sh"
bash "$SCRIPTS/mouse-bindings.sh"

# Focus cc-lead window
tmux select-window -t "$SESSION:cc-lead" 2>/dev/null
tmux select-pane -t "$SESSION:cc-lead.1" 2>/dev/null

echo ""
echo "Ready! 9 windows configured."
echo "  Switch windows: click nav bar / prefix+0-8 / prefix+n/p"
echo "  Pane 0 (top): dashboard | Pane 1 (bottom): agent"
echo "  Run with --force to rebuild existing windows"

if $DO_ATTACH; then
  if [ -n "$TMUX" ]; then
    tmux switch-client -t "$SESSION:cc-lead"
  else
    tmux attach -t "$SESSION:cc-lead"
  fi
fi
