#!/usr/bin/env python3
"""compile-wiki.py — Knowledge compiler: raw/ → wiki/

Reads raw JSONL archives + project state, calls Qwen Flash API (DashScope),
generates structured wiki markdown files. Runs as a pipeline — start, compile, exit.

Usage:
  compile-wiki.py              — incremental compile (since last run)
  compile-wiki.py --full       — full compile from all sources
  compile-wiki.py --dry-run    — show what would be compiled, don't call API
"""

import json
import os
import sys
import glob
import time
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

CE_HUB_CWD = os.environ.get("CE_HUB_CWD", os.path.expanduser("~/culinary-engine"))
CE_HUB_DIR = os.path.join(CE_HUB_CWD, ".ce-hub")
RAW_DIR = os.path.join(CE_HUB_DIR, "raw")
WIKI_DIR = os.path.join(CE_HUB_DIR, "wiki")
COMPILER_DIR = os.path.join(CE_HUB_DIR, "compiler")
LAST_COMPILE_FILE = os.path.join(COMPILER_DIR, "last-compile.json")
PROGRESS_FILE = os.path.join(COMPILER_DIR, "progress.json")

DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
MODEL = "qwen3.5-flash"  # Qwen 3.5 Flash — fast, cheap, good for compilation

# Ensure directories
for d in [RAW_DIR, WIKI_DIR, COMPILER_DIR, os.path.join(WIKI_DIR, "books"), os.path.join(WIKI_DIR, "agents")]:
    os.makedirs(d, exist_ok=True)


def write_progress(step, total, status="running"):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"completed": step, "total": total, "status": status}, f)


