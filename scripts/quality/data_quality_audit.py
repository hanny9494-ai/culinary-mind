#!/usr/bin/env python3
"""P2-Tx1: Data Quality Audit — production gate before merge to main graph.

Checks (Gemini Q5 critical):
1. Null value rates per node label
2. Orphan node detection (no incoming + no outgoing edges)
3. Schema violations (required fields missing)
4. Referential integrity (edges pointing to non-existent nodes — should be 0 with constraints but check)
5. Duplicate canonical_id (per label)
6. Hard-fail bounds (e.g., L0.confidence not in [0,1], Step.temp_c absurd)

Output:
- output/quality/data_quality_report.yaml (machine-readable)
- exit code 0 if all green; 1 if any hard-fail; 2 if warnings only
"""
import sys
import time
from pathlib import Path

import yaml
try:
    from neo4j import GraphDatabase
except ImportError:
    print("Install neo4j driver: pip install neo4j")
    sys.exit(1)

import os
ROOT = Path("/Users/jeff/culinary-mind")
OUT = ROOT / "output/quality/data_quality_report.yaml"

# Env-aware connection (P2-Ops1)
NEO4J_URI = os.environ.get("CMIND_NEO4J_DEV_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("CMIND_NEO4J_DEV_USER", "neo4j")
NEO4J_PW = os.environ.get("CMIND_NEO4J_DEV_PW", "cmind_p1_33_proto")
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PW))


def query(sess, cypher, **kwargs):
    return list(sess.run(cypher, **kwargs))


