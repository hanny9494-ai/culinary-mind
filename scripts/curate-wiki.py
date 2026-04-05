#!/usr/bin/env python3
"""curate-wiki.py — Knowledge Curator with Dreaming Mechanism

6-step curation pipeline using Sonnet 4.6:
  1. INGEST  — read raw/ since last curation
  2. EXTRACT — pull meaningful insights from raw data
  3. DETECT  — check new insights against existing wiki for contradictions
  4. DECIDE  — SKIP / KEEP_SEPARATE / MERGE / REPLACE / UPDATE
  5. WRITE   — update wiki files with frontmatter + [[backlinks]]
  6. DECAY   — age out stale knowledge, archive unused pages

Usage:
  curate-wiki.py              — incremental curation
  curate-wiki.py --full       — full curation from all raw data
  curate-wiki.py --lint-only  — only run health checks
  curate-wiki.py --dry-run    — show what would change, don't write
"""

import json
import os
import sys
import re
import glob
import time
import shutil
import requests
from datetime import datetime, timezone
from pathlib import Path

MIND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(MIND_DIR, "raw")
WIKI_DIR = os.path.join(MIND_DIR, "wiki")
ARCHIVE_DIR = os.path.join(WIKI_DIR, "_archived")
STATE_FILE = os.path.join(MIND_DIR, ".curate-state.json")
PROGRESS_FILE = os.path.join(MIND_DIR, ".curate-progress.json")

# Load config
def load_config():
    import yaml
    with open(os.path.join(MIND_DIR, "config.yaml")) as f:
        return yaml.safe_load(f)

CONFIG = None
def get_config():
    global CONFIG
    if CONFIG is None:
        CONFIG = load_config()
    return CONFIG


def ts():
    return datetime.now(timezone.utc).isoformat()


def write_progress(step, total, status="running"):
    with open(PROGRESS_FILE, "w") as f:
        json.dump({"completed": step, "total": total, "status": status, "updated_at": ts()}, f)


# ── LLM API ──

