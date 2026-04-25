#!/bin/bash
# Pull collected data from Mac Mini to Mac Studio
TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
LOG="$HOME/culinary-mind/logs/mini-sync.log"
MINI="jify"
LOCAL_DIR="$HOME/culinary-mind/data/mini-harvest"

mkdir -p "$LOCAL_DIR/raw" "$LOCAL_DIR/staging"

echo "[$TIMESTAMP] Pulling from Mini..." >> "$LOG"

rsync -avz --timeout=60 \
    "$MINI:~/culinary-mind-mini/data/raw/" \
    "$LOCAL_DIR/raw/" \
    >> "$LOG" 2>&1

rsync -avz --timeout=60 \
    "$MINI:~/culinary-mind-mini/data/staging/" \
    "$LOCAL_DIR/staging/" \
    >> "$LOG" 2>&1

RC=$?
echo "[$TIMESTAMP] Pull done (exit=$RC)" >> "$LOG"

[ -f "$LOG" ] && LINES=$(wc -l < "$LOG") && [ "$LINES" -gt 5000 ] && tail -2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
