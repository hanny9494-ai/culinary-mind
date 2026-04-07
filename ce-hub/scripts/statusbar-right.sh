#!/bin/bash
# statusbar-right.sh — Compact right status: daemon health + tasks + tokens
# Fast: must complete in <1s. Uses cached token stats.

CE_HUB_CWD="${CE_HUB_CWD:-$HOME/culinary-mind}"
API="http://localhost:8750"

health=$(curl -s --noproxy localhost --max-time 1 "$API/api/health" 2>/dev/null)

if [ -z "$health" ]; then
  echo "daemon:OFF"
  exit 0
fi

tasks=$(echo "$health" | python3 -c "import sys,json;print(json.load(sys.stdin).get('taskCount',0))" 2>/dev/null || echo "?")
agents_alive=$(echo "$health" | python3 -c "import sys,json;d=json.load(sys.stdin);print(sum(1 for a in d.get('agents',[]) if a.get('alive')))" 2>/dev/null || echo "0")
agents_total=$(echo "$health" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('agents',[])))" 2>/dev/null || echo "?")

# Token stats (cached, update every 30s)
CACHE="/tmp/cehub-tok-cache"
if [ ! -f "$CACHE" ] || [ "$(( $(date +%s) - $(stat -f %m "$CACHE" 2>/dev/null || echo 0) ))" -gt 30 ]; then
  python3 -c "
import json,glob,os,time
now=time.time()
total_in=0; s5_in=0
for f in glob.glob(os.path.expanduser('~/.claude/projects/*/*.jsonl')):
  age=(now-os.path.getmtime(f))/3600
  si=0
  try:
    with open(f) as fh:
      for line in fh:
        if '\"usage\"' not in line: continue
        try:
          d=json.loads(line)
          if d.get('type')!='assistant': continue
          u=d.get('message',{}).get('usage',{})
          si+=u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0)
        except: pass
  except: pass
  total_in+=si
  if age<=5: s5_in+=si
def fmt(n):
  if n>=1e9: return f'{n/1e9:.1f}B'
  if n>=1e6: return f'{n/1e6:.0f}M'
  if n>=1e3: return f'{n/1e3:.0f}K'
  return str(n)
print(f'{fmt(s5_in)}|{fmt(total_in)}')
" > "$CACHE" 2>/dev/null
fi
tokens=$(cat "$CACHE" 2>/dev/null || echo "?|?")
tok5h=$(echo "$tokens" | cut -d'|' -f1)
tokall=$(echo "$tokens" | cut -d'|' -f2)

echo "a:${agents_alive}/${agents_total} t:${tasks} tok:${tok5h}/5h"
