#!/usr/bin/env python3
"""
pipeline/skills/signal_router.py
9b Router — per-page markdown → A/B/C/D skill signals

Input:  output/{book_id}/pages.json
Output: output/{book_id}/signals.json

Model: qwen3.5:9b via Ollama (localhost:11434)
Strategy: recall-first —宁可多标不可漏标

Usage:
    python signal_router.py --book-id mc_vol3
    python signal_router.py --book-id mc_vol3 --pages 20 --start-page 25
    python signal_router.py --input-file /path/to/pages.json --out /path/to/signals.json
"""

import os, sys, json, time, logging, argparse
from pathlib import Path
from typing import Any

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY","all_proxy","ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_MODEL = "qwen3.5:9b"

# ── Prompt template (from 9b-signal-router-design-20260415.md) ────────────────

SYSTEM_PROMPT = """\
你是一个页面内容路由器。给你一页书的文本，判断它包含哪些类型的可提取信息。

输出纯 JSON，不要解释。

判断规则：
- A (定量参数): 页面包含数学公式、数据表格、物理常数、动力学参数、温度-时间曲线。\
关键词：Ea, k, D-value, Cp, viscosity, correlation, coefficient, 活化能, 速率常数
- B (食谱): 页面包含配料表、烹饪步骤、温度/时间指令、份量。\
关键词：ingredients, preheat, bake at, 材料, 做法, 步骤
- C (食材): 页面描述食材属性——品种、产地、季节、部位、营养成分、替代品。\
关键词：variety, cultivar, season, substitute, 品种, 产地, 部位
- D (审美/术语): 页面描述感官品质、风味目标、烹饪术语定义。\
关键词：texture, crispy, tender, umami, 口感, 嫩滑, 镬气, 断生

跳过规则：如果页面是目录、索引、版权页、空白页、纯图片说明，所有 signal 设为 false 并填写 skip_reason。

宁可多标不可漏标。如果不确定，标为 true。

hints 字段：
- 如果 A=true，尝试识别可能匹配的 MF 编号\
（从以下列表：MF-T01~T05, MF-K01~K05, MF-M01~M06, MF-R01~R07, MF-C01~C05）
- 如果 C=true，列出检测到的食材名
- 如果 D=true，列出检测到的审美/术语词
"""

USER_TEMPLATE = """\
=== Page {page_number} ===
{page_text}
"""

EXPECTED_JSON = """\
{
  "signals": {"A": true/false, "B": true/false, "C": true/false, "D": true/false},
  "hints": {
    "A": {"mf_candidates": [], "has_table": bool, "has_equation": bool},
    "C": {"ingredients_detected": []},
    "D": {"aesthetic_terms": []}
  },
  "confidence": 0.0-1.0,
  "skip_reason": null or "toc/index/blank/copyright"
}"""

# ── Ollama call ───────────────────────────────────────────────────────────────

def call_ollama(
    page_num: int,
    page_text: str,
    model: str = DEFAULT_MODEL,
    retries: int = 3,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    log = logger or logging.getLogger(__name__)

    # Truncate very long pages
    text_snippet = page_text[:3000] if len(page_text) > 3000 else page_text

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": USER_TEMPLATE.format(
            page_number=page_num,
            page_text=text_snippet,
        )},
    ]

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 512,
            "num_ctx": 4096,
        },
    }

    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(trust_env=False, timeout=60, follow_redirects=False) as client:
                resp = client.post(f"{OLLAMA_URL}/api/chat", json=payload)
            resp.raise_for_status()
            content = resp.json()["message"]["content"].strip()
            return parse_signal_json(content, page_num, log)
        except Exception as e:
            log.warning(f"[router] page {page_num} attempt {attempt} failed: {e}")
            if attempt == retries:
                log.error(f"[router] page {page_num} all retries failed — returning safe default")
                return default_signal(page_num, skip_reason=f"router_error: {e}")
            time.sleep(1)

    return default_signal(page_num)

