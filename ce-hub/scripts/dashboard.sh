#!/bin/bash
# dashboard.sh — ce-hub TUI v2 dashboard (enriched)
# Usage: dashboard.sh [agent_name]
# Called by: watch -n 5 -t dashboard.sh <agent>
# Target: 27" screen, DASH_H≥28. Information density ~3x original.

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
API="http://localhost:8750"
CURRENT_AGENT="${1:-?}"

# ── Colors ────────────────────────────────────────────────────────────────────
R='\033[0;31m'; G='\033[0;32m'; Y='\033[0;33m'; C='\033[0;36m'
W='\033[0;37m'; B='\033[1m'; D='\033[2m'; M='\033[0;35m'; RST='\033[0m'
BG='\033[1;32m'  # bright green
SEP="${D}────────────────────────────────────────────────────────────────────────────${RST}"

# ── Helpers ───────────────────────────────────────────────────────────────────
check_port() { nc -z -w2 -G2 localhost "$1" 2>/dev/null && printf "${G}●${RST}" || printf "${R}○${RST}"; }

ago() {
  local ts_ms="$1"  # epoch ms
  local now_ms
  now_ms=$(python3 -c "import time; print(int(time.time()*1000))" 2>/dev/null)
  local diff_s=$(( (now_ms - ts_ms) / 1000 ))
  if   [ $diff_s -lt 60 ];   then printf "${diff_s}s"
  elif [ $diff_s -lt 3600 ]; then printf "$((diff_s/60))m"
  else                             printf "$((diff_s/3600))h$((diff_s%3600/60))m"
  fi
}

status_icon() {
  case "$1" in
    done)        printf "${G}✓${RST}" ;;
    failed)      printf "${R}✗${RST}" ;;
    dead_letter) printf "${R}☠${RST}" ;;
    running)     printf "${Y}⏳${RST}" ;;
    pending)     printf "${D}·${RST}" ;;
    *)           printf "${D}?${RST}" ;;
  esac
}

ts=$(date '+%H:%M:%S')

# ── Fetch health once ──────────────────────────────────────────────────────────
health=$(curl -s --noproxy localhost --max-time 1 "$API/api/health" 2>/dev/null)
daemon_ok=$( [ -n "$health" ] && echo "true" || echo "false" )

