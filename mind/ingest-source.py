#!/usr/bin/env python3
"""ingest-source.py — Ingest one source document into the wiki.

Reads the source, calls LLM to write complete wiki articles (not bullet points),
updates index.md and log.md.

Usage:
  ingest-source.py <source-file>              — ingest one file
  ingest-source.py <source-file> --dry-run    — show what pages would be created/updated
"""

import json
import os
import sys
import re
import glob
import time
import yaml
import requests
from datetime import datetime, timezone
from pathlib import Path

MIND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WIKI_DIR = os.path.join(MIND_DIR, "wiki")
CONFIG_PATH = os.path.join(MIND_DIR, "config.yaml")

WIKI_STRUCTURE = """
Wiki directory structure (target_page must use these paths):
  layers/L0.md, layers/L1.md, layers/L2a.md, layers/L2b.md, layers/L2c.md, layers/FT.md, layers/L3.md, layers/L6.md
  agents/{name}.md (cc-lead, coder, researcher, architect, pipeline-supervisor, code-reviewer, open-data-collector)
  books/{book-id}.md (e.g. books/ofc.md)
  pipeline/prep.md, pipeline/l0.md, pipeline/l2b.md, pipeline/l2a.md, pipeline/graph.md
  decisions/D{number}.md (e.g. decisions/D22.md)
  infrastructure/services.md, infrastructure/api-routing.md, infrastructure/ce-hub.md
  research/{topic}.md
  concepts/{topic}.md
  STATUS.md
"""


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def call_llm(system_prompt, user_prompt, cfg=None):
    if cfg is None:
        cfg = load_config()
    api_key = os.environ.get(cfg["api_key_env"], "")
    if not api_key:
        print(f"  ERROR: {cfg['api_key_env']} not set")
        return None

    session = requests.Session()
    if cfg.get("no_proxy"):
        session.trust_env = False

    try:
        resp = session.post(
            cfg["api_endpoint"],
            json={
                "model": cfg["model"],
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": cfg.get("max_tokens", 4096),
                "temperature": cfg.get("temperature", 0.3),
            },
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if not content or not content.strip():
            print(f"  WARNING: API returned empty response")
            return None
        return content
    except Exception as e:
        print(f"  API error: {e}")
        return None


def read_wiki_page(page_path):
    full = os.path.join(WIKI_DIR, page_path)
    if os.path.exists(full):
        with open(full) as f:
            return f.read()
    return None


def write_wiki_page(page_path, content):
    full = os.path.join(WIKI_DIR, page_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w") as f:
        f.write(content)


def read_index():
    idx_path = os.path.join(WIKI_DIR, "index.md")
    if os.path.exists(idx_path):
        with open(idx_path) as f:
            return f.read()
    return "# Wiki Index\n\n(empty)\n"


def append_log(entry):
    log_path = os.path.join(WIKI_DIR, "log.md")
    with open(log_path, "a") as f:
        f.write(f"\n## [{ts()}] ingest | {entry['source']}\n")
        f.write(f"Pages created: {', '.join(entry.get('created', []))}\n")
        f.write(f"Pages updated: {', '.join(entry.get('updated', []))}\n")
        if entry.get('notes'):
            f.write(f"Notes: {entry['notes']}\n")


def ingest_source(source_path, dry_run=False):
    """Main ingest function: read source → LLM writes wiki pages → update index + log."""

    fname = os.path.basename(source_path)
    print(f"[ingest] Source: {fname}")

    # Read source
    with open(source_path) as f:
        source_content = f.read()

    if len(source_content) < 50:
        print(f"  Skipping: too short ({len(source_content)} chars)")
        return

    cfg = load_config()
    index_content = read_index()

    # Step 1: Ask LLM what pages to create/update
    plan_prompt = f"""You are a wiki curator for a food science project called "culinary-mind".

Read this source document and decide which wiki pages to create or update.

{WIKI_STRUCTURE}

Current wiki index:
{index_content[:2000]}

Source document ({fname}):
{source_content[:6000]}

Output a JSON array of pages to write. For each page:
- "page": wiki path (e.g. "layers/L0.md")
- "action": "create" or "update"
- "title": page title
- "reason": why this page needs creating/updating based on the source

ONLY include pages that have substantial content in this source document.
Output ONLY valid JSON array. No other text."""

    plan_result = call_llm(
        "You are a strict wiki planner. Only output JSON.",
        plan_prompt, cfg
    )

    if not plan_result:
        print("  Failed to get plan from LLM")
        return

    # Parse plan
    try:
        # Strip markdown code blocks if present
        clean = plan_result.strip()
        if clean.startswith("```"):
            clean = re.sub(r'^```\w*\n?', '', clean)
            clean = re.sub(r'\n?```$', '', clean)
        pages_plan = json.loads(clean)
    except json.JSONDecodeError:
        print(f"  Failed to parse plan JSON: {plan_result[:200]}")
        return

    if not isinstance(pages_plan, list):
        print(f"  Plan is not a list: {type(pages_plan)}")
        return

    print(f"  Plan: {len(pages_plan)} pages")
    for p in pages_plan:
        print(f"    [{p.get('action','?')}] {p.get('page','?')} — {p.get('reason','')[:60]}")

    if dry_run:
        print("  DRY RUN — not writing")
        return

    # Step 2: For each page, ask LLM to write complete article
    created = []
    updated = []

    for page_info in pages_plan:
        page_path = page_info.get("page", "")
        action = page_info.get("action", "create")
        title = page_info.get("title", page_path)

        if not page_path or not page_path.endswith(".md"):
            continue

        existing = read_wiki_page(page_path)

        write_prompt = f"""Write a complete wiki article for: {title}

{WIKI_STRUCTURE}

This article goes in: {page_path}

Source document ({fname}):
{source_content[:5000]}

{"Existing article to UPDATE (keep good content, add new info):" if existing else "This is a NEW article."}
{existing[:2000] if existing else ""}

Write a COMPLETE article in markdown with:
1. YAML frontmatter: title, type, sources, related (as [[wikilinks]]), created, updated, confidence
2. Clear sections with ## headings
3. Specific facts, numbers, file paths from the source
4. [[wikilinks]] to related pages
5. 300-1500 words

Write in Chinese for domain content, English for technical terms.
Output ONLY the markdown article. No explanation."""

        article = call_llm(
            "You are a wiki writer. Write complete, factual articles based on source data. Never invent information.",
            write_prompt, cfg
        )

        if not article:
            print(f"    FAILED: {page_path}")
            continue

        # Clean markdown code block wrapper if present
        article = article.strip()
        if article.startswith("```"):
            article = re.sub(r'^```\w*\n?', '', article)
            article = re.sub(r'\n?```$', '', article)

        write_wiki_page(page_path, article)

        if action == "create":
            created.append(page_path)
        else:
            updated.append(page_path)

        print(f"    WROTE: {page_path} ({len(article)} chars)")

    # Step 3: Update index.md
    update_index(pages_plan, cfg, source_content, fname)

    # Step 4: Log
    append_log({"source": fname, "created": created, "updated": updated, "notes": f"{len(source_content)} chars"})

    print(f"  Done: {len(created)} created, {len(updated)} updated")


def update_index(pages_plan, cfg, source_content, fname):
    """Regenerate index.md based on current wiki files."""
    all_pages = []
    for md in sorted(glob.glob(os.path.join(WIKI_DIR, "**/*.md"), recursive=True)):
        rel = os.path.relpath(md, WIKI_DIR)
        if rel in ("index.md", "log.md") or "/_archived/" in rel or ".obsidian" in rel:
            continue
        all_pages.append(rel)

    index_prompt = f"""Generate a wiki index (index.md) for these pages:

{chr(10).join(f'- {p}' for p in all_pages)}

Format: organized by category with [[wikilinks]] and one-line summaries.
Categories: Layers, Agents, Books, Pipeline, Infrastructure, Decisions, Research, Concepts, Status

Output ONLY markdown. Start with "# Culinary Mind Wiki"."""

    index_content = call_llm("Generate a clean wiki index.", index_prompt, cfg)
    if index_content:
        index_content = index_content.strip()
        if index_content.startswith("```"):
            index_content = re.sub(r'^```\w*\n?', '', index_content)
            index_content = re.sub(r'\n?```$', '', index_content)
        write_wiki_page("index.md", index_content)
        print(f"    INDEX updated ({len(all_pages)} pages)")


def main():
    if len(sys.argv) < 2:
        print("Usage: ingest-source.py <source-file> [--dry-run]")
        sys.exit(1)

    source_path = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    if not os.path.exists(source_path):
        print(f"File not found: {source_path}")
        sys.exit(1)

    # Ensure wiki dirs
    for d in ["layers", "agents", "books", "pipeline", "infrastructure", "decisions", "research", "concepts", "_archived"]:
        os.makedirs(os.path.join(WIKI_DIR, d), exist_ok=True)

    ingest_source(source_path, dry_run)


if __name__ == "__main__":
    main()
