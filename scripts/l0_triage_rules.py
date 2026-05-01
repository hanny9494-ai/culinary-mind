#!/usr/bin/env python3
"""
scripts/l0_triage_rules.py
P1-10 Phase-1 rule prefilter for L0 records that PHN routing left
unmapped (`phenomenon_tags == []`).

Spec: raw/architect/028-l0-triage-final-v2-20260426.md (Phase 1) and
      raw/architect/030-p110-reroute-and-triage-plan-20260426.md (Step 2).

Triage layers, evaluated in priority order (A > D > B > C):

  Layer 1 — L0 Rescue
    Process-trigger word + (mechanism-word OR result-word) → "_review"
    These look like real L0 chains; defer to LLM/human, never silent-bucket.

  Layer 2 — D (_adjacent)
    Adjacent-knowledge signal AND no process-trigger → "_adjacent"
    Subtype refined by classify_adjacent(): medical / ecology /
    regulation / water_chemistry.

  Layer 3 — B (_l1_candidate)
    Equipment signal AND no process-trigger AND no mechanism-word →
    "_l1_candidate".

  Layer 4 — C (_l2a_candidate)
    Static-attribute signal AND no process-trigger → "_l2a_candidate".

  Default → "_unclassified" (passes to Phase 2 LLM classifier).

The keyword tables below are copied verbatim from architect 028 §3 Phase 1,
not re-invented. Adding new triggers requires editing the architect spec
first.

Run:
  /Users/jeff/miniforge3/bin/python3 scripts/l0_triage_rules.py \\
      --input  output/phase1/l0_phn_routing_v2.jsonl \\
      --output output/phase1/l0_phn_routing_v2_triaged.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable


# ── Keyword tables (verbatim from architect 028 §3 Phase 1) ──────────────────

# Layer 1: L0 Rescue triggers — anything matching these stays out of B/C/D
# rule buckets and is instead labelled "_review" for the LLM/human pass.
PROCESS_TRIGGER_TERMS: tuple[str, ...] = (
    "加热", "冷却", "冻结", "解冻", "烟熏", "发酵", "腌制", "干燥", "脱水",
    "搅打", "乳化", "加压", "减压", "储藏", "熟成", "煎", "烤", "蒸", "煮",
    "炸", "炖", "焯", "浸泡", "真空", "低温慢煮",
)
MECHANISM_TERMS: tuple[str, ...] = (
    "变性", "凝固", "糊化", "回生", "胶凝", "乳化", "氧化", "还原", "褐变",
    "美拉德", "焦糖化", "挥发", "溶解", "析出", "结晶", "熔融", "渗透", "扩散",
    "水合", "脱水", "明胶化", "嫩化", "硬化", "失活", "抑制", "促进", "降解",
    "杀菌", "灭活", "钝化",
)
RESULT_TERMS: tuple[str, ...] = (
    "质地", "风味", "香气", "色泽", "口感", "嫩度", "脆度", "保水性", "稳定性",
)

# Layer 2: B (L1 candidate) — equipment/parameter language with no
# process trigger and no mechanism word.
EQUIPMENT_TERMS: tuple[str, ...] = (
    "搅拌机", "绞肉机", "烤箱", "烤架", "温度计", "温度控制器", "模具", "附件",
    "探针", "传感器", "恒温器", "喷嘴", "刀片", "筛网", "密封圈", "风扇",
    "真空泵", "循环泵", "压面机", "脱水机", "封口机",
    "英寸", "厘米", "psi", "bar", "rpm", "kW", "BTU", "功率", "转速", "校准",
)
# 'mm' is dangerous to match as a substring in CJK text but architect listed
# it — keep as a separate word-bounded check.
EQUIPMENT_WORDS_REGEX = re.compile(r"\b(mm|psi|bar|rpm|kW|BTU)\b", re.IGNORECASE)

# Layer 3: C (L2a candidate) — static-attribute phrasing.
STATIC_ATTR_TERMS: tuple[str, ...] = (
    "含量为", "含量约", "脂肪含量", "蛋白质含量", "维生素", "矿物质",
    "品种", "产地", "Brix", "水活度", "灰分",
    "富含", "含有", "主要由", "组成", "典型为", "比例为", "天然含有",
)
STATIC_ATTR_REGEX = re.compile(r"属于.{0,4}科")   # "属于...科"

# Layer 4: D (_adjacent) — non-food-processing signals. Sub-typed below.
ADJACENT_MEDICAL_TERMS: tuple[str, ...] = (
    "患者", "临床", "感染", "免疫系统", "过敏", "哮喘", "癌症", "心血管",
    "代谢综合征", "肠道菌群", "口腔菌群", "耐药", "病理", "流行病学",
)
ADJACENT_ECOLOGY_TERMS: tuple[str, ...] = (
    "碳足迹", "温室气体", "农药残留",
)
ADJACENT_REGULATION_TERMS: tuple[str, ...] = (
    "FDA", "USDA", "食品法典",
)
ADJACENT_WATER_TERMS: tuple[str, ...] = (
    "饮用水法规",
)


# ── Detector helpers ─────────────────────────────────────────────────────────

def _contains_any(text: str, terms: Iterable[str]) -> bool:
    return any(t in text for t in terms)


def has_process_trigger(text: str) -> bool:
    return _contains_any(text, PROCESS_TRIGGER_TERMS)


def has_mechanism_word(text: str) -> bool:
    return _contains_any(text, MECHANISM_TERMS)


def has_result_word(text: str) -> bool:
    return _contains_any(text, RESULT_TERMS)


def has_equipment_signal(text: str) -> bool:
    if _contains_any(text, EQUIPMENT_TERMS):
        return True
    return bool(EQUIPMENT_WORDS_REGEX.search(text))


def has_static_attribute_signal(text: str) -> bool:
    if _contains_any(text, STATIC_ATTR_TERMS):
        return True
    return bool(STATIC_ATTR_REGEX.search(text))


def has_adjacent_signal(text: str) -> bool:
    return any(_contains_any(text, group) for group in (
        ADJACENT_MEDICAL_TERMS,
        ADJACENT_ECOLOGY_TERMS,
        ADJACENT_REGULATION_TERMS,
        ADJACENT_WATER_TERMS,
    ))


def classify_adjacent(text: str) -> str:
    """Return medical / ecology / regulation / water_chemistry."""
    if _contains_any(text, ADJACENT_WATER_TERMS):
        return "water_chemistry"
    if _contains_any(text, ADJACENT_MEDICAL_TERMS):
        return "medical"
    if _contains_any(text, ADJACENT_ECOLOGY_TERMS):
        return "ecology"
    if _contains_any(text, ADJACENT_REGULATION_TERMS):
        return "regulation"
    return "unknown"


# ── Triage ───────────────────────────────────────────────────────────────────

TRIAGE_VERSION = 1


def triage(text: str) -> tuple[str, str, dict]:
    """Return (triage_label, triage_rule, extras).

    triage_label: A_phn / _review / _adjacent / _l1_candidate /
                  _l2a_candidate / _unclassified
    extras: subtype info (e.g. adjacent_subtype) when relevant.
    """
    extras: dict = {}
    if not text:
        return "_unclassified", "empty_text", extras

    # Layer 1 — L0 rescue
    if has_process_trigger(text) and (has_mechanism_word(text) or has_result_word(text)):
        return "_review", "process_plus_mechanism_or_result", extras

    # Layer 2 — D (_adjacent)
    if has_adjacent_signal(text) and not has_process_trigger(text):
        extras["adjacent_subtype"] = classify_adjacent(text)
        return "_adjacent", "adjacent_no_process", extras

    # Layer 3 — B (_l1_candidate)
    if (has_equipment_signal(text)
        and not has_process_trigger(text)
        and not has_mechanism_word(text)):
        return "_l1_candidate", "equip_no_process_no_mechanism", extras

    # Layer 4 — C (_l2a_candidate)
    if has_static_attribute_signal(text) and not has_process_trigger(text):
        return "_l2a_candidate", "static_attribute_no_process", extras

    return "_unclassified", "default", extras


def _record_text(rec: dict) -> str:
    """The text the rule layer sees per L0 record."""
    stmt  = (rec.get("scientific_statement") or "").strip()
    chain = (rec.get("causal_chain_text") or "").strip()
    if stmt and chain and stmt != chain:
        return f"{stmt} {chain}"
    return stmt or chain


def annotate(rec: dict) -> dict:
    """Add triage_label / triage_rule / triage_version to an L0 record.

    PHN-mapped records are tagged A_phn (already routed, no triage needed).
    Empty-tag records run through the rule chain.
    """
    out = dict(rec)
    if rec.get("phenomenon_tags"):
        out["triage_label"]   = "A_phn"
        out["triage_rule"]    = "phn_tagged"
        out["triage_version"] = TRIAGE_VERSION
        return out

    label, rule, extras = triage(_record_text(rec))
    out["triage_label"]   = label
    out["triage_rule"]    = rule
    out["triage_version"] = TRIAGE_VERSION
    for k, v in extras.items():
        out[f"triage_{k}"] = v
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="P1-10 Phase-1 rule triage")
    p.add_argument("--input",  required=True, type=Path,
                   help="Input l0_phn_routing_v2.jsonl path")
    p.add_argument("--output", required=True, type=Path,
                   help="Output JSONL path (one record per line, augmented)")
    p.add_argument("--limit",  type=int, default=None,
                   help="Smoke-test cap on input lines")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.input.exists():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 1

    counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    n = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.input, encoding="utf-8") as fin, \
         open(args.output, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            ann = annotate(rec)
            fout.write(json.dumps(ann, ensure_ascii=False) + "\n")
            counts[ann["triage_label"]] += 1
            rule_counts[ann["triage_rule"]] += 1
            n += 1
            if args.limit is not None and n >= args.limit:
                break

    print(f"\n── L0 Triage Phase 1 (rules) ──")
    print(f"  records processed: {n}")
    print(f"  output:            {args.output}")
    print(f"\n  triage_label distribution:")
    for label, c in counts.most_common():
        print(f"    {label:<20} {c:>6} ({100.0 * c / n:.2f}%)")
    print(f"\n  triage_rule distribution (top 10):")
    for rule, c in rule_counts.most_common(10):
        print(f"    {rule:<35} {c:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
