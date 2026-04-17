#!/usr/bin/env python3
"""
scripts/skill_a_model_compare.py
Skill A 四模型推理能力对比评测

从 2 本书各抽 5 页（已有 Skill A 结果的页面），用 4 个模型分别跑 L0 参数提取，
以现有 Opus 结果为 ground truth，对比：
  - record 数量（每页提取多少条）
  - mother_formula 覆盖率（提取了哪些公式）
  - 参数完整性（value/unit/conditions 是否齐全）
  - confidence 分布
  - 有无 None formula（质量缺陷）
  - 速度（秒/页）
  - token 用量

Usage:
    python scripts/skill_a_model_compare.py
    python scripts/skill_a_model_compare.py --pages-per-book 8 --seed 123
    python scripts/skill_a_model_compare.py --output /tmp/result.json
"""

import json
import logging
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any

# ── Proxy bypass ──────────────────────────────────────────────────────────────
for k in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]:
    os.environ.pop(k, None)
os.environ.setdefault(
    "no_proxy",
    "localhost,127.0.0.1,dashscope.aliyuncs.com,api.aigocode.com",
)

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = REPO_ROOT / "output"

# ── Sample books ──────────────────────────────────────────────────────────────
SAMPLE_BOOKS = [
    {"book_id": "rao_engineering_properties", "desc": "工程教科书（公式密集）"},
    {"book_id": "koji_alchemy",               "desc": "科学+食谱混合"},
]

# ── Model configs ─────────────────────────────────────────────────────────────
AIGOCODE_ENDPOINT = "https://api.aigocode.com/v1/messages"
AIGOCODE_KEY = "sk-b818671338b5ffd17e17ee1c962f84058c81504131e64cecdd68779d8156aca1"
AIGOCODE_MODEL = "claude-opus-4-6"

DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
DASHSCOPE_MODEL = "qwen3.6-plus"

# 灵雅 — resolved at runtime from env
LINGYA_ENDPOINT_TPL = "{L0_API_ENDPOINT}/v1/chat/completions"
LINGYA_GPT_MODEL = "gpt-5.4"
LINGYA_GPT_MODEL_FALLBACK = "gpt-5.4-turbo"
LINGYA_GEM_MODEL = "gemini-3.1-pro"
LINGYA_GEM_MODEL_FALLBACK = "gemini-3.1-pro-preview"


def get_lingya_endpoint() -> str:
    base = os.environ.get("L0_API_ENDPOINT", "").rstrip("/")
    if not base:
        raise RuntimeError("L0_API_ENDPOINT not set")
    return f"{base}/v1/chat/completions"


def get_lingya_key() -> str:
    key = os.environ.get("L0_API_KEY", "")
    if not key:
        raise RuntimeError("L0_API_KEY not set")
    return key


# ── Skill A prompt (MUST match run_skill.py exactly) ─────────────────────────
SKILL_A_SYSTEM = """\
你是食品工程参数提取器。从给定页面中提取所有可量化的科学参数。
每个参数必须绑定到 28 个 MotherFormula 之一（MF-T01~T05, MF-K01~K05, MF-M01~M06, MF-R01~R07, MF-C01~C05）。

输出纯 JSON 数组（每个参数一个对象）。如果没有可提取的参数，输出 []。

提取目标：
- 表格中的数值（温度、时间、速率常数、活化能等）
- LaTeX 公式中的系数和指数
- 图表标注中的临界值
- 参数的适用条件（基质、pH、温度范围）

输出 schema（每个元素）:
{
  "mother_formula": "Arrhenius",
  "formula_id": "MF-T03",
  "parameter_name": "Ea",
  "value": 127000,
  "unit": "J/mol",
  "conditions": {"substrate": "...", "pH": 7.0, "temperature_range": "60-90°C"},
  "source": {"book": "...", "chapter": "...", "page": ..., "table": "..."},
  "confidence": "high",
  "notes": "..."
}

如果没有参数，输出 []。不要解释。"""


