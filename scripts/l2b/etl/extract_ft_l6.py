#!/usr/bin/env python3
"""P2-Ft1 + P2-L6: Extract FT (Flavor Target) + L6 (Glossary) from Skill D output.

- 17,485 L6 glossary terms (term_zh/term_en/definition + l0_domains)
- 7,435 FT records (ft_id/aesthetic_word/matrix_type/substrate/target_states + l0_domains)

Output: output/l2b/etl/{ft_nodes,l6_nodes,ft_l0domain_edges,l6_l0domain_edges}.csv
"""
import csv
import json
from pathlib import Path
from collections import Counter

ROOT = Path("/Users/jeff/culinary-mind")
OUT_DIR = ROOT / "output/l2b/etl"

ft_rows = []
l6_rows = []
ft_domain_edges = []
l6_domain_edges = []
ft_seen = set()
l6_seen = set()

for p in ROOT.glob("output/*/skill_d/results.jsonl"):
    book = p.parents[1].name
    with open(p, encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except: continue
            if r.get("_filtered"): continue
            rtype = r.get("_type")
            if rtype == "glossary":
                term_en = (r.get("term_en") or "").strip()
                term_zh = (r.get("term_zh") or "").strip()
                if not (term_en or term_zh): continue
                l6_id = f"{book}__{term_en or term_zh}"[:200]
                if l6_id in l6_seen: continue
                l6_seen.add(l6_id)
                l6_rows.append({
                    "l6_id": l6_id,
                    "term_en": term_en,
                    "term_zh": term_zh,
                    "definition_en": (r.get("definition_en") or "")[:500],
                    "definition_zh": (r.get("definition_zh") or "")[:500],
                    "context": (r.get("context") or "")[:200],
                    "book_id": book,
                })
                for dom in r.get("l0_domains", []) or []:
                    l6_domain_edges.append({"l6_id": l6_id, "domain": dom})
            elif rtype == "flavor_target":
                ft_id = r.get("ft_id") or ""
                if not ft_id or ft_id in ft_seen: continue
                ft_seen.add(ft_id)
                target_states = r.get("target_states", {}) or {}
                ft_rows.append({
                    "ft_id": ft_id,
                    "aesthetic_word_zh": r.get("aesthetic_word") or "",
                    "aesthetic_word_en": r.get("aesthetic_word_en") or "",
                    "matrix_type": r.get("matrix_type") or "",
                    "substrate": r.get("substrate") or "",
                    "target_states_json": json.dumps(target_states, ensure_ascii=False)[:1000],
                    "book_id": book,
                })
                for dom in r.get("l0_domains", []) or []:
                    ft_domain_edges.append({"ft_id": ft_id, "domain": dom})

# Write CSVs
def w(name, rows, fields):
    p = OUT_DIR / name
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=fields)
        wr.writeheader()
        for r in rows: wr.writerow(r)
    tmp.rename(p)
    print(f"  ✅ {name}: {len(rows):,}")

w("l6_nodes.csv", l6_rows, ["l6_id","term_en","term_zh","definition_en","definition_zh","context","book_id"])
w("ft_nodes.csv", ft_rows, ["ft_id","aesthetic_word_zh","aesthetic_word_en","matrix_type","substrate","target_states_json","book_id"])
w("ft_l0domain_edges.csv", ft_domain_edges, ["ft_id","domain"])
w("l6_l0domain_edges.csv", l6_domain_edges, ["l6_id","domain"])

print(f"\n=== Summary ===")
print(f"L6 Glossary: {len(l6_rows):,}")
print(f"FT Targets: {len(ft_rows):,}")
print(f"FT→domain edges: {len(ft_domain_edges):,}")
print(f"L6→domain edges: {len(l6_domain_edges):,}")
