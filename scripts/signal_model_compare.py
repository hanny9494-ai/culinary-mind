#!/usr/bin/env python3
"""
scripts/signal_model_compare.py
三模型对比评测 — signal_router 在不同 DashScope 模型下的准确率 / 速度 / 成本

从 3 本书各抽 10 页（stratified: 5页有skill结果 + 5页无skill结果），
用 3 个模型分别跑信号路由，对比：
  - A/D 信号准确率（以 skill_a / skill_d results.jsonl 为 ground truth）
  - 漏标率（false negative）
  - 误标率（false positive）
  - hints 质量（MF_id 是否存在且合理）
  - 速度（秒/页）
  - 输入/输出 token 数

Usage:
    python scripts/signal_model_compare.py
    python scripts/signal_model_compare.py --pages-per-book 15 --concurrency 8
    python scripts/signal_model_compare.py --output /tmp/compare.json
    python scripts/signal_model_compare.py --models qwen3.5-flash qwen3.6-plus
"""

import asyncio
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Any

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ.setdefault("no_proxy", "localhost,127.0.0.1,dashscope.aliyuncs.com")

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output"
DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# ── Books to sample ───────────────────────────────────────────────────────────
SAMPLE_BOOKS = [
    {
        "book_id": "rao_engineering_properties",
        "desc": "工程教科书（公式密集）",
        "has_skill_a": True,
        "has_skill_d": False,
    },
    {
        "book_id": "koji_alchemy",
        "desc": "科学+食谱混合",
        "has_skill_a": True,
        "has_skill_d": True,
    },
    {
        "book_id": "guangdong_pengtiao_quanshu",
        "desc": "中文粤菜（审美+食谱）",
        "has_skill_a": False,
        "has_skill_d": True,
    },
]

# ── Models to compare (all via DashScope) ─────────────────────────────────────
DEFAULT_MODELS = [
    "qwen3.5-flash",
    "qwen3.6-plus",
    "glm-5",
]

