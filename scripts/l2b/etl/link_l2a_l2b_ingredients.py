#!/usr/bin/env python3
"""P2-Ic5: Match 22K L2b ingredient_slug ↔ 24K L2a canonical_id.

Strategy (matching priority):
1. Exact match: L2a.canonical_id == ingredient_slug
2. Exact match: any L2a.alias.lower() == item_raw.lower()
3. Exact match: L2a.display_name_en.lower() == item_raw.lower()
4. Fuzzy: ingredient_slug contains L2a.canonical_id as substring (e.g. "extra_virgin_olive_oil" → "olive_oil")
5. No match → flag as needs_review

Output: output/l2b/etl/l2a_l2b_match.csv (ingredient_slug, l2a_canonical_id, match_method, confidence)
"""
import csv
import json
import re
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
L2A_FILE = Path("/Users/jeff/culinary-mind/output/l2a/etl/final/nodes.csv")
L2B_FILE = ROOT / "output/l2b/etl/ingredients.csv"
OUT_FILE = ROOT / "output/l2b/etl/l2a_l2b_match.csv"


def parse_aliases(s):
    """Aliases stored as JSON list string."""
    if not s or s in ("[]", "null", "NULL"): return []
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return []


def normalize(s):
    return (s or "").lower().strip()


def main():
    # Load L2a
    l2a_by_canonical = {}
    alias_to_canonical = {}  # lowercased alias → canonical_id
    name_en_to_canonical = {}
    
    with open(L2A_FILE) as f:
        reader = csv.DictReader(f)
        for row in reader:
            cid = row["canonical_id"]
            name_en = row.get("display_name_en", "")
            name_zh = row.get("display_name_zh", "")
            aliases = parse_aliases(row.get("aliases", ""))
            
            l2a_by_canonical[cid] = {"name_en": name_en, "name_zh": name_zh, "aliases": aliases}
            if name_en:
                name_en_to_canonical[normalize(name_en)] = cid
            if name_zh:
                name_en_to_canonical[normalize(name_zh)] = cid  # share index for cn names too
            for alias in aliases:
                alias_to_canonical[normalize(alias)] = cid

    print(f"L2a loaded: {len(l2a_by_canonical):,} canonical_ids")
    print(f"L2a aliases indexed: {len(alias_to_canonical):,}")
    print(f"L2a name_en indexed: {len(name_en_to_canonical):,}")
    print()

    # Match L2b ingredients
    matches = []
    method_counts = {"canonical_id": 0, "alias_exact": 0, "name_en_exact": 0, "substring": 0, "no_match": 0}
    
    with open(L2B_FILE) as f:
        for row in csv.DictReader(f):
            slug = row["ingredient_slug"]
            item = row["item_raw"]
            match = None
            method = "no_match"
            confidence = 0.0
            
            # 1. Exact canonical_id match
            if slug in l2a_by_canonical:
                match = slug
                method = "canonical_id"
                confidence = 1.00
            # 2. Alias exact (lowercased)
            elif normalize(item) in alias_to_canonical:
                match = alias_to_canonical[normalize(item)]
                method = "alias_exact"
                confidence = 0.95
            # 3. name_en exact (lowercased)
            elif normalize(item) in name_en_to_canonical:
                match = name_en_to_canonical[normalize(item)]
                method = "name_en_exact"
                confidence = 0.95
            # 4. Substring: slug contains canonical_id as token (e.g. "extra_virgin_olive_oil" → "olive_oil")
            else:
                # Try common patterns by suffix match
                slug_parts = slug.split("_")
                for n in range(2, min(len(slug_parts), 4) + 1):
                    # Try last n tokens as a canonical_id candidate
                    candidate = "_".join(slug_parts[-n:])
                    if candidate in l2a_by_canonical:
                        match = candidate
                        method = "substring"
                        confidence = 0.75
                        break

            method_counts[method] = method_counts.get(method, 0) + 1
            if match:
                matches.append({
                    "ingredient_slug": slug,
                    "l2a_canonical_id": match,
                    "match_method": method,
                    "confidence": confidence,
                })

    # Write
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ingredient_slug", "l2a_canonical_id", "match_method", "confidence"])
        w.writeheader()
        for m in matches: w.writerow(m)

    total = sum(method_counts.values())
    print(f"=== Matching results ===")
    print(f"Total L2b slugs: {total:,}")
    matched = total - method_counts["no_match"]
    print(f"Matched: {matched:,} ({matched*100//total}%)")
    print(f"No match: {method_counts['no_match']:,}")
    print()
    print(f"By method:")
    for m, n in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"  {m:<20}: {n:>6}")
    print()
    print(f"✅ {OUT_FILE}")

if __name__ == "__main__":
    main()
