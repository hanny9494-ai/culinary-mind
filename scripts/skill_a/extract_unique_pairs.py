#!/usr/bin/env python3
"""P1-21c-D Step 1: Extract unique (formula_id, parameter_name) pairs from 94 books × skill_a/results.jsonl"""
import json
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path("/Users/jeff/culinary-mind/output")
TARGET = Path("/Users/jeff/culinary-mind/output/skill_a/unique_pairs.jsonl")

def main():
    pairs = defaultdict(lambda: {"occurrence_count": 0, "sample_value": None, "sample_unit": None, "sample_book": None, "sample_page": None})
    total_records = 0
    filtered = 0
    books_seen = set()

    for results_path in sorted(OUT_DIR.glob("*/skill_a/results.jsonl")):
        book_name = results_path.parents[1].name
        books_seen.add(book_name)
        with open(results_path, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get("_filtered"):
                    filtered += 1
                    continue
                fid = r.get("formula_id")
                pn = r.get("parameter_name")
                if not (fid and pn):
                    continue
                pn = pn.strip()
                if not pn:
                    continue
                total_records += 1
                key = (fid, pn)
                entry = pairs[key]
                entry["occurrence_count"] += 1
                if entry["sample_value"] is None and r.get("value") is not None:
                    entry["sample_value"] = r.get("value")
                    entry["sample_unit"] = r.get("unit")
                    entry["sample_book"] = book_name
                    entry["sample_page"] = r.get("_page") or r.get("source", {}).get("page")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as f:
        for (fid, pn), meta in sorted(pairs.items()):
            f.write(json.dumps({
                "formula_id": fid,
                "parameter_name": pn,
                **meta,
            }, ensure_ascii=False) + "\n")

    # Per-MF distribution
    by_mf = defaultdict(int)
    for (fid, pn) in pairs:
        by_mf[fid] += 1

    print(f"✅ Books processed: {len(books_seen)}")
    print(f"✅ Total non-filtered records: {total_records:,}")
    print(f"   (filtered records skipped: {filtered:,})")
    print(f"✅ Unique (formula_id, parameter_name) pairs: {len(pairs):,}")
    print(f"✅ Output: {TARGET}")
    print()
    print("Per-MF unique-name distribution:")
    for mf in sorted(by_mf):
        print(f"  {mf}: {by_mf[mf]:>6}")

if __name__ == "__main__":
    main()
