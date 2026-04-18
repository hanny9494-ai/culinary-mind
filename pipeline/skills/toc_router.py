#!/usr/bin/env python3
"""
pipeline/skills/toc_router.py
TOC-first intelligent signal routing — "没嫌疑的直接判，有嫌疑的才细看"

4-step pipeline for a single book:
  Step 1: TOC analysis  — DashScope qwen3.6-plus, ~$0.01/book
           Sample first 5 pages + every N pages + last 3 pages, ask LLM to map
           chapter structure to skills (certain / suspect / skip).
  Step 2: Route certain/skip directly (no LLM, pure logic)
           · certain → generate signals.json entries at confidence=0.85
           · skip    → generate skip entries with skip_reason="toc_skip"
           · suspect → collect page range for Step 3
  Step 3: Page scan for suspect pages (DashScope sync, chapter context injected)
           Uses signal_router.py SYSTEM_PROMPT + parse/normalize helpers.
           routing_source="page_scan"
  Step 4: Merge all signals, sort by page, write signals.json

Output files:
  output/{book_id}/toc_analysis.json  — TOC analysis result
  output/{book_id}/signals.json       — final merged signals (run_skill compatible)

Usage:
    python toc_router.py --book-id ice_cream_flavor
    python toc_router.py --book-id ice_cream_flavor --toc-only
    python toc_router.py --book-id ice_cream_flavor --dry-run
    python toc_router.py --batch --books-yaml config/books.yaml
    python toc_router.py --book-id ice_cream_flavor --force
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# ── Proxy bypass (must be before any network import) ─────────────────────────
for _k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "SOCKS_PROXY", "socks_proxy"]:
    os.environ.pop(_k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,dashscope.aliyuncs.com")

import httpx
import yaml  # type: ignore

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = REPO_ROOT / "output"
sys.path.insert(0, str(Path(__file__).parent))

# ── Constants ─────────────────────────────────────────────────────────────────

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
TOC_MODEL = "qwen3.6-plus"
PAGE_SCAN_MODEL = "qwen3.6-plus"
TOC_MAX_TOKENS = 4096
SCAN_MAX_TOKENS = 512
SCAN_TIMEOUT_SEC = 60.0
TOC_TIMEOUT_SEC = 120.0

# ── TOC Analysis System Prompt ────────────────────────────────────────────────

TOC_SYSTEM_PROMPT = """你是烹饪/食品科学书籍结构分析专家。给你一本书的采样页面（包括前20页密集采样和中间的间隔采样），判断每个章节的内容类型和页面范围。

【关键指令：优先使用目录页】
如果采样页中包含目录/Contents/Table of Contents/CONTENTS 页面，必须优先使用目录信息来确定章节边界：
- 从目录中提取每个章节的名称和起始页码
- 相邻章节的 page_end = 下一章节的 page_start - 1
- 最后一个内容章节的 page_end = 总页数减去索引/附录页数

4 种 Skill 定义：

- A (定量科学参数 → L0 ParameterSet):
  提取可绑定到物理/化学方程的定量参数——物质固有属性、动力学常数、经验方程系数。

  Scale-up Test（核心判断）：放大食材体积/改变温度/改变时间，这个数字还能用于预测新结果吗？
    能 → A（物质属性/动力学常数/经验系数）
    不能 → 不是 A

  A 的 3 类数字：
    ① 动力学常数/相变阈值：活化能(Ea)、变性温度、凝胶化温度、Tg、D-value、z-value
    ② 热物性/传递参数：热导率(k)、比热容(Cp)、密度(ρ)、扩散系数(D)
    ③ 经验方程系数：Nusselt/Sherwood 关联式常数、流变模型参数

  ✅ A 正例：
    "蛋白质 62°C 开始变性，70°C 完全凝固" — 相变阈值
    "明胶 Ea=125 kJ/mol" — 动力学常数
    "表3.2: 各部位胶原蛋白含量(%)" — 系统性科学数据表
    "肌肉收缩系数 β=0.05 K⁻¹" — 经验方程参数

  ❌ A 反例：
    "160°C 炸 3 分钟" — 食谱操作参数（→ B）
    "糖度 68%、脂肪含量 12%" — 配方配比（→ B）
    "炖煮保持 85°C 可避免蛋白收缩" — 科学服务操作（→ B）
    "牛肉 60°C 水浴 1h 汁液流失 15%" — 实验终点数据
    "微波 800W 2min 土豆中心 85°C" — 设备依赖，无普适性

  ⚠️ 章节级 A 判断硬规则：
    - 章节的主要目的是给食谱/配方 → 不标 A（即使配方里有精确数字）
    - 只有主要目的是呈现科学理论/数据/参数的章节才可能含 A
    - 食谱章节里的温度、时间、配比、百分比都是 B，不是 A

