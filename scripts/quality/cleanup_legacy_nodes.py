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
import os
import sys
import argparse
from neo4j import GraphDatabase

LEGACY = [
    ("CKG_Recipe", "Pre-D82 prototype, replaced by CKG_L2B_TMP_Recipe"),
    ("CKG_Step", "Pre-D82 prototype, replaced by CKG_L2B_TMP_Step"),
    ("CKG_Ingredient", "Pre-D82 prototype, replaced by CKG_L2B_TMP_Ingredient"),
    ("CKG_Equipment", "Pre-D82 prototype, replaced by CKG_L1_Equipment"),
]

# Namespace labels that indicate a node has been migrated to D82.
# A node with a legacy label AND any D82 label is multi-labeled and must NOT be deleted.
D82_NAMESPACE_PREFIXES = ("CKG_L2A_", "CKG_L2B_", "CKG_L2C_", "CKG_L0_TMP_", "CKG_L1_", "CKG_FT", "CKG_L6_", "CKG_PHN", "CKG_MF", "CKG_TEST_")


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
        # Build the "has only legacy label" filter using D82 namespace prefixes
        # A safe-to-delete node has the legacy label and NO label matching a D82 prefix
        d82_filter_clauses = [f'NOT any(lbl IN labels(n) WHERE lbl STARTS WITH "{pref}")' for pref in D82_NAMESPACE_PREFIXES]
        d82_filter = " AND ".join(d82_filter_clauses)
        for label, reason in LEGACY:
            # Total with legacy label
            r = s.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()
            total_with_label = r["n"] if r else 0
            # Safe-to-delete: legacy-only nodes
            r = s.run(f"MATCH (n:{label}) WHERE {d82_filter} RETURN count(n) AS n").single()
            n = r["n"] if r else 0
            # Edges on safe-to-delete subset
            r = s.run(f"MATCH (n:{label})-[e]-() WHERE {d82_filter} RETURN count(e) AS n").single()
            e = r["n"] if r else 0
            # Protected: multi-labeled with D82 namespace
            protected = total_with_label - n
            action = "DRY-RUN" if not args.apply else "DELETE"
            print(f"{label:<30} {n:<8} {e:<8} {action}  // {reason}  (protected={protected})")
            if args.apply and n > 0:
                s.run(f"MATCH (n:{label}) WHERE {d82_filter} DETACH DELETE n")
                deleted += n
                edges_lost += e
    print(f"\nTotal: {deleted} nodes / {edges_lost} edges {'deleted' if args.apply else 'would be deleted'}")
    if not args.apply:
        print("\nRun with --apply to execute.")

if __name__ == "__main__":
    main()
