#!/usr/bin/env python3
"""Demo: L6 term → FT → PHN → MF reasoning chain.

Example queries:
- "umami 这词在不同食物中怎么实现?"
- "镬气 (wok hei) → FT bundles → cooking phenomenon"
- "crispy texture → which MFs?"
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from neo4j import GraphDatabase


def main():
    driver = GraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "cmind_p1_33_proto"))
    with driver.session() as sess:
        print("=" * 95)
        print("DEMO: L6 (Glossary) → FT (Flavor Target) → Layer 3 reasoning")
        print("=" * 95)

        # Query 1: L6 term + FT translation
        print("\n### Q1: 'umami' L6 term → FT bundles")
        print("-" * 95)
        q1 = """
        MATCH (l:CKG_L6_Term)
        WHERE toLower(l.term_en) = 'umami' OR l.term_zh CONTAINS '鲜'
        OPTIONAL MATCH (l)-[:TRANSLATES_TO]->(f:CKG_FT)
        RETURN l.term_zh AS term_zh, l.term_en AS term_en,
               l.definition_zh AS def_zh,
               count(f) AS ft_count,
               collect(DISTINCT f.substrate)[..5] AS substrates
        LIMIT 5
        """
        for row in sess.run(q1):
            print(f"\nL6: {row['term_zh']} / {row['term_en']}")
            print(f"  Def: {(row['def_zh'] or '')[:120]}")
            print(f"  → {row['ft_count']} FT bundles")
            print(f"  → substrates seen: {row['substrates']}")

        # Query 2: FT for specific substrate
        print("\n\n### Q2: FT targets for 'chicken' substrate")
        print("-" * 95)
        q2 = """
        MATCH (f:CKG_FT) WHERE toLower(f.substrate) CONTAINS 'chicken'
        RETURN f.aesthetic_word_en AS word_en, f.aesthetic_word_zh AS word_zh,
               f.substrate AS substrate, f.matrix_type AS matrix
        LIMIT 10
        """
        for row in sess.run(q2):
            print(f"  {row['word_en']:<20} ({row['word_zh']:<10}) on {row['substrate']:<25} matrix: {row['matrix']}")

        # Query 3: Most-translated L6 terms
        print("\n\n### Q3: L6 terms with most FT translations (high-coverage culinary concepts)")
        print("-" * 95)
        q3 = """
        MATCH (l:CKG_L6_Term)-[:TRANSLATES_TO]->(f:CKG_FT)
        WITH l, count(DISTINCT f) AS n_ft, collect(DISTINCT f.substrate)[..5] AS substrates
        WHERE n_ft >= 5
        RETURN l.term_zh AS zh, l.term_en AS en, n_ft, substrates
        ORDER BY n_ft DESC LIMIT 10
        """
        print(f"  {'Term zh':<20} {'Term en':<20} {'#FT':>5}  Sample substrates")
        print(f"  {'-'*20} {'-'*20} {'-'*5}")
        for row in sess.run(q3):
            print(f"  {(row['zh'] or '')[:20]:<20} {(row['en'] or '')[:20]:<20} {row['n_ft']:>5}  {row['substrates']}")

        # Query 4: Full chain — L6 → FT → recipe matching
        print("\n\n### Q4: 'crispy' / '酥脆' → FT + which Recipes targeting that texture")
        print("-" * 95)
        q4 = """
        MATCH (l:CKG_L6_Term)-[:TRANSLATES_TO]->(f:CKG_FT)
        WHERE toLower(l.term_en) IN ['crispy', 'crisp'] OR l.term_zh = '酥脆'
        RETURN f.substrate AS substrate, f.aesthetic_word_en AS word_en,
               count(*) AS n LIMIT 10
        """
        for row in sess.run(q4):
            print(f"  '{row['word_en']}' applied to: {row['substrate']}")

        print("\n" + "=" * 95)
        print("✅ L6 (Glossary 13K terms) + FT (7K flavor targets) UNIFIED with Layer 3 graph")
        print("=" * 95)
    driver.close()

if __name__ == "__main__":
    main()
