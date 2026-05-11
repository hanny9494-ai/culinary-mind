#!/usr/bin/env python3
"""P2-Sa1: Skill A ETL — 9,153 mapped records → per-MF value distribution database.

Reads:
  - output/skill_a/param_ontology_map_v2.json (v1+v2 mapping: pn → (best_mf, canonical_field))
  - output/*/skill_a/results.jsonl × 94 books (raw Skill A records)

Writes:
  - output/skill_a/mf_parameter_value_database.yaml  (distribution stats per (mf, field))
  - output/skill_a/mf_parameter_records.jsonl       (full record-level provenance)
  - output/skill_a/p2_sa1_qc_report.yaml           (QC summary)
"""
import json
import re
import statistics
import yaml
from collections import defaultdict
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
MAP_FILE = ROOT / "output/skill_a/param_ontology_map_v3.json"

OUT_DB = ROOT / "output/skill_a/mf_parameter_value_database.yaml"
OUT_RECORDS = ROOT / "output/skill_a/mf_parameter_records.jsonl"
OUT_QC = ROOT / "output/skill_a/p2_sa1_qc_report.yaml"

# Simple unit normalization (subset of D44 rules from P1-21c)
UNIT_NORMALIZERS = {
    # temperature → °C
    ("K", "kelvin"): lambda v: v - 273.15 if isinstance(v, (int, float)) else None,
    ("°F", "F", "fahrenheit"): lambda v: (v - 32) * 5/9 if isinstance(v, (int, float)) else None,
    # pressure → Pa
    ("kPa",): lambda v: v * 1000 if isinstance(v, (int, float)) else None,
    ("MPa",): lambda v: v * 1e6 if isinstance(v, (int, float)) else None,
    ("bar",): lambda v: v * 1e5 if isinstance(v, (int, float)) else None,
    ("psi",): lambda v: v * 6894.76 if isinstance(v, (int, float)) else None,
    # viscosity → Pa·s
    ("cP", "centipoise", "mPa·s"): lambda v: v / 1000 if isinstance(v, (int, float)) else None,
    # time → s
    ("min", "minute", "minutes"): lambda v: v * 60 if isinstance(v, (int, float)) else None,
    ("h", "hr", "hour", "hours"): lambda v: v * 3600 if isinstance(v, (int, float)) else None,
    ("day", "days"): lambda v: v * 86400 if isinstance(v, (int, float)) else None,
    # mass fraction
    ("%", "percent"): lambda v: v / 100 if isinstance(v, (int, float)) else None,
}

def normalize_unit_value(value, unit):
    """Best-effort numeric + unit normalization. Returns (value_si, unit_si, ok)."""
    if value is None: return None, unit, False
    # Try parse scalar
    if isinstance(value, str):
        s = value.strip()
        m = re.match(r"^[-+]?\d+(\.\d+)?([eE][-+]?\d+)?$", s)
        if m:
            value = float(s)
        else:
            # try range like "30-40" or "[30, 40]"
            m = re.match(r"^\[?\s*([-+]?\d+(?:\.\d+)?)\s*[,\-~–]\s*([-+]?\d+(?:\.\d+)?)\s*\]?$", s)
            if m:
                value = (float(m.group(1)) + float(m.group(2))) / 2
            else:
                return None, unit, False
    if not isinstance(value, (int, float)): return None, unit, False
    if unit:
        u = unit.strip()
        for keys, fn in UNIT_NORMALIZERS.items():
            if u in keys:
                try:
                    out = fn(value)
                    if out is not None:
                        # Return canonical unit
                        canonical = {
                            "K": "°C", "°F": "°C", "F": "°C", "fahrenheit": "°C", "kelvin": "°C",
                            "kPa": "Pa", "MPa": "Pa", "bar": "Pa", "psi": "Pa",
                            "cP": "Pa·s", "centipoise": "Pa·s", "mPa·s": "Pa·s",
                            "min": "s", "minute": "s", "minutes": "s",
                            "h": "s", "hr": "s", "hour": "s", "hours": "s",
                            "day": "s", "days": "s",
                            "%": "fraction", "percent": "fraction",
                        }.get(u, u)
                        return out, canonical, True
                except: pass
    return value, unit, True

def percentiles(values, qs):
    """nearest-rank percentile."""
    if not values: return {q: None for q in qs}
    s = sorted(values)
    n = len(s)
    return {q: s[max(0, min(n-1, int(q * n / 100)))] for q in qs}

