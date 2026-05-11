#!/usr/bin/env python3
"""P1-21c-D v2: Aggregate v1 + v2 results. Merge cross-MF rescued items, identify new MF candidates."""
import json
import yaml
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path("/Users/jeff/culinary-mind")
V1_MAP = ROOT / "output/skill_a/param_ontology_map.json"
V2_RAW = ROOT / "output/skill_a/codex_raw_v2"
BOUNDS_FILE = ROOT / "config/solver_bounds.yaml"

OUT_MAP = ROOT / "output/skill_a/param_ontology_map_v2.json"
OUT_REVIEW = ROOT / "output/skill_a/param_ontology_needs_review_v2.jsonl"
OUT_NEW_MF = ROOT / "output/skill_a/new_mf_candidates_v2.jsonl"
OUT_STATS = ROOT / "output/skill_a/param_ontology_stats_v2.yaml"

CONF_AUTO = 0.85

def main():
    # Load 28 MF valid fields
    bounds = yaml.safe_load(open(BOUNDS_FILE))
    valid_by_mf = {mf_id: set(i["name"] for i in mf.get("inputs", [])) | {"no_match"} 
                   for mf_id, mf in bounds["solvers"].items()}

    # Load v1 mapping
    v1 = json.load(open(V1_MAP))

    # Load v2 batches
    v2_files = sorted(p for p in V2_RAW.glob("*.json") if not p.name.endswith(".error.json"))
    print(f"Loading {len(v2_files)} v2 batch files...")
    
    # v2 input: original_mf + parameter_name (was no_match in v1)
    # v2 output: best_mf + canonical_field + confidence + new_mf_candidate

    # Build v2 lookup: (original_mf, parameter_name) → v2 result
    v2_lookup = {}
    for bf in v2_files:
        data = json.loads(bf.read_text())
        inputs = data["input_items"]
        outs = data["raw_output"].get("mappings", [])
        for i, inp in enumerate(inputs):
            if i >= len(outs): continue
            v2_lookup[(inp["original_mf"], inp["parameter_name"])] = outs[i]

    print(f"v2 lookup size: {len(v2_lookup):,}")

    # Merge: for each v1 no_match item, look up v2 and decide
    final_mappings = defaultdict(dict)  # best_mf → {parameter_name: meta}
    needs_review = []
    new_mf_candidates = []
    final_no_match = []

    # Stats counters
    by_origin_mf = defaultdict(lambda: {"v1_auto": 0, "v2_rescued": 0, "v2_new_mf": 0, "v2_still_no_match": 0, "needs_review": 0})
    cross_mf_flow = Counter()  # (orig_mf, best_mf) → count
    rescued_by_target_mf = Counter()
    new_mf_groups = defaultdict(lambda: {"items": 0, "records": 0, "samples": []})

    total_v1_pairs = 0
    v1_auto_total = 0
    v1_review_total = 0

    # Walk v1 mappings (keeping all auto-accepted items as-is)
    for orig_mf, params in v1["mappings"].items():
        for pn, meta in params.items():
            total_v1_pairs += 1
            cf = meta["canonical_field"]
            conf = meta["confidence"]
            occ = meta.get("occurrence_count", 0)

            if cf != "no_match" and conf >= CONF_AUTO:
                # v1 auto-accepted, keep as-is
                final_mappings[orig_mf][pn] = {
                    "canonical_field": cf,
                    "confidence": conf,
                    "source": "v1_auto",
                    "occurrence_count": occ,
                    "sample_value": meta.get("sample_value"),
                    "sample_unit": meta.get("sample_unit"),
                    "alternatives": meta.get("alternatives", []),
                    "reason": meta.get("reason", ""),
                    "unit_hint": meta.get("unit_hint"),
                }
                v1_auto_total += 1
                by_origin_mf[orig_mf]["v1_auto"] += 1
            elif cf != "no_match" and conf < CONF_AUTO:
                # v1 needs review (low confidence on real field)
                needs_review.append({
                    "source": "v1_low_conf",
                    "original_mf": orig_mf,
                    "parameter_name": pn,
                    "v1_canonical_field": cf,
                    "v1_confidence": conf,
                    "occurrence_count": occ,
                    "sample_value": meta.get("sample_value"),
                    "sample_unit": meta.get("sample_unit"),
                })
                v1_review_total += 1
                by_origin_mf[orig_mf]["needs_review"] += 1
            else:  # v1 said no_match → look at v2
                v2 = v2_lookup.get((orig_mf, pn))
                if not v2:
                    # missing v2 result (shouldn't happen)
                    final_no_match.append({"original_mf": orig_mf, "parameter_name": pn, "occurrence_count": occ, "reason": "v2 missing"})
                    by_origin_mf[orig_mf]["v2_still_no_match"] += 1
                    continue

                best_mf = v2.get("best_mf", "no_match")
                best_field = v2.get("canonical_field", "no_match")
                v2_conf = float(v2.get("confidence", 0))
                new_cand = v2.get("new_mf_candidate")

                # Validate best_mf and canonical_field
                if best_mf == "no_match" or best_mf not in valid_by_mf:
                    is_rescued = False
                elif best_field == "no_match" or best_field not in valid_by_mf[best_mf]:
                    is_rescued = False
                else:
                    is_rescued = True

                if is_rescued and v2_conf >= CONF_AUTO:
                    final_mappings[best_mf][pn] = {
                        "canonical_field": best_field,
                        "confidence": v2_conf,
                        "source": "v2_rescued",
                        "original_mf": orig_mf,  # provenance: was originally assigned to this MF
                        "occurrence_count": occ,
                        "sample_value": meta.get("sample_value"),
                        "sample_unit": meta.get("sample_unit"),
                        "reason": v2.get("reason", ""),
                        "unit_hint": v2.get("unit_hint"),
                    }
                    cross_mf_flow[(orig_mf, best_mf)] += occ
                    rescued_by_target_mf[best_mf] += occ
                    by_origin_mf[orig_mf]["v2_rescued"] += 1
                elif is_rescued and v2_conf < CONF_AUTO:
                    needs_review.append({
                        "source": "v2_low_conf",
                        "original_mf": orig_mf,
                        "parameter_name": pn,
                        "v2_best_mf": best_mf,
                        "v2_canonical_field": best_field,
                        "v2_confidence": v2_conf,
                        "occurrence_count": occ,
                        "sample_value": meta.get("sample_value"),
                        "sample_unit": meta.get("sample_unit"),
                    })
                    by_origin_mf[orig_mf]["needs_review"] += 1
                elif new_cand:
                    new_mf_candidates.append({
                        "original_mf": orig_mf,
                        "parameter_name": pn,
                        "candidate_label": new_cand,
                        "v2_confidence": v2_conf,
                        "occurrence_count": occ,
                        "sample_value": meta.get("sample_value"),
                        "sample_unit": meta.get("sample_unit"),
                    })
                    new_mf_groups[new_cand]["items"] += 1
                    new_mf_groups[new_cand]["records"] += occ
                    if len(new_mf_groups[new_cand]["samples"]) < 5:
                        new_mf_groups[new_cand]["samples"].append({"name": pn, "occ": occ, "orig_mf": orig_mf})
                    by_origin_mf[orig_mf]["v2_new_mf"] += 1
                else:
                    final_no_match.append({
                        "original_mf": orig_mf,
                        "parameter_name": pn,
                        "occurrence_count": occ,
                        "sample_value": meta.get("sample_value"),
                        "sample_unit": meta.get("sample_unit"),
                    })
                    by_origin_mf[orig_mf]["v2_still_no_match"] += 1

    # Write outputs
    OUT_MAP.write_text(json.dumps({
        "version": "2.0",
        "generated_at": "2026-05-11",
        "source": "v1 (within-MF) + v2 (cross-MF re-mapping via Codex CLI gpt-5.4)",
        "mappings": dict(final_mappings),
    }, ensure_ascii=False, indent=2))

    with open(OUT_REVIEW, "w", encoding="utf-8") as f:
        for r in needs_review:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    with open(OUT_NEW_MF, "w", encoding="utf-8") as f:
        for r in new_mf_candidates:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Compute record-level totals
    v1_auto_records = sum(meta["occurrence_count"] for params in final_mappings.values() for meta in params.values() if meta.get("source") == "v1_auto")
    v2_rescued_records = sum(meta["occurrence_count"] for params in final_mappings.values() for meta in params.values() if meta.get("source") == "v2_rescued")
    review_records = sum(r.get("occurrence_count", 0) for r in needs_review)
    new_mf_records = sum(r.get("occurrence_count", 0) for r in new_mf_candidates)
    no_match_records = sum(r.get("occurrence_count", 0) for r in final_no_match)

    stats = {
        "version": "2.0",
        "generated_at": "2026-05-11",
        "method": "v1 within-MF Codex mapping + v2 cross-MF re-mapping for v1 no_match items",
        "totals": {
            "v1_pairs_processed": total_v1_pairs,
            "v2_no_match_re-mapped": len(v2_lookup),
            "final_mapped_unique_pairs": sum(len(p) for p in final_mappings.values()),
            "needs_review_pairs": len(needs_review),
            "new_mf_candidate_pairs": len(new_mf_candidates),
            "true_no_match_pairs": len(final_no_match),
        },
        "record_level": {
            "total_records": 26727,
            "v1_auto_accepted": v1_auto_records,
            "v2_rescued_cross_mf": v2_rescued_records,
            "subtotal_mapped_to_28_MF": v1_auto_records + v2_rescued_records,
            "needs_review": review_records,
            "new_mf_candidate": new_mf_records,
            "true_no_match": no_match_records,
            "coverage_pct_28_MF": round((v1_auto_records + v2_rescued_records) * 100 / 26727, 1),
            "coverage_pct_decisive": round((v1_auto_records + v2_rescued_records + new_mf_records + no_match_records) * 100 / 26727, 1),
        },
        "by_origin_mf": dict(by_origin_mf),
        "rescued_by_target_mf": dict(rescued_by_target_mf.most_common()),
        "top_cross_mf_flow": [{"from": k[0], "to": k[1], "records": v} for k, v in cross_mf_flow.most_common(20)],
        "new_mf_candidate_groups": {k: {"items": v["items"], "records": v["records"], "samples": v["samples"]} for k, v in sorted(new_mf_groups.items(), key=lambda x: -x[1]["records"])},
    }
    OUT_STATS.write_text(yaml.safe_dump(stats, allow_unicode=True, sort_keys=False))

    print()
    print("=== V2 FINAL SUMMARY ===")
    print(f"Total v1 pairs:                {total_v1_pairs:>6,}")
    print(f"v1 auto-accepted (real field): {v1_auto_total:>6,} pairs / {v1_auto_records:>6,} records")
    print(f"v2 rescued (cross-MF):         {sum(len([m for m in p.values() if m.get('source')=='v2_rescued']) for p in final_mappings.values()):>6,} pairs / {v2_rescued_records:>6,} records")
    print(f"needs review (combined):       {len(needs_review):>6,} pairs / {review_records:>6,} records")
    print(f"new MF candidate (real but outside 28 MF): {len(new_mf_candidates):>6,} pairs / {new_mf_records:>6,} records")
    print(f"true no_match (noise/error):   {len(final_no_match):>6,} pairs / {no_match_records:>6,} records")
    print()
    print(f"→ Coverage % of 28 MF: {stats['record_level']['coverage_pct_28_MF']}%")
    print()
    print(f"=== Top 10 new MF candidates by records ===")
    for k, v in list(stats["new_mf_candidate_groups"].items())[:10]:
        print(f"  [{v['records']:>4}r / {v['items']:>3}i] {k}")
    print()
    print(f"=== Top 10 cross-MF rescue flows (records) ===")
    for f in stats["top_cross_mf_flow"][:10]:
        print(f"  {f['from']} → {f['to']}: {f['records']:>4} records")

if __name__ == "__main__":
    main()
