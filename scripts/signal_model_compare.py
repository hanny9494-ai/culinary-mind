#!/usr/bin/env python3
"""
scripts/signal_model_compare.py
三模型对比评测 — signal_router 在不同 DashScope 模型下的准确率 / 速度 / 成本

从 3 本书各抽 10 页，用 3 个模型分别跑信号路由，对比：
  - 准确率（以 skill_a results.jsonl 为 ground truth）
  - 漏标率（false negative）
  - 误标率（false positive）
  - hints 质量（MF_id 有效率）
  - 速度（秒/页）
  - 成本（token 用量）

Usage:
    python scripts/signal_model_compare.py
    python scripts/signal_model_compare.py --pages-per-book 15 --concurrency 8
    python scripts/signal_model_compare.py --output /tmp/compare.json
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
    },
    {
        "book_id": "koji_alchemy",
        "desc": "科学+食谱混合",
        "has_skill_a": True,
    },
    {
        "book_id": "guangdong_pengtiao_quanshu",
        "desc": "中文粤菜（审美+食谱）",
        "has_skill_a": False,  # no skill_a results yet
    },
]

# ── Models to compare (all via DashScope) ─────────────────────────────────────
MODELS = [
    "qwen3.5-flash",
    "qwen-plus",
    "glm-4-flash",  # 智谱 GLM on DashScope; try glm4-flash-250414 if available
]

# ── Prompt (same as signal_router.py) ─────────────────────────────────────────
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


def load_skill_a_ground_truth(book_id: str) -> set[int]:
    """Return set of page numbers that have at least one skill_a result."""
    path = OUTPUT_ROOT / book_id / "skill_a" / "results.jsonl"
    if not path.exists():
        return set()
    pages = set()
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


def sample_pages(pages: list[dict], n: int, seed: int = 42) -> list[dict]:
    """Sample n pages with content (non-blank), reproducible."""
    content_pages = [p for p in pages if p.get("text", "").strip()]
    rng = random.Random(seed)
    if len(content_pages) <= n:
        return content_pages
    return rng.sample(content_pages, n)

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


async def run_model_on_book(
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

def evaluate_skill_a(
    results: list[dict],
    ground_truth_pages: set[int],
) -> dict:
    """
    Evaluate signal A accuracy against ground truth.
    ground_truth_pages: set of page numbers where skill_a found results.
    """
    if not ground_truth_pages:
        return {"note": "no_ground_truth"}

    tp = fp = fn = tn = 0
    valid_mf_prefixes = {"MF-T", "MF-K", "MF-M", "MF-R", "MF-C"}
    hints_useful = 0
    hints_total = 0

    for r in results:
        page = r["page"]
        sig = r["signal"]
        predicted_a = sig.get("signals", {}).get("A", False)
        actual_a = page in ground_truth_pages

        if predicted_a and actual_a:
            tp += 1
        elif predicted_a and not actual_a:
            fp += 1
        elif not predicted_a and actual_a:
            fn += 1
        else:
            tn += 1

        # hints quality: check if mf_candidates look valid
        if predicted_a:
            mf_cands = (
                sig.get("hints", {}).get("A", {}).get("mf_candidates", [])
                if isinstance(sig.get("hints", {}).get("A"), dict)
                else []
            )
            hints_total += 1
            if any(any(c.startswith(p) for p in valid_mf_prefixes) for c in mf_cands):
                hints_useful += 1

    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    fn_rate = fn / (tp + fn) if (tp + fn) > 0 else 0.0  # false negative rate (miss rate)
    fp_rate = fp / (fp + tn) if (fp + tn) > 0 else 0.0  # false positive rate

    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "fn_rate": round(fn_rate, 3),  # 漏标率
        "fp_rate": round(fp_rate, 3),  # 误标率
        "hints_useful_pct": round(hints_useful / hints_total * 100, 1) if hints_total > 0 else 0.0,
    }

# ── Formatting ────────────────────────────────────────────────────────────────

def print_comparison_table(model_stats: dict[str, dict]) -> None:
    """Print a human-readable comparison table."""
    print("\n" + "=" * 80)
    print("  SIGNAL ROUTER — 三模型对比评测结果")
    print("=" * 80)

    # Per-book breakdown
    all_books = sorted({book for m in model_stats.values() for book in m["per_book"]})
    for book_id in all_books:
        book_cfg = next((b for b in SAMPLE_BOOKS if b["book_id"] == book_id), {})
        print(f"\n📚 {book_id} — {book_cfg.get('desc', '')}")
        print(f"{'Model':<25} {'Pages':>6} {'Time/pg':>8} {'Tokens':>8} {'Recall':>7} {'Prec':>7} {'F1':>6} {'FN%':>6} {'FP%':>6}")
        print("-" * 80)
        for model, stats in model_stats.items():
            bk = stats["per_book"].get(book_id, {})
            if not bk:
                continue
            acc = bk.get("accuracy", {})
            avg_time = bk.get("avg_time_s", 0)
            avg_tokens = bk.get("avg_tokens", 0)
            if "note" in acc:
                recall = prec = f1 = fn = fp = "N/A"
            else:
                recall = f"{acc.get('recall', 0)*100:.0f}%"
                prec = f"{acc.get('precision', 0)*100:.0f}%"
                f1 = f"{acc.get('f1', 0):.2f}"
                fn = f"{acc.get('fn_rate', 0)*100:.0f}%"
                fp = f"{acc.get('fp_rate', 0)*100:.0f}%"
            print(f"  {model:<23} {bk.get('n_pages', 0):>6} {avg_time:>7.2f}s {avg_tokens:>8.0f} {recall:>7} {prec:>7} {f1:>6} {fn:>6} {fp:>6}")

    # Overall summary
    print(f"\n{'─'*80}")
    print(f"  OVERALL SUMMARY")
    print(f"{'─'*80}")
    print(f"{'Model':<25} {'Pages':>6} {'Time/pg':>9} {'Tokens':>9} {'Recall':>8} {'Prec':>8} {'F1':>7} {'FN%':>7} {'FP%':>7}")
    print("-" * 80)
    for model, stats in model_stats.items():
        overall = stats.get("overall", {})
        acc = overall.get("accuracy", {})
        avg_time = overall.get("avg_time_s", 0)
        avg_tokens = overall.get("avg_tokens", 0)
        n_pages = overall.get("n_pages", 0)
        if "note" in acc:
            recall = prec = f1 = fn = fp = "N/A"
        else:
            recall = f"{acc.get('recall', 0)*100:.0f}%"
            prec = f"{acc.get('precision', 0)*100:.0f}%"
            f1 = f"{acc.get('f1', 0):.2f}"
            fn = f"{acc.get('fn_rate', 0)*100:.0f}%"
            fp = f"{acc.get('fp_rate', 0)*100:.0f}%"
        print(f"  {model:<23} {n_pages:>6} {avg_time:>8.2f}s {avg_tokens:>9.0f} {recall:>8} {prec:>8} {f1:>7} {fn:>7} {fp:>7}")
    print()


def pick_winner(model_stats: dict[str, dict]) -> str:
    """Simple scoring: recall * 0.5 + (1-fn_rate) * 0.3 + speed_score * 0.2"""
    scores = {}
    times = {m: s["overall"].get("avg_time_s", 999) for m, s in model_stats.items()}
    max_time = max(times.values()) or 1

    for model, stats in model_stats.items():
        acc = stats["overall"].get("accuracy", {})
        if "note" in acc:
            scores[model] = 0.0
            continue
        recall = acc.get("recall", 0)
        fn_rate = acc.get("fn_rate", 1)
        speed_score = 1 - (times[model] / max_time)
        scores[model] = recall * 0.5 + (1 - fn_rate) * 0.3 + speed_score * 0.2

    return max(scores, key=lambda m: scores[m]) if scores else ""


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="三模型 signal_router 对比评测")
    p.add_argument("--pages-per-book", type=int, default=10, help="每本书抽样页数（默认10）")
    p.add_argument("--concurrency", type=int, default=5, help="DashScope 并发数（默认5）")
    p.add_argument("--seed", type=int, default=42, help="随机种子（默认42）")
    p.add_argument("--output", default="", help="结果 JSON 保存路径（默认 output/signal_model_comparison.json）")
    p.add_argument("--models", nargs="*", default=None,
                   help="覆盖测试的模型列表（默认: qwen3.5-flash qwen-plus glm-4-flash）")
    p.add_argument("--verbose", action="store_true", help="显示每页详细结果")
    return p.parse_args()


async def main_async(args) -> None:
    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key:
        print("ERROR: DASHSCOPE_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    models = args.models or MODELS
    pages_per_book = args.pages_per_book

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    log = logging.getLogger("compare")

    # ── Load samples ──────────────────────────────────────────────────────────
    book_samples: dict[str, list[dict]] = {}
    book_ground_truth: dict[str, set[int]] = {}

    for book_cfg in SAMPLE_BOOKS:
        bid = book_cfg["book_id"]
        all_pages = load_pages(bid)
        if not all_pages:
            log.warning(f"Book {bid}: pages.json not found, skipping")
            continue
        sampled = sample_pages(all_pages, pages_per_book, seed=args.seed)
        book_samples[bid] = sampled
        gt = load_skill_a_ground_truth(bid) if book_cfg["has_skill_a"] else set()
        book_ground_truth[bid] = gt
        log.info(
            f"Book {bid}: {len(sampled)} pages sampled, "
            f"{len(gt)} skill_a ground truth pages"
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
            log.info(f"  → {bid} ({len(pages)} pages)")
            t_book_start = time.time()
            results = await run_model_on_book(pages, model, api_key, args.concurrency)
            t_book_elapsed = time.time() - t_book_start
            all_results[model][bid] = results
            log.info(f"     done: {t_book_elapsed:.1f}s total, "
                     f"{t_book_elapsed/len(pages):.2f}s/page")

            if args.verbose:
                for r in results:
                    sig = r["signal"].get("signals", {})
                    print(f"    p{r['page']:04d} A={sig.get('A',False)} B={sig.get('B',False)} "
                          f"C={sig.get('C',False)} D={sig.get('D',False)} "
                          f"t={r['elapsed_s']:.2f}s tok={r['usage'].get('total_tokens',0)}")

    # ── Compute stats ─────────────────────────────────────────────────────────
    model_stats: dict[str, dict] = {}

    for model in models:
        per_book = {}
        all_model_results = []

        for bid, results in all_results.get(model, {}).items():
            gt = book_ground_truth.get(bid, set())
            times = [r["elapsed_s"] for r in results]
            tokens = [r["usage"].get("total_tokens", 0) for r in results]
            acc = evaluate_skill_a(results, gt)

            per_book[bid] = {
                "n_pages": len(results),
                "avg_time_s": round(sum(times) / len(times), 3) if times else 0,
                "total_time_s": round(sum(times), 2),
                "avg_tokens": round(sum(tokens) / len(tokens)) if tokens else 0,
                "total_tokens": sum(tokens),
                "accuracy": acc,
            }
            all_model_results.extend(results)

        # Aggregate overall (across books with ground truth)
        gt_results = [
            r for bid, results in all_results.get(model, {}).items()
            for r in results
            if book_ground_truth.get(bid)
        ]
        all_gt_pages = set().union(*[book_ground_truth[bid] for bid in all_results.get(model, {}) if book_ground_truth.get(bid)])

        overall_times = [r["elapsed_s"] for r in all_model_results]
        overall_tokens = [r["usage"].get("total_tokens", 0) for r in all_model_results]

        model_stats[model] = {
            "model": model,
            "per_book": per_book,
            "overall": {
                "n_pages": len(all_model_results),
                "avg_time_s": round(sum(overall_times) / len(overall_times), 3) if overall_times else 0,
                "total_time_s": round(sum(overall_times), 2),
                "avg_tokens": round(sum(overall_tokens) / len(overall_tokens)) if overall_tokens else 0,
                "total_tokens": sum(overall_tokens),
                "accuracy": evaluate_skill_a(gt_results, all_gt_pages) if gt_results else {"note": "no_ground_truth"},
            },
        }

    # ── Print table ───────────────────────────────────────────────────────────
    print_comparison_table(model_stats)

    winner = pick_winner(model_stats)
    if winner:
        print(f"  🏆 推荐模型（综合评分）: {winner}")
        print()

    # ── Save JSON ─────────────────────────────────────────────────────────────
    output_path = Path(args.output) if args.output else OUTPUT_ROOT / "signal_model_comparison.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    comparison_output = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pages_per_book": pages_per_book,
            "seed": args.seed,
            "concurrency": args.concurrency,
            "models": models,
            "books": [b["book_id"] for b in SAMPLE_BOOKS],
        },
        "model_stats": model_stats,
        "raw_results": {
            model: {
                bid: results
                for bid, results in book_results.items()
            }
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
