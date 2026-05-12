#!/usr/bin/env python3
"""P2-Ic3: Import 39,888 tagged L0 atoms to CKG_L0_TMP_Principle + TAGGED_BY_PHN edges.

Avoid clashing with existing 146 P1-33 prototype L0 nodes (CKG_L0_Principle).
"""
import csv
import json
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
OUT_DIR = ROOT / "output/l2b/etl"

l0_rows = []
l0_phn_rows = []
seen_atom_ids = set()

with open(ROOT / "output/phase1/l0_phn_routing_v3.jsonl") as f:
    for line in f:
        try:
            r = json.loads(line)
        except: continue
        # Use source_chunk_id + book as composite id
        book = r.get("_book_id", "unknown")
        chunk = r.get("source_chunk_id", "")
        atom_id = f"{book}__{chunk}"
        if atom_id in seen_atom_ids: continue
        seen_atom_ids.add(atom_id)
        tags = r.get("phenomenon_tags") or []
        if not tags: continue
        l0_rows.append({
            "atom_id": atom_id,
            "scientific_statement": (r.get("scientific_statement") or "")[:500],
            "causal_chain_text": (r.get("causal_chain_text") or "")[:300],
            "domain": r.get("domain") or "",
            "confidence": r.get("confidence") or 0.0,
            "book_id": book,
            "n_phn": len(tags),
        })
        scores = r.get("phn_scores", {})
        for tag in tags:
            l0_phn_rows.append({
                "atom_id": atom_id,
                "phn_id": tag,
                "score": scores.get(tag, 0.5) if isinstance(scores, dict) else 0.5,
            })

# Write CSVs (atomic)
def write_csv(name, rows, fields):
    p = OUT_DIR / name
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows: w.writerow(r)
    tmp.rename(p)
    print(f"  ✅ {name}: {len(rows):,} rows")

write_csv("l0_tmp_nodes.csv", l0_rows, ["atom_id","scientific_statement","causal_chain_text","domain","confidence","book_id","n_phn"])
write_csv("l0_tmp_phn_edges.csv", l0_phn_rows, ["atom_id", "phn_id", "score"])
print(f"\n=== Summary ===")
print(f"L0 TMP atoms: {len(l0_rows):,}")
print(f"L0 → PHN edges: {len(l0_phn_rows):,}")