def call_llm(system_prompt, user_prompt, max_tokens=4096):
    """Call DashScope Qwen API."""
    if not DASHSCOPE_API_KEY:
        print("[compiler] ERROR: DASHSCOPE_API_KEY not set")
        return None

    payload = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }).encode()

    req = urllib.request.Request(
        DASHSCOPE_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        },
    )

    try:
        # Bypass local proxy
        handler = urllib.request.ProxyHandler({})
        opener = urllib.request.build_opener(handler)
        with opener.open(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[compiler] API error: {e}")
        return None


def get_last_compile_time():
    if os.path.exists(LAST_COMPILE_FILE):
        with open(LAST_COMPILE_FILE) as f:
            data = json.load(f)
            return data.get("compiled_at", "")
    return ""


def read_jsonl_since(filepath, since_iso=""):
    """Read JSONL lines archived after `since_iso` timestamp."""
    lines = []
    if not os.path.exists(filepath):
        return lines
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                archived = entry.get("_archived_at", "")
                if not since_iso or archived > since_iso:
                    lines.append(entry)
            except json.JSONDecodeError:
                pass
    return lines


def get_git_log(since_iso=""):
    """Get recent git commits."""
    try:
        args = ["git", "log", "--oneline", "-30"]
        if since_iso:
            args.extend(["--since", since_iso])
        out = subprocess.check_output(args, cwd=CE_HUB_CWD, text=True, timeout=10)
        return out.strip()
    except Exception:
        return ""


def get_books_summary():
    """Read config/books.yaml for book list."""
    books_yaml = os.path.join(CE_HUB_CWD, "config", "books.yaml")
    if not os.path.exists(books_yaml):
        return "books.yaml not found"
    with open(books_yaml) as f:
        return f.read()[:3000]  # first 3K chars


def get_pipeline_progress():
    """Scan output directories for pipeline status."""
    output_dir = os.path.join(CE_HUB_CWD, "output")
    if not os.path.isdir(output_dir):
        return "No output directory"

    summaries = []
    for book_dir in sorted(glob.glob(os.path.join(output_dir, "*")))[:50]:
        if not os.path.isdir(book_dir):
            continue
        book_id = os.path.basename(book_dir)
        if book_id.startswith(".") or book_id.startswith("_"):
            continue

        stages = {}
        for stage in ["stage1", "stage4", "stage4_phaseB", "stage5", "l2a"]:
            progress_file = os.path.join(book_dir, stage, "progress.json")
            if os.path.exists(progress_file):
                try:
                    with open(progress_file) as f:
                        prog = json.load(f)
                    if isinstance(prog, dict):
                        total = prog.get("total", 0)
                        done = prog.get("completed", prog.get("done", 0))
                        pct = int(done / total * 100) if total > 0 else 0
                        stages[stage] = f"{pct}%"
                except Exception:
                    pass

        if stages:
            summaries.append(f"- {book_id}: {stages}")

    return "\n".join(summaries) if summaries else "No pipeline progress found"


def read_existing_wiki(filename):
    """Read existing wiki file for incremental update."""
    path = os.path.join(WIKI_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return f.read()
    return ""


def compile_status(dispatches, results, git_log, pipeline_progress, project_state=None, cehub_git=None):
    """Compile wiki/STATUS.md."""
    print("[compiler] Compiling STATUS.md...")

    existing = read_existing_wiki("STATUS.md")
    claude_md = ""
    claude_md_path = os.path.join(CE_HUB_CWD, "CLAUDE.md")
    if os.path.exists(claude_md_path):
        with open(claude_md_path) as f:
            claude_md = f.read()[:5000]

    prompt = f"""Based on the following project data, generate an updated STATUS.md for the culinary-engine project.

## Current CLAUDE.md (project handbook, first 5K chars):
{claude_md}

## Previous STATUS.md:
{existing[:3000] if existing else '(first compile, no previous status)'}

## Recent dispatches (tasks sent to agents):
{json.dumps(dispatches[-20:], ensure_ascii=False, indent=1) if dispatches else '(none)'}

## Recent results (completed work):
{json.dumps(results[-20:], ensure_ascii=False, indent=1) if results else '(none)'}

## Git log:
{git_log or '(no recent commits)'}

## Pipeline progress:
{pipeline_progress}

## Current project state snapshot (latest):
{json.dumps(project_state[-1] if project_state else {}, ensure_ascii=False, indent=1)[:3000]}

## ce-hub recent commits:
{chr(10).join(f"- {c.get('date','')[:10]} {c.get('subject','')}" for c in (cehub_git or [])[:15])}

Generate a concise STATUS.md in Chinese with these sections:
1. 项目概况 (one paragraph)
2. 七层架构状态表 (L0/L1/L2a/L2b/L2c/FT/L3/L6 with completion %)
3. 当前进行中的工作
4. 最近完成的工作
5. 阻塞项和待决事项
6. 下一步计划

Use markdown formatting. Be factual, based only on the data provided."""

    result = call_llm(
        "你是 culinary-engine 项目的知识编译器。根据原始数据生成结构化的项目状态文档。只使用提供的数据，不要猜测。",
        prompt,
        max_tokens=3000,
    )
    if result:
        with open(os.path.join(WIKI_DIR, "STATUS.md"), "w") as f:
            f.write(result)
        print("[compiler] STATUS.md written")
    return result


def compile_decisions(claude_md_content):
    """Compile wiki/DECISIONS.md from CLAUDE.md decision records."""
    print("[compiler] Compiling DECISIONS.md...")

    prompt = f"""Extract all numbered decisions from this project handbook and create a structured DECISIONS.md index.

## Source (CLAUDE.md):
{claude_md_content}

Generate a DECISIONS.md with:
- A table: | # | 决策 | 领域 | 影响 |
- Each decision as a row, extracted from the "关键技术决策" section and any other numbered decisions
- Group by category (Pipeline, Architecture, Resources, Git)
- In Chinese

Only include decisions that are explicitly stated. Do not invent new ones."""

    result = call_llm(
        "你是项目知识编译器。从项目手册中提取所有技术决策，生成结构化索引。",
        prompt,
        max_tokens=3000,
    )
    if result:
        with open(os.path.join(WIKI_DIR, "DECISIONS.md"), "w") as f:
            f.write(result)
        print("[compiler] DECISIONS.md written")
    return result


def compile_architecture(claude_md_content):
    """Compile wiki/ARCHITECTURE.md."""
    print("[compiler] Compiling ARCHITECTURE.md...")

    prompt = f"""From this project handbook, generate an ARCHITECTURE.md describing the 7-layer knowledge architecture.

## Source:
{claude_md_content}

Generate in Chinese:
1. 架构总览图 (ASCII art showing 7 layers)
2. 每层详细说明 (purpose, current status, key files/paths)
3. 数据流 (how data moves between layers)
4. 17 个科学域列表
5. 关键技术栈 (Neo4j, LangGraph, Ollama, etc.)"""

    result = call_llm(
        "你是项目知识编译器。生成项目架构文档。",
        prompt,
        max_tokens=3000,
    )
    if result:
        with open(os.path.join(WIKI_DIR, "ARCHITECTURE.md"), "w") as f:
            f.write(result)
        print("[compiler] ARCHITECTURE.md written")
    return result


def compile_changelog(dispatches, results, git_log):
    """Compile wiki/CHANGELOG.md — daily changes summary."""
    print("[compiler] Compiling CHANGELOG.md...")

    existing = read_existing_wiki("CHANGELOG.md")
    today = datetime.now().strftime("%Y-%m-%d")

    prompt = f"""Generate a daily changelog entry for {today} based on this data:

## Dispatches today:
{json.dumps(dispatches[-15:], ensure_ascii=False, indent=1) if dispatches else '(none)'}

## Results today:
{json.dumps(results[-15:], ensure_ascii=False, indent=1) if results else '(none)'}

## Git commits today:
{git_log or '(none)'}

Generate a concise changelog entry in this format:
## {today}
- bullet point summaries of what happened
- focus on outcomes, not mechanics

Only generate TODAY's entry. I will prepend it to the existing changelog."""

    result = call_llm(
        "你是项目知识编译器。生成每日变更日志。",
        prompt,
        max_tokens=1000,
    )
    if result:
        # Prepend today's entry to existing changelog
        full = result.strip() + "\n\n" + existing if existing else result.strip()
        with open(os.path.join(WIKI_DIR, "CHANGELOG.md"), "w") as f:
            f.write(full)
        print("[compiler] CHANGELOG.md written")
    return result


def compile_agent_context(agent_name, dispatches, results):
    """Compile wiki/agents/{name}.md — agent-specific context."""
    # Filter dispatches/results for this agent
    agent_dispatches = [d for d in dispatches if d.get("to") == agent_name]
    agent_results = [r for r in results if r.get("from") == agent_name]

    if not agent_dispatches and not agent_results:
        return  # No activity, skip

    print(f"[compiler] Compiling agents/{agent_name}.md...")

    # Read agent definition
    agent_def = ""
    agent_file = os.path.join(CE_HUB_CWD, ".claude", "agents", f"{agent_name}.md")
    if os.path.exists(agent_file):
        with open(agent_file) as f:
            agent_def = f.read()[:1000]

    existing = read_existing_wiki(f"agents/{agent_name}.md")

    prompt = f"""Update the context page for agent "{agent_name}".

## Agent definition:
{agent_def or '(no definition file)'}

## Previous context:
{existing[:1500] if existing else '(first compile)'}

## Recent tasks dispatched to this agent:
{json.dumps(agent_dispatches[-10:], ensure_ascii=False, indent=1)}

## Recent results from this agent:
{json.dumps(agent_results[-10:], ensure_ascii=False, indent=1)}

Generate a concise context page in Chinese:
1. 角色简介
2. 最近完成的工作
3. 进行中/待处理的任务
4. 关键经验和注意事项（从 results 中提取）"""

    result = call_llm(
        "你是项目知识编译器。更新 agent 上下文页面。",
        prompt,
        max_tokens=1500,
    )
    if result:
        with open(os.path.join(WIKI_DIR, "agents", f"{agent_name}.md"), "w") as f:
            f.write(result)


def main():
    full_mode = "--full" in sys.argv
    dry_run = "--dry-run" in sys.argv

    print(f"[compiler] Starting {'full' if full_mode else 'incremental'} compile...")
    print(f"[compiler] CE_HUB_CWD: {CE_HUB_CWD}")
    print(f"[compiler] API model: {MODEL}")

    if not DASHSCOPE_API_KEY:
        print("[compiler] ERROR: DASHSCOPE_API_KEY not set. Set it in environment.")
        sys.exit(1)

    since = "" if full_mode else get_last_compile_time()
    if since:
        print(f"[compiler] Incremental since: {since}")

    # Gather raw data
    write_progress(0, 6)

    dispatches = read_jsonl_since(os.path.join(RAW_DIR, "dispatches.jsonl"), since)
    results = read_jsonl_since(os.path.join(RAW_DIR, "results.jsonl"), since)
    git_log = get_git_log(since)
    pipeline_progress = get_pipeline_progress()

    # Additional data sources
    project_state = read_jsonl_since(os.path.join(RAW_DIR, "project-state.jsonl"), "")  # always read full
    cehub_git = read_jsonl_since(os.path.join(RAW_DIR, "cehub-git-log.jsonl"), since)
    decisions_raw = read_jsonl_since(os.path.join(RAW_DIR, "decisions.jsonl"), "")

    print(f"[compiler] Raw data: {len(dispatches)} dispatches, {len(results)} results, {len(git_log.splitlines())} commits")
    print(f"[compiler] Extra: {len(project_state)} state snapshots, {len(cehub_git)} ce-hub commits, {len(decisions_raw)} decisions")

    if dry_run:
        print("[compiler] DRY RUN — would compile:")
        print(f"  STATUS.md, DECISIONS.md, ARCHITECTURE.md, CHANGELOG.md")
        agents_seen = set(d.get("to", "") for d in dispatches) | set(r.get("from", "") for r in results)
        for a in agents_seen:
            if a:
                print(f"  agents/{a}.md")
        return

    # Read CLAUDE.md for decisions + architecture
    claude_md = ""
    claude_md_path = os.path.join(CE_HUB_CWD, "CLAUDE.md")
    if os.path.exists(claude_md_path):
        with open(claude_md_path) as f:
            claude_md = f.read()

    # Compile each wiki page
    write_progress(1, 6)
    compile_status(dispatches, results, git_log, pipeline_progress, project_state, cehub_git)

    write_progress(2, 6)
    compile_decisions(claude_md)

    write_progress(3, 6)
    compile_architecture(claude_md)

    write_progress(4, 6)
    compile_changelog(dispatches, results, git_log)

    # Compile agent-specific contexts
    write_progress(5, 6)
    agents_seen = set(d.get("to", "") for d in dispatches) | set(r.get("from", "") for r in results)
    for agent_name in sorted(agents_seen):
        if agent_name and agent_name != "system":
            compile_agent_context(agent_name, dispatches, results)

    # Save compile metadata
    write_progress(6, 6, "completed")
    compile_meta = {
        "compiled_at": datetime.now().isoformat(),
        "mode": "full" if full_mode else "incremental",
        "dispatches_processed": len(dispatches),
        "results_processed": len(results),
        "commits_processed": len(git_log.splitlines()),
        "wiki_files": len(glob.glob(os.path.join(WIKI_DIR, "**/*.md"), recursive=True)),
    }
    with open(LAST_COMPILE_FILE, "w") as f:
        json.dump(compile_meta, f, indent=2)

    print(f"[compiler] Done! {compile_meta['wiki_files']} wiki files generated.")
    print(f"[compiler] Wiki at: {WIKI_DIR}")


if __name__ == "__main__":
    main()
