#!/usr/bin/env python3
"""P2-Sa2 Phase 1: Automated outlier cleaning of MF value database.

Cleans:
1. Negative D_eff (log scale errors)
2. Metal-range conductivity / density wrongly assigned to food
3. Out-of-physical-bound values

Output:
- output/skill_a/mf_parameter_value_database_clean.yaml
- output/skill_a/p2_sa2_outlier_report.yaml
"""
import json
import yaml
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
DB_FILE = ROOT / "output/skill_a/mf_parameter_value_database.yaml"
CLEAN_FILE = ROOT / "output/skill_a/mf_parameter_value_database_clean.yaml"
REPORT_FILE = ROOT / "output/skill_a/p2_sa2_outlier_report.yaml"
RECORDS_FILE = ROOT / "output/skill_a/mf_parameter_records.jsonl"
CLEAN_RECORDS_FILE = ROOT / "output/skill_a/mf_parameter_records_clean.jsonl"

# Physical sanity rules per (mf, field)
CLEAN_RULES = {
    ("MF-M01", "D_eff"): {"min": 1e-15, "max": 1e-5, "reason": "diffusion coefficient must be > 0 and < bulk water D (~2e-9)"},
    ("MF-M01", "D"): {"min": 1e-15, "max": 1e-5, "reason": "diffusion coefficient sanity"},
    ("MF-T01", "k"): {"min": 0.05, "max": 5.0, "reason": "food thermal conductivity (metals 10-400 excluded)"},
    ("MF-T01", "rho"): {"min": 100.0, "max": 2500.0, "reason": "food density (metals 5000-10000 excluded)"},
    ("MF-T01", "Cp"): {"min": 0.5, "max": 5000.0, "reason": "food Cp in J/(kg·K) or kJ/(kg·°C)"},
    ("MF-T02", "T_C"): {"min": -100.0, "max": 250.0, "reason": "food processing temperature range"},
    ("MF-T05", "T_m"): {"min": -50.0, "max": 100.0, "reason": "food melting point (water-based)"},
    ("MF-R05", "Tg"): {"min": -100.0, "max": 300.0, "reason": "glass transition temperature"},
    ("MF-M02", "a_w"): {"min": 0.0, "max": 1.0, "reason": "water activity by definition"},
    ("MF-M04", "pKa"): {"min": -3.0, "max": 16.0, "reason": "pKa physical range"},
}

def main():
    print(f"Loading database: {DB_FILE}")
    db = yaml.safe_load(open(DB_FILE))
    
    # Load records jsonl
    records = []
    with open(RECORDS_FILE) as f:
        for line in f:
            records.append(json.loads(line))
    print(f"Loaded {len(records):,} records")

    # Apply cleaning rules to records
    cleaned_records = []
    dropped = defaultdict(list)
    by_rule = defaultdict(int)

    for r in records:
        key = (r["best_mf"], r["canonical_field"])
        rule = CLEAN_RULES.get(key)
        if rule is None:
            cleaned_records.append(r)
            continue
        v = r.get("value_si")
        if v is None or not isinstance(v, (int, float)):
            cleaned_records.append(r)  # parse already failed; not an outlier issue
            continue
        if v < rule["min"] or v > rule["max"]:
            dropped[f"{key[0]}.{key[1]}"].append({
                "value": v, "unit": r.get("unit_si"),
                "book": r["book"], "page": r.get("page"),
                "parameter_name": r["parameter_name"][:80],
                "reason": rule["reason"],
            })
            by_rule[f"{key[0]}.{key[1]}"] += 1
        else:
            cleaned_records.append(r)

    # Write cleaned records
    with open(CLEAN_RECORDS_FILE, "w") as f:
        for r in cleaned_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Rebuild value DB from cleaned records
    import statistics
    new_db = {}
    by_field = defaultdict(list)
    for r in cleaned_records:
        by_field[(r["best_mf"], r["canonical_field"])].append(r)

    def percentiles(values, qs):
        if not values: return {q: None for q in qs}
        s = sorted(values)
        n = len(s)
        return {q: s[max(0, min(n-1, int(q * n / 100)))] for q in qs}

    for (mf, field), recs in sorted(by_field.items()):
        nums = [r["value_si"] for r in recs if isinstance(r.get("value_si"), (int, float))]
        units = [r["unit_si"] for r in recs if r.get("unit_si")]
        unit = max(set(units), key=units.count) if units else "?"
        books = set(r["book"] for r in recs)
        dist = {}
        if nums:
            ps = percentiles(nums, [5, 25, 50, 75, 95])
            dist = {
                "n_numeric": len(nums),
                "min": float(min(nums)),
                "p5": float(ps[5]) if ps[5] is not None else None,
                "p25": float(ps[25]) if ps[25] is not None else None,
                "median": float(ps[50]) if ps[50] is not None else None,
                "p75": float(ps[75]) if ps[75] is not None else None,
                "p95": float(ps[95]) if ps[95] is not None else None,
                "max": float(max(nums)),
                "mean": float(statistics.mean(nums)),
                "stdev": float(statistics.stdev(nums)) if len(nums) > 1 else 0.0,
            }
        new_db.setdefault(mf, {})[field] = {
            "n_records": len(recs),
            "n_books": len(books),
            "typical_unit_si": unit,
            "distribution_si": dist,
            "sample_records_first_5": [{
                "book": r["book"], "page": r.get("page"), "value": r.get("value"), "unit": r.get("unit"),
                "value_si": r.get("value_si"),
            } for r in recs[:5]],
        }

    output_db = {
        "version": "2.0_clean",
        "generated_at": "2026-05-11",
        "source": "P2-Sa2 outlier-cleaned database (rules-based)",
        "stats": {
            "input_records": len(records),
            "output_records": len(cleaned_records),
            "dropped_records": len(records) - len(cleaned_records),
            "n_mf": len(new_db),
            "n_pairs": sum(len(v) for v in new_db.values()),
        },
        "mf_field_database": new_db,
    }
    CLEAN_FILE.write_text(yaml.safe_dump(output_db, allow_unicode=True, sort_keys=False))

    report = {
        "version": "1.0",
        "rules_applied": {f"{k[0]}.{k[1]}": v for k, v in CLEAN_RULES.items()},
        "summary": {
            "input_records": len(records),
            "output_records_clean": len(cleaned_records),
            "dropped_total": len(records) - len(cleaned_records),
            "dropped_by_rule": dict(by_rule),
        },
        "dropped_samples_by_field": {k: v[:5] for k, v in dropped.items()},
    }
    REPORT_FILE.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))

    print(f"\n✅ Cleaned: {len(cleaned_records):,} records ({len(records) - len(cleaned_records)} dropped)")
    print(f"✅ Wrote {CLEAN_FILE}")
    print(f"✅ Wrote {REPORT_FILE}")
    print()
    print("Dropped by rule:")
    for k, v in sorted(by_rule.items(), key=lambda x: -x[1]):
        print(f"  {k}: {v} records")

if __name__ == "__main__":
    main()