def call_llm(system_prompt, user_prompt, max_tokens=None):
    """Call Sonnet 4.6 via API proxy."""
    cfg = get_config()
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        print(f"[curator] ERROR: {cfg['api_key_env']} not set")
        return None

    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens or cfg.get("max_tokens", 4096),
        "temperature": cfg.get("temperature", 0.3),
    }

    try:
        # Bypass local proxy if configured
        session = requests.Session()
        if cfg.get("no_proxy"):
            session.trust_env = False

        resp = session.post(
            cfg["api_endpoint"],
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if not content or not content.strip():
            model_returned = data.get("model", "?")
            tokens = data.get("usage", {}).get("total_tokens", 0)
            print(f"[curator] WARNING: API returned empty content (model={model_returned}, tokens={tokens}). API may be down.")
            return None
        return content
    except Exception as e:
        print(f"[curator] API error: {type(e).__name__}: {e}")
        import traceback; traceback.print_exc()
        return None


# ── State Management ──

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_curated_at": "", "cycle_count": 0}


def save_state(state):
    state["last_curated_at"] = ts()
    state["cycle_count"] = state.get("cycle_count", 0) + 1
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Frontmatter ──

def parse_frontmatter(content):
    """Parse YAML frontmatter from markdown."""
    m = re.match(r'^---\n(.*?)\n---\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    import yaml
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        meta = {}
    return meta, m.group(2)


def render_frontmatter(meta, body):
    """Render frontmatter + body."""
    import yaml
    fm = yaml.dump(meta, default_flow_style=False, allow_unicode=True).strip()
    return f"---\n{fm}\n---\n{body}"


def read_wiki_page(name):
    """Read a wiki page, return (meta, body) or (None, None)."""
    path = os.path.join(WIKI_DIR, name if name.endswith(".md") else f"{name}.md")
    if not os.path.exists(path):
        return None, None
    with open(path) as f:
        return parse_frontmatter(f.read())


def clean_page_name(name):
    """Sanitize page name for Obsidian compatibility."""
    # "Pipeline Status / L0 Knowledge Base" → "Pipeline-Status/L0-Knowledge-Base"
    name = name.replace(" / ", "/").replace(" - ", "-")
    parts = name.split("/")
    return "/".join(p.strip().replace(" ", "-") for p in parts)


def write_wiki_page(name, meta, body):
    """Write a wiki page with frontmatter."""
    name = clean_page_name(name)
    path = os.path.join(WIKI_DIR, name if name.endswith(".md") else f"{name}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    meta["last_updated"] = ts()
    with open(path, "w") as f:
        f.write(render_frontmatter(meta, body))


def list_wiki_pages():
    """List all wiki .md files with their frontmatter."""
    pages = []
    for md in glob.glob(os.path.join(WIKI_DIR, "**/*.md"), recursive=True):
        if "/_archived/" in md:
            continue
        rel = os.path.relpath(md, WIKI_DIR)
        with open(md) as f:
            meta, body = parse_frontmatter(f.read())
        pages.append({"path": rel, "meta": meta, "body_preview": body[:200]})
    return pages


# ── Step 1: INGEST ──

def step_ingest(since=""):
    """Read all raw data since last curation."""
    print("[curator] Step 1: INGEST")
    data = {"conversations": [], "reports": [], "dispatches": [], "results": [],
            "decisions": [], "git_log": [], "books": [], "status": [], "pipeline": []}

    for jsonl_file in glob.glob(os.path.join(RAW_DIR, "*.jsonl")):
        fname = os.path.basename(jsonl_file)
        key = fname.replace(".jsonl", "").replace("cehub_", "")
        if key not in data:
            data[key] = []
        with open(jsonl_file) as f:
            for line in f:
                try:
                    entry = json.loads(line.strip())
                    ingested = entry.get("_ingested_at", entry.get("_archived_at", ""))
                    if not since or ingested > since:
                        data[key].append(entry)
                except json.JSONDecodeError:
                    pass

    # Also read report .md files
    for md in glob.glob(os.path.join(RAW_DIR, "reports", "*.md")):
        fname = os.path.basename(md)
        mtime = os.path.getmtime(md)
        mtime_iso = datetime.fromtimestamp(mtime, timezone.utc).isoformat()
        if not since or mtime_iso > since:
            with open(md) as f:
                content = f.read()
            data["reports"].append({"filename": fname, "content": content[:5000], "_ingested_at": mtime_iso})

    total = sum(len(v) for v in data.values())
    print(f"  Ingested: {total} items ({', '.join(f'{k}:{len(v)}' for k, v in data.items() if v)})")
    return data


# ── Step 2: EXTRACT ──

def step_extract(raw_data):
    """Extract meaningful insights from raw data — processes docs in batches."""
    print("[curator] Step 2: EXTRACT")

    all_insights = []

    # Priority docs to process individually (full content)
    priority_docs = []
    for r in raw_data.get("reports", []):
        fname = r.get("filename", "")
        content = r.get("content", "")
        if not content or len(content) < 50:
            continue
        # CLAUDE.md and STATUS.md get full treatment
        if fname in ("CLAUDE.md", "STATUS.md"):
            priority_docs.insert(0, r)
        # Research and design docs
        elif any(k in fname.lower() for k in ("research", "architecture", "design", "schema", "routing", "handover", "onboard")):
            priority_docs.append(r)
        # Daily reports (batch later)
        elif "daily" in fname:
            continue  # handled in batch below
        else:
            priority_docs.append(r)

    # Batch 1: CLAUDE.md — split into 3 sub-batches (architecture, agents, decisions)
    claude_docs = [d for d in priority_docs if d.get("filename") == "CLAUDE.md"]
    if claude_docs:
        content = claude_docs[0]['content']
        # 1a: Architecture (layers)
        print("  [batch 1a] CLAUDE.md → layers...")
        insights = _extract_from_text(
            f"## CLAUDE.md — Architecture Section\n{content[:4000]}",
            "提取七层架构定义：L0, L1, L2a, L2b, L2c, FT, L3, L6。每层的名称、定位、当前状态。17个科学域列表。target_page用layers/L0.md格式。"
        )
        all_insights.extend(insights)

        # 1b: Agents
        print("  [batch 1b] CLAUDE.md → agents...")
        insights = _extract_from_text(
            f"## CLAUDE.md — Agent Section\n{content[3000:6000]}",
            "提取每个agent的角色定义和职责：cc-lead, coder, researcher, architect, pipeline-runner, pipeline-supervisor, code-reviewer, ops。target_page用agents/cc-lead.md格式。"
        )
        all_insights.extend(insights)

        # 1c: Decisions + Pipeline + Infrastructure
        print("  [batch 1c] CLAUDE.md → decisions + infra...")
        insights = _extract_from_text(
            f"## CLAUDE.md — Decisions & Infrastructure\n{content[5000:10000]}",
            "提取所有编号决策(#22-#42)、pipeline流程(Stage1-5工具链)、基础设施服务(端口、API)。target_page用decisions/D22.md、pipeline/stage4.md、infrastructure/services.md格式。"
        )
        all_insights.extend(insights)

    # Batch 2: STATUS.md — split into 2 sub-batches
    status_docs = [d for d in priority_docs if d.get("filename") == "STATUS.md"]
    if status_docs:
        content = status_docs[0]['content']
        print("  [batch 2a] STATUS.md → current state...")
        insights = _extract_from_text(
            f"## STATUS.md — Current State\n{content[:5000]}",
            "提取当前项目状态：每层的完成度百分比、数据量、阻塞项。target_page用layers/L0.md、STATUS.md格式。"
        )
        all_insights.extend(insights)

        print("  [batch 2b] STATUS.md → books + pipeline...")
        insights = _extract_from_text(
            f"## STATUS.md — Books & Pipeline\n{content[4000:9000]}",
            "提取每本书的pipeline进度、Stage4完成明细、待处理书籍队列。target_page用books/ofc.md、pipeline/stage4.md格式。"
        )
        all_insights.extend(insights)

    # Batch 3: Research & design docs — extract key findings
    research_docs = [d for d in priority_docs if d.get("filename") not in ("CLAUDE.md", "STATUS.md")]
    if research_docs:
        print(f"  [batch 3/4] {len(research_docs)} research/design docs...")
        # Process one at a time for better quality
        for i, doc in enumerate(research_docs[:15]):  # cap at 15 docs
            batch = [doc]
            text = f"## {doc['filename']}\n{doc['content'][:4000]}"
            insights = _extract_from_text(text,
                "从这些研究/设计文档中提取关键发现、技术决策、架构方案和数据源信息。"
            )
            all_insights.extend(insights)

    # Batch 4: Operational data (dispatches, results, git, conversations)
    ops_sections = []
    if raw_data.get("dispatches"):
        ops_sections.append("## Dispatches\n" + "\n".join(
            f"- {d.get('from','?')} → {d.get('to','?')}: {d.get('task','')[:100]}"
            for d in raw_data["dispatches"][-20:]
        ))
    if raw_data.get("results"):
        ops_sections.append("## Results\n" + "\n".join(
            f"- {r.get('from','?')}: {r.get('summary','')[:100]} [{r.get('status','?')}]"
            for r in raw_data["results"][-20:]
        ))
    if raw_data.get("conversations"):
        ops_sections.append("## Conversations\n" + "\n".join(
            f"- [{c.get('agent','?')}]: {c.get('content','')[:300]}"
            for c in raw_data["conversations"][-10:]
        ))
    if raw_data.get("git_log"):
        ops_sections.append("## Git Log\n" + "\n".join(
            f"- {g.get('date','')[:10]} {g.get('subject','')}"
            for g in raw_data["git_log"][:30]
        ))
    if ops_sections:
        print("  [batch 4/4] Operational data (dispatches, results, git, conversations)...")
        insights = _extract_from_text(
            "\n\n".join(ops_sections),
            "从运营数据中提取有价值的信息：任务完成情况、agent间协作模式、关键git变更。"
        )
        all_insights.extend(insights)

    # Deduplicate by insight text similarity (simple)
    seen = set()
    unique = []
    for ins in all_insights:
        key = ins.get("insight", "")[:80]
        if key not in seen:
            seen.add(key)
            unique.append(ins)

    print(f"  Total extracted: {len(unique)} unique insights (from {len(all_insights)} raw)")
    return unique


def _extract_from_text(text, focus_instruction):
    """Call LLM to extract insights from a text chunk."""
    prompt = f"""Analyze the following project data and extract ALL meaningful knowledge points.

{focus_instruction}

For each insight, output a JSON object on its own line:
- "insight": the knowledge point (concise but complete — include specific numbers, names, paths)
- "category": one of [layer, agent, book, pipeline, decision, infrastructure, research, concept, status]
- "target_page": the wiki page this belongs to (MUST match structure: layers/L0.md, agents/coder.md, books/ofc.md, pipeline/stage4.md, decisions/D22.md, infrastructure/services.md, research/flavordb2.md, concepts/xxx.md, STATUS.md)
- "related_pages": other wiki pages this relates to via [[backlinks]]
- "importance": 1-10

Be THOROUGH. Extract every fact worth remembering. Include:
- Layer definitions (L0, L1, L2a, L2b, L2c, FT, L3, L6) with their exact purpose and status
- Agent roles and responsibilities
- Numbered decisions (#22, #23, etc.)
- Pipeline stages and their tools
- File paths, ports, API endpoints
- Data quantities (number of books, entries, recipes)
- Architectural principles and constraints

Raw data:
{text[:4000]}

Output ONLY valid JSON lines, one per line. No markdown, no explanation, no code blocks. Maximum 20 insights per call."""

    result = call_llm(
        "你是 culinary-engine 项目的知识策展人。全面、详尽地提取所有有价值的知识点。每个层级、每个agent、每个决策都要单独提取。只输出 JSON。",
        prompt,
        max_tokens=4096,
    )

    if not result:
        return []

    insights = []
    for line in result.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ins = json.loads(line)
            if "insight" in ins:
                insights.append(ins)
        except json.JSONDecodeError:
            pass

    return insights


# ── Step 3: DETECT contradictions ──

def step_detect(insights, wiki_pages):
    """Check each insight against existing wiki for contradictions."""
    print("[curator] Step 3: DETECT")

    if not insights or not wiki_pages:
        return insights  # nothing to check against

    # Build wiki context summary
    wiki_summary = "\n".join(
        f"- {p['path']}: {p['body_preview']}" for p in wiki_pages[:30]
    )

    insights_text = "\n".join(
        f"{i+1}. [{ins.get('category','')}] {ins.get('insight','')}"
        for i, ins in enumerate(insights)
    )

    prompt = f"""Compare these new insights against the existing wiki and identify contradictions.

## Existing Wiki Pages
{wiki_summary[:4000]}

## New Insights
{insights_text}

For EACH insight, output a JSON line:
{{"index": N, "contradiction": true/false, "conflicts_with": "page name or null", "explanation": "why it contradicts or null"}}

Only flag TRUE contradictions — where the new insight directly opposes an existing fact. Different perspectives on the same topic are NOT contradictions."""

    result = call_llm(
        "你是知识矛盾检测器。比较新洞察和现有 wiki 内容，找出真正的事实矛盾。",
        prompt,
        max_tokens=2000,
    )

    if not result:
        return insights

    conflict_count = 0
    for line in result.strip().split("\n"):
        try:
            check = json.loads(line.strip())
            idx = check.get("index", 0) - 1
            if 0 <= idx < len(insights):
                insights[idx]["contradiction"] = check.get("contradiction", False)
                insights[idx]["conflicts_with"] = check.get("conflicts_with")
                insights[idx]["conflict_explanation"] = check.get("explanation")
                if check.get("contradiction"):
                    conflict_count += 1
        except (json.JSONDecodeError, IndexError):
            pass

    print(f"  Contradictions found: {conflict_count}")
    return insights


# ── Step 4: DECIDE ──

def step_decide(insights, wiki_pages):
    """Decide action for each insight: SKIP/KEEP_SEPARATE/MERGE/REPLACE/UPDATE."""
    print("[curator] Step 4: DECIDE")

    if not insights:
        return insights

    wiki_page_names = [p["path"] for p in wiki_pages]

    insights_text = "\n".join(
        f"{i+1}. [{ins.get('category','')}] {ins.get('insight','')} "
        f"(importance:{ins.get('importance',5)}, contradiction:{ins.get('contradiction',False)})"
        for i, ins in enumerate(insights)
    )

    prompt = f"""For each insight, decide what action to take:

- SKIP: already known, not worth recording
- KEEP_SEPARATE: new perspective, add to existing page or create new page
- MERGE: combine with existing content on same topic
- REPLACE: new fact supersedes old fact (only if contradiction=true)
- UPDATE: enrich existing page with more detail

## Existing Wiki Pages
{', '.join(wiki_page_names)}

## Insights
{insights_text}

For EACH insight, output a JSON line:
{{"index": N, "action": "MERGE|REPLACE|KEEP_SEPARATE|UPDATE|SKIP", "target_page": "path", "reason": "brief"}}

MANDATORY wiki structure — target_page MUST be one of these paths:
  layers/L0.md, layers/L1.md, layers/L2a.md, layers/L2b.md, layers/L2c.md, layers/FT.md, layers/L3.md, layers/L6.md
  agents/{{agent-name}}.md (cc-lead, coder, researcher, architect, pipeline-runner, pipeline-supervisor, code-reviewer, ops)
  books/{{book-id}}.md (e.g. books/ofc.md, books/mc-vol1.md)
  pipeline/{{stage}}.md (pipeline/stage1.md, pipeline/stage4.md, pipeline/stage5.md, pipeline/ocr.md)
  decisions/D{{number}}.md (e.g. decisions/D22.md, decisions/D37.md)
  infrastructure/services.md, infrastructure/api-routing.md, infrastructure/ce-hub.md
  research/{{topic}}.md (e.g. research/flavordb2.md, research/ocr-comparison.md)
  concepts/{{topic}}.md (only for cross-cutting concepts that don't fit above)
  STATUS.md (overall project status)
  CONTRADICTIONS.md (only for contradiction records)

One concept per page. Do NOT create catch-all pages like "concepts/resource.md" with 200 items."""

    result = call_llm(
        "你是知识管理决策者。为每条洞察选择最合适的处理方式。",
        prompt,
        max_tokens=2000,
    )

    if not result:
        # Default: KEEP_SEPARATE for all
        for ins in insights:
            ins["action"] = "KEEP_SEPARATE"
            ins["target_page"] = f"concepts/{ins.get('category', 'misc')}.md"
        return insights

    for line in result.strip().split("\n"):
        try:
            decision = json.loads(line.strip())
            idx = decision.get("index", 0) - 1
            if 0 <= idx < len(insights):
                insights[idx]["action"] = decision.get("action", "KEEP_SEPARATE")
                insights[idx]["target_page"] = decision.get("target_page", "")
                insights[idx]["decision_reason"] = decision.get("reason", "")
        except (json.JSONDecodeError, IndexError):
            pass

    actions = {}
    for ins in insights:
        a = ins.get("action", "SKIP")
        actions[a] = actions.get(a, 0) + 1
    print(f"  Decisions: {actions}")
    return insights


# ── Step 5: WRITE ──

def step_write(insights, dry_run=False):
    """Execute decisions — update wiki pages."""
    print("[curator] Step 5: WRITE")

    if dry_run:
        for ins in insights:
            action = ins.get("action", "SKIP")
            if action != "SKIP":
                print(f"  [DRY] {action} → {ins.get('target_page','?')}: {ins.get('insight','')[:60]}")
        return

    # Group insights by target page
    by_page = {}
    for ins in insights:
        action = ins.get("action", "SKIP")
        if action == "SKIP":
            continue
        target = ins.get("target_page", "")
        if not target:
            continue
        by_page.setdefault(target, []).append(ins)

    # Process each target page
    for page_name, page_insights in by_page.items():
        meta, body = read_wiki_page(page_name)

        if meta is None:
            # New page
            meta = {
                "title": page_name.replace(".md", "").replace("/", " — "),
                "status": "active",
                "mention_count": 1.0,
                "sources": [],
                "related": [],
            }
            body = f"\n# {meta['title']}\n\n"

        # Apply insights
        additions = []
        for ins in page_insights:
            action = ins["action"]
            text = ins["insight"]

            if action == "REPLACE":
                # Prepend replacement notice
                body = f"\n> **Updated {ts()[:10]}**: {text}\n\n" + body
                # Record in CONTRADICTIONS.md
                _record_contradiction(ins)
            elif action == "MERGE":
                additions.append(f"- {text}")
            elif action in ("KEEP_SEPARATE", "UPDATE"):
                additions.append(f"- {text}")

            # Update metadata
            meta["mention_count"] = meta.get("mention_count", 0) + 1.0

            # Track sources
            sources = meta.get("sources", [])
            if len(sources) < 20:
                sources.append(f"curate-cycle-{ts()[:10]}")
            meta["sources"] = sources

            # Track related pages via [[backlinks]]
            related = meta.get("related", [])
            for rp in ins.get("related_pages", []):
                link = f"[[{rp}]]"
                if link not in related:
                    related.append(link)
            meta["related"] = related[:20]

        if additions:
            body += f"\n## Updates ({ts()[:10]})\n" + "\n".join(additions) + "\n"

        write_wiki_page(page_name, meta, body)
        print(f"  Wrote: {page_name} ({len(page_insights)} insights)")

    # Update CHANGELOG.md
    _update_changelog(insights)


def _record_contradiction(insight):
    """Append to CONTRADICTIONS.md."""
    path = os.path.join(WIKI_DIR, "CONTRADICTIONS.md")
    entry = (
        f"\n## {ts()[:10]} — {insight.get('category', '?')}\n"
        f"- **New**: {insight.get('insight', '')}\n"
        f"- **Conflicts with**: {insight.get('conflicts_with', '?')}\n"
        f"- **Explanation**: {insight.get('conflict_explanation', '?')}\n"
        f"- **Action**: REPLACE\n"
    )
    with open(path, "a") as f:
        f.write(entry)


def _update_changelog(insights):
    """Prepend today's changes to CHANGELOG.md."""
    actions = [ins for ins in insights if ins.get("action", "SKIP") != "SKIP"]
    if not actions:
        return

    path = os.path.join(WIKI_DIR, "CHANGELOG.md")
    existing = ""
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()

    entry = f"## {ts()[:10]}\n"
    for ins in actions[:15]:
        entry += f"- [{ins.get('action','?')}] {ins.get('insight','')[:80]}\n"
    if len(actions) > 15:
        entry += f"- ...+{len(actions) - 15} more\n"
    entry += "\n"

    with open(path, "w") as f:
        f.write(entry + existing)


# ── Step 6: DECAY ──

def step_decay(dry_run=False):
    """Age out stale knowledge. The dreaming mechanism."""
    print("[curator] Step 6: DECAY (dreaming)")

    cfg = get_config()
    decay_cfg = cfg.get("decay", {})
    decrement = decay_cfg.get("decrement", 0.1)
    stale_threshold = decay_cfg.get("stale_threshold", 1.0)
    archive_threshold = decay_cfg.get("archive_threshold", 0.3)

    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    stale_count = 0
    archive_count = 0

    for md in glob.glob(os.path.join(WIKI_DIR, "**/*.md"), recursive=True):
        if "/_archived/" in md:
            continue
        rel = os.path.relpath(md, WIKI_DIR)

        # Skip core pages from archival
        if rel in ("CHANGELOG.md", "CONTRADICTIONS.md"):
            continue

        with open(md) as f:
            meta, body = parse_frontmatter(f.read())

        if not meta:
            continue

        mention_count = meta.get("mention_count", 5.0)  # default 5 for existing pages without tracking

        # Decrement if not updated this cycle
        last_updated = str(meta.get("last_updated", ""))
        today = ts()[:10]
        if not last_updated or last_updated[:10] != today:
            mention_count -= decrement

        meta["mention_count"] = round(mention_count, 2)

        # Determine status
        if mention_count < archive_threshold:
            meta["status"] = "archived"
            if not dry_run:
                # Move to _archived/
                archive_path = os.path.join(ARCHIVE_DIR, rel)
                os.makedirs(os.path.dirname(archive_path), exist_ok=True)
                write_wiki_page(os.path.join("_archived", rel), meta, body)
                os.remove(md)
                print(f"  Archived: {rel} (mentions: {mention_count})")
            else:
                print(f"  [DRY] Would archive: {rel} (mentions: {mention_count})")
            archive_count += 1
        elif mention_count < stale_threshold:
            meta["status"] = "stale"
            if not dry_run:
                write_wiki_page(rel, meta, body)
            stale_count += 1
        else:
            meta["status"] = "active"
            if not dry_run:
                write_wiki_page(rel, meta, body)

    print(f"  Decay: {stale_count} stale, {archive_count} archived")


# ── Step 7: LINT ──

def step_lint():
    """Health check: broken links, orphans, missing data."""
    print("[curator] Step 7: LINT")

    pages = list_wiki_pages()
    page_names = {p["path"] for p in pages}
    issues = []

    for page in pages:
        body = page.get("body_preview", "")
        # Check for [[backlinks]] pointing to non-existent pages
        links = re.findall(r'\[\[(.+?)\]\]', body)
        for link in links:
            link_path = f"{link}.md" if not link.endswith(".md") else link
            if link_path not in page_names and link not in page_names:
                issues.append(f"  Broken link: {page['path']} → [[{link}]]")

    # Check for orphan pages (no other page references them)
    all_bodies = " ".join(p.get("body_preview", "") for p in pages)
    for page in pages:
        name = page["path"].replace(".md", "")
        if f"[[{name}]]" not in all_bodies and f"[[{page['path']}]]" not in all_bodies:
            status = page.get("meta", {}).get("status", "active")
            if status == "active":
                issues.append(f"  Orphan page: {page['path']} (not referenced by any other page)")

    if issues:
        print(f"  Found {len(issues)} issues:")
        for issue in issues[:20]:
            print(issue)
    else:
        print("  No issues found")

    return issues


# ── Main ──

def main():
    full = "--full" in sys.argv
    lint_only = "--lint-only" in sys.argv
    dry_run = "--dry-run" in sys.argv

    print(f"[curator] Culinary Mind v1 — {'Full' if full else 'Incremental'} Curation")
    print(f"[curator] Model: {get_config()['model']}")
    print(f"[curator] Wiki: {WIKI_DIR}")

    if lint_only:
        step_lint()
        return

    state = load_state()
    since = "" if full else state.get("last_curated_at", "")
    if since:
        print(f"[curator] Since: {since}")

    # Ensure dirs
    for d in [WIKI_DIR, ARCHIVE_DIR, os.path.join(WIKI_DIR, "agents"),
              os.path.join(WIKI_DIR, "books"), os.path.join(WIKI_DIR, "concepts")]:
        os.makedirs(d, exist_ok=True)

    write_progress(0, 7)

    # Step 1: INGEST
    raw_data = step_ingest(since)
    write_progress(1, 7)

    # Step 2: EXTRACT
    insights = step_extract(raw_data)
    write_progress(2, 7)

    if not insights:
        print("[curator] No insights extracted. Done.")
        write_progress(7, 7, "completed")
        save_state(state)
        return

    # Step 3: DETECT contradictions
    wiki_pages = list_wiki_pages()
    insights = step_detect(insights, wiki_pages)
    write_progress(3, 7)

    # Step 4: DECIDE actions
    insights = step_decide(insights, wiki_pages)
    write_progress(4, 7)

    # Step 5: WRITE
    step_write(insights, dry_run)
    write_progress(5, 7)

    # Step 6: DECAY
    step_decay(dry_run)
    write_progress(6, 7)

    # Step 7: LINT
    step_lint()
    write_progress(7, 7, "completed")

    save_state(state)

    # Summary
    action_counts = {}
    for ins in insights:
        a = ins.get("action", "SKIP")
        action_counts[a] = action_counts.get(a, 0) + 1
    print(f"\n[curator] Done! Actions: {action_counts}")
    print(f"[curator] Wiki pages: {len(list_wiki_pages())}")


if __name__ == "__main__":
    main()
