#!/usr/bin/env python3
"""P2-Sa1.2: Rule-based rescue of backlog records → new MF schema fields.

For each new MF schema field, define keyword/unit rules to map from
new_mf_candidates_v2.jsonl items.

Output:
  - Augment param_ontology_map_v2.json → param_ontology_map_v3.json
  - Re-emit MF value database with rescued records
"""
import json
import re
import yaml
from pathlib import Path
from collections import defaultdict

ROOT = Path("/Users/jeff/culinary-mind")
MAP_V2 = ROOT / "output/skill_a/param_ontology_map_v2.json"
NEW_MF_FILE = ROOT / "output/skill_a/new_mf_candidates_v2.jsonl"
MAP_V3 = ROOT / "output/skill_a/param_ontology_map_v3.json"

# Rule-based rescue: (target_mf, target_field, [label_patterns], [optional_unit_filter])
# Match if any pattern matches candidate_label
RULES = [
    # G1 一阶降解 → MF-T03.observed_k
    ("MF-T03", "observed_k", [
        r"first[ -]order.*degradation.*rate",
        r"first[ -]order.*kinetics.*rate",
        r"thermal degradation rate const",
        r"nutrient degradation rate",
        r"arrhenius response.*k",
        r"degradation rate const.*specified temp",
        r"reaction kinetics.*rate const",
        r"temperature[ -]specific reaction rate const",
        r"apparent reaction rate const",
        r"reaction/degradation rate const",
        r"\bk\(T\)",
        r"degradation kinetics.*rate const",
    ], None),
    # G1 一阶降解 → MF-T03.reaction_order (含 "reaction order" 字眼)
    ("MF-T03", "reaction_order", [
        r"\breaction[ -]order\b",
        r"nth[ -]order kinetics",
        r"order kinetics exponent",
    ], None),
    # G1 半衰期 → MF-T03.observed_k (转换: k = ln(2)/half_life，仍归 observed_k slot)
    ("MF-T03", "observed_k", [
        r"degradation.*half[ -]life",
        r"\bhalf[ -]life\b.*degradation",
        r"\bt½\b",
    ], None),
    # G2 辐照灭菌 → MF-K02.D_radiation_kGy
    ("MF-K02", "D_radiation_kGy", [
        r"radiation resistance",
        r"radiation dose",
        r"radiation[ -]induced",
        r"irradiation",
        r"gamma irradiation",
        r"\bD10\b",
    ], None),
    # G6 酶活最适 pH → MF-K01.pH_opt
    ("MF-K01", "pH_opt", [
        r"enzyme.*pH optimum",
        r"optimum pH",
        r"optimal pH",
    ], None),
    # G6 酶活最适温度 → MF-K01.T_opt
    ("MF-K01", "T_opt", [
        r"enzyme.*temperature optimum",
        r"optimum temperature.*enzyme",
        r"optimal temperature.*enzyme",
        r"enzyme activity.*optimum",
    ], None),
    # G11 等温吸湿热 → MF-M02.Q_iso
    ("MF-M02", "Q_iso", [
        r"isosteric heat",
        r"sorption.*binding energy",
        r"heat of sorption",
        r"adsorption enthalpy",
        r"\bQ_iso\b",
        r"\bQst\b",
        r"norrish.*water[ -]activity",
        r"moisture sorption.*binding",
    ], None),
    # G14 食品成分 → MF-T02.composition.salt/sugar/alcohol
    ("MF-T02", "composition.salt", [
        r"\bsalt content\b",
        r"NaCl content",
        r"sodium chloride content",
    ], None),
    ("MF-T02", "composition.sugar", [
        r"\bsugar content\b",
        r"sucrose content",
        r"glucose content.*compos",
        r"fructose content.*compos",
    ], None),
    ("MF-T02", "composition.alcohol", [
        r"\balcohol content\b",
        r"ethanol fraction",
        r"\bethanol content\b",
    ], None),
    # G17 pKa → MF-M04.pKa1/2/3
    ("MF-M04", "pKa1", [
        r"\bpKa1\b",
        r"first pKa",
        r"first dissociation",
        r"\bpK1\b",
    ], None),
    ("MF-M04", "pKa2", [
        r"\bpKa2\b",
        r"second pKa",
        r"second dissociation",
        r"\bpK2\b",
    ], None),
    ("MF-M04", "pKa3", [
        r"\bpKa3\b",
        r"third pKa",
        r"\bpK3\b",
    ], None),
    # G8 二阶反应 → MF-T03 (we don't have a dedicated 2nd-order field; flag as needs_review + new schema later)
    # not in current 6-MF schema extension
    # G28 比热多项式 → MF-T02.Cp (just goes to existing Cp slot at midpoint; better leave for now)
]