def build_user_msg(book_id: str, page_num: int, page_text: str) -> str:
    return f"Book: {book_id}\nPage: {page_num}\n\n{page_text[:4000]}"

# ── JSON helpers ──────────────────────────────────────────────────────────────

def extract_json(text: str) -> Any:
    """Extract JSON from LLM response (strips markdown fences, think blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    m2 = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", text)
    if m2:
        try:
            return json.loads(m2.group(1))
        except Exception:
            pass
    return None

# ── API callers (all serial, trust_env=False) ─────────────────────────────────

_RETRY_DELAYS = [2, 4, 8]


def call_anthropic_sse(
    endpoint: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float = 120,
    retries: int = 3,
    log: logging.Logger | None = None,
) -> tuple[str, dict]:
    """
    Anthropic SSE streaming call. Returns (text, usage_dict).
    Works for aigocode. Non-streaming drops content on some servers.
    """
    l = log or logging.getLogger(__name__)
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    body = {
        "model": model,
        "max_tokens": 8192,
        "stream": True,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    for attempt in range(1, retries + 1):
        try:
            chunks: list[str] = []
            usage: dict = {}
            with httpx.Client(trust_env=False, timeout=timeout, follow_redirects=False) as client:
                with client.stream("POST", endpoint, headers=headers, json=body) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            ev = json.loads(data_str)
                            etype = ev.get("type", "")
                            if etype == "content_block_delta":
                                delta = ev.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    chunks.append(delta["text"])
                            elif etype == "message_delta":
                                usage = ev.get("usage", {})
                            elif etype == "message_start":
                                usage = ev.get("message", {}).get("usage", {})
                        except Exception:
                            pass
            return "".join(chunks).strip(), usage
        except Exception as e:
            l.warning(f"  [aigocode] attempt {attempt}/{retries} failed: {e}")
            if attempt == retries:
                raise
            time.sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
    return "", {}


def call_openai_compat(
    endpoint: str,
    api_key: str,
    model: str,
    system: str,
    user: str,
    timeout: float = 120,
    retries: int = 3,
    log: logging.Logger | None = None,
    label: str = "openai",
) -> tuple[str, dict]:
    """
    OpenAI-compatible non-streaming call. Returns (text, usage_dict).
    Used for DashScope and 灵雅 OpenAI endpoint.
    """
    l = log or logging.getLogger(__name__)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        "temperature": 0,
        "max_tokens": 8192,
        "stream": False,
    }

    for attempt in range(1, retries + 1):
        try:
            with httpx.Client(trust_env=False, timeout=timeout, follow_redirects=False) as client:
                resp = client.post(endpoint, headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            usage = data.get("usage", {})
            return text, usage
        except Exception as e:
            l.warning(f"  [{label}] attempt {attempt}/{retries} failed: {e}")
            if attempt == retries:
                raise
            time.sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
    return "", {}


# ── Model dispatch ────────────────────────────────────────────────────────────

MODELS = [
    {
        "id": "claude-opus-4-6",
        "label": "Opus 4.6 (aigocode)",
        "provider": "aigocode",
    },
    {
        "id": DASHSCOPE_MODEL,
        "label": f"{DASHSCOPE_MODEL} (DashScope)",
        "provider": "dashscope",
    },
    {
        "id": LINGYA_GPT_MODEL,
        "label": f"{LINGYA_GPT_MODEL} (灵雅)",
        "provider": "lingya",
        "fallback": LINGYA_GPT_MODEL_FALLBACK,
    },
    {
        "id": LINGYA_GEM_MODEL,
        "label": f"{LINGYA_GEM_MODEL} (灵雅)",
        "provider": "lingya",
        "fallback": LINGYA_GEM_MODEL_FALLBACK,
    },
]


def call_model(
    model_cfg: dict,
    book_id: str,
    page_num: int,
    page_text: str,
    log: logging.Logger,
) -> tuple[list[dict], dict, float]:
    """
    Call one model for one page.
    Returns (records, usage, elapsed_s).
    records is a list of extracted parameter dicts (may be empty).
    """
    user = build_user_msg(book_id, page_num, page_text)
    provider = model_cfg["provider"]
    model_id = model_cfg["id"]
    t0 = time.time()
    raw_text = ""
    usage: dict = {}

    try:
        if provider == "aigocode":
            raw_text, usage = call_anthropic_sse(
                endpoint=AIGOCODE_ENDPOINT,
                api_key=AIGOCODE_KEY,
                model=model_id,
                system=SKILL_A_SYSTEM,
                user=user,
                log=log,
            )
        elif provider == "dashscope":
            api_key = os.environ.get("DASHSCOPE_API_KEY", "")
            if not api_key:
                raise RuntimeError("DASHSCOPE_API_KEY not set")
            raw_text, usage = call_openai_compat(
                endpoint=DASHSCOPE_URL,
                api_key=api_key,
                model=model_id,
                system=SKILL_A_SYSTEM,
                user=user,
                log=log,
                label="dashscope",
            )
        elif provider == "lingya":
            endpoint = get_lingya_endpoint()
            api_key = get_lingya_key()
            try:
                raw_text, usage = call_openai_compat(
                    endpoint=endpoint,
                    api_key=api_key,
                    model=model_id,
                    system=SKILL_A_SYSTEM,
                    user=user,
                    log=log,
                    label=f"lingya/{model_id}",
                )
            except Exception as primary_err:
                # Try fallback model name
                fallback = model_cfg.get("fallback")
                if fallback and fallback != model_id:
                    log.warning(f"  [{model_id}] primary failed ({primary_err}), trying fallback {fallback}")
                    raw_text, usage = call_openai_compat(
                        endpoint=endpoint,
                        api_key=api_key,
                        model=fallback,
                        system=SKILL_A_SYSTEM,
                        user=user,
                        log=log,
                        label=f"lingya/{fallback}",
                    )
                else:
                    raise
    except Exception as e:
        elapsed = time.time() - t0
        log.error(f"  [{model_id}] page {page_num} FAILED: {e}")
        return [], {"error": str(e)}, elapsed

    elapsed = time.time() - t0

    parsed = extract_json(raw_text)
    if parsed is None:
        log.warning(f"  [{model_id}] page {page_num}: could not parse JSON from: {raw_text[:100]}")
        return [], usage, elapsed

    if isinstance(parsed, list):
        records = parsed
    else:
        records = []

    return records, usage, elapsed

# ── Data loading ──────────────────────────────────────────────────────────────

def load_pages(book_id: str) -> dict[int, str]:
    """Return {page_num: text} map."""
    path = OUTPUT_ROOT / book_id / "pages.json"
    if not path.exists():
        return {}
    pages = json.loads(path.read_text())
    return {p["page"]: p.get("text", "") for p in pages}


def load_skill_a_results(book_id: str) -> dict[int, list[dict]]:
    """Return {page_num: [record, ...]} from skill_a/results.jsonl."""
    path = OUTPUT_ROOT / book_id / "skill_a" / "results.jsonl"
    if not path.exists():
        return {}
    by_page: dict[int, list[dict]] = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                pg = obj.get("_page")
                if pg is not None:
                    by_page.setdefault(int(pg), []).append(obj)
            except Exception:
                pass
    return by_page


def sample_pages_with_results(
    skill_a_by_page: dict[int, list[dict]],
    pages_map: dict[int, str],
    n: int,
    seed: int = 42,
) -> list[int]:
    """Sample n page numbers that have both skill_a results and non-empty text."""
    candidates = [
        pg for pg in skill_a_by_page
        if pages_map.get(pg, "").strip() and skill_a_by_page[pg]
    ]
    rng = random.Random(seed)
    return sorted(rng.sample(candidates, min(n, len(candidates))))

# ── Evaluation ────────────────────────────────────────────────────────────────

VALID_MF_PREFIXES = {"MF-T", "MF-K", "MF-M", "MF-R", "MF-C"}
VALID_CONFIDENCE = {"high", "medium", "low"}


def evaluate_records(
    records: list[dict],
    ground_truth: list[dict],
) -> dict:
    """
    Evaluate one model's output against ground truth records for one page.
    """
    gt_formulas = {r.get("mother_formula") for r in ground_truth if r.get("mother_formula")}
    pred_formulas = {r.get("mother_formula") for r in records if r.get("mother_formula")}

    # Completeness: fraction of records with value, unit, conditions all present
    def is_complete(rec: dict) -> bool:
        return (
            rec.get("value") is not None
            and bool(rec.get("unit"))
            and bool(rec.get("conditions"))
        )

    complete_count = sum(1 for r in records if is_complete(r))
    none_formula = sum(1 for r in records if not r.get("mother_formula") or r.get("mother_formula") == "None")
    invalid_formula_id = sum(
        1 for r in records
        if r.get("formula_id") and not any(r["formula_id"].startswith(p) for p in VALID_MF_PREFIXES)
    )

    conf_dist = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for r in records:
        conf = str(r.get("confidence", "")).lower()
        if conf in VALID_CONFIDENCE:
            conf_dist[conf] += 1
        else:
            conf_dist["unknown"] += 1

    # Formula coverage vs ground truth
    if gt_formulas:
        covered = len(pred_formulas & gt_formulas)
        coverage_pct = covered / len(gt_formulas) * 100
    else:
        coverage_pct = 0.0

    # Extra (hallucinated) formulas
    extra_formulas = pred_formulas - gt_formulas if gt_formulas else set()

    return {
        "n_records": len(records),
        "gt_n_records": len(ground_truth),
        "record_ratio": round(len(records) / len(ground_truth), 2) if ground_truth else None,
        "gt_formulas": sorted(gt_formulas),
        "pred_formulas": sorted(pred_formulas),
        "formula_coverage_pct": round(coverage_pct, 1),
        "extra_formulas": sorted(extra_formulas),
        "complete_count": complete_count,
        "complete_pct": round(complete_count / len(records) * 100, 1) if records else 0.0,
        "none_formula_count": none_formula,
        "invalid_formula_id_count": invalid_formula_id,
        "confidence_dist": conf_dist,
    }


def aggregate_book_stats(page_evals: list[dict]) -> dict:
    """Aggregate per-page evaluations for one book."""
    if not page_evals:
        return {}

    total_records = sum(e["n_records"] for e in page_evals)
    gt_records = sum(e["gt_n_records"] for e in page_evals)
    complete = sum(e["complete_count"] for e in page_evals)
    none_f = sum(e["none_formula_count"] for e in page_evals)
    cov_vals = [e["formula_coverage_pct"] for e in page_evals]
    conf_total = {"high": 0, "medium": 0, "low": 0, "unknown": 0}
    for e in page_evals:
        for k in conf_total:
            conf_total[k] += e["confidence_dist"].get(k, 0)

    return {
        "n_pages": len(page_evals),
        "total_records": total_records,
        "gt_total_records": gt_records,
        "avg_records_per_page": round(total_records / len(page_evals), 1),
        "gt_avg_records_per_page": round(gt_records / len(page_evals), 1),
        "avg_formula_coverage_pct": round(sum(cov_vals) / len(cov_vals), 1),
        "complete_pct": round(complete / total_records * 100, 1) if total_records else 0.0,
        "none_formula_count": none_f,
        "confidence_dist": conf_total,
    }

# ── Formatting ────────────────────────────────────────────────────────────────

def print_table(model_stats: dict[str, dict], books: list[dict]) -> None:
    print("\n" + "=" * 90)
    print("  SKILL A — 四模型推理能力对比（L0 公式参数提取）")
    print("=" * 90)

    for book_cfg in books:
        bid = book_cfg["book_id"]
        desc = book_cfg.get("desc", "")
        print(f"\n📚 {bid} — {desc}")
        hdr = (
            f"  {'Model':<28} {'Pages':>5} {'Rec/pg':>7} {'GT/pg':>6} "
            f"{'MF Cov%':>8} {'Cmplt%':>7} {'NullMF':>7} "
            f"{'Time/p':>7} {'Tokens':>8}"
        )
        print(hdr)
        print("  " + "-" * 85)
        for mcfg in MODELS:
            label = mcfg["label"]
            stats = model_stats.get(mcfg["id"], {})
            bk = stats.get("per_book", {}).get(bid, {})
            if not bk:
                print(f"  {label:<28} {'N/A':>5}")
                continue
            avg_t = stats.get("per_book_timing", {}).get(bid, {}).get("avg_time_s", 0)
            avg_tok = stats.get("per_book_timing", {}).get(bid, {}).get("avg_tokens", 0)
            row = (
                f"  {label:<28} "
                f"{bk.get('n_pages', 0):>5} "
                f"{bk.get('avg_records_per_page', 0):>7.1f} "
                f"{bk.get('gt_avg_records_per_page', 0):>6.1f} "
                f"{bk.get('avg_formula_coverage_pct', 0):>7.1f}% "
                f"{bk.get('complete_pct', 0):>6.1f}% "
                f"{bk.get('none_formula_count', 0):>7} "
                f"{avg_t:>6.2f}s "
                f"{avg_tok:>8.0f}"
            )
            print(row)

    print(f"\n{'='*90}")
    print("  OVERALL SUMMARY")
    print(f"{'='*90}")
    hdr = (
        f"  {'Model':<28} {'Pages':>5} {'Rec/pg':>7} {'GT/pg':>6} "
        f"{'MF Cov%':>8} {'Cmplt%':>7} {'NullMF':>7} "
        f"{'Time/p':>7} {'In-tok':>7} {'Out-tok':>8}"
    )
    print(hdr)
    print("  " + "-" * 88)
    for mcfg in MODELS:
        label = mcfg["label"]
        stats = model_stats.get(mcfg["id"], {})
        ov = stats.get("overall", {})
        if not ov:
            print(f"  {label:<28} {'N/A':>5}")
            continue
        avg_t = stats.get("overall_timing", {}).get("avg_time_s", 0)
        avg_in = stats.get("overall_timing", {}).get("avg_prompt_tokens", 0)
        avg_out = stats.get("overall_timing", {}).get("avg_completion_tokens", 0)
        row = (
            f"  {label:<28} "
            f"{ov.get('n_pages', 0):>5} "
            f"{ov.get('avg_records_per_page', 0):>7.1f} "
            f"{ov.get('gt_avg_records_per_page', 0):>6.1f} "
            f"{ov.get('avg_formula_coverage_pct', 0):>7.1f}% "
            f"{ov.get('complete_pct', 0):>6.1f}% "
            f"{ov.get('none_formula_count', 0):>7} "
            f"{avg_t:>6.2f}s "
            f"{avg_in:>7.0f} "
            f"{avg_out:>8.0f}"
        )
        print(row)
    print()

# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Skill A 四模型对比评测（串行）")
    p.add_argument("--pages-per-book", type=int, default=5, help="每本书抽样页数（默认5）")
    p.add_argument("--seed", type=int, default=42, help="随机种子（默认42）")
    p.add_argument("--output", default="", help="结果 JSON 路径（默认 output/skill_a_model_comparison.json）")
    p.add_argument("--skip-models", nargs="*", default=[], help="跳过指定 model id（调试用）")
    return p.parse_args()


def main():
    args = parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    log = logging.getLogger("skill_a_compare")

    # ── Load data ─────────────────────────────────────────────────────────────
    book_data: dict[str, dict] = {}
    active_books = []
    for book_cfg in SAMPLE_BOOKS:
        bid = book_cfg["book_id"]
        pages_map = load_pages(bid)
        skill_a_gt = load_skill_a_results(bid)
        if not pages_map:
            log.warning(f"Book {bid}: pages.json not found, skipping")
            continue
        if not skill_a_gt:
            log.warning(f"Book {bid}: no skill_a results, skipping")
            continue

        sampled_pages = sample_pages_with_results(skill_a_gt, pages_map, args.pages_per_book, args.seed)
        log.info(f"Book {bid}: sampled {len(sampled_pages)} pages from {len(skill_a_gt)} with skill_a results")
        book_data[bid] = {
            "pages_map": pages_map,
            "skill_a_gt": skill_a_gt,
            "sampled_pages": sampled_pages,
        }
        active_books.append(book_cfg)

    if not book_data:
        print("ERROR: No books with skill_a results found.", file=sys.stderr)
        sys.exit(1)

    # ── Run each model, each book, each page (serial) ─────────────────────────
    all_results: dict[str, dict[str, dict[int, dict]]] = {}  # model_id → book_id → page → result

    skip_models = set(args.skip_models)

    for mcfg in MODELS:
        model_id = mcfg["id"]
        label = mcfg["label"]

        if model_id in skip_models:
            log.info(f"\nSkipping {label} (--skip-models)")
            continue

        log.info(f"\n{'='*65}")
        log.info(f"Model: {label}")
        log.info(f"{'='*65}")
        all_results[model_id] = {}

        for book_cfg in active_books:
            bid = book_cfg["book_id"]
            desc = book_cfg["desc"]
            bdata = book_data[bid]
            pages_map = bdata["pages_map"]
            skill_a_gt = bdata["skill_a_gt"]
            sampled_pages = bdata["sampled_pages"]

            log.info(f"\n  📚 {bid} ({desc}) — {len(sampled_pages)} pages")
            all_results[model_id][bid] = {}

            for page_num in sampled_pages:
                page_text = pages_map.get(page_num, "")
                if not page_text.strip():
                    log.info(f"    page {page_num}: empty, skip")
                    continue

                log.info(f"    page {page_num}: calling {label}...")
                records, usage, elapsed = call_model(mcfg, bid, page_num, page_text, log)
                gt_records = skill_a_gt.get(page_num, [])
                eval_result = evaluate_records(records, gt_records)

                all_results[model_id][bid][page_num] = {
                    "records": records,
                    "gt_n_records": len(gt_records),
                    "eval": eval_result,
                    "elapsed_s": round(elapsed, 3),
                    "usage": usage,
                }

                log.info(
                    f"    page {page_num}: {len(records)} records (GT={len(gt_records)}) "
                    f"| cov={eval_result['formula_coverage_pct']:.0f}% "
                    f"| cmplt={eval_result['complete_pct']:.0f}% "
                    f"| t={elapsed:.2f}s"
                )

            log.info(f"  ✓ {bid} done for {label}")

    # ── Compute stats ─────────────────────────────────────────────────────────
    model_stats: dict[str, dict] = {}

    for model_id, book_results in all_results.items():
        per_book: dict[str, dict] = {}
        per_book_timing: dict[str, dict] = {}
        all_evals: list[dict] = []
        all_times: list[float] = []
        all_prompt_toks: list[int] = []
        all_completion_toks: list[int] = []

        for bid, page_results in book_results.items():
            evals = [v["eval"] for v in page_results.values()]
            times = [v["elapsed_s"] for v in page_results.values()]
            prompt_toks = [v["usage"].get("prompt_tokens", 0) for v in page_results.values()]
            completion_toks = [v["usage"].get("completion_tokens", 0) for v in page_results.values()]
            total_toks = [v["usage"].get("total_tokens", 0) or (prompt_toks[i] + completion_toks[i])
                          for i, v in enumerate(page_results.values())]

            per_book[bid] = aggregate_book_stats(evals)
            per_book_timing[bid] = {
                "avg_time_s": round(sum(times) / len(times), 3) if times else 0,
                "total_time_s": round(sum(times), 2),
                "avg_tokens": round(sum(total_toks) / len(total_toks)) if total_toks else 0,
                "avg_prompt_tokens": round(sum(prompt_toks) / len(prompt_toks)) if prompt_toks else 0,
                "avg_completion_tokens": round(sum(completion_toks) / len(completion_toks)) if completion_toks else 0,
            }
            all_evals.extend(evals)
            all_times.extend(times)
            all_prompt_toks.extend(prompt_toks)
            all_completion_toks.extend(completion_toks)

        overall = aggregate_book_stats(all_evals)
        overall_timing = {
            "avg_time_s": round(sum(all_times) / len(all_times), 3) if all_times else 0,
            "total_time_s": round(sum(all_times), 2),
            "avg_prompt_tokens": round(sum(all_prompt_toks) / len(all_prompt_toks)) if all_prompt_toks else 0,
            "avg_completion_tokens": round(sum(all_completion_toks) / len(all_completion_toks)) if all_completion_toks else 0,
        }

        model_stats[model_id] = {
            "model_id": model_id,
            "per_book": per_book,
            "per_book_timing": per_book_timing,
            "overall": overall,
            "overall_timing": overall_timing,
        }

    # ── Print table ───────────────────────────────────────────────────────────
    print_table(model_stats, active_books)

    # ── Recommendation ────────────────────────────────────────────────────────
    # Score: MF_cov*0.4 + complete_pct*0.3 + (1-null_ratio)*0.2 + speed_score*0.1
    scores = {}
    speeds = {mid: s["overall_timing"].get("avg_time_s", 999) for mid, s in model_stats.items()}
    max_speed = max(speeds.values()) or 1

    for mid, stats in model_stats.items():
        ov = stats.get("overall", {})
        if not ov:
            continue
        cov = ov.get("avg_formula_coverage_pct", 0) / 100
        cmplt = ov.get("complete_pct", 0) / 100
        total_rec = ov.get("total_records", 0)
        none_f = ov.get("none_formula_count", 0)
        null_ratio = none_f / total_rec if total_rec else 1
        speed_score = 1 - (speeds[mid] / max_speed)
        scores[mid] = cov * 0.4 + cmplt * 0.3 + (1 - null_ratio) * 0.2 + speed_score * 0.1

    if scores:
        winner = max(scores, key=lambda m: scores[m])
        winner_label = next((m["label"] for m in MODELS if m["id"] == winner), winner)
        print(f"  🏆 推荐模型（综合评分: MF覆盖×0.4 + 完整性×0.3 + 无NullMF×0.2 + 速度×0.1）: {winner_label}")
        print(f"     得分: { {mid: round(s, 3) for mid, s in sorted(scores.items(), key=lambda x: -x[1])} }")
        print()

    # ── Save JSON ─────────────────────────────────────────────────────────────
    output_path = (
        Path(args.output) if args.output else OUTPUT_ROOT / "skill_a_model_comparison.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    output_data = {
        "metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pages_per_book": args.pages_per_book,
            "seed": args.seed,
            "books": [b["book_id"] for b in active_books],
            "models": [m["id"] for m in MODELS],
        },
        "model_stats": model_stats,
        "raw_results": {
            model_id: {
                bid: {
                    str(pg): v
                    for pg, v in page_results.items()
                }
                for bid, page_results in book_results.items()
            }
            for model_id, book_results in all_results.items()
        },
        "scores": scores,
    }

    output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2))
    print(f"  Results saved → {output_path}")


if __name__ == "__main__":
    main()
