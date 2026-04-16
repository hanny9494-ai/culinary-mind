#!/usr/bin/env python3
"""
pipeline/skills/signal_router.py
Signal Router — per-page markdown → A/B/C/D skill signals

Input:  output/{book_id}/pages.json
Output: output/{book_id}/signals.json

Backends:
  - dashscope (default): qwen3.5-flash via DashScope API (async, concurrent)
  - ollama:              qwen3.5:9b via local Ollama (localhost:11434)

Usage:
    python signal_router.py --book-id mc_vol3
    python signal_router.py --book-id mc_vol3 --backend dashscope --concurrency 8
    python signal_router.py --book-id mc_vol3 --backend ollama
    python signal_router.py --book-id mc_vol3 --pages 20 --start-page 25
    python signal_router.py --input-file /path/to/pages.json --out /path/to/signals.json
"""

import asyncio
import os
import sys
import json
import time
import logging
import argparse
from pathlib import Path
from typing import Any

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,dashscope.aliyuncs.com")

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
DEFAULT_OLLAMA_MODEL = "qwen3.5:9b"
DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DEFAULT_DASHSCOPE_MODEL = "qwen3.6-plus"
DEFAULT_BACKEND = "dashscope"
CHECKPOINT_EVERY = 20

# ── Prompt template ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个页面内容路由器。给你一页书的文本，判断它包含哪些类型的可提取信息。

输出纯 JSON，不要解释。

【Skill A：定量科学参数 → L0 ParameterSet】
提取可绑定到物理/化学方程的定量参数——物质固有属性、动力学常数、经验方程系数。

Scale-up Test（核心判断）：放大食材体积/改变温度/改变时间，这个数字还能用于预测新结果吗？
  能 → A（物质属性/动力学常数/经验系数）
  不能（必须重新实验测量）→ L0 实验现象，不标 A

A 的 3 类数字：
  ① 动力学常数/相变阈值：活化能(Ea)、变性温度、凝胶化温度、Tg、D-value、z-value
  ② 热物性/传递参数：热导率(k)、比热容(Cp)、密度(ρ)、扩散系数(D)
  ③ 经验方程系数：Nusselt/Sherwood 关联式常数、流变模型参数

A 正例（A=true）：
  ✅ "蛋白质 62°C 开始变性，70°C 完全凝固" — 相变阈值，可绑 MF-T03
  ✅ "明胶 Ea=125 kJ/mol" — 动力学常数
  ✅ "表3.2: 各部位胶原蛋白含量(%)" — 系统性科学数据表
  ✅ "肌肉收缩系数 β=0.05 K⁻¹" — 经验方程参数
  ✅ "蛋黄酱临界剪切应力 τ₀=15 Pa" — 流变模型参数
  ✅ "Protein denaturation begins at 62°C" — 英文相变阈值
  ✅ "Table 3.2: Collagen content (%) — beef chuck 1.8%" — 英文数据表

A 反例（A=false）：
  ❌ "160°C 炸 3 分钟" — 食谱操作参数（→ B）
  ❌ "炖煮保持 85°C 可避免蛋白收缩" — 科学服务操作（→ B，科学解释操作理由）
  ❌ "牛肉 60°C 水浴 1h 汁液流失 15%" — 实验终点状态（End-state，→ L0）
  ❌ "微波 800W 2min 土豆中心 85°C" — 设备依赖无普适性（→ L0）
  ❌ "胶原蛋白受热转化为明胶" — 因果链无数字（→ L0）
  ❌ "beef boiled in 212°F water gets hotter faster than in 212°F oven" — 操作对比（→ L0）
  ❌ "Eggs boil at different rates depending on starting temperature" — 无具体数字（→ L0）
  ❌ 科学章节中解释为什么"低温慢煮比高温更好"的段落 — 这是 B 的注脚，不是 A

【关键区分】科学解释 vs 参数提取：
  如果一页的"数字"是为了说明一个烹饪操作的原理（"为什么要低温炖"），它是 B（科学服务操作）
  如果一页有数据表或公式参数（"明胶 Ea=125 kJ/mol"），提取这些参数不依赖烹饪上下文，它是 A

5 个灰色案例（Gemini 专家审核确认）：
  1. "牛肉 60°C 水浴 1h 汁液流失 15%" → A=false（End-state，换块肉就变了）
  2. "肌肉纤维收缩孔隙率变化系数 β=0.05 K⁻¹" → A=true（方程核心参数，可预测任意大小）
  3. "蛋黄酱临界剪切应力 τ₀=15 Pa" → A=true（Bingham 流体参数，填方程可用）
  4. "面团水分 12% 时 aw=0.6" → A=true（等温线参数，可拟合热力学方程）
  5. "微波 800W 2min 土豆中心 85°C" → A=false（设备依赖，无普适性）

