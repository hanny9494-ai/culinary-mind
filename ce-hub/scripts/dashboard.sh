#!/bin/bash
# dashboard.sh — ce-hub TUI dashboard (20 lines, 5 sections)
# Usage: dashboard.sh [agent_name]
# Called by: watch -n 5 -t dashboard.sh <agent>
# Output: structured 20-line dashboard for the top pane of each window

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
API="http://localhost:8750"
CURRENT_AGENT="${1:-?}"
ATTN_FILE="$CE_HUB_CWD/.ce-hub/state/attention.json"

# ── Colors (ANSI for terminal, not tmux sequences) ──────────────────────────
R='\033[0;31m'   # red
G='\033[0;32m'   # green
Y='\033[0;33m'   # yellow
C='\033[0;36m'   # cyan
W='\033[0;37m'   # white
B='\033[1m'      # bold
D='\033[2m'      # dim
RST='\033[0m'    # reset
SEP="${D}───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────${RST}"

# ── Quick API call ─────────────────────────────────────────────────────────
health=$(curl -s --noproxy localhost --max-time 1 "$API/api/health" 2>/dev/null)
daemon_ok=$( [ -n "$health" ] && echo "true" || echo "false" )

ts=$(date '+%H:%M:%S')

# Print header (1 line)
printf "${B}${C} ◈ ce-hub dashboard${RST}  ${D}window: ${W}${CURRENT_AGENT}${RST}  ${D}${ts}${RST}\n"
printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § 1 — 记忆固化 (4 lines)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§1 记忆固化${RST}\n"

# Latest conversation capture
conv_file="$CE_HUB_CWD/raw/conversations.jsonl"
if [ -f "$conv_file" ]; then
  conv_mtime=$(stat -f "%Sm" -t "%m-%d %H:%M" "$conv_file" 2>/dev/null || echo "?")
  conv_lines=$(wc -l < "$conv_file" 2>/dev/null | tr -d ' ')
  printf "  ${D}对话捕获:${RST} ${W}${conv_mtime}${RST} ${D}(${conv_lines} 行)${RST}\n"
else
  printf "  ${D}对话捕获:${RST} ${Y}无数据${RST}\n"
fi

# Latest wiki update
wiki_status="$CE_HUB_CWD/wiki/STATUS.md"
if [ -f "$wiki_status" ]; then
  wiki_mtime=$(stat -f "%Sm" -t "%m-%d %H:%M" "$wiki_status" 2>/dev/null || echo "?")
  printf "  ${D}wiki 更新:${RST} ${W}${wiki_mtime}${RST}\n"
else
  printf "  ${D}wiki 更新:${RST} ${Y}未初始化${RST}\n"
fi

# Conflicts count
conflicts_file="$CE_HUB_CWD/wiki/_conflicts.md"
if [ -f "$conflicts_file" ]; then
  conflict_count=$(grep -c '^### 冲突' "$conflicts_file" 2>/dev/null || echo 0)
  if [ "$conflict_count" -gt 0 ]; then
    printf "  ${D}冲突:${RST} ${R}${conflict_count} 条待处理${RST}\n"
  else
    printf "  ${D}冲突:${RST} ${G}无${RST}\n"
  fi
else
  printf "  ${D}冲突:${RST} ${D}N/A${RST}\n"
fi

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § 2 — Agents (3 lines)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§2 Agents${RST}\n"

if [ "$daemon_ok" = "true" ]; then
  # Parse agent status from health API
  agent_line=$(echo "$health" | python3 -c "
import sys, json
d = json.load(sys.stdin)
agents = d.get('agents', [])
parts = []
for a in agents:
    name = a.get('name', '?')
    alive = a.get('alive', False)
    short = name[:6]
    status = '\033[32m●\033[0m' if alive else '\033[2m○\033[0m'
    parts.append(f'{status}{short}')
print('  ' + '  '.join(parts))
" 2>/dev/null || echo "  ?(parse error)")
  printf "%s\n" "$agent_line"

  tasks=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); q=d.get('queueStats',{}); print(f\"  tasks: {d.get('taskCount',0)} total | running:{q.get('running',0)} pending:{q.get('pending',0)}\")" 2>/dev/null || echo "  tasks: ?")
  printf "%s\n" "$tasks"
else
  printf "  ${R}daemon offline${RST}\n"
  printf "  ${D}—${RST}\n"
fi

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § 3 — Mac Mini 爬虫 (2 lines, placeholder)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§3 Mac Mini${RST} ${D}(jify)${RST}\n"
printf "  ${D}OpenClaw: 一直运行中 | 下一步接 ssh push | 接入待开发${RST}\n"

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § 4 — 服务健康 (4 lines)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§4 服务${RST}\n"

check_port() {
  local name="$1"
  local port="$2"
  if nc -z -w1 localhost "$port" 2>/dev/null; then
    printf "  ${G}●${RST} ${name}:${port}"
  else
    printf "  ${R}○${RST} ${name}:${port}"
  fi
}

printf "%s" "$(check_port daemon 8750)"
printf "  %s" "$(check_port newapi 3001)"
printf "  %s" "$(check_port taskqueue 8742)"
printf "\n"
printf "%s" "$(check_port ollama 11434)"
printf "  %s\n" "$(check_port neo4j 7687)"

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § 5 — Alerts (3 lines max)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§5 Alerts${RST}\n"

alerts=0

# Daemon down?
if [ "$daemon_ok" = "false" ]; then
  printf "  ${R}⚠ daemon offline (port 8750 not responding)${RST}\n"
  alerts=$((alerts+1))
fi

# Stuck dispatches (older than 5 min in dispatch dir)?
dispatch_dir="$CE_HUB_CWD/.ce-hub/dispatch"
if [ -d "$dispatch_dir" ]; then
  stuck=$(find "$dispatch_dir" -name "*.json" -mmin +5 2>/dev/null | wc -l | tr -d ' ')
  if [ "$stuck" -gt 0 ]; then
    printf "  ${Y}⚠ ${stuck} dispatch(es) stuck >5min${RST}\n"
    alerts=$((alerts+1))
  fi
fi

# Conflicts present?
if [ -f "$conflicts_file" ] && [ "$conflict_count" -gt 0 ]; then
  printf "  ${Y}⚠ ${conflict_count} wiki conflict(s) need review${RST}\n"
  alerts=$((alerts+1))
fi

if [ $alerts -eq 0 ]; then
  printf "  ${G}✓ all clear${RST}\n"
fi
printf "\n"
