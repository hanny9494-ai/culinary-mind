#!/bin/bash
# Pull harvested data from jify to Studio
# Runs every 30 min via launchd (since Studio SSH inbound is off)
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
LOG="$HOME/culinary-mind/logs/pull-from-jify.log"
mkdir -p "$(dirname "$LOG")" "$HOME/culinary-mind/data/mini-harvest/raw"

echo "[$TIMESTAMP] Starting pull from jify..." >> "$LOG"

rsync -avz --timeout=60 \
    jify:~/culinary-mind-mini/data/raw/ \
    "$HOME/culinary-mind/data/mini-harvest/raw/" \
    >> "$LOG" 2>&1

RC=$?
echo "[$TIMESTAMP] Pull done (exit=$RC)" >> "$LOG"

# Trim log
if [ -f "$LOG" ]; then
    LINES=$(wc -l < "$LOG")
    if [ "$LINES" -gt 3000 ]; then
        tail -1500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
    fi
fi