# Parse health fields
if [ "$daemon_ok" = "true" ]; then
  task_count=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('taskCount',0))" 2>/dev/null || echo "?")
  uptime_s=$(echo "$health" | python3 -c "import sys,json; d=json.load(sys.stdin); u=d.get('uptime',0); print(f'{u//3600}h{u%3600//60}m' if u>=3600 else f'{u//60}m{u%60}s')" 2>/dev/null || echo "?")
  queue_str=$(echo "$health" | python3 -c "
import sys,json; d=json.load(sys.stdin); q=d.get('queueStats',{})
parts=[]
for tier,info in q.items():
    p=info.get('pending',0); s=info.get('size',0)
    c='\\033[0;31m' if p>0 else '\\033[2m'
    parts.append(f'{c}{tier}:{p}p/{s}\\033[0m')
print('  '.join(parts) or 'idle')
" 2>/dev/null || echo "?")
  # Costs
  cost_str=$(echo "$health" | python3 -c "
import sys,json; d=json.load(sys.stdin); c=d.get('costs',{})
if not c: print('\033[2mn/a\033[0m'); sys.exit()
parts=[]
for k,v in c.items():
    if isinstance(v,(int,float)) and v>0:
        parts.append(f'{k}:\${v:.2f}')
print('  '.join(parts) or '\033[2m\$0.00\033[0m')
" 2>/dev/null || echo "?")
else
  task_count="?"; uptime_s="?"; queue_str="${R}offline${RST}"; cost_str="?"
fi

# ── Header (1 line) ────────────────────────────────────────────────────────────
daemon_dot=$([ "$daemon_ok" = "true" ] && printf "${G}●${RST}" || printf "${R}●${RST}")
printf "${B}${C}◈ ce-hub${RST}  ${D}[${W}${CURRENT_AGENT}${D}]${RST}  ${D}${ts}${RST}  ${daemon_dot} daemon  ${D}tasks:${W}${task_count}${RST}  ${D}up:${W}${uptime_s}${RST}\n"
printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § A — This agent's recent tasks
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§ AGENT${RST}  ${C}${CURRENT_AGENT}${RST}\n"

if [ "$daemon_ok" = "true" ] && [ "$CURRENT_AGENT" != "?" ]; then
  agent_tasks=$(curl -s --noproxy localhost --max-time 1 \
    "$API/api/tasks?to_agent=${CURRENT_AGENT}&limit=3" 2>/dev/null)
  echo "$agent_tasks" | python3 -c "
import sys, json
try:
    tasks = json.load(sys.stdin)
except:
    print('  \033[2m(parse error)\033[0m')
    sys.exit()
if not tasks:
    print('  \033[2mno tasks yet\033[0m')
    sys.exit()
icons = {'done':'\033[32m✓\033[0m','failed':'\033[31m✗\033[0m',
         'dead_letter':'\033[31m☠\033[0m','running':'\033[33m⏳\033[0m',
         'pending':'\033[2m·\033[0m'}
import time
now_ms = int(time.time()*1000)
for t in tasks[:3]:
    st = t.get('status','?')
    ic = icons.get(st, '\033[2m?\033[0m')
    title = (t.get('title') or '?')[:38]
    from_a = (t.get('from_agent') or '?')[:10]
    ts_ms = t.get('completed_at') or t.get('started_at') or t.get('created_at') or 0
    diff_s = (now_ms - ts_ms) // 1000
    if diff_s < 60:      age = f'{diff_s}s'
    elif diff_s < 3600:  age = f'{diff_s//60}m'
    else:                age = f'{diff_s//3600}h{diff_s%3600//60}m'
    print(f'  {ic} \033[37m{title:<38}\033[0m \033[2m{from_a:<10}  {age:>5}\033[0m')
" 2>/dev/null || printf "  ${D}(error fetching tasks)${RST}\n"
fi

# Also show dispatched tasks (outgoing, if cc-lead)
if [ "$CURRENT_AGENT" = "cc-lead" ] && [ "$daemon_ok" = "true" ]; then
  pending_out=$(curl -s --noproxy localhost --max-time 1 \
    "$API/api/tasks?from_agent=cc-lead&status=running&limit=2" 2>/dev/null)
  out_count=$(echo "$pending_out" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
  if [ "$out_count" -gt 0 ]; then
    echo "$pending_out" | python3 -c "
import sys,json,time
tasks=json.load(sys.stdin)
now_ms=int(time.time()*1000)
for t in tasks[:2]:
    to=t.get('to_agent','?')[:10]; title=(t.get('title') or '?')[:35]
    ts_ms=t.get('created_at',0); diff_s=(now_ms-ts_ms)//1000
    age=f'{diff_s//60}m' if diff_s>=60 else f'{diff_s}s'
    print(f'  \033[33m→\033[0m \033[37m{title:<35}\033[0m \033[2m→{to:<10} {age:>5}\033[0m')
" 2>/dev/null
  fi
fi

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § B — Pipeline progress
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§ PIPELINE${RST}\n"

books_yaml="$CE_HUB_CWD/config/books.yaml"
if [ -f "$books_yaml" ]; then
  python3 -c "
import re, sys
try:
    content = open('$books_yaml').read()
except:
    print('  \033[2m(books.yaml not found)\033[0m'); sys.exit()

total = content.count('purpose:')
# L0 status
l0_done = len(re.findall(r'l0_status:\s*done', content))
l0_partial = len(re.findall(r'l0_status:\s*partial', content))
l0_pct = int(l0_done / total * 100) if total else 0
bar_len = 20
filled = int(l0_pct / 100 * bar_len)
l0_bar = '\033[32m' + '█'*filled + '\033[2m' + '░'*(bar_len-filled) + '\033[0m'

# L2b recipe status
r_done = len(re.findall(r'recipe_status:\s*done', content))
r_pct = int(r_done / total * 100) if total else 0
r_filled = int(r_pct / 100 * bar_len)
r_bar = '\033[36m' + '█'*r_filled + '\033[2m' + '░'*(bar_len-r_filled) + '\033[0m'

print(f'  L0  [{l0_bar}] {l0_pct:3d}%  {l0_done}/{total} books done, {l0_partial} partial')
print(f'  L2b [{r_bar}] {r_pct:3d}%  {r_done}/{total} books extracted')
print(f'  L2a \033[2mpilot 75 ingredients complete — full build pending\033[0m')
" 2>/dev/null || printf "  ${D}(error reading books.yaml)${RST}\n"
else
  printf "  ${D}books.yaml not found${RST}\n"
fi

# L2a R2 distillation progress
r2_progress="$CE_HUB_CWD/output/l2a/atoms_r2/_progress.json"
printf "${B}§ L2A R2${RST}  "
if [ -f "$r2_progress" ]; then
  python3 -c "
import json, sys
try:
    p = json.load(open('$r2_progress'))
except:
    print('\033[2m(parse error)\033[0m'); sys.exit()
done = p.get('done', 0); total = p.get('total', 21422)
failed = p.get('failed', 0); eta = p.get('eta_seconds', -1)
cost = p.get('cost_estimate_usd', 0)
pct = int(done / total * 100) if total else 0
bar_len = 10
filled = int(pct / 100 * bar_len)
bar = '\033[35m' + '█'*filled + '\033[2m' + '░'*(bar_len-filled) + '\033[0m'
if eta > 0:
    d, r = divmod(eta, 86400); h, m = divmod(r, 3600)
    eta_str = f'{d}d{h}h' if d else (f'{h}h{m}m' if h else f'{m}m')
else:
    eta_str = '?'
fail_str = f'  \033[31mfailed:{failed}\033[0m' if failed > 0 else ''
print(f'[{bar}] {pct}% ({done}/{total}){fail_str}  ETA:{eta_str}  \${cost:.2f}')
" 2>/dev/null || printf "${D}(error)${RST}"
else
  printf "${D}not started${RST}"
fi
printf "\n"

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § C — Queue + Costs (1-2 lines each)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§ QUEUE${RST}  %b\n" "$queue_str"
printf "${B}§ COSTS${RST}  %b\n" "$cost_str"
printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § D — Recent events timeline (last 5 results + dispatches)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§ TIMELINE${RST}  ${D}(recent results)${RST}\n"

if [ "$daemon_ok" = "true" ]; then
  curl -s --noproxy localhost --max-time 1 \
    "$API/api/tasks?limit=5" 2>/dev/null | python3 -c "
import sys, json, time
try:
    tasks = json.load(sys.stdin)
except:
    print('  \033[2m(parse error)\033[0m'); sys.exit()
icons = {'done':'\033[32m✓\033[0m','failed':'\033[31m✗\033[0m',
         'dead_letter':'\033[31m☠\033[0m','running':'\033[33m⏳\033[0m','pending':'\033[2m·\033[0m'}
now_ms = int(time.time()*1000)
for t in tasks[:5]:
    st = t.get('status','?')
    ic = icons.get(st, '\033[2m?\033[0m')
    title = (t.get('title') or '?')[:35]
    to_a = (t.get('to_agent') or '?')[:8]
    ts_ms = t.get('completed_at') or t.get('started_at') or t.get('created_at') or 0
    diff_s = (now_ms - ts_ms) // 1000
    if diff_s < 60:       age = f'{diff_s}s'
    elif diff_s < 3600:   age = f'{diff_s//60}m'
    else:                 age = f'{diff_s//3600}h{diff_s%3600//60}m'
    print(f'  {ic} {to_a:<8} \033[37m{title:<35}\033[0m \033[2m{age:>6}\033[0m')
" 2>/dev/null || printf "  ${D}(offline)${RST}\n"
fi

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § E — Services health (compact, 1-2 lines)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§ SERVICES${RST}  "
printf "$(check_port 8750) daemon  "
printf "$(check_port 11434) ollama  "
printf "$(check_port 7687) neo4j  "
printf "$(check_port 3456) cloudcli  "
printf "$(check_port 3333) mctl\n"

# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# § H — Mac Mini (jify) harvest status (cached, ssh every 60s via /tmp file)
# ─────────────────────────────────────────────────────────────────────────────
JIFY_CACHE="/tmp/cehub-jify-status"
JIFY_AGE=$(($(date +%s) - $(stat -f %m "$JIFY_CACHE" 2>/dev/null || echo 0)))
if [ ! -f "$JIFY_CACHE" ] || [ $JIFY_AGE -gt 60 ]; then
  ssh -o ConnectTimeout=2 -o BatchMode=yes jify '
    queue=$(grep -hvc "^#\\|^$" ~/culinary-mind-mini/config/harvest-queue.txt ~/culinary-mind-mini/config/flavor-databases.txt ~/culinary-mind-mini/config/serious-eats-foodlab.txt ~/culinary-mind-mini/config/tds-brands.txt 2>/dev/null | awk "{s+=\$1} END {print s}")
    done=$(find ~/culinary-mind-mini/data/raw -type f 2>/dev/null | wc -l | tr -d " ")
    orch=$(pgrep -f harvest-orchestrator >/dev/null && echo running || echo idle)
    claw=$(pgrep -f openclaw >/dev/null && echo running || echo idle)
    echo "$queue|$done|$orch|$claw"
  ' > "$JIFY_CACHE" 2>/dev/null || echo "offline|||" > "$JIFY_CACHE"
fi
IFS="|" read jify_q jify_d jify_o jify_c < "$JIFY_CACHE"
if [ "$jify_q" = "offline" ]; then
  printf "${B}§ JIFY${RST}  ${R}○${RST} offline\n"
else
  [ "$jify_o" = "running" ] && orch_dot="${G}●${RST}" || orch_dot="${D}○${RST}"
  [ "$jify_c" = "running" ] && claw_dot="${G}●${RST}" || claw_dot="${D}○${RST}"
  printf "${B}§ JIFY${RST}  ${G}●${RST} jify  ${D}queue:${RST}${jify_q}  ${D}done:${RST}${jify_d}  ${orch_dot}orch ${claw_dot}claw\n"
fi

# ─────────────────────────────────────────────────────────────────────────────
# § F — System resources (1 line)
# ─────────────────────────────────────────────────────────────────────────────
mem_info=$(python3 -c "
import subprocess, re
try:
    out = subprocess.check_output(['vm_stat'], text=True)
    pages_free = int(re.search(r'Pages free:\s+(\d+)', out).group(1))
    pages_active = int(re.search(r'Pages active:\s+(\d+)', out).group(1))
    pages_wired = int(re.search(r'Pages wired down:\s+(\d+)', out).group(1))
    pages_compressed = int(re.search(r'Pages stored in compressor:\s+(\d+)', out).group(1))
    page_sz = 4096
    used_gb = (pages_active + pages_wired + pages_compressed) * page_sz / 1024**3
    free_gb = pages_free * page_sz / 1024**3
    print(f'mem: {used_gb:.0f}G/{used_gb+free_gb:.0f}G')
except Exception as e:
    print('mem: ?')
" 2>/dev/null)

disk_info=$(df -h "$HOME" 2>/dev/null | tail -1 | awk '{print "disk: "$4" free"}')

ollama_vram=""
if nc -z -w2 -G2 localhost 11434 2>/dev/null; then
  model_count=$(curl -s --noproxy localhost --max-time 1 http://localhost:11434/api/tags 2>/dev/null | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "?")
  ollama_vram="${model_count} models"
fi

printf "${B}§ SYS${RST}  ${D}${mem_info}  ${disk_info}${RST}"
[ -n "$ollama_vram" ] && printf "  ${D}ollama: ${ollama_vram}${RST}"
printf "\n"

printf "$SEP\n"

# ─────────────────────────────────────────────────────────────────────────────
# § G — Wiki + Alerts (compact)
# ─────────────────────────────────────────────────────────────────────────────
printf "${B}§ WIKI${RST}  "

wiki_status_file="$CE_HUB_CWD/wiki/STATUS.md"
conflicts_file="$CE_HUB_CWD/wiki/_conflicts.md"

[ -f "$wiki_status_file" ] \
  && printf "${D}updated: ${W}$(stat -f "%Sm" -t "%m-%d %H:%M" "$wiki_status_file" 2>/dev/null || echo ?)${RST}  " \
  || printf "${Y}STATUS.md missing  ${RST}"

conflict_count=0
[ -f "$conflicts_file" ] && conflict_count=$(grep -c '^### 冲突' "$conflicts_file" 2>/dev/null || echo 0)
[ "$conflict_count" -gt 0 ] \
  && printf "${R}⚠ ${conflict_count} conflict(s)${RST}" \
  || printf "${G}✓ no conflicts${RST}"
printf "\n"

# Alerts
alerts=0
alert_msgs=()

[ "$daemon_ok" = "false" ] && { alert_msgs+=("${R}⚠ daemon offline (8750)${RST}"); alerts=$((alerts+1)); }

dispatch_dir="$CE_HUB_CWD/.ce-hub/dispatch"
if [ -d "$dispatch_dir" ]; then
  stuck=$(find "$dispatch_dir" -name "*.json" -mmin +5 2>/dev/null | wc -l | tr -d ' ')
  [ "$stuck" -gt 0 ] && { alert_msgs+=("${Y}⚠ ${stuck} dispatch(es) stuck >5min${RST}"); alerts=$((alerts+1)); }
fi

[ "$conflict_count" -gt 0 ] && { alert_msgs+=("${Y}⚠ ${conflict_count} wiki conflict(s)${RST}"); alerts=$((alerts+1)); }

# Check for inbox messages for this agent
inbox_dir="$CE_HUB_CWD/.ce-hub/inbox/${CURRENT_AGENT}"
if [ -d "$inbox_dir" ]; then
  inbox_count=$(ls "$inbox_dir"/*.json 2>/dev/null | wc -l | tr -d ' ')
  [ "$inbox_count" -gt 0 ] && { alert_msgs+=("${C}📬 ${inbox_count} inbox msg(s)${RST}"); alerts=$((alerts+1)); }
fi

printf "${B}§ ALERTS${RST}  "
if [ $alerts -eq 0 ]; then
  printf "${G}✓ all clear${RST}\n"
else
  printf "\n"
  for msg in "${alert_msgs[@]}"; do
    printf "  %b\n" "$msg"
  done
fi
printf "\n"
