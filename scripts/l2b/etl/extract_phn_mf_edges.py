#!/usr/bin/env python3
"""Build PHN nodes, MF nodes, L0→PHN edges, MF→PHN edges, Step→PHN edges."""
import csv
import json
import yaml
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path("/Users/jeff/culinary-mind")
OUT_DIR = ROOT / "output/l2b/etl"

# 1. PHN nodes from l0_phn_routing_v3.jsonl distinct tags
phns = Counter()
l0_to_phn = []  # (l0_atom_id, phn_id, score)
with open(ROOT / "output/phase1/l0_phn_routing_v3.jsonl") as f:
    for line in f:
        try:
            r = json.loads(line)
            tags = r.get("phenomenon_tags") or []
            atom_id = r.get("source_chunk_id") or r.get("_atom_id") or r.get("id")
            scores = r.get("phn_scores", {})
            for tag in tags:
                phns[tag] += 1
                if atom_id:
                    l0_to_phn.append({
                        "l0_atom_id": atom_id,
                        "phn_id": tag,
                        "score": scores.get(tag, 0.5) if isinstance(scores, dict) else 0.5,
                    })
        except: pass

# Write PHN nodes
phn_rows = []
for phn_id, count in phns.most_common():
    phn_rows.append({
        "phn_id": phn_id,
        "name_en": phn_id.replace("_", " ").title(),
        "l0_atom_count": count,
    })
with open(OUT_DIR / "phn_nodes.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["phn_id", "name_en", "l0_atom_count"])
    w.writeheader()
    [w.writerow(r) for r in phn_rows]
print(f"✅ PHN nodes: {len(phn_rows)}")

# 2. MF nodes from config/solver_bounds.yaml (40 MFs)
bounds = yaml.safe_load(open(ROOT / "config/solver_bounds.yaml"))
mf_rows = []
for mf_id, spec in sorted(bounds["solvers"].items()):
    if mf_id == "MF-T02": continue  # parent_only
    mf_rows.append({
        "mf_id": mf_id,
        "canonical_name": spec.get("canonical_name", ""),
        "n_inputs": len(spec.get("inputs", [])),
    })
with open(OUT_DIR / "mf_nodes.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["mf_id", "canonical_name", "n_inputs"])
    w.writeheader()
    [w.writerow(r) for r in mf_rows]
print(f"✅ MF nodes: {len(mf_rows)}")

# 3. L0→PHN edges from step_phn_rules backed by V3 routing
with open(OUT_DIR / "l0_phn_edges.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["l0_atom_id", "phn_id", "score"])
    w.writeheader()
    [w.writerow(r) for r in l0_to_phn]
print(f"✅ L0→PHN edges: {len(l0_to_phn)} (will only match existing L0 in Neo4j)")

# 4. MF→PHN edges (GOVERNS) from step_phn_rules
rules = yaml.safe_load(open(ROOT / "config/step_phn_rules.yaml"))["rules"]
mf_phn_pairs = set()
for rule in rules:
    phn = rule["triggers_phn"]
    for mf in rule.get("governed_by_mf", []):
        mf_phn_pairs.add((mf, phn))
mf_phn_rows = [{"mf_id": m, "phn_id": p} for m, p in sorted(mf_phn_pairs)]
with open(OUT_DIR / "mf_phn_edges.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["mf_id", "phn_id"])
    w.writeheader()
    [w.writerow(r) for r in mf_phn_rows]
print(f"✅ MF→PHN edges (GOVERNS_PHN): {len(mf_phn_rows)}")

# Print summary
print(f"\n=== Summary ===")
print(f"PHN nodes: {len(phn_rows)}")
print(f"MF nodes: {len(mf_rows)}")
print(f"L0→PHN edges: {len(l0_to_phn):,}")
print(f"MF→PHN edges: {len(mf_phn_rows)}")