⚠️ 核心原则：宁可多标 suspect，不漏标真正有价值的 A。如不确定，标 A=true。
⚠️ 同一页可以同时是 A+B（含科学参数表的食谱页）

【Skill B：食谱/操作指令 → L2b】
包含烹饪操作指令——配料表、步骤序列、温度/时间操作参数。
即使含科学解释，只要目的是"教你怎么做菜"或"解释为什么要这样做菜" → B=true。
"科学服务操作"：用科学原理解释烹饪技法（为什么低温慢煮更嫩，为什么加盐改变质地）→ B
操作判断：这页是在告诉读者如何或为何要这样操作食物吗？是 → B。
关键词（中）：材料、做法、步骤、份量、烹饪方法、为什么要...、如何避免...
关键词（英）：ingredients, preheat, bake at, recipe, serves, how to, why you should, key to

【Skill C：食材 → L2a】
页面描述食材属性——品种、产地、季节、部位、营养成分、替代品。
关键词：variety, cultivar, season, substitute, 品种, 产地, 部位

【Skill D：审美/术语 → FT + L6】
页面描述感官品质、风味目标、烹饪术语定义。
关键词：texture, crispy, tender, umami, 口感, 嫩滑, 镬气, 断生

跳过规则：如果页面是目录、索引、版权页、空白页、纯图片说明，所有 signal 设为 false 并填写 skip_reason。