# ── Prompt (same as signal_router.py — must not be modified) ──────────────────
SYSTEM_PROMPT = """\
你是一个页面内容路由器。给你一页书的文本，判断它包含哪些类型的可提取信息。

输出纯 JSON，不要解释。

判断规则：
- A (定量参数): 页面含有任何可量化的科学数据，包括但不限于：
  * 明确数值：温度（60°C, 160°F）、时间（30 min）、百分比（20%）、能量（37 J/g）、pH、重量
  * 数学公式或方程（任何含变量的表达式）
  * 数据表格或图表中的数值
  * 物理/化学常数（活化能 Ea、速率常数 k、扩散系数 D）
  * 定量比较陈述：如"fat explains 20% of variation"、"3 times more myoglobin"
  * 科学阈值：如"above 60°C collagen shrinks"、"water activity below 0.85"
  ⚠️ 宁可多标！只要页面里有任何具体数字或可测量的量，就标 A=true。
  关键词：%, °C, °F, J/g, kJ/mol, mg, mM, ppm, ratio, coefficient, correlation
- B (食谱): 页面包含配料表、烹饪步骤、温度/时间指令、份量。\
关键词：ingredients, preheat, bake at, 材料, 做法, 步骤
- C (食材): 页面描述食材属性——品种、产地、季节、部位、营养成分、替代品。\
关键词：variety, cultivar, season, substitute, 品种, 产地, 部位
- D (审美/术语): 页面描述感官品质、风味目标、烹饪术语定义。\
关键词：texture, crispy, tender, umami, 口感, 嫩滑, 镬气, 断生

跳过规则：如果页面是目录、索引、版权页、空白页、纯图片说明，所有 signal 设为 false 并填写 skip_reason。

⚠️ 核心原则：宁可多标不可漏标。如果不确定，标为 true。

Few-shot 示例（A 信号判断）：

示例1 — 输入："fat content explains only about 20% of the variation in tenderness"
→ A=true（包含具体百分比 20%，定量陈述）

示例2 — 输入："Animal fat stores energy quite densely—about 37 joules per gram, comparable to gasoline"
→ A=true（包含具体能量密度 37 J/g）

示例3 — 输入："temperatures above 60°C cause collagen to contract and squeeze out moisture"
→ A=true（包含温度阈值 60°C）

示例4 — 输入："Duck breasts are made up mainly of intermediate fibers containing myoglobin"
→ A=false（纯描述性，无具体数值）

示例5 — 输入："Table 3.2: Collagen content (%) — beef chuck 1.8%, beef tenderloin 0.3%"
→ A=true（含数据表格和百分比）

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

# ── Data loading ──────────────────────────────────────────────────────────────

def load_pages(book_id: str) -> list[dict]:
    path = OUTPUT_ROOT / book_id / "pages.json"
    if not path.exists():
        return []
    return json.loads(path.read_text())


def load_skill_ground_truth(book_id: str, skill: str) -> set[int]:
    """Return set of page numbers that have at least one skill result."""
    path = OUTPUT_ROOT / book_id / f"skill_{skill}" / "results.jsonl"
    if not path.exists():
        return set()
    pages: set[int] = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                page = obj.get("_page") or (obj.get("source") or {}).get("page")
                if page is not None:
                    pages.add(int(page))
            except Exception:
                pass
    return pages


def sample_pages_stratified(
    all_pages: list[dict],
    skill_a_gt: set[int],
    n_positive: int = 5,
    n_negative: int = 5,
    seed: int = 42,
) -> list[dict]:
    """
    Stratified sample: n_positive pages from pages WITH skill_a results,
    n_negative pages from pages WITHOUT skill_a results.
    Falls back to simple random if strata are too small.
    """
    content_pages = [p for p in all_pages if p.get("text", "").strip()]
    positive = [p for p in content_pages if p["page"] in skill_a_gt]
    negative = [p for p in content_pages if p["page"] not in skill_a_gt]

    rng = random.Random(seed)
    sampled_pos = rng.sample(positive, min(n_positive, len(positive)))
    sampled_neg = rng.sample(negative, min(n_negative, len(negative)))

    # If not enough in either stratum, top up from the other
    total_needed = n_positive + n_negative
    result = sampled_pos + sampled_neg
    if len(result) < total_needed:
        remaining_pool = [p for p in content_pages if p not in result]
        extra = rng.sample(remaining_pool, min(total_needed - len(result), len(remaining_pool)))
        result += extra

    return sorted(result, key=lambda p: p["page"])

# ── DashScope async call ───────────────────────────────────────────────────────

def parse_signal_json(text: str) -> dict:
    """Extract JSON signal from model response."""
    import re
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    def normalize(raw: dict) -> dict:
        if "signals" in raw:
            return raw
        sigs = {k: bool(raw.get(k, False)) for k in ("A", "B", "C", "D")}
        hints = raw.get("hints", {})
        return {
            "signals": sigs,
            "hints": hints,
            "confidence": raw.get("confidence", 0.7 if any(sigs.values()) else 0.5),
            "skip_reason": raw.get("skip_reason"),
        }

    try:
        return normalize(json.loads(text))
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return normalize(json.loads(m.group(0)))
        except Exception:
            pass
    # Fallback: all true (recall-first)
    return {
        "signals": {"A": True, "B": True, "C": True, "D": True},
        "hints": {},
        "confidence": 0.3,
        "skip_reason": "parse_error",
    }


async def call_model_async(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    page: dict,
    model: str,
    api_key: str,
) -> dict:
    """Call DashScope for one page with one model. Returns result dict."""
    page_num = page["page"]
    page_text = page.get("text", "")[:3000]
    user_content = USER_TEMPLATE.format(page_number=page_num, page_text=page_text)

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

    t_start = time.time()
    error_msg = None
    signal_result = None
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    async with semaphore:
        for attempt in range(1, 4):
            try:
                resp = await client.post(DASHSCOPE_URL, headers=headers, json=body)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                signal_result = parse_signal_json(content)
                usage = data.get("usage", usage)
                break
            except Exception as e:
                error_msg = str(e)
                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)

    elapsed = time.time() - t_start

    if signal_result is None:
        signal_result = {
            "signals": {"A": True, "B": True, "C": True, "D": True},
            "hints": {},
            "confidence": 0.0,
            "skip_reason": f"error: {error_msg}",
        }

    return {
        "page": page_num,
        "model": model,
        "signal": signal_result,
        "elapsed_s": round(elapsed, 3),
        "usage": usage,
    }


async def run_model_on_pages(
    pages: list[dict],
    model: str,
    api_key: str,
    concurrency: int = 5,
) -> list[dict]:
    """Run model on all pages concurrently. Returns list of result dicts."""
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(trust_env=False, timeout=90, follow_redirects=False) as client:
        tasks = [call_model_async(client, semaphore, p, model, api_key) for p in pages]
        return await asyncio.gather(*tasks, return_exceptions=False)

# ── Evaluation ────────────────────────────────────────────────────────────────

VALID_MF_PREFIXES = {"MF-T", "MF-K", "MF-M", "MF-R", "MF-C"}


def evaluate_signal(
    results: list[dict],
    ground_truth_pages: set[int],
    signal_key: str = "A",
) -> dict:
    """
    Evaluate one signal key against ground truth page set.
    ground_truth_pages: pages where skill extracted at least one result.
    """
    if not ground_truth_pages:
        return {"note": "no_ground_truth"}

    tp = fp = fn = tn = 0
    hints_useful = 0
    hints_total = 0

    for r in results:
        page = r["page"]
        sig = r["signal"]
        predicted = sig.get("signals", {}).get(signal_key, False)
        actual = page in ground_truth_pages

        if predicted and actual:
            tp += 1
        elif predicted and not actual:
            fp += 1
        elif not predicted and actual:
            fn += 1
        else:
            tn += 1

        # hints quality for A signal: check mf_candidates
        if signal_key == "A" and predicted:
            hints_a = sig.get("hints", {}).get("A", {})
            mf_cands = hints_a.get("mf_candidates", []) if isinstance(hints_a, dict) else []
            hints_total += 1
            if any(any(c.startswith(pfx) for pfx in VALID_MF_PREFIXES) for c in mf_cands):
                hints_useful += 1

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    fn_rate = fn / (tp + fn) if (tp + fn) > 0 else 0.0
    fp_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    result = {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "fn_rate": round(fn_rate, 3),
        "fp_rate": round(fp_rate, 3),
    }
    if signal_key == "A":
        result["hints_useful_pct"] = round(
            hints_useful / hints_total * 100, 1
        ) if hints_total > 0 else 0.0

    return result

# ── Formatting ────────────────────────────────────────────────────────────────

def fmt_pct(val: Any, factor: float = 100.0, decimals: int = 0) -> str:
    if val == "N/A" or not isinstance(val, (int, float)):
        return "N/A"
    return f"{val * factor:.{decimals}f}%"


def fmt_f(val: Any, decimals: int = 2) -> str:
    if not isinstance(val, (int, float)):
        return "N/A"
    return f"{val:.{decimals}f}"


def print_comparison_table(
    model_stats: dict[str, dict],
    books: list[dict],
) -> None:
    """Print formatted comparison table to stdout."""
    print("\n" + "=" * 90)
    print("  SIGNAL ROUTER — 三模型对比评测")
    print("=" * 90)

    all_book_ids = [b["book_id"] for b in books]

    for book_cfg in books:
        bid = book_cfg["book_id"]
        desc = book_cfg.get("desc", "")
        has_a = book_cfg.get("has_skill_a", False)
        has_d = book_cfg.get("has_skill_d", False)
        gt_info = []
        if has_a:
            gt_info.append("GT:skill_a")
        if has_d:
            gt_info.append("GT:skill_d")
        print(f"\n📚 {bid} — {desc}  ({', '.join(gt_info) or '无ground truth'})")

        # Signal A table
        if has_a:
            print(f"\n  [Signal A — 定量参数]")
            hdr = f"  {'Model':<22} {'Pages':>5} {'Time/p':>7} {'Tokens':>7} {'Recall':>7} {'Prec':>7} {'F1':>5} {'FN%':>6} {'FP%':>6} {'Hints%':>7}"
            print(hdr)
            print("  " + "-" * 80)
            for model, stats in model_stats.items():
                bk = stats["per_book"].get(bid, {})
                if not bk:
                    continue
                acc = bk.get("accuracy_a", {})
                avg_t = bk.get("avg_time_s", 0)
                avg_tok = bk.get("avg_tokens", 0)
                if "note" in acc:
                    row = f"  {model:<22} {bk.get('n_pages',0):>5} {avg_t:>6.2f}s {avg_tok:>7.0f} {'N/A':>7} {'N/A':>7} {'N/A':>5} {'N/A':>6} {'N/A':>6} {'N/A':>7}"
                else:
                    row = (
                        f"  {model:<22} {bk.get('n_pages',0):>5} {avg_t:>6.2f}s {avg_tok:>7.0f} "
                        f"{fmt_pct(acc.get('recall')):>7} "
                        f"{fmt_pct(acc.get('precision')):>7} "
                        f"{fmt_f(acc.get('f1')):>5} "
                        f"{fmt_pct(acc.get('fn_rate')):>6} "
                        f"{fmt_pct(acc.get('fp_rate')):>6} "
                        f"{fmt_f(acc.get('hints_useful_pct', 0), 1):>6}%"
                    )
                print(row)

        # Signal D table
        if has_d:
            print(f"\n  [Signal D — 审美/术语]")
            hdr = f"  {'Model':<22} {'Recall':>7} {'Prec':>7} {'F1':>5} {'FN%':>6} {'FP%':>6}"
            print(hdr)
            print("  " + "-" * 50)
            for model, stats in model_stats.items():
                bk = stats["per_book"].get(bid, {})
                if not bk:
                    continue
                acc = bk.get("accuracy_d", {})
                if "note" in acc or not acc:
                    row = f"  {model:<22} {'N/A':>7} {'N/A':>7} {'N/A':>5} {'N/A':>6} {'N/A':>6}"
                else:
                    row = (
                        f"  {model:<22} "
                        f"{fmt_pct(acc.get('recall')):>7} "
                        f"{fmt_pct(acc.get('precision')):>7} "
                        f"{fmt_f(acc.get('f1')):>5} "
                        f"{fmt_pct(acc.get('fn_rate')):>6} "
                        f"{fmt_pct(acc.get('fp_rate')):>6}"
                    )
                print(row)

    # Overall summary
    print(f"\n{'='*90}")
    print("  OVERALL (Signal A, books with ground truth)")
    print(f"{'='*90}")
    hdr = f"  {'Model':<22} {'Pages':>5} {'Time/p':>7} {'In tok':>7} {'Out tok':>8} {'Recall':>7} {'Prec':>7} {'F1':>5} {'FN%':>6} {'FP%':>6}"
    print(hdr)
    print("  " + "-" * 85)
    for model, stats in model_stats.items():
        ov = stats.get("overall", {})
        acc = ov.get("accuracy_a", {})
        avg_t = ov.get("avg_time_s", 0)
        avg_in = ov.get("avg_prompt_tokens", 0)
        avg_out = ov.get("avg_completion_tokens", 0)
        n = ov.get("n_pages", 0)
        if "note" in acc or not acc:
            row = f"  {model:<22} {n:>5} {avg_t:>6.2f}s {avg_in:>7.0f} {avg_out:>8.0f} {'N/A':>7} {'N/A':>7} {'N/A':>5} {'N/A':>6} {'N/A':>6}"
        else:
            row = (
                f"  {model:<22} {n:>5} {avg_t:>6.2f}s {avg_in:>7.0f} {avg_out:>8.0f} "
                f"{fmt_pct(acc.get('recall')):>7} "
                f"{fmt_pct(acc.get('precision')):>7} "
                f"{fmt_f(acc.get('f1')):>5} "
                f"{fmt_pct(acc.get('fn_rate')):>6} "
                f"{fmt_pct(acc.get('fp_rate')):>6}"
            )
        print(row)
    print()


def pick_winner(model_stats: dict[str, dict]) -> str:
    """Composite score: recall * 0.5 + (1-fn_rate) * 0.3 + speed_score * 0.2"""
    scores = {}
    times = {m: s["overall"].get("avg_time_s", 999) for m, s in model_stats.items()}
    max_time = max(times.values()) or 1

    for model, stats in model_stats.items():
        acc = stats["overall"].get("accuracy_a", {})
        if "note" in acc or not acc:
            scores[model] = 0.0
            continue
        recall = acc.get("recall", 0)
        fn_rate = acc.get("fn_rate", 1)
        speed_score = 1 - (times[model] / max_time)
        scores[model] = recall * 0.5 + (1 - fn_rate) * 0.3 + speed_score * 0.2

    if not scores:
        return ""
    return max(scores, key=lambda m: scores[m])

# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="三模型 signal_router 对比评测（全部走 DashScope API）")
    p.add_argument("--pages-per-book", type=int, default=10,
                   help="每本书抽样页数（默认10，stratified: 5正+5负）")
    p.add_argument("--concurrency", type=int, default=5,
                   help="DashScope 并发数（默认5）")
    p.add_argument("--seed", type=int, default=42,
                   help="随机种子（默认42，确保可复现）")
    p.add_argument("--output", default="",
                   help="结果 JSON 保存路径（默认 output/signal_model_comparison.json）")
    p.add_argument("--models", nargs="*", default=None,
                   help=f"覆盖测试的模型列表（默认: {' '.join(DEFAULT_MODELS)}）")
    p.add_argument("--verbose", action="store_true",
                   help="显示每页详细结果")
    return p.parse_args()


async def main_async(args) -> None:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("ERROR: DASHSCOPE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    models = args.models or DEFAULT_MODELS
    n_per_book = args.pages_per_book
    n_pos = n_per_book // 2
    n_neg = n_per_book - n_pos

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    log = logging.getLogger("compare")

    # ── Load samples ──────────────────────────────────────────────────────────
    book_samples: dict[str, list[dict]] = {}
    book_gt_a: dict[str, set[int]] = {}
    book_gt_d: dict[str, set[int]] = {}

    active_books = []
    for book_cfg in SAMPLE_BOOKS:
        bid = book_cfg["book_id"]
        all_pages = load_pages(bid)
        if not all_pages:
            log.warning(f"Book {bid}: pages.json not found, skipping")
            continue

        gt_a = load_skill_ground_truth(bid, "a") if book_cfg["has_skill_a"] else set()
        gt_d = load_skill_ground_truth(bid, "d") if book_cfg["has_skill_d"] else set()

        # Stratify on skill_a (primary signal)
        if gt_a:
            sampled = sample_pages_stratified(all_pages, gt_a, n_pos, n_neg, seed=args.seed)
        else:
            # No skill_a GT: just random sample
            content_pages = [p for p in all_pages if p.get("text", "").strip()]
            rng = random.Random(args.seed)
            sampled = rng.sample(content_pages, min(n_per_book, len(content_pages)))
            sampled = sorted(sampled, key=lambda p: p["page"])

        book_samples[bid] = sampled
        book_gt_a[bid] = gt_a
        book_gt_d[bid] = gt_d
        active_books.append(book_cfg)

        log.info(
            f"Book {bid}: {len(sampled)} pages sampled "
            f"(pos={sum(1 for p in sampled if p['page'] in gt_a)} "
            f"neg={sum(1 for p in sampled if p['page'] not in gt_a)}), "
            f"skill_a GT={len(gt_a)} pages, skill_d GT={len(gt_d)} pages"
        )

    if not book_samples:
        print("ERROR: No books found in output/", file=sys.stderr)
        sys.exit(1)

    # ── Run each model on all books ───────────────────────────────────────────
    all_results: dict[str, dict[str, list[dict]]] = {}  # model → book_id → results

    for model in models:
        log.info(f"\n{'='*60}")
        log.info(f"Running model: {model}")
        log.info(f"{'='*60}")
        all_results[model] = {}

        for bid, pages in book_samples.items():
            log.info(f"  → {bid} ({len(pages)} pages, concurrency={args.concurrency})")
            t0 = time.time()
            results = await run_model_on_pages(pages, model, api_key, args.concurrency)
            elapsed = time.time() - t0
            all_results[model][bid] = results
            log.info(f"     done: {elapsed:.1f}s total, {elapsed/len(pages):.2f}s/page")

            if args.verbose:
                for r in results:
                    sig = r["signal"].get("signals", {})
                    print(
                        f"    p{r['page']:04d} A={sig.get('A',False)} B={sig.get('B',False)} "
                        f"C={sig.get('C',False)} D={sig.get('D',False)} "
                        f"t={r['elapsed_s']:.2f}s "
                        f"in={r['usage'].get('prompt_tokens',0)} "
                        f"out={r['usage'].get('completion_tokens',0)}"
                    )

    # ── Compute stats ─────────────────────────────────────────────────────────
    model_stats: dict[str, dict] = {}

    for model in models:
        per_book: dict[str, dict] = {}
        all_model_results: list[dict] = []

        for bid, results in all_results.get(model, {}).items():
            gt_a = book_gt_a.get(bid, set())
            gt_d = book_gt_d.get(bid, set())
            times = [r["elapsed_s"] for r in results]
            prompt_toks = [r["usage"].get("prompt_tokens", 0) for r in results]
            completion_toks = [r["usage"].get("completion_tokens", 0) for r in results]
            total_toks = [r["usage"].get("total_tokens", 0) for r in results]

            acc_a = evaluate_signal(results, gt_a, "A") if gt_a else {"note": "no_ground_truth"}
            acc_d = evaluate_signal(results, gt_d, "D") if gt_d else {"note": "no_ground_truth"}

            per_book[bid] = {
                "n_pages": len(results),
                "avg_time_s": round(sum(times) / len(times), 3) if times else 0,
                "total_time_s": round(sum(times), 2),
                "avg_tokens": round(sum(total_toks) / len(total_toks)) if total_toks else 0,
                "total_tokens": sum(total_toks),
                "avg_prompt_tokens": round(sum(prompt_toks) / len(prompt_toks)) if prompt_toks else 0,
                "avg_completion_tokens": round(sum(completion_toks) / len(completion_toks)) if completion_toks else 0,
                "accuracy_a": acc_a,
                "accuracy_d": acc_d,
            }
            all_model_results.extend(results)

        # Overall across all books
        ov_times = [r["elapsed_s"] for r in all_model_results]
        ov_prompt = [r["usage"].get("prompt_tokens", 0) for r in all_model_results]
        ov_completion = [r["usage"].get("completion_tokens", 0) for r in all_model_results]
        ov_total = [r["usage"].get("total_tokens", 0) for r in all_model_results]

        # Only evaluate A accuracy on books that have skill_a GT
        gt_results_a = [
            r for bid, results in all_results.get(model, {}).items()
            for r in results
            if book_gt_a.get(bid)
        ]
        all_gt_a = set().union(*(gt for gt in book_gt_a.values() if gt))
        acc_overall_a = evaluate_signal(gt_results_a, all_gt_a, "A") if gt_results_a else {"note": "no_ground_truth"}

        model_stats[model] = {
            "model": model,
            "per_book": per_book,
            "overall": {
                "n_pages": len(all_model_results),
                "avg_time_s": round(sum(ov_times) / len(ov_times), 3) if ov_times else 0,
                "total_time_s": round(sum(ov_times), 2),
                "avg_prompt_tokens": round(sum(ov_prompt) / len(ov_prompt)) if ov_prompt else 0,
                "avg_completion_tokens": round(sum(ov_completion) / len(ov_completion)) if ov_completion else 0,
                "avg_tokens": round(sum(ov_total) / len(ov_total)) if ov_total else 0,
                "total_tokens": sum(ov_total),
                "accuracy_a": acc_overall_a,
            },
        }

    # ── Print table ───────────────────────────────────────────────────────────
    print_comparison_table(model_stats, active_books)

    winner = pick_winner(model_stats)
    if winner:
        print(f"  🏆 推荐模型（综合评分: recall×0.5 + (1-FN)×0.3 + speed×0.2）: {winner}")
        print()

    # ── Save JSON ─────────────────────────────────────────────────────────────
    output_path = Path(args.output) if args.output else OUTPUT_ROOT / "signal_model_comparison.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    comparison_output = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pages_per_book": n_per_book,
            "n_positive_per_book": n_pos,
            "n_negative_per_book": n_neg,
            "seed": args.seed,
            "concurrency": args.concurrency,
            "models": models,
            "books": [b["book_id"] for b in active_books],
        },
        "model_stats": model_stats,
        "raw_results": {
            model: {bid: results for bid, results in book_results.items()}
            for model, book_results in all_results.items()
        },
        "winner": winner,
    }

    output_path.write_text(json.dumps(comparison_output, ensure_ascii=False, indent=2))
    print(f"  Results saved → {output_path}")


def main():
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
