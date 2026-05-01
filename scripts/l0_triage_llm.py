#!/usr/bin/env python3
"""
scripts/l0_triage_llm.py
P1-10 Phase-2 LLM classifier — refines records the rule layer left as
`_review` or `_unclassified`. Uses local Ollama qwen3.5:9b.

Spec: raw/architect/028-l0-triage-final-v2-20260426.md (Phase 2).

Output policy:
  • Records the rules already labelled (A_phn / _adjacent / _l1_candidate /
    _l2a_candidate) pass through untouched.
  • Records labelled `_review` or `_unclassified` are sent to qwen3.5:9b
    with the prompt below; we update `triage_label` to one of A_l0 /
    B_l1 / C_l2a / D_adjacent / _review (low-confidence override).

Run:
  /Users/jeff/miniforge3/bin/python3 scripts/l0_triage_llm.py \\
      --input  output/phase1/l0_phn_routing_v2_triaged.jsonl \\
      --output output/phase1/l0_phn_routing_v2_llm.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx
from tqdm import tqdm


OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL      = "qwen3.5:9b"
TIMEOUT    = 120

# Verbatim prompt template from architect 028 §3 Phase 2.
PROMPT_TEMPLATE = """任务：判断下列食品科学语句最适合归入哪一类。

A. 食物科学原理（L0）
- 存在加工或环境触发，且在解释食物性质如何变化
- 结果落在食物本身：质地、风味、香气、色泽、结构、稳定性、安全性
- 包括直接感官体验（味觉、嗅觉、触觉）
- 即使提到设备，只要重点在解释食物变化机制，仍归 A

B. 设备参数（L1）
- 描述设备/工具的规格、部件、操作、校准、控制或性能
- 没有在解释食物性质变化机制

C. 食材属性（L2a）
- 陈述食材/原料的静态属性、成分、营养、品种、理化指标
- 没有明确的加工触发和食物变化过程

D. 外围知识（_adjacent）
- 人体医学、生态、法规、公共卫生等非食物加工内容
- 不直接进入烹饪加工推理链

判定优先级：A > B > C > D
若同时含设备信息和食物变化机制 → A
若同时含食材属性和加工行为后果 → A

示例：
- "加热使蛋白质变性并凝固。" → A
- "立式搅拌机常配 1/4 英寸和 1/8 英寸模具。" → B
- "火鸡通常比其他家禽脂肪含量更低。" → C
- "长期抗生素滥用会增加耐药风险。" → D
- "对流烤箱通过提高空气流速加快表面脱水和褐变。" → A（设备+机制→A优先）
- "低果胶水果即使加糖也较难形成稳定凝胶。" → A（属性驱动加工→A优先）

语句：{statement}