def main():
    # Load mapping (from v2 result: best_mf 已存在 mappings 结构中)
    map_data = json.load(open(MAP_FILE))
    # mappings: best_mf → {parameter_name: meta}; meta has canonical_field, source (v1_auto/v2_rescued), original_mf, occurrence_count
    
    # Build lookup: (original_mf or any source_mf, parameter_name) → (best_mf, canonical_field)
    pn_lookup = {}  # (some_mf_for_v1_or_v2, parameter_name) → (best_mf, canonical_field, source)
    for best_mf, params in map_data["mappings"].items():
        for pn, meta in params.items():
            cf = meta["canonical_field"]
            src = meta.get("source", "v1_auto")
            # v1_auto: best_mf == original_mf (same key). v2_rescued: original_mf saved in meta
            if src == "v1_auto":
                pn_lookup[(best_mf, pn)] = (best_mf, cf, "v1_auto")
            elif src in ("v2_rescued", "v3_rule_rescued"):
                orig = meta.get("original_mf")
                if orig:
                    pn_lookup[(orig, pn)] = (best_mf, cf, "v2_rescued")

    print(f"Mapping lookup size: {len(pn_lookup):,}")

    # Now walk Skill A records
    field_records = defaultdict(list)  # (best_mf, canonical_field) → [{value, unit, value_si, unit_si, book, page, ingredient, ...}]
    total_records = 0
    matched = 0
    unmatched = 0
    no_value = 0

    for results_file in sorted(ROOT.glob("output/*/skill_a/results.jsonl")):
        book = results_file.parents[1].name
        with open(results_file, encoding="utf-8") as f:
            for line in f:
                try: r = json.loads(line)
                except: continue
                if r.get("_filtered"): continue
                fid = r.get("formula_id")
                pn = (r.get("parameter_name") or "").strip()
                if not (fid and pn): continue
                total_records += 1

                key = (fid, pn)
                if key not in pn_lookup:
                    unmatched += 1
                    continue
                best_mf, canonical_field, source = pn_lookup[key]
                if canonical_field == "no_match": continue  # shouldn't happen since we filter
                matched += 1
                value = r.get("value")
                unit = r.get("unit") or ""
                v_si, u_si, ok = normalize_unit_value(value, unit)
                if not ok or v_si is None:
                    no_value += 1
                rec = {
                    "book": book,
                    "page": r.get("_page") or (r.get("source") or {}).get("page"),
                    "value": value,
                    "unit": unit,
                    "value_si": v_si,
                    "unit_si": u_si,
                    "value_ok": ok,
                    "parameter_name": pn,
                    "original_mf": fid,
                    "best_mf": best_mf,
                    "canonical_field": canonical_field,
                    "mapping_source": source,
                    "confidence": r.get("confidence"),
                    "ingredient": (r.get("conditions") or {}).get("substrate") or (r.get("conditions") or {}).get("ingredient"),
                    "causal_context": r.get("causal_context"),
                }
                field_records[(best_mf, canonical_field)].append(rec)

    # Aggregate distributions
    db = {}
    for (mf, field), recs in sorted(field_records.items()):
        nums = [r["value_si"] for r in recs if r["value_si"] is not None and isinstance(r["value_si"], (int, float))]
        # bucket SI unit (most common)
        units_si = [r["unit_si"] for r in recs if r["unit_si"]]
        most_common_unit = max(set(units_si), key=units_si.count) if units_si else "?"
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
        db.setdefault(mf, {})[field] = {
            "n_records": len(recs),
            "n_books": len(books),
            "typical_unit_si": most_common_unit,
            "distribution_si": dist,
            "v1_auto_count": sum(1 for r in recs if r["mapping_source"] == "v1_auto"),
            "v2_rescued_count": sum(1 for r in recs if r["mapping_source"] == "v2_rescued"),
            "sample_records_first_5": [{
                "book": r["book"], "page": r["page"], "value": r["value"], "unit": r["unit"],
                "value_si": r["value_si"], "ingredient": r.get("ingredient"),
                "parameter_name": r["parameter_name"][:80],
            } for r in recs[:5]],
        }

    output_db = {
        "version": "1.0",
        "generated_at": "2026-05-11",
        "source": "P2-Sa1 ETL: Skill A 26,727 records → MF value database (via P1-21c-D ontology map v2)",
        "stats": {
            "total_skill_a_records": total_records,
            "mapped_records_loaded": matched,
            "unmapped_records_dropped": unmatched,
            "value_parse_failed": no_value,
            "n_mf_with_data": len(db),
            "n_unique_mf_field_pairs": sum(len(v) for v in db.values()),
        },
        "mf_field_database": db,
    }
    OUT_DB.parent.mkdir(parents=True, exist_ok=True)
    OUT_DB.write_text(yaml.safe_dump(output_db, allow_unicode=True, sort_keys=False))
    print(f"✅ Wrote MF value database: {OUT_DB}")

    # Write record-level jsonl
    with open(OUT_RECORDS, "w", encoding="utf-8") as f:
        for (mf, field), recs in sorted(field_records.items()):
            for r in recs:
                r["mf_field_key"] = f"{mf}.{field}"
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"✅ Wrote record-level jsonl: {OUT_RECORDS} ({matched} records)")

    # QC report
    qc = {
        "version": "1.0",
        "p1_exit_check": "skill_a_param_ontology_mapped >= 95% → PASS (P1-21c-D)",
        "p2_sa1_stats": output_db["stats"],
        "coverage_by_mf": {mf: sum(v["n_records"] for v in fields.values()) for mf, fields in sorted(db.items())},
        "top_10_field_records": sorted(
            [(mf, f, v["n_records"]) for mf, fields in db.items() for f, v in fields.items()],
            key=lambda x: -x[2]
        )[:10],
        "qc_flags": {
            "any_field_with_zero_numeric": [(mf, f) for mf, fields in db.items() for f, v in fields.items() if v["distribution_si"].get("n_numeric", 0) == 0],
            "any_field_with_extreme_stdev": [(mf, f, v["distribution_si"]["stdev"]) for mf, fields in db.items() for f, v in fields.items() if v["distribution_si"].get("stdev", 0) > 1e6][:10],
        },
    }
    OUT_QC.write_text(yaml.safe_dump(qc, allow_unicode=True, sort_keys=False))
    print(f"✅ Wrote QC report: {OUT_QC}")

    print()
    print("=== SUMMARY ===")
    for k, v in output_db["stats"].items():
        print(f"  {k}: {v}")
    print()
    print("=== Top 10 (mf, field) by record count ===")
    for mf, f, n in qc["top_10_field_records"]:
        d = db[mf][f]["distribution_si"]
        u = db[mf][f]["typical_unit_si"]
        if d:
            print(f"  {mf}.{f:<20} n={n:>4}  range=[{d.get('p5','?')!s:<8}, {d.get('p95','?')!s:<8}] {u}  median={d.get('median','?')!s}")
        else:
            print(f"  {mf}.{f:<20} n={n:>4}  (no numeric distribution)")

if __name__ == "__main__":
    main()