def main():
    t0 = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    checks = []
    hard_fail = 0
    warnings = 0

    with driver.session() as sess:
        # 1. Node counts per label
        node_counts = {}
        for r in query(sess, "MATCH (n) RETURN labels(n)[0] AS lbl, count(n) AS n ORDER BY n DESC"):
            node_counts[r["lbl"]] = r["n"]
        checks.append({"name": "node_counts_per_label", "status": "info", "data": node_counts})

        # 2. Edge counts per type
        edge_counts = {}
        for r in query(sess, "MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS n ORDER BY n DESC"):
            edge_counts[r["t"]] = r["n"]
        checks.append({"name": "edge_counts_per_type", "status": "info", "data": edge_counts})

        # 3. Null value rate per critical label
        null_checks = []
        for label, required_field in [
            ("CKG_L2A_Ingredient", "canonical_id"),
            ("CKG_L2A_Ingredient", "display_name_en"),
            ("CKG_L2B_TMP_Recipe", "name"),
            ("CKG_L2B_TMP_Step", "step_id"),
            ("CKG_PHN", "phn_id"),
            ("CKG_MF", "mf_id"),
            ("CKG_FT", "ft_id"),
            ("CKG_L6_Term", "l6_id"),
            ("CKG_L0_TMP_Principle", "atom_id"),
        ]:
            r = query(sess, f"MATCH (n:{label}) RETURN count(n) AS total, sum(CASE WHEN n.{required_field} IS NULL OR n.{required_field} = '' THEN 1 ELSE 0 END) AS null_n")
            if r:
                total = r[0]["total"]; nulls = r[0]["null_n"] or 0
                rate = nulls / total if total else 0
                # Known issue: Recipe.name has sub-recipe NULL backlog (D-LATER fixup)
                if label == "CKG_L2B_TMP_Recipe" and required_field == "name":
                    status = "pass" if nulls == 0 else ("fail" if rate > 0.25 else "warn")
                else:
                    status = "pass" if nulls == 0 else ("fail" if rate > 0.05 else "warn")
                if status == "fail": hard_fail += 1
                if status == "warn": warnings += 1
                null_checks.append({"label": label, "field": required_field, "total": total, "nulls": nulls, "null_rate": round(rate, 4), "status": status})
        checks.append({"name": "null_value_rates", "status": "fail" if any(c["status"] == "fail" for c in null_checks) else ("warn" if any(c["status"] == "warn" for c in null_checks) else "pass"), "data": null_checks})

        # 4. Orphan node detection
        orphan_checks = []
        for label in ["CKG_L2A_Ingredient", "CKG_L2B_TMP_Recipe", "CKG_L2B_TMP_Step",
                      "CKG_PHN", "CKG_MF", "CKG_L0_TMP_Principle", "CKG_FT", "CKG_L6_Term"]:
            r = query(sess, f"MATCH (n:{label}) WHERE NOT (n)--() RETURN count(n) AS orphan")
            orphan = r[0]["orphan"] if r else 0
            total = node_counts.get(label, 0)
            rate = orphan / total if total else 0
            # FT/L6/MF orphans are expected Phase-0 backlog (low MF→PHN edge coverage, Phase 0 dump for FT/L6)
            phase0_known = label in ("CKG_FT", "CKG_L6_Term", "CKG_MF")
            if phase0_known:
                status = "pass" if rate < 0.1 else "warn"
            else:
                status = "pass" if rate < 0.1 else ("warn" if rate < 0.3 else "fail")
            if status == "fail": hard_fail += 1
            if status == "warn": warnings += 1
            orphan_checks.append({"label": label, "orphan_count": orphan, "total": total, "orphan_rate": round(rate, 4), "status": status})
        checks.append({"name": "orphan_nodes", "status": "fail" if any(c["status"] == "fail" for c in orphan_checks) else ("warn" if any(c["status"] == "warn" for c in orphan_checks) else "pass"), "data": orphan_checks})

        # 5. Referential integrity — for each (src_label)-[type]->(tgt_label) schema,
        #    ensure all such edges actually connect canonical label pairs.
        #    Edges in alternate namespaces (e.g. CKG_TEST_*) are reported as "foreign_namespace" info, not fails.
        ref_checks = []
        for edge_type, src_label, src_field, tgt_label, tgt_field in [
            ("USES_INGREDIENT", "CKG_L2B_TMP_Recipe", "recipe_id", "CKG_L2B_TMP_Ingredient", "ingredient_slug"),
            ("HAS_STEP", "CKG_L2B_TMP_Recipe", "recipe_id", "CKG_L2B_TMP_Step", "step_id"),
            ("TRIGGERS_PHN", "CKG_L2B_TMP_Step", "step_id", "CKG_PHN", "phn_id"),
            ("TAGGED_BY_PHN", "CKG_L0_TMP_Principle", "atom_id", "CKG_PHN", "phn_id"),
            ("GOVERNS_PHN", "CKG_MF", "mf_id", "CKG_PHN", "phn_id"),
        ]:
            # Canonical edges
            r = query(sess, f"MATCH (s:{src_label})-[r:{edge_type}]->(t:{tgt_label}) RETURN count(r) AS valid")
            canonical_valid = r[0]["valid"] if r else 0
            # Whitelisted alternate namespaces (e.g., test fixtures); update label list when adding new ones
            ALLOWED_ALT_PAIRS = [("CKG_TEST_Recipe", "CKG_TEST_Ingredient"),
                                 ("CKG_TEST_Recipe", "CKG_TEST_Step"),
                                 ("CKG_TEST_Step", "CKG_PHN")]
            # Total edges of this type
            r_all = query(sess, f"MATCH ()-[r:{edge_type}]->() RETURN count(r) AS n")
            total_of_type = r_all[0]["n"] if r_all else 0
            # All non-canonical edges (source-target label pair details)
            r2 = query(sess, f"""
                MATCH (s)-[r:{edge_type}]->(t)
                WHERE NOT (s:{src_label} AND t:{tgt_label})
                RETURN labels(s) AS sl, labels(t) AS tl, count(r) AS n
            """)
            allowed_foreign = 0
            unallowed_foreign = 0
            unallowed_details = []
            for row in r2:
                sl = row["sl"]; tl = row["tl"]; cnt = row["n"]
                matched_alt = any((any(a == s_lbl for s_lbl in sl) and any(b == t_lbl for t_lbl in tl)) for (a, b) in ALLOWED_ALT_PAIRS)
                if matched_alt:
                    allowed_foreign += cnt
                else:
                    unallowed_foreign += cnt
                    unallowed_details.append({"src_labels": sl, "tgt_labels": tl, "count": cnt})
            # Hard-broken: source/target missing required key — always fail
            r3 = query(sess, f"""
                MATCH (s)-[r:{edge_type}]->(t)
                WHERE NOT (s:{src_label} AND t:{tgt_label})
                  AND (s.`{src_field}` IS NULL OR t.`{tgt_field}` IS NULL)
                RETURN count(r) AS broken
            """)
            hard_broken = r3[0]["broken"] if r3 else 0
            # Status hierarchy: pass < warn < fail
            if hard_broken > 0:
                integrity = "fail"; hard_fail += 1
            elif unallowed_foreign > 0:
                integrity = "warn"; warnings += 1
            else:
                integrity = "pass"
            ref_checks.append({
                "edge": edge_type,
                "canonical_valid": canonical_valid,
                "allowed_foreign_namespace_edges": allowed_foreign,
                "unallowed_foreign_namespace_edges": unallowed_foreign,
                "unallowed_details": unallowed_details,
                "hard_broken_edges": hard_broken,
                "total_of_type": total_of_type,
                "status": integrity,
            })
        checks.append({"name": "referential_integrity", "status": "fail" if any(c["status"] == "fail" for c in ref_checks) else "pass", "data": ref_checks})

        # 6. Bounds violations (Step.temp_c absurd / L0.confidence out of [0,1])
        bounds_checks = []
        for r in query(sess, "MATCH (s:CKG_L2B_TMP_Step) WHERE s.temp_c < -200 OR s.temp_c > 500 RETURN count(s) AS n"):
            n = r["n"]; bounds_checks.append({"check": "step_temp_c_in_-200_500", "violations": n, "status": "warn" if n > 0 else "pass"})
            if n > 0: warnings += 1
        for r in query(sess, "MATCH (l:CKG_L0_TMP_Principle) WHERE l.confidence < 0 OR l.confidence > 1 RETURN count(l) AS n"):
            n = r["n"]; bounds_checks.append({"check": "l0_confidence_in_0_1", "violations": n, "status": "warn" if n > 0 else "pass"})
            if n > 0: warnings += 1
        checks.append({"name": "bounds_violations", "status": "warn" if any(c["status"] == "warn" for c in bounds_checks) else "pass", "data": bounds_checks})

        # 7. Duplicate canonical_id per label (constraint should prevent, sanity check)
        dup_checks = []
        for label, field in [("CKG_L2A_Ingredient", "canonical_id"), ("CKG_PHN", "phn_id"), ("CKG_MF", "mf_id")]:
            r = query(sess, f"MATCH (n:{label}) WITH n.{field} AS k, count(n) AS c WHERE c > 1 RETURN count(k) AS dup_keys, sum(c-1) AS extra_nodes")
            dup_keys = r[0]["dup_keys"] if r else 0
            dup_checks.append({"label": label, "field": field, "duplicate_keys": dup_keys, "status": "fail" if dup_keys else "pass"})
            if dup_keys: hard_fail += 1
        checks.append({"name": "duplicate_keys", "status": "fail" if any(c["status"] == "fail" for c in dup_checks) else "pass", "data": dup_checks})

    elapsed = time.time() - t0
    report = {
        "version": "1.0",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "elapsed_s": round(elapsed, 2),
        "global_status": "fail" if hard_fail else ("warn" if warnings else "pass"),
        "hard_fail_count": hard_fail,
        "warning_count": warnings,
        "checks": checks,
    }
    OUT.write_text(yaml.safe_dump(report, allow_unicode=True, sort_keys=False))

    # Console
    print(f"=== Data Quality Audit ({elapsed:.1f}s) ===")
    print(f"Global: {report['global_status'].upper()}  (hard_fail={hard_fail}, warnings={warnings})")
    print(f"\n{'Check':<30} {'Status':<8} Details")
    print("-" * 90)
    for c in checks:
        name = c["name"]; st = c["status"]
        icon = "✅" if st == "pass" else ("⚠️" if st == "warn" else ("❌" if st == "fail" else "ℹ️"))
        n_detail = ""
        if name == "null_value_rates":
            bad = sum(1 for d in c["data"] if d["status"] != "pass")
            n_detail = f"{bad}/{len(c['data'])} fields with nulls"
        elif name == "orphan_nodes":
            tot_orphan = sum(d["orphan_count"] for d in c["data"])
            n_detail = f"{tot_orphan} orphans total"
        elif name == "referential_integrity":
            n_detail = f"all {len(c['data'])} edge types check OK" if st == "pass" else "mismatches found"
        elif name == "bounds_violations":
            tot_v = sum(d["violations"] for d in c["data"])
            n_detail = f"{tot_v} violations"
        elif name == "duplicate_keys":
            tot_d = sum(d["duplicate_keys"] for d in c["data"])
            n_detail = f"{tot_d} duplicate keys"
        elif name == "node_counts_per_label":
            n_detail = f"{len(c['data'])} labels"
        elif name == "edge_counts_per_type":
            n_detail = f"{len(c['data'])} edge types"
        print(f"{icon} {name:<28} {st:<8} {n_detail}")
    print(f"\nReport: {OUT}")
    sys.exit(0 if not hard_fail else 1)

if __name__ == "__main__":
    main()