先一句话说明理由，然后输出标签（A/B/C/D）。"""

# Phrases that signal the model is hedging — flag those for human review
# regardless of the final letter it picked.
LOW_CONFIDENCE_SIGNALS: tuple[str, ...] = (
    "可能是", "也可能", "也许", "或许", "不确定", "难以判断", "倾向于",
    "but could be", "ambiguous", "uncertain", "either", "borderline",
)

LABEL_RE = re.compile(r"\b([ABCD])\b")
ARROW_LABEL_RE = re.compile(r"→\s*([ABCD])")
LABEL_TO_TRIAGE = {
    "A": "A_l0",
    "B": "B_l1",
    "C": "C_l2a",
    "D": "D_adjacent",
}

TRIAGE_VERSION = 2  # Phase-2 enrichment carries version 2.


# ── Ollama ──────────────────────────────────────────────────────────────────

def call_qwen(client: httpx.Client, statement: str,
              retries: int = 3, backoff: tuple[int, ...] = (3, 9, 18)) -> str:
    payload = {
        "model":  MODEL,
        "prompt": PROMPT_TEMPLATE.format(statement=statement),
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 256},
    }
    last_err = ""
    for attempt in range(retries):
        try:
            resp = client.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json().get("response", "").strip()
        except Exception as e:   # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            if attempt < retries - 1:
                time.sleep(backoff[min(attempt, len(backoff) - 1)])
    raise RuntimeError(f"qwen3.5:9b failed after {retries} tries: {last_err}")


# ── Reasoning parser ────────────────────────────────────────────────────────

def parse_label(text: str) -> str | None:
    """Extract A/B/C/D from the model output. Prefer arrow form (' → A')
    because the few-shot examples in the prompt use it."""
    m = ARROW_LABEL_RE.search(text)
    if m:
        return m.group(1)
    # Fall back to any standalone capital letter at end of text
    m = LABEL_RE.findall(text)
    if not m:
        return None
    # Prefer the LAST occurrence — the prompt says reason first, label last.
    return m[-1]


def is_low_confidence(text: str) -> bool:
    low = text.lower()
    return any(sig in text or sig in low for sig in LOW_CONFIDENCE_SIGNALS)


# ── Pipeline ────────────────────────────────────────────────────────────────

def needs_llm(rec: dict) -> bool:
    """Phase-2 only re-classifies records the rule layer left ambiguous."""
    return rec.get("triage_label") in ("_review", "_unclassified")


def _statement_for(rec: dict) -> str:
    stmt  = (rec.get("scientific_statement") or "").strip()
    chain = (rec.get("causal_chain_text") or "").strip()
    if stmt and chain and stmt != chain:
        return f"{stmt}\n（因果链：{chain}）"
    return stmt or chain


def annotate(rec: dict, response: str) -> dict:
    out = dict(rec)
    label = parse_label(response)
    out["triage_llm_response"] = response[:600]
    out["triage_version"] = TRIAGE_VERSION
    if label is None:
        out["triage_label"] = "_review"
        out["triage_rule"]  = "llm_no_label"
        return out
    if is_low_confidence(response):
        out["triage_label"] = "_review"
        out["triage_rule"]  = "llm_low_confidence"
        out["triage_llm_initial_label"] = LABEL_TO_TRIAGE[label]
        return out
    out["triage_label"] = LABEL_TO_TRIAGE[label]
    out["triage_rule"]  = "llm_classified"
    return out


# ── CLI ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="P1-10 Phase-2 LLM triage")
    p.add_argument("--input",  required=True, type=Path,
                   help="Input JSONL with rule-layer triage_label set")
    p.add_argument("--output", required=True, type=Path,
                   help="Output JSONL with LLM-refined triage_label")
    p.add_argument("--limit",  type=int, default=None,
                   help="Smoke-test cap on records to send to LLM")
    p.add_argument("--resume", action="store_true",
                   help="If output exists, skip records already present "
                        "(matched by source_chunk_id + scientific_statement hash)")
    return p.parse_args()


def _record_key(rec: dict) -> str:
    return (
        f"{rec.get('_book_id','')}|{rec.get('source_chunk_id','')}|"
        f"{(rec.get('scientific_statement') or '')[:80]}"
    )


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    if args.resume and args.output.exists():
        with open(args.output, encoding="utf-8") as f:
            for line in f:
                try:
                    seen.add(_record_key(json.loads(line)))
                except Exception:
                    pass
        print(f"[llm-triage] resume: skipping {len(seen)} already-processed records",
              flush=True)

    counts: Counter[str] = Counter()
    sent = 0
    passed = 0

    with httpx.Client(trust_env=False) as client, \
         open(args.input, encoding="utf-8") as fin, \
         open(args.output, "a" if args.resume else "w", encoding="utf-8") as fout:

        records = []
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            records.append(rec)

        for rec in tqdm(records, desc="triage_llm"):
            key = _record_key(rec)
            if key in seen:
                continue
            if not needs_llm(rec):
                # Pass-through: already labelled by rules / phn.
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                passed += 1
                counts[rec.get("triage_label", "?")] += 1
                continue

            statement = _statement_for(rec)
            if not statement:
                # No text → keep as _unclassified.
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                counts[rec.get("triage_label", "?")] += 1
                continue

            try:
                resp = call_qwen(client, statement)
            except Exception as e:   # noqa: BLE001
                rec["triage_llm_error"] = str(e)
                rec["triage_label"] = "_review"
                rec["triage_rule"]  = "llm_error"
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                counts["_review"] += 1
                continue

            ann = annotate(rec, resp)
            fout.write(json.dumps(ann, ensure_ascii=False) + "\n")
            counts[ann["triage_label"]] += 1
            sent += 1
            if (sent % 50) == 0:
                fout.flush()
            if args.limit is not None and sent >= args.limit:
                break

    total = sum(counts.values())
    print(f"\n── L0 Triage Phase 2 (LLM) ──")
    print(f"  records sent to LLM: {sent}")
    print(f"  records pass-through:{passed}")
    print(f"  total written:       {total}")
    print(f"\n  triage_label distribution:")
    for label, c in counts.most_common():
        pct = 100.0 * c / total if total else 0
        print(f"    {label:<20} {c:>6} ({pct:.2f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