def normalize_signal(raw: dict, page_num: int) -> dict:
    """Normalize model output to canonical signal schema.
    
    Handles two formats:
      1. {signals: {A: bool,...}, hints: {...}, ...}  (canonical)
      2. {A: bool, B: bool, C: bool, D: bool, ...}   (flat, model often emits this)
    """
    if "signals" in raw:
        return raw  # already canonical

    # Flat format — lift A/B/C/D into signals dict
    sigs = {k: bool(raw.get(k, False)) for k in ("A","B","C","D")}
    hints: dict = {}
    if "hints" in raw:
        hints = raw["hints"]
    else:
        # Try to find nested hint keys used by model
        for key in ("A","C","D"):
            # Some models output hints inline
            if key + "_hints" in raw:
                hints[key] = raw[key + "_hints"]
        # Collect ingredient/term lists if model put them at top level
        if "ingredients" in raw:
            hints.setdefault("C", {})["ingredients_detected"] = raw["ingredients"]
        if "terms" in raw or "aesthetic_terms" in raw:
            hints.setdefault("D", {})["aesthetic_terms"] = raw.get("terms") or raw.get("aesthetic_terms", [])
        if "MF_numbers" in raw or "mf_candidates" in raw:
            hints.setdefault("A", {})["mf_candidates"] = raw.get("MF_numbers") or raw.get("mf_candidates", [])

    return {
        "signals": sigs,
        "hints": hints,
        "confidence": raw.get("confidence", 0.7 if any(sigs.values()) else 0.5),
        "skip_reason": raw.get("skip_reason"),
    }


def parse_signal_json(text: str, page_num: int, log: logging.Logger) -> dict[str, Any]:
    """Extract JSON from LLM response, with fallback parsing."""
    import re

    # Strip <think> blocks if qwen3 thinking mode somehow slips through
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # Try direct parse
    try:
        raw = json.loads(text)
        return normalize_signal(raw, page_num)
    except Exception:
        pass

    # Try to extract JSON block
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            raw = json.loads(m.group(0))
            return normalize_signal(raw, page_num)
        except Exception:
            pass

    log.warning(f"[router] page {page_num}: could not parse JSON from: {text[:200]}")
    # Default: mark all true (recall-first)
    return default_signal(page_num, all_true=True)

def default_signal(page_num: int, skip_reason: str | None = None, all_true: bool = False) -> dict:
    return {
        "signals": {"A": all_true, "B": all_true, "C": all_true, "D": all_true},
        "hints": {
            "A": {"mf_candidates": [], "has_table": False, "has_equation": False},
            "C": {"ingredients_detected": []},
            "D": {"aesthetic_terms": []},
        },
        "confidence": 0.5 if all_true else 0.0,
        "skip_reason": skip_reason,
    }

# ── Resume helpers ────────────────────────────────────────────────────────────

