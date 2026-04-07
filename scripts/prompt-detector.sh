#!/bin/bash
# prompt-detector.sh — Monitor all 9 agent panes for y/n prompts
# When detected: show macOS dialog with Yes/No buttons → send answer to pane.
#
# Design:
#   - Poll ALL 9 agent panes (pane 1 of each window) every 0.5s
#   - Match 12+ prompt patterns (y/n, [Y/n], Do you want, ❯ Yes, 1. Yes, etc.)
#   - macOS display dialog with context snippet + Yes/No buttons
#   - Send 'y' or 'n' (+ Enter) to the pane based on Jeff's click
#   - 5s per-pane dedup: same pane won't re-alert within 5s
#
# Install: bash ~/culinary-mind/scripts/prompt-detector-install.sh install
# Logs:    ~/culinary-mind/ce-hub/logs/prompt-detector.log

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

SESSION="cehub"
LOG="$HOME/culinary-mind/ce-hub/logs/prompt-detector.log"
POLL_INTERVAL=0.5     # seconds between captures (sub-second for quick response)
DEDUP_SECS=5          # per-pane cooldown after alert

# All 9 agent windows (pane 1 = agent pane in each window)
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

mkdir -p "$(dirname "$LOG")" "$HOME/culinary-mind/.ce-hub/state"

log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

# Prompt detection patterns (extended regex)
# These cover Claude Code's common confirmation prompts
GREP_PATTERN='([Dd]o you want|[Aa]re you sure|\[Y/n\]|\[y/N\]|y/n\)|Yes.*No|❯ Yes|❯ No|[Pp]roceed\?|[Cc]ontinue\?|[Cc]onfirm|[Oo]verwrite|[Aa]llow\?|1\. Yes|1\) Yes|\(y\)|\(n\))'

# Per-pane last-alert timestamps (associative array)
declare -A last_alert

show_dialog_and_reply() {
  local pane="$1"      # e.g. cehub:cc-lead.1
  local window="$2"    # e.g. cc-lead
  local context="$3"   # prompt context snippet

  local now
  now=$(date +%s)

  # Dedup: skip if within cooldown
  local prev="${last_alert[$window]:-0}"
  if [ $((now - prev)) -lt $DEDUP_SECS ]; then
    return
  fi
  last_alert[$window]=$now

  log "PROMPT detected in [$window]: ${context:0:80}"

  # Escape context for AppleScript (backslash, quote, newline)
  local safe_ctx
  safe_ctx=$(printf '%s' "$context" | head -c 200 | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g')

  # Show dialog — blocks until Jeff clicks
  local choice
  choice=$(osascript 2>/dev/null <<APPL
set dlgResult to display dialog "Agent [${window}] 需要确认:\n\n${safe_ctx}" ¬
    buttons {"No", "Yes"} ¬
    default button "Yes" ¬
    with icon caution ¬
    giving up after 30
if gave up of dlgResult then
    return "timeout"
end if
return button returned of dlgResult
APPL
)

  log "Jeff chose: [${choice}] for [$window]"

  case "$choice" in
    "Yes")
      # Send 'y' then Enter — covers y/n prompts and "1. Yes" numbered style
      /opt/homebrew/bin/tmux send-keys -t "$pane" "y" Enter 2>/dev/null
      log "Sent: y + Enter to $pane"
      ;;
    "No")
      /opt/homebrew/bin/tmux send-keys -t "$pane" "n" Enter 2>/dev/null
      log "Sent: n + Enter to $pane"
      ;;
    "timeout")
      log "Dialog timed out (30s) — no reply sent"
      ;;
    *)
      log "Unknown choice '${choice}' — no reply sent"
      ;;
  esac
}

log "prompt-detector v2 started. Monitoring ${#WINDOWS[@]} agent panes (poll=${POLL_INTERVAL}s, dedup=${DEDUP_SECS}s)"

# Main loop
while true; do
  # Check if session exists at all
  if ! /opt/homebrew/bin/tmux has-session -t "$SESSION" 2>/dev/null; then
    sleep 2
    continue
  fi

  for window in "${WINDOWS[@]}"; do
    pane="${SESSION}:${window}.1"

    # Skip windows that don't exist
    if ! /opt/homebrew/bin/tmux list-windows -t "$SESSION" -F "#{window_name}" 2>/dev/null | grep -qx "$window"; then
      continue
    fi

    # Capture last 15 lines of visible pane content
    pane_content=$(/opt/homebrew/bin/tmux capture-pane -t "$pane" -p -S -15 2>/dev/null)
    [ -z "$pane_content" ] && continue

    # Check for prompt patterns
    matched=$(printf '%s' "$pane_content" | grep -oE "$GREP_PATTERN" | head -1)
    if [ -n "$matched" ]; then
      # Get context: last 3 non-empty lines as a single string
      context=$(printf '%s' "$pane_content" | grep -v '^\s*$' | tail -3 | tr '\n' ' ')
      show_dialog_and_reply "$pane" "$window" "$context"
    fi
  done

  sleep "$POLL_INTERVAL"
done
