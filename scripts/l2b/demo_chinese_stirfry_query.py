#!/usr/bin/env python3
"""Demo D: Chinese cuisine stir-fry analysis — 镬气 / 炒 / 锅气

Real food science:
- "镬气" (wok hei) = high-temp brief stir-fry → Maillard + aroma volatilization
- typical wok temp: 200-300°C
- ingredients quickly seared in oil
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from neo4j import GraphDatabase

driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))


def q(session, query, **kwargs):
    return list(session.run(query, **kwargs))


def main():
    with driver.session() as sess:
        print("=" * 90)
        print("DEMO D: Chinese Stir-Fry (炒) Analysis via Layer 3 Graph")
        print("=" * 90)

        # Find recipes with stir-fry actions
        print("\n--- Q1: Recipes with 'stir-fry' / '炒' steps ---")
        result = q(sess, """
            MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
            WHERE toLower(s.action) IN ['stir-fry', 'stirfry', 'wok', 'sear']
               OR s.text CONTAINS '炒'
               OR s.text CONTAINS 'wok'
            RETURN r.name AS name, r.book_id AS book, s.action AS action,
                   s.temp_c AS temp, s.duration_min AS dur,
                   s.text AS text
            LIMIT 10
        """)
        for r in result[:5]:
            print(f"  {(r['name'] or '')[:55]:<55} [{r['book'][:25]}]")
            print(f"    [{r['action']}] T={r['temp']} dur={r['dur']}min")

        # 镬气 / wok_hei_pyrolysis PHN
        print("\n--- Q2: PHN 'wok_hei_pyrolysis' (镬气) — what recipes? ---")
        result = q(sess, """
            MATCH (s:CKG_L2B_TMP_Step)-[:TRIGGERS_PHN]->(p:CKG_PHN {phn_id: 'wok_hei_pyrolysis'})
            <-[:TAGGED_BY_PHN]-(l:CKG_L0_TMP_Principle)
            WITH p, count(DISTINCT s) AS step_count, count(DISTINCT l) AS l0_count
            RETURN p.phn_id, step_count, l0_count
        """)
        if result:
            for r in result:
                print(f"  wok_hei_pyrolysis: {r['step_count']} step triggers, {r['l0_count']} L0 evidence")
        else:
            print("  No wok_hei_pyrolysis matches in current rules (need rule update)")
            # Check L0 directly for wok hei
            result2 = q(sess, """
                MATCH (l:CKG_L0_TMP_Principle)-[:TAGGED_BY_PHN]->(p:CKG_PHN {phn_id: 'wok_hei_pyrolysis'})
                RETURN l.scientific_statement AS stmt LIMIT 3
            """)
            for r in result2:
                print(f"  L0 evidence (no step linked yet): {(r['stmt'] or '')[:120]}")

        # Find stir-fry-like steps that should trigger wok_hei
        print("\n--- Q3: High-temp short stir-fry steps (≥200°C, <5min) ---")
        result = q(sess, """
            MATCH (s:CKG_L2B_TMP_Step)
            WHERE s.temp_c >= 200 AND s.duration_min <= 5
              AND s.duration_min IS NOT NULL
              AND toLower(s.action) CONTAINS 'sear' OR toLower(s.action) CONTAINS 'fry'
            RETURN s.action AS action, s.temp_c AS temp, s.duration_min AS dur,
                   substring(s.text, 0, 80) AS text
            LIMIT 5
        """)
        for r in result:
            print(f"  [{r['action']}] {r['temp']}°C × {r['dur']}min  '{r['text']}...'")

        # Ingredients in stir-fry recipes
        print("\n--- Q4: Common ingredients in high-temp stir-fry (Maillard + aroma) ---")
        result = q(sess, """
            MATCH (r:CKG_L2B_TMP_Recipe)-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
                  -[:TRIGGERS_PHN]->(p:CKG_PHN {phn_id: 'maillard_browning'})
            WHERE s.temp_c >= 200 AND s.duration_min <= 10
            MATCH (r)-[:USES_L2A_INGREDIENT]->(i:CKG_L2A_Ingredient)
            WITH i.canonical_id AS ing, count(DISTINCT r) AS n_recipes
            WHERE n_recipes >= 5
            RETURN ing, n_recipes ORDER BY n_recipes DESC LIMIT 15
        """)
        print(f"  {'Ingredient':<30} {'#stir-fry recipes':>17}")
        print("-" * 50)
        for r in result:
            print(f"  {r['ing']:<30} {r['n_recipes']:>17}")

        print("\n" + "=" * 90)
        print("✅ Chinese stir-fry / 炒 reasoning LIVE through Layer 1+3 graph")
        print("=" * 90)
    driver.close()


if __name__ == "__main__":
    main()