- B (食谱/操作指令 → L2b):
  包含烹饪操作指令——配料表、步骤序列、温度/时间操作参数。
  即使含科学解释，只要目的是"教你怎么做菜"→ B。科学注释不改变 B 的判定。
  操作判断：普通人能照着这个做饭吗？能 → B。
  注意：有食谱就一定有食材 → B 蕴含 C。

  ✅ B 正例：
    "炖牛肉：先煎至焦糖色，加水没过肉，小火炖 2.5 小时"
    "85°C 炖 2 小时（此温度下胶原蛋白缓慢水解）"——括号里的科学是操作注脚
    "vanilla gelato: cream 500ml, sugar 150g, egg yolks 6, vanilla bean 1"

- C (食材): 品种、产地、季节、部位、营养成分。不需要单独标，B 自动带 C。

- D (审美/术语): 感官描述、风味词、口感词、粤菜术语

【重要规则】
- 同一章节可以同时标 A+B — 但仅当章节确实有独立的科学数据部分（不是食谱里的操作数字）
- 纯食谱章节（全是配方）→ certain B+C，绝不标 A
- 纯科学/理论章节 → suspect A（需逐页细看是 A 还是 L0 实验现象）
- 科学+食谱混合章节 → suspect（逐页细看）
- 宁可标 suspect 不可标 certain A。不确定时标 suspect

每个章节标记 confidence 级别：
- certain: 非常确定内容类型（纯食谱集 → certain B+C；纯索引 → certain skip）
- suspect: 可能混合多种内容（科学章节中穿插食谱，或有数据表但也有操作步骤）
- skip: 前言、目录、索引、版权、致谢、纯图片 → 跳过

输出纯 JSON（不要任何解释）：
{
  "book_summary": "一句话",
  "toc_found": true,
  "toc_page": N,
  "chapters": [
    {
      "name": "章节名",
      "page_start": N,
      "page_end": N,
      "confidence": "certain|suspect|skip",
      "skills": ["A", "B"],
      "parameter_density": "extreme|high|medium|low|none",
      "value_assessment": "一句话评估"
    }
  ]
}
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY not set")
    return key


