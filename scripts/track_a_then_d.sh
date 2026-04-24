#!/bin/bash
set -e
cd ~/culinary-mind

echo "[$(date)] Waiting for Track A to finish..."

# 1. Wait for orchestrator (heldman + campbell)
ORCH_PID=44125
while kill -0 $ORCH_PID 2>/dev/null; do
  sleep 30
done
echo "[$(date)] Orchestrator done"

# 2. Wait for walstra skill A
WALSTRA_PID=49198
while kill -0 $WALSTRA_PID 2>/dev/null; do
  sleep 30
done
echo "[$(date)] walstra skill A done"

# 3. Wait for signal routing (principles_fsts)
while pgrep -f "signal_router.*principles_food_science_fsts" > /dev/null 2>&1; do
  sleep 10
done
echo "[$(date)] principles_fsts signal routing done"

# 4. Update principles_fsts signal status
python3 -c "
import yaml
with open('config/books.yaml') as f:
    books=yaml.safe_load(f)
for b in books:
    if b['id']=='principles_food_science_fsts':
        b['signal_status']='done'
with open('config/books.yaml','w') as f:
    yaml.dump(books,f,allow_unicode=True,default_flow_style=False,sort_keys=False,width=200)
print('principles_fsts: signal=done')
"

# 5. Run principles_fsts skill A
echo "[$(date)] Running principles_fsts skill A..."
python3 pipeline/skills/run_skill.py --skill a --book-id principles_food_science_fsts --resume 2>&1 | tail -5
echo "[$(date)] principles_fsts skill A done"

# 6. Update all books.yaml statuses
python3 -c "
import yaml, os, json
with open('config/books.yaml') as f:
    books=yaml.safe_load(f)
for b in books:
    if b.get('skill_a_status') in ('partial','pending') and 'A' in [s.upper() for s in (b.get('skills') or [])]:
        bid=b['id']
        prog_path=os.path.expanduser(f'~/l0-knowledge-engine/output/{bid}/skill_a/_progress.json')
        if os.path.exists(prog_path):
            with open(prog_path) as f:
                prog=json.load(f)
            if prog.get('done',0)>=prog.get('total',1) and prog.get('total',0)>0:
                b['skill_a_status']='done'
                print(f'{bid}: → done')
with open('config/books.yaml','w') as f:
    yaml.dump(books,f,allow_unicode=True,default_flow_style=False,sort_keys=False,width=200)
"

echo "[$(date)] ====== Track A complete. Starting Track D ======"

# 7. Start Track D
nohup python3 scripts/orchestrator.py \
  --track D \
  --skip-gates \
  --toc-concurrency 5 \
  --skill-concurrency 3 \
  --dashboard-interval 30 \
  > output/orchestrator_trackD_$(date +%Y%m%d_%H%M).log 2>&1 &

echo "[$(date)] Track D started, PID=$!"
