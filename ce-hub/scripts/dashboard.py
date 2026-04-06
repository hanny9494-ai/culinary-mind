#!/usr/bin/env python3
"""ce-hub dashboard — real-time TUI status panel for tmux pane."""

import json
import glob
import os
import time
import subprocess
import sys
import signal
import urllib.request

API = os.environ.get("CE_HUB_API", "http://localhost:8750")
CLAUDE_PROJ_DIR = os.path.expanduser("~/.claude/projects")
CLAUDE_SESSIONS_DIR = os.path.expanduser("~/.claude/sessions")
CE_HUB_CWD = os.environ.get("CE_HUB_CWD", os.path.expanduser("~/culinary-engine"))
REFRESH = int(os.environ.get("DASHBOARD_REFRESH", "8"))

# ANSI colors
RST = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_BLACK = "\033[40m"
GRAY = "\033[90m"


def api_get(path):
    """GET from ce-hub API, bypass proxy."""
    try:
        handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(f"{API}{path}", headers={"Accept": "application/json"})
        with opener.open(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def get_tmux_windows():
    """List tmux windows in cehub session."""
    try:
        out = subprocess.check_output(
            ["tmux", "list-windows", "-t", "cehub", "-F",
             "#{window_name} #{window_active} #{window_activity}"],
            text=True, timeout=3, stderr=subprocess.DEVNULL
        ).strip()
        windows = []
        for line in out.split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                name = parts[0]
                active = parts[1] == "1"
                activity = int(parts[2]) if len(parts) > 2 else 0
                windows.append({"name": name, "active": active, "activity": activity})
        return windows
    except Exception:
        return []


_token_cache = {"data": None, "time": 0}

def get_claude_token_stats():
    """Parse Claude Code JSONL sessions for token usage. Cached for 60s."""
    now = time.time()
    if _token_cache["data"] and now - _token_cache["time"] < 60:
        return _token_cache["data"]

    # Find all project dirs that could have sessions
    all_jsonl = []
    for proj in glob.glob(f"{CLAUDE_PROJ_DIR}/*/"):
        all_jsonl.extend(glob.glob(os.path.join(proj, "*.jsonl")))

    now = time.time()
    stats = {"5h": {"input": 0, "output": 0, "sessions": 0},
             "all": {"input": 0, "output": 0, "sessions": 0}}

    for fpath in all_jsonl:
        mtime = os.path.getmtime(fpath)
        age_h = (now - mtime) / 3600
        sess_in = 0
        sess_out = 0
        try:
            with open(fpath) as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                        if d.get("type") != "assistant":
                            continue
                        usage = d.get("message", {}).get("usage", {})
                        inp = usage.get("input_tokens", 0)
                        out = usage.get("output_tokens", 0)
                        cr = usage.get("cache_read_input_tokens", 0)
                        cc = usage.get("cache_creation_input_tokens", 0)
                        sess_in += inp + cr + cc
                        sess_out += out
                    except (json.JSONDecodeError, AttributeError):
                        pass
        except Exception:
            continue

        stats["all"]["input"] += sess_in
        stats["all"]["output"] += sess_out
        stats["all"]["sessions"] += 1
        if age_h <= 5:
            stats["5h"]["input"] += sess_in
            stats["5h"]["output"] += sess_out
            stats["5h"]["sessions"] += 1

    _token_cache["data"] = stats
    _token_cache["time"] = time.time()
    return stats


def get_active_claude_sessions():
    """Count running Claude Code sessions from session files."""
    active = 0
    total = 0
    try:
        for f in glob.glob(f"{CLAUDE_SESSIONS_DIR}/*.json"):
            total += 1
            try:
                with open(f) as fh:
                    data = json.load(fh)
                pid = data.get("pid")
                if pid:
                    os.kill(pid, 0)  # check if alive
                    active += 1
            except (ProcessLookupError, PermissionError, json.JSONDecodeError):
                pass
    except Exception:
        pass
    return active, total


def fmt_tokens(n):
    """Format token count."""
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def fmt_uptime(seconds):
    """Format uptime."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds//60}m{seconds%60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h{m}m"


def fmt_age(ts):
    """Format timestamp age."""
    if not ts:
        return "?"
    diff = time.time() - ts
    if diff < 60:
        return "now"
    if diff < 3600:
        return f"{int(diff/60)}m ago"
    if diff < 86400:
        return f"{int(diff/3600)}h ago"
    return f"{int(diff/86400)}d ago"


def bar(pct, width=20):
    """Render a percentage bar."""
    filled = int(pct / 100 * width)
    return f"{GREEN}{'#' * filled}{GRAY}{'.' * (width - filled)}{RST}"


def render(term_width=80, term_height=40):
    """Render one frame of the dashboard."""
    lines = []
    w = min(term_width, 82)

    # Header
    now_str = time.strftime("%H:%M:%S")
    header = f" CE-HUB DASHBOARD "
    pad = w - len(header) - len(now_str) - 4
    lines.append(f"{BOLD}{CYAN}{'=' * 2}{header}{'=' * max(pad, 2)} {DIM}{now_str}{RST}")

    # === API Health ===
    health = api_get("/api/health")
    if not health:
        lines.append(f"  {RED}!! ce-hub API unreachable ({API}){RST}")
        lines.append("")
    else:
        uptime = health.get("uptime", 0)
        task_count = health.get("taskCount", 0)
        lines.append(f"  {GREEN}* daemon up{RST} {DIM}{fmt_uptime(uptime)}{RST}  "
                      f"{WHITE}tasks: {BOLD}{task_count}{RST}")
        lines.append("")

    # === Agent Status ===
    lines.append(f"{BOLD}{YELLOW}  AGENTS{RST}")

    agents = health.get("agents", []) if health else []
    tmux_wins = get_tmux_windows()
    win_names = {w["name"] for w in tmux_wins}

    for agent in agents:
        name = agent["name"]
        alive = agent.get("alive", False) or name in win_names
        # Find tmux window activity for age
        win = next((w for w in tmux_wins if w["name"] == name), None)
        age_str = fmt_age(win["activity"]) if win else ""

        if alive:
            status = f"{GREEN}LIVE{RST}"
        else:
            status = f"{GRAY}off {RST}"

        # Pad name
        padded = f"{name:<22}"
        lines.append(f"    {status}  {padded} {DIM}{age_str}{RST}")

    lines.append("")

    # === Task Queue ===
    lines.append(f"{BOLD}{BLUE}  TASK QUEUE{RST}")

    tasks = api_get("/api/tasks")
    if tasks and len(tasks) > 0:
        # Group by status
        by_status = {}
        for t in tasks:
            s = t.get("status", "unknown")
            by_status.setdefault(s, []).append(t)

        status_order = ["in_progress", "pending", "queued", "done", "failed"]
        for s in status_order:
            if s not in by_status:
                continue
            color = GREEN if s == "done" else YELLOW if s in ("pending", "queued") else CYAN if s == "in_progress" else RED
            lines.append(f"    {color}{s}{RST}: {len(by_status[s])}")
            for t in by_status[s][:3]:
                title = t.get("title", "?")[:40]
                agent = t.get("to_agent", "?")
                lines.append(f"      {DIM}- {title} -> {agent}{RST}")
            if len(by_status[s]) > 3:
                lines.append(f"      {DIM}  ...+{len(by_status[s])-3} more{RST}")
    else:
        lines.append(f"    {DIM}(empty){RST}")

    # Queue pressure
    if health:
        qs = health.get("queueStats", {})
        parts = []
        for q in ["opus", "flash", "ollama"]:
            info = qs.get(q, {})
            pending = info.get("pending", 0)
            color = RED if pending > 2 else YELLOW if pending > 0 else GRAY
            parts.append(f"{color}{q}:{pending}{RST}")
        lines.append(f"    queues: {' '.join(parts)}")

    lines.append("")

    # === Token Consumption ===
    lines.append(f"{BOLD}{MAGENTA}  TOKEN USAGE{RST}")

    token_stats = get_claude_token_stats()
    active_sess, total_sess = get_active_claude_sessions()

    s5 = token_stats["5h"]
    sa = token_stats["all"]

    lines.append(f"    {WHITE}Last 5h{RST}  "
                  f"in: {CYAN}{fmt_tokens(s5['input'])}{RST}  "
                  f"out: {CYAN}{fmt_tokens(s5['output'])}{RST}  "
                  f"({s5['sessions']} sess)")
    lines.append(f"    {WHITE}All time{RST}  "
                  f"in: {CYAN}{fmt_tokens(sa['input'])}{RST}  "
                  f"out: {CYAN}{fmt_tokens(sa['output'])}{RST}  "
                  f"({sa['sessions']} sess)")
    lines.append(f"    {WHITE}Live sessions{RST}: {GREEN}{active_sess}{RST}/{total_sess}")

    lines.append("")

    # === Costs ===
    costs = api_get("/api/costs")
    if costs:
        daily = costs.get("daily", 0)
        weekly = costs.get("weekly", 0)
        lines.append(f"{BOLD}{RED}  COSTS{RST}")
        lines.append(f"    daily: ${daily:.2f}  weekly: ${weekly:.2f}")

        agent_costs = costs.get("agents", {})
        if agent_costs:
            for name, c in sorted(agent_costs.items(), key=lambda x: x[1], reverse=True)[:5]:
                lines.append(f"      {name}: ${c:.2f}")
        lines.append("")

    # === Schedules ===
    schedules = api_get("/api/schedules")
    if schedules and len(schedules) > 0:
        lines.append(f"{BOLD}{WHITE}  SCHEDULES{RST}")
        for s in schedules[:4]:
            cron = s.get("cron", "?")
            task = s.get("task", "?")[:35]
            agent = s.get("agent", "?")
            lines.append(f"    {DIM}{cron}{RST}  {task} -> {agent}")
        lines.append("")

    # === File Protocol Status ===
    ce_hub_dir = os.path.join(CE_HUB_CWD, ".ce-hub")
    dispatch_count = len(glob.glob(os.path.join(ce_hub_dir, "dispatch", "*.json")))
    results_count = len(glob.glob(os.path.join(ce_hub_dir, "results", "*.json")))
    inbox_count = sum(len(glob.glob(os.path.join(d, "*.json")))
                      for d in glob.glob(os.path.join(ce_hub_dir, "inbox", "*")))

    if dispatch_count + results_count + inbox_count > 0:
        lines.append(f"{BOLD}{WHITE}  FILE PROTOCOL{RST}")
        lines.append(f"    dispatch: {dispatch_count}  inbox: {inbox_count}  results: {results_count}")
        lines.append("")

    # Footer
    lines.append(f"{DIM}{'─' * w}{RST}")
    lines.append(f"{DIM}  refresh: {REFRESH}s | right-click: context menu | drag border: resize{RST}")

    return "\n".join(lines)


def main():
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    while True:
        try:
            # Get terminal size
            try:
                cols, rows = os.get_terminal_size()
            except OSError:
                cols, rows = 80, 40

            output = render(cols, rows)
            # Clear and redraw
            sys.stdout.write("\033[2J\033[H")  # clear screen + home
            sys.stdout.write(output)
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(f"\033[2J\033[H")
            sys.stdout.write(f"Dashboard error: {e}\n")
            sys.stdout.flush()

        time.sleep(REFRESH)


if __name__ == "__main__":
    main()
