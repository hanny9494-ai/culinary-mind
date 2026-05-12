#!/usr/bin/env python3
"""Demo: Recipe → L2A ingredient → IS_A category → siblings (substitution suggestions).

Real food substitution reasoning through the Layer 1+3 graph.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neo4j import GraphDatabase


def main():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))
    with driver.session() as sess:
        print("=" * 95)
        print("DEMO: Layer 1+3 Ingredient Substitution Reasoning")
        print("=" * 95)

        # Find a real recipe with chicken
        q = """
        MATCH (r:CKG_L2B_TMP_Recipe)-[:USES_L2A_INGREDIENT]->(chicken:CKG_L2A_Ingredient {canonical_id: 'chicken'})
        WHERE r.name IS NOT NULL AND r.name <> ''
        RETURN r.recipe_id AS rid, r.name AS name, r.book_id AS book
        LIMIT 1
        """
        rec = sess.run(q).single()
        print(f"\nRecipe: {rec['name']} ({rec['book']})")

        # Get all L2A ingredients + their IS_A parents
        q2 = """
        MATCH (r:CKG_L2B_TMP_Recipe {recipe_id: $rid})-[:USES_L2A_INGREDIENT]->(i:CKG_L2A_Ingredient)
        OPTIONAL MATCH (i)-[:IS_A]->(parent:CKG_L2A_Ingredient)
        RETURN i.canonical_id AS ingredient,
               i.display_name_en AS name_en,
               collect(DISTINCT parent.canonical_id) AS parents
        ORDER BY i.canonical_id
        """
        print(f"\n--- Ingredients & their categories (IS_A) ---")
        for row in sess.run(q2, rid=rec["rid"]):
            parents = row['parents'] or ['(no IS_A parent)']
            print(f"  {row['name_en'] or row['ingredient']:<35} → {parents}")

        # For chicken specifically, find siblings (substitution candidates)
        q3 = """
        MATCH (chicken:CKG_L2A_Ingredient {canonical_id: 'chicken'})-[:IS_A]->(parent:CKG_L2A_Ingredient)
        OPTIONAL MATCH (sibling:CKG_L2A_Ingredient)-[:IS_A]->(parent)
        WHERE sibling.canonical_id <> 'chicken' AND sibling.tree_status = 'active'
        RETURN parent.canonical_id AS parent,
               parent.display_name_en AS parent_name,
               collect(DISTINCT sibling.display_name_en)[..10] AS siblings
        """
        print(f"\n--- Chicken substitutions via IS_A siblings ---")
        for row in sess.run(q3):
            print(f"\n  Through parent: {row['parent_name']} ({row['parent']})")
            print(f"  Siblings: {row['siblings'][:8]}")

        # Bonus: full reasoning chain for one step of this recipe
        q4 = """
        MATCH (r:CKG_L2B_TMP_Recipe {recipe_id: $rid})-[:HAS_STEP]->(s:CKG_L2B_TMP_Step)
              -[:TRIGGERS_PHN]->(p:CKG_PHN)
        OPTIONAL MATCH (m:CKG_MF)-[:GOVERNS_PHN]->(p)
        WHERE s.temp_c IS NOT NULL
        RETURN s.order AS order, s.action AS action,
               s.temp_c AS temp, s.duration_min AS dur,
               p.phn_id AS phn,
               collect(DISTINCT m.mf_id) AS mfs
        ORDER BY s.order LIMIT 3
        """
        print(f"\n--- Recipe scientific reasoning (Step → PHN → MF) ---")
        for row in sess.run(q4, rid=rec["rid"]):
            print(f"  Step {row['order']}: {row['action']} {row['temp']}°C × {row['dur']}min")
            print(f"    → PHN: {row['phn']}")
            print(f"    → MF tools: {row['mfs']}")

        print(f"\n" + "=" * 95)
        print(f"✅ Layer 1 (24K ingredient tree) + Layer 3 (PHN/MF reasoning) UNIFIED")
        print("=" * 95)
    driver.close()

if __name__ == "__main__":
    main()
