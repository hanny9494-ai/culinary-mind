#!/bin/bash
# prompt-detector.sh — Monitor cc-lead pane for y/n prompts
# Detects when Claude Code shows a confirmation prompt that freezes the TUI.
#
# Mechanism: poll tmux capture-pane every 3s, grep for known prompt patterns.
# Alert: macOS display alert + switch tmux to cc-lead window.
# Dedup: 10s cooldown between alerts for same session.
#
# Run via launchd: see scripts/prompt-detector.plist
# Manual start: bash ~/culinary-mind/scripts/prompt-detector.sh
# Manual stop: pkill -f prompt-detector.sh

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

SESSION="cehub"
PANE="${SESSION}:cc-lead.1"      # window=cc-lead, pane 1 = agent pane
LOG="$HOME/culinary-mind/ce-hub/logs/prompt-detector.log"
POLL_INTERVAL=3       # seconds between captures
ALERT_COOLDOWN=10     # seconds before re-alerting same prompt
STATE_DIR="$HOME/culinary-mind/.ce-hub/state"

mkdir -p "$(dirname "$LOG")" "$STATE_DIR"

# Prompt patterns to detect (Claude Code confirmation prompts)
# These are patterns that typically mean Claude is waiting for user input
PROMPT_PATTERNS=(
  "[Dd]o you want"
  "[Aa]re you sure"
  "\[Y/n\]"
  "\[y/N\]"
  "y/n\)"
  "Yes.*No"
  "❯ Yes"
  "❯ No"
  "Proceed\?"
  "Continue\?"
  "confirm"
  "Overwrite"
  "overwrite"
  "Allow\?"
)

# Build grep pattern
GREP_PATTERN=$(printf '%s\n' "${PROMPT_PATTERNS[@]}" | paste -sd '|')

last_alert=0
log() { echo "[$(date '+%H:%M:%S')] $*" >> "$LOG"; }

log "prompt-detector started. Monitoring ${PANE} (poll=${POLL_INTERVAL}s, cooldown=${ALERT_COOLDOWN}s)"

alert_jeff() {
  local snippet="$1"
  local now
  now=$(date +%s)

  # Dedup: skip if within cooldown window
  if [ $((now - last_alert)) -lt $ALERT_COOLDOWN ]; then
    return
  fi
  last_alert=$now

  log "ALERT: prompt detected → ${snippet:0:80}"

  # macOS display alert (blocks until Jeff dismisses or chooses)
  choice=$(osascript 2>/dev/null <<APPL
set btnResult to button returned of (display alert "⚠️ cc-lead 需要确认" message "检测到 y/n prompt — TUI 可能假死\n\n${snippet:0:120}" buttons {"忽略", "切到 cc-lead"} default button "切到 cc-lead" as critical)
APPL
)

  log "Jeff chose: ${choice}"

  # If Jeff chose to switch, bring cc-lead window to front
  if [ "$choice" = "切到 cc-lead" ]; then
    # Switch tmux to cc-lead window
    /opt/homebrew/bin/tmux select-window -t "${SESSION}:cc-lead" 2>/dev/null
    /opt/homebrew/bin/tmux select-pane -t "${PANE}" 2>/dev/null
    # Also bring Terminal to front
    osascript -e 'tell application "Terminal" to activate' 2>/dev/null
    log "Switched tmux to cc-lead pane"
  fi
}

# Main poll loop
while true; do
  # Check if tmux session + pane exist
  if ! /opt/homebrew/bin/tmux has-session -t "$SESSION" 2>/dev/null; then
    sleep "$POLL_INTERVAL"
    continue
  fi

  # Capture pane content (last 30 lines of visible buffer)
  pane_content=$(/opt/homebrew/bin/tmux capture-pane -t "$PANE" -p -S -30 2>/dev/null)

  if [ -n "$pane_content" ]; then
    # Check for prompt patterns (case-sensitive grep with extended regex)
    matched=$(echo "$pane_content" | grep -oE "$GREP_PATTERN" | head -1)
    if [ -n "$matched" ]; then
      # Get a clean snippet of context (last 3 lines)
      snippet=$(echo "$pane_content" | tail -3 | tr -s ' ' | xargs)
      alert_jeff "$snippet"
    fi
  fi

  sleep "$POLL_INTERVAL"
done