hints 字段：
- 如果 A=true，尝试识别可能匹配的 MF 编号（MF-T01~T05, MF-K01~K05, MF-M01~M06, MF-R01~R07, MF-C01~C05）
- 如果 C=true，列出检测到的食材名
- 如果 D=true，列出检测到的审美/术语词
"""

USER_TEMPLATE = """\
=== Page {page_number} ===
{page_text}
"""

# ── JSON helpers ──────────────────────────────────────────────────────────────

def normalize_signal(raw: dict, page_num: int) -> dict:
    """Normalize model output to canonical signal schema.

    Handles two formats:
      1. {signals: {A: bool,...}, hints: {...}, ...}  (canonical)
      2. {A: bool, B: bool, C: bool, D: bool, ...}   (flat, model often emits this)
    """
    if "signals" in raw:
        return raw  # already canonical

    # Flat format — lift A/B/C/D into signals dict
    sigs = {k: bool(raw.get(k, False)) for k in ("A", "B", "C", "D")}
    hints: dict = {}
    if "hints" in raw:
        hints = raw["hints"]
    else:
        for key in ("A", "C", "D"):
            if key + "_hints" in raw:
                hints[key] = raw[key + "_hints"]
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

# ── Ollama call (synchronous) ─────────────────────────────────────────────────

def call_ollama(
    page_num: int,
    page_text: str,
    model: str = DEFAULT_OLLAMA_MODEL,
    retries: int = 3,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    log = logger or logging.getLogger(__name__)

    text_snippet = page_text[:3000] if len(page_text) > 3000 else page_text

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": USER_TEMPLATE.format(
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
            log.warning(f"[router] ollama page {page_num} attempt {attempt} failed: {e}")
            if attempt == retries:
                log.error(f"[router] ollama page {page_num} all retries failed — returning safe default")
                return default_signal(page_num, skip_reason=f"router_error: {e}")
            time.sleep(1)

    return default_signal(page_num)

# ── DashScope async concurrent calls ──────────────────────────────────────────

async def async_call_dashscope(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    page_num: int,
    page_text: str,
    model: str,
    api_key: str,
    retries: int = 3,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Async single-page DashScope call with semaphore concurrency control."""
    log = logger or logging.getLogger(__name__)

    text_snippet = page_text[:3000] if len(page_text) > 3000 else page_text
    user_content = USER_TEMPLATE.format(page_number=page_num, page_text=text_snippet)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0,
        "max_tokens": 512,
        "stream": False,
        "enable_thinking": False,
        "response_format": {"type": "json_object"},
    }

    async with semaphore:
        for attempt in range(1, retries + 1):
            try:
                resp = await client.post(DASHSCOPE_URL, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                result = parse_signal_json(text, page_num, log)
                result["page"] = page_num
                return result
            except Exception as e:
                log.warning(f"[router] dashscope page {page_num} attempt {attempt} failed: {e}")
                if attempt == retries:
                    log.error(f"[router] dashscope page {page_num} all retries failed")
                    result = default_signal(page_num, skip_reason=f"dashscope_error: {e}")
                    result["page"] = page_num
                    return result
                await asyncio.sleep(2 ** attempt)

    result = default_signal(page_num)
    result["page"] = page_num
    return result


async def async_process_dashscope(
    todo_pages: list[dict],
    out_path: Path,
    existing: dict[int, dict],
    model: str,
    api_key: str,
    concurrency: int,
    checkpoint_every: int = CHECKPOINT_EVERY,
    log: logging.Logger | None = None,
) -> dict[int, dict]:
    """
    Process pages concurrently via DashScope API.
    Returns signals_by_page dict (merged with existing).
    Saves checkpoint every `checkpoint_every` completions.
    """
    if log is None:
        log = logging.getLogger(__name__)

    signals_by_page: dict[int, dict] = dict(existing)
    semaphore = asyncio.Semaphore(concurrency)
    t0 = time.time()
    completed = 0

    # Handle blank pages before async
    async_tasks = []
    for page in todo_pages:
        pnum = page["page"]
        ptext = page.get("text", "")
        if not ptext.strip():
            sig = default_signal(pnum, skip_reason="blank_page")
            sig["page"] = pnum
            signals_by_page[pnum] = sig
        else:
            async_tasks.append(page)

    log.info(f"[router] Async DashScope: {len(async_tasks)} pages, concurrency={concurrency}, model={model}")

    async with httpx.AsyncClient(trust_env=False, timeout=90, follow_redirects=False) as client:
        tasks = [
            async_call_dashscope(
                client, semaphore,
                p["page"], p.get("text", ""),
                model, api_key,
                logger=log,
            )
            for p in async_tasks
        ]

        # Process in chunks for checkpointing
        for chunk_start in range(0, len(tasks), checkpoint_every):
            chunk = tasks[chunk_start: chunk_start + checkpoint_every]
            results = await asyncio.gather(*chunk, return_exceptions=True)

            for r in results:
                if isinstance(r, Exception):
                    log.error(f"[router] unexpected exception in gather: {r}")
                    continue
                pnum = r.get("page", 0)
                signals_by_page[pnum] = r
                completed += 1

            # Checkpoint save
            sorted_sigs = sorted(signals_by_page.values(), key=lambda x: x["page"])
            save_signals(out_path, sorted_sigs)
            elapsed = time.time() - t0
            rate = completed / elapsed if elapsed > 0 else 0
            log.info(
                f"[router] Checkpoint: {completed}/{len(async_tasks)} done, "
                f"{rate:.1f} pages/s, {elapsed:.0f}s elapsed"
            )

    return signals_by_page

# ── File I/O ──────────────────────────────────────────────────────────────────

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

# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Signal Router — per-page markdown to A/B/C/D signals")
    grp = p.add_mutually_exclusive_group()
    grp.add_argument("--book-id", help="Book ID → reads output/{book_id}/pages.json")
    grp.add_argument("--input-file", help="Explicit path to pages.json")
    p.add_argument("--out", help="Output path (default: output/{book_id}/signals.json)")
    p.add_argument("--pages", type=int, default=None, help="Max pages to process (default: all)")
    p.add_argument("--start-page", type=int, default=1, help="Start at this page number (default: 1)")
    p.add_argument("--resume", action="store_true", default=True, help="Skip already-done pages (default: True)")
    p.add_argument("--no-resume", dest="resume", action="store_false")
    p.add_argument("--force", action="store_true", help="Re-run all pages")
    p.add_argument("--pilot", action="store_true", help="Print detailed output for each page (debug)")

    # Backend selection — --backend is primary, --provider is legacy alias
    p.add_argument(
        "--backend", "--provider",
        choices=["ollama", "dashscope"],
        default=DEFAULT_BACKEND,
        dest="backend",
        help=f"Router backend: dashscope (default, async API) or ollama (local sync)",
    )

    # Model selection
    p.add_argument(
        "--model",
        default=None,
        help=(
            f"Model name. For dashscope: default={DEFAULT_DASHSCOPE_MODEL}. "
            f"For ollama: default={DEFAULT_OLLAMA_MODEL}."
        ),
    )
    # Legacy alias kept for backwards compatibility
    p.add_argument(
        "--dashscope-model",
        default=None,
        dest="dashscope_model_legacy",
        help=argparse.SUPPRESS,  # hidden, use --model instead
    )

    p.add_argument(
        "--concurrency", type=int, default=5,
        help="Concurrent requests for dashscope backend (default: 5)",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    # Resolve effective model
    if args.model:
        effective_model = args.model
    elif args.dashscope_model_legacy:
        effective_model = args.dashscope_model_legacy
    elif args.backend == "dashscope":
        effective_model = DEFAULT_DASHSCOPE_MODEL
    else:
        effective_model = DEFAULT_OLLAMA_MODEL

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
    log.info(
        f"book_id={book_id}, backend={args.backend}, model={effective_model}, "
        f"concurrency={args.concurrency}, resume={args.resume}"
    )

    # Load pages
    pages: list[dict] = json.loads(pages_path.read_text())
    log.info(f"Loaded {len(pages)} pages from {pages_path}")

    # Apply start_page / max_pages filter
    pages = [p for p in pages if p["page"] >= args.start_page]
    if args.pages:
        pages = pages[: args.pages]

    # Load existing signals for resume
    existing: dict[int, dict] = {}
    if args.resume and not args.force:
        existing = load_existing_signals(out_path)
        if existing:
            log.info(f"Resume: {len(existing)} pages already done")

    # Filter todo pages
    todo = [p for p in pages if p["page"] not in existing or args.force]
    log.info(f"Processing {len(todo)}/{len(pages)} pages (skipping {len(pages)-len(todo)} already done)")

    t0 = time.time()

    if args.backend == "dashscope":
        # Async concurrent path
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            print("ERROR: DASHSCOPE_API_KEY not set", file=sys.stderr)
            sys.exit(1)

        signals_by_page = asyncio.run(
            async_process_dashscope(
                todo_pages=todo,
                out_path=out_path,
                existing=existing,
                model=effective_model,
                api_key=api_key,
                concurrency=args.concurrency,
                log=log,
            )
        )

        if args.pilot:
            sorted_sigs = sorted(signals_by_page.values(), key=lambda x: x["page"])
            for sig in sorted_sigs:
                sigs = sig.get("signals", {})
                print(
                    f"  page {sig['page']:4d}: A={sigs.get('A', False)!s:5} B={sigs.get('B', False)!s:5} "
                    f"C={sigs.get('C', False)!s:5} D={sigs.get('D', False)!s:5} "
                    f"conf={sig.get('confidence', 0):.2f}  skip={sig.get('skip_reason')}"
                )

    else:
        # Synchronous Ollama path
        signals_by_page: dict[int, dict] = dict(existing)

        for i, page in enumerate(todo):
            page_num = page["page"]
            page_text = page.get("text", "")

            if not page_text.strip():
                sig = default_signal(page_num, skip_reason="blank_page")
            else:
                sig = call_ollama(page_num, page_text, model=effective_model, logger=log)

            sig["page"] = page_num
            signals_by_page[page_num] = sig

            if args.pilot:
                sigs = sig.get("signals", {})
                print(
                    f"  page {page_num:4d}: A={sigs.get('A', False)!s:5} B={sigs.get('B', False)!s:5} "
                    f"C={sigs.get('C', False)!s:5} D={sigs.get('D', False)!s:5} "
                    f"conf={sig.get('confidence', 0):.2f}  skip={sig.get('skip_reason')}"
                )

            # Save every CHECKPOINT_EVERY pages
            if (i + 1) % CHECKPOINT_EVERY == 0:
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
    total = len(sorted_sigs)
    if total == 0:
        print("No signals processed.")
        return

    sig_a = sum(1 for s in sorted_sigs if s.get("signals", {}).get("A"))
    sig_b = sum(1 for s in sorted_sigs if s.get("signals", {}).get("B"))
    sig_c = sum(1 for s in sorted_sigs if s.get("signals", {}).get("C"))
    sig_d = sum(1 for s in sorted_sigs if s.get("signals", {}).get("D"))
    skipped = sum(1 for s in sorted_sigs if s.get("skip_reason"))

    print(f"\n── Signal Router Summary ──")
    print(f"  book_id:      {book_id}")
    print(f"  backend:      {args.backend}")
    print(f"  model:        {effective_model}")
    print(f"  total:        {total}")
    print(f"  A (quant):    {sig_a:4d} ({sig_a/total*100:.0f}%)")
    print(f"  B (recipe):   {sig_b:4d} ({sig_b/total*100:.0f}%)")
    print(f"  C (ingred):   {sig_c:4d} ({sig_c/total*100:.0f}%)")
    print(f"  D (aesthetic):{sig_d:4d} ({sig_d/total*100:.0f}%)")
    print(f"  skipped:      {skipped}")
    print(f"  time:         {elapsed:.1f}s")
    print(f"  output:       {out_path}")


if __name__ == "__main__":
    main()