def load_existing_signals(path: Path) -> dict[int, dict]:
    """Load existing signals.json, keyed by page number."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
        return {entry["page"]: entry for entry in data if "page" in entry}
    except Exception:
        return {}

def save_signals(path: Path, signals_list: list[dict]) -> None:
    path.write_text(json.dumps(signals_list, ensure_ascii=False, indent=2))

# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="9b Signal Router — per-page markdown to A/B/C/D signals")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--book-id", help="Book ID → reads output/{book_id}/pages.json")
    grp.add_argument("--input-file", help="Explicit path to pages.json")
    p.add_argument("--out", help="Output path (default: output/{book_id}/signals.json)")
    p.add_argument("--pages", type=int, default=None, help="Max pages to process (default: all)")
    p.add_argument("--start-page", type=int, default=1, help="Start at this page number (default: 1)")
    p.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    p.add_argument("--resume", action="store_true", default=True, help="Skip already-done pages (default: True)")
    p.add_argument("--no-resume", dest="resume", action="store_false")
    p.add_argument("--force", action="store_true", help="Re-run all pages")
    p.add_argument("--pilot", action="store_true", help="Print detailed output for each page (debug)")
    return p.parse_args()

def main() -> None:
    args = parse_args()

    # Resolve input
    if args.input_file:
        pages_path = Path(args.input_file).expanduser()
        book_id = pages_path.parent.name
        out_path = Path(args.out) if args.out else pages_path.parent / "signals.json"
    elif args.book_id:
        book_id = args.book_id
        pages_path = REPO_ROOT / "output" / book_id / "pages.json"
        out_path = Path(args.out) if args.out else REPO_ROOT / "output" / book_id / "signals.json"
    else:
        print("ERROR: Provide --book-id or --input-file", file=sys.stderr)
        sys.exit(1)

    if not pages_path.exists():
        print(f"ERROR: {pages_path} not found. Run ocr_claw.py first.", file=sys.stderr)
        sys.exit(1)

    # Logging
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = out_path.parent / "signal_router.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )
    log = logging.getLogger("signal_router")
    log.info(f"book_id={book_id}, model={args.model}, resume={args.resume}")

    # Load pages
    pages: list[dict] = json.loads(pages_path.read_text())
    log.info(f"Loaded {len(pages)} pages from {pages_path}")

    # Apply start_page / max_pages filter
    pages = [p for p in pages if p["page"] >= args.start_page]
    if args.pages:
        pages = pages[:args.pages]

    # Load existing signals for resume
    existing: dict[int, dict] = {}
    if args.resume and not args.force:
        existing = load_existing_signals(out_path)
        if existing:
            log.info(f"Resume: {len(existing)} pages already done")

    # Process
    signals_by_page: dict[int, dict] = dict(existing)
    todo = [p for p in pages if p["page"] not in existing or args.force]
    log.info(f"Processing {len(todo)}/{len(pages)} pages (skipping {len(pages)-len(todo)} already done)")

    t0 = time.time()
    for i, page in enumerate(todo):
        page_num = page["page"]
        page_text = page.get("text", "")

        if not page_text.strip():
            sig = default_signal(page_num, skip_reason="blank_page")
        else:
            sig = call_ollama(page_num, page_text, model=args.model, logger=log)

        sig["page"] = page_num
        signals_by_page[page_num] = sig

        if args.pilot:
            sigs = sig.get("signals", {})
            print(f"  page {page_num:4d}: A={sigs.get('A',False)!s:5} B={sigs.get('B',False)!s:5} "
                  f"C={sigs.get('C',False)!s:5} D={sigs.get('D',False)!s:5} "
                  f"conf={sig.get('confidence', 0):.2f}  skip={sig.get('skip_reason')}")

        # Save every 50 pages
        if (i + 1) % 50 == 0:
            sorted_sigs = sorted(signals_by_page.values(), key=lambda x: x["page"])
            save_signals(out_path, sorted_sigs)
            elapsed = time.time() - t0
            log.info(f"Checkpoint: {i+1}/{len(todo)} pages, {elapsed:.0f}s")

    # Final save
    sorted_sigs = sorted(signals_by_page.values(), key=lambda x: x["page"])
    save_signals(out_path, sorted_sigs)

    elapsed = time.time() - t0
    log.info(f"Done: {len(sorted_sigs)} signals in {elapsed:.1f}s → {out_path}")

    # Statistics
    total  = len(sorted_sigs)
    sig_a  = sum(1 for s in sorted_sigs if s.get("signals",{}).get("A"))
    sig_b  = sum(1 for s in sorted_sigs if s.get("signals",{}).get("B"))
    sig_c  = sum(1 for s in sorted_sigs if s.get("signals",{}).get("C"))
    sig_d  = sum(1 for s in sorted_sigs if s.get("signals",{}).get("D"))
    skipped = sum(1 for s in sorted_sigs if s.get("skip_reason"))

    print(f"\n── Signal Router Summary ──")
    print(f"  book_id:  {book_id}")
    print(f"  total:    {total}")
    print(f"  A (quant):{sig_a:4d} ({sig_a/total*100:.0f}%)")
    print(f"  B (recipe):{sig_b:3d} ({sig_b/total*100:.0f}%)")
    print(f"  C (ingred):{sig_c:3d} ({sig_c/total*100:.0f}%)")
    print(f"  D (aesthetic):{sig_d:1d} ({sig_d/total*100:.0f}%)")
    print(f"  skipped:  {skipped}")
    print(f"  time:     {elapsed:.1f}s")
    print(f"  output:   {out_path}")

if __name__ == "__main__":
    main()
