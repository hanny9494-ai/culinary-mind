#!/usr/bin/env python3
"""P1-21c-D Step 3: Aggregate codex_raw/*.json → param_ontology_map.json + needs_review + stats."""
import json
import yaml
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
RAW_DIR = ROOT / "output/skill_a/codex_raw"
BOUNDS_FILE = ROOT / "config/solver_bounds.yaml"
MAP_FILE = ROOT / "output/skill_a/param_ontology_map.json"
REVIEW_FILE = ROOT / "output/skill_a/param_ontology_needs_review.jsonl"
STATS_FILE = ROOT / "output/skill_a/param_ontology_stats.yaml"

CONF_AUTO = 0.85

def main():
    bounds = yaml.safe_load(open(BOUNDS_FILE))
    valid_fields_by_mf = {}
    for mf_id, mf in bounds["solvers"].items():
        valid_fields_by_mf[mf_id] = set(i["name"] for i in mf.get("inputs", []))
        valid_fields_by_mf[mf_id].add("no_match")

    # Load all batches
    mappings = defaultdict(dict)  # mf_id → {param_name: mapping}
    needs_review = []
    invalid_field = []
    total_pairs = 0
    by_mf_counts = defaultdict(lambda: {"total": 0, "auto": 0, "review": 0, "no_match": 0, "invalid": 0})
    conf_buckets = Counter()
    canonical_field_freq = defaultdict(Counter)  # mf_id → Counter(canonical_field)

    batch_files = sorted(RAW_DIR.glob("*.json"))
    batch_files = [f for f in batch_files if not f.name.endswith(".error.json")]
    print(f"Loading {len(batch_files)} batch files...")

    for bf in batch_files:
        data = json.loads(bf.read_text())
        mf_id = data["mf_id"]
        valid = valid_fields_by_mf[mf_id]
        input_pairs = data["input_pairs"]
        out_mappings = data["raw_output"]["mappings"]

        for i, inp in enumerate(input_pairs):
            if i >= len(out_mappings):
                # Truncated output — mark as needs_review
                needs_review.append({
                    "formula_id": mf_id,
                    "parameter_name": inp["parameter_name"],
                    "reason_no_output": "batch output truncated",
                    "occurrence_count": inp.get("occurrence_count", 0),
                    "sample_value": inp.get("sample_value"),
                    "sample_unit": inp.get("sample_unit"),
                })
                by_mf_counts[mf_id]["total"] += 1
                by_mf_counts[mf_id]["review"] += 1
                continue

            m = out_mappings[i]
            cf = m.get("canonical_field", "no_match")
            conf = float(m.get("confidence", 0))
            total_pairs += 1
            by_mf_counts[mf_id]["total"] += 1
            canonical_field_freq[mf_id][cf] += 1

            # Validate canonical_field
            if cf not in valid:
                invalid_field.append({
                    "formula_id": mf_id,
                    "parameter_name": inp["parameter_name"],
                    "llm_field": cf,
                    "valid_fields": sorted(valid),
                })
                by_mf_counts[mf_id]["invalid"] += 1
                # treat as needs_review
                needs_review.append({
                    "formula_id": mf_id,
                    "parameter_name": inp["parameter_name"],
                    "llm_canonical_field": cf,
                    "confidence": conf,
                    "reason_invalid": f"canonical_field '{cf}' not in {mf_id} standard list",
                    "alternatives": m.get("alternatives", []),
                    "occurrence_count": inp.get("occurrence_count", 0),
                    "sample_value": inp.get("sample_value"),
                    "sample_unit": inp.get("sample_unit"),
                })
                continue

            entry = {
                "canonical_field": cf,
                "confidence": conf,
                "alternatives": m.get("alternatives", []),
                "reason": m.get("reason", ""),
                "unit_hint": m.get("unit_hint"),
                "occurrence_count": inp.get("occurrence_count", 0),
                "sample_value": inp.get("sample_value"),
                "sample_unit": inp.get("sample_unit"),
            }

            # Bucket confidence
            if conf >= 0.85: conf_buckets[">=0.85"] += 1
            elif conf >= 0.7: conf_buckets["0.7-0.85"] += 1
            elif conf >= 0.5: conf_buckets["0.5-0.7"] += 1
            else: conf_buckets["<0.5"] += 1

            if cf == "no_match":
                by_mf_counts[mf_id]["no_match"] += 1
                # Still write to map as no_match (informational)
                mappings[mf_id][inp["parameter_name"]] = entry
            elif conf >= CONF_AUTO:
                by_mf_counts[mf_id]["auto"] += 1
                mappings[mf_id][inp["parameter_name"]] = entry
            else:
                by_mf_counts[mf_id]["review"] += 1
                needs_review.append({
                    "formula_id": mf_id,
                    "parameter_name": inp["parameter_name"],
                    "llm_canonical_field": cf,
                    "confidence": conf,
                    "alternatives": m.get("alternatives", []),
                    "reason": m.get("reason", ""),
                    "unit_hint": m.get("unit_hint"),
                    "occurrence_count": inp.get("occurrence_count", 0),
                    "sample_value": inp.get("sample_value"),
                    "sample_unit": inp.get("sample_unit"),
                })

    # Write map
    out = {
        "version": "1.0",
        "generated_at": "2026-05-11",
        "source": "Codex CLI gpt-5.4 low reasoning, 30 pairs/batch × 10 parallel, 717 batches",
        "stats_summary": {
            "total_pairs_input": total_pairs,
            "auto_accepted": sum(c["auto"] for c in by_mf_counts.values()),
            "needs_review": len(needs_review),
            "no_match": sum(c["no_match"] for c in by_mf_counts.values()),
            "invalid_field": len(invalid_field),
            "conf_buckets": dict(conf_buckets),
        },
        "mappings": dict(mappings),
    }
    MAP_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"✅ Map: {MAP_FILE}")

    # Write needs_review
    with open(REVIEW_FILE, "w", encoding="utf-8") as f:
        for r in needs_review:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ Needs review: {REVIEW_FILE} ({len(needs_review)} rows)")

    # Compute coverage per MF (excluding no_match)
    coverage_table = {}
    for mf_id in sorted(by_mf_counts):
        c = by_mf_counts[mf_id]
        total = c["total"] or 1
        coverage_table[mf_id] = {
            "total_unique_names": c["total"],
            "auto_accepted": c["auto"],
            "needs_review": c["review"],
            "no_match": c["no_match"],
            "invalid_field": c["invalid"],
            "coverage_pct_strict": round(c["auto"] * 100 / total, 1),  # auto only
            "coverage_pct_inclusive": round((c["auto"] + c["no_match"]) * 100 / total, 1),  # auto + no_match (LLM had a definite answer)
            "top_canonical_fields": dict(canonical_field_freq[mf_id].most_common(5)),
        }

    stats = {
        "version": "1.0",
        "generated_at": "2026-05-11",
        "total_pairs": total_pairs,
        "auto_accepted_count": out["stats_summary"]["auto_accepted"],
        "needs_review_count": len(needs_review),
        "no_match_count": out["stats_summary"]["no_match"],
        "invalid_field_count": len(invalid_field),
        "auto_accept_pct": round(out["stats_summary"]["auto_accepted"] * 100 / total_pairs, 1),
        "decisive_pct": round((out["stats_summary"]["auto_accepted"] + out["stats_summary"]["no_match"]) * 100 / total_pairs, 1),
        "p1_exit_criteria": {
            "target": "skill_a_param_ontology_mapped ≥ 95%",
            "achieved": round(((total_pairs - len(needs_review) - len(invalid_field)) * 100 / total_pairs), 1),
            "pass": (total_pairs - len(needs_review) - len(invalid_field)) >= 0.95 * total_pairs,
        },
        "confidence_buckets": dict(conf_buckets),
        "by_mf": coverage_table,
    }
    STATS_FILE.write_text(yaml.safe_dump(stats, allow_unicode=True, sort_keys=False))
    print(f"✅ Stats: {STATS_FILE}")

    print()
    print("=== SUMMARY ===")
    print(f"Total pairs:          {total_pairs:>6,}")
    print(f"Auto-accepted (≥0.85): {out['stats_summary']['auto_accepted']:>6,} ({stats['auto_accept_pct']}%)")
    print(f"No-match (decisive):   {out['stats_summary']['no_match']:>6,}")
    print(f"Needs review (<0.85):  {len(needs_review):>6,}")
    print(f"Invalid field:         {len(invalid_field):>6,}")
    print(f"P1 Exit Criteria ≥95%: {'PASS ✅' if stats['p1_exit_criteria']['pass'] else 'FAIL ❌'} (achieved {stats['p1_exit_criteria']['achieved']}%)")
    print()
    print("Confidence buckets:", dict(conf_buckets))

if __name__ == "__main__":
    main()
