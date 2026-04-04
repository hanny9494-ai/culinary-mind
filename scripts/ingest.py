#!/usr/bin/env python3
"""ingest.py — Collect raw data from culinary-engine into raw/

Sources:
  - docs/research/*.md → raw/reports/
  - reports/*.md → raw/reports/
  - .ce-hub/raw/*.jsonl → raw/ (copy existing)
  - git log → raw/git-log.jsonl
  - tmux pane captures → raw/conversations.jsonl
  - CLAUDE.md decisions → raw/decisions.jsonl
  - config/books.yaml → raw/books.jsonl
  - STATUS.md snapshot → raw/status.jsonl

Usage:
  ingest.py                     — incremental (new files only)
  ingest.py --full              — full re-ingest
  ingest.py --source ~/path     — override project root
  ingest.py --conversations     — only capture tmux conversations
"""

import json
import os
import sys
import glob
import shutil
import subprocess
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

MIND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(MIND_DIR, "raw")
REPORTS_DIR = os.path.join(RAW_DIR, "reports")
INGEST_STATE_FILE = os.path.join(MIND_DIR, ".ingest-state.json")


def ts():
    return datetime.now(timezone.utc).isoformat()


def load_config():
    import yaml
    config_path = os.path.join(MIND_DIR, "config.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_ingest_state():
    if os.path.exists(INGEST_STATE_FILE):
        with open(INGEST_STATE_FILE) as f:
            return json.load(f)
    return {"ingested_files": {}, "last_ingest": ""}


def save_ingest_state(state):
    state["last_ingest"] = ts()
    with open(INGEST_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def append_jsonl(filename, data):
    path = os.path.join(RAW_DIR, filename)
    with open(path, "a") as f:
        f.write(json.dumps({**data, "_ingested_at": ts()}, ensure_ascii=False) + "\n")


def ingest_reports(project_root, state, full=False):
    """Copy .md reports from project into raw/reports/."""
    config = load_config()
    paths = [os.path.expanduser(p) for p in config.get("ingest_paths", [])]
    count = 0

    for search_dir in paths:
        if not os.path.isdir(search_dir):
            continue
        for md_file in glob.glob(os.path.join(search_dir, "*.md")):
            fname = os.path.basename(md_file)
            dest = os.path.join(REPORTS_DIR, fname)
            fhash = file_hash(md_file)

            # Skip if already ingested (same hash)
            if not full and state["ingested_files"].get(md_file) == fhash:
                continue

            shutil.copy2(md_file, dest)
            state["ingested_files"][md_file] = fhash
            count += 1
            print(f"  [report] {fname}")

    print(f"  Reports: {count} new/updated")


def ingest_git_log(project_root):
    """Export git history to raw/git-log.jsonl."""
    try:
        out = subprocess.check_output(
            ["git", "log", "--format=%H|||%h|||%an|||%aI|||%s", "-200"],
            cwd=project_root, text=True, timeout=10
        )
        path = os.path.join(RAW_DIR, "git-log.jsonl")
        with open(path, "w") as f:
            for line in out.strip().split("\n"):
                parts = line.split("|||")
                if len(parts) == 5:
                    f.write(json.dumps({
                        "hash": parts[0], "short": parts[1], "author": parts[2],
                        "date": parts[3], "subject": parts[4], "_ingested_at": ts()
                    }, ensure_ascii=False) + "\n")
        print(f"  Git log: {len(out.strip().splitlines())} commits")
    except Exception as e:
        print(f"  Git log: failed ({e})")


def ingest_decisions(project_root):
    """Extract numbered decisions from CLAUDE.md."""
    claude_md = os.path.join(project_root, "CLAUDE.md")
    if not os.path.exists(claude_md):
        return

    with open(claude_md) as f:
        content = f.read()

    path = os.path.join(RAW_DIR, "decisions.jsonl")
    with open(path, "w") as f:
        for text, num in re.findall(r'(.*?决策#(\d+).*)', content):
            f.write(json.dumps({
                "type": "decision", "number": int(num), "text": text.strip(),
                "source": "CLAUDE.md", "_ingested_at": ts()
            }, ensure_ascii=False) + "\n")

    # Also save full CLAUDE.md as a raw source
    claude_dest = os.path.join(REPORTS_DIR, "CLAUDE.md")
    shutil.copy2(claude_md, claude_dest)

    count = len(re.findall(r'决策#(\d+)', content))
    print(f"  Decisions: {count} extracted from CLAUDE.md")


def ingest_books(project_root):
    """Import books.yaml registry."""
    books_yaml = os.path.join(project_root, "config", "books.yaml")
    if not os.path.exists(books_yaml):
        return

    try:
        import yaml
        with open(books_yaml) as f:
            data = yaml.safe_load(f)
        books = data.get("books", []) if isinstance(data, dict) else data if isinstance(data, list) else []

        path = os.path.join(RAW_DIR, "books.jsonl")
        with open(path, "w") as f:
            for b in books:
                if isinstance(b, dict):
                    f.write(json.dumps({**b, "type": "book", "_ingested_at": ts()}, ensure_ascii=False) + "\n")
        print(f"  Books: {len(books)} entries")
    except Exception as e:
        print(f"  Books: failed ({e})")


def ingest_status(project_root):
    """Snapshot STATUS.md."""
    status_md = os.path.join(project_root, "STATUS.md")
    if not os.path.exists(status_md):
        return

    with open(status_md) as f:
        content = f.read()

    path = os.path.join(RAW_DIR, "status.jsonl")
    with open(path, "w") as f:
        f.write(json.dumps({
            "type": "status_snapshot", "content": content,
            "_ingested_at": ts()
        }, ensure_ascii=False) + "\n")

    # Also copy full file
    shutil.copy2(status_md, os.path.join(REPORTS_DIR, "STATUS.md"))
    print(f"  STATUS.md: {len(content)} chars")


def ingest_conversations():
    """Capture recent tmux pane output as conversations."""
    try:
        # Get all panes in cehub session
        panes = subprocess.check_output(
            ["tmux", "list-panes", "-t", "cehub:main", "-F", "#{pane_index}\t#{pane_title}"],
            text=True, timeout=5
        ).strip().split("\n")
    except Exception:
        print("  Conversations: tmux not available")
        return

    count = 0
    for pane_line in panes:
        parts = pane_line.split("\t")
        if len(parts) < 2:
            continue
        pane_idx, pane_title = parts[0], parts[1]

        # Skip task board
        if pane_title == "tasks":
            continue

        # Determine agent name from title
        agent = pane_title.lower().replace("✳ ", "").replace("claude code", "cc-lead").strip()
        if not agent or agent in ("clear session", "session started"):
            agent = "cc-lead" if pane_idx == "0" else f"agent-pane-{pane_idx}"

        try:
            output = subprocess.check_output(
                ["tmux", "capture-pane", "-t", f"cehub:main.{pane_idx}", "-p", "-S", "-50"],
                text=True, timeout=5
            ).strip()

            if len(output) > 20:  # skip near-empty captures
                append_jsonl("conversations.jsonl", {
                    "type": "conversation",
                    "agent": agent,
                    "content": output[-2000:],  # last 2000 chars
                    "source": "tmux_capture"
                })
                count += 1
        except Exception:
            pass

    print(f"  Conversations: {count} panes captured")


def ingest_cehub_raw(project_root):
    """Copy existing .ce-hub/raw/ JSONL files."""
    ce_raw = os.path.join(project_root, ".ce-hub", "raw")
    if not os.path.isdir(ce_raw):
        return

    count = 0
    for f in glob.glob(os.path.join(ce_raw, "*.jsonl")):
        fname = os.path.basename(f)
        dest = os.path.join(RAW_DIR, f"cehub_{fname}")
        shutil.copy2(f, dest)
        count += 1

    print(f"  ce-hub raw: {count} files copied")


def ingest_pipeline_progress(project_root):
    """Scan output/ for pipeline progress."""
    output_dir = os.path.realpath(os.path.join(project_root, "output"))
    if not os.path.isdir(output_dir):
        return

    path = os.path.join(RAW_DIR, "pipeline.jsonl")
    count = 0
    with open(path, "w") as f:
        for pf in glob.glob(os.path.join(output_dir, "**/progress.json"), recursive=True):
            try:
                with open(pf) as pfile:
                    data = json.load(pfile)
                if not isinstance(data, dict):
                    continue
                rel = os.path.relpath(pf, output_dir)
                parts = rel.split(os.sep)
                f.write(json.dumps({
                    "type": "pipeline_progress",
                    "book_id": parts[0],
                    "stage": parts[1] if len(parts) > 1 else "?",
                    "progress": data,
                    "_ingested_at": ts()
                }, ensure_ascii=False) + "\n")
                count += 1
            except Exception:
                pass

    print(f"  Pipeline: {count} progress snapshots")


def main():
    full = "--full" in sys.argv
    conv_only = "--conversations" in sys.argv

    config = load_config()
    project_root = os.path.expanduser(
        next((sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--source"), "")
        or config.get("project_root", "~/culinary-engine")
    )

    print(f"[ingest] {'Full' if full else 'Incremental'} ingest from {project_root}")

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(REPORTS_DIR, exist_ok=True)

    state = load_ingest_state() if not full else {"ingested_files": {}, "last_ingest": ""}

    if conv_only:
        ingest_conversations()
        save_ingest_state(state)
        return

    ingest_reports(project_root, state, full)
    ingest_git_log(project_root)
    ingest_decisions(project_root)
    ingest_books(project_root)
    ingest_status(project_root)
    ingest_conversations()
    ingest_cehub_raw(project_root)
    ingest_pipeline_progress(project_root)

    save_ingest_state(state)
    print(f"[ingest] Done. Raw data at: {RAW_DIR}")


if __name__ == "__main__":
    main()