def _strip_thinking(text: str) -> str:
    """Remove <think>...</think> blocks from qwen3 responses."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _call_dashscope(
    system: str,
    user: str,
    model: str = TOC_MODEL,
    max_tokens: int = TOC_MAX_TOKENS,
    timeout_sec: float = TOC_TIMEOUT_SEC,
    retries: int = 3,
    log: logging.Logger | None = None,
) -> str | None:
    """Synchronous DashScope call. trust_env=False bypasses local SOCKS proxy."""
    lg = log or logging.getLogger("toc_router")
    key = _get_api_key()
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "enable_thinking": False,
    }
    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(trust_env=False, timeout=timeout_sec, follow_redirects=False) as client:
                resp = client.post(
                    DASHSCOPE_URL, headers=headers, json=body,
                )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            return _strip_thinking(raw)
        except Exception as e:
            lg.warning(f"DashScope attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
    return None


def _load_pages(book_id: str) -> list[dict]:
    path = OUTPUT_ROOT / book_id / "pages.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ── Step 1: TOC Analysis ──────────────────────────────────────────────────────

def _build_sample_pages(pages: list[dict]) -> list[dict]:
    """
    Two-phase sampling strategy:

    Phase 1 — Dense front sampling (find TOC/Contents page):
      All pages 0-19 (first 20 pages contain TOC in almost all books).

    Phase 2 — Stride sampling (validate chapter structure + detect skills):
      Every N pages from page 20 onward, N = max(10, (total-20) // 12),
      aiming for 10-15 sample points through the body.
      Plus last 3 pages (index/appendix boundary).

    This ensures the TOC page is always included in full, so the model can
    infer chapter boundaries from explicit page numbers in the table of contents.
    """
    total = len(pages)
    selected_indices: set[int] = set()

    # Phase 1: all front pages (first 20 or total, whichever smaller)
    front_end = min(20, total)
    for i in range(front_end):
        selected_indices.add(i)

    # Phase 2: stride through body
    body_len = total - front_end
    if body_len > 0:
        N = max(10, body_len // 12)
        for i in range(front_end, total, N):
            selected_indices.add(i)

    # Last 3 pages
    for i in range(max(0, total - 3), total):
        selected_indices.add(i)

    return [pages[i] for i in sorted(selected_indices)]


def analyze_toc(book_id: str, log: logging.Logger) -> dict | None:
    """
    Step 1: Call DashScope to analyze book structure.

    Returns parsed TOC analysis dict, or None on failure.
    Saves result to output/{book_id}/toc_analysis.json.
    """
    pages = _load_pages(book_id)
    if not pages:
        log.error(f"pages.json not found for {book_id}")
        return None

    total = len(pages)
    sample = _build_sample_pages(pages)
    log.info(f"TOC analysis: {total} total pages, {len(sample)} sample points")

    # Build prompt: include page number + first 500 chars
    parts = []
    for p in sample:
        pnum = p.get("page", "?")
        text = p.get("text", "").strip()[:500]
        if text:
            parts.append(f"[Page {pnum}]\n{text}")

    user_prompt = (
        f"Book ID: {book_id}\n"
        f"Total pages: {total}\n\n"
        "=== Sampled Pages ===\n\n"
        + "\n\n".join(parts)
    )

    t0 = time.time()
    raw = _call_dashscope(TOC_SYSTEM_PROMPT, user_prompt, log=log)
    elapsed = time.time() - t0

    if not raw:
        log.error("TOC analysis API call failed")
        return None

    # Parse JSON
    try:
        # Try direct parse first
        parsed = json.loads(raw)
    except Exception:
        # Try to extract JSON block
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                log.error(f"TOC JSON parse failed. Raw: {raw[:300]}")
                return None
        else:
            log.error(f"No JSON found in TOC response. Raw: {raw[:300]}")
            return None

    # Validate chapters
    chapters = parsed.get("chapters", [])
    if not isinstance(chapters, list):
        log.error("TOC response missing 'chapters' list")
        return None

    # Normalize: ensure B implies C
    for ch in chapters:
        skills = ch.get("skills", [])
        if "B" in skills and "C" not in skills:
            ch["skills"].append("C")
        ch["page_start"] = int(ch.get("page_start", 0))
        ch["page_end"] = int(ch.get("page_end", 0))
        if ch["page_end"] == 0:
            ch["page_end"] = total  # assume to end of book

    result = {
        "book_id": book_id,
        "total_pages": total,
        "sample_count": len(sample),
        "elapsed_sec": round(elapsed, 1),
        "model": TOC_MODEL,
        "_ts": _ts(),
        **parsed,
    }

    log.info(f"TOC: {len(chapters)} chapters identified in {elapsed:.1f}s")
    for ch in chapters:
        log.info(f"  [{ch['page_start']}-{ch['page_end']}] {ch['name']} "
                 f"→ {ch['confidence']} {ch.get('skills', [])}")

    return result


# ── Step 2: Route Decision (no LLM) ──────────────────────────────────────────

def _make_certain_signal(
    page_num: int,
    skills: list[str],
    chapter_name: str,
) -> dict:
    """Generate a signal entry for a 'certain' chapter page."""
    sigs = {
        "A": "A" in skills,
        "B": "B" in skills,
        "C": "C" in skills or "B" in skills,  # B implies C
        "D": "D" in skills,
    }
    hints: dict[str, Any] = {}
    if sigs["A"]:
        hints["A"] = {"mf_candidates": [], "has_table": False, "has_equation": False}
    if sigs["C"]:
        hints["C"] = {"ingredients_detected": []}
    if sigs["D"]:
        hints["D"] = {"aesthetic_terms": []}
    return {
        "page": page_num,
        "signals": sigs,
        "hints": hints,
        "confidence": 0.85,
        "skip_reason": None,
        "routing_source": "toc_certain",
        "chapter": chapter_name,
    }


def _make_skip_signal(page_num: int, chapter_name: str) -> dict:
    """Generate a skip signal entry for a 'skip' chapter page."""
    return {
        "page": page_num,
        "signals": {"A": False, "B": False, "C": False, "D": False},
        "hints": {},
        "confidence": 0.0,
        "skip_reason": "toc_skip",
        "routing_source": "toc_skip",
        "chapter": chapter_name,
    }


def route_certain_and_skip(
    toc: dict,
    pages_map: dict[int, str],
    log: logging.Logger,
) -> tuple[list[dict], list[dict], list[int]]:
    """
    Step 2: Route all pages by chapter confidence.

    Returns:
        (certain_signals, skip_signals, suspect_page_nums)
    """
    chapters = toc.get("chapters", [])
    certain_signals: list[dict] = []
    skip_signals: list[dict] = []
    suspect_pages: list[int] = []

    # Build chapter lookup: page_num → chapter info
    page_to_chapter: dict[int, dict] = {}
    for ch in chapters:
        ps = ch.get("page_start", 0)
        pe = ch.get("page_end", 0)
        for pn in range(ps, pe + 1):
            if pn in pages_map:
                page_to_chapter[pn] = ch

    # Pages not covered by any chapter → treat as suspect
    all_pages = set(pages_map.keys())
    covered = set(page_to_chapter.keys())
    uncovered = all_pages - covered

    for pn in sorted(uncovered):
        if pages_map.get(pn, "").strip():
            suspect_pages.append(pn)

    # Route covered pages
    for pn in sorted(covered):
        ch = page_to_chapter[pn]
        conf = ch.get("confidence", "suspect")
        name = ch.get("name", "unknown")
        skills = ch.get("skills", [])

        if conf == "certain":
            if pages_map.get(pn, "").strip():
                certain_signals.append(_make_certain_signal(pn, skills, name))
            else:
                skip_signals.append(_make_skip_signal(pn, name))
        elif conf == "skip":
            skip_signals.append(_make_skip_signal(pn, name))
        else:  # suspect or unknown
            if pages_map.get(pn, "").strip():
                suspect_pages.append(pn)
            else:
                skip_signals.append(_make_skip_signal(pn, "blank"))

    certain_count = len(certain_signals)
    skip_count = len(skip_signals)
    suspect_count = len(suspect_pages)
    log.info(f"Route: certain={certain_count} skip={skip_count} suspect={suspect_count}")
    return certain_signals, skip_signals, suspect_pages


# ── Step 3: Suspect Page Scan ─────────────────────────────────────────────────

def _get_chapter_context(page_num: int, toc: dict) -> tuple[str, str]:
    """Return (chapter_name, value_assessment) for a page, or empty strings."""
    for ch in toc.get("chapters", []):
        if ch.get("page_start", 0) <= page_num <= ch.get("page_end", 0):
            return ch.get("name", ""), ch.get("value_assessment", "")
    return "", ""


def scan_page_with_context(
    page_num: int,
    page_text: str,
    chapter_name: str,
    value_assessment: str,
    log: logging.Logger,
) -> dict:
    """
    Step 3: Call DashScope to route a single suspect page.
    Injects chapter context into the prompt.
    Uses signal_router SYSTEM_PROMPT + normalize helpers for compatibility.
    """
    from signal_router import SYSTEM_PROMPT as ROUTER_SYSTEM, parse_signal_json

    context_prefix = ""
    if chapter_name:
        context_prefix = (
            f"[章节上下文] 这一页来自章节「{chapter_name}」，"
            f"该章节主要内容：{value_assessment or '未知'}。\n\n"
        )

    user = (
        f"{context_prefix}"
        f"=== Page {page_num} ===\n"
        f"{page_text[:3000]}"
    )

    raw = _call_dashscope(
        system=ROUTER_SYSTEM,
        user=user,
        model=PAGE_SCAN_MODEL,
        max_tokens=SCAN_MAX_TOKENS,
        timeout_sec=SCAN_TIMEOUT_SEC,
        log=log,
    )

    if raw is None:
        # Fallback: all true (recall-first, consistent with signal_router)
        return {
            "page": page_num,
            "signals": {"A": True, "B": True, "C": True, "D": True},
            "hints": {},
            "confidence": 0.5,
            "skip_reason": "scan_api_error",
            "routing_source": "page_scan",
            "chapter": chapter_name,
        }

    parsed = parse_signal_json(raw, page_num, log)
    parsed["page"] = page_num
    parsed["routing_source"] = "page_scan"
    parsed["chapter"] = chapter_name
    return parsed


def scan_suspect_pages(
    suspect_pages: list[int],
    pages_map: dict[int, str],
    toc: dict,
    log: logging.Logger,
    checkpoint_every: int = 20,
    checkpoint_path: Path | None = None,
) -> list[dict]:
    """
    Step 3: Scan all suspect pages one by one with chapter context.
    Checkpoints progress to avoid losing work on failure.
    """
    if not suspect_pages:
        return []

    log.info(f"Scanning {len(suspect_pages)} suspect pages...")
    scan_signals: list[dict] = []
    t0 = time.time()

    for i, pn in enumerate(sorted(suspect_pages)):
        page_text = pages_map.get(pn, "")
        if not page_text.strip():
            scan_signals.append({
                "page": pn,
                "signals": {"A": False, "B": False, "C": False, "D": False},
                "hints": {},
                "confidence": 0.0,
                "skip_reason": "blank_page",
                "routing_source": "page_scan",
                "chapter": "",
            })
            continue

        ch_name, ch_assess = _get_chapter_context(pn, toc)
        sig = scan_page_with_context(pn, page_text, ch_name, ch_assess, log)
        scan_signals.append(sig)

        a_val = sig.get("signals", {}).get("A", False)
        log.info(f"  p{pn:04d}: A={a_val} B={sig['signals'].get('B',False)} "
                 f"C={sig['signals'].get('C',False)} D={sig['signals'].get('D',False)} "
                 f"src=page_scan ch={ch_name[:30]!r}")

        # Checkpoint
        if checkpoint_path and (i + 1) % checkpoint_every == 0:
            elapsed = time.time() - t0
            log.info(f"  Checkpoint: {i+1}/{len(suspect_pages)}, {elapsed:.0f}s")
            checkpoint_path.write_text(json.dumps(scan_signals, ensure_ascii=False, indent=2))

    return scan_signals


# ── Step 4: Merge & Write ─────────────────────────────────────────────────────

def merge_and_write(
    certain_signals: list[dict],
    skip_signals: list[dict],
    scan_signals: list[dict],
    out_path: Path,
    dry_run: bool = False,
    log: logging.Logger | None = None,
) -> list[dict]:
    """
    Step 4: Merge all signal sources, sort by page, write signals.json.

    Output format is fully compatible with run_skill.py's signals.json reader.
    """
    lg = log or logging.getLogger("toc_router")
    all_signals: dict[int, dict] = {}

    for sig in certain_signals + skip_signals + scan_signals:
        pn = sig["page"]
        all_signals[pn] = sig  # last write wins (page_scan overrides if same page)

    final = sorted(all_signals.values(), key=lambda s: s["page"])

    a_count = sum(1 for s in final if s.get("signals", {}).get("A"))
    b_count = sum(1 for s in final if s.get("signals", {}).get("B"))
    skip_count = sum(1 for s in final if s.get("skip_reason"))
    certain_count = sum(1 for s in final if s.get("routing_source") == "toc_certain")
    scan_count = sum(1 for s in final if s.get("routing_source") == "page_scan")

    lg.info(f"Merged: {len(final)} pages total | A={a_count} B={b_count} "
            f"skip={skip_count} | certain={certain_count} scan={scan_count}")

    if not dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(final, ensure_ascii=False, indent=2))
        lg.info(f"Written: {out_path}")

    return final


# ── Full Pipeline ─────────────────────────────────────────────────────────────

def run_book(
    book_id: str,
    *,
    toc_only: bool = False,
    dry_run: bool = False,
    force: bool = False,
    log: logging.Logger | None = None,
) -> dict:
    """
    Run full toc_router pipeline for one book.

    Returns summary dict with stats.
    """
    lg = log or logging.getLogger(f"toc_router.{book_id}")

    book_out = OUTPUT_ROOT / book_id
    signals_path = book_out / "signals.json"
    toc_path = book_out / "toc_analysis.json"
    checkpoint_path = book_out / "_toc_scan_checkpoint.json"

    # Check if signals.json already exists
    if signals_path.exists() and not force:
        lg.info(f"signals.json already exists for {book_id}, skipping (--force to override)")
        return {"book_id": book_id, "status": "skipped", "reason": "signals_exists"}

    pages = _load_pages(book_id)
    if not pages:
        return {"book_id": book_id, "status": "error", "reason": "no pages.json"}

    pages_map: dict[int, str] = {p["page"]: p.get("text", "") for p in pages}
    total_pages = len(pages)
    t_start = time.time()

    # ── Step 1: TOC Analysis ──
    toc: dict | None = None
    if toc_path.exists() and not force:
        lg.info(f"Loading existing toc_analysis.json for {book_id}")
        try:
            toc = json.loads(toc_path.read_text())
        except Exception:
            lg.warning("Failed to load existing toc_analysis.json, re-running")

    if toc is None:
        toc = analyze_toc(book_id, lg)
        if toc is None:
            lg.error("TOC analysis failed — falling back to full page scan")
            # Fallback: all pages are suspect
            toc = {
                "book_id": book_id,
                "total_pages": total_pages,
                "book_summary": "TOC analysis failed — full page scan",
                "chapters": [],
                "_fallback": True,
            }
        if not dry_run:
            toc_path.write_text(json.dumps(toc, ensure_ascii=False, indent=2))
            lg.info(f"Written: {toc_path}")

    if toc_only:
        return {
            "book_id": book_id,
            "status": "toc_only",
            "chapters": len(toc.get("chapters", [])),
            "toc_path": str(toc_path),
            "elapsed_sec": round(time.time() - t_start, 1),
        }

    # ── Step 2: Route certain/skip ──
    certain_signals, skip_signals, suspect_pages = route_certain_and_skip(toc, pages_map, lg)

    # ── Step 3: Scan suspect pages ──
    scan_signals = scan_suspect_pages(
        suspect_pages, pages_map, toc, lg,
        checkpoint_path=checkpoint_path if not dry_run else None,
    )

    # ── Step 4: Merge & Write ──
    final = merge_and_write(
        certain_signals, skip_signals, scan_signals,
        out_path=signals_path,
        dry_run=dry_run,
        log=lg,
    )

    # Clean up checkpoint
    if checkpoint_path.exists() and not dry_run:
        checkpoint_path.unlink(missing_ok=True)

    elapsed = time.time() - t_start
    a_count = sum(1 for s in final if s.get("signals", {}).get("A"))
    b_count = sum(1 for s in final if s.get("signals", {}).get("B"))
    skip_total = sum(1 for s in final if s.get("skip_reason"))
    certain_ct = sum(1 for s in final if s.get("routing_source") == "toc_certain")
    scan_ct = sum(1 for s in final if s.get("routing_source") == "page_scan")
    toc_skip_ct = sum(1 for s in final if s.get("routing_source") == "toc_skip")

    summary = {
        "book_id": book_id,
        "status": "done" if not dry_run else "dry_run",
        "total_pages": total_pages,
        "signals_total": len(final),
        "a_pages": a_count,
        "b_pages": b_count,
        "skip_pages": skip_total,
        "certain_pages": certain_ct,
        "scan_pages": scan_ct,
        "toc_skip_pages": toc_skip_ct,
        "elapsed_sec": round(elapsed, 1),
        "toc_chapters": len(toc.get("chapters", [])),
    }
    lg.info(f"Done: {book_id} in {elapsed:.1f}s — A={a_count} B={b_count} "
            f"certain={certain_ct} scan={scan_ct}")
    return summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="TOC-first intelligent signal routing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--book-id", help="Run for a single book")
    mode.add_argument("--batch", action="store_true",
                      help="Batch mode: run for all books in books.yaml whose signal_status != done")

    p.add_argument("--books-yaml", default=str(REPO_ROOT / "config" / "books.yaml"),
                   help="Path to books.yaml (for --batch)")
    p.add_argument("--toc-only", action="store_true",
                   help="Only run Step 1 (TOC analysis), don't route or scan")
    p.add_argument("--dry-run", action="store_true",
                   help="Analyze but don't write any output files")
    p.add_argument("--force", action="store_true",
                   help="Overwrite existing signals.json and toc_analysis.json")
    p.add_argument("--verbose", action="store_true",
                   help="Verbose logging")
    return p.parse_args()


def _setup_logging(verbose: bool, book_id: str | None = None) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return logging.getLogger(f"toc_router.{book_id or 'batch'}")


def main() -> None:
    args = parse_args()
    log = _setup_logging(args.verbose, getattr(args, "book_id", None))

    if args.batch:
        # Batch mode: process all books with signal_status != done
        yaml_path = Path(args.books_yaml)
        if not yaml_path.exists():
            print(f"ERROR: books.yaml not found: {yaml_path}", file=sys.stderr)
            sys.exit(1)
        with open(yaml_path) as f:
            books = yaml.safe_load(f)
        if not isinstance(books, list):
            print("ERROR: books.yaml must be a list", file=sys.stderr)
            sys.exit(1)

        targets = [b for b in books if b.get("signal_status") != "done"]
        log.info(f"Batch: {len(targets)}/{len(books)} books need signal routing")

        results = []
        for book in targets:
            bid = book.get("id", "?")
            log.info(f"\n{'='*60}\nBook: {bid}\n{'='*60}")
            try:
                summary = run_book(
                    bid,
                    toc_only=args.toc_only,
                    dry_run=args.dry_run,
                    force=args.force,
                    log=logging.getLogger(f"toc_router.{bid}"),
                )
            except Exception as e:
                log.error(f"Book {bid} failed: {e}")
                summary = {"book_id": bid, "status": "error", "reason": str(e)}
            results.append(summary)
            print(f"  {bid}: {summary.get('status')} "
                  f"A={summary.get('a_pages','?')} elapsed={summary.get('elapsed_sec','?')}s")

        # Summary table
        print(f"\n{'='*60}")
        print(f"Batch complete: {len(results)} books")
        done = sum(1 for r in results if r.get("status") == "done")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        errors = sum(1 for r in results if r.get("status") == "error")
        print(f"  done={done} skipped={skipped} errors={errors}")
        return

    # Single book mode
    if not args.book_id:
        print("ERROR: Provide --book-id or --batch", file=sys.stderr)
        sys.exit(1)

    book_id = args.book_id
    log = _setup_logging(args.verbose, book_id)

    try:
        summary = run_book(
            book_id,
            toc_only=args.toc_only,
            dry_run=args.dry_run,
            force=args.force,
            log=log,
        )
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n── TOC Router: {book_id} ──")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if summary.get("status") == "done":
        print(f"\n✅ signals.json written")
        print(f"  Total pages:    {summary.get('total_pages')}")
        print(f"  TOC chapters:   {summary.get('toc_chapters')}")
        print(f"  Certain pages:  {summary.get('certain_pages')} (no scan needed)")
        print(f"  Scanned pages:  {summary.get('scan_pages')} (suspect pages)")
        print(f"  Skipped pages:  {summary.get('toc_skip_pages')} (toc_skip)")
        print(f"  A-signal pages: {summary.get('a_pages')}")
        print(f"  B-signal pages: {summary.get('b_pages')}")
        print(f"  Time:           {summary.get('elapsed_sec')}s")
    elif summary.get("status") == "toc_only":
        print(f"\n✅ TOC analysis complete")
        print(f"  Chapters: {summary.get('chapters')}")
        print(f"  Saved to: {summary.get('toc_path')}")
    elif summary.get("status") == "skipped":
        print(f"\n⏭  Skipped: {summary.get('reason')} (use --force to overwrite)")


if __name__ == "__main__":
    main()
