#!/usr/bin/env python3
"""10-minute heartbeat: check pipeline progress and report."""
import json, os, time
from datetime import datetime

REPO = "/Users/jeff/culinary-mind"
os.chdir(REPO)

# --- Signal routing progress ---
import yaml
with open("config/books.yaml") as f:
    books = yaml.safe_load(f)

sig_done = 0
sig_partial = []
sig_none = 0
total_books_with_pages = 0
total_pages_routed = 0

for b in books:
    bid = b["id"]
    pj = f"output/{bid}/pages.json"
    if not os.path.exists(pj): continue
    total_books_with_pages += 1
    pages = json.load(open(pj))
    total = len(pages)
    sj = f"output/{bid}/signals.json"
    if os.path.exists(sj):
        sigs = json.load(open(sj))
        total_pages_routed += len(sigs)
        if len(sigs) >= total * 0.9:
            sig_done += 1
        else:
            sig_partial.append(f"{bid}({len(sigs)}/{total})")
    else:
        sig_none += 1

# --- Running processes ---
import subprocess
procs = subprocess.run(
    "ps aux | grep -E 'signal_router|ocr_claw|run_skill' | grep -v grep | grep python",
    shell=True, capture_output=True, text=True
).stdout.strip()
active = []
for line in procs.split("\n"):
    if "signal_router" in line:
        book = line.split("--book-id")[-1].split()[0] if "--book-id" in line else "?"
        active.append(f"signal-router: {book}")
    elif "ocr_claw" in line:
        active.append("ocr-claw: running")
    elif "run_skill" in line:
        skill = line.split("--skill")[-1].split()[0] if "--skill" in line else "?"
        book = line.split("--book-id")[-1].split()[0] if "--book-id" in line else "?"
        active.append(f"skill-{skill}: {book}")

# --- MC OCR status ---
mc_status = []
for vol in ["mc_vol2", "mc_vol3", "mc_vol4"]:
    pj = f"output/{vol}/pages.json"
    parts_dir = f"output/{vol}/parts"
    if os.path.exists(pj):
        p = json.load(open(pj))
        mc_status.append(f"{vol}: {len(p)} pages ✅")
    elif os.path.exists(parts_dir):
        n = len([d for d in os.listdir(parts_dir) if os.path.isdir(f"{parts_dir}/{d}")])
        mc_status.append(f"{vol}: {n} parts done, merging pending")
    else:
        mc_status.append(f"{vol}: not started")

# --- Output ---
now = datetime.now().strftime("%H:%M:%S")
report = f"""📊 Heartbeat {now}
Signal routing: {sig_done}/{total_books_with_pages} complete, {len(sig_partial)} partial, {sig_none} pending
Pages routed: {total_pages_routed:,}
Active: {', '.join(active) if active else 'none'}
MC OCR: {' | '.join(mc_status)}"""

if sig_partial:
    report += f"\nPartial: {', '.join(sig_partial[:5])}"

print(report)

# Write to ce-hub for cc-lead
heartbeat = {
    "from": "heartbeat",
    "type": "status",
    "timestamp": datetime.now().isoformat(),
    "signal_done": sig_done,
    "signal_partial": len(sig_partial),
    "signal_none": sig_none,
    "total_pages_routed": total_pages_routed,
    "active_processes": active,
    "mc_status": mc_status
}
hb_path = f"{REPO}/.ce-hub/results/heartbeat_latest.json"
with open(hb_path, "w") as f:
    json.dump(heartbeat, f, ensure_ascii=False, indent=2)
