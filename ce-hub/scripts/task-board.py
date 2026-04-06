#!/usr/bin/env python3
"""task-board.py — Slim vertical task board for tmux right-side pane."""

import json
import os
import time
import sys
import signal
import urllib.request
import glob

API = os.environ.get("CE_HUB_API", "http://localhost:8750")
CE_HUB_CWD = os.environ.get("CE_HUB_CWD", os.path.expanduser("~/culinary-engine"))
OUTPUT_DIR = os.path.join(CE_HUB_CWD, "output")
REFRESH = int(os.environ.get("BOARD_REFRESH", "6"))

# ANSI
RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
CYAN = "\033[36m"
MAGENTA = "\033[35m"
WHITE = "\033[37m"
GRAY = "\033[90m"


def api_get(path):
    try:
        handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/json"})
        with opener.open(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def get_pipeline_status():
    """Scan output directories for pipeline progress."""
    results = []
    if not os.path.isdir(OUTPUT_DIR):
        return results

    for book_dir in sorted(glob.glob(os.path.join(OUTPUT_DIR, "*"))):
        if not os.path.isdir(book_dir):
            continue
        book_id = os.path.basename(book_dir)
        if book_id.startswith(".") or book_id.startswith("_"):
            continue

        # Check for running stages by looking at progress files
        for stage_name in ["stage1", "stage4", "stage4_phaseB", "stage5"]:
            progress_file = os.path.join(book_dir, stage_name, "progress.json")
            if not os.path.exists(progress_file):
                continue
            try:
                with open(progress_file) as f:
                    prog = json.load(f)
                if not isinstance(prog, dict):
                    continue
                total = prog.get("total", 0)
                done = prog.get("completed", prog.get("done", 0))
                status = prog.get("status", "unknown")
                if total > 0 and done < total and status != "completed":
                    pct = int(done / total * 100) if total > 0 else 0
                    results.append({
                        "book": book_id[:12],
                        "stage": stage_name.replace("stage", "S"),
                        "pct": pct,
                        "done": done,
                        "total": total,
                    })
            except Exception:
                pass

    return results[:5]  # top 5


def get_ollama_status():
    """Check Ollama running models."""
    try:
        handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request("http://localhost:11434/api/ps")
        with opener.open(req, timeout=2) as resp:
            data = json.loads(resp.read())
        models = data.get("models", [])
        return [m.get("name", "?").split(":")[0] for m in models]
    except Exception:
        return None


def fmt_age(ts):
    if not ts:
        return ""
    diff = time.time() - ts / 1000 if ts > 1e12 else time.time() - ts
    if diff < 0:
        diff = 0
    if diff < 60:
        return "now"
    if diff < 3600:
        return f"{int(diff/60)}m"
    if diff < 86400:
        return f"{int(diff/3600)}h"
    return f"{int(diff/86400)}d"


def render(width=20, height=40):
    lines = []
    w = max(width - 1, 16)

    # Header
    lines.append(f"{BOLD}{CYAN}{'─' * w}{RST}")
    lines.append(f"{BOLD}{WHITE} TASKS{RST}")
    lines.append(f"{CYAN}{'─' * w}{RST}")

    # === In Progress ===
    health = api_get("/api/health")
    tasks_raw = api_get("/api/tasks") or []

    in_progress = [t for t in tasks_raw if t.get("status") in ("in_progress", "running")]
    pending = [t for t in tasks_raw if t.get("status") in ("pending", "queued")]
    recent_done = sorted(
        [t for t in tasks_raw if t.get("status") == "done"],
        key=lambda t: t.get("completed_at", 0),
        reverse=True,
    )[:3]
    failed = [t for t in tasks_raw if t.get("status") in ("failed", "dead_letter")]

    if in_progress:
        for t in in_progress[:5]:
            agent = (t.get("to_agent") or "?")[:8]
            title = (t.get("title") or "?")[:w - 4]
            age = fmt_age(t.get("started_at") or t.get("created_at"))
            lines.append(f" {YELLOW}●{RST} {BOLD}{agent}{RST}")
            lines.append(f"   {DIM}{title}{RST}")
            if age:
                lines.append(f"   {GRAY}{age}{RST}")
    else:
        lines.append(f" {GRAY}(no active){RST}")

    lines.append("")

    # === Pipeline Progress ===
    pipeline = get_pipeline_status()
    if pipeline:
        lines.append(f"{BLUE}{'─' * w}{RST}")
        lines.append(f"{BOLD}{BLUE} PIPELINE{RST}")
        for p in pipeline:
            pct = p["pct"]
            bar_w = max(w - 6, 8)
            filled = int(pct / 100 * bar_w)
            bar = f"{GREEN}{'█' * filled}{GRAY}{'░' * (bar_w - filled)}{RST}"
            lines.append(f" {p['stage']} {p['book']}")
            lines.append(f" {bar} {pct}%")
        lines.append("")

    # === Recent Done ===
    if recent_done:
        lines.append(f"{GREEN}{'─' * w}{RST}")
        lines.append(f"{BOLD}{GREEN} DONE{RST}")
        for t in recent_done:
            agent = (t.get("to_agent") or "?")[:8]
            title = (t.get("title") or "?")[:w - 4]
            age = fmt_age(t.get("completed_at"))
            lines.append(f" {GREEN}✓{RST} {agent}")
            lines.append(f"   {DIM}{title}{RST}")
            if age:
                lines.append(f"   {GRAY}{age}{RST}")
        lines.append("")

    # === Failed ===
    if failed:
        lines.append(f"{RED}{'─' * w}{RST}")
        lines.append(f"{BOLD}{RED} FAILED{RST}")
        for t in failed[:3]:
            agent = (t.get("to_agent") or "?")[:8]
            title = (t.get("title") or "?")[:w - 4]
            lines.append(f" {RED}✗{RST} {agent}")
            lines.append(f"   {DIM}{title}{RST}")
        lines.append("")

    # === Pending Queue ===
    if pending:
        lines.append(f"{GRAY}{'─' * w}{RST}")
        lines.append(f" {GRAY}queue: {len(pending)}{RST}")
        for t in pending[:3]:
            agent = (t.get("to_agent") or "?")[:8]
            title = (t.get("title") or "?")[:w - 6]
            lines.append(f"  {GRAY}→ {agent}: {title}{RST}")
        if len(pending) > 3:
            lines.append(f"  {GRAY}+{len(pending) - 3} more{RST}")
        lines.append("")

    # === Agents ===
    agents = health.get("agents", []) if health else []
    alive = [a for a in agents if a.get("alive")]
    if alive:
        lines.append(f"{CYAN}{'─' * w}{RST}")
        lines.append(f"{BOLD}{WHITE} AGENTS{RST}")
        for a in alive:
            lines.append(f" {GREEN}●{RST} {a['name']}")
        lines.append("")

    # === Ollama ===
    ollama = get_ollama_status()
    if ollama is not None:
        lines.append(f"{GRAY}{'─' * w}{RST}")
        if ollama:
            models_str = " ".join(m[:6] for m in ollama)
            lines.append(f" {MAGENTA}ollama{RST} {models_str}")
        else:
            lines.append(f" {GRAY}ollama: idle{RST}")

    # Fill remaining height
    while len(lines) < height - 1:
        lines.append("")

    # Footer
    lines.append(f"{GRAY}{'─' * w}{RST}")

    return "\n".join(lines[:height])


def main():
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    while True:
        try:
            cols, rows = os.get_terminal_size()
        except OSError:
            cols, rows = 20, 40

        output = render(cols, rows)
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write(output)
        sys.stdout.flush()
        time.sleep(REFRESH)


if __name__ == "__main__":
    main()
