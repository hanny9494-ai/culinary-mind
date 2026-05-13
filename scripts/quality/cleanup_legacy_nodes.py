#!/usr/bin/env python3
"""P2-Rb2: Cleanup legacy un-namespaced nodes (pre-D82 prototype residue).

Targets:
- CKG_Recipe (10 nodes) — pre-D82 prototype recipes, replaced by CKG_L2B_TMP_Recipe
- CKG_Step (49 nodes) — pre-D82, replaced by CKG_L2B_TMP_Step
- CKG_Ingredient (15 nodes) — pre-D82, replaced by CKG_L2B_TMP_Ingredient
- CKG_Equipment (5 nodes) — pre-D82, replaced by CKG_L1_Equipment

Safety:
- DRY-RUN first: report what would be deleted
- Snapshot via P2-Rb1 first
- Edges automatically dropped with DETACH DELETE
"""
import sys
import argparse
from neo4j import GraphDatabase

LEGACY = [
    ("CKG_Recipe", "Pre-D82 prototype, replaced by CKG_L2B_TMP_Recipe"),
    ("CKG_Step", "Pre-D82 prototype, replaced by CKG_L2B_TMP_Step"),
    ("CKG_Ingredient", "Pre-D82 prototype, replaced by CKG_L2B_TMP_Ingredient"),
    ("CKG_Equipment", "Pre-D82 prototype, replaced by CKG_L1_Equipment"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually delete (else dry-run)")
    args = ap.parse_args()

    d = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))
    deleted = 0
    edges_lost = 0
    with d.session() as s:
        print(f"{'Label':<30} {'Nodes':<8} {'Edges':<8} Action")
        print("-" * 80)
        for label, reason in LEGACY:
            r = s.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()
            n = r["n"] if r else 0
            r = s.run(f"MATCH (n:{label})-[e]-() RETURN count(e) AS n").single()
            e = r["n"] if r else 0
            action = "DRY-RUN" if not args.apply else "DELETE"
            print(f"{label:<30} {n:<8} {e:<8} {action}  // {reason}")
            if args.apply and n > 0:
                s.run(f"MATCH (n:{label}) DETACH DELETE n")
                deleted += n
                edges_lost += e
    print(f"\nTotal: {deleted} nodes / {edges_lost} edges {'deleted' if args.apply else 'would be deleted'}")
    if not args.apply:
        print("\nRun with --apply to execute.")

if __name__ == "__main__":
    main()