# Compile patterns
compiled_rules = [(mf, field, [re.compile(p, re.IGNORECASE) for p in patterns], unit_filter)
                  for mf, field, patterns, unit_filter in RULES]

def match_rule(label):
    for mf, field, pats, unit_filter in compiled_rules:
        if any(p.search(label) for p in pats):
            return (mf, field)
    return None

def main():
    # Load v2 mapping
    v2 = json.load(open(MAP_V2))
    mappings = v2["mappings"]

    # Build provenance lookup: which (mf, pn) entries are already in mappings
    already = set()
    for mf, params in mappings.items():
        for pn in params:
            already.add((mf, pn))

    # Load new_mf_candidates
    candidates = []
    with open(NEW_MF_FILE) as f:
        for line in f:
            candidates.append(json.loads(line))

    rescued = []
    skipped_already = 0
    no_match = 0

    for c in candidates:
        label = c["candidate_label"]
        pn = c["parameter_name"]
        m = match_rule(label)
        if not m:
            no_match += 1
            continue
        target_mf, target_field = m
        if (target_mf, pn) in already:
            skipped_already += 1
            continue
        # Add to mappings
        mappings.setdefault(target_mf, {})[pn] = {
            "canonical_field": target_field,
            "confidence": 0.85,  # rule-based, mark as 0.85 (auto-accepted floor)
            "source": "v3_rule_rescued",
            "original_mf": c["original_mf"],
            "candidate_label": label,
            "occurrence_count": c["occurrence_count"],
            "sample_value": c.get("sample_value"),
            "sample_unit": c.get("sample_unit"),
            "reason": f"Rule-based: candidate_label '{label[:50]}...' matched → {target_mf}.{target_field}",
        }
        already.add((target_mf, pn))
        rescued.append({
            "original_mf": c["original_mf"],
            "parameter_name": pn,
            "best_mf": target_mf,
            "canonical_field": target_field,
            "occurrence_count": c["occurrence_count"],
        })

    # Save v3
    v3 = {
        "version": "3.0",
        "generated_at": "2026-05-11",
        "source": "v1 within-MF + v2 cross-MF + v3 rule-based rescue to new schema fields",
        "stats_summary": v2.get("stats_summary", {}),
        "v3_rescued_pairs": len(rescued),
        "v3_rescued_records": sum(r["occurrence_count"] for r in rescued),
        "mappings": mappings,
    }
    MAP_V3.write_text(json.dumps(v3, ensure_ascii=False, indent=2))

    # Stats
    rescued_records = sum(r["occurrence_count"] for r in rescued)
    by_target = defaultdict(int)
    for r in rescued:
        by_target[f'{r["best_mf"]}.{r["canonical_field"]}'] += r["occurrence_count"]

    print(f"=== V3 Rule-based Rescue Results ===")
    print(f"Total candidates scanned: {len(candidates):,}")
    print(f"Rescued pairs: {len(rescued):,}")
    print(f"Rescued records: {rescued_records:,}")
    print(f"Already in map (skipped): {skipped_already:,}")
    print(f"No rule match: {no_match:,}")
    print()
    print("By target field (records):")
    for k, v in sorted(by_target.items(), key=lambda x: -x[1]):
        print(f"  {k:<32}: {v:>4}")

if __name__ == "__main__":
    main()
