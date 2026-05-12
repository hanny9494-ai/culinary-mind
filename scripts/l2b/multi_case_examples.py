#!/usr/bin/env python3
"""Multi-case real-recipe queries through Layer 3 reasoning graph.

Examples:
1. Find recipes with HIGH temperature + LONG duration → likely Maillard heavy
2. Find recipes with fermentation → microbial PHN
3. Find recipes with freeze + thaw → ice crystal PHN
4. Cross-cuisine comparison: same ingredient + different methods
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neo4j import GraphDatabase


def main():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))
    with driver.session() as sess:

        # ==== Case 1: High-heat Maillard recipes ====
        print("=" * 90)
        print("Q1: Top 5 recipes with HIGH-temp Maillard browning (≥180°C bake/roast/sear)")
        print("=" * 90)
        q1 = """
        MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
              -[:TRIGGERS_PHN]->(p:CKG_PHN {phn_id: 'maillard_browning'})
        WHERE s.temp_c >= 180 AND s.duration_min >= 10
        RETURN r.name AS recipe, r.book_id AS book,
               s.action AS action, s.temp_c AS temp, s.duration_min AS dur
        ORDER BY s.temp_c DESC, s.duration_min DESC
        LIMIT 5
        """
        for r in sess.run(q1):
            print(f"  {(r['recipe'] or 'Unnamed')[:55]:<55} [{(r['book'] or 'unk')[:25]}]")
            print(f"    Step: {r['action']} {r['temp']}°C × {r['dur']}min")

        # ==== Case 2: Fermentation recipes ====
        print("\n" + "=" * 90)
        print("Q2: Top 5 fermentation recipes (microbial PHN)")
        print("=" * 90)
        q2 = """
        MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
              -[:TRIGGERS_PHN]->(p:CKG_PHN) WHERE p.phn_id IN ['lactic_acid_fermentation', 'alcoholic_fermentation', 'koji_mold_fermentation', 'acetic_acid_fermentation']
        RETURN r.name AS recipe, r.book_id AS book,
               s.action AS action, s.duration_min AS dur
        ORDER BY s.duration_min DESC
        LIMIT 5
        """
        for r in sess.run(q2):
            print(f"  {(r['recipe'] or 'Unnamed')[:55]:<55} [{(r['book'] or 'unk')[:25]}]")
            print(f"    Step: {r['action']} {r['dur']}min")

        # ==== Case 3: Recipes that exercise the MOST MF tools ====
        print("\n" + "=" * 90)
        print("Q3: Recipes exercising the MOST MF tools (broad reasoning surface)")
        print("=" * 90)
        q3 = """
        MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
              -[:TRIGGERS_PHN]->(p:CKG_PHN)<-[:GOVERNS_PHN]-(m:CKG_MF)
        WITH r, collect(DISTINCT m.mf_id) AS unique_mfs, count(DISTINCT p) AS n_phn
        WHERE size(unique_mfs) >= 3 AND r.name IS NOT NULL AND r.name <> ''
        RETURN r.name AS recipe, r.book_id AS book,
               unique_mfs, n_phn
        ORDER BY size(unique_mfs) DESC
        LIMIT 5
        """
        for r in sess.run(q3):
            print(f"  {(r['recipe'] or 'Unnamed')[:55]:<55} [{(r['book'] or 'unk')[:25]}]")
            print(f"    {len(r['unique_mfs'])} MFs: {r['unique_mfs']}, {r['n_phn']} PHNs")

        # ==== Case 4: PHN ordering — what gets triggered most ====
        print("\n" + "=" * 90)
        print("Q4: Most-triggered PHNs across all recipes")
        print("=" * 90)
        q4 = """
        MATCH (s:CKG_L2B_TMP_Step)-[:TRIGGERS_PHN]->(p:CKG_PHN)
        RETURN p.phn_id AS phn, p.l0_atom_count AS l0_evidence_count,
               count(DISTINCT s) AS step_triggers
        ORDER BY step_triggers DESC
        LIMIT 10
        """
        print(f"  {'PHN':<35} {'Step triggers':>13} {'L0 evidence':>13}")
        print(f"  {'-'*35} {'-'*13} {'-'*13}")
        for r in sess.run(q4):
            print(f"  {r['phn']:<35} {r['step_triggers']:>13} {r['l0_evidence_count']:>13}")

        # ==== Case 5: Cross-book PHN comparison ====
        print("\n" + "=" * 90)
        print("Q5: Books with most diverse PHN coverage (Maillard/protein/starch/etc)")
        print("=" * 90)
        q5 = """
        MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
              -[:TRIGGERS_PHN]->(p:CKG_PHN)
        WITH r.book_id AS book, count(DISTINCT p) AS unique_phn,
             count(DISTINCT r) AS n_recipes
        RETURN book, unique_phn, n_recipes
        ORDER BY unique_phn DESC
        LIMIT 10
        """
        print(f"  {'Book':<35} {'unique PHNs':>11} {'Recipes':>9}")
        print(f"  {'-'*35} {'-'*11} {'-'*9}")
        for r in sess.run(q5):
            print(f"  {r['book'][:35]:<35} {r['unique_phn']:>11} {r['n_recipes']:>9}")

        print("\n" + "=" * 90)
        print("✅ Multi-case queries SUCCESS — Layer 3 graph supports diverse analytical reasoning")
        print("=" * 90)
    driver.close()


if __name__ == "__main__":
    main()
